"""独立产线路由与 JSON 契约，复用应用鉴权和账号快照。"""
from __future__ import annotations

import asyncio

from aiohttp import web

from spritelens.app_context import AppContext
from spritelens.domain.collection_lines import GOALS, Breeder, CollectionGoal
from spritelens.domain.measurements import range_position
from spritelens.services.collection_lines_service import CollectionLinesService
from spritelens.view_models.collection_lines_vm import CollectionLinesViewModel, CollectionView
from spritelens.web.pet_media import pet_images


def collection_payload(view: CollectionView, goal: CollectionGoal, context: AppContext) -> dict:
    snapshot = view.snapshot
    inventory = snapshot.inventory
    static = context.static_data

    def parent_row(parent: Breeder) -> dict:
        pet = parent.pet
        location = inventory.locations.get(pet.gid)
        return {"gid": str(pet.gid), "name": pet.name or parent.species.name, "gender": pet.gender,
                "nature": parent.nature, "voice": pet.voice, "basis": parent.basis,
                "marks": [{"name": name, "source": source} for name, source in parent.marks],
                "height_ratio": range_position(pet.height, parent.species.height_range)["ratio"],
                "weight_ratio": range_position(pet.weight, parent.species.weight_range)["ratio"],
                "icon_url": pet_images(pet.base_conf_id)["portrait_url"],
                "location": location.payload() if location else None}

    lines = []
    for line in snapshot.lines:
        members = []
        for base_id in line.chain.members:
            species = static.species(base_id) if static else None
            if species:
                members.append({"base_id": base_id, "name": species.display_name or species.name, "dex_no": species.dex_no,
                                "stage": species.stage, "icon_url": pet_images(base_id)["portrait_url"]})
        members.sort(key=lambda member: (member["stage"], member["dex_no"], member["base_id"]))
        lines.append({"key": line.chain.key, "members": members, "groups": line.chain.groups,
                      "status": line.status, "gaps": line.chain.gaps,
                      "mothers": [parent_row(mother) for mother in line.mothers],
                      "pairs": [{"mother_gid": str(mother), "father_gids": [str(gid) for gid in fathers]}
                                for mother, fathers in line.pairs]})
    lines.sort(key=lambda line: (line["members"][0]["dex_no"] if line["members"] else 0, line["key"]))
    return {"uid": inventory.uid, "version": inventory.version, "rule_version": "observed-double-marks-v2",
            "available": snapshot.available, "source": "observed" if inventory.identity else "history",
            "goal": goal.key, "natures": [nature.name for _, nature in static.nature_items()] if static else [], "pet_count": len(inventory.pets),
            "totals": view.totals, "lines": lines,
            "fathers": [parent_row(father) for father in snapshot.fathers]}


def register_collection_routes(app: web.Application, context: AppContext) -> None:
    vm = CollectionLinesViewModel(CollectionLinesService(context.pet_repository, context.static_data, context.egg_catalog))

    async def get_lines(request: web.Request) -> web.Response:
        key = request.query.get("goal", "big-soft")
        sound = request.query.get("sound", "")
        if key not in GOALS or sound not in ("", "100", "-100"):
            raise web.HTTPBadRequest(text="无效的产线目标或声音条件")
        for name in ("full_weight", "colorful", "ignore_missing_male"):
            if request.query.get(name, "0") not in ("0", "1"):
                raise web.HTTPBadRequest(text=f"无效的产线条件：{name}")
        goal = CollectionGoal(key, int(sound) if sound else None, request.query.get("full_weight") == "1",
                              request.query.get("colorful") == "1", request.query.get("ignore_missing_male") == "1")
        def payload() -> dict:
            return collection_payload(vm.snapshot(goal), goal, context)
        return web.json_response(await asyncio.to_thread(payload))

    app.router.add_get("/api/collection-lines", get_lines)
