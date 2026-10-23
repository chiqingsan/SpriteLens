"""游戏进程自动监听的纯逻辑与系统边界测试。"""

from __future__ import annotations

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock, patch

import spritelens.system.game_process as game_process
from spritelens.repositories.settings import SettingsRepository
from spritelens.services.game_capture_automation import GameCaptureAutomation
from spritelens.system.game_process import DEFAULT_GAME_PROCESS_NAME, _task_xml, normalize_process_name
from spritelens.system.runtime_session import RuntimeSession, clear_runtime, read_runtime, write_runtime


class GameProcessTests(unittest.TestCase):
    def test_process_name_accepts_exe_basename_only(self):
        self.assertEqual(normalize_process_name("  RocoWorld.exe "), "RocoWorld.exe")
        for value in ("", "RocoWorld", r"C:\\Game\\RocoWorld.exe", "RocoWorld.dll"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_process_name(value)

    def test_task_xml_matches_process_creation_event(self):
        xml = _task_xml("RocoWorld.exe", r"C:\\SpriteLens.exe", ["--background", "--process-name", "RocoWorld.exe"])
        ET.fromstring(xml)
        self.assertIn("EventID=4688", xml)
        self.assertIn("Data[@Name='NewProcessName']", xml)
        self.assertIn("*[System[(EventID=4688)] and EventData[", xml)
        self.assertNotIn("]] and *[EventData", xml)
        self.assertNotIn("contains(", xml)
        self.assertIn("C:\\\\SpriteLens.exe", xml)

    def test_task_registration_elevates_only_when_needed(self):
        with patch.object(game_process, "_is_user_admin", return_value=False), patch.object(
            game_process, "_run_schtasks_elevated"
        ) as elevated:
            game_process._run_schtasks(["/Delete", "/TN", "SpriteLens.GameCapture", "/F"])

        elevated.assert_called_once_with(["/Delete", "/TN", "SpriteLens.GameCapture", "/F"])

    def test_remove_missing_task_is_noop_and_existing_task_uses_runner(self):
        with patch.object(game_process, "_task_exists", return_value=False), patch.object(
            game_process, "_run_schtasks"
        ) as runner:
            game_process.remove_game_trigger()
        runner.assert_not_called()

        with patch.object(game_process, "_task_exists", return_value=True), patch.object(
            game_process, "_run_schtasks"
        ) as runner:
            game_process.remove_game_trigger()
        runner.assert_called_once_with(["/Delete", "/TN", "SpriteLens.GameCapture", "/F"])


class AutomationServiceTests(unittest.TestCase):
    def test_snapshot_defaults_to_game_process_from_meow(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = SettingsRepository(Path(directory) / "config.json")
            service = GameCaptureAutomation(settings, install=Mock(), remove=Mock())

            result = service.snapshot()

            self.assertFalse(result["enabled"])
            self.assertEqual(result["process_name"], DEFAULT_GAME_PROCESS_NAME)

    def test_enable_installs_task_before_persisting(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = SettingsRepository(Path(directory) / "config.json")
            installed: list[str] = []
            removed = Mock()
            service = GameCaptureAutomation(settings, install=installed.append, remove=removed)

            result = service.configure(enabled=True, process_name="RocoWorld.exe")

            self.assertEqual(installed, ["RocoWorld.exe"])
            self.assertFalse(removed.called)
            self.assertTrue(result["enabled"])
            self.assertEqual(service.snapshot()["process_name"], "RocoWorld.exe")

    def test_enable_requires_process_name(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = SettingsRepository(Path(directory) / "config.json")
            install = Mock()
            service = GameCaptureAutomation(settings, install=install, remove=Mock())
            with self.assertRaises(ValueError):
                service.configure(enabled=True, process_name="")
            install.assert_not_called()

    def test_disable_removes_task_and_keeps_name(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = SettingsRepository(Path(directory) / "config.json")
            settings.set_checked("capture.game_automation", {"enabled": True, "process_name": "RocoWorld.exe"})
            remove = Mock()
            service = GameCaptureAutomation(settings, install=Mock(), remove=remove)

            result = service.configure(enabled=False, process_name="RocoWorld.exe")

            remove.assert_called_once_with()
            self.assertFalse(result["enabled"])
            self.assertEqual(result["process_name"], "RocoWorld.exe")


class RuntimeSessionTests(unittest.TestCase):
    def test_roundtrip_and_pid_guarded_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            import os
            with patch.dict(os.environ, {"SPRITELENS_DATA_ROOT": directory}):
                session = RuntimeSession(os.getpid(), "http://127.0.0.1:1234/#token=x")
                write_runtime(session)
                self.assertEqual(read_runtime(), session)
                clear_runtime(os.getpid() + 1)
                self.assertEqual(read_runtime(), session)
                clear_runtime(os.getpid())
                self.assertIsNone(read_runtime())


if __name__ == "__main__":
    unittest.main()
