"""悬浮雷达单实例及退出生命周期，不操作用户窗口。"""
from __future__ import annotations

import unittest
import ctypes
from types import SimpleNamespace
from unittest.mock import Mock, patch

from spritelens.web.radar_window import RADAR_MAX_SIZE, RADAR_MIN_SIZE, RadarWindow, _MinMaxInfo


class RadarWindowTests(unittest.TestCase):
    def test_singleton_close_reopen_and_shutdown(self):
        from webview.event import Event
        first = Mock(); first.events = SimpleNamespace(closed=Event(first, True), closing=Event(first, True), before_show=Event(first, True))
        second = Mock(); second.events = SimpleNamespace(closed=Event(second, True), closing=Event(second, True), before_show=Event(second, True))
        create = Mock(side_effect=[first, second])
        notify = Mock()
        settings = Mock(); settings.radar_position.return_value = None
        manager = RadarWindow("http://127.0.0.1/static/radar.html#token=synthetic", settings, on_closed=notify)
        with patch("webview.create_window", create), patch.object(manager, "_show_without_activation") as show, patch.object(manager, "_install_tool_window"), patch.object(manager, "_set_opacity"):
            manager.open_radar(); manager.open_radar()
            self.assertEqual(create.call_count, 1)
            self.assertTrue(create.call_args.kwargs["on_top"])
            self.assertFalse(create.call_args.kwargs["resizable"])
            self.assertEqual((create.call_args.kwargs["width"], create.call_args.kwargs["height"]), (360, 460))
            self.assertFalse(create.call_args.kwargs["focus"])
            self.assertEqual(show.call_count, 2)
            first.events.closed.set()
            notify.assert_called_once()
            manager.open_radar()
            self.assertEqual(create.call_count, 2)
            manager.shutdown(); manager.shutdown()
            second.destroy.assert_called_once()
            with self.assertRaisesRegex(RuntimeError, "正在关闭"):
                manager.open_radar()

    def test_creation_failure_allows_retry(self):
        from webview.event import Event
        window = Mock()
        window.events = SimpleNamespace(closed=Event(window, True), closing=Event(window, True), before_show=Event(window, True))
        settings = Mock(); settings.radar_position.return_value = None
        manager = RadarWindow("http://127.0.0.1/static/radar.html", settings)
        with patch("webview.create_window", side_effect=[OSError("创建失败"), window]), patch.object(manager, "_install_tool_window"), patch.object(manager, "_show_without_activation"), patch.object(manager, "_set_opacity"):
            with self.assertRaisesRegex(OSError, "创建失败"): manager.open_radar()
            manager.open_radar()
            manager.shutdown()
        window.destroy.assert_called_once()

    def test_tool_style_failure_closes_partial_window(self):
        window = Mock()
        manager = RadarWindow("about:blank", Mock())
        with patch("webview.create_window", return_value=window), patch.object(manager, "_install_tool_window", side_effect=OSError("工具窗失败")):
            with self.assertRaisesRegex(OSError, "工具窗失败"):
                manager.open_radar()
        window.destroy.assert_called_once()

    def test_mouse_activation_is_rejected_without_discarding_click(self):
        manager = RadarWindow("about:blank", Mock())
        self.assertEqual(manager._tool_message(1, 0x21, 0, 0, 1, 0), 3)

    def test_maximize_requests_are_ignored(self):
        manager = RadarWindow("about:blank", Mock())
        self.assertEqual(manager._tool_message(1, 0x112, 0xF000, 0, 1, 0), 0)
        self.assertEqual(manager._tool_message(1, 0x112, 0xF030, 0, 1, 0), 0)
        self.assertEqual(manager._tool_message(1, 0xA3, 0, 0, 1, 0), 0)

    def test_window_size_limits_are_applied_to_native_resize_message(self):
        manager = RadarWindow("about:blank", Mock())
        info = _MinMaxInfo()
        address = ctypes.addressof(info)
        self.assertEqual(manager._tool_message(1, 0x24, 0, address, 1, 0), 0)
        self.assertEqual((info.ptMinTrackSize.x, info.ptMinTrackSize.y), RADAR_MIN_SIZE)
        self.assertEqual((info.ptMaxTrackSize.x, info.ptMaxTrackSize.y), RADAR_MAX_SIZE)

    def test_opacity_boundary_and_active_window_ownership(self):
        manager = RadarWindow("about:blank", Mock())
        for value in (True, 0, 34, 91, 85.5, "85"):
            with self.assertRaises(ValueError): manager.set_radar_opacity(value)
        with self.assertRaises(RuntimeError): manager.set_radar_opacity(85)
        window = Mock(); manager._window = window
        with patch.object(manager, "_set_opacity") as apply:
            manager.set_radar_opacity(35); manager.set_radar_opacity(90)
        self.assertEqual(apply.call_args_list[0].args, (window, 35))
        self.assertEqual(apply.call_args_list[1].args, (window, 90))

    def test_window_is_shown_and_position_is_saved_before_close(self):
        from webview.event import Event
        settings = Mock(); settings.radar_position.return_value = (520, 240)
        location = SimpleNamespace(X=520, Y=240)
        window = Mock(native=SimpleNamespace(Location=location))
        window.events = SimpleNamespace(closed=Event(window, True), closing=Event(window, True))
        manager = RadarWindow("about:blank", settings)
        with patch("webview.create_window", return_value=window), patch.object(manager, "_install_tool_window") as install, patch.object(manager, "_set_opacity"), patch.object(manager, "_show_without_activation") as show:
            manager.open_radar()
            install.assert_called_once_with(window, (520, 240))
            show.assert_called_once_with(window)
            window.events.closing.set()
        settings.set_radar_position.assert_called_once_with(520, 240)
