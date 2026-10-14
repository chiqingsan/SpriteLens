"""背包详情展示载荷：复用个体和静态资料，不另行读取仓库。"""
from __future__ import annotations

from spritelens.domain.pets import Pet
from spritelens.domain.static_data import StaticData
from spritelens.domain.measurements import range_position
from spritelens.domain.pet_conditions import ACQUISITION_NAMES
from spritelens.web.pet_media import pet_images


def detail_payload(pet: Pet, static: StaticData | None, egg_catalog=None) -> dict:
    species = static.species(pet.base_conf_id) if static else None
    egg = egg_catalog.egg_by_base_id(pet.base_conf_id) if egg_catalog else None
    measurements = {}
    egg_limits = {}
    for field, scale in (("height", 100), ("weight", 1000)):
        limits = getattr(species, f"{field}_range") if species else (0, 0)
        position = range_position(getattr(pet, field), limits)
        measurements[field] = {"value": getattr(pet, field) / scale if getattr(pet, field) else None,
                               "limits": [value / scale for value in limits] if limits[0] > 0 and limits[1] >= limits[0] else None,
                               **position}
        low, high = (getattr(egg, f"{field}_low"), getattr(egg, f"{field}_high")) if egg else (0, 0)
        egg_limits[field] = [low / scale, high / scale] if low > 0 and high >= low else None
    ratio = (pet.voice + 100) / 200 if pet.voice else None
    measurements["voice"] = {"value": pet.voice if pet.voice else None, "limits": [-100, 100], "ratio": ratio,
                             "status": "unknown" if ratio is None else "below" if ratio < 0 else "above" if ratio > 1 else "within"}
    members = set(species.chain_members or (pet.base_conf_id, *species.evolutions)) if species else set()
    nodes, edges = [], []
    for base_id in sorted(members):
        member = static.species(base_id)
        nodes.append({"id": base_id, "name": member.name if member else f"物种 #{base_id}",
                      "dex_no": member.dex_no if member else 0,
                      "portrait_url": pet_images(base_id)["portrait_url"]})
        if member:
            edges.extend([base_id, target] for target in member.evolutions if target in members)
    medal_ids = sorted(set(pet.awarded_medal_ids)) if pet.awarded_medal_ids is not None else None
    return {
        "speciality_name": static.speciality_name(pet.speciality_id) if static and pet.speciality_id else
                           f"特性 #{pet.speciality_id}" if pet.speciality_id else "特性未知",
        "acquisition_name": ACQUISITION_NAMES.get(pet.catch_way, f"方式 #{pet.catch_way}" if pet.catch_way else "未采集"),
        "types": [{"name": name, "icon_url": f"/static/type-icons/type-{key}.png"}
                  for key, info in static.type_items() if species and key in species.types
                  for name in [info.name]] if static else [],
        "measurements": measurements, "egg_limits": egg_limits,
        "evolution": {"nodes": nodes, "edges": edges},
        "awarded_medals": [{"id": key, "name": static.medal_name(key) if static else f"奖牌 #{key}",
                            "icon_url": f"/static/medal-icons/{key}.png"} for key in medal_ids] if medal_ids is not None else None,
    }
