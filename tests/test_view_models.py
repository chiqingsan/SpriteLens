"""ViewModel 单测：无 UI 框架依赖，直接验证状态与命令。"""

import tempfile
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


def _make_vm(tmp: Path, *, preset_key: bytes | None = None, **install_kwargs) -> tuple[CaptureViewModel, MonitorService]:
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

    def test_stop_without_start_is_safe(self):
        vm, _monitor = _make_vm(self.tmp_path)
        vm.stop()  # 未启动时停止不应抛错
        self.assertFalse(vm.snapshot().running)

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
