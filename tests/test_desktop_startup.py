"""桌面启动的单画面交接、原生拖动设置和重试 URL；不打开用户窗口。"""
from __future__ import annotations

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from spritelens.web.desktop_shell import WindowControls
from spritelens.web.startup_cover import StartupCover


class DesktopStartupTest(unittest.TestCase):
    def test_restore_resizes_browser_on_gui_thread_without_navigation(self):
        bounds = SimpleNamespace(Width=1350, Height=900)
        browser = Mock()
        queued = []
        native = SimpleNamespace(ClientRectangle=bounds, webview=browser, BeginInvoke=queued.append)
        controls = WindowControls.__new__(WindowControls)
        controls._window = Mock(native=native)
        controls.get_window_state = Mock(return_value={"minimized": False, "maximized": False})
        with patch.dict(sys.modules, {"System": SimpleNamespace(Action=lambda f: f),
                                    "System.Drawing": SimpleNamespace(Size=lambda w, h: (w, h))}):
            controls.restore_content()
            browser.Refresh.assert_not_called()
            queued.pop()()
        self.assertEqual(browser.Size, (1349, 900))
        self.assertIs(browser.Bounds, bounds)
        browser.Refresh.assert_called_once()
        controls._window.load_url.assert_not_called()

    def test_restore_queued_before_another_minimize_does_not_resize_hidden_view(self):
        browser = Mock()
        native = SimpleNamespace(webview=browser, BeginInvoke=lambda f: f())
        controls = WindowControls.__new__(WindowControls)
        controls._window = SimpleNamespace(native=native)
        controls.get_window_state = Mock(return_value={"minimized": True, "maximized": False})
        with patch.dict(sys.modules, {"System": SimpleNamespace(Action=lambda f: f),
                                    "System.Drawing": SimpleNamespace(Size=Mock())}):
            controls.restore_content()
        browser.Refresh.assert_not_called()

    def test_geometry_uses_normal_bounds_when_minimized_or_maximized(self):
        normal = SimpleNamespace(X=-2100, Y=150, Width=1770, Height=1095)
        native = SimpleNamespace(Bounds=normal, RestoreBounds=normal, _scale=1.5,
                                 Invoke=lambda action: action())
        controls = WindowControls.__new__(WindowControls)
        controls._window = SimpleNamespace(native=native)
        with patch.dict(sys.modules, {"System": SimpleNamespace(Action=lambda action: action)}):
            for state in ({"maximized": False, "minimized": False},
                          {"maximized": True, "minimized": False},
                          {"maximized": False, "minimized": True}):
                controls.get_window_state = Mock(return_value=state)
                native.Bounds = normal if not any(state.values()) else SimpleNamespace(X=-32000, Y=-32000, Width=0, Height=0)
                self.assertEqual(controls.get_window_geometry(), {"x": -2100, "y": 150, "width": 1180, "height": 730})

    def test_drag_support_is_enabled_before_first_navigation_and_retry(self):
        settings = SimpleNamespace(IsNonClientRegionSupportEnabled=False)
        from webview.event import Event
        navigation = Event(None, True)
        view = SimpleNamespace(CoreWebView2=None, NavigationStarting=navigation)
        native = SimpleNamespace(webview=view,
                                 Invoke=lambda action: action())
        controls = WindowControls.__new__(WindowControls)
        controls._window = SimpleNamespace(native=native)
        with patch.dict(sys.modules, {"System": SimpleNamespace(Action=lambda action: action)}):
            controls.enable_native_drag()
        self.assertFalse(settings.IsNonClientRegionSupportEnabled)
        view.CoreWebView2 = SimpleNamespace(Settings=settings)
        navigation.set(view, None)
        self.assertTrue(settings.IsNonClientRegionSupportEnabled)
        settings.IsNonClientRegionSupportEnabled = False
        navigation.set(view, None)
        self.assertTrue(settings.IsNonClientRegionSupportEnabled)

    def test_retry_preserves_desktop_hint_and_forces_navigation(self):
        window = Mock(original_url="http://127.0.0.1:1234/?desktop=1#token=synthetic")
        cover = StartupCover(window)
        cover._reset = Mock()
        with patch("spritelens.web.startup_cover.time.monotonic_ns", return_value=55):
            cover._reload(None, None)
        window.load_url.assert_called_once_with("http://127.0.0.1:1234/?desktop=1&startup_retry=55#token=synthetic")

    def test_loaded_does_not_resurrect_disposed_cover(self):
        panel = Mock(IsDisposed=True)
        window = SimpleNamespace(native=SimpleNamespace(BeginInvoke=lambda action: action()))
        cover = StartupCover(window)
        cover._cover = panel
        with patch.dict(sys.modules, {"System": SimpleNamespace(Action=lambda action: action)}):
            cover.keep_on_top()
        panel.BringToFront.assert_not_called()
