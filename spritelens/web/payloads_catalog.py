"""目录域载荷：图鉴/种公矩阵/花田/色卡/家园/蛋仓/蛋图鉴（阶段1.4 拆分）。

从 payloads.py 按业务域机械搬移，函数体未改动；前端契约稳定，
payloads.py 保留兼容重导出。本模块不依赖 aiohttp 与 pywebview。
"""

from __future__ import annotations

from spritelens.domain.static_data import StaticData
from spritelens.domain.display import TYPE_COLORS
from spritelens.domain.measurements import range_position, range_text
from spritelens.web.pet_media import pet_images
from spritelens.services.egg_repository import EggBoxSnapshot
from spritelens.services.home_repository import HomeRepoSnapshot
from spritelens.services.flower_repository import FlowerRepoSnapshot


def species_icon_url(base_conf_id: int) -> str:
    """精灵图 URL（Web 静态资源）；无图时前端回退首字头像。"""
    return f"/static/pets/{base_conf_id}.webp"


def handbook_payload(
    static: StaticData | None,
    repository: PetRepository,
    *,
    search: str = "",
    type_name: str = "",
    collected_only: bool = False,
    uncollected_only: bool = False,
) -> dict:
    """图鉴载荷：全物种目录 + 收集状态（来自当前快照）+ 筛选。

    收集状态以「会话快照里出现过该 base_conf_id」为准（与宠物仓库同源）；
    图鉴是只读视图，不做独立持久化——快照本身已由本地库恢复。
    """
    snapshot = repository.consistent_snapshot()
    if static is None:
        return {
            "uid": snapshot.uid, "version": snapshot.version, "complete": None,
            "species": [],
            "total": 0,
            "collected": 0,
            "shown": 0,
            "type_options": [],
            "filters": {"search": search, "type": type_name,
                        "collected_only": collected_only, "uncollected_only": uncollected_only},
        }

    # 收集统计：base_conf_id → 拥有只数 / 其中最高等级
    owned: dict[str, dict] = {}
    for pet in snapshot.pets:
        key = str(pet.base_conf_id)
        if not key or key == "0":
            continue
        entry = owned.setdefault(key, {"count": 0, "max_level": 0})
        entry["count"] += 1
        entry["max_level"] = max(entry["max_level"], pet.level)

    needle = search.strip().lower()
    rows: list[dict] = []
    type_names_seen: set[str] = set()
    for key, info in static.species_items():
        type_names_seen.update(info.type_names)
        if type_name and type_name not in info.type_names:
            continue
        if needle and needle not in info.name.lower() and needle not in key:
            continue
        own = owned.get(key)
        if collected_only and own is None:
            continue
        if uncollected_only and own is not None:
            continue
        rows.append(
            {
                "key": key,
                "name": info.name,
                "display_name": info.display_name,
                "dex_no": info.dex_no,
                "handbook_no": info.handbook_no,
                "icon_url": species_icon_url(int(key)) if key.isdigit() else "",
                "egg_groups": list(info.egg_groups),
                "gender_ratio": list(info.gender_ratio),
                "height_range": list(info.height_range),
                "weight_range": list(info.weight_range),
                "reference_ranges": {"height": range_text(info.height_range, 100, "m"), "weight": range_text(info.weight_range, 1000, "kg")},
                "has_shiny": info.has_shiny,
                "type_names": list(info.type_names),
                "type_colors": [type_color_for(static, name) for name in info.type_names],
                "stats": dict(info.stats),
                "stat_sum": info.stat_sum,
                "quality": info.quality,
                "stage": info.stage,
                "max_energy": info.max_energy,
                "evolutions": [
                    {"key": str(e), "name": evo.name}
                    for e in info.evolutions
                    if (evo := static.species(e)) is not None
                ],
                "chain_members": [{"key": str(e), "name": member.name}
                                  for e in info.chain_members if (member := static.species(e)) is not None],
                "collected": own is not None,
                "owned_count": own["count"] if own else 0,
                "best_level": own["max_level"] if own else 0,
                "description": info.description,
            }
        )
    return {
        "species": rows,
        "uid": snapshot.uid, "version": snapshot.version, "complete": None,
        "total": len(static.species_items()),
        "collected": len(owned),
        "shown": len(rows),
        "type_options": sorted(type_names_seen),
        "filters": {
            "search": search,
            "type": type_name,
            "collected_only": collected_only,
            "uncollected_only": uncollected_only,
        },
    }
