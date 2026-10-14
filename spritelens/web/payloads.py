"""本地服务视图数据：把业务对象/VM 快照序列化为前端消费的 JSON。

前端契约稳定在此模块；它不依赖任何 UI 框架与 aiohttp，可被测试直接驱动。
"""

from __future__ import annotations

from spritelens.domain.pets import Pet
from spritelens.domain.static_data import StaticData
from spritelens.view_models.pet_vm import SORT_KEYS, PetView, PetViewModel
from spritelens.domain.display import STAT_LABELS, TALENT_RANK_COLORS, TYPE_COLORS
from spritelens.domain.measurements import range_position, range_text
from spritelens.web.pet_media import pet_images
from spritelens.web.pet_details import detail_payload
from spritelens.domain.pet_marks import pet_marks
from spritelens.domain.pet_conditions import ACQUISITION_NAMES


def _stat_bars(pet: Pet, peak: int) -> tuple[dict, ...]:
    bars: list[dict] = []
    for index, (key, label) in enumerate(STAT_LABELS):
        attr = pet.attribute(key)
        bars.append(
            {
                "key": key,
                "label": label,
                "value": attr.final_value,
                "race": attr.total_race,
                "talent_add": attr.talent_add,
                "effort_add": attr.effort_add,
                "ratio": round(min(1.0, attr.final_value / peak), 4) if peak else 0.0,
                "race_ratio": round(min(1.0, attr.total_race / peak), 4) if peak else 0.0,
            }
        )
    return tuple(bars)


def _talent_color(rank: int) -> str:
    index = max(0, min(int(rank), len(TALENT_RANK_COLORS) - 1))
    return TALENT_RANK_COLORS[index]


def species_icon_url(base_conf_id: int) -> str:
    """精灵头像 URL；缺图时前端回退首字头像。"""
    return pet_images(base_conf_id)["portrait_url"]


def pet_row(
    pet: Pet,
    static: StaticData | None,
    height_max: int,
    weight_max: int,
    color_catalog=None,
    egg_catalog=None,
) -> dict:
    """一行宠物的完整展示数据（表格与详情共用，避免两处各算一遍）。"""
    species = static.species(pet.base_conf_id) if static is not None else None
    type_names = list(species.type_names) if species is not None else []
    nature_name = static.nature_name(pet.nature) if static is not None else str(pet.nature)
    nature_info = static.nature(pet.nature) if static is not None else None

    stat_values = [a.final_value for a in pet.attributes]
    peak = max(stat_values) if stat_values else 0
    bars = _stat_bars(pet, peak) if pet.attributes else ()
    height_range = species.height_range if species else (0, 0)
    weight_range = species.weight_range if species else (0, 0)
    height_position = range_position(pet.height, height_range)
    weight_position = range_position(pet.weight, weight_range)
    egg = egg_catalog.egg_by_base_id(pet.base_conf_id) if egg_catalog else None

    return {
        "gid": pet.gid,
        "conf_id": pet.conf_id,
        "base_conf_id": pet.base_conf_id,
        "name": pet.name,
        "level": pet.level,
        "exp": pet.exp,
        "nature": pet.nature,
        "nature_name": nature_name,
        "nature_positive": nature_info.positive_stat if nature_info else None,
        "nature_negative": nature_info.negative_stat if nature_info else None,
        "gender": pet.gender,
        "talent_rank": pet.talent_rank,
        "talent_color": _talent_color(pet.talent_rank),
        "species_name": species.name if species is not None else "",
        "icon_url": species_icon_url(pet.base_conf_id) if pet.base_conf_id else "",
        "dex_no": species.dex_no if species is not None else 0,
        "handbook_no": species.handbook_no if species is not None else "",
        "egg_groups": list(species.egg_groups) if species is not None else [],
        "gender_ratio": list(species.gender_ratio) if species is not None else [0, 0],
        "has_shiny": species.has_shiny if species is not None else False,
        "type_names": type_names,
        "type_colors": [TYPE_COLORS.get(name, "") for name in type_names],
        "stats": list(bars),
        "stat_sum": sum(stat_values),
        "height": pet.height,
        "weight": pet.weight,
        "glass_colors": _glass_colors(pet, color_catalog),
        "voice": pet.voice,
        "is_colorful": bool(pet.mutation_type & 8),
        "is_shiny": bool(pet.mutation_type & 1),
        **pet_images(pet.base_conf_id, bool(pet.mutation_type & 1)),
        "color_card": color_catalog.effect_for(pet.glass_type, pet.glass_value) if color_catalog and pet.mutation_type & 8 else None,
        "worn_medal_id": pet.worn_medal_id,
        "detail": detail_payload(pet, static, egg_catalog),
        "catch_way": pet.catch_way, "add_time": pet.add_time,
        "medal_marks": pet_marks(pet, weight_range),
        "worn_medal_name": static.medal_name(pet.worn_medal_id) if static and pet.worn_medal_id else (f"奖牌 #{pet.worn_medal_id}" if pet.worn_medal_id else ""),
        "height_text": f"{pet.height / 100:.2f} m" if pet.height else "暂无数据",
        "weight_text": f"{pet.weight / 1000:.2f} kg" if pet.weight else "暂无数据",
        "height_pct": max(0, min(1, height_position["ratio"])) if height_position["ratio"] is not None else 0,
        "weight_pct": max(0, min(1, weight_position["ratio"])) if weight_position["ratio"] is not None else 0,
        "reference_ranges": {"height": range_text(height_range, 100, "m"), "weight": range_text(weight_range, 1000, "kg")},
        "range_positions": {"height": height_position, "weight": weight_position},
        "egg_ranges": {"height": range_text((egg.height_low, egg.height_high), 100, "m") if egg else "暂无数据",
                       "weight": range_text((egg.weight_low, egg.weight_high), 1000, "kg") if egg else "暂无数据"},
        "voice_text": f"{pet.voice:+d}" if pet.voice else "暂无数据",
        "voice_pct": round(min(1.0, abs(pet.voice) / 100.0), 4) if pet.voice else 0.0,
        "species_stats": dict(species.stats) if species is not None else {},
        "species_stat_sum": species.stat_sum if species is not None else 0,
        "skills": [
            {
                "skill_id": s.skill_id,
                "name": static.skill_name(s.skill_id) if static is not None else str(s.skill_id),
                "equipped": bool(s.is_equipped),
                "learned": bool(s.is_learned),
                "unlock_lv": s.unlock_need_lv,
            }
            for s in pet.skills
        ],
    }


