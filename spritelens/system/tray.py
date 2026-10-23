"""无第三方依赖的 Windows 通知区域图标。"""

from __future__ import annotations

import ctypes
import os
import threading
from ctypes import wintypes
from pathlib import Path
from typing import Callable

from spritelens.logs import get_logger

logger = get_logger("tray")


class TrayIcon:
    """在独立消息线程创建托盘图标，回调只投递轻量动作。"""

    def __init__(self, *, icon_path: str, on_open: Callable[[], None], on_exit: Callable[[], None]) -> None:
        self._icon_path = icon_path
        self._on_open = on_open
        self._on_exit = on_exit
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._hwnd = 0
        self._class_name = ""
        self._wndproc = None

    def start(self) -> None:
        if os.name != "nt":
            return
        if self._thread is not None:
            raise RuntimeError("托盘图标已经启动")
        self._thread = threading.Thread(target=self._run, name="spritelens-tray", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    def stop(self) -> None:
        if self._thread is None:
            return
        if self._hwnd:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.PostMessageW.argtypes = [
                wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
            ]
            user32.PostMessageW.restype = wintypes.BOOL
            user32.PostMessageW(self._hwnd, 0x0010, 0, 0)  # WM_CLOSE
        self._thread.join(timeout=5)
        self._thread = None

    def _run(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        )

        class _WndClass(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.UINT),
                ("style", wintypes.UINT),
                ("lpfnWndProc", callback_type),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
                ("hIconSm", wintypes.HICON),
            ]

        class _NotifyIconData(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT),
                ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128),
            ]

        class _Point(ctypes.Structure):
            _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

        class _Msg(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND),
                ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM),
                ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD),
                ("pt", _Point),
            ]

        WM_TRAY = 0x0400 + 1
        WM_LBUTTONDBLCLK = 0x0203
        WM_RBUTTONUP = 0x0205
        WM_DESTROY = 0x0002
        HWND_MESSAGE = wintypes.HWND(-3)
        NIM_ADD, NIM_DELETE = 0x00000000, 0x00000002
        NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x00000001, 0x00000002, 0x00000004
        MF_STRING, MF_SEPARATOR = 0x0000, 0x0800
        TPM_RETURNCMD, TPM_NONOTIFY = 0x0100, 0x0080

        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.DefWindowProcW.restype = ctypes.c_ssize_t
        user32.RegisterClassExW.argtypes = [ctypes.POINTER(_WndClass)]
        user32.RegisterClassExW.restype = wintypes.ATOM
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p,
        ]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.PostQuitMessage.argtypes = [ctypes.c_int]
        user32.GetMessageW.argtypes = [ctypes.POINTER(_Msg), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.GetMessageW.restype = ctypes.c_int
        user32.TranslateMessage.argtypes = [ctypes.POINTER(_Msg)]
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(_Msg)]
        user32.CreatePopupMenu.restype = wintypes.HMENU
        user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
        user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, ctypes.c_void_p]
        user32.TrackPopupMenu.restype = wintypes.UINT
        user32.DestroyMenu.argtypes = [wintypes.HMENU]
        user32.GetCursorPos.argtypes = [ctypes.POINTER(_Point)]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
        user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.LoadImageW.restype = wintypes.HICON
        shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(_NotifyIconData)]
        shell32.Shell_NotifyIconW.restype = wintypes.BOOL

        def show_menu(hwnd: int) -> None:
            menu = user32.CreatePopupMenu()
            if not menu:
                return
            try:
                user32.AppendMenuW(menu, MF_STRING, 1, "打开主界面")
                user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
                user32.AppendMenuW(menu, MF_STRING, 2, "退出后台监听")
                point = _Point()
                user32.GetCursorPos(ctypes.byref(point))
                user32.SetForegroundWindow(hwnd)
                choice = user32.TrackPopupMenu(menu, TPM_RETURNCMD | TPM_NONOTIFY,
                                               point.x, point.y, 0, hwnd, None)
                if choice == 1:
                    self._on_open()
                elif choice == 2:
                    self._on_exit()
            finally:
                user32.DestroyMenu(menu)

        @callback_type
        def wndproc(hwnd, message, wparam, lparam):
            if message == WM_TRAY:
                if lparam == WM_LBUTTONDBLCLK:
                    self._on_open()
                elif lparam == WM_RBUTTONUP:
                    show_menu(hwnd)
                return 0
            if message == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, message, wparam, lparam)

        self._wndproc = wndproc
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
        hinstance = kernel32.GetModuleHandleW(None)
        self._class_name = f"SpriteLensTray_{os.getpid()}_{id(self)}"
        window_class = _WndClass(
            cbSize=ctypes.sizeof(_WndClass), style=0, lpfnWndProc=wndproc,
            cbClsExtra=0, cbWndExtra=0, hInstance=hinstance, hIcon=None,
            hCursor=None, hbrBackground=None, lpszMenuName=None,
            lpszClassName=self._class_name, hIconSm=None,
        )
        if not user32.RegisterClassExW(ctypes.byref(window_class)):
            logger.exception("注册托盘窗口类失败")
            self._ready.set()
            return
        try:
            self._hwnd = int(user32.CreateWindowExW(
                0, self._class_name, "SpriteLens", 0, 0, 0, 0, 0,
                HWND_MESSAGE, None, hinstance, None,
            ))
            if not self._hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
            icon = user32.LoadImageW(None, self._icon_path, 1, 16, 16, 0x10) if Path(self._icon_path).is_file() else None
            data = _NotifyIconData(
                cbSize=ctypes.sizeof(_NotifyIconData), hWnd=self._hwnd, uID=1,
                uFlags=NIF_MESSAGE | NIF_ICON | NIF_TIP, uCallbackMessage=WM_TRAY,
                hIcon=icon, szTip="小洛探探 - 后台监听",
            )
            if not shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(data)):
                raise ctypes.WinError(ctypes.get_last_error())
            self._ready.set()
            message = _Msg()
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(data))
        except Exception:
            logger.exception("托盘图标启动失败")
            self._ready.set()
        finally:
            if self._hwnd:
                user32.DestroyWindow(self._hwnd)
                self._hwnd = 0
            user32.UnregisterClassW(self._class_name, hinstance)


__all__ = ["TrayIcon"]
