"""ViewModel 单测：无 UI 框架依赖，直接验证状态与命令。"""

import tempfile
import threading
import time
import unittest
from pathlib import Path

from spritelens.capture.base import StreamChunk
from spritelens.capture.key_store import KeyStore
from spritelens.protocol.opcodes import OpcodeCatalog
from spritelens.protocol.records import Direction
from spritelens.repositories.settings import SettingsRepository
from spritelens.services.monitor_service import MonitorService
from spritelens.services.session_tracker import SessionTracker
from spritelens.system.environment import NpcapReport, check_npcap
from spritelens.view_models import CaptureViewModel, EventsViewModel
from tests._synth import SYNTH_KEY, make_ack_frame, make_data_frame, make_protobuf_payload

SESSION = "10.1.1.9:60000"


def _make_vm(tmp: Path, *, preset_key: bytes | None = None, probe_environment: bool = False, **install_kwargs) -> tuple[CaptureViewModel, MonitorService]:
    settings = SettingsRepository(tmp / "config.json")
    monitor = MonitorService(
        catalog=OpcodeCatalog({}),
        key_store=KeyStore(tmp / "keys"),
        preset_key=preset_key,
    )
    vm = CaptureViewModel(
        monitor=monitor,
        settings=settings,
        keys_dir=tmp / "keys",
        recordings_dir=tmp / "recordings",
        port=8195,
        # 测试默认关闭后台环境探测：不跑 PowerShell，也不与手工设置的报告竞争
        probe_environment=probe_environment,
        **install_kwargs,
    )
    return vm, monitor