def male_matrix_payload(pet_repository, static: StaticData | None, gender: str = "all") -> dict:
    """种公阵列载荷：性格 × 蛋组覆盖矩阵（对标孵蛋管理器）。

    行=性格（含正/负修正说明），列=蛋组，格子=该组合下的宠物摘要列表。
    gender: all / male / female——按公母分库筛选。
    """
    snapshot = pet_repository.consistent_snapshot() if pet_repository is not None else None
    pets = snapshot.pets if snapshot else ()
    cells: dict[str, list[dict]] = {}
    natures_seen: dict[str, dict] = {}
    groups_seen: dict[str, None] = {}
    for pet in pets:
        species = static.species(pet.base_conf_id) if static is not None else None
        if species is None or not species.egg_groups:
            continue
        if gender == "male" and pet.gender != 1:
            continue
        if gender == "female" and pet.gender != 2:
            continue
        nature_name = static.nature_name(pet.nature) if static is not None else str(pet.nature)
        nature_info = static.nature(pet.nature) if static is not None else None
        natures_seen.setdefault(
            nature_name,
            {
                "name": nature_name,
                "positive": nature_info.positive_stat if nature_info else None,
                "negative": nature_info.negative_stat if nature_info else None,
            },
        )
        summary = {
            "gid": pet.gid,
            "name": pet.name,
            "gender": pet.gender,
            "level": pet.level,
            "icon_url": species_icon_url(pet.base_conf_id),
        }
        for group in species.egg_groups:
            groups_seen.setdefault(group, None)
            cells.setdefault(f"{nature_name}|{group}", []).append(summary)
    order = {name: i for i, name in enumerate(sorted(groups_seen))}
    cell_lists = {
        key: sorted(items, key=lambda p: (-p["level"], p["gid"]))[:8]
        for key, items in cells.items()
        if items
    }
    return {
        "natures": sorted(natures_seen.values(), key=lambda n: n["name"]),
        "uid": snapshot.uid if snapshot else 0, "version": snapshot.version if snapshot else 0,
        "complete": None,
        "groups": sorted(groups_seen),
        "cell_order": order,
        "cells": cell_lists,
        "total_pets": len(pets),
        "matched": sum(len(v) for v in cells.values()),
        "gender": gender,
    }
def flowers_payload(flower_repo, static: StaticData | None, catalog=None, pet_repository=None) -> dict:
    """炫彩花种载荷：我的花田 + 好友花田摘要（花联查宠物名）。

    名字降级链：图鉴物种表 → 蛋目录 → 宠物帧学习表（colorful_conf_id→名字）
    → "#id"。
    """
    view = flower_repo.consistent_snapshot() if flower_repo is not None else FlowerRepoSnapshot(None, 0, 0)
    snap = view.data
    metadata = {"uid": view.uid, "version": view.version, "complete": None,
                "source": "observed" if snap is not None else "unknown"}
    if snap is None:
        return {**metadata, "available": False, "own": [], "friends": []}

    def name_of(conf_id: int) -> str:
        species = static.species(conf_id) if static is not None else None
        if species is not None:
            return species.name
        egg = catalog.egg_by_base_id(conf_id) if catalog is not None else None
        if egg is not None:
            return egg.name
        learned = pet_repository.colorful_name(conf_id) if pet_repository is not None else None
        return learned or f"#{conf_id}"

    def row(r, owner):
        return {
            "slot_id": r.slot_id,
            "slot_index": r.slot_index,
            "pet_conf_id": r.pet_conf_id,
            "pet_name": name_of(r.pet_conf_id) if r.pet_conf_id else "—",
            "icon_url": species_icon_url(r.pet_conf_id) if r.pet_conf_id else "",
            "planted_at": r.planted_at,
            "owner": owner,
        }

    own = [row(r, "self") for r in snap.own]
    friends = [row(r, "friend") for r in snap.friends]
    return {
        "available": True,
        "own": own,
        "friends": friends,
        **metadata,
    }
