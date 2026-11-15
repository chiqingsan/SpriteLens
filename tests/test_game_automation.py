"""游戏进程自动监听的纯逻辑与系统边界测试。"""

from __future__ import annotations

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock, patch

import spritelens.system.game_process as game_process
import spritelens.web.background_run as background_run
from spritelens.repositories.settings import SettingsRepository
from spritelens.services.game_capture_automation import GameCaptureAutomation
from spritelens.system.game_process import DEFAULT_GAME_PROCESS_NAME, _task_xml, normalize_process_name
from spritelens.system.process_watch import OBJID_WINDOW, ProcessWindowWatcher
from spritelens.system.runtime_session import RuntimeSession, clear_runtime, read_runtime, write_runtime


class GameProcessTests(unittest.TestCase):
    def test_process_name_accepts_exe_basename_only(self):
        self.assertEqual(normalize_process_name("  RocoWorld.exe "), "RocoWorld.exe")
        for value in ("", "RocoWorld", r"C:\\Game\\RocoWorld.exe", "RocoWorld.dll"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_process_name(value)

    def test_task_xml_uses_logon_trigger_without_auditing(self):
        xml = _task_xml("RocoWorld.exe", r"C:\\SpriteLens.exe", ["--background", "--process-name", "RocoWorld.exe"])
        ET.fromstring(xml)
        self.assertIn("<LogonTrigger>", xml)
        self.assertIn("<RunLevel>LeastPrivilege</RunLevel>", xml)
        self.assertIn("<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>", xml)
        self.assertIn("<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>", xml)
        self.assertIn("<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>", xml)
        self.assertIn("<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>", xml)
        self.assertNotIn("EventTrigger", xml)
        self.assertNotIn("4688", xml)
        self.assertNotIn("HighestAvailable", xml)
        self.assertIn("C:\\\\SpriteLens.exe", xml)

    def test_task_registration_elevates_only_when_access_is_denied(self):
        with patch.object(game_process, "_run_schtasks_direct") as direct, patch.object(
            game_process, "_run_schtasks_elevated"
        ) as elevated:
            game_process._run_schtasks(["/Delete", "/TN", "SpriteLens.GameCapture", "/F"])
        direct.assert_called_once()
        elevated.assert_not_called()

        denied = OSError("Windows 任务计划程序操作失败：拒绝访问。")
        with patch.object(game_process, "_run_schtasks_direct", side_effect=denied), patch.object(
            game_process, "_run_schtasks_elevated"
        ) as elevated:
            game_process._run_schtasks(["/Delete", "/TN", "SpriteLens.GameCapture", "/F"])
        elevated.assert_called_once_with(["/Delete", "/TN", "SpriteLens.GameCapture", "/F"])

        with patch.object(game_process, "_run_schtasks_direct", side_effect=OSError("参数错误")), patch.object(
            game_process, "_run_schtasks_elevated"
        ) as elevated, self.assertRaises(OSError):
            game_process._run_schtasks(["/Delete", "/TN", "SpriteLens.GameCapture", "/F"])
        elevated.assert_not_called()

    @unittest.skipUnless(game_process.os.name == "nt", "Windows 子进程窗口策略")
    def test_direct_system_commands_do_not_create_console_windows(self):
        result = game_process.subprocess.CompletedProcess([], 0, "", "")
        with patch.object(game_process.subprocess, "run", return_value=result) as run:
            game_process._run_schtasks_direct(["/Delete", "/TN", "synthetic", "/F"])
            self.assertTrue(game_process._task_exists())
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            self.assertEqual(call.kwargs["creationflags"], game_process.subprocess.CREATE_NO_WINDOW)
            self.assertTrue(call.kwargs["capture_output"])

    def test_remove_missing_task_is_noop_and_existing_task_stops_then_deletes(self):
        with patch.object(game_process, "_task_exists", return_value=False), patch.object(
            game_process, "_run_schtasks"
        ) as runner:
            game_process.remove_game_trigger()
        runner.assert_not_called()

        with patch.object(game_process, "_task_exists", return_value=True), patch.object(
            game_process, "_run_schtasks_direct"
        ) as direct, patch.object(game_process, "_run_schtasks") as runner:
            game_process.remove_game_trigger()
        direct.assert_called_once_with(["/End", "/TN", "SpriteLens.GameCapture"])
        runner.assert_called_once_with(["/Delete", "/TN", "SpriteLens.GameCapture", "/F"])

    def test_remove_keeps_deleting_when_no_instance_is_running(self):
        with patch.object(game_process, "_task_exists", return_value=True), patch.object(
            game_process, "_run_schtasks_direct", side_effect=OSError("任务未运行")
        ), patch.object(game_process, "_run_schtasks") as runner:
            game_process.remove_game_trigger()
        runner.assert_called_once_with(["/Delete", "/TN", "SpriteLens.GameCapture", "/F"])


class ProcessWindowWatcherTests(unittest.TestCase):
    def test_top_level_window_of_target_process_marks_ready(self):
        watcher = ProcessWindowWatcher("RocoWorld.exe")
        with patch.object(watcher, "_window_matches", return_value=True) as matches:
            watcher._on_window(0, 0x8000, 4321, OBJID_WINDOW, 0, 0, 0)

        self.assertTrue(watcher.wait(0))
        matches.assert_called_once_with(4321)

    def test_child_objects_and_empty_handles_are_ignored(self):
        watcher = ProcessWindowWatcher("RocoWorld.exe")
        with patch.object(watcher, "_window_matches", return_value=True) as matches:
            watcher._on_window(0, 0x8000, 4321, -4, 0, 0, 0)  # OBJID_CLIENT
            watcher._on_window(0, 0x8000, 0, OBJID_WINDOW, 0, 0, 0)

        self.assertFalse(watcher.wait(0.01))
        matches.assert_not_called()

    def test_unrelated_process_window_is_ignored(self):
        watcher = ProcessWindowWatcher("RocoWorld.exe")
        with patch.object(watcher, "_window_matches", return_value=False):
            watcher._on_window(0, 0x8000, 99, OBJID_WINDOW, 0, 0, 0)

        self.assertFalse(watcher.wait(0.01))

    def test_reset_rearms_for_next_game_launch(self):
        watcher = ProcessWindowWatcher("RocoWorld.exe")
        with patch.object(watcher, "_window_matches", return_value=True):
            watcher._on_window(0, 0x8000, 7, OBJID_WINDOW, 0, 0, 0)
        self.assertTrue(watcher.wait(0))

        watcher.reset()

        self.assertFalse(watcher.wait(0.01))


class BackgroundRunTests(unittest.TestCase):
    def _run(self, **patches):
        watcher = Mock()
        watcher.wait.return_value = True
        guard = Mock()
        guard.acquire.return_value = True
        defaults = {
            "ProcessWindowWatcher": Mock(return_value=watcher),
            "SingleInstanceGuard": Mock(return_value=guard),
            "is_process_running": Mock(return_value=False),
        }
        defaults.update(patches)
        with patch.multiple(background_run, **defaults):
            code = background_run.run_background("RocoWorld.exe")
        return code, watcher, guard

    def test_window_event_starts_capture_session(self):
        session = Mock(return_value=background_run._SESSION_USER_EXIT)
        code, watcher, guard = self._run(_run_capture_session=session)

        self.assertEqual(code, 0)
        watcher.start.assert_called_once_with()
        watcher.stop.assert_called_once_with()
        session.assert_called_once_with("RocoWorld.exe", guard)
        guard.close.assert_called_once_with()

    def test_game_exit_rearms_and_waits_for_next_launch(self):
        session = Mock(side_effect=[background_run._SESSION_IDLE, background_run._SESSION_USER_EXIT])
        code, watcher, guard = self._run(_run_capture_session=session)

        self.assertEqual(code, 0)
        self.assertEqual(session.call_count, 2)
        watcher.reset.assert_called_once_with()
        self.assertEqual(guard.acquire.call_count, 2)

    def test_existing_instance_defers_until_game_exits(self):
        session = Mock(return_value=background_run._SESSION_USER_EXIT)
        acquire = Mock(side_effect=[False, True])
        guard = Mock()
        guard.acquire = acquire
        exit_waiter = Mock()
        code, watcher, _ = self._run(
            SingleInstanceGuard=Mock(return_value=guard),
            _run_capture_session=session,
            wait_for_process_exit=exit_waiter,
        )

        self.assertEqual(code, 0)
        exit_waiter.assert_called_once_with("RocoWorld.exe")
        session.assert_called_once()

    def test_invalid_process_name_does_not_touch_system(self):
        with patch.object(background_run, "ProcessWindowWatcher") as watcher:
            self.assertEqual(background_run.run_background(r"C:\\Game\\game.exe"), 2)
        watcher.assert_not_called()


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

            result = service.configure(enabled=True)

            self.assertEqual(installed, [DEFAULT_GAME_PROCESS_NAME])
            self.assertFalse(removed.called)
            self.assertTrue(result["enabled"])
            self.assertEqual(service.snapshot()["process_name"], DEFAULT_GAME_PROCESS_NAME)

    def test_saved_process_name_is_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = SettingsRepository(Path(directory) / "config.json")
            settings.set_checked("capture.game_automation", {"enabled": True, "process_name": "RocoWorld.exe"})
            install = Mock()
            service = GameCaptureAutomation(settings, install=install, remove=Mock())

            result = service.snapshot()

            self.assertTrue(result["enabled"])
            self.assertEqual(result["process_name"], DEFAULT_GAME_PROCESS_NAME)

    def test_disable_removes_task_and_uses_builtin_name(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = SettingsRepository(Path(directory) / "config.json")
            settings.set_checked("capture.game_automation", {"enabled": True, "process_name": "RocoWorld.exe"})
            remove = Mock()
            service = GameCaptureAutomation(settings, install=Mock(), remove=remove)

            result = service.configure(enabled=False)

            remove.assert_called_once_with()
            self.assertFalse(result["enabled"])
            self.assertEqual(result["process_name"], DEFAULT_GAME_PROCESS_NAME)


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
