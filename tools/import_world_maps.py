"""从解包资源导入世界地图底图并生成坐标 manifest。

显式传入资源根（如 D:/code_resources/roco_resources），只读取两张 4096 世界地图
与 desktop-data.json 的地图参数；来源哈希、语义参数或图片尺寸不符时失败，
不覆盖上一份可用产物。运行时只读 data/static/world_maps.json 与
spritelens/web/static/maps/，不引用外部解包目录。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = PROJECT_ROOT / "data" / "static" / "world_maps.json"
WEB_MAP_DIR = PROJECT_ROOT / "spritelens" / "web" / "static" / "maps"

SCHEMA_VERSION = 1
# 投影公式变化时递增；当前坐标语义与参考实现 origin_side_normalized 一致。
COORDINATE_VERSION = 1
DATASET = "roco_resources"
CONFIG_PATH = "runtime_assets/desktop-data.json"

# 参考数据集固定版本：底图内容哈希决定产物本身，源数据升级时先复核再更新。
# 大陆 10003 为首期支持地图，已用 8 个游戏内坐标点与地图截图完成投影校准；
# 学院 10018 图片可用，但未做独立现场校准，只保留为 candidate，
# C13-02 启用动态投影前必须先按计划 §3.2 校准。
PINNED_MAPS = {
    "10003": {
        "path": "decompiled/asar/ui/assets/maps/10003.webp",
        "sha256": "3aaaca531a50e6fcee6763c696a1f58c824d464dbc790a20970d5052a7e88c7c",
        "bytes": 1263992,
        "width": 4096,
        "height": 4096,
        "origin": (306000, 408000),
        "side": 408000,
        "availability": "supported",
    },
    "10018": {
        "path": "decompiled/asar/ui/assets/maps/10018.webp",
        "sha256": "44851431840cc83988de4eaf5d9c0c0da62d9c13abb44b7081fc9c922b89b96b",
        "bytes": 1786848,
        "width": 4096,
        "height": 4096,
        "origin": (-886161, -891000),
        "side": 180000,
        "availability": "candidate",
    },
}


# 现场校准证据：游戏内地图截图（缩放约 4.6 倍）与入库 4096 底图做多尺度互相关匹配，
# 锚点取玩家徽标外接框中心；8 个现场点平均误差 2.82 px、最大 4.54 px（阈值 8 px），
# 朝向确认北向上。这里只记录结论与参数，不写截图或本机路径。
FIELD_CALIBRATION = {
    "10003": {
        "level": "verified",
        "basis": "field_screenshot_match",
        "field_points": 8,
        "orientation": "verified_north_up",
        "max_error_px": 4.54,
        "mean_error_px": 2.82,
        "checked_at": "2026-10-26",
        "method": "游戏内地图截图与入库底图多尺度互相关匹配，锚点取玩家徽标中心",
    },
}


def calibration_for(map_id: str) -> dict[str, Any]:
    field = FIELD_CALIBRATION.get(map_id)
    if field is not None:
        return dict(field)
    return {
        "level": "candidate",
        "basis": "static_import",
        "field_points": 0,
        "orientation": "unverified",
    }


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_source(root: Path, relative: str) -> bytes:
    path = root / relative
    if not path.is_file():
        raise ValueError(f"缺少来源文件 {relative}")
    return path.read_bytes()


def _integer(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{label} 不是整数")
    return value


def build_manifest(config_raw: bytes, source_root: Path) -> dict[str, Any]:
    try:
        config = json.loads(config_raw)
    except ValueError as exc:
        raise ValueError(f"desktop-data.json 不是有效 JSON：{exc}") from exc
    maps_config = config.get("maps")
    scene_res = config.get("scene_res")
    if not isinstance(maps_config, dict) or not isinstance(scene_res, dict):
        raise ValueError("desktop-data.json 缺少 maps 或 scene_res")

    entries: dict[str, Any] = {}
    source_maps: dict[str, Any] = {}
    image_payloads: dict[str, bytes] = {}
    for map_id, pinned in PINNED_MAPS.items():
        raw_entry = maps_config.get(map_id)
        scene = scene_res.get(map_id)
        name = scene.get("n") if isinstance(scene, dict) else None
        if not isinstance(raw_entry, dict) or not isinstance(name, str) or not name:
            raise ValueError(f"{map_id} 缺少地图参数或场景名称")
        if raw_entry.get("world") is not True:
            raise ValueError(f"{map_id} 不是世界地图（world != true）")
        origin_x = _integer(raw_entry.get("ox"), f"{map_id}.ox")
        origin_y = _integer(raw_entry.get("oy"), f"{map_id}.oy")
        side = _integer(raw_entry.get("side"), f"{map_id}.side")
        if side <= 0:
            raise ValueError(f"{map_id}.side 必须为正数")
        if (origin_x, origin_y) != pinned["origin"] or side != pinned["side"]:
            raise ValueError(
                f"{map_id} 坐标参数与固定版本不符："
                f"原点 ({origin_x},{origin_y}) 边长 {side}，"
                f"期望原点 {pinned['origin']} 边长 {pinned['side']}"
            )

        data = read_source(source_root, pinned["path"])
        if len(data) != pinned["bytes"] or sha256(data) != pinned["sha256"]:
            raise ValueError(f"{map_id} 底图内容与固定版本不符")
        with Image.open(BytesIO(data)) as image:
            if image.format != "WEBP":
                raise ValueError(f"{map_id} 底图不是 WebP")
            if image.size != (pinned["width"], pinned["height"]):
                raise ValueError(
                    f"{map_id} 底图尺寸 {image.size} 与固定版本 "
                    f"{pinned['width']}x{pinned['height']} 不符"
                )
            image.load()
        image_payloads[map_id] = data

        entries[map_id] = {
            "name": name,
            "availability": pinned["availability"],
            "image": {
                "asset": f"maps/{map_id}.webp",
                "url": f"/static/maps/{map_id}.webp",
                "format": "webp",
                "width": pinned["width"],
                "height": pinned["height"],
                "bytes": len(data),
                "sha256": pinned["sha256"],
            },
            "coordinate_system": {
                "raw_unit": "game_world",
                "image_pixel_origin": "top_left",
            },
            "projection": {
                "kind": "origin_side_normalized",
                "origin_x": origin_x,
                "origin_y": origin_y,
                "side": side,
            },
            "calibration": calibration_for(map_id),
            "notes": (
                "解包原图直接入库，未转码、未裁切；原点与边长来自 desktop-data.json，"
                "已用 8 个游戏内坐标点与地图截图比对，单位像素误差不超过 8，朝向已确认北向上。"
                if map_id in FIELD_CALIBRATION
                else "解包原图直接入库，未转码、未裁切；原点与边长来自 desktop-data.json，"
                "朝向和坐标误差未做游戏现场地标校准。"
            ),
        }
        source_maps[map_id] = {
            "path": pinned["path"],
            "sha256": pinned["sha256"],
            "bytes": len(data),
        }

    for map_id, entry in entries.items():
        verify_projection(map_id, entry)

    return {
        "schema_version": SCHEMA_VERSION,
        "coordinate_version": COORDINATE_VERSION,
        "dataset": DATASET,
        "generated_by": "tools/import_world_maps.py",
        "source": {
            "config": {
                "path": CONFIG_PATH,
                "sha256": sha256(config_raw),
            },
            "maps": source_maps,
        },
        "maps": entries,
    }


def verify_projection(map_id: str, entry: dict[str, Any]) -> None:
    """校验投影与固定参数一致，并检查原点、边缘、轴向与越界行为。"""
    projection = entry["projection"]
    pinned = PINNED_MAPS[map_id]
    width = entry["image"]["width"]
    height = entry["image"]["height"]
    origin_x = projection["origin_x"]
    origin_y = projection["origin_y"]
    side = projection["side"]
    if (origin_x, origin_y, side) != (*pinned["origin"], pinned["side"]):
        raise ValueError(f"{map_id} 投影参数与固定版本不一致")

    def project(raw_x: int, raw_y: int) -> tuple[float, float]:
        return (
            (raw_x - origin_x) / side * width,
            (raw_y - origin_y) / side * height,
        )

    checks = {
        "原点": ((origin_x, origin_y), (0.0, 0.0)),
        "x 轴边缘": ((origin_x + side, origin_y), (float(width), 0.0)),
        "y 轴边缘": ((origin_x, origin_y + side), (0.0, float(height))),
        "对角边缘": ((origin_x + side, origin_y + side), (float(width), float(height))),
        "留出点": (
            (origin_x + side // 4, origin_y + side * 3 // 4),
            (width / 4, height * 3 / 4),
        ),
    }
    for label, (raw, expected) in checks.items():
        actual = project(*raw)
        if abs(actual[0] - expected[0]) > 1e-6 or abs(actual[1] - expected[1]) > 1e-6:
            raise ValueError(
                f"{map_id} 投影在{label}校验失败：{actual} 应为 {expected}"
            )
    # 轴向契约：raw x/y 分别只影响图内 x/y，越界坐标不得被静默钳制
    step = project(origin_x + side // 10, origin_y + side // 10)
    if step[0] <= 0 or step[1] <= 0:
        raise ValueError(f"{map_id} 投影未保持自原点向下的正方向")
    if project(origin_x - side, origin_y)[0] >= 0:
        raise ValueError(f"{map_id} 投影把越界坐标钳制进了图像范围")


def publish(files: dict[Path, bytes]) -> None:
    """先暂存与校验，替换失败时恢复已经替换的文件。"""
    staged: list[tuple[Path, Path, Path | None]] = []
    temporary_files: list[Path] = []
    published: list[tuple[Path, Path | None]] = []
    keep_backups = False
    try:
        for destination, payload in files.items():
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.is_file() and destination.read_bytes() == payload:
                continue
            fd, name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".importing", dir=destination.parent)
            os.close(fd)
            temporary = Path(name)
            temporary_files.append(temporary)
            temporary.write_bytes(payload)
            if temporary.read_bytes() != payload:
                raise ValueError(f"暂存校验失败 {destination.name}")
            backup = None
            if destination.exists():
                original = destination.read_bytes()
                fd, name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".rollback", dir=destination.parent)
                os.close(fd)
                backup = Path(name)
                temporary_files.append(backup)
                backup.write_bytes(original)
                if backup.read_bytes() != original:
                    raise ValueError(f"备份校验失败 {destination.name}")
            staged.append((temporary, destination, backup))
        try:
            for temporary, destination, backup in staged:
                os.replace(temporary, destination)
                published.append((destination, backup))
        except OSError as exc:
            failures = []
            for destination, backup in reversed(published):
                try:
                    if backup is None:
                        destination.unlink()
                    else:
                        os.replace(backup, destination)
                except OSError as rollback_error:
                    failures.append(f"{destination.name}: {rollback_error}")
            if failures:
                keep_backups = True
                raise RuntimeError(f"地图发布失败且回滚不完整，备份已保留：{'; '.join(failures)}") from exc
            raise
    finally:
        for temporary in temporary_files:
            if keep_backups and temporary.suffix == ".rollback":
                continue
            if temporary.exists():
                temporary.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path, help="解包资源根目录")
    args = parser.parse_args()
    source_root: Path = args.source_root
    if not source_root.is_dir():
        raise SystemExit(f"导入失败：资源根不存在 {source_root}")
    try:
        config_raw = read_source(source_root, CONFIG_PATH)
        manifest = build_manifest(config_raw, source_root)
        payloads: dict[Path, bytes] = {}
        for map_id, entry in manifest["maps"].items():
            data = read_source(source_root, manifest["source"]["maps"][map_id]["path"])
            if sha256(data) != entry["image"]["sha256"]:
                raise ValueError(f"{map_id} 底图在生成 manifest 后发生变化")
            payloads[WEB_MAP_DIR / f"{map_id}.webp"] = data
        payloads[MANIFEST_PATH] = (
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        publish(payloads)
    except RuntimeError as exc:
        raise SystemExit(f"导入失败：{exc}") from exc
    except (OSError, ValueError) as exc:
        raise SystemExit(f"导入失败（保留旧产物）：{exc}") from exc

    print(f"导入 {len(manifest['maps'])} 张世界地图 → {MANIFEST_PATH}")
    for map_id, entry in manifest["maps"].items():
        image = entry["image"]
        projection = entry["projection"]
        print(
            f"  {map_id} {entry['name']}: {image['width']}x{image['height']} "
            f"{image['sha256'][:12]} origin=({projection['origin_x']},"
            f"{projection['origin_y']}) side={projection['side']} "
            f"availability={entry['availability']} "
            f"calibration={entry['calibration']['level']}"
        )


if __name__ == "__main__":
    main()
