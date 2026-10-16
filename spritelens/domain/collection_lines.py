"""双牌产线参考规则：纯目录聚合与同账号候选，不代表已实际配窝。"""
from __future__ import annotations

from dataclasses import dataclass

from spritelens.domain.eggs import EggCatalog
from spritelens.domain.pet_marks import pet_marks
from spritelens.domain.pets import Pet
from spritelens.domain.static_data import SpeciesInfo, StaticData

GOALS = {
    "big-soft": ("大块头", "婉转声"),
    "big-loud": ("大块头", "粗嗓门"),
    "small-soft": ("小不点", "婉转声"),
    "small-loud": ("小不点", "粗嗓门"),
}
EXCLUDED_GROUPS = frozenset(("无", "未发现", "无法孵蛋", "无蛋组", "未知", "暂无蛋组", "暂无"))


@dataclass(frozen=True)
class CollectionGoal:
    key: str = "big-soft"
    sound: int | None = None
    full_weight: bool = False
    colorful: bool = False
    ignore_missing_male: bool = False


@dataclass(frozen=True)
class CollectionChain:
    key: str
    members: tuple[int, ...]
    groups: tuple[str, ...]
    egg_key: str
    gaps: tuple[str, ...] = ()


@dataclass(frozen=True)
class Breeder:
    pet: Pet
    species: SpeciesInfo
    nature: str
    marks: tuple[tuple[str, str], ...]
    basis: tuple[str, ...]


@dataclass(frozen=True)
class CollectionLine:
    chain: CollectionChain
    status: str
    mothers: tuple[Breeder, ...]
    pairs: tuple[tuple[int, tuple[int, ...]], ...]


def build_catalog(static: StaticData, eggs: EggCatalog) -> tuple[CollectionChain, ...]:
    """以目录成员 ID 归一链；交叠而不一致的声明留作资料待补。"""
    chains: dict[tuple[int, ...], CollectionChain] = {}
    for raw_id, species in static.species_items():
        base_id = int(raw_id)
        egg = eggs.egg_by_base_id(base_id)
        groups = tuple(group for group in species.egg_groups if group and group not in EXCLUDED_GROUPS)
        if not groups or egg is None:
            continue
        members = tuple(sorted(set(species.chain_members or (base_id,)) | {base_id}))
        if members in chains:
            continue
        gaps = []
        for member_id in members:
            member = static.species(member_id)
            if member is None:
                gaps.append(f"物种 #{member_id} 资料缺失")
            elif member.chain_members and tuple(sorted(set(member.chain_members) | {member_id})) != members:
                gaps.append("进化链成员声明冲突")
        chains[members] = CollectionChain("chain:" + ":".join(map(str, members)), members, groups,
                                          egg.egg_key, tuple(dict.fromkeys(gaps)))
    memberships: dict[int, int] = {}
    for members in chains:
        for member in members:
            memberships[member] = memberships.get(member, 0) + 1
    return tuple(CollectionChain(chain.key, chain.members, chain.groups, chain.egg_key,
                                 tuple(dict.fromkeys((*chain.gaps, "进化链重叠冲突"))))
                 if any(memberships[member] > 1 for member in chain.members) else chain
                 for chain in chains.values())


def breeder(pet: Pet, static: StaticData, goal: CollectionGoal) -> Breeder | None:
    species = static.species(pet.base_conf_id)
    nature = static.nature(pet.nature)
    if pet.is_trial_pet or pet.is_mirror_pet or species is None or nature is None:
        return None
    if pet.gender not in (1, 2) or not species.egg_groups or any(g in EXCLUDED_GROUPS for g in species.egg_groups):
        return None
    marks = pet_marks(pet, species.weight_range)
    tags = [mark["name"] for mark in marks]
    basis = [f'{mark["name"]}（{"佩戴奖牌" if mark["source"] == "worn" else "数值参考"}）' for mark in marks]
    # 身高极值的培育经验不证明个体具有体型标记，不能计入双牌收集。
    if not set(GOALS[goal.key]).issubset(tags):
        return None
    if goal.sound is not None and pet.voice != goal.sound:
        return None
    low, high = species.weight_range
    if goal.full_weight and not (high > low > 0 and pet.weight == high):
        return None
    if goal.colorful and not pet.mutation_type & 8:
        return None
    return Breeder(pet, species, nature.name, tuple((mark["name"], mark["source"]) for mark in marks), tuple(basis))


def collect_lines(chains: tuple[CollectionChain, ...], pets: tuple[Pet, ...], static: StaticData,
                  goal: CollectionGoal) -> tuple[tuple[CollectionLine, ...], tuple[Breeder, ...]]:
    parents = tuple(parent for pet in pets if (parent := breeder(pet, static, goal)) is not None)
    fathers = tuple(parent for parent in parents if parent.pet.gender == 1)
    # 每次快照按性格和蛋组建立索引，避免每条链重扫整仓种公。
    male_index: dict[tuple[str, str], set[int]] = {}
    for father in fathers:
        for group in father.species.egg_groups:
            male_index.setdefault((father.nature, group), set()).add(father.pet.gid)
    mothers_by_species: dict[int, list[Breeder]] = {}
    for parent in parents:
        if parent.pet.gender == 2:
            mothers_by_species.setdefault(parent.pet.base_conf_id, []).append(parent)
    lines = []
    for chain in chains:
        mothers = tuple(mother for member in chain.members for mother in mothers_by_species.get(member, ()))
        pairs = tuple((mother.pet.gid, tuple(sorted(set().union(*(
            male_index.get((mother.nature, group), set()) for group in mother.species.egg_groups
        ))))) for mother in mothers)
        status = "unknown" if chain.gaps else "collected" if any(males for _, males in pairs) else "missingMale" if mothers else "missing"
        lines.append(CollectionLine(chain, status, mothers, pairs))
    return tuple(lines), fathers
