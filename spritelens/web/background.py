"""受控的同步后台任务入口。

生产请求由 LocalServer 注入的 runner 托管，关闭服务时会等待这些任务结束。
独立路由单测没有组合根时才退回本地 task，避免把测试装配契约带进业务代码。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from aiohttp import web

RUN_BLOCKING: web.AppKey[Callable] = web.AppKey("run_blocking")


async def run_blocking(request: web.Request, function: Callable, *args, **kwargs):
    runner = request.app.get(RUN_BLOCKING)
    if runner is not None:
        return await runner(function, *args, **kwargs)
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    return await asyncio.shield(task)


__all__ = ["RUN_BLOCKING", "run_blocking"]
