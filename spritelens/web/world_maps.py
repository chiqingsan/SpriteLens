"""世界地图清单的只读接口：下发投影参数与底图地址，由前端完成画布投影。

清单由 `tools/import_world_maps.py` 生成；接口只暴露前端需要的最小契约，
不把本机路径、来源台账或校准过程细节带进用户界面。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from aiohttp import web

from spritelens.paths import static_dir
from spritelens.web.background import run_blocking

logger = logging.getLogger(__name__)

MAP_MANIFEST_NAME = "world_maps.json"
MAP_AVAILABILITIES = {"supported", "candidate"}
CALIBRATION_LEVELS = {"verified", "candidate"}

# 清单只在导入工具重写时才变化；按 mtime+大小缓存解析结果，避免每个请求
# 都读文件并逐字段校验（审查 2026-10-27 P2）。返回同一份只读 dict，
# 由 json_response 序列化，调用方不得就地修改。
_MANIFEST_CACHE: dict[str, tuple[tuple[int, int], dict]] = {}


def _integer(value, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"世界地图清单格式无效：{field} 必须是整数")
    return value


def _positive(value, field: str) -> int:
    number = _integer(value, field)
    if number <= 0:
        raise ValueError(f"世界地图清单格式无效：{field} 必须大于 0")
    return number


def _text(value, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"世界地图清单格式无效：{field} 必须是非空字符串")
    return value


def _map_entry(map_id: str, entry) -> dict:
    if not isinstance(entry, dict):
        raise ValueError(f"世界地图清单格式无效：{map_id} 必须是对象")
    name = _text(entry.get("name"), f"{map_id}.name")
    availability = entry.get("availability")
    if availability not in MAP_AVAILABILITIES:
        raise ValueError(f"世界地图清单格式无效：{map_id}.availability 取值未知")
    image = entry.get("image")
    if not isinstance(image, dict):
        raise ValueError(f"世界地图清单格式无效：{map_id}.image 必须是对象")
    projection = entry.get("projection")
    if not isinstance(projection, dict):
        raise ValueError(f"世界地图清单格式无效：{map_id}.projection 必须是对象")
    calibration = entry.get("calibration")
    if not isinstance(calibration, dict) or calibration.get("level") not in CALIBRATION_LEVELS:
        raise ValueError(f"世界地图清单格式无效：{map_id}.calibration.level 取值未知")
    return {
        "name": name,
        "availability": availability,
        "image": {
            "url": _text(image.get("url"), f"{map_id}.image.url"),
            "width": _positive(image.get("width"), f"{map_id}.image.width"),
            "height": _positive(image.get("height"), f"{map_id}.image.height"),
        },
        "projection": {
            "origin_x": _integer(projection.get("origin_x"), f"{map_id}.projection.origin_x"),
            "origin_y": _integer(projection.get("origin_y"), f"{map_id}.projection.origin_y"),
            "side": _positive(projection.get("side"), f"{map_id}.projection.side"),
        },
        "calibration": {"level": calibration["level"]},
    }


def world_maps_payload(path: Path | None = None) -> dict:
    """读取并校验导入产物；缺失或损坏时抛 ValueError，由路由转成可重试的错误。"""
    target = path or (static_dir() / MAP_MANIFEST_NAME)
    try:
        stat = target.stat()
    except OSError as exc:
        raise ValueError(f"世界地图清单不可用：{exc}") from exc
    signature = (stat.st_mtime_ns, stat.st_size)
    cached = _MANIFEST_CACHE.get(str(target))
    if cached is not None and cached[0] == signature:
        return cached[1]
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"世界地图清单不可用：{exc}") from exc
    try:
        raw = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"世界地图清单格式无效：{exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("世界地图清单格式无效：顶层必须是对象")
    maps = raw.get("maps")
    if not isinstance(maps, dict) or not maps:
        raise ValueError("世界地图清单格式无效：maps 不能为空")
    entries = {}
    for map_id, entry in maps.items():
        if not isinstance(map_id, str) or not map_id.isdigit():
            raise ValueError("世界地图清单格式无效：地图编号必须是数字字符串")
        entries[map_id] = _map_entry(map_id, entry)
    payload = {
        "schema_version": _positive(raw.get("schema_version"), "schema_version"),
        "coordinate_version": _positive(raw.get("coordinate_version"), "coordinate_version"),
        "maps": entries,
    }
    _MANIFEST_CACHE[str(target)] = (signature, payload)
    return payload


def register_world_map_routes(app: web.Application, path: Path | None = None) -> None:
    async def get_world_maps(request: web.Request) -> web.Response:
        try:
            payload = await run_blocking(request, world_maps_payload, path)
        except ValueError as exc:
            logger.warning("世界地图清单读取失败: %s", exc)
            return web.json_response({"error": str(exc)}, status=503, headers={"Cache-Control": "no-store"})
        return web.json_response(payload, headers={"Cache-Control": "no-store"})

    app.router.add_get("/api/world-maps", get_world_maps)
