"""从游戏配置补齐蛋仓联查；先输出到暂存目录，确认差异后再发布。"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path


def is_colorful_item(item_id: str, item: dict) -> bool:
    """活动珍贵蛋的炫彩只能按道具事实判定。

    蛋仓分页（0x1344）不下发 mutation/precious 字段，1.5 活动的「大量出没 / 重逢契约」
    珍贵精灵蛋（151xxx 道具）与官方命名带「炫彩」的道具孵化必得炫彩外观；wiki 派生数据
    当时只映射了异色，这里补一层显式规则，避免重导后退回「特殊蛋」。
    """
    return (item_id.isdigit() and 151_000 <= int(item_id) < 152_000) or "炫彩" in str(item.get("name") or "")


def build(game: Path, pets_file: Path, catalog_file: Path, icons: Path, reference: Path, output: Path,
          wiki_items: Path | None = None, wiki_icons: Path | None = None) -> None:
    sources = [game / f"{name}.json" for name in ("PET_EGG_CONF", "BAG_ITEM_CONF", "PET_RANDOM_EGG_CONF")]
    configs, items, random = [json.loads(p.read_text(encoding="utf-8"))["RocoDataRows"] for p in sources]
    pets = json.loads(pets_file.read_text(encoding="utf-8"))
    catalog = json.loads(catalog_file.read_text(encoding="utf-8"))
    image_by_texture = {}
    for egg in catalog["eggs"]:
        item_id = str(egg["egg_item_id"])
        item = items.get(item_id, {})
        if item.get("icon") and (icons / f"{item_id}.png").is_file():
            image_by_texture.setdefault(item["icon"], int(item_id))
    result = {"configs": {}, "items": {}, "random": {}}
    for key, row in configs.items():
        pet = pets.get(str(row.get("pet_id")), {})
        result["configs"][key] = {
            "name": pet.get("species_name") or row.get("name", ""),
            "base_id": pet.get("base_id", 0),
            "precious_type": row.get("precious_egg_type", 0),
            "hatch_seconds": row.get("hatch_data", 0),
            **{field: row.get(field, 0) for field in ("height_low", "height_high", "weight_low", "weight_high")},
        }
    copied = []
    target_icons = output / "egg-icons"
    target_icons.mkdir(parents=True, exist_ok=True)
    for key, row in items.items():
        if row.get("type") != 8:
            continue
        behavior = next((b for b in row.get("item_behavior", []) if b.get("use_action") == 17), {})
        image_id = int(key) if (icons / f"{key}.png").is_file() else image_by_texture.get(row.get("icon"), 0)
        for folder in (reference / "items/special-eggs", reference / "items/bag", reference / "official-resources/mirrors/item"):
            image = folder / f"{key}.png"
            if image.is_file() and not (icons / f"{key}.png").is_file():
                shutil.copyfile(image, target_icons / image.name)
                image_id = int(key)
                copied.append({"item_id": int(key), "source_kind": "reference-cache", "source_path": image.relative_to(reference).as_posix(), "sha256": hashlib.sha256(image.read_bytes()).hexdigest()})
                break
        result["items"][key] = {
            "name": row.get("name", ""), "icon_item_id": image_id,
            "egg_conf_id": next(iter(behavior.get("ratio", [])), 0),
            "random_conf_id": next(iter(behavior.get("ratio2", [])), 0),
        }
    for key, row in random.items():
        result["random"][key] = {"precious_type": row.get("precious_egg_type", 0), "mutation_type": row.get("mutation_type", 0)}
    names_file = reference.parent / "webui/trade-market-mini.js"
    if names_file.is_file():
        text = names_file.read_text(encoding="utf-8")
        block = re.search(r"const RANDOM_EGG_NAMES = \{([^}]+)\}", text)
        if block:
            for key, name in re.findall(r"(\d+):\s*'([^']+)'", block[1]):
                result["items"].setdefault(key, {"name": name, "icon_item_id": 0})
    if wiki_items:
        wiki = json.loads(wiki_items.read_text(encoding="utf-8"))
        for key, row in wiki.items():
            item = result["items"].setdefault(key, {"icon_item_id": 0})
            item.update({field: row[field] for field in ("name", "base_id", "species_name", "egg_group_names", "kind") if field in row})
            item["source_page"] = row["page_title"]
    if wiki_icons:
        for image in sorted(wiki_icons.glob("*.png")):
            key = image.stem
            if not key.isdigit():
                continue
            item = result["items"].setdefault(key, {"name": ""})
            shutil.copyfile(image, target_icons / image.name)
            copied[:] = [record for record in copied if record["item_id"] != int(key)]
            copied.append({"item_id": int(key), "source_kind": "wiki", "sha256": hashlib.sha256(image.read_bytes()).hexdigest()})
            item["icon_item_id"] = int(key)
    for key, item in result["items"].items():
        if is_colorful_item(key, item):
            item["kind"] = "colorful"
    (output / "egg_inventory.json").write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    report = {
        "source": "Roco-Kingdom-World-Data/Bin/BinDataCompressed",
        "source_hashes": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [*sources, pets_file]},
        "configs": len(result["configs"]), "items": len(result["items"]), "random": len(result["random"]),
        "copied_icons": copied,
    }
    if names_file.is_file():
        report["source_hashes"][names_file.name] = hashlib.sha256(names_file.read_bytes()).hexdigest()
    if wiki_items:
        report["wiki_source"] = "https://wiki.biligame.com/nrc/Module:Items/data/Details/"
        report["wiki_pet_source"] = "https://wiki.biligame.com/nrc/Module:Pets/data/Catalog"
        report["source_hashes"][wiki_items.name] = hashlib.sha256(wiki_items.read_bytes()).hexdigest()
    if wiki_icons and (wiki_icons.parent / "wiki-download-report.json").is_file():
        report["wiki_images"] = json.loads((wiki_icons.parent / "wiki-download-report.json").read_text(encoding="utf-8"))["downloads"]
    (output / "egg_inventory_meta.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("configs", "items", "random")} | {"copied_icons": len(copied)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("game", "pets", "catalog", "icons", "reference", "output"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--wiki-items", type=Path, help="Wiki Items 变体与 Pets 目录按 Item 图标 ID 联查的事实 JSON")
    parser.add_argument("--wiki-icons", type=Path, help="已下载并校验的 Wiki 原图目录")
    args = parser.parse_args()
    build(args.game, args.pets, args.catalog, args.icons, args.reference, args.output, args.wiki_items, args.wiki_icons)