def colors_payload(pet_repository, catalog, static: StaticData | None) -> dict:
    """炫彩色卡载荷：宠物库按 glass → 卡号聚合，输出底色×混色矩阵。

    蛋神同款交互：底色在横轴、混色在纵轴；未收录的卡号（glass 在但目录无）
    与赛季卡单独分组。
    """
    cards = catalog.cards() if catalog is not None else ()
    snapshot = pet_repository.consistent_snapshot() if pet_repository is not None else None
    # 轴带目录色（mock/降级路径可能没有 color 字段，getattr 防御）
    base_map: dict[str, str | None] = {}
    mix_map: dict[str, str | None] = {}
    for card in cards:
        base_map.setdefault(card.base_name, getattr(card, "base_color", None))
        mix_map.setdefault(card.mix_name, getattr(card, "mix_color", None))
    matrix: dict[str, list[dict]] = {}
    seasonal: list[dict] = []
    unknown: list[dict] = []
    total = 0
    for pet in (snapshot.pets if snapshot is not None else ()):
        if not pet.mutation_type & 8 or (not pet.glass_type and not pet.glass_value):
            continue
        if catalog is None:
            continue
        card_id = catalog.card_id_for(pet.glass_type, pet.glass_value)
        summary = {
            "gid": pet.gid,
            "name": pet.name,
            "level": pet.level,
            "gender": pet.gender,
            "icon_url": species_icon_url(pet.base_conf_id),
            "card_id": card_id,
            **pet_images(pet.base_conf_id, bool(pet.mutation_type & 1)),
            "color_card": catalog.effect_for(pet.glass_type, pet.glass_value),
        }
        total += 1
        if card_id.startswith("s"):
            seasonal.append(summary)
            continue
        card = catalog.card(card_id)
        if card is None:
            unknown.append(summary)
            continue
        matrix.setdefault(f"{card.base_name}|{card.mix_name}", []).append(summary)
    return {
        "base_axis": [{"name": n, "hex": h} for n, h in base_map.items()],
        "uid": snapshot.uid if snapshot else 0, "version": snapshot.version if snapshot else 0,
        "complete": None,
        "mix_axis": [{"name": n, "hex": h} for n, h in mix_map.items()],
        "matrix": matrix,
        "seasonal": seasonal,
        "unknown": unknown,
        "card_total": len(cards),
        "pet_total": total,
    }
def home_payload(home_repo, static: StaticData | None) -> dict:
    """我的家园载荷：居民（联查物种图标）/ 家具 / 产蛋窝 / 增量提示。"""
    view = home_repo.consistent_snapshot() if home_repo is not None else HomeRepoSnapshot(None, 0, 0, 0)
    snap = view.data
    metadata = {"uid": view.uid, "version": view.version, "pending_deltas": view.pending_deltas,
                "complete": None, "source": "stale" if snap and view.pending_deltas else "observed" if snap else "unknown"}
    if snap is None:
        return {"available": False, "residents": [], "furniture": [], "nests": [],
                "room_level": 0, **metadata}
    residents = []
    for r in snap.residents:
        species = static.species(r.actor_id & 0xFFFF) if static is not None else None
        residents.append({
            # uint64 必须在 JSON 序列化之前转字符串，JS Number 无法区分相邻 ID。
            "actor_id": str(r.actor_id),
            "name": r.name,
            "gender": r.gender,
            "level": r.level,
            "position": list(r.position),
            "icon_url": species_icon_url(species.base_conf_id if species else 0),
            "species_name": species.name if species else "",
        })
    furniture = [
        {
            "config_id": f.config_id,
            "guid": f.guid,
            "kind": f.kind,
            "name": f.name,
            "position": list(f.position),
        }
        for f in snap.furniture
    ]
    nests = [f for f in furniture if f["kind"] != "furniture"]
    return {
        "available": True,
        "room_level": snap.room_level,
        "residents": residents,
        "furniture": furniture,
        "nests": nests,
        **metadata,
    }
def egg_box_payload(egg_box, catalog) -> dict:
    """蛋蛋仓库载荷：蛋仓快照 + 蛋目录联查（名字/孵化时长/图标）+ 聚合统计。"""
    view = egg_box.consistent_snapshot() if egg_box is not None else EggBoxSnapshot((), frozenset(), 0, 0, frozenset(), "unknown", "unknown")
    entries, slots = view.entries, view.slots
    rows: list[dict] = []
    hatching_count = 0
    historical_hatching = 0
    total_quantity = 0
    for egg in entries:
        info = catalog.egg(egg.egg_conf_id) if catalog is not None else None
        total_quantity += egg.quantity or 1
        in_slot = egg.instance_id in slots
        hatching = in_slot and view.slots_source == "observed"
        historical = egg.instance_id in view.historical_ids
        history_hatch = view.slots_source != "observed" and (in_slot and view.slots_source == "historical" or historical and egg.hatching)
        if hatching:
            hatching_count += 1
        if history_hatch:
            historical_hatching += 1
        rows.append(
            {
                "instance_id": egg.instance_id,
                "egg_conf_id": egg.egg_conf_id,
                "egg_name": info.egg_name if info else f"蛋 #{egg.egg_conf_id}",
                "species_name": info.name if info else "",
                "icon_url": (
                    f"/static/egg-icons/{info.egg_item_id}.png"
                    if info is not None and info.egg_item_id
                    else ""
                ),
                "fallback_icon_url": (
                    species_icon_url(info.base_id) if info is not None else ""
                ),
                "egg_type_name": info.egg_type_name if info is not None else "",
                "hatch_label": info.hatch_label if info is not None else "",
                "quantity": egg.quantity,
                "obtained_at": egg.obtained_at,
                "historical": historical,
                "hatching": hatching,
                "hatch_known": view.slots_source == "observed",
                "historical_hatching": history_hatch,
                "in_slot": in_slot,
                "hatch_progress": round(egg.hatch_progress, 4),
                "category": egg.category,
                "height_cm": egg.height_cm,
                "weight_g": egg.weight_g,
                "reference_ranges": {"height": range_text((info.height_low, info.height_high), 100, "m") if info else "暂无数据",
                                     "weight": range_text((info.weight_low, info.weight_high), 1000, "kg") if info else "暂无数据"},
            }
        )
    return {
        "eggs": rows,
        "total": len(entries),
        "total_quantity": total_quantity,
        "hatching": hatching_count if view.slots_source == "observed" else None,
        "historical_hatching": historical_hatching,
        "source": view.source,
        "slots_source": view.slots_source,
        "complete": None,
        "hatch_slots": len(slots),
        "version": view.version,
        # 数据归属（R05）：前端据此核对与概览身份是否一致，拒绝旧账号响应
        "uid": view.uid,
    }
