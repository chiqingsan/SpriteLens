"""静态映射数据：物种 / 性格 / 系别 / 技能的中文名与数值。

协议 wire 层只有数字 ID，本模块把「游戏静态表」接上来，供 UI 展示与筛选。
数据文件在 data/static/（由 tools/import_static_data.py 从解包数据转制）。

**关联键（实测确立，勿用错）**：
    协议的 pet.base_conf_id（字段 15） → species 表
实测 105/107 命中，名字与协议直带一致。反例：pet.conf_id（字段 2）是实例
级 ID，用它查物种表会得到错误物种（实测 conf_id=2000671 实为「波波拉」，
旧 pets.json 却索引到「水蓝蓝」）。

设计约束：本模块零 IO 副作用、可被 UI 与测试直接调用；加载失败整体降级
为空表（宁可少显示名字，也不能让界面崩）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from spritelens.logs import get_logger

logger = get_logger("static_data")

_TABLE_FILES = {
    "species": "species.json",
    "natures": "natures.json",
    "types": "types.json",
    "skills": "skills.json",
}


@dataclass(frozen=True)
class SpeciesInfo:
    """宠物物种静态属性（按 base_conf_id 索引）。

    前 8 项来自基础静态表；后 7 项为图鉴元数据（import_assets 合并，
    来自 petBaseData；缺失时为零值/空，展示层按需降级）。
    """

    name: str
    type_names: tuple[str, ...]
    types: tuple[int, ...]
    stats: dict[str, int]
    quality: int
    stage: int
    max_energy: int
    evolutions: tuple[int, ...]
    # -- 图鉴元数据（可选）------------------------------------------------
    dex_no: int = 0
    handbook_no: str = ""
    display_name: str = ""
    description: str = ""
    egg_groups: tuple[str, ...] = ()
    gender_ratio: tuple[int, int] = (0, 0)  # (雄%, 雌%)
    height_range: tuple[int, int] = (0, 0)
    weight_range: tuple[int, int] = (0, 0)
    has_shiny: bool = False
    chain_members: tuple[int, ...] = ()

    @property
    def stat_sum(self) -> int:
        return int(self.stats.get("sum", 0))


@dataclass(frozen=True)
class NatureInfo:
    """性格：名字与正/负修正项。"""

    name: str
    positive_stat: str | None
    negative_stat: str | None


@dataclass(frozen=True)
class TypeInfo:
    """系别：名字与主题色（来自游戏 type_chart）。"""

    name: str
    name_en: str
    color: str


@dataclass(frozen=True)
class SkillInfo:
    """技能：名字/描述/系别/能耗。"""

    name: str
    desc: str
    type_id: int | None
    energy_cost: int
    damage_type: int | None


def _load_table(directory: Path, filename: str) -> dict:
    path = directory / filename
    if not path.is_file():
        logger.warning("静态数据缺失: %s（相关名称将退回原始 ID）", path)
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("静态数据加载失败 %s: %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


class StaticData:
    """静态表只读索引；全量加载一次，进程内共享。"""

    def medal_name(self, medal_id: int) -> str:
        return str(self._medals.get(str(medal_id)) or f"奖牌 #{medal_id}")

    def speciality_name(self, speciality_id: int) -> str:
        return str(self._specialities.get(str(speciality_id)) or f"特性 #{speciality_id}")

    def __init__(self, directory: Path | None) -> None:
        self.directory = directory
        self._medals = _load_table(directory, "medals.json") if directory and (directory / "medals.json").is_file() else {}
        self._specialities = _load_table(directory, "specialities.json") if directory and (directory / "specialities.json").is_file() else {}
        self._species: dict[str, SpeciesInfo] = {}
        self._natures: dict[int, NatureInfo] = {}
        self._types: dict[int, TypeInfo] = {}
        self._skills: dict[int, SkillInfo] = {}
        self._species_misses = 0
        self._species_hits = 0
        self._name_color_cache: dict[str, str] | None = None
        if directory is None:
            return
        self._load()

    # -- 加载 ----------------------------------------------------------
    def _load(self) -> None:
        assert self.directory is not None
        for key, entry in _load_table(self.directory, _TABLE_FILES["species"]).items():
            if not isinstance(entry, dict) or not entry.get("name"):
                continue
            stats_raw = entry.get("stats") or {}
            stats = {
                "hp": int(stats_raw.get("hp", 0) or 0),
                "atk": int(stats_raw.get("atk", 0) or 0),
                "spa": int(stats_raw.get("spa", 0) or 0),
                "def": int(stats_raw.get("def", 0) or 0),
                "spd": int(stats_raw.get("spd", 0) or 0),
                "spe": int(stats_raw.get("spe", 0) or 0),
                "sum": int(stats_raw.get("sum", 0) or 0),
            }
            ratio = entry.get("gender_ratio") or {}
            height_range = entry.get("height_range") or []
            weight_range = entry.get("weight_range") or []
            self._species[str(key)] = SpeciesInfo(
                name=str(entry["name"]),
                type_names=tuple(str(t) for t in (entry.get("type_names") or [])),
                types=tuple(int(t) for t in (entry.get("types") or []) if isinstance(t, int)),
                stats=stats,
                quality=int(entry.get("quality") or 0),
                stage=int(entry.get("stage") or 0),
                max_energy=int(entry.get("max_energy") or 0),
                evolutions=tuple(
                    int(e) for e in (entry.get("evolutions") or []) if isinstance(e, int)
                ),
                dex_no=int(entry.get("dex_no") or 0),
                handbook_no=str(entry.get("handbook_no") or ""),
                display_name=str(entry.get("display_name") or ""),
                description=str(entry.get("description") or ""),
                egg_groups=tuple(str(g) for g in (entry.get("egg_groups") or [])),
                gender_ratio=(
                    int(ratio.get("male") or 0),
                    int(ratio.get("female") or 0),
                ),
                height_range=(
                    int(height_range[0] or 0) if len(height_range) > 0 else 0,
                    int(height_range[1] or 0) if len(height_range) > 1 else 0,
                ),
                weight_range=(
                    int(weight_range[0] or 0) if len(weight_range) > 0 else 0,
                    int(weight_range[1] or 0) if len(weight_range) > 1 else 0,
                ),
                has_shiny=bool(entry.get("has_shiny")),
                chain_members=tuple(int(e) for e in (entry.get("chain_members") or []) if isinstance(e, int)),
            )

        for key, entry in _load_table(self.directory, _TABLE_FILES["natures"]).items():
            if not isinstance(entry, dict) or not entry.get("name"):
                continue
            try:
                nature_id = int(key)
            except (TypeError, ValueError):
                continue
            self._natures[nature_id] = NatureInfo(
                name=str(entry["name"]),
                positive_stat=entry.get("positive_stat"),
                negative_stat=entry.get("negative_stat"),
            )

        for key, entry in _load_table(self.directory, _TABLE_FILES["types"]).items():
            if not isinstance(entry, dict) or not entry.get("name"):
                continue
            try:
                type_id = int(key)
            except (TypeError, ValueError):
                continue
            self._types[type_id] = TypeInfo(
                name=str(entry["name"]),
                name_en=str(entry.get("name_en", "")),
                color=str(entry.get("color", "")),
            )

        for key, entry in _load_table(self.directory, _TABLE_FILES["skills"]).items():
            if not isinstance(entry, dict) or not entry.get("name"):
                continue
            try:
                skill_id = int(key)
            except (TypeError, ValueError):
                continue
            type_id = entry.get("type_id")
            damage_type = entry.get("damage_type")
            self._skills[skill_id] = SkillInfo(
                name=str(entry["name"]),
                desc=str(entry.get("desc", "")),
                type_id=int(type_id) if isinstance(type_id, int) else None,
                energy_cost=int(entry.get("energy_cost") or 0),
                damage_type=int(damage_type) if isinstance(damage_type, int) else None,
            )

    # -- 查询 ----------------------------------------------------------
    def species(self, base_conf_id: int) -> SpeciesInfo | None:
        """按协议 pet.base_conf_id 取物种信息；命中率可经 stats() 观测。"""
        info = self._species.get(str(base_conf_id))
        if info is None:
            self._species_misses += 1
        else:
            self._species_hits += 1
        return info

    def species_items(self) -> tuple[tuple[str, SpeciesInfo], ...]:
        """全部物种（key 为 base_conf_id 字符串），按数值 ID 升序（图鉴用）。"""

        def sort_key(item: tuple[str, SpeciesInfo]):
            try:
                return (0, int(item[0]), "")
            except ValueError:
                return (1, 0, item[0])

        return tuple(sorted(self._species.items(), key=sort_key))

    def nature(self, nature_id: int) -> NatureInfo | None:
        return self._natures.get(nature_id)

    def nature_items(self) -> tuple[tuple[int, NatureInfo], ...]:
        """完整已加载性格目录，不受当前背包出现频次限制。"""
        return tuple(sorted(self._natures.items()))

    def type_items(self) -> tuple[tuple[int, TypeInfo], ...]:
        return tuple(sorted(self._types.items()))

    def medal_items(self) -> tuple[tuple[int, str], ...]:
        return tuple(sorted((int(key), name) for key, name in self._medals.items()
                            if key.isdecimal() and isinstance(name, str)))

    def speciality_items(self) -> tuple[tuple[int, str], ...]:
        return tuple(sorted((int(key), name) for key, name in self._specialities.items()
                            if key.isdecimal() and isinstance(name, str)))

    def nature_name(self, nature_id: int, fallback: str = "") -> str:
        info = self._natures.get(nature_id)
        return info.name if info else (fallback or str(nature_id))

    def type_info(self, type_id: int) -> TypeInfo | None:
        return self._types.get(type_id)

    def type_color(self, type_id: int) -> str:
        info = self._types.get(type_id)
        return info.color if info else ""

    def type_color_by_name(self, name: str) -> str:
        """按系别名取主题色（统计聚合后只有名字，没有 id）。"""
        return self._type_colors_by_name.get(name, "")

    @property
    def _type_colors_by_name(self) -> dict[str, str]:
        if self._name_color_cache is None:
            self._name_color_cache = {
                info.name: info.color for info in self._types.values() if info.color
            }
        return self._name_color_cache

    def skill(self, skill_id: int) -> SkillInfo | None:
        return self._skills.get(skill_id)

    def skill_name(self, skill_id: int) -> str:
        info = self._skills.get(skill_id)
        return info.name if info else str(skill_id)

    # -- 观测 ----------------------------------------------------------
    def stats(self) -> dict[str, int]:
        """命中/未命中计数（用于诊断静态数据版本漂移）。"""
        return {
            "species_total": len(self._species),
            "species_hits": self._species_hits,
            "species_misses": self._species_misses,
            "natures": len(self._natures),
            "types": len(self._types),
            "skills": len(self._skills),
        }

    @property
    def available(self) -> bool:
        return bool(self._species or self._skills)


_default: StaticData | None = None


def _default_directory() -> Path | None:
    from spritelens.paths import static_dir

    path = static_dir()
    return path if path.is_dir() else None


def load_static_data(directory: Path | None = None) -> StaticData:
    """加载静态数据（进程级缓存）；目录缺省用 data/static/。"""
    global _default
    if directory is None and _default is not None:
        return _default
    target = directory if directory is not None else _default_directory()
    data = StaticData(target)
    if directory is None:
        _default = data
    return data


def get_static_data() -> StaticData:
    """未显式加载时按需加载默认目录（保证任何调用路径都有兜底对象）。"""
    return load_static_data()


__all__ = [
    "NatureInfo",
    "SkillInfo",
    "SpeciesInfo",
    "StaticData",
    "TypeInfo",
    "get_static_data",
    "load_static_data",
]