def _glass_colors(pet: Pet, catalog) -> list[str] | None:
    """glass 参数 → 色卡 [底色 hex, 混色 hex]；无卡/未携带返回 None。"""
    if catalog is None or (not pet.glass_type and not pet.glass_value):
        return None
    card = catalog.card(catalog.card_id_for(pet.glass_type, pet.glass_value))
    if card is None:
        return None
    return [card.base_color, card.mix_color]


def pets_payload(
    vm: PetViewModel | PetView,
    static: StaticData | None,
    color_catalog=None,
    egg_catalog=None,
) -> dict:
    """宠物列表页载荷：行数据 + 可选值与当前筛选状态（一次给全）。"""
    if isinstance(vm, PetViewModel):
        sort_key, sort_desc = vm.sort_state
        vm = vm.view_with(vm.filters, sort_key, descending=sort_desc)
    pets = vm.filtered_pets()
    height_max = max((p.height for p in pets), default=0)
    weight_max = max((p.weight for p in pets), default=0)
    filters = vm.filters
    sort_key, sort_desc = vm.sort_state
    backpack = vm.backpack()
    matched = {pet.gid for pet in pets}
    all_gids = {pet.gid for pet in vm.all_pets()}
    locations = backpack.locations()
    located_gids = set(locations) | {gid for team in backpack.teams for gid in team.slots if gid}
    def slot_payload(gid):
        return {"gid": gid, "state": "unknown" if gid is None else "empty" if gid == 0
                else "missing" if gid not in all_gids else "matched" if gid in matched else "filtered"}
    return {
        "pets": [dict(pet_row(p, static, height_max, weight_max, color_catalog, egg_catalog), location=vm.location_of(p)) for p in pets],
        "total": vm.total_count(),
        "shown": len(pets),
        "backpack": {
            "boxes": [{"box_id": box.box_id, "name": box.name, "historical": box.historical,
                       "slots": [slot_payload(gid) for gid in box.slots],
                       "matched": sum(gid in matched for gid in box.slots if gid),
                       "occupied": sum(bool(gid) for gid in box.slots),
                       "unknown": sum(gid is None for gid in box.slots)}
                      for box in sorted(backpack.boxes.values(), key=lambda box: box.box_id)],
            "teams": [{"team_id": team.box_id, "name": team.name, "historical": team.historical,
                       "slots": [slot_payload(gid) for gid in team.slots],
                       "matched": sum(gid in matched for gid in team.slots if gid)} for team in backpack.teams],
            "active_team": backpack.active_team,
            "unlocated_total": sum(gid not in located_gids for gid in all_gids),
            "unlocated_shown": sum(gid not in located_gids for gid in matched),
            "filtering": filters.active,
        },
        "uid": vm.uid,
        "version": vm.version(),
        "filters": {
            "search": filters.search,
            "level_min": filters.level_min,
            "level_max": filters.level_max,
            "natures": sorted(filters.natures),
            "types": sorted(filters.type_names),
            "talent_min": filters.talent_min,
            "gender": filters.gender,
            "egg_groups": sorted(filters.egg_groups),
            "egg_mode": filters.egg_mode,
            "pool": sorted(filters.pool), "pool_mode": filters.pool_mode,
            "shiny": filters.shiny, "colorful": filters.colorful,
            "medal": filters.medal, "medals": sorted(filters.medals), "marks": sorted(filters.marks), "speciality": filters.speciality,
            "acquisition": filters.acquisition, "captured_days": filters.captured_days,
            **{key: getattr(filters, key) for key in ("height_min", "height_max", "weight_min", "weight_max", "voice_min", "voice_max",
                "height_position_min", "height_position_max", "weight_position_min", "weight_position_max")},
        },
        "sort": {"key": sort_key, "desc": sort_desc},
        "options": {
            "natures": [{"id": i, "name": n} for i, n in vm.nature_options()],
            "types": list(vm.type_options()),
            "type_icons": {info.name: f"/static/type-icons/type-{key}.png" for key, info in static.type_items()} if static else {},
            "egg_groups": list(vm.egg_group_options()),
            "sorts": [{"key": k, "label": label} for k, label in SORT_KEYS],
            "talent_max": vm.talent_rank_max(),
            "measurement_limits": vm.measurement_limits(),
            "medals": [{"id": key, "name": static.medal_name(key) if static else f"奖牌 #{key}"}
                       for key in sorted(({key for key, _ in static.medal_items()} if static else set())
                                         | {pet.worn_medal_id for pet in vm.all_pets() if pet.worn_medal_id})],
            "specialities": [{"id": key, "name": static.speciality_name(key) if static else f"特性 #{key}"}
                            for key in sorted(({key for key, _ in static.speciality_items()} if static else set())
                                              | {pet.speciality_id for pet in vm.all_pets() if pet.speciality_id})],
            "stat_labels": [label for _, label in STAT_LABELS],
            "acquisitions": [{"id": key, "name": ACQUISITION_NAMES.get(key, f"方式 #{key}")}
                             for key in sorted(set(ACQUISITION_NAMES) | {pet.catch_way for pet in vm.all_pets() if pet.catch_way})],
        },
    }


