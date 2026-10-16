"""从单次账号快照计算产线；不建立第二份库存或持久化状态。"""
from __future__ import annotations

from dataclasses import dataclass

from spritelens.domain.collection_lines import Breeder, CollectionGoal, CollectionLine, build_catalog, collect_lines
from spritelens.domain.eggs import EggCatalog
from spritelens.domain.static_data import StaticData
from spritelens.services.pet_repository import PetRepository, PetRepoSnapshot


@dataclass(frozen=True)
class CollectionSnapshot:
    inventory: PetRepoSnapshot
    lines: tuple[CollectionLine, ...]
    fathers: tuple[Breeder, ...]
    available: bool


class CollectionLinesService:
    def __init__(self, repository: PetRepository, static: StaticData | None, eggs: EggCatalog | None) -> None:
        self._repository = repository
        self._static = static
        self._chains = build_catalog(static, eggs) if static is not None and eggs is not None else ()

    def snapshot(self, goal: CollectionGoal) -> CollectionSnapshot:
        inventory = self._repository.consistent_snapshot()
        if self._static is None:
            return CollectionSnapshot(inventory, (), (), False)
        lines, fathers = collect_lines(self._chains, inventory.pets, self._static, goal)
        return CollectionSnapshot(inventory, lines, fathers, bool(self._chains))
