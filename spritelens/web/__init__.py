"""Web 层：本地 HTTP 服务 + pywebview 窗口（阶段 B 的目标承载形态）。

形态与竞品（蛋神助手）一致：单进程，pywebview 用系统 WebView2 开窗，
前端由本地 aiohttp 服务提供（仅回环 + 启动 token 鉴权）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from spritelens.web.run import run_web
    from spritelens.web.server import LocalServer

__all__ = ["LocalServer", "run_web"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        module = "spritelens.web.run" if name == "run_web" else "spritelens.web.server"
        import importlib

        return getattr(importlib.import_module(module), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
