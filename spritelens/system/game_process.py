"""Windows 游戏进程检测与跟随启动任务。

跟随启动靠登录时拉起一次的常驻监听进程，由窗口事件唤醒采集；本模块只承接
Windows 边界，不把系统命令和 Win32 结构泄漏到业务层。
"""

from __future__ import annotations

import ctypes
import getpass
import os
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path
from xml.sax.saxutils import escape

from spritelens.logs import get_logger
from spritelens.paths import project_root

logger = get_logger("game_process")

GAME_PROCESS_AUDIT_GUIDANCE = (
    "启用「跟随启动」会注册一个登录时自动运行的监听任务；游戏窗口出现后立即开始采集，"
    "不需要管理员权限，也不会开启进程创建审计。"
)
DEFAULT_GAME_PROCESS_NAME = "NRC-Win64-Shipping.exe"
GAME_TASK_NAME = "SpriteLens.GameCapture"

_TH32CS_SNAPPROCESS = 0x00000002
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_SEE_MASK_NOCLOSEPROCESS = 0x00000040
_SW_HIDE = 0
_WAIT_INFINITE = 0xFFFFFFFF
_ERROR_CANCELLED = 1223
_SYNCHRONIZE = 0x00100000
_FALLBACK_POLL_SECONDS = 1.0


class _ShellExecuteInfoW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", wintypes.ULONG),
        ("hwnd", wintypes.HWND),
        ("lpVerb", ctypes.c_wchar_p),
        ("lpFile", ctypes.c_wchar_p),
        ("lpParameters", ctypes.c_wchar_p),
        ("lpDirectory", ctypes.c_wchar_p),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", ctypes.c_wchar_p),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIcon", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


class _ProcessEntry32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def normalize_process_name(value: str) -> str:
    """校验设置中的固定进程文件名，不接受路径或命令行。"""
    name = value.strip()
    if (
        not name
        or len(name) > 260
        or not name.casefold().endswith(".exe")
        or any(char in name for char in ("/", "\\", ":", "\x00"))
    ):
        raise ValueError(f"游戏进程名必须是单独的 exe 文件名，例如 {DEFAULT_GAME_PROCESS_NAME}")
    return name


def is_process_running(process_name: str) -> bool:
    """按 exe 文件名检查当前用户会话可见的进程。"""
    return bool(_process_ids(process_name))


def _process_ids(process_name: str) -> list[int]:
    target = normalize_process_name(process_name).casefold()
    if os.name != "nt":
        return []

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    snapshot = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if snapshot == _INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    found: list[int] = []
    try:
        entry = _ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(_ProcessEntry32W)
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return found
        while True:
            if entry.szExeFile.casefold() == target:
                found.append(int(entry.th32ProcessID))
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                return found
    finally:
        kernel32.CloseHandle(snapshot)


def wait_for_process_exit(process_name: str) -> None:
    """用进程句柄阻塞到同名进程全部退出，不做周期性扫描。

    只有拿不到同步句柄（受保护进程）时才退化为低频检查，避免忙等。
    """
    if os.name != "nt":
        return
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    while True:
        observed = False
        for pid in _process_ids(process_name):
            handle = kernel32.OpenProcess(_SYNCHRONIZE, False, pid)
            if not handle:
                continue
            observed = True
            try:
                kernel32.WaitForSingleObject(handle, _WAIT_INFINITE)
            finally:
                kernel32.CloseHandle(handle)
        if not _process_ids(process_name):
            return
        if not observed:
            logger.debug("游戏进程句柄不可用，退化为低频检查：%s", process_name)
            time.sleep(_FALLBACK_POLL_SECONDS)


def current_app_command(*args: str) -> tuple[str, list[str]]:
    """返回当前源码态/冻结态都可执行的命令与参数。

    源码态优先用同目录的 pythonw.exe：登录时拉起后台监听不应该闪控制台窗口。
    """
    executable = Path(sys.executable).resolve()
    if not (getattr(sys, "frozen", False) or "__compiled__" in globals()):
        windowless = executable.with_name("pythonw.exe")
        if os.name == "nt" and windowless.exists():
            executable = windowless
        return str(executable), [str(project_root() / "main.py"), *args]
    return str(executable), list(args)


def background_task_action(process_name: str) -> tuple[str, list[str]]:
    return current_app_command("--background", "--process-name", normalize_process_name(process_name))


