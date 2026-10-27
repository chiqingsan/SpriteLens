"""目录域载荷：图鉴/色卡/家园/蛋仓/蛋图鉴（阶段1.4 拆分）。

从 payloads.py 按业务域机械搬移，函数体未改动；前端契约稳定，
payloads.py 保留兼容重导出。本模块不依赖 aiohttp 与 pywebview。
"""

from __future__ import annotations

from dataclasses import replace
from math import trunc

from spritelens.domain.color_cards import ColorCatalog
from spritelens.domain.static_data import StaticData
from spritelens.domain.display import TYPE_COLORS
from spritelens.domain.egg_box import EGG_KIND_LABELS, egg_kind
from spritelens.domain.eggs import EggCatalog
from spritelens.domain.home_breeding import HomeBreedingProfile, infer_range_couples
from spritelens.domain.breeding_nature import parent_nature_reference
from spritelens.domain.measurements import range_position, range_text
from spritelens.domain.pet_marks import pet_marks
from spritelens.web.pet_media import pet_images
from spritelens.services.egg_repository import EggBoxSnapshot
from spritelens.services.home_repository import HomeRepoSnapshot


def species_icon_url(base_conf_id: int) -> str:
    """精灵头像 URL；缺图时前端回退首字头像。"""
    return pet_images(base_conf_id)["portrait_url"]


def _handbook_haystacks(key: str, info, chain_names: tuple[str, ...] = ()) -> tuple[str, ...]:
    """图鉴可检索字段（全小写）。

    卡面印的是 handbook_no，但原实现只匹配 name 与 base_conf_id，导致
    「照着卡面编号搜不到、反而搜出一堆无关物种」；dex_no 同理。
    chain_names 让同一进化链上的物种互相命中（搜「恶魔叮」也命中叮叮恶魔、
    恶魔男爵），与背包、附近页的链式搜索保持同一规则。
    """
    return tuple(text.lower() for text in (
        info.name, info.display_name, key, str(info.dex_no), info.handbook_no, *chain_names,
    ) if text)


def _handbook_exact_match(needle: str, key: str, info) -> bool:
    """精确命中：图鉴号 / base_conf_id 整串相等，或 dex_no 数值相等。

    子串匹配只作兜底：base_conf_id 的子串会让「3002 含 002」连带一堆无关物种，
    所以检索词整串命中某个编号时只认这些物种，不再混入前缀邻居。
    """
    if needle == info.handbook_no.lower() or needle == key.lower():
        return True
    return needle.isdigit() and int(needle) == info.dex_no


def _handbook_egg(catalog: EggCatalog | None, key: str) -> dict | None:
    """该物种对应的精灵蛋资料（与蛋图鉴同源）；无蛋或目录缺失时为 None。"""
    if catalog is None or not key.isdigit():
        return None
    egg = catalog.egg_by_base_id(int(key))
    if egg is None:
        return None
    return {
        "egg_conf_id": egg.egg_conf_id,
        "name": egg.egg_name or egg.name,
        "species_name": egg.name,
        "icon_url": f"/static/egg-icons/{egg.egg_item_id}.webp" if egg.egg_item_id else "",
        "hatch_hours": round(egg.hatch_seconds / 3600, 1),
        "hatch_label": egg.hatch_label,
        "egg_groups": list(egg.egg_group_names),
        "egg_type": egg.egg_type_name,
    }


def _handbook_identity(key: str, info) -> tuple:
    """同一可查询精灵的稳定身份；不把不同图鉴编号或体型范围误合并。"""
    label = info.display_name or info.name
    number = info.handbook_no or (str(info.dex_no) if info.dex_no else "")
    if not label or not number:
        return ("key", key)
    return (
        "species", label, number, tuple(info.type_names),
        tuple(info.height_range), tuple(info.weight_range),
    )


def _handbook_completeness(key: str, info) -> tuple[int, ...]:
    """重复记录优先使用资料更完整的记录；同样完整时使用较小的稳定 ID。"""
    return (
        int(info.stat_sum > 0), int(bool(info.description)),
        int(bool(info.egg_groups)), int(bool(info.gender_ratio != (0, 0))),
        int(info.height_range != (0, 0)), int(info.weight_range != (0, 0)),
        int(bool(info.chain_members)), -int(key) if key.isdigit() else 0,
    )


