"""按官方 manifest 导入精灵头像/立绘及已解包的游戏标记，生成离线映射。"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent


def fit_portrait(image: Image.Image) -> Image.Image:
    """按透明边界统一头像占比，不裁切非透明内容。"""
    image = image.convert("RGBA")
    bounds = image.getchannel("A").getbbox()
    if bounds:
        image = image.crop(bounds)
    scale = 232 / max(image.size)
    image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (256, 256))
    canvas.paste(image, ((256 - image.width) // 2, (256 - image.height) // 2))
    return canvas


def sync_portraits(web: Path, index: dict) -> list[dict]:
    """保留原始头像，派生统一留白版本；重复导入从原始文件生成。"""
    resources = []
    for variants in index.values():
        for entry in variants.values():
            url = entry.get("portrait")
            if not url:
                continue
            original = web / url.removeprefix("/static/").replace("-portrait-fit.webp", "-portrait.webp")
            target = original.with_name(original.stem + "-fit.webp")
            with Image.open(original) as image:
                fit_portrait(image).save(target, "WEBP", lossless=True)
            entry["portrait"] = "/static/pet-media/" + target.name
            resources.append({"key": "portrait-fit/" + original.name,
                              "sourceLocal": "/static/pet-media/" + original.name,
                              "sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
                              "local": entry["portrait"], "transform": "alpha bounds crop + 232px content on 256px canvas"})
    return resources


def sync_rarity(web: Path) -> list[dict]:
    """统一稀有标记透明留白，保留原图及比例。"""
    resources = []
    for original in sorted((web / "rarity").glob("*.png")):
        if original.stem.endswith("-fit"):
            continue
        with Image.open(original) as image:
            image = image.convert("RGBA")
            bounds = image.getchannel("A").getbbox()
            if bounds:
                image = image.crop(bounds)
            scale = 60 / max(image.size)
            image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", (64, 64))
            canvas.paste(image, ((64 - image.width) // 2, (64 - image.height) // 2))
            target = original.with_name(original.stem + "-fit.png")
            canvas.save(target)
        resources.append({"key": "rarity-fit/" + original.name,
                          "sourceLocal": "/static/rarity/" + original.name,
                          "sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
                          "local": "/static/rarity/" + target.name,
                          "transform": "alpha bounds crop + 60px content on 64px canvas"})
    return resources


def sync_medals(source: Path, web: Path) -> list[dict]:
    """导入四种普通奖章，裁掉透明边距以统一显示尺寸。"""
    target = web / "medals"
    target.mkdir(parents=True, exist_ok=True)
    resources = []
    for medal_id, name in ((1001, "大块头"), (1002, "小不点"), (1025, "粗嗓门"), (1026, "婉转声")):
        origin = source / "assets/medals" / f"{medal_id}.png"
        with Image.open(origin) as image:
            image = image.convert("RGBA")
            bounds = image.getchannel("A").getbbox()
            if bounds:
                image = image.crop(bounds)
            image.thumbnail((128, 128))
            normalized = Image.new("RGBA", (128, 128))
            normalized.paste(image, ((128 - image.width) // 2, (128 - image.height) // 2))
            normalized.save(target / f"{medal_id}.png")
        resources.append({"key": f"medals/{medal_id}.png", "name": name,
                          "sha256": hashlib.sha256(origin.read_bytes()).hexdigest(),
                          "local": f"/static/medals/{medal_id}.png",
                          "transform": "alpha bounds crop + centered 128px canvas"})
    (target / "sources.json").write_text(json.dumps({"source": source.name, "resources": resources}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return resources


def sync(source: Path, root: Path = ROOT) -> dict:
    assets = source / "assets"
    manifest = json.loads((assets / "official-resources/manifest.json").read_text(encoding="utf-8"))
    species = json.loads((root / "data/static/species.json").read_text(encoding="utf-8"))
    web = root / "spritelens/web/static"
    output = web / "pet-media"
    output.mkdir(parents=True, exist_ok=True)
    index, sources, missing = {}, [], []
    previous_path = root / "data/static/pet_media_report.json"
    previous = json.loads(previous_path.read_text(encoding="utf-8")) if previous_path.is_file() else {}
    previous_hashes = {row["key"]: row.get("sha256") for row in previous.get("resources", [])}
    def fetch(resource):
        key = str(resource.get("speciesId"))
        use, variant = resource.get("use"), resource.get("variant")
        if key not in species or use not in ("portrait", "artwork") or variant not in ("normal", "shiny"):
            return None
        filename = f"{key}-{variant}-{use}.webp"
        url = "/static/pet-media/" + filename
        if (output / filename).is_file() and not resource.get("refresh"):
            return key, variant, use, url, resource.get("sha256") or previous_hashes.get(resource["key"])
        mirror = resource.get("mirrorPath")
        path = assets / "official-resources" / mirror if mirror else None
        try:
            if path is not None and path.is_file():
                raw = path.read_bytes()
            elif resource.get("sourceKind") == "official-cdn" and str(resource.get("sourceUrl", "")).startswith("https://game.gtimg.cn/"):
                with urllib.request.urlopen(resource["sourceUrl"], timeout=20) as response:
                    raw = response.read()
            else:
                return {"key": resource["key"], "reason": "无可用官方镜像或地址"}
            digest = hashlib.sha256(raw).hexdigest()
            if resource.get("sha256") and digest != resource["sha256"]:
                return {"key": resource["key"], "reason": "内容校验不符"}
            with Image.open(io.BytesIO(raw)) as image:
                image = image.convert("RGBA")
                image.thumbnail((256, 256) if use == "portrait" else (512, 512))
                image.save(output / filename, "WEBP", quality=90)
            return key, variant, use, url, digest
        except Exception as exc:
            return {"key": resource["key"], "reason": str(exc)}
    resources = list(manifest["resources"].values())
    portrait_ids = {str(row.get("speciesId")) for row in resources if row.get("use") == "portrait" and row.get("variant") == "normal"}
    catalog = json.loads((assets / "catalog/petBaseData.json").read_text(encoding="utf-8"))
    # 社区 icon.png 可能实际为立绘。以目录确认的稳定 ID 查询同一官方头像路径，
    # 成功解码后才入映射；404 不回退社区全身图。
    for row in catalog["records"]:
        if str(row["id"]) not in portrait_ids and row.get("iconUrl"):
            for variant, filename in (("normal", "icon.png"), ("shiny", "icon_yise.png")):
                key = f"verified-cdn/{row['id']}/portrait/{variant}"
                resources.append({"key": key, "speciesId": row["id"], "use": "portrait", "variant": variant,
                                  "sourceKind": "official-cdn", "derivedFrom": "catalog stable ID + manifest portrait endpoint",
                                  "refresh": key not in previous_hashes,
                                  "sourceUrl": f"https://game.gtimg.cn/images/rocom/rocodata/jingling/{row['id']}/{filename}"})
    with ThreadPoolExecutor(max_workers=12) as pool:
        for resource, result in zip(resources, pool.map(fetch, resources)):
            if result is None:
                continue
            if isinstance(result, dict):
                missing.append(result)
                continue
            key, variant, use, url, digest = result
            index.setdefault(key, {}).setdefault(variant, {})[use] = url
            sources.append({"key": resource["key"], "url": resource.get("sourceUrl"), "mirror": resource.get("mirrorPath"),
                            "sha256": digest, "local": url, "derivedFrom": resource.get("derivedFrom")})
    for folder, names in {
        "colorCards": ["pattern_sparkle_four.png", "pattern_heart.png", "pattern_diamond.png",
                       "pattern_star_outline.png", "1000.png", "s1.png", "s2.png", "s3.png", "s4.png"],
        "reference/rarity": ["shiny.png", "colorful.png", "shiny-colorful.png", "blackwhite-colorful.png",
                             "blackwhite-shiny-colorful.png"] + [f"s{i}-{kind}.png" for i in range(1, 5)
                                                               for kind in ("colorful", "shiny-colorful")],
    }.items():
        target = web / ("color-cards" if folder == "colorCards" else "rarity")
        target.mkdir(exist_ok=True)
        for name in names:
            origin = assets / folder / name
            shutil.copyfile(origin, target / name)
            sources.append({"key": folder + "/" + name, "sha256": hashlib.sha256(origin.read_bytes()).hexdigest(),
                            "local": "/static/" + target.name + "/" + name})
    sources.extend(sync_rarity(web))
    sources.extend(sync_medals(source, web))
    sources.extend(sync_portraits(web, index))
    report = {"source": source.name, "manifest_version": manifest.get("resourceVersion"),
              "species_total": len(species), "portrait_species": len(index), "missing_mirrors": missing,
              "without_portrait": sorted(set(species) - set(index), key=int), "resources": sources}
    for name, data in (("pet_media.json", index), ("pet_media_report.json", report)):
        (root / "data/static" / name).write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    return {"species_total": len(species), "portrait_species": len(index), "missing": len(missing)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    print(json.dumps(sync(parser.parse_args().source), ensure_ascii=False))
