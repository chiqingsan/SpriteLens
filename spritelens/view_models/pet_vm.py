"""宠物仓库 ViewModel：快照读取、多维筛选、排序与聚合统计。

纯 Python（零 UI 框架依赖），本地服务与前端只消费它的输出。
筛选维度对 roco_helper 的筛选器：搜索（名字/gid/conf_id）、等级范围、
性格多选、系别多选、天赋阶下限、只看首捕。系别筛选依赖静态物种表
（可选注入；缺省时该维度被忽略，不抛错）。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from spritelens.domain.pets import Pet
from spritelens.domain.static_data import StaticData
from spritelens.services.pet_repository import PetRepository

# 排序键（UI 排序菜单用）
SORT_KEYS: tuple[tuple[str, str], ...] = (
    ("gid", "编号"),
    ("conf_id", "图鉴 ID"),
    ("level", "等级"),
    ("talent_rank", "天赋阶"),
    ("stat_sum", "六维总和"),
    ("name", "名字"),
)


@dataclass(frozen=True)
class PetFilters:
    """筛选条件；空集合语义为「不限」。"""

    search: str = ""
    level_min: int = 1
    level_max: int = 100
    natures: frozenset[int] = frozenset()
    type_names: frozenset[str] = frozenset()
    talent_min: int = 0
    first_catch_only: bool = False
    gender: int = 0

    @property
    def active(self) -> bool:
        return bool(
            self.search
            or self.natures
            or self.type_names
            or self.talent_min > 0
            or self.first_catch_only
            or self.gender
            or self.level_min > 1
            or self.level_max < 100
        )


@dataclass(frozen=True)
class PetStats:
    """仓库聚合统计（概览页与页内统计条共用）。"""

    total: int = 0
    first_catch: int = 0
    maxed: int = 0
    max_level: int = 0
    type_counts: tuple[tuple[str, int], ...] = field(default_factory=tuple)


class PetViewModel:
    """宠物仓库的状态与命令：过滤/排序状态 + 快照读取。"""

    def __init__(self, repository: PetRepository, static_data: StaticData | None = None) -> None:
        self._repository = repository
        self._static = static_data
        self._search = ""
        self._filters = PetFilters()
        self._sort_key = "gid"
        self._sort_desc = False

    # -- 命令 ----------------------------------------------------------
    def set_search(self, text: str) -> None:
        self._search = text.strip().lower()
        self._filters = replace(self._filters, search=self._search)

    def set_level_range(self, minimum: int, maximum: int) -> None:
        self._filters = replace(
            self._filters,
            level_min=max(1, min(minimum, maximum)),
            level_max=max(minimum, maximum),
        )

    def set_natures(self, natures: frozenset[int]) -> None:
        self._filters = replace(self._filters, natures=natures)

    def set_types(self, type_names: frozenset[str]) -> None:
        self._filters = replace(self._filters, type_names=type_names)

    def set_talent_min(self, rank: int) -> None:
        self._filters = replace(self._filters, talent_min=max(0, int(rank)))

    def set_first_catch_only(self, enabled: bool) -> None:
        self._filters = replace(self._filters, first_catch_only=bool(enabled))

    def set_gender(self, gender: int) -> None:
        self._filters = replace(self._filters, gender=gender if gender in (1, 2) else 0)

    def set_sort(self, key: str, *, descending: bool = False) -> None:
        if key not in {k for k, _ in SORT_KEYS}:
            key = "gid"
        self._sort_key = key
        self._sort_desc = descending

    def reset_filters(self) -> None:
        self._search = ""
        self._filters = PetFilters()

    def clear(self) -> None:
        self._repository.clear()

    # -- 视图 ----------------------------------------------------------
    @property
    def filters(self) -> PetFilters:
        return self._filters

    @property
    def sort_state(self) -> tuple[str, bool]:
        return self._sort_key, self._sort_desc

    def filtered_pets(self) -> tuple[Pet, ...]:
        """按当前筛选与排序返回宠物（UI 表格数据源）。"""
        pets = self._apply_filters(self._repository.snapshot())
        return self._apply_sort(pets)

    def all_pets(self) -> tuple[Pet, ...]:
        """全部宠物（不筛选；概览页统计用）。"""
        return self._repository.snapshot()

    def filtered_count(self) -> int:
        return len(self.filtered_pets())

    def total_count(self) -> int:
        return len(self._repository.snapshot())

    def version(self) -> int:
        return self._repository.version

    def stats(self) -> PetStats:
        """聚合统计：总量/首捕/满级/最高等级/系别分布（按主系别）。"""
        pets = self._repository.snapshot()
        if not pets:
            return PetStats()
        counts: dict[str, int] = {}
        for pet in pets:
            counts[self._primary_type(pet)] = counts.get(self._primary_type(pet), 0) + 1
        ranked = tuple(sorted(counts.items(), key=lambda kv: kv[1], reverse=True))
        return PetStats(
            total=len(pets),
            first_catch=sum(1 for p in pets if p.is_first_catch),
            maxed=sum(1 for p in pets if p.level >= 60),
            max_level=max(p.level for p in pets),
            type_counts=ranked,
        )

    def nature_options(self) -> tuple[tuple[int, str], ...]:
        """出现过的性格（id, 名字），供筛选器多选。"""
        seen: dict[int, str] = {}
        for pet in self._repository.snapshot():
            if pet.nature in seen:
                continue
            name = str(pet.nature)
            if self._static is not None:
                info = self._static.nature(pet.nature)
                if info is not None:
                    name = info.name
            seen[pet.nature] = name
        return tuple(sorted(seen.items(), key=lambda kv: kv[0]))

    def type_options(self) -> tuple[str, ...]:
        """出现过的系别名（依赖静态表；无静态表返回空）。"""
        if self._static is None:
            return ()
        names: set[str] = set()
        for pet in self._repository.snapshot():
            species = self._static.species(pet.base_conf_id)
            if species is not None:
                names.update(species.type_names)
        return tuple(sorted(names))

    def species_of(self, pet: Pet):
        """宠物的静态物种信息（UI 展示系别/种族值用）；无静态表返回 None。"""
        if self._static is None:
            return None
        return self._static.species(pet.base_conf_id)

    def talent_rank_max(self) -> int:
        pets = self._repository.snapshot()
        return max((p.talent_rank for p in pets), default=0)

    # -- 持久化 --------------------------------------------------------
    def load_persisted(self, uid: int) -> int:
        """载入历史宠物（重启后"数据还在"的入口）；返回补入条数。"""
        return self._repository.load_persisted(uid)

    @property
    def identity(self):
        """当前角色身份（uid/名字/等级）；未识别到返回 None。"""
        return self._repository.identity

    def cached_accounts(self) -> tuple[tuple[int, str], ...]:
        """本地库里有历史的账号（uid, 名字），供离线时也能加载。"""
        return self._repository.cached_accounts()

    def load_last_account(self) -> int:
        """启动即载入最近账号的历史宠物（离线也能看到上次的数据）。"""
        return self._repository.load_last_account()

    # -- 内部 ----------------------------------------------------------
    def _apply_filters(self, pets: tuple[Pet, ...]) -> tuple[Pet, ...]:
        filters = self._filters
        if not filters.active:
            return pets
        static = self._static

        def matches(pet: Pet) -> bool:
            if filters.search:
                needle = filters.search
                if not (
                    needle in pet.name.lower()
                    or needle in str(pet.gid)
                    or needle in str(pet.conf_id)
                    or needle in str(pet.base_conf_id)
                ):
                    return False
            if pet.level < filters.level_min or pet.level > filters.level_max:
                return False
            if filters.natures and pet.nature not in filters.natures:
                return False
            if filters.talent_min and pet.talent_rank < filters.talent_min:
                return False
            if filters.first_catch_only and not pet.is_first_catch:
                return False
            if filters.gender and pet.gender != filters.gender:
                return False
            if filters.type_names:
                if static is None:
                    return True  # 无静态表时该维度不可用，视为通过
                species = static.species(pet.base_conf_id)
                if species is None or not (set(species.type_names) & filters.type_names):
                    return False
            return True

        return tuple(p for p in pets if matches(p))

    def _apply_sort(self, pets: tuple[Pet, ...]) -> tuple[Pet, ...]:
        key = self._sort_key

        def sort_value(pet: Pet):
            if key == "name":
                return pet.name
            if key == "stat_sum":
                return sum(a.final_value for a in pet.attributes)
            return getattr(pet, key, 0)

        reverse = self._sort_desc
        if key == "name":
            # 名字排序默认升序更直观；descending 时反向
            return tuple(sorted(pets, key=sort_value, reverse=reverse))
        return tuple(sorted(pets, key=sort_value, reverse=reverse))

    def _primary_type(self, pet: Pet) -> str:
        if self._static is None:
            return "未知"
        species = self._static.species(pet.base_conf_id)
        if species is None or not species.type_names:
            return "未知"
        return species.type_names[0]


__all__ = ["PetFilters", "PetStats", "PetViewModel", "SORT_KEYS"]
