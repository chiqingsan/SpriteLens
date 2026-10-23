"""Windows 游戏进程检测与按需任务计划程序。

后台采集由 Windows 进程创建事件按需拉起；本模块只承接 Windows 边界，
不把系统命令和 Win32 结构泄漏到业务层。
"""

from __future__ import annotations

import ctypes
import getpass
import os
import subprocess
import sys
import tempfile
from ctypes import wintypes
from pathlib import Path
from xml.sax.saxutils import escape

from spritelens.logs import get_logger
from spritelens.paths import project_root

logger = get_logger("game_process")

GAME_PROCESS_AUDIT_GUIDANCE = (
    "需要 Windows 安全日志记录进程创建事件 4688；"
    "可用 auditpol /set /subcategory:\"Process Creation\" /success:enable 启用。"
)
DEFAULT_GAME_PROCESS_NAME = "NRC-Win64-Shipping.exe"
GAME_TASK_NAME = "SpriteLens.GameCapture"

_TH32CS_SNAPPROCESS = 0x00000002
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


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
    target = normalize_process_name(process_name).casefold()
    if os.name != "nt":
        return False

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
    try:
        entry = _ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(_ProcessEntry32W)
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return False
        while True:
            if entry.szExeFile.casefold() == target:
                return True
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                return False
    finally:
        kernel32.CloseHandle(snapshot)


def current_app_command(*args: str) -> tuple[str, list[str]]:
    """返回当前源码态/冻结态都可执行的命令与参数。"""
    executable = str(Path(sys.executable).resolve())
    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        return executable, list(args)
    return executable, [str(project_root() / "main.py"), *args]


def background_task_action(process_name: str) -> tuple[str, list[str]]:
    return current_app_command("--background", "--process-name", normalize_process_name(process_name))


def _task_xml(process_name: str, command: str, arguments: list[str]) -> str:
    user = getpass.getuser()
    domain = os.environ.get("USERDOMAIN", "").strip()
    user_id = f"{domain}\\{user}" if domain else user
    command_line = subprocess.list2cmdline(arguments)
    normalize_process_name(process_name)
    # Windows 事件 XPath 不支持 contains 等字符串函数；4688 触发后由
    # background_run 用 Win32 进程枚举按 exe 文件名做最终过滤。
    subscription = (
        "<QueryList><Query Id=\"0\" Path=\"Security\">"
        "<Select Path=\"Security\">"
        "*[System[(EventID=4688)] and EventData[Data[@Name='NewProcessName']]]"
        "</Select></Query></QueryList>"
    )
    return f'''<?xml version="1.0" encoding="UTF-16"?>
<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task" version="1.4">
  <RegistrationInfo><Description>游戏进程出现后按需启动 SpriteLens 后台采集。</Description></RegistrationInfo>
  <Triggers>
    <EventTrigger>
      <Enabled>true</Enabled>
      <Subscription><![CDATA[{subscription}]]></Subscription>
    </EventTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(user_id)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <StartWhenAvailable>true</StartWhenAvailable>
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
    if os.name != "nt":
        raise OSError("按需游戏启动任务仅支持 Windows")
    result = subprocess.run(
        ["schtasks.exe", *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise OSError(f"Windows 任务计划程序操作失败：{detail or result.returncode}")


def install_game_trigger(process_name: str) -> None:
    """安装/覆盖按进程创建事件触发的后台任务。"""
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
    """移除按需任务；不存在时视为已移除。"""
    if os.name != "nt":
        raise OSError("按需游戏启动任务仅支持 Windows")
    result = subprocess.run(
        ["schtasks.exe", "/Delete", "/TN", GAME_TASK_NAME, "/F"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode and "does not exist" not in (result.stdout + result.stderr).casefold():
        detail = (result.stderr or result.stdout).strip()
        raise OSError(f"Windows 任务计划程序删除失败：{detail or result.returncode}")


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
]
