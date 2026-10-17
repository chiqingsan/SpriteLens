"""筛选配对的静态候选规则；不代表实际配窝或已验证遗传。"""
from __future__ import annotations

from dataclasses import dataclass, replace
from math import trunc

from spritelens.domain.measurements import range_position
from spritelens.domain.pet_marks import pet_marks
from spritelens.domain.pets import Pet
from spritelens.domain.static_data import SpeciesInfo, StaticData


MARKS = ("双奖牌", "大块头", "小不点", "婉转声", "粗嗓门")
EXCLUDED_GROUPS = frozenset(("无", "未发现", "无法孵蛋", "无蛋组", "未知", "暂无蛋组"))


@dataclass(frozen=True)
class BreederFilters:
    search: str = ""
    groups: frozenset[str] = frozenset()
    natures: frozenset[str] = frozenset()
    marks: frozenset[str] = frozenset()
    voice_min: float | None = None
    voice_max: float | None = None
    height_min: float | None = None
    height_max: float | None = None
    weight_min: float | None = None
    weight_max: float | None = None
    same_nature: bool = True
    male: int = 0
    female: int = 0
    anchor: int = 0
    male_page: int = 1
    female_page: int = 1


@dataclass(frozen=True)
class Candidate:
    pet: Pet
    species: SpeciesInfo
    nature: str
    groups: tuple[str, ...]
    chain: tuple[int, ...]
    marks: tuple[dict, ...]
    height: float | None
    weight: float | None
    voice: int | None


def candidates(pets: tuple[Pet, ...], static: StaticData, voice_overrides: dict[int, int]) -> tuple[Candidate, ...]:
    result = []
    for pet in pets:
        species = static.species(pet.base_conf_id)
        if species is None or pet.gender not in (1, 2) or not species.egg_groups:
            continue
        if any(group in EXCLUDED_GROUPS for group in species.egg_groups):
            continue
        nature = static.nature(pet.nature)
        voice = voice_overrides.get(pet.gid, pet.voice if pet.voice != 0 else None)
        voice = voice if voice is not None and -100 <= voice <= 100 else None
        effective_pet = replace(pet, voice=voice) if voice is not None else pet
        result.append(Candidate(pet, species, nature.name if nature else "", species.egg_groups,
                                tuple(sorted(species.chain_members or (pet.base_conf_id,))),
                                tuple(pet_marks(effective_pet, species.weight_range)),
                                range_position(pet.height, species.height_range)["ratio"],
                                range_position(pet.weight, species.weight_range)["ratio"],
                                voice))
    return tuple(sorted(result, key=lambda row: (row.species.dex_no, -row.pet.level, row.pet.gid)))


def can_pair(male: Candidate, female: Candidate, same_nature: bool) -> bool:
    return (male.pet.gender == 1 and female.pet.gender == 2
            and bool(set(male.groups) & set(female.groups))
            and (not same_nature or bool(male.nature) and male.nature == female.nature))


def matches(row: Candidate, filters: BreederFilters) -> bool:
    search = filters.search.strip().casefold()
    if search and search not in " ".join((row.pet.name, row.species.name, row.nature,
                                          str(row.pet.gid), str(row.species.dex_no), *row.groups)).casefold():
        return False
    if filters.groups and not filters.groups.intersection(row.groups):
        return False
    if filters.natures and row.nature not in filters.natures:
        return False
    names = {mark["name"] for mark in row.marks}
    if filters.marks - {"双奖牌"} - names or "双奖牌" in filters.marks and len(names) < 2:
        return False
    for value, low, high, ratio in ((row.voice, filters.voice_min, filters.voice_max, False),
                                     (row.height, filters.height_min, filters.height_max, True),
                                     (row.weight, filters.weight_min, filters.weight_max, True)):
        if low is None and high is None:
            continue
        # 目录外的体型值不能参与百分比筛选或均值参考。
        if value is None or low is not None and value < low or high is not None and value > high:
            return False
        if ratio and not 0 <= value <= 1:
            return False
    return True


def prediction(male: Candidate, female: Candidate) -> dict:
    distribution: dict[str, int] = {}
    unknown = 0
    for row in (male, female):
        if row.nature:
            distribution[row.nature] = distribution.get(row.nature, 0) + 30
        else:
            unknown += 30
    def mean(a: float | None, b: float | None) -> float | None:
        return round((a + b) / 2, 4) if a is not None and b is not None and 0 <= a <= 1 and 0 <= b <= 1 else None
    return {"groups": sorted(set(male.groups) & set(female.groups)),
            "natures": distribution, "random_percent": 40, "unknown_percent": unknown,
            "voice": trunc((male.voice + female.voice) / 2) if male.voice is not None and female.voice is not None else None,
            "height_ratio": mean(male.height, female.height), "weight_ratio": mean(male.weight, female.weight)}
