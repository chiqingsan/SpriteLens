"""宠物仓库 ViewModel：快照读取、多维筛选、排序与聚合统计。

纯 Python（零 UI 框架依赖），本地服务与前端只消费它的输出。
筛选维度对 roco_helper 的筛选器：搜索（名字/gid/conf_id）、等级范围、
性格多选、系别多选、天赋阶下限。系别筛选依赖静态物种表
（可选注入；缺省时该维度被忽略，不抛错）。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import time

from spritelens.domain.pets import Pet
from spritelens.domain.identity import PlayerIdentity
from spritelens.domain.static_data import StaticData
from spritelens.domain.measurements import range_position
from spritelens.domain.pet_conditions import MAX_PET_LEVEL, matches_conditions
from spritelens.services.pet_repository import PetRepository

# 排序键（UI 排序菜单用）
SORT_KEYS: tuple[tuple[str, str], ...] = (
    ("dex_no", "图鉴 ID"),
    ("add_time", "捕捉时间"),
    ("level", "等级"),
    ("height", "身高"),
    ("weight", "体重"),
    ("voice", "声音"),
)


@dataclass(frozen=True)
class PetFilters:
    """筛选条件；空集合语义为「不限」。"""

    search: str = ""
    level_min: int = 1
    level_max: int = MAX_PET_LEVEL
    natures: frozenset[int] = frozenset()
    type_names: frozenset[str] = frozenset()
    talent_min: int = 0
    gender: int = 0
    egg_groups: frozenset[str] = frozenset()
    egg_mode: str = "any"
    pool: frozenset[str] = frozenset()
    pool_mode: str = "and"
    shiny: bool = False
    colorful: bool = False
    medal: int = 0
    medals: frozenset[int] = frozenset()
    marks: frozenset[str] = frozenset()
    speciality: int = 0
    acquisition: int = 0
    captured_days: int = 0
    height_min: float | None = None
    height_max: float | None = None
    weight_min: float | None = None
    weight_max: float | None = None
    voice_min: float | None = None
    voice_max: float | None = None
    height_position_min: float | None = None
    height_position_max: float | None = None
    weight_position_min: float | None = None
    weight_position_max: float | None = None

    @property
    def active(self) -> bool:
        return bool(
            self.search
            or self.natures
            or self.type_names
            or self.talent_min > 0
            or self.gender
            or self.egg_groups
            or self.pool or self.shiny or self.colorful or self.medal or self.medals or self.marks or self.speciality or self.acquisition or self.captured_days
            or any(getattr(self, key) is not None for key in (
                "height_min", "height_max", "weight_min", "weight_max", "voice_min", "voice_max",
                "height_position_min", "height_position_max", "weight_position_min", "weight_position_max"))
            or self.level_min > 1
            or self.level_max < MAX_PET_LEVEL
        )


@dataclass(frozen=True)
class PetStats:
    """仓库聚合统计（页内统计条与 WS 状态共用）。"""

    total: int = 0
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
        self._sort_key = "dex_no"
        self._sort_desc = False

    # -- 命令 ----------------------------------------------------------
    def set_search(self, text: str) -> None:
        self._search = text.strip().lower()
        self._filters = replace(self._filters, search=self._search)

    def set_level_range(self, minimum: int, maximum: int) -> None:
        self._filters = replace(
            self._filters,
            level_min=max(1, min(MAX_PET_LEVEL, minimum, maximum)),
            level_max=min(MAX_PET_LEVEL, max(1, minimum, maximum)),
        )

    def set_natures(self, natures: frozenset[int]) -> None:
        self._filters = replace(self._filters, natures=natures)

    def set_types(self, type_names: frozenset[str]) -> None:
        self._filters = replace(self._filters, type_names=type_names)

    def set_talent_min(self, rank: int) -> None:
        self._filters = replace(self._filters, talent_min=max(0, int(rank)))

    def set_gender(self, gender: int) -> None:
        self._filters = replace(self._filters, gender=gender if gender in (1, 2) else 0)

    def set_egg_groups(self, groups: frozenset[str], mode: str = "any") -> None:
        self._filters = replace(self._filters, egg_groups=groups, egg_mode="all" if mode == "all" else "any")

    def set_measurement_ranges(self, **values: object) -> None:
        normalized = self.measurement_query(**values)
        self._filters = replace(self._filters, **normalized)

    @staticmethod
    def measurement_query(**values: object) -> dict[str, float | None]:
        """测量值筛选参数归一化（纯函数，不写状态）：无效值降级 None。"""
        import math

        normalized: dict[str, float | None] = {}
        for field in ("height", "weight", "voice", "height_position", "weight_position"):
            pair = []
            for bound in ("min", "max"):
                try:
                    value = float(values.get(f"{field}_{bound}"))
                    if not math.isfinite(value) or (field != "voice" and value < 0) or (field.endswith("_position") and value > 100):
                        value = None
                except (ValueError, TypeError):
                    value = None
                pair.append(value)
            if all(v is not None for v in pair) and pair[0] > pair[1]:
                pair.reverse()
            normalized.update({f"{field}_min": pair[0], f"{field}_max": pair[1]})
        return normalized

    def set_sort(self, key: str, *, descending: bool = False) -> None:
        if key not in {k for k, _ in SORT_KEYS}:
            key = "dex_no"
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

    def view_with(
        self,
        filters: PetFilters,
        sort_key: str = "dex_no",
        *,
        descending: bool = False,
    ) -> "PetView":
        """按给定筛选与排序生成一次性视图（R08：GET 不写共享状态）。

        请求级查询用它构造不可变条件；共享 VM 的 _filters/_sort_key 只由
        页面命令（set_search 等）修改，HTTP 请求与 bootstrap、多客户端
        互不污染。
        """
        if sort_key not in {k for k, _ in SORT_KEYS}:
            sort_key = "dex_no"
        return PetView(self, filters, sort_key, descending)

    def filtered_pets(self) -> tuple[Pet, ...]:
        """按当前筛选与排序返回宠物（UI 表格数据源）。"""
        pets = self._apply_filters(self._repository.snapshot())
        return self._apply_sort(pets)

    def all_pets(self) -> tuple[Pet, ...]:
        """全部宠物（不筛选；统计与范围选项使用）。"""
        return self._repository.snapshot()

    def filtered_count(self) -> int:
        return len(self.filtered_pets())

    def total_count(self) -> int:
        return len(self._repository.snapshot())

    def version(self) -> int:
        return self._repository.version

    def stats(self, pets: tuple[Pet, ...] | None = None) -> PetStats:
        """聚合统计：总量/满级/最高等级/系别分布（按主系别）。"""
        if pets is None:
            pets = self._repository.snapshot()
        if not pets:
            return PetStats()
        counts: dict[str, int] = {}
        for pet in pets:
            counts[self._primary_type(pet)] = counts.get(self._primary_type(pet), 0) + 1
        ranked = tuple(sorted(counts.items(), key=lambda kv: kv[1], reverse=True))
        return PetStats(
            total=len(pets),
            maxed=sum(1 for p in pets if p.level >= 60),
            max_level=max(p.level for p in pets),
            type_counts=ranked,
        )

    def nature_options(self, pets: tuple[Pet, ...] | None = None) -> tuple[tuple[int, str], ...]:
        """完整性格目录与观测到的未知ID，常用项按当前背包频次排在前面。"""
        seen: dict[int, str] = {key: info.name for key, info in self._static.nature_items()} if self._static else {}
        counts: dict[int, int] = {}
        for pet in self._repository.snapshot() if pets is None else pets:
            counts[pet.nature] = counts.get(pet.nature, 0) + 1
            if pet.nature in seen:
                continue
            name = str(pet.nature)
            if self._static is not None:
                info = self._static.nature(pet.nature)
                if info is not None:
                    name = info.name
            seen[pet.nature] = name
        return tuple(sorted(seen.items(), key=lambda kv: (-counts.get(kv[0], 0), kv[0])))

    def type_options(self, pets: tuple[Pet, ...] | None = None) -> tuple[str, ...]:
        """完整系别目录，并保留物种元数据里的已知系别名。"""
        if self._static is None:
            return ()
        names: set[str] = {info.name for _, info in self._static.type_items()}
        names.update(name for _, species in self._static.species_items() for name in species.type_names)
        for pet in self._repository.snapshot() if pets is None else pets:
            species = self._static.species(pet.base_conf_id)
            if species is not None:
                names.update(species.type_names)
        return tuple(sorted(name for name in names if name))

    def species_of(self, pet: Pet):
        """宠物的静态物种信息（UI 展示系别/种族值用）；无静态表返回 None。"""
        if self._static is None:
            return None
        return self._static.species(pet.base_conf_id)

    def location_of(self, pet: Pet):
        location = self._repository.location(pet.gid)
        if location:
            return location.payload()
        for team in self._repository.backpack().teams:
            if pet.gid in team.slots:
                return {"team_id": team.box_id, "slot": team.slots.index(pet.gid) + 1, "historical": team.historical}
        return None

    def backpack(self):
        return self._repository.backpack()

    def talent_rank_max(self, pets: tuple[Pet, ...] | None = None) -> int:
        if pets is None:
            pets = self._repository.snapshot()
        return max((p.talent_rank for p in pets), default=0)

    def measurement_limits(self, pets: tuple[Pet, ...] | None = None) -> dict[str, dict[str, float]]:
        """用完整库存快照定量程，筛选结果变化不能缩短滑动条范围。"""
        if pets is None:
            pets = self._repository.snapshot()
        limits = {"height": {"min": 0.0, "max": 1.0}, "weight": {"min": 0.0, "max": 1.0},
                  "voice": {"min": -100.0, "max": 100.0}}
        for pet in pets:
            species = self.species_of(pet)
            for field, scale in (("height", 100), ("weight", 1000)):
                reference = getattr(species, field + "_range", (0, 0))[1]
                limits[field]["max"] = max(limits[field]["max"], getattr(pet, field) / scale, reference / scale)
            limits["voice"]["min"] = min(limits["voice"]["min"], pet.voice)
            limits["voice"]["max"] = max(limits["voice"]["max"], pet.voice)
        return limits

    # -- 持久化 --------------------------------------------------------
    def load_persisted(self, uid: int) -> int:
        """载入历史宠物（重启后"数据还在"的入口）；返回补入条数。"""
        return self._repository.load_persisted(uid)

    @property
    def identity(self):
        """当前角色身份（uid/名字/等级）；未识别到返回 None。"""
        return self._repository.identity

    def load_last_account(self) -> int:
        """启动即载入最近账号的历史宠物（离线也能看到上次的数据）。"""
        return self._repository.load_last_account()

    # -- 内部 ----------------------------------------------------------
    def _apply_filters_with(self, pets: tuple[Pet, ...], filters: PetFilters) -> tuple[Pet, ...]:
        if not filters.active:
            return pets
        static = self._static
        captured_since = time.time() - filters.captured_days * 86400
        def matches(pet: Pet) -> bool:
            species = static.species(pet.base_conf_id) if static else None
            if filters.search:
                needle = filters.search
                texts = [pet.name, str(pet.gid), str(pet.conf_id), str(pet.base_conf_id)]
                if static:
                    texts.append(static.nature_name(pet.nature))
                if species:
                    texts.extend((species.name, species.display_name, species.handbook_no, *species.egg_groups))
                    if species.dex_no:
                        texts.append(str(species.dex_no))
                if not any(needle in text.lower() for text in texts):
                    return False  # 搜索在条件池之外，始终约束整个结果集合。
            checks: list[bool] = []
            if filters.level_min > 1 or filters.level_max < MAX_PET_LEVEL:
                checks.append(filters.level_min <= pet.level <= filters.level_max)
            checks.extend(pet.nature == nature for nature in filters.natures)
            if filters.talent_min:
                checks.append(pet.talent_rank >= filters.talent_min)
            if filters.gender:
                checks.append(pet.gender == filters.gender)
            for field, scale in (("height", 100), ("weight", 1000), ("voice", 1)):
                low, high = getattr(filters, field + "_min"), getattr(filters, field + "_max")
                if low is not None or high is not None:
                    value = getattr(pet, field) / scale
                    checks.append(getattr(pet, field) != 0 and (low is None or value >= low) and (high is None or value <= high))
            groups = set(species.egg_groups) if species else set()
            checks.extend(group in groups for group in filters.egg_groups)
            for field in ("height", "weight"):
                low, high = getattr(filters, field + "_position_min"), getattr(filters, field + "_position_max")
                if low is not None or high is not None:
                    ratio = range_position(getattr(pet, field), getattr(species, field + "_range", (0, 0)))["ratio"]
                    checks.append(ratio is not None and 0 <= ratio <= 1 and (low is None or ratio * 100 >= low) and (high is None or ratio * 100 <= high))
            if static is not None:
                types = set(species.type_names) if species else set()
                checks.extend(name in types for name in filters.type_names)
            if filters.acquisition:
                checks.append(pet.catch_way == filters.acquisition)
            if filters.captured_days:
                checks.append(pet.add_time > 0 and pet.add_time >= captured_since)
            return matches_conditions(pet, static, pool=filters.pool, pool_mode=filters.pool_mode,
                                      shiny=filters.shiny, colorful=filters.colorful, medal=filters.medal,
                                      marks=filters.marks, medals=filters.medals, speciality=filters.speciality, additional=checks)

        return tuple(p for p in pets if matches(p))

    def _apply_filters(self, pets: tuple[Pet, ...]) -> tuple[Pet, ...]:
        return self._apply_filters_with(pets, self._filters)

    def egg_group_options(self, pets: tuple[Pet, ...] | None = None) -> tuple[str, ...]:
        groups = {group for _, species in self._static.species_items() for group in species.egg_groups} if self._static else set()
        for pet in self._repository.snapshot() if pets is None else pets:
            species = self._static.species(pet.base_conf_id) if self._static else None
            if species:
                groups.update(species.egg_groups)
        return tuple(sorted(groups - {"未知", "未知组", "未发现", "未发现组", "暂无数据", ""}))

    def _apply_sort(self, pets: tuple[Pet, ...]) -> tuple[Pet, ...]:
        return self._apply_sort_with(pets, self._sort_key, self._sort_desc)

    def _apply_sort_with(self, pets: tuple[Pet, ...], key: str, reverse: bool) -> tuple[Pet, ...]:
        def sort_value(pet: Pet):
            if key == "dex_no":
                species = self._static.species(pet.base_conf_id) if self._static else None
                return species.dex_no if species is not None else 0
            return getattr(pet, key, 0)

        def tie_value(pet: Pet):
            species = self._static.species(pet.base_conf_id) if self._static else None
            return (species.dex_no if species is not None else 0, pet.add_time)

        # 主键可能降序，但并列时固定按（图鉴 ID, 捕捉时间）升序：先升序排次级，
        # 再用稳定排序按主键排，相等项保留次级顺序。
        ranked = sorted(pets, key=tie_value)
        return tuple(sorted(ranked, key=sort_value, reverse=reverse))

    def _primary_type(self, pet: Pet) -> str:
        if self._static is None:
            return "未知"
        species = self._static.species(pet.base_conf_id)
        if species is None or not species.type_names:
            return "未知"
        return species.type_names[0]


class PetView:
    """请求级一次性视图（R08 + 阶段1.5）：筛选条件显式传入 + 一致性快照。

    构造时经 repository.consistent_snapshot() 单次锁内取齐
    pets/backpack/locations/version/uid，筛选排序在锁外对该快照执行——
    整个响应对应仓库的同一版本，不出现「旧条目 + 新位置」的组合。
    与 PetViewModel 的读取接口同形，pets_payload 等载荷函数无差别消费。
    """

    def __init__(self, vm: PetViewModel, filters: PetFilters, sort_key: str, descending: bool) -> None:
        self._vm = vm
        self._filters = filters
        self._sort_key = sort_key
        self._sort_desc = descending
        self._snapshot = vm._repository.consistent_snapshot()

    @property
    def uid(self) -> int:
        return self._snapshot.uid

    @property
    def identity(self) -> PlayerIdentity | None:
        return self._snapshot.identity

    @property
    def cached_identity(self) -> PlayerIdentity | None:
        return self._snapshot.cached_identity

    def stats(self) -> PetStats:
        return self._vm.stats(self._snapshot.pets)

    @property
    def filters(self) -> PetFilters:
        return self._filters

    @property
    def sort_state(self) -> tuple[str, bool]:
        return self._sort_key, self._sort_desc

    def filtered_pets(self) -> tuple[Pet, ...]:
        pets = self._vm._apply_filters_with(self._snapshot.pets, self._filters)
        return self._vm._apply_sort_with(pets, self._sort_key, self._sort_desc)

    def all_pets(self) -> tuple[Pet, ...]:
        return self._snapshot.pets

    def filtered_count(self) -> int:
        return len(self.filtered_pets())

    def total_count(self) -> int:
        return len(self._snapshot.pets)

    def version(self) -> int:
        return self._snapshot.version

    def location_of(self, pet: Pet):
        location = self._snapshot.locations.get(pet.gid)
        if location:
            return location.payload()
        for team in self._snapshot.backpack.teams:
            if pet.gid in team.slots:
                return {"team_id": team.box_id, "slot": team.slots.index(pet.gid) + 1, "historical": team.historical}
        return None

    def backpack(self):
        return self._snapshot.backpack

    def nature_options(self) -> tuple[tuple[int, str], ...]:
        return self._vm.nature_options(self._snapshot.pets)

    def type_options(self) -> tuple[str, ...]:
        return self._vm.type_options(self._snapshot.pets)

    def egg_group_options(self) -> tuple[str, ...]:
        return self._vm.egg_group_options(self._snapshot.pets)

    def talent_rank_max(self) -> int:
        return self._vm.talent_rank_max(self._snapshot.pets)

    def measurement_limits(self) -> dict[str, dict[str, float]]:
        return self._vm.measurement_limits(self._snapshot.pets)


__all__ = ["PetFilters", "PetStats", "PetViewModel", "PetView", "SORT_KEYS"]