def pet_summary_payload(vm: PetView, static: StaticData | None) -> dict:
    """同一宠物快照的归属、身份与统计，供概览和 WS/REST state 共用。"""
    stats = vm.stats()
    identity = vm.identity
    cached = vm.cached_identity
    return {
        "uid": vm.uid,
        "version": vm.version(),
        "identity": (
            {"uid": identity.uid, "name": identity.name, "level": identity.level}
            if identity is not None
            else None
        ),
        "cached_identity": {"uid": cached.uid, "name": cached.name, "level": cached.level} if cached else None,
        "stats": {
            "total": stats.total,
            "maxed": stats.maxed,
            "max_level": stats.max_level,
            "types": [
                {"name": name, "count": count, "color": type_color_for(static, name)}
                for name, count in stats.type_counts
            ],
        },
    }


def overview_payload(vm: PetView, static: StaticData | None) -> dict:
    """概览载荷：快照内身份/统计 + 独立静态表状态与历史账号列表。"""
    return {
        **pet_summary_payload(vm, static),
        "static_ready": bool(static is not None and static.available),
        "accounts": [{"uid": uid, "name": name} for uid, name in vm.cached_accounts()],
    }

# -- 图鉴/蛋/家园/花田/色卡域已拆至 payloads_catalog.py（阶段1.4）--------
# 旧导入路径兼容：from spritelens.web.payloads import handbook_payload 等
from spritelens.web.payloads_catalog import (  # noqa: E402,F401
    colors_payload,
    egg_box_payload,
    egg_dex_payload,
    flowers_payload,
    handbook_payload,
    home_payload,
    male_matrix_payload,
    type_color_for,
)
