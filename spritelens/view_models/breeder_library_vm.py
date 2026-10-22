"""当前账号筛选配对：一次快照内完成两侧筛选和亲本校验。"""
from __future__ import annotations

from dataclasses import dataclass

from spritelens.domain.breeder_library import BreederFilters, Candidate, candidates, can_pair, matches, prediction
from spritelens.domain.static_data import StaticData
from spritelens.services.pet_repository import PetRepository, PetRepoSnapshot

PAGE_SIZE = 24


@dataclass(frozen=True)
class BreederView:
    inventory: PetRepoSnapshot
    available: bool
    groups: tuple[str, ...]
    natures: tuple[str, ...]
    males: tuple[Candidate, ...]
    females: tuple[Candidate, ...]
    male_total: int
    female_total: int
    male_page: int
    female_page: int
    selected_male: Candidate | None
    selected_female: Candidate | None
    anchor: int
    selection_changed: bool
    prediction: dict | None


class BreederLibraryViewModel:
    def __init__(self, repository: PetRepository, static: StaticData | None) -> None:
        self._repository = repository
        self._static = static

    def snapshot(self, filters: BreederFilters) -> BreederView:
        inventory = self._repository.consistent_snapshot()
        pool = candidates(inventory.pets, self._static) if self._static else ()
        by_id = {row.pet.gid: row for row in pool}
        male, female = by_id.get(filters.male), by_id.get(filters.female)
        male = male if male and male.pet.gender == 1 else None
        female = female if female and female.pet.gender == 2 else None
        anchor = male if filters.anchor == 1 else female if filters.anchor == 2 else male or female
        if male and female and not can_pair(male, female, filters.same_nature):
            if anchor is female:
                male = None
            else:
                female = None
        anchor = anchor or male or female
        visible = tuple(row for row in pool if matches(row, filters))
        males = tuple(row for row in visible if row.pet.gender == 1)
        females = tuple(row for row in visible if row.pet.gender == 2)
        if anchor:
            if anchor.pet.gender == 1:
                males = tuple(row for row in males if row.chain == anchor.chain)
                females = tuple(row for row in females if can_pair(anchor, row, filters.same_nature))
            else:
                females = tuple(row for row in females if row.chain == anchor.chain)
                males = tuple(row for row in males if can_pair(row, anchor, filters.same_nature))
        male_page = min(filters.male_page, max(1, (len(males) + PAGE_SIZE - 1) // PAGE_SIZE))
        female_page = min(filters.female_page, max(1, (len(females) + PAGE_SIZE - 1) // PAGE_SIZE))
        return BreederView(inventory, self._static is not None,
                           tuple(sorted({group for row in pool for group in row.groups})),
                           tuple(nature.name for _, nature in self._static.nature_items()) if self._static else (),
                           males[(male_page - 1) * PAGE_SIZE:male_page * PAGE_SIZE],
                           females[(female_page - 1) * PAGE_SIZE:female_page * PAGE_SIZE],
                           len(males), len(females), male_page, female_page, male, female,
                           anchor.pet.gender if anchor else 0,
                           bool(filters.male and male is None or filters.female and female is None),
                           prediction(male, female) if male and female else None)
