"""C02 只读附近观察接口；不提供列表页面或距离换算。"""
from __future__ import annotations

from dataclasses import asdict

from aiohttp import web

from spritelens.services.scene_repository import SceneRepository, SceneSnapshot
from spritelens.web.background import run_blocking


def nearby_payload(snapshot: SceneSnapshot) -> dict:
    data = asdict(snapshot)
    data["uid"] = str(snapshot.uid)
    data["complete"] = False
    data["source"] = "observed_partial"
    data["coordinate_unit"] = "unverified"
    data["actors"] = [dict(asdict(actor), actor_id=str(actor.actor_id)) for actor in snapshot.actors]
    # 不把本地会话地址暴露到用户功能接口。
    del data["session_id"]
    return data


def register_nearby_routes(app: web.Application, repository: SceneRepository | None) -> None:
    async def get_nearby(request: web.Request) -> web.Response:
        if repository is None:
            return web.json_response({"error": "当前实例未装配场景观察"}, status=503)
        return web.json_response(await run_blocking(request, lambda: nearby_payload(repository.snapshot())))

    app.router.add_get("/api/nearby", get_nearby)
