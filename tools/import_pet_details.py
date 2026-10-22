"""补全静态数据：图鉴描述 / sum 修正 / 技能名补缺 / 奖牌表 / 蛋图标。

数据来源：游戏客户端配置整理的宠物目录与技能/奖牌名映射（事实性数据）。
对 data/static/ 就地补全：
  1. species.json  并入 description / display_name / has_ride_talent / form /
     breedable；**sum 字段全部按六维重算**（旧来源的 sum 与六维之和不符，实测
     601 条中 547 条错误，六维本身核对一致）
  2. skills.json   补齐缺失的技能名（只有名字，无描述，其余字段留空）
  3. medals.json   新表：体型/声音奖牌与勋章 id → 名称
  4. spritelens/web/static/egg-icons/   蛋图标（按 egg_item_id 命名）
  5. spritelens/web/static/medal-icons/ 奖牌图标（按 medal_id 命名）

用法: python tools/import_pet_details.py [蛋神解包目录]
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STATIC = REPO / "data" / "static"
WEB_STATIC = REPO / "spritelens" / "web" / "static"
DEFAULT_SRC = Path(
    r"C:\Users\chiqingsan\AppData\Local\Temp\ds\out"
    r"\蛋神助手电脑版-v1.1.6-b49823778e99.exe_extracted"
)

_STAT_KEYS = ("hp", "atk", "spa", "def", "spd", "spe")


def enrich_species(src: Path) -> str:
    pets = json.loads((src / "assets" / "catalog" / "petBaseData.json").read_text(encoding="utf-8"))
    by_id = {str(r["id"]): r for r in pets.get("records", []) if isinstance(r, dict) and r.get("id")}
    species = json.loads((STATIC / "species.json").read_text(encoding="utf-8"))
    added_desc = 0
    for key, entry in species.items():
        stats = entry.get("stats") or {}
        # sum 一律重算：来源数据的 sum 字段不可信
        stats["sum"] = sum(int(stats.get(k) or 0) for k in _STAT_KEYS)
        ref = by_id.get(key)
        if not ref:
            continue
        if ref.get("description"):
            entry["description"] = str(ref["description"])
            added_desc += 1
        if ref.get("displayName") and ref["displayName"] != ref.get("name"):
            entry["display_name"] = str(ref["displayName"])
        if ref.get("hasRideTalent") is not None:
            entry["has_ride_talent"] = bool(ref["hasRideTalent"])
        if ref.get("form") is not None:
            entry["form"] = ref["form"]
        if ref.get("breedable") is not None:
            entry["breedable"] = bool(ref["breedable"])
    (STATIC / "species.json").write_text(
        json.dumps(species, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    return f"species.json: {len(species)} 条（sum 重算 + {added_desc} 条图鉴描述）"


def fill_skills(src: Path) -> str:
    medal = json.loads(
        (src / "assets" / "catalog" / "desktopSkillMedalData.json").read_text(encoding="utf-8")
    )
    skills = json.loads((STATIC / "skills.json").read_text(encoding="utf-8"))
    before = len(skills)
    for skill_id, name in (medal.get("skills") or {}).items():
        if skill_id in skills:
            continue
        skills[skill_id] = {"name": str(name), "desc": "", "energy_cost": 0}
    (STATIC / "skills.json").write_text(
        json.dumps(skills, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    return f"skills.json: {before} → {len(skills)} 条（补 {len(skills) - before} 个名字）"


def import_medals(src: Path) -> str:
    medal = json.loads(
        (src / "assets" / "catalog" / "desktopSkillMedalData.json").read_text(encoding="utf-8")
    )
    medals = {str(k): str(v) for k, v in (medal.get("medals") or {}).items()}
    (STATIC / "medals.json").write_text(
        json.dumps(medals, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    icons = WEB_STATIC / "medal-icons"
    icons.mkdir(parents=True, exist_ok=True)
    copied = 0
    for png in (src / "assets" / "medals").glob("*.png"):
        shutil.copyfile(png, icons / png.name)
        copied += 1
    return f"medals.json: {len(medals)} 条 + {copied} 个图标"


def import_egg_icons(src: Path) -> str:
    icons = WEB_STATIC / "egg-icons"
    icons.mkdir(parents=True, exist_ok=True)
    copied = 0
    for png in (src / "assets" / "items" / "bag").glob("*.png"):
        shutil.copyfile(png, icons / png.name)
        copied += 1
    return f"egg-icons: {copied} 个蛋图标"


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SRC
    if not src.is_dir():
        print(f"源目录不存在: {src}")
        return 1
    for step in (enrich_species, fill_skills, import_medals, import_egg_icons):
        print(step(src))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
