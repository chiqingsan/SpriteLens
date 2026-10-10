"""活跃网卡识别与排序：把"真正在用"的网卡排到设备列表前面。

抓包工具最常见痛点：设备下拉第一项是无关虚拟网卡（蓝牙/回环/WAN Miniport），
用户必须自己逐个试。这里用 `Get-NetAdapter` 查 Status=Up 的物理/虚拟网卡名，
把名称能对上的设备排前面（对标同类产品的 active_network_descriptions 思路）。

纯函数 + 可注入的查询函数，测试不跑 PowerShell。
"""

from __future__ import annotations

import os
import subprocess

from spritelens.logs import get_logger

logger = get_logger("nic_rank")


def _no_window_kwargs() -> dict:
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {"startupinfo": startupinfo, "creationflags": subprocess.CREATE_NO_WINDOW}


def _query_active_adapters(timeout: float = 6.0) -> list[str]:
    """查当前 Up 状态的网卡名（PowerShell）；失败返回空表。"""
    try:
        out = subprocess.run(
            [
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                "Get-NetAdapter | Where-Object { $_.Status -eq 'Up' } "
                "| Select-Object -ExpandProperty Name",
            ],
            capture_output=True, timeout=timeout, text=True,
            encoding="utf-8", errors="replace", **_no_window_kwargs(),
        )
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        logger.debug("活跃网卡查询失败: %s", exc)
        return []
    return [line.strip() for line in (out.stdout or "").splitlines() if line.strip()]


def _name_matches(description: str, active_names: list[str]) -> bool:
    """设备描述与活跃网卡名的宽松匹配（双方都常带前缀/序号差异）。"""
    desc = description.lower().replace(" ", "")
    for name in active_names:
        clean = name.lower().replace(" ", "")
        if clean and (clean in desc or desc in clean):
            return True
    return False


def rank_ifaces(
    ifaces: list[tuple[str, str]],
    active_names: list[str] | None = None,
) -> list[tuple[str, str]]:
    """把描述匹配活跃网卡的项排到前面；其余保持原相对顺序（稳定排序）。"""
    if active_names is None:
        active_names = _query_active_adapters()
    if not active_names:
        return ifaces

    def sort_key(item: tuple[str, str]) -> int:
        return 0 if _name_matches(item[1], active_names) else 1

    return sorted(ifaces, key=sort_key)


__all__ = ["rank_ifaces"]