def _task_xml(process_name: str, command: str, arguments: list[str]) -> str:
    user = getpass.getuser()
    domain = os.environ.get("USERDOMAIN", "").strip()
    user_id = f"{domain}\\{user}" if domain else user
    command_line = subprocess.list2cmdline(arguments)
    normalize_process_name(process_name)
    # 登录时拉起一次常驻监听进程，由窗口事件决定何时进入采集；
    # 不再订阅 4688，避免每次进程创建都新建解释器。
    return f'''<?xml version="1.0" encoding="UTF-16"?>
<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task" version="1.4">
  <RegistrationInfo><Description>登录后常驻监听游戏进程，游戏启动时自动开始 SpriteLens 后台采集。</Description></RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{escape(user_id)}</UserId>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(user_id)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>false</StartWhenAvailable>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <AllowHardTerminate>true</AllowHardTerminate>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(command)}</Command>
      <Arguments>{escape(command_line)}</Arguments>
      <WorkingDirectory>{escape(str(project_root()))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
'''


def _run_schtasks(arguments: list[str]) -> None:
    """先直接执行；只有权限不足才请求一次提权。"""
    if os.name != "nt":
        raise OSError("跟随启动任务仅支持 Windows")
    try:
        _run_schtasks_direct(arguments)
        return
    except OSError as exc:
        if not _is_permission_denied(exc):
            raise
    _run_schtasks_elevated(arguments)


def _is_permission_denied(error: OSError) -> bool:
    detail = str(error).casefold()
    markers = ("access is denied", "拒绝访问", "0x80070005", "e_accessdenied")
    return any(marker in detail for marker in markers)


def _run_schtasks_direct(arguments: list[str]) -> None:
    result = subprocess.run(
        ["schtasks.exe", *arguments],
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        capture_output=True,
        text=True,
        encoding="mbcs" if os.name == "nt" else "utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise OSError(f"Windows 任务计划程序操作失败：{detail or result.returncode}")


def _is_user_admin() -> bool:
    if os.name != "nt":
        return False
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.IsUserAnAdmin.argtypes = []
    shell32.IsUserAnAdmin.restype = wintypes.BOOL
    return bool(shell32.IsUserAnAdmin())


def _run_schtasks_elevated(arguments: list[str]) -> None:
    _run_elevated_executable("schtasks.exe", arguments)


def _run_elevated_executable(executable: str, arguments: list[str]) -> None:
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(_ShellExecuteInfoW)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    info = _ShellExecuteInfoW(
        cbSize=ctypes.sizeof(_ShellExecuteInfoW),
        fMask=_SEE_MASK_NOCLOSEPROCESS,
        lpVerb="runas",
        lpFile=executable,
        lpParameters=subprocess.list2cmdline(arguments),
        nShow=_SW_HIDE,
    )
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        error = ctypes.get_last_error()
        if error == _ERROR_CANCELLED:
            raise OSError("用户取消了管理员权限确认")
        raise ctypes.WinError(error)

    try:
        kernel32.WaitForSingleObject(info.hProcess, _WAIT_INFINITE)
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(exit_code)):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel32.CloseHandle(info.hProcess)

    if exit_code.value:
        raise OSError(f"管理员命令执行失败：{executable}（{exit_code.value}）")


def install_game_trigger(process_name: str) -> None:
    """安装/覆盖登录时拉起常驻监听的跟随任务。"""
    command, arguments = background_task_action(process_name)
    xml = _task_xml(process_name, command, arguments)
    with tempfile.NamedTemporaryFile(prefix="spritelens-task-", suffix=".xml", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        temporary.write_text(xml, encoding="utf-16")
        _run_schtasks(["/Create", "/TN", GAME_TASK_NAME, "/XML", str(temporary), "/F"])
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def remove_game_trigger() -> None:
    """结束常驻监听并移除跟随任务；不存在时视为已移除。"""
    if os.name != "nt":
        raise OSError("跟随启动任务仅支持 Windows")
    if not _task_exists():
        return
    # 任务已被删除也要先停掉正在运行的监听进程，否则它会继续等到下次登录。
    try:
        _run_schtasks_direct(["/End", "/TN", GAME_TASK_NAME])
    except OSError:
        logger.debug("跟随任务当前没有运行实例：%s", GAME_TASK_NAME)
    _run_schtasks(["/Delete", "/TN", GAME_TASK_NAME, "/F"])


def _task_exists() -> bool:
    result = subprocess.run(
        ["schtasks.exe", "/Query", "/TN", GAME_TASK_NAME],
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        capture_output=True,
        text=True,
        encoding="mbcs" if os.name == "nt" else "utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode == 0:
        return True
    detail = (result.stdout + result.stderr).casefold()
    missing_markers = ("cannot find the file specified", "does not exist", "找不到", "不存在")
    return not any(marker in detail for marker in missing_markers)


__all__ = [
    "GAME_PROCESS_AUDIT_GUIDANCE",
    "DEFAULT_GAME_PROCESS_NAME",
    "GAME_TASK_NAME",
    "background_task_action",
    "current_app_command",
    "install_game_trigger",
    "is_process_running",
    "normalize_process_name",
    "remove_game_trigger",
    "wait_for_process_exit",
]