def _handbook_catalog(static: StaticData) -> tuple[dict[str, str], tuple[tuple[str, object], ...]]:
    """返回重复图鉴记录的别名映射，以及去重后的主记录。"""
    items = [(key, info) for key, info in static.species_items() if info.handbook_no or info.dex_no]
    canonical: dict[tuple, tuple[str, object]] = {}
    for key, info in items:
        identity = _handbook_identity(key, info)
        current = canonical.get(identity)
        if current is None or _handbook_completeness(key, info) > _handbook_completeness(*current):
            canonical[identity] = (key, info)
    aliases = {
        key: canonical[_handbook_identity(key, info)][0]
        for key, info in items
    }
    return aliases, tuple(canonical.values())


def handbook_payload(
    static: StaticData | None,
    catalog: EggCatalog | None = None,
    *,
    search: str = "",
    type_name: str = "",
    stage: int = 0,
    egg_group: str = "",
    sort: str = "dex",
    details: bool = False,
) -> dict:
    """图鉴资料载荷：全物种目录 + 游戏静态资料（不读玩家数据）。

    图鉴是资料查询页（WIKI 性质），没有账号与快照也必须可用，因此载荷不接
    pet 仓库、也不返回「已收集 / 拥有几只 / 最高等级」这类背包统计——那属于
    精灵背包与炫彩色卡。资料含种族值、系别相性、蛋组、性别比、身高体重、
    图鉴描述、进化链，以及该物种对应的精灵蛋（与蛋图鉴同源）。

    搜索匹配 name / display_name / base_conf_id / dex_no / handbook_no；编号
    精确命中优先：检索词整串等于 handbook_no 或 dex_no 时只返回这些物种，
    不再混入子串兜底结果（「002」原先会连带命中 3002、5002 等 base_conf_id
    含「002」的物种）。无精确命中才退回子串匹配，按名称搜行为不变。

    筛选与排序全部来自静态数据：系别 / 阶段 / 蛋组，排序 dex / name / stats。
    """
    if static is None:
        return {
            "species": [],
            "total": 0,
            "shown": 0,
            "type_options": [],
            "stage_options": [],
            "egg_group_options": [],
            "filters": {"search": search, "type": type_name, "stage": stage,
                        "egg_group": egg_group, "sort": sort},
        }

    needle = search.strip().lower()

    def matches(info) -> bool:
        if type_name and type_name not in info.type_names:
            return False
        if stage and stage != info.stage:
            return False
        if egg_group and egg_group not in info.egg_groups:
            return False
        return True

    aliases, catalog_items = _handbook_catalog(static)
    members_by_id = {key: info for key, info in static.species_items() if key in aliases}
    rows: list[dict] = []
    exact_rows: list[dict] = []
    type_names_seen: set[str] = set()
    stages_seen: set[int] = set()
    egg_groups_seen: set[str] = set()
    type_icons = {
        info.name: f"/static/type-icons/type-{type_id}.webp"
        for type_id, info in static.type_items()
    }
    for key, info in catalog_items:
        type_names_seen.update(name for name in info.type_names if name)
        stages_seen.add(info.stage)
        egg_groups_seen.update(info.egg_groups)
        if not matches(info):
            continue
        if needle:
            exact = _handbook_exact_match(needle, key, info)
            chain_names = tuple(
                member.name for member_id in info.chain_members
                if (member := members_by_id.get(str(member_id))) is not None and member.name
            )
            if not exact and not any(
                needle in text for text in _handbook_haystacks(key, info, chain_names)
            ):
                continue
        else:
            exact = False
        matchups = static.matchups(info.types)
        row = {
                "key": key,
                "name": info.name,
                "display_name": info.display_name,
                "dex_no": info.dex_no,
                "handbook_no": info.handbook_no,
                "icon_url": species_icon_url(int(key)) if key.isdigit() else "",
                "artwork_url": pet_images(int(key))["artwork_url"] if key.isdigit() else "",
                "shiny_artwork_url": f"/static/pet-media/{key}-shiny-artwork.webp" if key.isdigit() and info.has_shiny else "",
                "types": list(info.types),
                "egg_groups": list(info.egg_groups),
                "gender_ratio": list(info.gender_ratio),
                "height_range": list(info.height_range),
                "weight_range": list(info.weight_range),
                "reference_ranges": {"height": range_text(info.height_range, 100, "m"), "weight": range_text(info.weight_range, 1000, "kg")},
                "has_shiny": info.has_shiny,
                "type_names": list(info.type_names),
                "type_colors": [type_color_for(static, name) for name in info.type_names],
                "type_icons": {name: type_icons[name] for name in set(info.type_names) | set(sum(matchups.values(), [])) if name in type_icons},
                "matchups": matchups,
                "stats": dict(info.stats),
                "stat_sum": info.stat_sum,
                "quality": info.quality,
                "stage": info.stage,
                "max_energy": info.max_energy,
                "evolutions": [
                    {"key": member_key, "name": evo.name}
                    for e in info.evolutions
                    if (member_key := aliases.get(str(e)))
                    and (evo := static.species(int(member_key))) is not None
                ],
                "chain_members": [{"key": member_key, "name": member.name, "icon_url": species_icon_url(int(member_key)), "stage": member.stage}
                                  for e in info.chain_members
                                  if (member_key := aliases.get(str(e)))
                                  and (member := static.species(int(member_key))) is not None],
                "egg": _handbook_egg(catalog, key),
                "description": info.description,
                "wiki": static.wiki_reference.species(key, info.name) if details else None,
            }
        rows.append(row)
        if exact:
            exact_rows.append(row)
    # 编号精确命中优先：有人认领编号时不再混入子串兜底结果
    if exact_rows:
        rows = exact_rows
    if sort == "name":
        rows.sort(key=lambda row: (row["name"], row["key"]))
    elif sort == "stats":
        rows.sort(key=lambda row: (-row["stat_sum"], row["name"]))
    else:
        rows.sort(key=lambda row: (
            0 if row["handbook_no"].isdigit() else 1,
            int(row["handbook_no"]) if row["handbook_no"].isdigit() else row["dex_no"],
            row["key"],
        ))
    return {
        "species": rows,
        "total": len(catalog_items),
        "shown": len(rows),
        "type_options": sorted(type_names_seen),
        "type_option_icons": type_icons,
        "stage_options": sorted(stage for stage in stages_seen if stage),
        "egg_group_options": sorted(egg_groups_seen),
        "filters": {
            "search": search,
            "type": type_name,
            "stage": stage,
            "egg_group": egg_group,
            "sort": sort,
        },
    }


