"""导入蛋目录静态表到 data/static/eggs.json。

来源：游戏客户端配置整理的蛋目录（蛋组 / 孵化时长 / 公母比 / 身高体重区间 /
进化链），与 tools/import_static_data.py 同管线定位。源 JSON 结构（顶层键）：
  eggs: list[dict]      全部蛋条目（含形态变体）
  groupMap: dict        蛋组 id → 名称

用法:
    python tools/import_egg_data.py [源文件路径]
不带参数时尝试默认的蛋神解包产物路径（本机研究环境）。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_SOURCE = Path(
    r"C:\Users\chiqingsan\AppData\Local\Temp\ds\out"
    r"\蛋神助手电脑版-v1.1.6-b49823778e99.exe_extracted\assets\catalog\eggData.json"
)
TARGET_DIR = Path(__file__).resolve().parent.parent / "data" / "static"

# 保留的事实字段；URL 等第三方资源定位不导入（纯本地原则，图标后续走官方资源管线）
_EGG_FIELDS = (
    "eggKey", "nameKey", "eggConfId", "petEggPetId", "eggName", "name",
    "ownerBaseId", "baseId", "dexNo", "handbookNo", "eggItemId", "eggItemName",
    "eggTypeId", "eggTypeName", "hatchLabel", "hatchSeconds",
    "eggGroupIds", "eggGroupNames", "heightLow", "heightHigh",
    "weightLow", "weightHigh", "chainKey", "chainMembers",
)

_CAMEL_TO_SNAKE = {
    "eggKey": "egg_key", "nameKey": "name_key", "eggConfId": "egg_conf_id",
    "petEggPetId": "pet_egg_pet_id", "eggName": "egg_name", "name": "name",
    "ownerBaseId": "owner_base_id", "baseId": "base_id", "dexNo": "dex_no",
    "handbookNo": "handbook_no", "eggItemId": "egg_item_id",
    "eggItemName": "egg_item_name", "eggTypeId": "egg_type_id",
    "eggTypeName": "egg_type_name", "hatchLabel": "hatch_label",
    "hatchSeconds": "hatch_seconds", "eggGroupIds": "egg_group_ids",
    "eggGroupNames": "egg_group_names", "heightLow": "height_low",
    "heightHigh": "height_high", "weightLow": "weight_low",
    "weightHigh": "weight_high", "chainKey": "chain_key",
    "chainMembers": "chain_members",
}


def convert(source: Path) -> dict:
    raw = json.loads(source.read_text(encoding="utf-8"))
    eggs: list[dict] = []
    seen: set[str] = set()
    conf_index: dict[str, str] = {}
    base_index: dict[str, str] = {}
    for entry in raw.get("eggs", []):
        if not isinstance(entry, dict) or not entry.get("eggKey"):
            continue
        egg_key = str(entry["eggKey"])
        if entry.get("baseId"):
            base_index[str(entry["baseId"])] = egg_key
        if egg_key in seen:
            # 形态变体只保留首条主记录；confId 索引仍全部保留
            conf_index[str(entry.get("eggConfId"))] = egg_key
            continue
        seen.add(egg_key)
        item: dict = {}
        for field in _EGG_FIELDS:
            value = entry.get(field)
            if value is None:
                continue
            item[_CAMEL_TO_SNAKE[field]] = value
        ratio = entry.get("genderRatio")
        if isinstance(ratio, dict):
            item["gender_male"] = int(ratio.get("male_percent") or 0)
            item["gender_female"] = int(ratio.get("female_percent") or 0)
        eggs.append(item)
        conf_index[str(entry.get("eggConfId"))] = egg_key

    return {
        "groups": {str(k): v for k, v in (raw.get("groupMap") or {}).items()},
        "eggs": eggs,
        "egg_conf_index": conf_index,
        "egg_base_index": base_index,
    }


def main() -> int:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE
    if not source.is_file():
        print(f"源文件不存在: {source}")
        print("用法: python tools/import_egg_data.py <eggData.json 路径>")
        return 1
    payload = convert(source)
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    target = TARGET_DIR / "eggs.json"
    target.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    meta = {
        "source": source.name,
        "imported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "egg_entries": len(payload["eggs"]),
        "conf_index": len(payload["egg_conf_index"]),
        "groups": len(payload["groups"]),
    }
    (TARGET_DIR / "eggs_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"已写入 {target}: {meta['egg_entries']} 种蛋 / {meta['conf_index']} 条 confId 索引"
          f" / {meta['groups']} 个蛋组")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
