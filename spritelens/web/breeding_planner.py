"""智能配窝鉴权 API，严格校验外部草稿并在工作线程计算。"""
from __future__ import annotations

import asyncio
import re
from dataclasses import asdict
from math import isfinite

from aiohttp import web

from spritelens.domain.breeding_planner import GEOMETRY_VERSION, RULE_VERSION, Goal, Placement, Request
from spritelens.services.breeding_planner_service import BreedingPlannerService, StalePlannerInput
from spritelens.view_models.breeding_planner_vm import BreedingPlannerViewModel
from spritelens.web.pet_media import pet_images


def parse_draft(value: dict) -> Request:
    def require(condition, message="规划参数格式错误"):
        if not condition:
            raise ValueError(message)
    require(isinstance(value, dict))
    require(value.get("mode") in ("target", "selected"))
    require(type(value.get("capacity")) is int and 0 <= value["capacity"] <= 10)
    require(type(value.get("academy")) is bool and value.get("participation") in ("best", "all"))
    require(value.get("rule_version") == RULE_VERSION and value.get("geometry_version") == GEOMETRY_VERSION,
            "规则版本已变化，请刷新资料后重新评估草稿")
    goals, placements, aliases = [], [], {}
    raw_goals, raw_positions = value.get("goals"), value.get("placements")
    require(isinstance(raw_goals, list) and len(raw_goals) <= 30 and isinstance(raw_positions, list) and len(raw_positions) <= 11)
    for row in raw_goals:
        require(isinstance(row, dict))
        require(all(isinstance(row.get(k), str) and 0 < len(row[k]) <= 100 for k in ("goal_id", "egg_key")))
        require(re.fullmatch(r"[A-Za-z0-9_-]+", row["goal_id"]) is not None)
        require(row.get("size_mark") in ("", "大块头", "小不点") and row.get("voice_mark") in ("", "婉转声", "粗嗓门"))
        require(type(row.get("nature_id")) is int and row["nature_id"] >= 0 and type(row.get("priority")) is int and row["priority"] in (0, 1))
        goal = Goal(**{k: row[k] for k in Goal.__dataclass_fields__})
        # 相同目标合并；不同目标 ID 不可复用。
        duplicate = next((g for g in goals if (asdict(g) | {"goal_id": ""}) == (asdict(goal) | {"goal_id": ""})), None)
        if duplicate:
            aliases[goal.goal_id] = duplicate.goal_id
            continue
        require(all(g.goal_id != goal.goal_id for g in goals), "目标标识重复")
        goals.append(goal)
    def gid(item):
        return isinstance(item, str) and re.fullmatch(r"[1-9][0-9]{0,19}", item) is not None and int(item) < 2**64
    selected = value.get("selected")
    approved = value.get("approved")
    require(isinstance(selected, list) and len(selected) <= 2000 and all(gid(i) for i in selected))
    require(isinstance(approved, list) and len(approved) <= 720
            and all(isinstance(i, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,100}:[1-9][0-9]{0,19}:[1-9][0-9]{0,19}", i) is not None
                    for i in approved), "准许迭代组合格式错误")
    for row in raw_positions:
        require(isinstance(row, dict) and gid(row.get("gid")))
        require(row.get("kind") in ("normal", "academy") and row.get("lock") in ("", "participation", "position"))
        require(isinstance(row.get("primary_goal_id"), str))
        require(all(type(row.get(k)) in (int, float) and isfinite(row[k]) and abs(row[k]) <= 1000 and row[k] * 2 == int(row[k] * 2) for k in ("x", "y")),
                "坐标必须是有限数值并吸附半格")
        primary = aliases.get(row["primary_goal_id"], row["primary_goal_id"])
        placements.append(Placement(**{**{k: row[k] for k in Placement.__dataclass_fields__}, "primary_goal_id": primary}))
        require(not primary or primary in {g.goal_id for g in goals}, "母本主目标不存在，请重新分配")
    require(len({p.gid for p in placements}) == len(placements), "同一个体不能重复入住")
    return Request(value["mode"], tuple(goals), tuple(dict.fromkeys(selected)), value["participation"],
                   value["capacity"], value["academy"], tuple(placements), frozenset(
                       aliases.get(key.split(":", 1)[0], key.split(":", 1)[0]) + ":" + key.split(":", 1)[1]
                       if ":" in key else key for key in approved))


