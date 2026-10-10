"""导入静态映射数据（宠物物种/性格/技能/系别）到 data/static/。

为什么需要：协议 wire 层只有数字 ID，系别名/性格名/技能名/种族值这类
「游戏静态表」不在流量里。UI 要做 roco_helper 式的高密度宠物表与筛选器，
必须先有这层映射。

**关键映射关系（实测确立）**：
    协议宠物对象.pet.base_conf_id（字段 15） → pet_species.json 的 key
    实测 105/107 命中（98.1%），且名字与协议直带完全一致。
    反例：按 conf_id（字段 2）查 pet_map.json 只有 29/107 命中，且名字
    会错（conf_id=2000671 实为「波波拉」，pet_map 却索引到「水蓝蓝」）——
    conf_id 是实例级 ID，不是物种 ID。

数据来源：innovationb1ue/rocom-helper 的 data/game/（自游戏 pak 解包所得，
格式为 rkpp-data-bundle-v1）。本脚本只做**字段裁剪与结构规整**。

用法：
    python tools/import_static_data.py [SRC_DIR]

产出（data/static/）：
    species.json    base_conf_id → {name, types, type_names, stats, quality, stage, evolutions}
    natures.json    nature_id → {name, positive_stat, negative_stat}
    types.json      type_id → {name, name_en, color}
    skills.json     skill_id → {name, desc, type, energy_cost, damage_type}
    _meta.json      来源 / 生成时间 / 各表条目数
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_ROOT / "data" / "static"

DEFAULT_SRC_CANDIDATES = (
    Path(tempfile.gettempdir()) / "roco_research" / "rocom-helper-innovationb1ue" / "data" / "game",
    Path(tempfile.gettempdir()) / "rocom-helper-reference" / "data" / "game",
)

# 六维字段顺序（与 domain/pets.py 的 _STAT_KEY_NAMES 对应）
_STAT_KEYS = ("hp", "atk", "spa", "def", "spd", "spe")


def _find_src(argv: list[str]) -> Path:
    if len(argv) > 1:
        src = Path(argv[1])
        if not src.is_dir():
            raise SystemExit(f"目录不存在: {src}")
        return src
    for candidate in DEFAULT_SRC_CANDIDATES:
        if candidate.is_dir():
            return candidate
    raise SystemExit(
        "找不到静态数据源目录。请传入路径，例如："
        "\n  python tools/import_static_data.py /path/to/rocom-helper/data/game"
    )


def _load(src: Path, name: str) -> dict:
    path = src / name
    if not path.is_file():
        print(f"[import-static] 缺少 {name}，跳过")
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _build_species(pet_species: dict) -> dict:
    """物种表：key 为 base_conf_id（协议字段 15）。"""
    out: dict[str, dict] = {}
    for key, entry in pet_species.items():
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not name:
            continue
        stats_raw = entry.get("stats") or {}
        stats = {k: int(stats_raw.get(k, 0) or 0) for k in _STAT_KEYS}
        stats["sum"] = int(stats_raw.get("sum", sum(stats.values())) or 0)
        out[str(key)] = {
            "name": str(name),
            "types": [int(t) for t in (entry.get("types") or []) if isinstance(t, int)],
            "type_names": [str(t) for t in (entry.get("type_names") or [])],
            "stats": stats,
            "quality": entry.get("quality"),
            "stage": entry.get("stage"),
            "max_energy": entry.get("max_energy"),
            "evolutions": [int(e) for e in (entry.get("evolution_pet_ids") or []) if isinstance(e, int)],
        }
    return out


def _build_natures(nature_map: dict) -> dict:
    out: dict[str, dict] = {}
    for key, entry in nature_map.items():
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not name:
            continue
        out[str(key)] = {
            "name": str(name),
            "positive_stat": entry.get("positive_stat"),
            "negative_stat": entry.get("negative_stat"),
        }
    return out


def _build_types(type_chart: dict) -> dict:
    out: dict[str, dict] = {}
    for entry in type_chart.get("types", []):
        if not isinstance(entry, dict):
            continue
        out[str(entry.get("id"))] = {
            "name": str(entry.get("name", "")),
            "name_en": str(entry.get("name_en", "")),
            "color": str(entry.get("color", "")),
        }
    return out


def _build_skills(skill_map: dict) -> dict:
    out: dict[str, dict] = {}
    for key, entry in skill_map.items():
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not name:
            continue
        energy = entry.get("energy_cost") or []
        out[str(key)] = {
            "name": str(name),
            "desc": str(entry.get("desc", "")),
            # skill_type_id 为系别（可空）；type 为技能分类编号
            "type_id": entry.get("skill_type_id"),
            "type": entry.get("type"),
            "damage_type": entry.get("damage_type"),
            "energy_cost": int(energy[0]) if energy and isinstance(energy[0], int) else 0,
        }
    return out


def main(argv: list[str]) -> int:
    src = _find_src(argv)
    print(f"[import-static] 数据源: {src}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    species = _build_species(_load(src, "pet_species.json"))
    natures = _build_natures(_load(src, "nature_map.json"))
    types = _build_types(_load(src, "type_chart.json"))
    skills = _build_skills(_load(src, "skill_map.json"))

    tables = {
        "species.json": species,
        "natures.json": natures,
        "types.json": types,
        "skills.json": skills,
    }
    # 旧的 pets.json（含错误的 conf_id→物种 索引）已废弃，清理避免误用
    stale = OUT_DIR / "pets.json"
    if stale.is_file():
        stale.unlink()
        print("[import-static] 已移除废弃的 pets.json（改用 species.json）")

    for filename, table in tables.items():
        path = OUT_DIR / filename
        path.write_text(
            json.dumps(table, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        print(f"[import-static] {filename}: {len(table)} 条 ({path.stat().st_size} B)")

    meta = {
        "source": "innovationb1ue/rocom-helper data/game (rkpp-data-bundle-v1)",
        "source_dir": str(src),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "counts": {name: len(table) for name, table in tables.items()},
        "mapping": "协议 pet.base_conf_id(字段15) → species.json key（实测 105/107 命中）",
        "notes": [
            "species name 仅作兜底：协议直带的宠物名优先（实测二者一致）",
            "不要用 pet.conf_id(字段2) 查物种表：它是实例 ID，会得到错误物种",
            "types/natures/技能名为版本稳定字段，可直接展示",
        ],
    }
    (OUT_DIR / "_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[import-static] 完成 → {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
