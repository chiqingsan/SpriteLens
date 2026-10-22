from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from spritelens.web.close_coordinator import CloseCoordinator


class CloseCoordinatorTest(unittest.TestCase):
    def test_missing_page_ack_times_out_and_can_retry_after_restore(self):
        window = Mock()
        window.create_confirmation_dialog.return_value = False
        context = SimpleNamespace(capture_vm=Mock(), pet_store=None, egg_store=None,
                                  home_store=None, event_log=None)
        callbacks = []

        def evaluate(script, callback=None):
            if callback:
                callbacks.append(callback)

        window.evaluate_js.side_effect = evaluate
        coordinator = CloseCoordinator(window, context, save_timeout=0.05)
        coordinator._prepare()
        coordinator._recovery_thread.join(2)
        window.destroy.assert_not_called()
        # 迟到的上次响应不得被用作本次保存确认。
        callbacks[0]({"ok": True})
        coordinator._prepare()
        coordinator._recovery_thread.join(2)
        self.assertEqual(len(callbacks), 2)
        window.destroy.assert_not_called()
        window.create_confirmation_dialog.assert_called()

    def test_js_dispatch_timeout_is_retryable_without_parallel_dispatch(self):
        window = Mock()
        release = threading.Event()
        context = SimpleNamespace(capture_vm=Mock(), pet_store=None, egg_store=None,
                                  home_store=None, event_log=None)
        window.create_confirmation_dialog.return_value = False
        calls = []

        def evaluate(script, callback=None):
            calls.append("save" if callback else "restore")
            if callback:
                release.wait(2)
                callback({"ok": True})

        window.evaluate_js.side_effect = evaluate
        coordinator = CloseCoordinator(window, context, save_timeout=0.05)
        try:
            coordinator._prepare()
            window.create_confirmation_dialog.assert_called_once()
            window.destroy.assert_not_called()
            self.assertFalse(coordinator._saving)
            coordinator._prepare()
            self.assertEqual(calls, ["save"])
            release.set()
            coordinator._recovery_thread.join(2)
            self.assertEqual(calls, ["save", "restore"])
            coordinator._prepare()
            self.assertEqual(calls, ["save", "restore", "save"])
            window.destroy.assert_called_once()
        finally:
            release.set()
            if coordinator._page_thread is not None:
                coordinator._page_thread.join(2)
            if coordinator._recovery_thread is not None:
                coordinator._recovery_thread.join(2)

    def test_blocked_cancel_dispatch_does_not_hold_retry_state(self):
        window = Mock()
        release, restoring = threading.Event(), threading.Event()
        window.create_confirmation_dialog.return_value = False

        def evaluate(script, callback=None):
            if callback:
                callback({"ok": False, "error": "disk full"})
            else:
                restoring.set()
                release.wait(2)

        window.evaluate_js.side_effect = evaluate
        coordinator = CloseCoordinator(window, Mock(), save_timeout=0.05)
        try:
            coordinator._prepare()
            self.assertTrue(restoring.wait(2))
            self.assertFalse(coordinator._saving)
            worker = coordinator._recovery_thread
            coordinator._prepare()
            self.assertIs(coordinator._recovery_thread, worker)
            self.assertEqual(window.evaluate_js.call_count, 2)
        finally:
            release.set()
            coordinator._recovery_thread.join(2)

    def test_geometry_write_is_in_storage_budget_and_precedes_destroy(self):
        window = Mock()
        window.events.loaded.is_set.return_value = False
        release, writing, failed = threading.Event(), threading.Event(), threading.Event()
        window.create_confirmation_dialog.side_effect = lambda *args: (failed.set(), False)[1]
        context = SimpleNamespace(capture_vm=Mock(), pet_store=None, egg_store=None,
                                  home_store=None, event_log=None, settings=Mock())
        geometry = {"width": 900, "height": 700, "x": 10, "y": 20}

        def save(**kwargs):
            writing.set()
            release.wait(2)

        context.settings.set_window_geometry.side_effect = save
        coordinator = CloseCoordinator(window, context, save_timeout=0.05,
                                       get_geometry=lambda: geometry)
        try:
            self.assertFalse(coordinator.request_close())
            self.assertTrue(writing.wait(2))
            self.assertTrue(failed.wait(2))
            self.assertTrue(coordinator._storage_thread.is_alive())
            window.destroy.assert_not_called()
            release.set()
            coordinator._storage_thread.join(2)
        finally:
            release.set()
        context.settings.set_window_geometry.assert_called_once_with(**geometry, maximized=False)

    def test_window_stays_open_until_page_acknowledges_save(self):
        window = Mock()
        waiting, destroyed = threading.Event(), threading.Event()
        callbacks = []
        window.evaluate_js.side_effect = lambda script, callback: (callbacks.append(callback), waiting.set())
        window.destroy.side_effect = destroyed.set
        context = SimpleNamespace(capture_vm=Mock(), pet_store=Mock(), egg_store=Mock(),
                                  home_store=Mock(), event_log=Mock())
        coordinator = CloseCoordinator(window, context)
        self.assertFalse(coordinator.request_close())
        self.assertTrue(waiting.wait(2))
        window.destroy.assert_not_called()
        context.pet_store.flush.assert_not_called()
        callbacks[0]({"ok": True})
        self.assertTrue(destroyed.wait(2))
        context.capture_vm.stop.assert_called_once()
        context.pet_store.flush.assert_called_once()
        self.assertTrue(coordinator.request_close())

    def test_failed_save_keeps_window_retryable_unless_abandon_is_confirmed(self):
        for abandon in (False, True):
            with self.subTest(abandon=abandon):
                window = Mock()
                window.evaluate_js.side_effect = lambda script, callback=None: callback({"ok": False, "error": "disk full"}) if callback else None
                window.create_confirmation_dialog.return_value = abandon
                coordinator = CloseCoordinator(window, Mock())
                coordinator._prepare()
                if abandon:
                    window.destroy.assert_called_once()
                    self.assertTrue(coordinator._approved)
                else:
                    window.destroy.assert_not_called()
                    self.assertFalse(coordinator._saving)
                    self.assertFalse(coordinator._approved)

    def test_storage_failure_is_reported_before_window_is_destroyed(self):
        window = Mock()
        window.events.loaded.is_set.return_value = False
        window.create_confirmation_dialog.return_value = False
        context = SimpleNamespace(capture_vm=Mock(), pet_store=Mock(), egg_store=None,
                                  home_store=None, event_log=None)
        context.pet_store.flush.side_effect = OSError("disk full")
        coordinator = CloseCoordinator(window, context)
        coordinator._prepare()
        window.destroy.assert_not_called()
        self.assertIn("disk full", window.create_confirmation_dialog.call_args.args[1])

    def test_blocked_storage_times_out_and_retry_does_not_start_parallel_writer(self):
        window = Mock()
        window.events.loaded.is_set.return_value = False
        window.create_confirmation_dialog.return_value = False
        release = threading.Event()
        context = SimpleNamespace(capture_vm=Mock(), pet_store=Mock(), egg_store=None,
                                  home_store=None, event_log=None)
        context.pet_store.flush.side_effect = lambda: release.wait(2)
        coordinator = CloseCoordinator(window, context, save_timeout=0.05)
        try:
            coordinator._prepare()
            worker = coordinator._storage_thread
            self.assertTrue(worker.is_alive())
            self.assertFalse(coordinator._saving)
            window.destroy.assert_not_called()
            coordinator._prepare()
            self.assertIs(coordinator._storage_thread, worker)
            context.pet_store.flush.assert_called_once()
            release.set()
            worker.join(2)
            coordinator._prepare()
            window.destroy.assert_called_once()
            self.assertEqual(context.pet_store.flush.call_count, 2)
        finally:
            release.set()
            coordinator._storage_thread.join(2)

    def test_explicit_abandon_returns_while_storage_is_still_blocked(self):
        window = Mock()
        window.events.loaded.is_set.return_value = False
        window.create_confirmation_dialog.return_value = True
        release = threading.Event()
        context = SimpleNamespace(capture_vm=Mock(), pet_store=Mock(), egg_store=None,
                                  home_store=None, event_log=None)
        context.pet_store.flush.side_effect = lambda: release.wait(2)
        coordinator = CloseCoordinator(window, context, save_timeout=0.05)
        try:
            coordinator._prepare()
            self.assertTrue(coordinator.abandoned)
            self.assertTrue(coordinator._storage_thread.is_alive())
            window.destroy.assert_called_once()
        finally:
            release.set()
            coordinator._storage_thread.join(2)
