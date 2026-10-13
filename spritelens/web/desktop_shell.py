"""自绘标题栏的窗口操作；窗口状态以 Win32 为准，不保存前端副本。"""

from __future__ import annotations

import ctypes
import json
from ctypes import wintypes
from typing import TYPE_CHECKING

from spritelens.logs import get_logger

if TYPE_CHECKING:
    from webview import Window

logger = get_logger("desktop_shell")


class _MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD),
    ]


class WindowControls:
    def __init__(self, window: Window, position: tuple[int, int] | None = None) -> None:
        self._window = window
        self._position = position
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        for name in ("IsZoomed", "IsIconic"):
            function = getattr(self._user32, name)
            function.argtypes = [wintypes.HWND]
            function.restype = wintypes.BOOL

    def get_window_state(self) -> dict[str, bool]:
        hwnd = self._window.native.Handle.ToInt64()
        return {
            "maximized": bool(self._user32.IsZoomed(hwnd)),
            "minimized": bool(self._user32.IsIconic(hwnd)),
        }

    def minimize(self) -> None:
        self._window.minimize()

    def get_window_geometry(self) -> dict[str, int]:
        """正常窗口的物理坐标与逻辑尺寸；最大化/最小化时读取还原边界。"""
        from System import Action

        geometry = {}
        def read() -> None:
            native = self._window.native
            bounds = native.RestoreBounds if any(self.get_window_state().values()) else native.Bounds
            scale = native._scale
            geometry.update(x=bounds.X, y=bounds.Y,
                            width=round(bounds.Width / scale), height=round(bounds.Height / scale))
        self._window.native.Invoke(Action(read))
        return geometry

    def install_native_frame(self) -> None:
        """在 GUI 线程保留系统动画样式，只把非客户区交给网页绘制。"""
        from System import Action
        from System.Drawing import Point, Size
        from System.Windows.Forms import Screen
        from spritelens.system.window_geometry import fit_window_position

        def install() -> None:
            hwnd = self._window.native.Handle.ToInt64()
            user32 = self._user32
            user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
            user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
            user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
            user32.SetWindowPos.argtypes = [
                wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                ctypes.c_int, ctypes.c_int, wintypes.UINT,
            ]
            user32.SetWindowPos.restype = wintypes.BOOL
            user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
            user32.MonitorFromWindow.restype = wintypes.HANDLE
            user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_MonitorInfo)]
            user32.GetMonitorInfoW.restype = wintypes.BOOL

            # SetWindowSubclass 必须与窗口同线程，回调引用由 controls 持有至销毁。
            self._comctl32 = ctypes.WinDLL("comctl32", use_last_error=True)
            callback_type = ctypes.WINFUNCTYPE(
                ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                wintypes.LPARAM, ctypes.c_size_t, ctypes.c_size_t,
            )
            self._frame_callback = callback_type(self._frame_message)
            self._comctl32.SetWindowSubclass.argtypes = [wintypes.HWND, callback_type, ctypes.c_size_t, ctypes.c_size_t]
            self._comctl32.SetWindowSubclass.restype = wintypes.BOOL
            self._comctl32.RemoveWindowSubclass.argtypes = [wintypes.HWND, callback_type, ctypes.c_size_t]
            self._comctl32.RemoveWindowSubclass.restype = wintypes.BOOL
            self._comctl32.DefSubclassProc.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            self._comctl32.DefSubclassProc.restype = ctypes.c_ssize_t
            if not self._comctl32.SetWindowSubclass(hwnd, self._frame_callback, 1, 0):
                raise ctypes.WinError(ctypes.get_last_error())

            # WS_CAPTION / THICKFRAME / SYSMENU / MINIMIZEBOX / MAXIMIZEBOX。
            # 完全移除这些样式会让 DWM 的最大化、还原和最小化动画失效。
            original = user32.GetWindowLongPtrW(hwnd, -16)
            try:
                ctypes.set_last_error(0)
                previous = user32.SetWindowLongPtrW(hwnd, -16, original | 0x00CF0000)
                if not previous and ctypes.get_last_error():
                    raise ctypes.WinError(ctypes.get_last_error())
                # FRAMECHANGED / NOMOVE / NOSIZE / NOZORDER / NOACTIVATE。
                if not user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x37):
                    raise ctypes.WinError(ctypes.get_last_error())
                # pywebview 设置 FormBorderStyle.None 会扣掉旧非客户区尺寸；
                # 首次显示前恢复指定外框大小，不能等网页加载后再缩放。
                native = self._window.native
                if self._position is not None:
                    # 位置用物理像素存储，跨不同DPI的显示器仍恢复到原坐标。
                    native.Location = Point(*self._position)
                scale = native._scale
                native.Size = Size(round(self._window.initial_width * scale),
                                   round(self._window.initial_height * scale))
                if self._position is not None:
                    work = Screen.FromRectangle(native.Bounds).WorkingArea
                    x, y = fit_window_position(native.Left, native.Top, native.Width, native.Height,
                                               (work.Left, work.Top, work.Right, work.Bottom))
                    native.Location = Point(x, y)
            except OSError:
                # 初始化失败时撤销已安装的样式和回调，异常继续向外报告。
                user32.SetWindowLongPtrW(hwnd, -16, original)
                self._comctl32.RemoveWindowSubclass(hwnd, self._frame_callback, 1)
                user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x37)
                raise

        self._window.native.Invoke(Action(install))

    def enable_native_drag(self) -> None:
        """首次导航前启用原生拖动；此设置在 loaded 时更改要到下次导航才生效。"""
        from System import Action

        def install() -> None:
            self._window.native.webview.NavigationStarting += self._enable_drag_before_navigation

        self._window.native.Invoke(Action(install))

    def _enable_drag_before_navigation(self, sender: object, _args: object) -> None:
        # NavigationStarting 在 GUI 线程触发，CoreWebView2 已创建；同时覆盖失败重试。
        sender.CoreWebView2.Settings.IsNonClientRegionSupportEnabled = True

    def _frame_message(self, hwnd: int, message: int, wparam: int, lparam: int,
                       subclass_id: int, reference: int) -> int:
        if message == 0x83 and wparam:  # WM_NCCALCSIZE：整个窗口都是网页客户区。
            if self._user32.IsZoomed(hwnd):
                monitor = self._user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
                info = _MonitorInfo(cbSize=ctypes.sizeof(_MonitorInfo))
                if not self._user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                    logger.error("最大化工作区读取失败: %s", ctypes.get_last_error())
                    return self._comctl32.DefSubclassProc(hwnd, message, wparam, lparam)
                # NCCALCSIZE_PARAMS 首成员是客户区 RECT；裁掉系统的最大化边框余量。
                rect = ctypes.cast(lparam, ctypes.POINTER(wintypes.RECT)).contents
                rect.left = max(rect.left, info.rcWork.left)
                rect.top = max(rect.top, info.rcWork.top)
                rect.right = min(rect.right, info.rcWork.right)
                rect.bottom = min(rect.bottom, info.rcWork.bottom)
            return 0
        if message == 0x82:  # WM_NCDESTROY：卸下本窗口回调，保留框架的正常销毁。
            self._comctl32.RemoveWindowSubclass(hwnd, self._frame_callback, subclass_id)
        return self._comctl32.DefSubclassProc(hwnd, message, wparam, lparam)

    def toggle_maximize(self) -> None:
        if self.get_window_state()["maximized"]:
            self._window.restore()
        else:
            from System import Action
            from System.Windows.Forms import Screen

            def set_bounds() -> None:
                native = self._window.native
                # 无边框窗默认可能覆盖任务栏；每次按所在屏幕工作区最大化。
                native.MaximizedBounds = Screen.FromHandle(native.Handle).WorkingArea

            self._window.native.Invoke(Action(set_bounds))
            self._window.maximize()

    def close(self) -> None:
        self._window.destroy()

    def resize_window(self, edge: int, width: int, height: int) -> None:
        # JS 桥是输入边界，只接受八个缩放方向。
        if isinstance(edge, bool) or not isinstance(edge, int) or edge not in range(1, 9):
            raise ValueError("无效的窗口缩放方向")
        if self.get_window_state()["maximized"]:
            return
        from webview.window import FixPoint

        horizontal = FixPoint.EAST if edge in (1, 4, 7) else FixPoint.WEST
        vertical = FixPoint.SOUTH if edge in (3, 4, 5) else FixPoint.NORTH
        minimum_width, minimum_height = self._window.min_size
        self._window.resize(max(minimum_width, width), max(minimum_height, height),
                            fix_point=horizontal | vertical)

    def sync_state(self) -> None:
        state = json.dumps(self.get_window_state())
        self._window.run_js(
            f"window.dispatchEvent(new CustomEvent('desktop-window-state', {{detail: {state}}}));"
        )