def _color_axis(cards, attr: str, color_attr: str) -> tuple[dict[str, str], dict[str, str]]:
    """颜色轴：名称 → 色值（加载顺序）+ 名称 → 轴字母。

    字母按首次出现顺序编号（A、B、C…），用于卡面「底色字母+混色数字」标签。
    mock/降级路径可能没有 color 字段，故 getattr 防御。
    """
    letters: dict[str, str] = {}
    colors: dict[str, str] = {}
    for card in cards:
        name = getattr(card, attr, "")
        if not name or name in letters:
            continue
        letters[name] = chr(ord("A") + (len(letters) % 26))
        colors[name] = getattr(card, color_attr, None) or ""
    return colors, letters


def _matrix_key(base_name: str, mix_name: str) -> str:
    return f"{base_name}|{mix_name}"


def colors_payload(pet_repository, catalog, static: StaticData | None) -> dict:
    """炫彩色卡载荷：宠物库按 glass → 卡号聚合，输出底色×混色矩阵。

    蛋神同款交互：底色在横轴、混色在纵轴；赛季卡与未解析编号单独分组。

    格子三态由三个字段的键共同表达，前端不再需要自己推算：
    - catalogs: 目录内卡号清单（含卡面标签 base_letter+mix_letter 与配色名）。
    - cells[键] = {card_id, card_number, base_name, mix_name, base_color, mix_color,
      base_letter, mix_letter, label, names, pet_count}：本地目录里存在这张卡。
    - matrix[键]: 当前账号抽到了这张卡。cells 有键而 matrix 无键 = 有卡未持有；
      两者都无键 = 该底色×混色组合在本作里没有卡。
    - unknown: card_id 解析为空（unresolved=True，glass 值不在目录编码规则内）
      或解析出编号但本地目录没有这张卡（unresolved=False）。

    轴的几何只由普通卡决定：赛季卡（s1-s4）的底色名「赛季」、混色名「S1..S4」不进
    坐标轴，否则矩阵会多出永远不可能有普通卡的一行四列，把 44 张卡摊成 128 格。
    """
    cards = catalog.cards() if catalog is not None else ()
    snapshot = pet_repository.consistent_snapshot() if pet_repository is not None else None
    fair_cards = tuple(
        card for card in cards if not ColorCatalog.is_seasonal(str(getattr(card, "card_id", "") or ""))
    )
    base_colors, base_letters = _color_axis(fair_cards, "base_name", "base_color")
    mix_colors, mix_letters = _color_axis(fair_cards, "mix_name", "mix_color")

    def card_face(card) -> dict:
        """卡面标签：底色字母 + 混色数字（与卡面印刷一致），配色名自解释。"""
        base_letter = base_letters.get(card.base_name, "")
        mix_number = mix_letters.get(card.mix_name, "")
        number = ""
        if mix_number:
            number = str(ord(mix_number) - ord("A") + 1)
        # 赛季卡不在网格里，没有网格标签；用混色名（S1..S4）当卡面标签，避免标签为空。
        label = f"{base_letter}{number}".strip() or card.mix_name
        return {
            "card_id": card.card_id,
            "card_number": card.card_id,
            "base_name": card.base_name,
            "mix_name": card.mix_name,
            "base_color": getattr(card, "base_color", "") or "",
            "mix_color": getattr(card, "mix_color", "") or "",
            "base_letter": base_letter,
            "mix_letter": mix_number,
            "label": label,
            "names": f"{card.base_name}底 · {card.mix_name}混",
        }

    # 目录清单：卡号 → 卡面信息（带 card_id 的才进目录，mock 对象可缺）
    catalogs: list[dict] = []
    cell_meta: dict[str, dict] = {}
    for card in cards:
        card_id = str(getattr(card, "card_id", "") or "")
        if not card_id:
            continue
        face = card_face(card)
        catalogs.append(face)
        # 同色对多卡号时保留卡号最小的一张作为格子代表（编号稳定可比）
        key = _matrix_key(card.base_name, card.mix_name)
        existing = cell_meta.get(key)
        if existing is None or card_id < existing["card_id"]:
            cell_meta[key] = face

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
        if not card_id:
            # 编号没解析出来：glass 有值但 card_id_for 返回空串。放进「未解析」而不是
            # 让前端渲染一个没有编号的裸卡面（原实现会显示孤立的「#」）。
            summary["unresolved"] = True
            unknown.append(summary)
            continue
        if card_id.startswith("s"):
            seasonal.append(summary)
            continue
        card = catalog.card(card_id)
        if card is None:
            # 编号能解析、但本地目录没有这张卡（目录版本落后）：按编号单列，不猜底色/混色
            summary["unresolved"] = False
            unknown.append(summary)
            continue
        summary["base_name"] = card.base_name
        summary["mix_name"] = card.mix_name
        matrix.setdefault(_matrix_key(card.base_name, card.mix_name), []).append(summary)
    # 格子元数据：catalogs 的键 = 目录里有这张卡，matrix 的键 = 当前账号抽到了。
    # 两者都不在 = 该底色×混色组合在本作里根本没有卡（44 张卡只填 128 格中的一部分）。
    cells = {
        key: {**meta, "pet_count": len(matrix.get(key, ()))}
        for key, meta in cell_meta.items()
    }
    return {
        "base_axis": [{"name": n, "hex": h, "letter": base_letters[n]} for n, h in base_colors.items()],
        "uid": snapshot.uid if snapshot else 0, "version": snapshot.version if snapshot else 0,
        "complete": None,
        "mix_axis": [{"name": n, "hex": h, "letter": mix_letters[n]} for n, h in mix_colors.items()],
        "matrix": matrix,
        "cells": cells,
        "catalogs": catalogs,
        "seasonal": seasonal,
        "unknown": unknown,
        "card_total": len(cards),
        "pet_total": total,
    }
