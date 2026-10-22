"""Npcap 环境检测与安装引导。

一键安装的边界：只做「下载官方安装器 + 等待官方安装向导完成」，
不静默安装、不改系统设置——许可条款与安装选项由用户在官方向导中确认
（务必保持默认勾选 WinPcap API-compatible Mode）。
"""

from __future__ import annotations

import os
import re
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from spritelens.logs import get_logger

logger = get_logger("environment")

NPCAP_DIST_URL = "https://npcap.com/dist/"
# x64 Npcap 的标准安装位置；System32 下的 wpcap.dll 是 WinPcap 兼容模式的入口
_NPCAP_PATH_CANDIDATES = (
    r"C:\Windows\System32\Npcap\wpcap.dll",
    r"C:\Windows\SysWOW64\Npcap\wpcap.dll",
    r"C:\Windows\System32\wpcap.dll",
)
_DOWNLOAD_CHUNK = 64 * 1024
_POWERSHELL_EXE = "powershell.exe"
_MANUAL_INSTALL_URL = "https://npcap.com/#download"


@dataclass(frozen=True)
class NpcapReport:
    """检测结果与用户可读说明。"""

    installed: bool
    wpcap_path: str | None
    message: str
    rsc_enabled: bool = False
    rsc_adapter: str = ""


def check_npcap(
    *,
    search_paths: tuple[str, ...] | None = None,
    check_rsc=None,
    quick: bool = False,
) -> NpcapReport:
    """探测 Npcap：查 wpcap.dll 存在性 + RSC 状态（RSC 会导致入站数据包抓不到）。

    RSC（接收段合并）开启时，网卡把入站 TCP 数据合并成大段，Npcap 经常
    看不到这些包——症状是"小包（ACK/心跳）能抓到、业务数据包消失"，
    且间歇性出现。抓包机应禁用 RSC（Npcap 官方建议）。

    quick=True 时只做文件存在性检查（毫秒级），跳过 RSC 的 PowerShell
    探活（实测约 1.8s）——启动路径用它先拿到 installed 结论，RSC 结果
    由调用方异步补齐（见 CaptureViewModel 的 npcap-probe 线程）。
    """
    candidates = search_paths or _NPCAP_PATH_CANDIDATES
    rsc_probe = check_rsc if check_rsc is not None else _check_rsc
    for candidate in candidates:
        if Path(candidate).is_file():
            if quick:
                return NpcapReport(
                    installed=True,
                    wpcap_path=candidate,
                    message=f"已检测到 Npcap（{candidate}），正在检查网卡 RSC…",
                )
            rsc_enabled, rsc_adapter = rsc_probe()
            if rsc_enabled:
                return NpcapReport(
                    installed=True,
                    wpcap_path=candidate,
                    message=f"已检测到 Npcap（{candidate}），但网卡「{rsc_adapter}」开启了 RSC"
                    "（接收段合并）——入站数据包会被合并导致抓不到。请点「一键禁用 RSC」"
                    "或以管理员运行: Disable-NetAdapterRsc -Name \"" + rsc_adapter + "\"",
                    rsc_enabled=True,
                    rsc_adapter=rsc_adapter,
                )
            return NpcapReport(
                installed=True,
                wpcap_path=candidate,
                message=f"已检测到 Npcap（{candidate}），RSC 已关闭，抓包环境正常",
            )
    return NpcapReport(
        installed=False,
        wpcap_path=None,
        message="未检测到 Npcap（抓包驱动），无法采集网络流量。可点击「一键安装」，"
        f"或到 {_MANUAL_INSTALL_URL} 手动下载（安装时勾选 WinPcap API-compatible Mode）。",
    )


def _no_window_kwargs() -> dict:
    """从 GUI 进程调子进程时不弹控制台黑窗。

    打包成 windowed exe 后（或 pythonw 启动时）自身没有控制台，此时
    subprocess 默认会新建一个控制台窗口闪一下。STARTUPINFO + SW_HIDE
    是标准做法；非 Windows 平台返回空字典。
    """
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {"startupinfo": startupinfo, "creationflags": subprocess.CREATE_NO_WINDOW}


def _run_powershell(script: str, *, timeout: float) -> str:
    """执行 PowerShell 并返回 stdout（隐藏窗口；失败返回空串）。"""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            timeout=timeout,
            text=True,
            encoding="utf-8",
            errors="replace",
            **_no_window_kwargs(),
        )
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        logger.debug("PowerShell 调用失败: %s", exc)
        return ""
    return out.stdout or ""


def _check_rsc() -> tuple[bool, str]:
    """检查所有物理网卡的 IPv4 RSC；任一开启即返回 (True, 网卡名)。"""
    import json as _json

    stdout = _run_powershell(
        "Get-NetAdapterRsc | ConvertTo-Json -Compress",
        timeout=15,
    )
    try:
        data = _json.loads(stdout) if stdout.strip() else []
    except ValueError as exc:
        logger.debug("RSC 检测结果无法解析（视为未开启）: %s", exc)
        return False, ""
    if isinstance(data, dict):
        data = [data]
    for item in data or []:
        try:
            if item.get("IPv4Enabled") and item.get("Name"):
                return True, str(item["Name"])
        except AttributeError as exc:
            logger.debug("RSC 条目结构异常（跳过）: %s", exc)
    return False, ""


def disable_rsc(adapter: str) -> None:
    """禁用指定网卡的 RSC（需管理员权限；内部会触发 UAC 提权窗口）。"""
    script = (
        f"Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile -Command \""
        f'Disable-NetAdapterRsc -Name "{adapter}"\'"'
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            timeout=120,
            check=False,
            **_no_window_kwargs(),
        )
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        logger.warning("禁用 RSC 失败: %s", exc)


