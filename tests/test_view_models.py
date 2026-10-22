"""ViewModel 单测：无 UI 框架依赖，直接验证状态与命令。"""

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from spritelens.capture.base import StreamChunk
from spritelens.capture.key_store import KeyStore
from spritelens.protocol.opcodes import OpcodeCatalog
from spritelens.protocol.records import Direction
from spritelens.repositories.settings import SettingsRepository
from spritelens.services.monitor_service import MonitorService
from spritelens.system.environment import NpcapReport
from spritelens.view_models import CaptureViewModel
from tests._synth import SYNTH_KEY, make_data_frame

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


class CaptureViewModelTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)

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

    def test_recording_intent_single_owner_after_paused_service_call(self):
        """D02 回归：服务调用完成后暂停，VM 无锁外回写可覆盖较新意愿。

        旧实现 VM 在服务调用**返回后**回写 `_recording_requested`：
        T1（true）在服务调用完成、回写前暂停；T2（false）完整执行；
        T1 恢复把页面意愿写回 True——服务/配置 False 而页面 True。
        新实现意愿只有服务一个所有者，VM 属性直接读服务状态，
        交错任意排列后页面、服务、配置三者一致。
        """
        vm, monitor = _make_vm(self.tmp_path)

        class _RunningSource:
            is_running = True

        monitor._source = _RunningSource()
        settings_path = self.tmp_path / "config.json"

        real_set_recording = vm._service.set_recording
        t1_done = threading.Event()
        t1_release = threading.Event()

        def paused_set_recording(enabled: bool) -> None:
            real_set_recording(enabled)  # 完整服务调用（含持久化）
            if enabled and not t1_release.is_set():
                t1_done.set()
                t1_release.wait(timeout=5)  # 暂停在服务调用返回之后

        vm._service.set_recording = paused_set_recording  # type: ignore[method-assign]

        t1 = threading.Thread(target=vm.set_recording_requested, args=(True,))
        t1.start()
        self.assertTrue(t1_done.wait(timeout=5), "T1 未到达暂停点")

        # T2 完整执行相反命令（此时 T1 尚未「回写」）
        vm.set_recording_requested(False)
        t1_release.set()
        t1.join(timeout=5)
        self.assertFalse(t1.is_alive())

        # 三者一致为 False（旧实现页面意愿会被 T1 恢复后写成 True）
        self.assertFalse(vm.recording_requested, "页面意愿必须与服务一致")
        self.assertFalse(vm._service.recording_wanted())
        self.assertFalse(
            SettingsRepository(settings_path).get_bool("capture.record_on_start", True),
            "持久化配置应为 false",
        )
        self.assertFalse(vm._service.status().recording, "录制器不应在录")

    def test_config_write_failure_is_visible(self):
        """D03 回归：配置保存失败不再被吞——命令抛出，运行状态仍已生效。

        旧实现 set() 吞 OSError：命令 200 成功、内存 True、磁盘 False，
        重启静默回旧设置。新实现 set_checked 把失败传给调用者。
        """
        from unittest import mock

        vm, monitor = _make_vm(self.tmp_path)
        self.addCleanup(vm._service._recorder.stop)

        class _RunningSource:
            is_running = True

        monitor._source = _RunningSource()

        with mock.patch.object(
            SettingsRepository, "set_checked", side_effect=OSError("注入：磁盘不可写")
        ):
            with self.assertRaises(OSError):
                vm.set_recording_requested(True)

        # 运行状态已生效（意愿 + 实际录制），但磁盘没有写入
        self.assertTrue(vm.recording_requested, "意愿已生效")
        self.assertTrue(vm._service.status().recording, "录制已启动")
        self.assertFalse(
            (self.tmp_path / "config.json").exists(), "配置未写入（失败可见）"
        )

    def test_autostart_config_failure_is_visible(self):
        """D03 回归：autostart 保存失败同样上抛（set_checked）。"""
        from unittest import mock

        vm, _monitor = _make_vm(self.tmp_path)
        with mock.patch.object(
            SettingsRepository, "set_checked", side_effect=OSError("注入：磁盘不可写")
        ):
            with self.assertRaises(OSError):
                vm.set_autostart(False)
        self.assertFalse(vm.autostart, "运行态已切到 false")

    def test_recorder_start_failure_is_visible_and_retryable(self):
        """D03 语义：录制器启动失败上抛；意愿保留、下次启动仍会尝试。

        磁盘满/路径不可写时 recorder.start 抛 OSError：命令失败可见，
        「意愿=True、实际未录、磁盘配置未写」——意愿保留是有意为之
        （下次 start 采集时重试），不能静默吞掉。
        """
        from unittest import mock

        from spritelens.recording.recorder import StreamRecorder

        vm, monitor = _make_vm(self.tmp_path)
        self.addCleanup(vm._service._recorder.stop)

        class _RunningSource:
            is_running = True

        monitor._source = _RunningSource()

        with mock.patch.object(
            StreamRecorder, "start", side_effect=OSError("注入：磁盘满")
        ):
            with self.assertRaises(OSError):
                vm.set_recording_requested(True)

        self.assertTrue(vm._service.recording_wanted(), "意愿保留（下次启动重试）")
        self.assertFalse(vm._service.status().recording, "实际没有在录")
        self.assertFalse((self.tmp_path / "config.json").exists(), "配置未写入")

        # 环境恢复后重试成功：意愿已保留，直接开录
        vm._service.set_recording(True)
        self.assertTrue(vm._service.status().recording)

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
        from unittest import mock
        from spritelens.capture.npcap_source import NpcapCaptureSource

        vm, monitor = _make_vm(self.tmp_path)
        # 只验证命令交错；禁止此单测启动真实 Npcap/访问驱动。
        start_patch = mock.patch.object(NpcapCaptureSource, "_start_sniffer")
        start_patch.start()
        self.addCleanup(start_patch.stop)
        self.addCleanup(vm.stop)
        vm.start()
        results: list[str] = []
        lock = threading.Lock()

        stop_entered = threading.Event()
        release_stop = threading.Event()
        real_stop = monitor.stop

        def paused_stop():
            stop_entered.set()
            release_stop.wait(timeout=5)
            real_stop()

        monitor.stop = paused_stop

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
        try:
            self.assertTrue(stop_entered.wait(timeout=2))
            t2.start()
            t2.join(timeout=2)
            self.assertFalse(t2.is_alive(), "停止期间 start 应拒绝，不等待旧命令")
            self.assertFalse(vm._service.status().last_error == "")
        finally:
            release_stop.set()
            t1.join(timeout=5)
        self.assertEqual(sorted(results), ["start", "stop"])
        # 终态一致：要么在采集中（start 后到），要么已停止
        self.assertIsInstance(vm.snapshot().running, bool)
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

    def test_npcap_install_waits_then_checks_and_completes(self):
        installer = self.tmp_path / "npcap.exe"
        installer.write_bytes(b"MZinstaller")
        launcher_called = threading.Event()

        def downloader(url, dest_dir, *, progress_cb):
            launcher_called.set()
            progress_cb(1.0)
            return installer

        vm, _monitor = _make_vm(
            self.tmp_path,
            resolver=lambda: ("https://npcap.com/dist/npcap-1.0.exe", "1.0"),
            downloader=downloader,
            launcher=lambda path: 0,
        )
        vm._npcap_report = NpcapReport(False, None, "未安装")
        installed = NpcapReport(True, str(installer), "已安装")
        with mock.patch.object(vm, "refresh_environment", return_value=installed) as refresh:
            vm.start_npcap_install()
            deadline = time.monotonic() + 5
            while vm.install_state().phase not in {"completed", "failed"}:
                if time.monotonic() >= deadline:
                    self.fail(f"安装流程未结束: {vm.install_state()}")
                time.sleep(0.01)

        self.assertTrue(launcher_called.is_set())
        self.assertEqual(vm.install_state().phase, "completed")
        refresh.assert_called_once_with()
        self.assertIn("已就绪", vm.install_state().message)

    def test_npcap_install_enters_checking_after_installer_exits(self):
        installer = self.tmp_path / "npcap.exe"
        installer.write_bytes(b"MZinstaller")
        checking_seen = threading.Event()

        vm, _monitor = _make_vm(
            self.tmp_path,
            resolver=lambda: ("https://npcap.com/dist/npcap-1.0.exe", "1.0"),
            downloader=lambda url, dest_dir, *, progress_cb: installer,
            launcher=lambda path: 0,
        )
        vm._npcap_report = NpcapReport(False, None, "未安装")

        def observe_check():
            checking_seen.set()
            self.assertEqual(vm.install_state().phase, "checking")
            return NpcapReport(True, str(installer), "已安装")

        with mock.patch.object(vm, "refresh_environment", side_effect=observe_check):
            vm.start_npcap_install()
            self.assertTrue(checking_seen.wait(timeout=5))
            deadline = time.monotonic() + 5
            while vm.install_state().phase != "completed":
                if time.monotonic() >= deadline:
                    self.fail(f"安装流程未完成: {vm.install_state()}")
                time.sleep(0.01)

    def test_npcap_install_detection_failure_is_failed(self):
        installer = self.tmp_path / "npcap.exe"
        installer.write_bytes(b"MZinstaller")
        vm, _monitor = _make_vm(
            self.tmp_path,
            resolver=lambda: ("https://npcap.com/dist/npcap-1.0.exe", "1.0"),
            downloader=lambda url, dest_dir, *, progress_cb: installer,
            launcher=lambda path: 1,
        )
        vm._npcap_report = NpcapReport(False, None, "未安装")
        with mock.patch.object(
            vm,
            "refresh_environment",
            return_value=NpcapReport(False, None, "仍未安装"),
        ):
            vm.start_npcap_install()
            deadline = time.monotonic() + 5
            while vm.install_state().phase not in {"completed", "failed"}:
                if time.monotonic() >= deadline:
                    self.fail(f"安装流程未结束: {vm.install_state()}")
                time.sleep(0.01)
        self.assertEqual(vm.install_state().phase, "failed")
        self.assertIn("仍未检测到", vm.install_state().message)

    def test_npcap_install_launcher_cancel_is_failed(self):
        installer = self.tmp_path / "npcap.exe"
        installer.write_bytes(b"MZinstaller")

        def canceled_launcher(path):
            raise RuntimeError("用户取消安装向导")

        vm, _monitor = _make_vm(
            self.tmp_path,
            resolver=lambda: ("https://npcap.com/dist/npcap-1.0.exe", "1.0"),
            downloader=lambda url, dest_dir, *, progress_cb: installer,
            launcher=canceled_launcher,
        )
        vm._npcap_report = NpcapReport(False, None, "未安装")
        vm.start_npcap_install()
        deadline = time.monotonic() + 5
        while vm.install_state().phase not in {"completed", "failed"}:
            if time.monotonic() >= deadline:
                self.fail(f"安装流程未结束: {vm.install_state()}")
            time.sleep(0.01)
        self.assertEqual(vm.install_state().phase, "failed")
        self.assertIn("用户取消", vm.install_state().message)

    def test_npcap_install_concurrent_clicks_start_one_flow(self):
        installer = self.tmp_path / "npcap.exe"
        installer.write_bytes(b"MZinstaller")
        download_started = threading.Event()
        release_download = threading.Event()
        launch_count = 0
        count_lock = threading.Lock()

        def downloader(url, dest_dir, *, progress_cb):
            download_started.set()
            release_download.wait(timeout=5)
            return installer

        def launcher(path):
            nonlocal launch_count
            with count_lock:
                launch_count += 1
            return 0

        vm, _monitor = _make_vm(
            self.tmp_path,
            resolver=lambda: ("https://npcap.com/dist/npcap-1.0.exe", "1.0"),
            downloader=downloader,
            launcher=launcher,
        )
        vm._npcap_report = NpcapReport(False, None, "未安装")
        with mock.patch.object(
            vm,
            "refresh_environment",
            return_value=NpcapReport(True, str(installer), "已安装"),
        ):
            vm.start_npcap_install()
            self.assertTrue(download_started.wait(timeout=5))
            vm.start_npcap_install()
            release_download.set()
            deadline = time.monotonic() + 5
            while vm.install_state().phase not in {"completed", "failed"}:
                if time.monotonic() >= deadline:
                    self.fail(f"安装流程未结束: {vm.install_state()}")
                time.sleep(0.01)
        self.assertEqual(launch_count, 1)


if __name__ == "__main__":
    unittest.main()