def home_payload(home_repo, static: StaticData | None, pet_repository=None, egg_catalog=None) -> dict:
    """我的家园载荷：居民 / 已识别小窝 / 配对与增量状态。"""
    view = home_repo.consistent_snapshot() if home_repo is not None else HomeRepoSnapshot(None, 0, 0, 0)
    snap = view.data
    metadata = {"uid": view.uid, "version": view.version, "pending_deltas": view.pending_deltas,
                  "complete": None, "source": view.source}
    if snap is None:
        return {"available": False, "residents": [], "nests": [],
                "couples": [], "inferred_couples": [], "scene_eggs": [], "couples_stale": False,
                "room_level": 0, **metadata}
    couples_stale = snap.couples_stale or view.pending_deltas > 0
    pet_view = pet_repository.consistent_snapshot() if pet_repository is not None else None
    pets_by_gid = (
        {pet.gid: pet for pet in pet_view.pets}
        if pet_view is not None and pet_view.uid == view.uid else {}
    )
    residents = []
    breeding_profiles = {}
    for r in snap.residents:
        pet = pets_by_gid.get(r.instance_id) if r.instance_id else None
        base_conf_id = r.base_conf_id or (pet.base_conf_id if pet else 0)
        species = static.species(base_conf_id) if static is not None and base_conf_id else None
        gender = r.gender or (pet.gender if pet else 0)
        nature_name = static.nature_name(pet.nature) if static is not None and pet and pet.nature else ""
        voice = pet.voice if pet and pet.voice != 0 else None
        effective_pet = replace(pet, voice=voice) if pet is not None and voice is not None else pet
        height_position = range_position(pet.height, species.height_range) if pet and species else {"ratio": None}
        weight_position = range_position(pet.weight, species.weight_range) if pet and species else {"ratio": None}
        egg = egg_catalog.egg_by_base_id(base_conf_id) if egg_catalog is not None and base_conf_id else None
        if r.actor_id:
            breeding_profiles[r.actor_id] = HomeBreedingProfile(
                gender=gender,
                egg_groups=tuple(species.egg_groups) if species is not None else (),
            )
        residents.append({
            # uint64 必须在 JSON 序列化之前转字符串，JS Number 无法区分相邻 ID。
            "actor_id": str(r.actor_id),
            "instance_id": str(r.instance_id),
            "base_conf_id": base_conf_id,
            "nest_guid": r.nest_guid,
            "name": r.name or (pet.name if pet else ""),
            "gender": gender,
            "is_shiny": bool(pet and pet.mutation_type & 1),
            "is_colorful": bool(pet and pet.mutation_type & 8),
            "level": r.level or (pet.level if pet else 0),
            "nature_name": nature_name,
            "voice": voice,
            "height_text": f"{pet.height / 100:.2f} m" if pet and pet.height else "",
            "weight_text": f"{pet.weight / 1000:.2f} kg" if pet and pet.weight else "",
            "height_pct": height_position["ratio"],
            "weight_pct": weight_position["ratio"],
            "medals": pet_marks(effective_pet, species.weight_range if species else (0, 0)) if effective_pet else [],
            "egg_name": egg.egg_name if egg is not None else "",
            "egg_icon_url": f"/static/egg-icons/{egg.egg_item_id}.webp" if egg and egg.egg_item_id else "",
            "egg_weight_range": {"min": egg.weight_low, "max": egg.weight_high}
            if egg is not None and egg.weight_high > egg.weight_low else None,
            "egg_groups": list(species.egg_groups) if species is not None else [],
            "icon_url": species_icon_url(base_conf_id),
            "artwork_url": pet_images(base_conf_id)["artwork_url"],
            "species_name": species.name if species else "",
        })
    nests = [
        {
            "config_id": f.config_id,
            "guid": f.guid,
            "kind": f.kind,
            "name": f.name,
            "resident_ids": [str(actor_id) for actor_id in f.resident_ids],
        }
        for f in snap.nests
    ]
    resident_by_actor = {str(row["actor_id"]): row for row in residents}
    academy_nests = {str(row["guid"]) for row in nests if row["kind"] == "academy"}

    def parent(actor_id: int) -> dict:
        row = resident_by_actor.get(str(actor_id))
        if row is None:
            return {"actor_id": str(actor_id), "name": "资料缺失", "nature": None,
                    "voice": None, "academy": False, "missing": True}
        return {"actor_id": str(actor_id), "name": row["name"] or "资料缺失",
                "nature": row["nature_name"] or None, "voice": row["voice"],
                "academy": row["nest_guid"] in academy_nests, "missing": False}

    def nature_prediction(mother: dict, fathers: list[dict]) -> dict:
        distribution: dict[str, float] = {}
        random_percent = 0.0
        unknown_percent = 0.0

        if mother["missing"] or not fathers:
            return {"distribution": {}, "random_percent": 0.0, "unknown_percent": 100.0,
                    "assumption": "equal-father-probability"}
        weight = 1 / len(fathers)
        for father in fathers:
            if father["missing"]:
                unknown_percent += 100 * weight
            else:
                reference = parent_nature_reference(father["nature"], mother["nature"],
                                                     male_academy=father["academy"], female_academy=mother["academy"])
                for nature, share in reference["known"].items():
                    distribution[nature] = distribution.get(nature, 0.0) + share * 100 * weight
                random_percent += reference["random"] * 100 * weight
                unknown_percent += reference["unknown"] * 100 * weight
        return {"distribution": {name: round(percent, 2) for name, percent in distribution.items()},
                "random_percent": round(random_percent, 2), "unknown_percent": round(unknown_percent, 2),
                "assumption": "equal-father-probability"}

    def couple_payload(couple, pairing_basis: str) -> dict:
        mother = parent(couple.female_actor_id)
        fathers = [parent(actor_id) for actor_id in couple.male_actor_ids]
        return {
            "female_actor_id": str(couple.female_actor_id),
            "female_name": mother["name"],
            "female_nature": mother["nature"],
            "female_is_academy": mother["academy"],
            "male_actor_ids": [str(actor_id) for actor_id in couple.male_actor_ids],
            "male_names": [father["name"] for father in fathers],
            "male_natures": [father["nature"] for father in fathers],
            "male_is_academy": [father["academy"] for father in fathers],
            "voice_predictions": [
                {"father_actor_id": str(actor_id), "father_name": father["name"],
                 "voice": trunc((mother["voice"] + father["voice"]) / 2)
                 if mother["voice"] is not None and father["voice"] is not None else None}
                for actor_id, father in zip(couple.male_actor_ids, fathers)
            ],
            "mode": "academy-mother" if mother["academy"] else
                    "academy-father" if any(father["academy"] for father in fathers)
                    else "ordinary",
            "pairing_basis": pairing_basis,
            "nature_prediction": nature_prediction(mother, fathers),
        }

    couples = [couple_payload(couple, "scene") for couple in snap.couples]
    inferred_couples = [
        couple_payload(couple, "nest-range")
        for couple in infer_range_couples(snap.residents, snap.nests, breeding_profiles)
    ] if couples_stale else []
    return {
        "available": True,
        "room_level": snap.room_level,
        "residents": residents,
        "nests": nests,
        "couples": couples,
        "inferred_couples": inferred_couples,
        "scene_eggs": [
            {"actor_id": str(egg.actor_id), "furniture_guid": egg.furniture_guid,
             "npc_config_id": egg.npc_config_id}
            for egg in snap.scene_eggs
        ],
        "couples_stale": couples_stale,
        **metadata,
    }