def parse_dist_page(html: str) -> str | None:
    """从 npcap.com/dist/ 页面解析最新版本号；无匹配返回 None。"""
    versions = re.findall(r"npcap-(\d+(?:\.\d+)+)\.exe", html)
    if not versions:
        return None
    latest = max(versions, key=lambda v: tuple(int(p) for p in v.split(".")))
    return latest


def resolve_latest_installer(*, timeout: float = 15.0) -> tuple[str, str]:
    """返回 (下载地址, 版本号)；页面不可解析时抛 RuntimeError。"""
    with urllib.request.urlopen(NPCAP_DIST_URL, timeout=timeout) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    version = parse_dist_page(html)
    if version is None:
        raise RuntimeError(f"无法从 npcap.com 解析最新版本，请到 {_MANUAL_INSTALL_URL} 手动安装")
    return f"{NPCAP_DIST_URL}npcap-{version}.exe", version


def download_installer(
    url: str,
    dest_dir: Path,
    *,
    progress_cb=None,
    timeout: float = 30.0,
) -> Path:
    """下载安装器到 dest_dir；PowerShell 失败时回退 urllib。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = url.rsplit("/", 1)[-1]
    dest = dest_dir / filename
    tmp = dest.with_suffix(dest.suffix + ".part")
    logger.info("下载 Npcap 安装器: %s", url)
    try:
        if progress_cb:
            progress_cb(0.0)
        _download_with_powershell(url, tmp, timeout=timeout)
        _validate_installer(tmp)
        tmp.replace(dest)
        if progress_cb:
            progress_cb(1.0)
        logger.info("Npcap 安装器下载完成（PowerShell）: %s (%d 字节)", dest, dest.stat().st_size)
        return dest
    except Exception as powershell_exc:  # noqa: BLE001 - fallback is the contract
        _remove_partial(tmp)
        logger.warning("PowerShell 下载 Npcap 失败，回退 Python: %s", powershell_exc)

    try:
        result = _download_with_python(
            url,
            dest,
            tmp,
            progress_cb=progress_cb,
            timeout=timeout,
        )
        logger.info("Npcap 安装器下载完成（Python）: %s (%d 字节)", result, result.stat().st_size)
        return result
    except Exception as python_exc:  # noqa: BLE001 - expose both paths to the user
        _remove_partial(tmp)
        raise RuntimeError(
            "PowerShell 与 Python 下载均失败："
            f"{python_exc}。请到 {_MANUAL_INSTALL_URL} 手动下载安装。"
        ) from python_exc


def _download_with_powershell(url: str, tmp: Path, *, timeout: float) -> None:
    """用 PowerShell 写入 .part；校验和原子移动由 Python 完成。"""
    script = (
        "$ErrorActionPreference='Stop'; "
        "$ProgressPreference='SilentlyContinue'; "
        f"Invoke-WebRequest -UseBasicParsing -Uri {_ps_quote(url)} "
        f"-OutFile {_ps_quote(str(tmp))}"
    )
    subprocess.run(
        [_POWERSHELL_EXE, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        timeout=timeout,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
        **_no_window_kwargs(),
    )


def _download_with_python(
    url: str,
    dest: Path,
    tmp: Path,
    *,
    progress_cb=None,
    timeout: float,
) -> Path:
    req = urllib.request.Request(url, headers={"User-Agent": "SpriteLens/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            with tmp.open("wb") as fh:
                while True:
                    chunk = resp.read(_DOWNLOAD_CHUNK)
                    if not chunk:
                        break
                    fh.write(chunk)
                    done += len(chunk)
                    if progress_cb and total:
                        progress_cb(min(1.0, done / total))
        _validate_installer(tmp)
        tmp.replace(dest)
        if progress_cb:
            progress_cb(1.0)
        return dest
    finally:
        _remove_partial(tmp)


def _validate_installer(path: Path) -> None:
    """拒绝空文件和非 Windows PE，避免把错误页交给安装器。"""
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError("下载文件为空或不存在")
    with path.open("rb") as fh:
        if fh.read(2) != b"MZ":
            raise RuntimeError("下载文件不是 Windows PE 安装器")


def _remove_partial(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.debug("无法删除不完整安装器: %s", path, exc_info=True)


def _ps_quote(value: str) -> str:
    """PowerShell 单引号字符串转义（路径和 URL 均来自本地/官方源）。"""
    return "'" + value.replace("'", "''") + "'"


def launch_installer(path: Path) -> int | None:
    """运行官方安装向导并等待退出；PowerShell 失败时回退原生进程。"""
    if not path.is_file():
        raise RuntimeError(f"安装器不存在: {path}")
    _validate_installer(path)
    try:
        return _launch_with_powershell(path)
    except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        logger.warning("PowerShell 启动 Npcap 安装器失败，回退原生进程: %s", exc)
    try:
        completed = subprocess.run([str(path)], check=False)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"安装向导拉起失败：{exc}") from exc
    return completed.returncode


def _launch_with_powershell(path: Path) -> int | None:
    script = (
        "$ErrorActionPreference='Stop'; "
        f"$process=Start-Process -FilePath {_ps_quote(str(path))} -Wait -PassThru; "
        "Write-Output ('SPRITELENS_EXIT:' + $process.ExitCode)"
    )
    completed = subprocess.run(
        [_POWERSHELL_EXE, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        timeout=None,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
        **_no_window_kwargs(),
    )
    for line in (completed.stdout or "").splitlines():
        if line.startswith("SPRITELENS_EXIT:"):
            return int(line.split(":", 1)[1].strip())
    return None
