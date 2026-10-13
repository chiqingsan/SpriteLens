"""背包条件池与快捷奖章规则；复用卡片展示的标记来源。"""
from __future__ import annotations

from collections.abc import Iterable

from spritelens.domain.measurements import range_position
from spritelens.domain.pet_marks import pet_marks
from spritelens.domain.pets import Pet
from spritelens.domain.static_data import StaticData

MAX_PET_LEVEL = 60
POOL_KEYS = frozenset({"medal", "male", "shiny", "max_height", "max_weight"})
MARK_NAMES = ("大块头", "小不点", "婉转声", "粗嗓门")
ACQUISITION_NAMES = {1: "捕捉", 2: "互访捕捉", 3: "孵化", 4: "花种", 5: "传说", 6: "守护地"}


def matches_conditions(pet: Pet, static: StaticData | None, *, pool: frozenset[str],
                       pool_mode: str, shiny: bool, colorful: bool, medal: int,
                       marks: frozenset[str], speciality: int, additional: Iterable[bool] = ()) -> bool:
    species = static.species(pet.base_conf_id) if static else None
    names = {item["name"] for item in pet_marks(pet, species.weight_range if species else (0, 0))}
    checks = list(additional)
    if shiny:
        checks.append(bool(pet.mutation_type & 1))
    if colorful:
        checks.append(bool(pet.mutation_type & 8))
    if medal:
        checks.append(pet.worn_medal_id == medal)
    if speciality:
        checks.append(pet.speciality_id == speciality)
    checks.extend(name in names for name in marks)
    values = {"medal": bool(pet.worn_medal_id), "male": pet.gender == 1,
              "shiny": bool(pet.mutation_type & 1)}
    for field in ("height", "weight"):
        position = range_position(getattr(pet, field), getattr(species, field + "_range", (0, 0)))
        values["max_" + field] = position["status"] == "within" and position["ratio"] == 1
    checks.extend(values[key] for key in pool)
    return not checks or (any if pool_mode == "or" else all)(checks)
