"""只读附近观察载荷与接口；静态联查使用精确 NPC 映射，不换算距离。"""
from __future__ import annotations

import os
import json

from aiohttp import web

from spritelens.domain.pet_marks import observation_marks
from spritelens.domain.static_data import StaticData
from spritelens.services.scene_repository import DEFAULT_RADAR_RADIUS_RAW, SceneRepository, SceneSnapshot
from spritelens.web.background import run_blocking
from spritelens.web.pet_media import pet_images

# 仅调试用的原始坐标读数开关：现场地标校准时打开，正常启动不显示未校准数值。
DEBUG_COORDINATES_ENV = "SPRITELENS_DEBUG_COORDS"


def debug_coordinates_enabled() -> bool:
    """环境变量只接受 1/true/yes/on；其余值一律视为关闭。"""
    return os.environ.get(DEBUG_COORDINATES_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def coverage_payload(snapshot: SceneSnapshot) -> dict | None:
    """本次运行足迹：只下发格索引，不含半径与圆心。

    无资源或无格时返回 None（前端不画覆盖）；uid/map_id 让前端在切号、
    换图后拒绝旧数据，而不是把旧足迹画到新底图上。
    """
    coverage = snapshot.coverage
    if coverage is None or snapshot.resource_id is None:
        return None
    return {
        "uid": str(snapshot.uid),
        "map_id": str(snapshot.resource_id),
        "layer": "visit",
        "scope": "history" if coverage.persistent else "session",
        "revision": coverage.revision,
        "cell_size": coverage.cell_size,
        "cells": coverage.cells,
        "updated_at": coverage.updated_at,
        "radius_raw": coverage.radius,
        "rows": [list(row) for row in coverage.rows],
    }


def nearby_payload(
    snapshot: SceneSnapshot,
    static: StaticData | None = None,
    *,
    radar_radius_raw: int = DEFAULT_RADAR_RADIUS_RAW,
    type_icons: dict[str, str] | None = None,
) -> dict:
    # 只浅拷贝顶层字段：asdict 会递归深拷贝全部实体（300 实体约多花 0.9ms/次，
    # 见 docs/reviews/2026-10-27-nearby-performance-review.md P1）；下游字段
    # 都是只读使用或显式改写，不需要第二份深拷贝。
    data = dict(vars(snapshot))
    data["uid"] = str(snapshot.uid)
    # 场景与实例归属供地图模式定位底图；64 位实例号超出 JS 安全整数，统一按字符串下发。
    data["resource_id"] = str(snapshot.resource_id) if snapshot.resource_id is not None else None
    data["instance_id"] = str(snapshot.instance_id) if snapshot.instance_id is not None else None
    data["complete"] = False
    data["source"] = "observed_partial"
    data["coordinate_unit"] = "unverified"
    # 前端据此显示原始 x/y；字段始终存在，避免附加字段改变载荷形状。
    data["debug_coordinates"] = debug_coordinates_enabled()
    data["mapping_available"] = bool(static and static.scene_mapping_available)
    # 属性图标复用背包页的 type-icons 素材；名称 → URL，不换算任何数值。
    # 路由层只在启动时算一次，避免每个 0.5s 推送都重建映射。
    if type_icons is None:
        type_icons = (
            {info.name: f"/static/type-icons/type-{key}.webp" for key, info in static.type_items()}
            if static is not None else {}
        )
    data["type_icons"] = type_icons
    # 覆盖只保留格索引（行区间编码），不再随载荷下发圆心数组。
    data["coverage"] = coverage_payload(snapshot)
    # 只下发展示半径，不换算米制；前端按原始单位过滤。
    data["radar_radius_raw"] = max(1, int(radar_radius_raw))
    data["actors"] = [dict(vars(actor), actor_id=str(actor.actor_id)) for actor in snapshot.actors]
    for row in data["actors"]:
        base_id = static.scene_species_id(row["config_id"]) if static and row["config_id"] is not None else None
        species = static.species(base_id) if static and base_id is not None else None
        row["base_id"] = base_id
        row["name"] = species.name if species else f"未收录精灵 · 配置 {row['config_id'] if row['config_id'] is not None else '未知'}"
        row["icon_url"] = pet_images(base_id)["portrait_url"] if species else ""
        row["type_names"] = list(species.type_names) if species else []
        # 进化链名称：前端搜索时一并匹配，搜「恶魔叮」也能找到链上的其它形态。
        row["chain_names"] = list(static.chain_names(base_id)) if (static and base_id is not None) else []
        row["marks"] = observation_marks(row["weight"], row["voice"], species.weight_range if species else (0, 0))
        mark_names = {mark["name"] for mark in row["marks"]}
        row["attention"] = "double" if ({"大块头", "小不点"} & mark_names and {"婉转声", "粗嗓门"} & mark_names) else "marked" if mark_names else "normal"
    # 不把本地会话地址暴露到用户功能接口。
    data.pop("session_id", None)
    return data


def register_nearby_routes(
    app: web.Application,
    repository: SceneRepository | None,
    static: StaticData | None = None,
    settings=None,
) -> None:
    # 属性图标映射只依赖启动时加载的静态数据，装配时算一次即可。
    type_icons = (
        {info.name: f"/static/type-icons/type-{key}.webp" for key, info in static.type_items()}
        if static is not None else {}
    )

    def payload() -> dict:
        radius = (
            settings.get_int("nearby.radar_radius_raw", DEFAULT_RADAR_RADIUS_RAW, lo=500, hi=200000)
            if settings is not None
            else DEFAULT_RADAR_RADIUS_RAW
        )
        return nearby_payload(repository.snapshot(), static, radar_radius_raw=radius, type_icons=type_icons)

    async def get_nearby(request: web.Request) -> web.Response:
        if repository is None:
            return web.json_response({"error": "当前实例未装配场景观察"}, status=503)
        return web.json_response(await run_blocking(request, payload), headers={"Cache-Control": "no-store"})

    async def reset_coverage(request: web.Request) -> web.Response:
        """清空当前地图的本次足迹；只影响覆盖层，不重置精灵列表与观察周期。"""
        if repository is None:
            return web.json_response({"error": "当前实例未装配场景观察"}, status=503)
        try:
            body = await request.json()
        except (ValueError, json.JSONDecodeError):
            return web.json_response({"error": "请求格式无效"}, status=400)
        if (not isinstance(body, dict) or not isinstance(body.get("uid"), str)
                or not body["uid"].isdigit() or not isinstance(body.get("resource_id"), str)
                or not body["resource_id"].isdigit() or type(body.get("observation_id")) is not int):
            return web.json_response({"error": "缺少有效的账号或地图归属"}, status=400)
        ok = await run_blocking(request, repository.reset_coverage, int(body["uid"]),
                                int(body["resource_id"]), body["observation_id"])
        if not ok:
            return web.json_response({"error": "账号或场景已变化，请重新确认"}, status=409)
        return web.json_response({"ok": True}, headers={"Cache-Control": "no-store"})

    app.router.add_get("/api/nearby", get_nearby)
    app.router.add_post("/api/nearby/coverage/reset", reset_coverage)
