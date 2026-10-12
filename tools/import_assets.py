"""导入游戏静态资源：精灵图 / 系别图标 / 图鉴元数据 / 系别克制表。

数据来源（本机解包与公开静态资源，均非云服务依赖）：
- 精灵图：wegame.shallow.ink 的公开 wiki 静态资源（社区镜像，按 base_conf_id 取 small.png；头像另见 sync_pet_media.py）
- 系别图标：蛋神助手包内 assets/reference/roco-helper-v3.8.1/TypeIcon（雪碧图 + CSS）
- 图鉴元数据：蛋神助手包内 assets/catalog/petBaseData.json（图鉴号/蛋组/性别比/体型区间/进化链）
- 系别克制表：rocom-helper 数据包 data/game/type_chart.json

用法：
    python tools/import_assets.py [--pets-only] [--meta-only] [--skip-pets]
    python tools/import_assets.py --src-danshen <解包目录> --src-game <game数据目录>

产物：
    spritelens/web/static/pets/<base_conf_id>.webp      128×128 精灵图
    spritelens/web/static/type-icons/sprite-0.webp      系别图标雪碧图
    spritelens/web/static/type-icons/sprites.css        雪碧图定位样式
    data/static/species.json                            合并图鉴元数据（原地更新）
    data/static/type_chart.json                         系别克制表
    data/static/_assets_meta.json                       本次导入的来源与统计
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "data" / "static"
WEB_STATIC = PROJECT_ROOT / "spritelens" / "web" / "static"
PETS_DIR = WEB_STATIC / "pets"
TYPE_ICON_DIR = WEB_STATIC / "type-icons"

PET_ICON_URL = "https://wegame.shallow.ink/api/v1/resources/wiki/assets/pets/{pid}/small.png"
PET_ICON_SIZE = 128  # 卡片全身小图约 40px，128 兼顾清晰与体积
PET_ICON_QUALITY = 88
DOWNLOAD_WORKERS = 12

DEFAULT_DANSHEN = Path.home() / "AppData" / "Local" / "Temp" / "ds" / "out"
DEFAULT_GAME = (
    Path.home() / "AppData" / "Local" / "Temp" / "roco_research"
    / "rocom-helper-innovationb1ue" / "data" / "game"
)


def _find_danshen_root(explicit: Path | None) -> Path | None:
    """定位蛋神助手解包目录（exe_extracted 的上级）。"""
    if explicit is not None:
        return explicit if explicit.is_dir() else None
    if not DEFAULT_DANSHEN.is_dir():
        return None
    for child in sorted(DEFAULT_DANSHEN.iterdir()):
        if child.is_dir() and (child / "assets").is_dir():
            return child
    return None


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# -- 精灵图 ------------------------------------------------------------
def _download_one(pid: str) -> tuple[str, bytes | None, str]:
    url = PET_ICON_URL.format(pid=pid)
    try:
        with urllib.request.urlopen(url, timeout=25) as response:
            return pid, response.read(), ""
    except urllib.error.HTTPError as exc:
        return pid, None, f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 - 网络异常逐项报告，不中断整批
        return pid, None, str(exc)


def _save_webp(data: bytes, dest: Path) -> int:
    from PIL import Image

    image = Image.open(io.BytesIO(data)).convert("RGBA")
    image = image.resize((PET_ICON_SIZE, PET_ICON_SIZE), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="WEBP", quality=PET_ICON_QUALITY, method=4)
    payload = buffer.getvalue()
    dest.write_bytes(payload)
    return len(payload)


def import_pet_icons(static: dict) -> dict:
    """按 species.json 的键下载精灵图；已存在的跳过。"""
    PETS_DIR.mkdir(parents=True, exist_ok=True)
    pids = list(static.keys())
    pending = [pid for pid in pids if not (PETS_DIR / f"{pid}.webp").is_file()]
    print(f"[assets] 精灵图：共 {len(pids)} 个，待下载 {len(pending)}，已存在 {len(pids) - len(pending)}")

    ok = skipped = failed = 0
    total_bytes = 0
    errors: list[str] = []
    if pending:
        with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
            futures = {pool.submit(_download_one, pid): pid for pid in pending}
            for index, future in enumerate(as_completed(futures), 1):
                pid, data, error = future.result()
                if data is None:
                    skipped += 1
                    if error and "404" not in error:
                        errors.append(f"{pid}: {error}")
                else:
                    try:
                        total_bytes += _save_webp(data, PETS_DIR / f"{pid}.webp")
                        ok += 1
                    except Exception as exc:  # noqa: BLE001 - 单张失败不影响整批
                        failed += 1
                        errors.append(f"{pid}: 写入失败 {exc}")
                if index % 50 == 0:
                    print(f"[assets]   进度 {index}/{len(pending)}（成功 {ok}）")
    existing = sum(1 for pid in pids if (PETS_DIR / f"{pid}.webp").is_file())
    print(f"[assets] 精灵图完成：新增 {ok}，无图 {skipped}（404 等），失败 {failed}，"
          f"现有 {existing}/{len(pids)}，新增体积 {total_bytes / 1024 / 1024:.1f}MB")
    for item in errors[:5]:
        print(f"[assets]   错误样例: {item}")
    return {"downloaded": ok, "missing": skipped, "failed": failed, "available": existing, "total": len(pids)}


# -- 系别图标 ----------------------------------------------------------
def import_type_icons(danshen: Path | None) -> dict:
    if danshen is None:
        print("[assets] 系别图标：未找到蛋神解包目录，跳过")
        return {"copied": 0}
    source = danshen / "assets" / "reference" / "roco-helper-v3.8.1" / "TypeIcon"
    if not source.is_dir():
        print(f"[assets] 系别图标：源目录不存在 {source}")
        return {"copied": 0}
    TYPE_ICON_DIR.mkdir(parents=True, exist_ok=True)
    copied = 0
    for name in ("sprite-0.webp", "sprites.css"):
        src = source / name
        if src.is_file():
            (TYPE_ICON_DIR / name).write_bytes(src.read_bytes())
            copied += 1
            print(f"[assets] 系别图标：{name}（{src.stat().st_size / 1024:.1f}KB）")
    return {"copied": copied}


# -- 图鉴元数据 --------------------------------------------------------
def import_handbook_meta(danshen: Path | None) -> dict:
    """把 petBaseData 的图鉴字段合并进 species.json（原地更新，保留既有键）。"""
    if danshen is None:
        print("[assets] 图鉴元数据：未找到蛋神解包目录，跳过")
        return {"merged": 0}
    source = danshen / "assets" / "catalog" / "petBaseData.json"
    if not source.is_file():
        print(f"[assets] 图鉴元数据：源文件不存在 {source}")
        return {"merged": 0}

    meta = _load_json(source)
    by_id: dict = meta.get("byId", {})
    group_map: dict = meta.get("groupMap", {})
    species_path = STATIC_DIR / "species.json"
    species = _load_json(species_path)

    merged = 0
    for key, entry in species.items():
        base = by_id.get(key)
        if base is None:
            continue
        entry["dex_no"] = base.get("dexNo")
        entry["handbook_no"] = base.get("handbookNo")
        entry["egg_groups"] = [str(g) for g in (base.get("eggGroupNames") or [])]
        ratio = base.get("genderRatio") or {}
        entry["gender_ratio"] = {
            "male": ratio.get("male_percent"),
            "female": ratio.get("female_percent"),
        }
        entry["height_range"] = [base.get("heightLow"), base.get("heightHigh")]
        entry["weight_range"] = [base.get("weightLow"), base.get("weightHigh")]
        entry["chain_members"] = [int(c) for c in (base.get("chainMembers") or []) if isinstance(c, int)]
        entry["has_shiny"] = bool(base.get("hasShiny"))
        if base.get("displayName") and base["displayName"] != entry.get("name"):
            entry["display_name"] = str(base["displayName"])
        merged += 1

    species_path.write_text(
        json.dumps(species, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    print(f"[assets] 图鉴元数据：已合并 {merged}/{len(species)} 个物种"
          f"（蛋组 {len(group_map)} 组，来源 {source.name}）")
    return {"merged": merged, "total": len(species), "egg_groups": len(group_map)}


# -- 系别克制表 --------------------------------------------------------
def import_type_chart(game_dir: Path | None) -> dict:
    if game_dir is None or not (game_dir / "type_chart.json").is_file():
        print("[assets] 系别克制表：未找到源文件，跳过")
        return {"imported": 0}
    source = game_dir / "type_chart.json"
    raw = _load_json(source)
    # 只保留前端需要的部分：系别名录 + 克制矩阵（id → {target_id: multiplier}）
    out = {
        "version": raw.get("version"),
        "types": [
            {"id": t.get("id"), "name": t.get("name"), "name_en": t.get("name_en"), "color": t.get("color")}
            for t in raw.get("types", [])
        ],
        "chart": {str(k): {str(kk): float(vv) for kk, vv in v.items()} for k, v in raw.get("chart", {}).items()},
    }
    dest = STATIC_DIR / "type_chart.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"[assets] 系别克制表：{len(out['types'])} 系别 / {len(out['chart'])} 条克制关系 "
          f"（{dest.stat().st_size / 1024:.1f}KB）")
    return {"imported": len(out["types"]), "relations": len(out["chart"])}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="导入静态资源（精灵图/系别图标/图鉴元数据/克制表）")
    parser.add_argument("--src-danshen", type=Path, default=None, help="蛋神助手解包目录（含 assets/）")
    parser.add_argument("--src-game", type=Path, default=None, help="rocom-helper data/game 目录")
    parser.add_argument("--skip-pets", action="store_true", help="跳过精灵图下载")
    parser.add_argument("--meta-only", action="store_true", help="只导入元数据（不下载图片）")
    args = parser.parse_args(argv)

    danshen = _find_danshen_root(args.src_danshen)
    game_dir = args.src_game if (args.src_game and args.src_game.is_dir()) else (DEFAULT_GAME if DEFAULT_GAME.is_dir() else None)
    print(f"[assets] 蛋神解包: {danshen or '（未找到）'}")
    print(f"[assets] 游戏数据: {game_dir or '（未找到）'}")

    species_path = STATIC_DIR / "species.json"
    if not species_path.is_file():
        raise SystemExit(f"缺少 {species_path}，请先运行 tools/import_static_data.py")
    species = _load_json(species_path)

    report: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": {
            "pet_icons": PET_ICON_URL,
            "type_icons": str(danshen / "assets/reference/roco-helper-v3.8.1/TypeIcon") if danshen else "",
            "handbook_meta": str(danshen / "assets/catalog/petBaseData.json") if danshen else "",
            "type_chart": str(game_dir / "type_chart.json") if game_dir else "",
        },
    }

    if not args.meta_only:
        report["type_icons"] = import_type_icons(danshen)
    report["handbook_meta"] = import_handbook_meta(danshen)
    report["type_chart"] = import_type_chart(game_dir)
    if not args.skip_pets and not args.meta_only:
        report["pet_icons"] = import_pet_icons(species)

    meta_path = STATIC_DIR / "_assets_meta.json"
    meta_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[assets] 完成 → {meta_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