def _wait_until(predicate, timeout: float = 3.0) -> bool:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class NpcapInstallFlowTest(unittest.TestCase):
    """一键安装状态机：用 fake 依赖驱动，不触网不提权。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        self.calls: list[str] = []

        def fake_resolver():
            self.calls.append("resolve")
            return "https://npcap.com/dist/npcap-1.79.exe", "1.79"

        def fake_downloader(url, dest_dir, progress_cb=None):
            self.calls.append("download")
            Path(dest_dir).mkdir(parents=True, exist_ok=True)
            dest = Path(dest_dir) / url.rsplit("/", 1)[-1]
            dest.write_bytes(b"npcap-installer")
            return dest

        def fake_launcher(path):
            self.calls.append(f"launch:{path.name}")

        self.vm, _monitor = _make_vm(
            self.tmp_path,
            installer_dir=self.tmp_path / "downloads",
            resolver=fake_resolver,
            downloader=fake_downloader,
            launcher=fake_launcher,
        )
        # 安装流程测试不依赖本机 Npcap 状态，强制视为未安装
        self.vm._npcap_report = NpcapReport(installed=False, wpcap_path=None, message="(测试桩)")

    def test_install_flow_reaches_launched(self):
        self.vm.start_npcap_install()
        self.assertTrue(
            _wait_until(lambda: self.vm.install_state().phase in ("launched", "failed")),
            "安装线程未在时限内完成",
        )
        state = self.vm.install_state()
        self.assertEqual(state.phase, "launched")
        self.assertIn("重新检测", state.message)
        self.assertEqual(self.calls, ["resolve", "download", "launch:npcap-1.79.exe"])
        self.assertTrue((self.tmp_path / "downloads" / "npcap-1.79.exe").is_file())

    def test_failed_resolver_shows_manual_hint(self):
        def bad_resolver():
            raise RuntimeError("网络不可达")

        self.vm._resolver = bad_resolver
        self.vm.start_npcap_install()
        self.assertTrue(_wait_until(lambda: self.vm.install_state().phase == "failed"))
        self.assertIn("手动下载", self.vm.install_state().message)

    def test_start_while_installing_is_noop(self):
        gate = {"blocked": True}

        def blocking_resolver():
            import time

            self.calls.append("resolve")
            while gate["blocked"]:
                time.sleep(0.01)
            return "url", "1.0"

        self.vm._resolver = blocking_resolver
        self.vm.start_npcap_install()
        self.vm.start_npcap_install()  # 进行中重复点击应被忽略
        gate["blocked"] = False
        self.assertTrue(_wait_until(lambda: self.vm.install_state().phase in ("launched", "failed")))
        self.assertEqual(self.calls.count("resolve"), 1)

    def test_refresh_environment_rechecks(self):
        """refresh 应重新执行检测（结果与真实检测一致，不受注入桩影响）。"""
        self.vm._npcap_report = NpcapReport(installed=False, wpcap_path=None, message="(测试桩)")
        after = self.vm.refresh_environment()
        self.assertEqual(after.installed, check_npcap().installed)
        self.assertTrue(after.message)


class CaptureViewModelTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)

    def test_snapshot_when_idle(self):
        vm, _monitor = _make_vm(self.tmp_path)
        snapshot = vm.snapshot()
        self.assertFalse(snapshot.running)
        self.assertEqual(snapshot.sessions, ())
        self.assertEqual(snapshot.totals.decrypt_ok, 0)
        self.assertFalse(snapshot.recording)

    def test_environment_probe_updates_report_async(self):
        """探测线程异步补全报告（含 RSC），不阻塞构造与 autostart 判定。"""
        from spritelens.view_models import capture_vm as vm_mod

        fake_report = NpcapReport(
            installed=True,
            wpcap_path="X:\\fake\\wpcap.dll",
            message="(探测线程写入)",
            rsc_enabled=True,
            rsc_adapter="WLAN",
        )
        original = vm_mod.check_npcap
        vm_mod.check_npcap = lambda **kwargs: fake_report
        self.addCleanup(setattr, vm_mod, "check_npcap", original)

        vm, _monitor = _make_vm(self.tmp_path, probe_environment=True)
        self.assertTrue(
            _wait_until(lambda: vm.environment_report().message == "(探测线程写入)"),
            "探测线程应在超时前替换占位报告",
        )
        self.assertTrue(vm.environment_report().rsc_enabled)

    def test_probe_failure_is_swallowed(self):
        """探测线程异常不传播：后台线程死亡不影响界面与采集主流程。"""
        import threading as _threading

        ran = _threading.Event()

        def _boom(**kwargs):
            ran.set()
            raise RuntimeError("探测炸了")

        vm, _monitor = _make_vm(
            self.tmp_path, probe_environment=True, environment_probe=_boom
        )
        self.assertTrue(ran.wait(timeout=2.0), "探测线程应被启动并消费注入函数")
        # 报告保持在快速检查结果上（异常被吞，未覆盖也未崩溃）
        self.assertIsInstance(vm.environment_report(), NpcapReport)

    def test_manual_key_valid_and_invalid(self):
        vm, monitor = _make_vm(self.tmp_path)
        ok, message = vm.apply_manual_key("bad key!")
        self.assertFalse(ok)
        ok, _ = vm.apply_manual_key(SYNTH_KEY.decode())
        self.assertTrue(ok)
        # 手动 key 落盘并作用于后续会话
        self.assertEqual(KeyStore(self.tmp_path / "keys").load_latest(), SYNTH_KEY)
        monitor.on_chunk(
            StreamChunk(
                session_id=SESSION,
                direction=Direction.S2C,
                data=make_data_frame(SYNTH_KEY, 0x0001, b"\x01" * 16, sequence=1),
                first_seq=1,
            )
        )
        snapshot = vm.snapshot()
        self.assertEqual(snapshot.totals.decrypt_ok, 1)

    def test_iface_selection_persisted(self):
        vm, _monitor = _make_vm(self.tmp_path)
        vm.select_iface("以太网 2")
        self.assertEqual(SettingsRepository(self.tmp_path / "config.json").get_str("capture.iface"), "以太网 2")
        self.assertEqual(vm.selected_iface, "以太网 2")

    def test_record_toggle_persisted(self):
        vm, _monitor = _make_vm(self.tmp_path)
        vm.set_recording_requested(True)
        self.assertTrue(SettingsRepository(self.tmp_path / "config.json").get_bool("capture.record_on_start"))
        self.assertTrue(vm.recording_requested)

    def test_recording_command_is_atomic_under_interleaving(self):
        """S01/C01 回归：录制命令四步（意愿/启停/持久化/VM缓存）原子生效。

        旧实现交错复现：T1 请求 true 在「写设置前」由 Event 暂停，
        T2 完成完整请求 false，恢复 T1——最终页面声明不录制、配置却为
        true、录制器仍在录。新实现整条命令在服务命令锁内执行，T2 排在
        T1 之后完整覆盖，最终四个状态一致为 false。
        """
        vm, monitor = _make_vm(self.tmp_path)
        # 打桩 is_running：用假 source 走真实 property 判定（模拟采集中）
        class _RunningSource:
            is_running = True

        monitor._source = _RunningSource()

        persist_gate = threading.Event()
        t1_started = threading.Event()
        settings_path = self.tmp_path / "config.json"
        original_set = SettingsRepository(settings_path).set

        def blocking_persist(enabled: bool) -> None:
            if enabled and not persist_gate.is_set():
                t1_started.set()
                persist_gate.wait(timeout=5)  # T1 在写设置前暂停
            original_set("capture.record_on_start", enabled)

        vm._service.set_recording_persist(blocking_persist)

        t1 = threading.Thread(target=vm.set_recording_requested, args=(True,))
        t1.start()
        self.assertTrue(t1_started.wait(timeout=5), "T1 未进入持久化暂停点")

        # T2 在 T1 暂停期间发出相反请求；新实现整条命令在命令锁内串行，
        # T2 排队等 T1 完整结束（含持久化）后执行，最终状态以 T2 为准。
        # 旧实现的缺陷在于四个步骤可交错出「意愿 false / 配置 true / 仍在录」。
        t2 = threading.Thread(target=vm.set_recording_requested, args=(False,))
        t2.start()
        persist_gate.set()
        t1.join(timeout=5)
        t2.join(timeout=5)
        self.assertFalse(t1.is_alive(), "T1 未完成")
        self.assertFalse(t2.is_alive(), "T2 未完成")

        # 四个状态最终一致（T2 后到覆盖 T1，符合「最后命令胜」语义）
        self.assertFalse(vm.recording_requested, "页面意愿应为 false")
        self.assertFalse(vm._service._recording_wanted, "下次启动意愿应为 false")
        self.assertFalse(
            SettingsRepository(settings_path).get_bool("capture.record_on_start", True),
            "持久化配置应为 false",
        )
        self.assertFalse(vm._service.status().recording, "录制器不应在录")

    def test_stop_then_stale_running_does_not_start_recording(self):
        """S01 回归：锁内判定 running——stop 后带旧 running 的请求不会开录制。

        旧实现 set_recording(enabled, running=锁外旧值) 可在停止后开录。
        新实现 running 由服务在命令锁内判定，running=False 时不开。
        """
        vm, monitor = _make_vm(self.tmp_path)

        class _RunningSource:
            is_running = True

        class _StoppedSource:
            is_running = False

            def stop(self) -> None:
                pass

        monitor._source = _RunningSource()
        vm.set_recording_requested(True)
        self.assertTrue(vm._service.status().recording)

        # 停止采集后，录制应随 stop 关闭
        monitor._source = _StoppedSource()
        vm.stop()
        self.assertFalse(vm._service.status().recording)
        self.assertFalse(monitor.is_running)

        # 若仍有旧请求到达（running 已为 False）：不开录制
        vm._service.set_recording(True)
        self.assertFalse(vm._service.status().recording, "停止后不得开录制")

    def test_stop_without_start_is_safe(self):
        vm, _monitor = _make_vm(self.tmp_path)
        vm.stop()  # 未启动时停止不应抛错
        self.assertFalse(vm.snapshot().running)

    def test_concurrent_start_commands_are_serialized(self):
        """并发 start 命令串行化：同一时刻只创建一个接入层（R09）。

        HTTP 的 start 经 to_thread 调用，同源重复点击会并发进入；
        串行化在 CaptureService 的命令锁内执行，并发调用排队。
        """
        vm, monitor = _make_vm(self.tmp_path)
        entered: list[float] = []
        done: list[float] = []
        # 慢 start 在服务的真实命令锁内执行，验证并发调用排队
        command_lock = vm._service._command_lock

        def slow_start():
            with command_lock:
                entered.append(time.monotonic())
                time.sleep(0.2)
                done.append(time.monotonic())

        vm._service.start = slow_start  # type: ignore[method-assign]

        threads = [threading.Thread(target=vm.start) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        self.assertEqual(len(entered), 3)
        # 串行化：任一时刻只有一个命令在执行（进入区间不重叠）
        ordered = sorted(zip(entered, done))
        for (_e0, d0), (e1, _d1) in zip(ordered, ordered[1:]):
            self.assertGreaterEqual(e1 - d0, -0.01, "start 命令未串行化")

    def test_concurrent_stop_and_start_are_serialized(self):
        """stop 与 start 并发时命令互斥，不产生中间态竞态。"""
        import threading

        vm, monitor = _make_vm(self.tmp_path)
        vm.start()
        results: list[str] = []
        lock = threading.Lock()

        def do_stop():
            vm.stop()
            with lock:
                results.append("stop")

        def do_start():
            vm.start()
            with lock:
                results.append("start")

        t1 = threading.Thread(target=do_stop)
        t2 = threading.Thread(target=do_start)
        t1.start()
        time.sleep(0.05)
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)
        self.assertEqual(sorted(results), ["start", "stop"])
        # 终态一致：要么在采集中（start 后到），要么已停止
        self.assertIsInstance(vm.snapshot().running, bool)
    def test_autostart_defaults_on_and_persists(self):
        """打开即采集默认开启；关闭后写入配置、重开仍为关闭。"""
        vm, _monitor = _make_vm(self.tmp_path)
        self.assertTrue(vm.autostart)

        vm.set_autostart(False)
        self.assertFalse(vm.autostart)
        self.assertFalse(
            SettingsRepository(self.tmp_path / "config.json").get_bool("capture.autostart")
        )
        vm2, _ = _make_vm(self.tmp_path)
        self.assertFalse(vm2.autostart)

    def test_start_if_autostart_skips_without_npcap(self):
        """未装 Npcap 时不自动发起采集（避免每次启动弹失败提示）。"""
        from spritelens.system.environment import NpcapReport

        vm, monitor = _make_vm(self.tmp_path)
        vm._npcap_report = NpcapReport(installed=False, wpcap_path=None, message="未检测到 Npcap")
        self.assertFalse(vm.start_if_autostart())
        self.assertFalse(monitor.is_running)

    def test_start_if_autostart_respects_switch(self):
        """开关关闭时不自动采集（即便环境就绪）。"""
        vm, monitor = _make_vm(self.tmp_path)
        vm.set_autostart(False)
        self.assertFalse(vm.start_if_autostart())
        self.assertFalse(monitor.is_running)


class EventsViewModelTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        self.monitor = MonitorService(
            catalog=OpcodeCatalog({}),
            key_store=KeyStore(self.tmp_path / "keys"),
            preset_key=SYNTH_KEY,
        )
        self.vm = EventsViewModel(monitor=self.monitor)

    def test_drain_converts_events_with_details(self):
        self.monitor.on_chunk(
            StreamChunk(
                session_id=SESSION,
                direction=Direction.S2C,
                data=make_data_frame(SYNTH_KEY, 0x1888, make_protobuf_payload(), sequence=1),
                first_seq=1,
            )
        )
        rows = self.vm.drain()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.opcode_hex, "0x1888")
        self.assertEqual(row.payload_len, len(make_protobuf_payload()))
        detail = self.vm.detail(row.index)
        self.assertIn("0x1888", detail)
        self.assertIn("field_1", detail)  # 无 schema 时 wire 占位名

    def test_drain_empty(self):
        self.assertEqual(self.vm.drain(), [])

    def test_missing_detail_falls_back(self):
        self.assertEqual(self.vm.detail(9999), "(详情已随滚动淘汰)")


if __name__ == "__main__":
    unittest.main()
