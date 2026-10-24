"""只读附近观察载荷与接口；静态联查使用精确 NPC 映射，不换算距离。"""
from __future__ import annotations

from dataclasses import asdict

from aiohttp import web

from spritelens.domain.pet_marks import observation_marks
from spritelens.domain.static_data import StaticData
from spritelens.services.scene_repository import SceneRepository, SceneSnapshot
from spritelens.web.background import run_blocking
from spritelens.web.pet_media import pet_images

# 雷达半径同样是原始坐标单位；真实流量 p90≈8,881、p99≈8,994，取 10,000
# 可覆盖绝大多数实体，避免旧值 2,000 只画 8%。
DEFAULT_RADAR_RADIUS_RAW = 10000


def nearby_payload(
    snapshot: SceneSnapshot,
    static: StaticData | None = None,
    *,
    radar_radius_raw: int = DEFAULT_RADAR_RADIUS_RAW,
) -> dict:
    data = asdict(snapshot)
    data["uid"] = str(snapshot.uid)
    data["complete"] = False
    data["source"] = "observed_partial"
    data["coordinate_unit"] = "unverified"
    data["mapping_available"] = bool(static and static.scene_mapping_available)
    # 只下发展示半径，不换算米制；前端按原始单位过滤。
    data["radar_radius_raw"] = max(1, int(radar_radius_raw))
    data["actors"] = [dict(asdict(actor), actor_id=str(actor.actor_id)) for actor in snapshot.actors]
    for row in data["actors"]:
        base_id = static.scene_species_id(row["config_id"]) if static and row["config_id"] is not None else None
        species = static.species(base_id) if static and base_id is not None else None
        row["base_id"] = base_id
        row["name"] = species.name if species else f"未收录精灵 · 配置 {row['config_id'] if row['config_id'] is not None else '未知'}"
        row["icon_url"] = pet_images(base_id)["portrait_url"] if species else ""
        row["type_names"] = list(species.type_names) if species else []
        row["marks"] = observation_marks(row["weight"], row["voice"], species.weight_range if species else (0, 0))
        mark_names = {mark["name"] for mark in row["marks"]}
        row["attention"] = "double" if ({"大块头", "小不点"} & mark_names and {"婉转声", "粗嗓门"} & mark_names) else "marked" if mark_names else "normal"
    # 不把本地会话地址暴露到用户功能接口。
    del data["session_id"]
    return data


def register_nearby_routes(
    app: web.Application,
    repository: SceneRepository | None,
    static: StaticData | None = None,
    settings=None,
) -> None:
    def payload() -> dict:
        radius = (
            settings.get_int("nearby.radar_radius_raw", DEFAULT_RADAR_RADIUS_RAW, lo=500, hi=200000)
            if settings is not None
            else DEFAULT_RADAR_RADIUS_RAW
        )
        return nearby_payload(repository.snapshot(), static, radar_radius_raw=radius)

    async def get_nearby(request: web.Request) -> web.Response:
        if repository is None:
            return web.json_response({"error": "当前实例未装配场景观察"}, status=503)
        return web.json_response(await run_blocking(request, payload), headers={"Cache-Control": "no-store"})

    app.router.add_get("/api/nearby", get_nearby)