def egg_dex_payload(
    catalog,
    *,
    static: StaticData | None = None,
    search: str = "",
    group: str = "",
    egg_type: str = "",
    hatch_min_hours: int = 0,
) -> dict:
    """蛋图鉴载荷：蛋目录静态数据 + 可选筛选（搜索/蛋组/蛋类型/孵化时长下限）。"""
    entries = catalog.entries() if catalog is not None else ()
    keyword = search.strip().lower()
    rows: list[dict] = []
    for info in entries:
        if keyword and not any(keyword in value.lower() for value in (
            info.name_key, info.name, info.egg_name, str(info.egg_conf_id),
        )):
            continue
        if group and group not in info.egg_group_names:
            continue
        if egg_type and info.egg_type_name != egg_type:
            continue
        if hatch_min_hours and info.hatch_seconds < hatch_min_hours * 3600:
            continue
        rows.append(
            {
                "egg_conf_id": info.egg_conf_id,
                "egg_name": info.egg_name,
                "name": info.name,
                "base_id": info.base_id,
                "icon_url": species_icon_url(info.base_id) if info.base_id else "",
                "egg_icon_url": (
                    f"/static/egg-icons/{info.egg_item_id}.png" if info.egg_item_id else ""
                ),
                "handbook_no": info.handbook_no,
                "dex_no": info.dex_no,
                "egg_type_name": info.egg_type_name,
                "hatch_label": info.hatch_label,
                "hatch_seconds": info.hatch_seconds,
                "egg_group_names": list(info.egg_group_names),
                "gender_male": info.gender_male,
                "gender_female": info.gender_female,
                "gender_ratio_text": (
                    f"♂{info.gender_male}% / ♀{info.gender_female}%"
                    if info.gender_male or info.gender_female
                    else "暂无"
                ),
                "height": [info.height_low, info.height_high],
                "weight": [info.weight_low, info.weight_high],
                "reference_ranges": {"height": range_text((info.height_low, info.height_high), 100, "m"), "weight": range_text((info.weight_low, info.weight_high), 1000, "kg")},
                "chain": list(info.chain_members),
                "chain_names": {str(base): member.name for base in info.chain_members
                                if static is not None and (member := static.species(base)) is not None},
            }
        )
    return {
        "eggs": rows,
        "total": len(entries),
        "shown": len(rows),
        "groups": list(catalog.group_names()) if catalog is not None else [],
        "egg_types": list(catalog.type_names()) if catalog is not None else [],
        "filters": {
            "search": search,
            "group": group,
            "egg_type": egg_type,
            "hatch_min_hours": hatch_min_hours,
        },
    }


__all__ = [
    "egg_box_payload",
    "flowers_payload",
    "home_payload",
    "colors_payload",
    "male_matrix_payload",
    "egg_dex_payload",
    "handbook_payload",
    "overview_payload",
    "pet_row",
    "pets_payload",
    "type_color_for",
]
def type_color_for(static: StaticData | None, name: str) -> str:
    """系别名 → 主题色：优先静态表，缺失时退回内置常量。"""
    if static is not None:
        color = static.type_color_by_name(name)
        if color:
            return color
    return TYPE_COLORS.get(name, "")
