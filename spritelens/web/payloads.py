"""本地服务视图数据：把业务对象/VM 快照序列化为前端消费的 JSON。

前端契约稳定在此模块；它不依赖任何 UI 框架与 aiohttp，可被测试直接驱动。
"""

from __future__ import annotations

from spritelens.domain.pets import Pet
from spritelens.domain.static_data import StaticData
from spritelens.services.pet_repository import PetRepository
from spritelens.view_models.pet_vm import SORT_KEYS, PetViewModel
from spritelens.domain.display import STAT_LABELS, TALENT_RANK_COLORS, TYPE_COLORS


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
                "ratio": round(min(1.0, attr.final_value / peak), 4) if peak else 0.0,
                "race_ratio": round(min(1.0, attr.total_race / peak), 4) if peak else 0.0,
            }
        )
    return tuple(bars)


def _talent_color(rank: int) -> str:
    index = max(0, min(int(rank), len(TALENT_RANK_COLORS) - 1))
    return TALENT_RANK_COLORS[index]


def species_icon_url(base_conf_id: int) -> str:
    """精灵图 URL（Web 静态资源）；无图时前端回退首字头像。"""
    return f"/static/pets/{base_conf_id}.webp"


def pet_row(pet: Pet, static: StaticData | None, height_max: int, weight_max: int) -> dict:
    """一行宠物的完整展示数据（表格与详情共用，避免两处各算一遍）。"""
    species = static.species(pet.base_conf_id) if static is not None else None
    type_names = list(species.type_names) if species is not None else []
    nature_name = static.nature_name(pet.nature) if static is not None else str(pet.nature)
    nature_info = static.nature(pet.nature) if static is not None else None

    stat_values = [a.final_value for a in pet.attributes]
    peak = max(stat_values) if stat_values else 0
    bars = _stat_bars(pet, peak) if pet.attributes else ()

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
        "is_first_catch": pet.is_first_catch,
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
        "voice": pet.voice,
        "height_text": f"{pet.height / 100:.2f}m" if pet.height else "—",
        "weight_text": f"{pet.weight / 1000:.1f}kg" if pet.weight else "—",
        "height_pct": round(min(1.0, pet.height / height_max), 4) if pet.height and height_max else 0.0,
        "weight_pct": round(min(1.0, pet.weight / weight_max), 4) if pet.weight and weight_max else 0.0,
        "voice_text": f"{pet.voice:+d}" if pet.voice else "—",
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


def pets_payload(vm: PetViewModel, static: StaticData | None) -> dict:
    """宠物列表页载荷：行数据 + 可选值与当前筛选状态（一次给全）。"""
    pets = vm.filtered_pets()
    height_max = max((p.height for p in pets), default=0)
    weight_max = max((p.weight for p in pets), default=0)
    filters = vm.filters
    sort_key, sort_desc = vm.sort_state
    return {
        "pets": [pet_row(p, static, height_max, weight_max) for p in pets],
        "total": vm.total_count(),
        "shown": len(pets),
        "version": vm.version(),
        "filters": {
            "search": filters.search,
            "level_min": filters.level_min,
            "level_max": filters.level_max,
            "natures": sorted(filters.natures),
            "types": sorted(filters.type_names),
            "talent_min": filters.talent_min,
            "first_catch_only": filters.first_catch_only,
        },
        "sort": {"key": sort_key, "desc": sort_desc},
        "options": {
            "natures": [{"id": i, "name": n} for i, n in vm.nature_options()],
            "types": list(vm.type_options()),
            "sorts": [{"key": k, "label": label} for k, label in SORT_KEYS],
            "talent_max": vm.talent_rank_max(),
            "stat_labels": [label for _, label in STAT_LABELS],
        },
    }


def overview_payload(vm: PetViewModel, repository: PetRepository, static: StaticData | None) -> dict:
    """概览载荷：账号身份 + 聚合统计 + 静态表状态。"""
    stats = vm.stats()
    identity = repository.identity
    return {
        "identity": (
            {"uid": identity.uid, "name": identity.name, "level": identity.level}
            if identity is not None
            else None
        ),
        "stats": {
            "total": stats.total,
            "first_catch": stats.first_catch,
            "maxed": stats.maxed,
            "max_level": stats.max_level,
            "types": [
                {"name": name, "count": count, "color": type_color_for(static, name)}
                for name, count in stats.type_counts
            ],
        },
        "static_ready": bool(static is not None and static.available),
        "accounts": [{"uid": uid, "name": name} for uid, name in vm.cached_accounts()],
    }


def type_color_for(static: StaticData | None, name: str) -> str:
    """系别名 → 主题色：优先静态表，缺失时退回内置常量。"""
    if static is not None:
        color = static.type_color_by_name(name)
        if color:
            return color
    return TYPE_COLORS.get(name, "")


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
    if static is None:
        return {
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
    for pet in repository.snapshot():
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
                "collected": own is not None,
                "owned_count": own["count"] if own else 0,
                "best_level": own["max_level"] if own else 0,
            }
        )
    return {
        "species": rows,
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


def egg_dex_payload(
    catalog,
    *,
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
        if keyword and keyword not in info.name_key.lower() and keyword not in str(info.egg_conf_id):
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
                "chain": list(info.chain_members),
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
    "egg_dex_payload",
    "handbook_payload",
    "overview_payload",
    "pet_row",
    "pets_payload",
    "type_color_for",
]
