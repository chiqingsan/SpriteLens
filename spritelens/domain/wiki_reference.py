"""离线 Wiki 补充目录。只按已知游戏 ID 联查，名称不一致时不借用其它形态。"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path


class WikiReference:
    def __init__(self, directory: Path | None) -> None:
        path = directory / "wiki_reference.json" if directory is not None else None
        self._data = json.loads(path.read_text(encoding="utf-8")) if path is not None and path.is_file() else {}

    def _entry(self, base_id: str | int, name: str) -> dict | None:
        pet = self._data.get("catalog", {}).get(str(base_id))
        if pet is None:
            return None
        normalized_name = unicodedata.normalize("NFKC", name).replace(" ", "")
        if normalized_name not in tuple(unicodedata.normalize("NFKC", value).replace(" ", "")
                                        for value in (pet["name"], pet["title"])):
            return None
        return pet

    def can_double_ride(self, base_id: str | int, name: str) -> bool | None:
        pet = self._entry(base_id, name)
        return pet.get("can_double_ride") if pet is not None else None

    def species(self, base_id: str | int, name: str) -> dict | None:
        pet = self._entry(base_id, name)
        if pet is None:
            return None
        skills = self._data["skills"]
        learnset = self._data["learnsets"].get(pet["learnset_id"], {})
        rows = []
        for source, entries in (("自学", learnset.get("native_skills", [])),
                                ("技能石", [{"skill": key} for key in learnset.get("skill_stones", [])]),
                                ("血脉", learnset.get("blood_skills", []))):
            for entry in entries:
                skill = skills[entry["skill"]]
                rows.append({"id": entry["skill"], "name": skill["name"], "description": skill.get("desc", ""),
                             "type": skill.get("element", ""), "category": skill.get("damage_class", skill["category"]),
                             "power": skill.get("power"), "energy": skill.get("energy"), "source": source,
                             "level": entry.get("level"), "blood": entry.get("blood", "")})
        feature = skills.get(pet["feature_skill_id"])
        ecology = pet.get("ecology") or {}
        evolutions = []
        for branch in self._data["evolutions"].get(pet["evolution_id"], []):
            evolutions.append({"name": branch["name"], "members": [
                {"name": member.get("title", member["name"]), "level": member.get("level"),
                 "condition": member.get("cond", ""), "item": member.get("item", "")}
                for member in [*branch.get("chain", []), *branch.get("lord_branches", [])]]})
        return {"source_url": pet["source_url"], "updated_at": self._data["retrieved_at"][:10],
                "classification": pet.get("class") or "", "can_ride": pet.get("can_ride"),
                "can_double_ride": pet.get("can_double_ride"),
                "feature": {"name": feature["name"], "description": feature.get("desc", "")} if feature else None,
                "skills": rows, "areas": ecology.get("areas", []), "evolutions": evolutions,
                "eggs": [{"name": egg["name"], "description": egg.get("description", ""),
                          "sources": egg.get("sources", [])} for egg in ecology.get("eggs", [])],
                "activities": [{"name": activity["name"], "window": activity.get("window", ""),
                                "note": activity.get("note", "")} for activity in ecology.get("activities", [])]}
