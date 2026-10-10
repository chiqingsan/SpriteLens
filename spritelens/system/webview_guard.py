"""WebView2 运行时预检测与缺失引导。

pywebview 依赖 Edge WebView2（Evergreen Runtime）渲染。缺运行时时
`webview.start()` 才失败，用户看到的是白屏或进程退出——这里在开壳前
主动检测，缺失时弹原生对话框引导安装（对标同类产品的 webview_guard）。

检测顺序（微软官方判定标准）：
1. 环境变量 WEBVIEW2_RUNTIME_PATH 指定的目录存在 webview2.dll；
2. 注册表 Evergreen 常驻键的 pv 值（HKLM 与 HKCU 各查一遍，WOW6432 视图）。
"""

from __future__ import annotations

import json
import os
import winreg
from datetime import datetime, timezone
from pathlib import Path

from spritelens.logs import get_logger

logger = get_logger("webview_guard")

# Evergreen Runtime 的包标识（微软文档固定值）
_CLIENT_ID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
_REGISTRY_VIEWS = (
    (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
    (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
    (winreg.HKEY_CURRENT_USER, winreg.KEY_WOW64_32KEY),
    (winreg.HKEY_CURRENT_USER, winreg.KEY_WOW64_64KEY),
)
DOWNLOAD_URL = "https://developer.microsoft.com/microsoft-edge/webview2/#download-section"

GUIDE_MESSAGE = (
    "没有检测到可用的 Microsoft Edge WebView2 运行环境，或该组件已损坏。\n\n"
    "这是界面运行所需的系统组件（Win10/11 一般预装）。\n\n"
    "点击「是」打开微软官方页面，安装 Evergreen WebView2 Runtime 后重新打开小洛探探。\n"
    "点击「否」退出，本次没有修改任何数据。"
)


def _runtime_path_from_env() -> str | None:
    custom = os.environ.get("WEBVIEW2_RUNTIME_PATH")
    if custom and (Path(custom) / "webview2.dll").is_file():
        return custom
    return None


def _runtime_version_from_registry() -> str | None:
    for hive, view in _REGISTRY_VIEWS:
        try:
            with winreg.OpenKey(hive, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{_CLIENT_ID}", 0, winreg.KEY_READ | view) as key:
                value, value_type = winreg.QueryValueEx(key, "pv")
                if value_type == winreg.REG_SZ and value:
                    return str(value)
        except OSError:
            continue
    return None


def installed_runtime_version() -> str | None:
    """返回可用 WebView2 版本号；不可用返回 None。"""
    custom = _runtime_path_from_env()
    if custom:
        return "custom:" + custom
    return _runtime_version_from_registry()


def _write_probe_log(log_dir: Path | None, version: str | None) -> None:
    if log_dir is None:
        return
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "webview-startup.json").write_text(
            json.dumps(
                {
                    "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "runtime_version": version,
                    "env_override": os.environ.get("WEBVIEW2_RUNTIME_PATH") or "",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.debug("WebView2 探测日志写入失败: %s", exc)


def ensure_webview2(log_dir: Path | None = None) -> bool:
    """开壳前检测；缺失时弹原生对话框引导安装。返回是否可以继续启动。"""
    version = installed_runtime_version()
    if version is not None:
        return True

    logger.error("WebView2 运行时不可用")
    _write_probe_log(log_dir, None)
    import ctypes

    try:
        choice = ctypes.windll.user32.MessageBoxW(
            None, GUIDE_MESSAGE, "小洛探探：需要安装 WebView2", 0x34  # MB_YESNO | MB_ICONWARNING | MB_DEFBUTTON1
        )
    except Exception as exc:  # noqa: BLE001 - 对话框失败也按"否"处理
        logger.warning("WebView2 引导对话框失败: %s", exc)
        choice = 7  # IDNO
    if choice == 6:  # IDYES
        import webbrowser

        webbrowser.open(DOWNLOAD_URL)
    return False


__all__ = ["DOWNLOAD_URL", "ensure_webview2", "installed_runtime_version"]
