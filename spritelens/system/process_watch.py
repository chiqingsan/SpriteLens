"""窗口事件驱动的进程启动监听。

任务计划的事件触发器只能订阅「任何进程创建」，每次触发都要新建一个 Python
进程；改成登录后常驻一次、由 WinEvent 的顶层窗口创建回调唤醒后，系统在目标
程序建窗口的那一刻直接叫醒监听线程，空闲时既不轮询也不需要进程创建审计。
"""

from __future__ import annotations

import ctypes
import os
import threading
from ctypes import wintypes

from spritelens.logs import get_logger

logger = get_logger("process_watch")

EVENT_OBJECT_CREATE = 0x8000
WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002
OBJID_WINDOW = 0
WM_QUIT = 0x0012
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_IMAGE_NAME_CAPACITY = 32768

_user32: "ctypes.WinDLL | None" = None
_kernel32: "ctypes.WinDLL | None" = None


def _dlls():
    """按需加载并声明 Win32 原型；同一进程内只声明一次。"""
    global _user32, _kernel32
    if _user32 is not None:
        return _user32, _kernel32
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.GetMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT,
    ]
    user32.GetMessageW.restype = ctypes.c_int
    user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
    user32.UnhookWinEvent.restype = wintypes.BOOL
    user32.PostThreadMessageW.argtypes = [
        wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    ]
    user32.PostThreadMessageW.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    _user32, _kernel32 = user32, kernel32
    return user32, kernel32


class ProcessWindowWatcher:
    """等待目标 exe 创建顶层窗口；只由系统回调唤醒，不做周期扫描。"""

    def __init__(self, process_name: str) -> None:
        self._target = process_name.casefold()
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._hook = 0
        self._callback = None
        self._failed = False

    @property
    def failed(self) -> bool:
        """事件通道是否注册失败；失败时调用方仍可用低频快照兜底。"""
        return self._failed

    def start(self) -> None:
        if os.name != "nt" or self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._pump, name="spritelens-process-watch", daemon=True
        )
        self._thread.start()

    def reset(self) -> None:
        """一轮跟随结束后重新武装，等待游戏下次启动。"""
        self._ready.clear()

    def wait(self, timeout: float | None = None) -> bool:
        return self._ready.wait(timeout)

    def stop(self) -> None:
        thread = self._thread
        if thread is None:
            return
        if self._thread_id:
            user32, _ = _dlls()
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        thread.join(timeout=2)
        self._thread = None

    def _pump(self) -> None:
        user32, kernel32 = _dlls()
        callback_type = ctypes.WINFUNCTYPE(
            None,
            wintypes.HANDLE,   # HWINEVENTHOOK
            wintypes.DWORD,    # event
            wintypes.HWND,     # hwnd
            wintypes.LONG,     # idObject
            wintypes.LONG,     # idChild
            wintypes.DWORD,    # idEventThread
            wintypes.DWORD,    # dwmsEventTime
        )
        user32.SetWinEventHook.argtypes = [
            wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, callback_type,
            wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
        ]
        user32.SetWinEventHook.restype = wintypes.HANDLE
        self._thread_id = kernel32.GetCurrentThreadId()
        # 回调对象必须留在实例上：临时对象被回收时系统仍持有函数指针，
        # 下一次事件会以 STATUS_FATAL_USER_CALLBACK_EXCEPTION 结束进程。
        self._callback = callback_type(self._on_window)
        self._hook = user32.SetWinEventHook(
            EVENT_OBJECT_CREATE, EVENT_OBJECT_CREATE, None, self._callback,
            0, 0, WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS,
        )
        if not self._hook:
            self._failed = True
            logger.error("窗口事件监听注册失败：%s", ctypes.get_last_error())
            return
        try:
            message = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                pass
        except Exception:
            logger.exception("窗口事件监听线程异常")
        finally:
            user32.UnhookWinEvent(self._hook)
            self._hook = 0
            self._thread_id = 0

    def _on_window(self, _hook, _event, hwnd, id_object, id_child, _thread, _time) -> None:
        # 回调里的异常同样会让进程崩溃，整段兜住。
        try:
            if self._ready.is_set() or not hwnd:
                return
            if id_object != OBJID_WINDOW or id_child != 0:
                return
            if self._window_matches(hwnd):
                self._ready.set()
        except Exception:
            logger.exception("窗口事件回调失败")

    def _window_matches(self, hwnd: int) -> bool:
        user32, kernel32 = _dlls()
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return False
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not handle:
            return False
        try:
            buffer = ctypes.create_unicode_buffer(_IMAGE_NAME_CAPACITY)
            size = wintypes.DWORD(_IMAGE_NAME_CAPACITY)
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return False
            return os.path.basename(buffer.value).casefold() == self._target
        finally:
            kernel32.CloseHandle(handle)


__all__ = ["ProcessWindowWatcher"]
