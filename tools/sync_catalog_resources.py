"""按稳定 ID 补齐目录和官方镜像，输出可复查的缺口/冲突报告。"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools.import_egg_data import convert

STAT_MAP = {"hp": "hp", "physical_attack": "atk", "magic_attack": "spa",
            "physical_defense": "def", "magic_defense": "spd", "speed": "spe"}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def merge_species(species: dict, records: list[dict]) -> tuple[list[str], list[dict]]:
    added, conflicts = [], []
    for ref in records:
        key = str(ref["id"])
        attrs = ref.get("attributes") or {}
        stats = {dest: int(attrs.get(src) or 0) for src, dest in STAT_MAP.items()}
        stats["sum"] = sum(stats.values())
        ratio = ref.get("genderRatio") or {}
        candidate = {
            "name": ref.get("name"), "display_name": ref.get("displayName"),
            "types": ref.get("typeIds"), "type_names": ref.get("typeNames"),
            "stats": stats, "stage": ref.get("stage"), "dex_no": ref.get("dexNo"),
            "handbook_no": ref.get("handbookNo"), "egg_groups": ref.get("eggGroupNames"),
            "gender_ratio": {"male": ratio.get("male_percent"), "female": ratio.get("female_percent")},
            "height_range": [ref.get("heightLow"), ref.get("heightHigh")],
            "weight_range": [ref.get("weightLow"), ref.get("weightHigh")],
            "chain_members": ref.get("chainMembers"), "description": ref.get("description"),
            "has_shiny": ref.get("hasShiny"), "has_ride_talent": ref.get("hasRideTalent"),
            "breedable": ref.get("breedable"), "form": ref.get("form"),
        }
        if key not in species:
            species[key] = {}
            added.append(key)
        entry = species[key]
        for field, value in candidate.items():
            if value is None or value == "" or value == []:
                continue
            if field.endswith("_range") and not valid_range(value):
                continue
            if field == "gender_ratio" and any(v is None for v in value.values()):
                continue
            current = entry.get(field)
            missing = current is None or current == "" or current == []
            if field.endswith("_range"):
                missing = not valid_range(current)
            if missing:
                entry[field] = value
            elif current != value:
                conflicts.append({"id": key, "field": field, "kept": current, "reference": value})
    return added, conflicts


def valid_range(value: object) -> bool:
    return (isinstance(value, (list, tuple)) and len(value) == 2
            and all(isinstance(v, int) and v > 0 for v in value) and value[1] >= value[0])


def sync(source: Path, root: Path, download: bool) -> dict:
    assets = source / "assets"
    static = root / "data/static"
    web = root / "spritelens/web/static"
    catalog = load(assets / "catalog/petBaseData.json")
    species = load(static / "species.json")
    added, conflicts = merge_species(species, catalog["records"])
    write(static / "species.json", species)
    eggs = load(static / "eggs.json")
    reference_eggs = convert(assets / "catalog/eggData.json")
    by_key = {x["egg_key"]: x for x in eggs["eggs"]}
    for row in reference_eggs["eggs"]:
        if row["egg_key"] not in by_key:
            eggs["eggs"].append(row)
        else:
            for key, value in row.items():
                current = by_key[row["egg_key"]].get(key)
                if current is None or current == "" or current == [] or (isinstance(current, int) and current == 0 and value):
                    by_key[row["egg_key"]][key] = value
                elif current != value:
                    conflicts.append({"id": row["egg_key"], "field": "egg." + key, "kept": current, "reference": value})
    aliases = eggs.get("egg_base_index", {}).copy()
    for base_id, egg_key in reference_eggs["egg_base_index"].items():
        if base_id not in aliases or aliases[base_id] not in by_key:
            aliases[base_id] = egg_key
        elif aliases[base_id] != egg_key:
            conflicts.append({"id": base_id, "field": "egg_base_index", "kept": aliases[base_id], "reference": egg_key})
    eggs["egg_base_index"] = aliases
    write(static / "eggs.json", eggs)
    manifest = load(assets / "official-resources/manifest.json")
    resources = list(manifest["resources"].values())
    portraits = {str(x["speciesId"]): x for x in resources
                 if x.get("use") == "portrait" and x.get("variant") == "normal"
                 and x.get("speciesId") == x.get("resourceId")}
    items = {str(x.get("resourceId")): x for x in resources if x.get("use") == "item"}
    jobs = [(web / "pets" / f"{key}.webp", portraits.get(key), "pet", key)
            for key in species if not (web / "pets" / f"{key}.webp").is_file()]
    jobs += [(web / "egg-icons" / f"{e['egg_item_id']}.png", items.get(str(e["egg_item_id"])), "egg", str(e["egg_item_id"]))
             for e in eggs["eggs"] if e.get("egg_item_id") and not (web / "egg-icons" / f"{e['egg_item_id']}.png").is_file()]

    def fetch(job: tuple) -> dict:
        dest, resource, kind, key = job
        record = {"kind": kind, "id": key}
        if not resource:
            return {**record, "status": "missing", "reason": "manifest 无对应资源"}
        mirror = resource.get("mirrorPath")
        path = (assets / "official-resources" / mirror).resolve() if mirror else None
        record.update(source_url=resource.get("sourceUrl"), manifest_key=resource["key"])
        try:
            if path and path.is_relative_to((assets / "official-resources").resolve()) and path.is_file():
                data = path.read_bytes()
            elif download and resource.get("sourceKind") == "official-cdn" and str(resource.get("sourceUrl", "")).startswith("https://game.gtimg.cn/"):
                with urllib.request.urlopen(resource["sourceUrl"], timeout=20) as response:
                    data = response.read()
            else:
                return {**record, "status": "missing", "reason": "本地镜像缺失"}
            digest = hashlib.sha256(data).hexdigest()
            if resource.get("sha256") and digest != resource["sha256"]:
                return {**record, "status": "missing", "reason": "内容哈希与 manifest 不符"}
            from PIL import Image
            image = Image.open(io.BytesIO(data)).convert("RGBA")
            dest.parent.mkdir(parents=True, exist_ok=True)
            if kind == "pet":
                image.thumbnail((128, 128), Image.Resampling.LANCZOS)
                image.save(dest, "WEBP", quality=88, method=4)
            else:
                image.save(dest, "PNG")
            return {**record, "status": "imported", "sha256_source": digest}
        except Exception as exc:
            return {**record, "status": "missing", "reason": str(exc)}

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(fetch, jobs))
    previous = static / "resource_sync_report.json"
    history = load(previous).get("resource_imports", []) if previous.is_file() else []
    imported = {f"{x['kind']}/{x['id']}": x for x in history + outcomes if x["status"] == "imported"}
    report = {
        "source": "蛋神助手 v1.1.6 assets/catalog + official-resources manifest",
        "source_hashes": {name: hashlib.sha256((assets / path).read_bytes()).hexdigest() for name, path in (
            ("species", "catalog/petBaseData.json"), ("eggs", "catalog/eggData.json"), ("manifest", "official-resources/manifest.json"))},
        "catalog_version": catalog.get("dataVersion"), "resource_version": manifest.get("resourceVersion"),
        "added_species": sorted(set(added + (load(previous).get("added_species", []) if previous.is_file() else []))),
        "conflicts": conflicts, "resource_imports": list(imported.values()),
        "missing_resources": [x for x in outcomes if x["status"] == "missing"],
        "missing_fields": [{"id": key, "fields": [field for field in ("height_range", "weight_range", "egg_groups", "chain_members")
                           if not (valid_range(row.get(field)) if field.endswith("_range") else row.get(field))]}
                           for key, row in species.items() if any(not (valid_range(row.get(field)) if field.endswith("_range") else row.get(field))
                           for field in ("height_range", "weight_range", "egg_groups", "chain_members"))],
        "coverage": {"species": len(species), "height_ranges": sum(valid_range(x.get("height_range")) for x in species.values()),
                     "weight_ranges": sum(valid_range(x.get("weight_range")) for x in species.values()),
                     "eggs": len(eggs["eggs"]), "egg_base_aliases": len(eggs["egg_base_index"]),
                     "pet_images": len(list((web / "pets").glob("*.webp"))), "egg_images": len(list((web / "egg-icons").glob("*.png")))},
    }
    write(previous, report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    result = sync(args.source, ROOT, args.download)
    print(json.dumps(result["coverage"], ensure_ascii=False))
    print(f"缺失资源 {len(result['missing_resources'])}；字段冲突 {len(result['conflicts'])}（保留已有值）")