def register_planner_routes(app: web.Application, context) -> None:
    service = BreedingPlannerService(context.pet_repository, context.static_data, context.egg_catalog, context.settings)
    vm = BreedingPlannerViewModel(service)

    async def get_context(request):
        payload = await asyncio.to_thread(vm.context)
        for row in payload["parents"]:
            row["icon_url"] = pet_images(row.pop("base_id"), row["is_shiny"])["portrait_url"]
        return web.json_response(payload)

    async def mutate(request):
        try:
            body = await request.json()
            draft = parse_draft(body)
            if not all(type(body.get(key)) is int and body[key] >= 0 for key in ("uid", "version", "revision")):
                raise ValueError("缺少有效账号、背包版本或草稿修订号")
            if body.get("catalog_version") != service.catalog_version:
                raise StalePlannerInput("目录版本已变化，请刷新资料后重新评估草稿")
            if request.match_info["action"] == "draft":
                try:
                    await asyncio.to_thread(service.save_draft, body["uid"], body["version"], draft.mode, {**body, "schema_version": 1})
                except OSError as error:
                    return web.json_response({"error": f"草稿保存失败：{error}"}, status=500)
                return web.json_response({"uid": body["uid"], "version": body["version"], "saved": True, "revision": body["revision"]})
            if draft.mode == "target" and not draft.goals or draft.mode == "selected" and not draft.selected:
                raise ValueError("请先添加目标蛋或选择参与精灵")
            # 目标只能使用真实繁育映射，目录性格必须存在。
            catalog = await asyncio.to_thread(vm.context)
            if any(g.egg_key not in {e["egg_key"] for e in catalog["eggs"]} or g.nature_id and g.nature_id not in {n["id"] for n in catalog["natures"]} for g in draft.goals):
                raise ValueError("目标蛋或性格不在当前可繁育目录中")
            result = await asyncio.to_thread(service.calculate, body["uid"], body["version"], draft, request.match_info["action"])
            return web.json_response({**result, "revision": body["revision"]})
        except StalePlannerInput as error:
            return web.json_response({"error": str(error)}, status=409)
        except (ValueError, TypeError) as error:
            return web.json_response({"error": str(error)}, status=400)

    async def get_draft(request):
        mode = request.query.get("mode", "target")
        if mode not in ("target", "selected"):
            return web.json_response({"error": "无效入口"}, status=400)
        inventory = await asyncio.to_thread(context.pet_repository.consistent_snapshot)
        value = await asyncio.to_thread(service.load_draft, inventory.uid, mode)
        try:
            if value is not None:
                if not isinstance(value, dict) or value.get("schema_version") != 1 or value.get("uid") != inventory.uid or value.get("mode") != mode:
                    raise ValueError("草稿结构或账号无效")
                parse_draft({**value, "rule_version": RULE_VERSION, "geometry_version": GEOMETRY_VERSION})
        except (ValueError, TypeError) as error:
            return web.json_response({"uid": inventory.uid, "version": inventory.version, "draft": None, "error": f"无法恢复草稿：{error}"})
        return web.json_response({"uid": inventory.uid, "version": inventory.version, "draft": value})

    app.router.add_get("/api/breeding-planner/context", get_context)
    app.router.add_get("/api/breeding-planner/draft", get_draft)
    app.router.add_post("/api/breeding-planner/{action:solve|evaluate|draft}", mutate)
    async def cleanup(application):
        service.cancel()
    app.on_cleanup.append(cleanup)
