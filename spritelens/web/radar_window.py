"""单个置顶雷达窗口；随主窗口退出，关闭后允许重新打开。"""
from __future__ import annotations

import threading
import ctypes
from ctypes import wintypes
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spritelens.repositories.settings import SettingsRepository
    from webview import Window


RADAR_MIN_SIZE = (280, 380)
RADAR_MAX_SIZE = (720, 900)


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _MinMaxInfo(ctypes.Structure):
    _fields_ = [
        ("ptReserved", _Point),
        ("ptMaxSize", _Point),
        ("ptMaxPosition", _Point),
        ("ptMinTrackSize", _Point),
        ("ptMaxTrackSize", _Point),
    ]


class RadarWindow:
    def __init__(self, url: str, settings: SettingsRepository,
                 on_closed: Callable[[], None] | None = None) -> None:
        self._url = url
        self._settings = settings
        self._lock = threading.Lock()
        self._window: Window | None = None
        self._closing = False
        self._on_closed = on_closed
        self._tool_callback = None

    def open_radar(self) -> None:
        import webview

        with self._lock:
            if self._closing:
                raise RuntimeError("应用正在关闭")
            if self._window is not None:
                self._show_without_activation(self._window)
                return
            window = webview.create_window(
                "小洛探探 · 悬浮雷达", "about:blank", width=360, height=460,
                min_size=RADAR_MIN_SIZE, on_top=True, focus=False, hidden=True, frameless=True, easy_drag=False,
                background_color="#17251f",
            )
            self._window = window
            closing_registered = False
            closed_registered = False
            try:
                self._install_tool_window(window, self._settings.radar_position())
                window.expose(self.close_radar, self.set_radar_opacity)
                self._set_opacity(window, 85)
                window.events.closing += self._save_position
                closing_registered = True
                window.events.closed += self._closed
                closed_registered = True
                window.load_url(self._url)
                self._show_without_activation(window)
            except Exception:
                self._window = None
                if closing_registered:
                    window.events.closing -= self._save_position
                if closed_registered:
                    window.events.closed -= self._closed
                window.destroy()
                raise

    def _install_tool_window(self, window: Window, position: tuple[int, int] | None = None) -> None:
        from System import Action
        from System.Drawing import Point
        from System.Windows.Forms import Screen
        from spritelens.system.window_geometry import fit_window_position

        def install() -> None:
            native = window.native
            native.webview.NavigationStarting += self._enable_drag
            # 直接改 HWND 样式，避免 WinForms 重建句柄中断 WebView2 初始化。
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
            user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
            user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
            hwnd = native.Handle.ToInt64()
            # 保留原生边缘缩放，非客户区由网页自行绘制；雷达不允许最大化。
            original_style = user32.GetWindowLongPtrW(hwnd, -16)
            style_value = (original_style | 0x00040000) & ~0x00010000  # WS_THICKFRAME，清除 WS_MAXIMIZEBOX
            ctypes.set_last_error(0)
            result = user32.SetWindowLongPtrW(hwnd, -16, style_value)
            if not result and ctypes.get_last_error():
                raise ctypes.WinError(ctypes.get_last_error())
            # 工具窗不进入任务栏/Alt-Tab；鼠标操作也不激活窗口。
            style = user32.GetWindowLongPtrW(hwnd, -20)
            ctypes.set_last_error(0)
            result = user32.SetWindowLongPtrW(hwnd, -20, (style | 0x08000080) & ~0x00040000)
            if not result and ctypes.get_last_error():
                raise ctypes.WinError(ctypes.get_last_error())
            user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                           ctypes.c_int, ctypes.c_int, wintypes.UINT]
            user32.SetWindowPos.restype = wintypes.BOOL
            if self._tool_callback is None:
                self._comctl32 = ctypes.WinDLL("comctl32", use_last_error=True)
                callback_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                                                   wintypes.WPARAM, wintypes.LPARAM, ctypes.c_size_t, ctypes.c_size_t)
                self._tool_callback = callback_type(self._tool_message)
                self._comctl32.SetWindowSubclass.argtypes = [wintypes.HWND, callback_type, ctypes.c_size_t, ctypes.c_size_t]
                self._comctl32.SetWindowSubclass.restype = wintypes.BOOL
                self._comctl32.RemoveWindowSubclass.argtypes = [wintypes.HWND, callback_type, ctypes.c_size_t]
                self._comctl32.RemoveWindowSubclass.restype = wintypes.BOOL
                self._comctl32.DefSubclassProc.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
                self._comctl32.DefSubclassProc.restype = ctypes.c_ssize_t
            if not self._comctl32.SetWindowSubclass(hwnd, self._tool_callback, 1, 0):
                raise ctypes.WinError(ctypes.get_last_error())
            if not user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x37):
                raise ctypes.WinError(ctypes.get_last_error())
            if position is not None:
                native.Location = Point(*position)
                work = Screen.FromRectangle(native.Bounds).WorkingArea
                native.Location = Point(*fit_window_position(
                    native.Left, native.Top, native.Width, native.Height,
                    (work.Left, work.Top, work.Right, work.Bottom),
                ))

        window.native.Invoke(Action(install))

    def _save_position(self, window: Window) -> None:
        location = window.native.Location
        self._settings.set_radar_position(location.X, location.Y)

    def _tool_message(self, hwnd: int, message: int, wparam: int, lparam: int,
                      subclass_id: int, reference: int) -> int:
        if message == 0x112 and (wparam & 0xFFF0) == 0xF030:  # WM_SYSCOMMAND / SC_MAXIMIZE
            return 0
        if message == 0xA3:  # WM_NCLBUTTONDBLCLK：禁止标题栏双击最大化。
            return 0
        if message == 0x24:  # WM_GETMINMAXINFO：限制窗口拖拽范围。
            info = ctypes.cast(lparam, ctypes.POINTER(_MinMaxInfo)).contents
            info.ptMinTrackSize.x, info.ptMinTrackSize.y = RADAR_MIN_SIZE
            info.ptMaxTrackSize.x, info.ptMaxTrackSize.y = RADAR_MAX_SIZE
            return 0
        if message == 0x21:  # WM_MOUSEACTIVATE：保留点击处理，但不激活工具窗。
            return 3  # MA_NOACTIVATE
        if message == 0x83 and wparam:  # WM_NCCALCSIZE
            return 0
        if message == 0x82:  # WM_NCDESTROY
            self._comctl32.RemoveWindowSubclass(hwnd, self._tool_callback, subclass_id)
        return self._comctl32.DefSubclassProc(hwnd, message, wparam, lparam)

    def _enable_drag(self, sender: object, _args: object) -> None:
        sender.CoreWebView2.Settings.IsNonClientRegionSupportEnabled = True

    def _set_opacity(self, window: Window, percent: int) -> None:
        from System import Action

        def apply() -> None:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
            user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
            user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
            user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_ubyte, wintypes.DWORD]
            user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
            hwnd = window.native.Handle.ToInt64()
            style = user32.GetWindowLongPtrW(hwnd, -20)
            ctypes.set_last_error(0)
            result = user32.SetWindowLongPtrW(hwnd, -20, style | 0x00080000)
            if not result and ctypes.get_last_error():
                raise ctypes.WinError(ctypes.get_last_error())
            if not user32.SetLayeredWindowAttributes(hwnd, 0, round(percent * 255 / 100), 2):
                raise ctypes.WinError(ctypes.get_last_error())

        window.native.Invoke(Action(apply))

    def set_radar_opacity(self, percent: int) -> None:
        if isinstance(percent, bool) or not isinstance(percent, int) or not 35 <= percent <= 90:
            raise ValueError("不透明度必须是35到90的整数")
        with self._lock:
            if self._window is None or self._closing:
                raise RuntimeError("悬浮雷达未打开")
            self._set_opacity(self._window, percent)

    def close_radar(self) -> None:
        with self._lock:
            window = self._window
        if window is not None:
            window.destroy()

    def _show_without_activation(self, window: Window) -> None:
        from System import Action

        def show() -> None:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.ShowWindow.restype = wintypes.BOOL
            user32.ShowWindow(window.native.Handle.ToInt64(), 4)  # SW_SHOWNOACTIVATE

        window.native.Invoke(Action(show))

    def _closed(self) -> None:
        with self._lock:
            self._window = None
            notify = not self._closing
        if notify and self._on_closed is not None:
            self._on_closed()

    def shutdown(self) -> None:
        with self._lock:
            self._closing = True
            window = self._window
            self._window = None
        if window is not None:
            window.destroy()