def egg_box_payload(egg_box, catalog, *, static=None, annotations=None, nature_options=()) -> dict:
    """蛋蛋仓库载荷：蛋仓快照 + 蛋目录联查（名字/孵化时长/图标）+ 聚合统计。"""
    view = (
        egg_box if isinstance(egg_box, EggBoxSnapshot)
        else egg_box.consistent_snapshot() if egg_box is not None
        else EggBoxSnapshot((), frozenset(), 0, 0, frozenset(), "unknown", "unknown")
    )
    entries, slots = view.entries, view.slots
    annotations = annotations or {}
    nature_names = dict(nature_options)
    rows: list[dict] = []
    hatching_count = 0
    historical_hatching = 0
    total_quantity = 0
    for egg in entries:
        annotation = annotations.get(egg.instance_id, {})
        nature_id = int(annotation.get("nature_id", 0))
        nest_override = str(annotation.get("nest_override", ""))
        note = str(annotation.get("note", ""))
        voice_tag = str(annotation.get("voice_tag", ""))
        voice_db = annotation.get("voice_db")
        favorite = bool(annotation.get("is_favorite", False))
        info = catalog.inventory_egg(egg.egg_conf_id, egg.pet_conf_id, egg.special_egg_conf_id) if catalog is not None else None
        kind = egg_kind(egg, info.precious_type if info else None, info.mutation_type if info else 0,
                        info.random if info else bool(egg.special_egg_conf_id))
        hatch_seconds = egg.hatch_seconds or (info.hatch_seconds if info else 0)
        hatch_label = (f"{hatch_seconds // 3600}小时" if hatch_seconds % 3600 == 0 else
                       f"{hatch_seconds // 60}分钟" if hatch_seconds % 60 == 0 else f"{hatch_seconds}秒") if hatch_seconds else ""
        total_quantity += egg.quantity or 1
        in_slot = egg.instance_id in slots
        hatching = in_slot and view.slots_source == "observed"
        historical = egg.instance_id in view.historical_ids
        history_hatch = view.slots_source != "observed" and (in_slot and view.slots_source == "historical" or historical and egg.hatching)
        if hatching:
            hatching_count += 1
        if history_hatch:
            historical_hatching += 1
        weight_range = (info.weight_low, info.weight_high) if info else (0, 0)
        weight_label = None
        low, high = weight_range
        if egg.weight_g > 0 and low > 0 and high > low:
            if egg.weight_g == high:
                weight_label = "满重"
            elif egg.weight_g == low:
                weight_label = "底重"
        voice_label = voice_tag if voice_tag in ("满分", "底分") else None
        chain_names = [
            species.name for base_id in (info.chain_members if info else ())
            if static is not None and (species := static.species(base_id)) is not None
        ]
        medals = []
        if not weight_label and egg.weight_g > 0 and low > 0 and high > low:
            position = egg.weight_g - low
            width = high - low
            if 0 < position < width * 0.02:
                medals.append("小不点")
            elif width * 0.98 < position < width:
                medals.append("大块头")
        if voice_tag in ("婉转声", "粗嗓门"):
            medals.append(voice_tag)
        nature_label = nature_names.get(nature_id, str(nature_id)) if nature_id else ""
        nest_label = {"normal": "普通窝", "green": "学院绿窝"}.get(
            nest_override or ("normal" if egg.home_egg else ""), ""
        )
        rows.append(
            {
                "instance_id": egg.instance_id,
                "egg_conf_id": egg.egg_conf_id,
                "egg_name": info.egg_name if info else f"蛋 #{egg.egg_conf_id}",
                "species_name": info.species_name if info else "",
                "chain_names": chain_names,
                "description": info.description if info else "",
                "description_source": info.description_source if info else "",
                "icon_url": (
                    f"/static/egg-icons/{info.icon_item_id}.webp"
                    if info is not None and info.icon_item_id
                    else ""
                ),
                "fallback_icon_url": "",
                "egg_kind": kind,
                "egg_type_name": EGG_KIND_LABELS[kind],
                "egg_group_names": list(info.egg_group_names) if info is not None else [],
                "hatch_label": hatch_label,
                "quantity": egg.quantity,
                "obtained_at": egg.obtained_at,
                "historical": historical,
                "hatching": hatching,
                "hatch_known": view.slots_source == "observed",
                "historical_hatching": history_hatch,
                "favorite": favorite,
                "in_slot": in_slot,
                "hatch_progress": round(egg.hatch_progress, 4),
                "category": egg.category,
                "special_egg_conf_id": egg.special_egg_conf_id,
                "height_cm": egg.height_cm,
                "weight_g": egg.weight_g,
                "home_egg": egg.home_egg,
                "annotations": {"nature_id": nature_id, "nest_override": nest_override,
                                "note": note, "voice_tag": voice_tag, "voice_db": voice_db},
                "tags": {"nature": nature_label, "weight": weight_label, "voice": voice_label,
                         "medals": medals, "nest": nest_label},
                "measurement_ranges": {
                    "height_cm": {"min": info.height_low, "max": info.height_high}
                    if info is not None and info.height_high > info.height_low else None,
                    "weight_g": {"min": info.weight_low, "max": info.weight_high}
                    if info is not None and info.weight_high > info.weight_low else None,
                },
                "reference_ranges": {"height": range_text((info.height_low, info.height_high), 100, "m") if info else "暂无数据",
                                     "weight": range_text((info.weight_low, info.weight_high), 1000, "kg") if info else "暂无数据"},
            }
        )
    return {
        "eggs": rows,
        "total": len(entries),
        "nature_options": [{"id": key, "name": value} for key, value in nature_options],
        "total_quantity": total_quantity,
        "hatching": hatching_count if view.slots_source == "observed" else None,
        "historical_hatching": historical_hatching,
        "source": view.source,
        "slots_source": view.slots_source,
        "complete": None,
        "hatch_slots": len(slots),
        "version": view.version,
        # 数据归属（R05）：前端据此核对当前账号身份，拒绝旧账号响应
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
    details: bool = False,
) -> dict:
    """蛋图鉴载荷：蛋目录静态数据 + 可选筛选（搜索/蛋组/蛋类型/孵化时长下限）。"""
    entries = catalog.entries() if catalog is not None else ()
    type_icons = {
        info.name: f"/static/type-icons/type-{type_id}.webp"
        for type_id, info in static.type_items()
    } if static is not None else {}
    keyword = search.strip().lower()
    rows: list[dict] = []
    for info in entries:
        male, female = info.gender_male, info.gender_female
        species = static.species(info.base_id) if static is not None else None
        if not (male or female) and species is not None and species.name == info.name:
            male, female = species.gender_ratio
        if keyword and not any(keyword in value.lower() for value in (
            info.name_key, info.name, info.egg_name, str(info.egg_conf_id),
            *(static.chain_names(int(info.base_id)) if (static is not None and info.base_id) else ()),
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
                "can_same_ride": static.wiki_reference.can_double_ride(info.base_id, info.name) if static is not None else None,
                "wiki": static.wiki_reference.species(info.base_id, info.name) if details and static is not None else None,
                "egg_name": info.egg_name,
                "name": info.name,
                "base_id": info.base_id,
                "icon_url": species_icon_url(info.base_id) if info.base_id else "",
                "egg_icon_url": (
                    f"/static/egg-icons/{info.egg_item_id}.webp" if info.egg_item_id else ""
                ),
                "handbook_no": info.handbook_no,
                "dex_no": info.dex_no,
                "egg_type_name": info.egg_type_name,
                "hatch_label": info.hatch_label,
                "hatch_seconds": info.hatch_seconds,
                "egg_group_names": list(info.egg_group_names),
                "gender_male": male,
                "gender_female": female,
                "type_names": list(species.type_names) if species is not None else [],
                "type_colors": [type_color_for(static, name) for name in species.type_names] if species is not None and static is not None else [],
                "type_icons": {name: type_icons[name] for name in species.type_names if name in type_icons} if species is not None else {},
                "gender_ratio_text": (
                    f"♂{male}% / ♀{female}%"
                    if male or female
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
        "type_option_icons": type_icons,
        "filters": {
            "search": search,
            "group": group,
            "egg_type": egg_type,
            "hatch_min_hours": hatch_min_hours,
        },
    }


__all__ = [
    "egg_box_payload",
    "home_payload",
    "colors_payload",
    "egg_dex_payload",
    "handbook_payload",
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
