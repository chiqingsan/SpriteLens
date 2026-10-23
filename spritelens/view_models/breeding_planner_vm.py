"""智能配窝页面的库存/目录视图；不依赖 Web。"""
from __future__ import annotations

from spritelens.domain.breeding_planner import GEOMETRY_VERSION, RULE_VERSION


class BreedingPlannerViewModel:
    def __init__(self, service):
        self.service = service

    def context(self) -> dict:
        inventory, pool = self.service.snapshot()
        rows = []
        if pool:
            for gid, parent in pool.parents.items():
                pet = parent.pet
                location = inventory.locations.get(pet.gid)
                rows.append({"gid": gid, "name": pet.name or parent.species.name, "species": parent.species.name,
                             "dex_no": parent.species.dex_no, "gender": pet.gender, "nature": parent.nature,
                             "groups": parent.groups, "marks": parent.marks, "voice": parent.voice,
                             "height_ratio": parent.height, "weight_ratio": parent.weight,
                             "is_shiny": bool(pet.mutation_type & 1), "is_colorful": bool(pet.mutation_type & 8),
                             "base_id": pet.base_conf_id, "egg_key": pool.eggs.get(gid),
                             "location": location.payload() if location else None})
        targets = {}
        if pool:
            for base_id, species in self.service.static.species_items():
                egg = self.service.eggs.egg_by_base_id(int(base_id))
                if egg and egg.egg_type_name in ("普通", "普通蛋") and any(g not in {"", "未知", "未发现", "无", "无法孵蛋", "无蛋组", "暂无蛋组", "暂无"} for g in species.egg_groups) and not any(g in {"无", "无法孵蛋", "无蛋组"} for g in species.egg_groups):
                    chain_names = [
                        member.name for member_id in egg.chain_members
                        if (member := self.service.static.species(member_id)) is not None
                    ]
                    targets[egg.egg_key] = {"egg_key": egg.egg_key, "name": egg.egg_name, "groups": egg.egg_group_names,
                                            "base_id": egg.base_id, "icon_url": f"/static/egg-icons/{egg.egg_item_id}.webp",
                                            "chain_names": chain_names}
        return {"uid": inventory.uid, "version": inventory.version, "available": pool is not None,
                "source": "observed" if inventory.identity else "history", "pet_count": len(inventory.pets),
                "parents": sorted(rows, key=lambda row: (row["dex_no"], row["gid"])),
                "eggs": sorted(targets.values(), key=lambda row: row["egg_key"]),
                "natures": [{"id": key, "name": value} for key, value in pool.natures.items()] if pool else [],
                "issues": list(pool.issues) if pool else ["静态目录不可用"],
                "rule_version": RULE_VERSION, "geometry_version": GEOMETRY_VERSION, "catalog_version": self.service.catalog_version}
