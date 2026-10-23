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
    "启用「跟随启动」时会自动请求管理员权限并开启 Windows 进程创建审计（事件 4688）；"
    "如果电脑的组策略禁止修改，请在本地安全策略中手动开启。"
)
DEFAULT_GAME_PROCESS_NAME = "NRC-Win64-Shipping.exe"
GAME_TASK_NAME = "SpriteLens.GameCapture"
PROCESS_CREATION_AUDIT_SUBCATEGORY = "{0CCE922B-69AE-11D9-BED3-505054503030}"

_TH32CS_SNAPPROCESS = 0x00000002
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_SEE_MASK_NOCLOSEPROCESS = 0x00000040
_SW_HIDE = 0
_WAIT_INFINITE = 0xFFFFFFFF
_ERROR_CANCELLED = 1223


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
    if not _is_user_admin():
        _run_schtasks_elevated(arguments)
        return
    _run_schtasks_direct(arguments)


def _run_schtasks_direct(arguments: list[str]) -> None:
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


def _enable_process_creation_audit() -> None:
    result = subprocess.run(
        [
            "auditpol.exe",
            "/set",
            f"/subcategory:{PROCESS_CREATION_AUDIT_SUBCATEGORY}",
            "/success:enable",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise OSError(f"Windows 进程创建审计开启失败：{detail or result.returncode}")


def _powershell_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _run_game_trigger_setup_elevated(task_arguments: list[str]) -> None:
    script_lines = [
        "$ErrorActionPreference = 'Stop'",
        f"& auditpol.exe '/set' '/subcategory:{PROCESS_CREATION_AUDIT_SUBCATEGORY}' '/success:enable'",
        "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }",
        "$taskArguments = @(",
        *[f"    {_powershell_literal(argument)}" for argument in task_arguments],
        ")",
        "& schtasks.exe @taskArguments",
        "exit $LASTEXITCODE",
    ]
    with tempfile.NamedTemporaryFile(prefix="spritelens-setup-", suffix=".ps1", delete=False) as handle:
        script = Path(handle.name)
    try:
        script.write_text("\n".join(script_lines) + "\n", encoding="utf-8-sig")
        _run_elevated_executable(
            "powershell.exe",
            ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        )
    finally:
        try:
            script.unlink()
        except FileNotFoundError:
            pass


def install_game_trigger(process_name: str) -> None:
    """安装/覆盖按进程创建事件触发的后台任务。"""
    command, arguments = background_task_action(process_name)
    xml = _task_xml(process_name, command, arguments)
    with tempfile.NamedTemporaryFile(prefix="spritelens-task-", suffix=".xml", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        temporary.write_text(xml, encoding="utf-16")
        task_arguments = ["/Create", "/TN", GAME_TASK_NAME, "/XML", str(temporary), "/F"]
        if _is_user_admin():
            _enable_process_creation_audit()
            _run_schtasks_direct(task_arguments)
        else:
            _run_game_trigger_setup_elevated(task_arguments)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def remove_game_trigger() -> None:
    """移除按需任务；不存在时视为已移除。"""
    if os.name != "nt":
        raise OSError("按需游戏启动任务仅支持 Windows")
    if not _task_exists():
        return
    _run_schtasks(["/Delete", "/TN", GAME_TASK_NAME, "/F"])


def _task_exists() -> bool:
    result = subprocess.run(
        ["schtasks.exe", "/Query", "/TN", GAME_TASK_NAME],
        capture_output=True,
        text=True,
        encoding="utf-8",
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
    "PROCESS_CREATION_AUDIT_SUBCATEGORY",
    "background_task_action",
    "current_app_command",
    "install_game_trigger",
    "is_process_running",
    "normalize_process_name",
    "remove_game_trigger",
]
