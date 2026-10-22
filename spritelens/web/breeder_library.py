"""筛选配对的独立鉴权路由及载荷转换。"""
from __future__ import annotations

from collections.abc import Mapping
from math import isfinite

from aiohttp import web

from spritelens.app_context import AppContext
from spritelens.domain.breeder_library import MARKS, BreederFilters, Candidate
from spritelens.view_models.breeder_library_vm import PAGE_SIZE, BreederLibraryViewModel, BreederView
from spritelens.web.pet_media import pet_images
from spritelens.web.background import run_blocking


def parse_filters(query: Mapping[str, str]) -> BreederFilters:
    values = {key: frozenset(filter(None, query.get(key, "").split(","))) for key in ("groups", "natures", "marks")}
    if values["marks"] - set(MARKS) or query.get("same_nature", "1") not in ("0", "1"):
        raise ValueError("无效的奖牌或性格条件")
    values.update(search=query.get("search", ""), same_nature=query.get("same_nature", "1") == "1")
    for key in ("male", "female", "anchor", "male_page", "female_page"):
        value = int(query.get(key, "1" if key.endswith("page") else "0"))
        if value < (1 if key.endswith("page") else 0) or key == "anchor" and value not in (0, 1, 2):
            raise ValueError("无效的亲本或页码")
        values[key] = value
    for field in ("voice", "height", "weight"):
        for bound in ("min", "max"):
            key = f"{field}_{bound}"
            text = query.get(key, "")
            value = float(text) if text else None
            low, high = (-100, 100) if field == "voice" else (0, 1)
            if value is not None and (not isfinite(value) or not low <= value <= high):
                raise ValueError("数值范围无效")
            values[key] = value
        if values[f"{field}_min"] is not None and values[f"{field}_max"] is not None and values[f"{field}_min"] > values[f"{field}_max"]:
            raise ValueError("最小值不能大于最大值")
    return BreederFilters(**values)


def breeder_payload(view: BreederView, context: AppContext) -> dict:
    def row(parent: Candidate | None) -> dict | None:
        if parent is None:
            return None
        pet = parent.pet
        location = view.inventory.locations.get(pet.gid)
        return {"gid": str(pet.gid), "name": pet.name or parent.species.name, "species": parent.species.name,
                "dex_no": parent.species.dex_no, "gender": pet.gender, "nature": parent.nature,
                "groups": parent.groups, "marks": parent.marks, "voice": parent.voice,
                "height_ratio": parent.height, "weight_ratio": parent.weight,
                "is_shiny": bool(pet.mutation_type & 1), "is_colorful": bool(pet.mutation_type & 8),
                "icon_url": pet_images(pet.base_conf_id, bool(pet.mutation_type & 1))["portrait_url"],
                "location": location.payload() if location else None}
    predicted = dict(view.prediction) if view.prediction else None
    if predicted is not None:
        mother = view.selected_female
        egg = context.egg_catalog.egg_by_base_id(mother.pet.base_conf_id) if context.egg_catalog and mother else None
        predicted["egg_name"] = egg.egg_name if egg else None
        predicted["offspring"] = egg.name if egg else None
    return {"uid": view.inventory.uid, "version": view.inventory.version, "available": view.available,
            "source": "observed" if view.inventory.identity else "history", "complete": None,
            "pet_count": len(view.inventory.pets), "groups": view.groups, "natures": view.natures,
            "males": [row(parent) for parent in view.males], "females": [row(parent) for parent in view.females],
            "male_total": view.male_total, "female_total": view.female_total, "page_size": PAGE_SIZE,
            "male_page": view.male_page, "female_page": view.female_page,
            "selected_male": row(view.selected_male), "selected_female": row(view.selected_female),
            "anchor": view.anchor, "selection_changed": view.selection_changed, "prediction": predicted}


def register_breeder_routes(app: web.Application, context: AppContext) -> None:
    vm = BreederLibraryViewModel(context.pet_repository, context.static_data)
    async def get_library(request: web.Request) -> web.Response:
        try:
            filters = parse_filters(request.query)
        except ValueError as error:
            return web.json_response({"error": str(error)}, status=400)
        return web.json_response(await run_blocking(request, lambda: breeder_payload(vm.snapshot(filters), context)))
    app.router.add_get("/api/breeder-library", get_library)
