"""家园巢穴范围内的确定性繁育候选。"""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot

from spritelens.domain.home import HomeCouple, HomeFurniture, HomeResident, home_floor


@dataclass(frozen=True)
class HomeBreedingProfile:
    gender: int
    egg_groups: tuple[str, ...]


_INFERTILE_GROUPS = frozenset(("无", "未发现", "无法孵蛋", "无蛋组"))
_UNKNOWN_GROUPS = frozenset(("未知", "暂无蛋组"))


def _in_range(a: HomeFurniture, b: HomeFurniture) -> bool:
    if not a.position_known or not b.position_known or home_floor(a.position) != home_floor(b.position):
        return False
    dx = max(0.0, abs(a.position[0] - b.position[0]) / 40 - 4)
    dy = max(0.0, abs(a.position[1] - b.position[1]) / 40 - 4)
    return hypot(dx, dy) <= 10 + 1e-9


def _compatible(a: HomeBreedingProfile, b: HomeBreedingProfile) -> bool:
    if a.gender not in (1, 2) or b.gender not in (1, 2) or a.gender == b.gender:
        return False
    if any(group in _INFERTILE_GROUPS for group in (*a.egg_groups, *b.egg_groups)):
        return False
    groups_a = {group for group in a.egg_groups if group and group not in _UNKNOWN_GROUPS}
    groups_b = {group for group in b.egg_groups if group and group not in _UNKNOWN_GROUPS}
    return bool(groups_a and groups_b and groups_a & groups_b)


def infer_range_couples(
    residents: tuple[HomeResident, ...],
    nests: tuple[HomeFurniture, ...],
    profiles: dict[int, HomeBreedingProfile],
) -> tuple[HomeCouple, ...]:
    """按解包版巢穴边缘距离规则，只返回性别与蛋组都能确认的候选。"""
    nests_by_guid = {piece.guid: piece for piece in nests if piece.guid}
    placed = [
        (resident, profiles.get(resident.actor_id), nests_by_guid.get(resident.nest_guid))
        for resident in residents
    ]
    pairs: list[HomeCouple] = []
    for mother, mother_profile, mother_nest in placed:
        if mother_profile is None or mother_profile.gender != 2 or mother_nest is None:
            continue
        fathers = tuple(
            father.actor_id
            for father, father_profile, father_nest in placed
            if father.actor_id != mother.actor_id and father_profile is not None
            and father_profile.gender == 1 and father_nest is not None
            and _compatible(mother_profile, father_profile)
            and _in_range(mother_nest, father_nest)
        )
        if fathers:
            pairs.append(HomeCouple(mother.actor_id, fathers))
    return tuple(pairs)


__all__ = ["HomeBreedingProfile", "infer_range_couples"]
