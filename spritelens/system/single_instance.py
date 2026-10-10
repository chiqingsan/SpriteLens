"""单实例控制：命名互斥锁（唯一性）+ 命名事件（唤醒已有窗口）。

为什么需要：抓包引擎与监听会话是独占资源。重复启动会出现两个进程同时抓同一
网卡、写同一份 SQLite 与事件日志，数据互相干扰且用户不易察觉。允许多开没有
合理场景，因此限定单实例：第二次启动不报错，而是把已有窗口唤到前台。

实现参考姊妹项目 meow toolkit 的 windows.py：
- `CreateMutexW` 拿到命名互斥锁；返回 `ERROR_ALREADY_EXISTS` 说明已有实例；
- 已有实例创建命名事件并轮询；新进程 `SetEvent` 唤醒它。

只用标准库 ctypes，不引入新依赖；非 Windows 平台优雅降级（不做限制，不影响开发）。
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

# 命名互斥锁/事件名：带应用名前缀避免与其他工具撞名
MUTEX_NAME = "SpriteLens.SingleInstance.Mutex"
ACTIVATION_EVENT_NAME = "SpriteLens.SingleInstance.Activate"

ERROR_ALREADY_EXISTS = 183
WAIT_OBJECT_0 = 0
EVENT_MODIFY_STATE = 0x0002
SW_RESTORE = 9

# 仅在 Windows 上加载内核库；其他平台下面各函数走降级分支
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True) if sys.platform == "win32" else None
_user32 = ctypes.WinDLL("user32", use_last_error=True) if sys.platform == "win32" else None

if _kernel32 is not None:
    _kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    _kernel32.CreateMutexW.restype = wintypes.HANDLE
    _kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    _kernel32.OpenEventW.restype = wintypes.HANDLE
    _kernel32.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    _kernel32.CreateEventW.restype = wintypes.HANDLE
    _kernel32.SetEvent.argtypes = [wintypes.HANDLE]
    _kernel32.SetEvent.restype = wintypes.BOOL
    _kernel32.ResetEvent.argtypes = [wintypes.HANDLE]
    _kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.GetCurrentProcessId.restype = wintypes.DWORD

if _user32 is not None:
    _user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    _user32.SetForegroundWindow.restype = wintypes.BOOL
    _user32.BringWindowToTop.argtypes = [wintypes.HWND]
    _user32.BringWindowToTop.restype = wintypes.BOOL


class SingleInstanceGuard:
    """单实例守卫：首个实例持有互斥锁，重复启动负责唤醒。

    用法（首实例）：
        guard = SingleInstanceGuard()
        if not guard.acquire():
            guard.notify_existing()   # 已有实例，唤醒它后退出
            return 0
        # ... 启动 UI；把 guard.activation_handle 交给窗口轮询 ...
        guard.close()                 # 退出时释放（进程退出也会自动释放）
    """

    def __init__(self) -> None:
        self._mutex_handle: int | None = None
        self._event_handle: int | None = None

    # -- 首实例：抢锁 / 建事件 / 消费唤醒 ---------------------------------
    def acquire(self) -> bool:
        """尝试成为唯一实例；返回 True 表示抢到锁。"""
        if _kernel32 is None:
            return True
        handle = _kernel32.CreateMutexW(None, True, MUTEX_NAME)
        if not handle:
            # 创建失败（极端情况）按可启动处理，不阻断用户使用
            return True
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            _kernel32.CloseHandle(handle)
            return False
        self._mutex_handle = int(handle)
        return True

    def create_activation_event(self) -> int | None:
        """创建唤醒事件（首实例在自己启动时调用一次）。"""
        if _kernel32 is None:
            return None
        handle = _kernel32.CreateEventW(None, True, False, ACTIVATION_EVENT_NAME)
        self._event_handle = int(handle) if handle else None
        return self._event_handle

    def consume_activation(self, handle: int | None) -> bool:
        """唤醒事件已触发则消费并返回 True（由 UI 定时器轮询调用）。"""
        if _kernel32 is None or not handle:
            return False
        if _kernel32.WaitForSingleObject(handle, 0) != WAIT_OBJECT_0:
            return False
        _kernel32.ResetEvent(handle)
        return True

    # -- 重复启动：唤醒已有实例后退出 -------------------------------------
    def notify_existing(self) -> bool:
        """通知已运行实例显示窗口；返回是否投递成功。"""
        if _kernel32 is None:
            return False
        handle = _kernel32.OpenEventW(EVENT_MODIFY_STATE, False, ACTIVATION_EVENT_NAME)
        if not handle:
            return False
        try:
            return bool(_kernel32.SetEvent(handle))
        finally:
            _kernel32.CloseHandle(handle)

    @staticmethod
    def force_foreground(hwnd: int) -> bool:
        """对目标窗口强制置顶。

        为什么需要三重兜底：Windows 有前台激活锁，非前台进程直接调
        SetForegroundWindow 会被系统忽略（实测窗口未提到前台）。这里
        先 ShowWindow(SW_RESTORE) 解除最小化，再 SetForegroundWindow，
        最后 BringWindowToTop 兜底。
        """
        if _user32 is None or not hwnd:
            return False
        _user32.ShowWindow(wintypes.HWND(hwnd), SW_RESTORE)
        foreground = bool(_user32.SetForegroundWindow(wintypes.HWND(hwnd)))
        _user32.BringWindowToTop(wintypes.HWND(hwnd))
        return foreground

    # -- 生命周期 -------------------------------------------------------
    def close(self) -> None:
        """释放句柄（互斥锁随进程退出自动释放，这里做显式清理）。"""
        if _kernel32 is None:
            return
        if self._event_handle:
            _kernel32.CloseHandle(self._event_handle)
            self._event_handle = None
        if self._mutex_handle:
            _kernel32.CloseHandle(self._mutex_handle)
            self._mutex_handle = None


__all__ = [
    "ACTIVATION_EVENT_NAME",
    "MUTEX_NAME",
    "SingleInstanceGuard",
]
