"""Npcap 环境检测与安装引导。

一键安装的边界：只做「下载官方安装器 + UAC 提权拉起安装向导」，
不静默安装、不改系统设置——许可条款与安装选项由用户在官方向导中确认
（务必保持默认勾选 WinPcap API-compatible Mode）。
"""

from __future__ import annotations

import ctypes
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
        "或到 https://npcap.com 手动下载（安装时勾选 WinPcap API-compatible Mode）。",
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
        raise RuntimeError("无法从 npcap.com 解析最新版本，请手动安装")
    return f"{NPCAP_DIST_URL}npcap-{version}.exe", version


def download_installer(
    url: str,
    dest_dir: Path,
    *,
    progress_cb=None,
    timeout: float = 30.0,
) -> Path:
    """下载安装器到 dest_dir；progress_cb(0.0~1.0) 可选。返回文件路径。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = url.rsplit("/", 1)[-1]
    dest = dest_dir / filename
    logger.info("下载 Npcap 安装器: %s", url)
    req = urllib.request.Request(url, headers={"User-Agent": "SpriteLens/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        tmp = dest.with_suffix(dest.suffix + ".part")
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
    tmp.replace(dest)
    logger.info("Npcap 安装器下载完成: %s (%d 字节)", dest, done)
    return dest


def launch_installer(path: Path) -> None:
    """UAC 提权拉起官方安装向导（异步返回，向导自行运行）。"""
    if not path.is_file():
        raise RuntimeError(f"安装器不存在: {path}")
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", str(path), None, None, 1)
    if rc <= 32:
        raise RuntimeError(f"安装向导拉起失败（用户取消或权限拒绝），代码 {rc}")
