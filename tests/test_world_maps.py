"""世界地图 manifest 与底图：来源指纹、投影和校准等级必须自洽且可复现。"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import tomllib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from spritelens.web.world_maps import register_world_map_routes, world_maps_payload
from tools.import_world_maps import (
    CONFIG_PATH,
    PINNED_MAPS,
    build_manifest,
    publish,
    read_source,
    verify_projection,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "data" / "static" / "world_maps.json"
MAP_DIR = ROOT / "spritelens" / "web" / "static" / "maps"
BUILD_CONFIG_PATH = ROOT / "build_config.toml"

EXPECTED_NAMES = {"10003": "卡洛西亚大陆", "10018": "魔法学院"}
EXPECTED_PROJECTIONS = {
    "10003": (306000, 408000, 408000),
    "10018": (-886161, -891000, 180000),
}


def project(entry: dict, raw_x: int, raw_y: int) -> tuple[float, float]:
    projection = entry["projection"]
    width = entry["image"]["width"]
    height = entry["image"]["height"]
    return (
        (raw_x - projection["origin_x"]) / projection["side"] * width,
        (raw_y - projection["origin_y"]) / projection["side"] * height,
    )


class WorldMapManifestTest(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_support_table_and_calibration_levels(self):
        maps = self.manifest["maps"]
        self.assertEqual(set(maps), {"10003", "10018"})
        supported = {key for key, entry in maps.items() if entry["availability"] == "supported"}
        candidate = {key for key, entry in maps.items() if entry["availability"] == "candidate"}
        self.assertEqual(supported, {"10003"})
        self.assertEqual(candidate, {"10018"})
        for map_id, entry in maps.items():
            with self.subTest(map_id=map_id):
                self.assertEqual(entry["name"], EXPECTED_NAMES[map_id])
                calibration = entry["calibration"]
                if map_id == "10003":
                    # 大陆已用 8 个现场点完成校准，误差在计划阈值内
                    self.assertEqual(calibration["level"], "verified")
                    self.assertEqual(calibration["basis"], "field_screenshot_match")
                    self.assertEqual(calibration["orientation"], "verified_north_up")
                    self.assertEqual(calibration["checked_at"], "2026-10-26")
                    self.assertGreaterEqual(calibration["field_points"], 5)
                    self.assertGreater(calibration["mean_error_px"], 0)
                    self.assertLessEqual(calibration["max_error_px"], 8)
                else:
                    # 学院尚未现场校准，不得写 verified，也不得套用大陆参数
                    self.assertEqual(calibration["level"], "candidate")
                    self.assertEqual(calibration["basis"], "static_import")
                    self.assertEqual(calibration["field_points"], 0)
                    self.assertEqual(calibration["orientation"], "unverified")

    def test_schema_and_coordinate_versions(self):
        self.assertEqual(self.manifest["schema_version"], 1)
        self.assertEqual(self.manifest["coordinate_version"], 1)
        self.assertEqual(self.manifest["dataset"], "roco_resources")
        self.assertEqual(self.manifest["generated_by"], "tools/import_world_maps.py")

    def test_source_fingerprints_are_relative_and_recorded(self):
        source = self.manifest["source"]
        self.assertEqual(source["config"]["path"], "runtime_assets/desktop-data.json")
        self.assertEqual(len(source["config"]["sha256"]), 64)
        for map_id, image in self.manifest["maps"].items():
            with self.subTest(map_id=map_id):
                record = source["maps"][map_id]
                self.assertFalse(Path(record["path"]).is_absolute(), record["path"])
                self.assertEqual(len(record["sha256"]), 64)
                # 原图直接入库、不转码，所以来源哈希与产物哈希一致
                self.assertEqual(record["sha256"], image["image"]["sha256"])
                self.assertEqual(record["bytes"], image["image"]["bytes"])

    def test_projection_parameters_are_pinned_per_map(self):
        for map_id, (origin_x, origin_y, side) in EXPECTED_PROJECTIONS.items():
            with self.subTest(map_id=map_id):
                entry = self.manifest["maps"][map_id]
                projection = entry["projection"]
                self.assertEqual(projection["kind"], "origin_side_normalized")
                self.assertEqual(
                    (projection["origin_x"], projection["origin_y"], projection["side"]),
                    (origin_x, origin_y, side),
                )
                self.assertEqual(entry["coordinate_system"]["image_pixel_origin"], "top_left")
        # 学院地图必须独立校准，不能套用大陆的原点与边长
        self.assertNotEqual(
            self.manifest["maps"]["10018"]["projection"]["origin_x"],
            self.manifest["maps"]["10003"]["projection"]["origin_x"],
        )
        self.assertNotEqual(
            self.manifest["maps"]["10018"]["projection"]["side"],
            self.manifest["maps"]["10003"]["projection"]["side"],
        )

    def test_images_exist_match_manifest_and_decode(self):
        for map_id, entry in self.manifest["maps"].items():
            with self.subTest(map_id=map_id):
                image = entry["image"]
                self.assertEqual(image["url"], "/static/" + image["asset"])
                path = MAP_DIR / f"{map_id}.webp"
                self.assertTrue(path.is_file(), path)
                data = path.read_bytes()
                self.assertEqual(len(data), image["bytes"])
                self.assertEqual(hashlib.sha256(data).hexdigest(), image["sha256"])
                with Image.open(path) as decoded:
                    self.assertEqual(decoded.format, "WEBP")
                    self.assertEqual(decoded.size, (4096, 4096))
                    self.assertEqual(decoded.size, (image["width"], image["height"]))

    def test_projection_maps_origin_edges_center_and_holdout(self):
        for map_id, entry in self.manifest["maps"].items():
            origin_x, origin_y, side = EXPECTED_PROJECTIONS[map_id]
            width = entry["image"]["width"]
            height = entry["image"]["height"]
            checks = {
                "origin": ((origin_x, origin_y), (0.0, 0.0)),
                "right_edge": ((origin_x + side, origin_y), (float(width), 0.0)),
                "bottom_edge": ((origin_x, origin_y + side), (0.0, float(height))),
                "far_corner": ((origin_x + side, origin_y + side), (float(width), float(height))),
                "center": ((origin_x + side // 2, origin_y + side // 2), (width / 2, height / 2)),
                # 留出点：不参与拟合，只按固定投影核对
                "holdout": ((origin_x + side // 4, origin_y + side * 3 // 4), (width / 4, height * 0.75)),
            }
            for label, (raw, expected) in checks.items():
                with self.subTest(map_id=map_id, check=label):
                    actual = project(entry, *raw)
                    self.assertTrue(math.isclose(actual[0], expected[0], abs_tol=1e-6), (label, actual))
                    self.assertTrue(math.isclose(actual[1], expected[1], abs_tol=1e-6), (label, actual))

    def test_negative_origin_projects_without_clamping(self):
        entry = self.manifest["maps"]["10018"]
        origin_x, origin_y, side = EXPECTED_PROJECTIONS["10018"]
        # 原点为负的世界坐标仍应落到图内
        self.assertEqual(project(entry, origin_x + side // 2, origin_y + side // 2), (2048.0, 2048.0))
        # 超出范围不得静默钳制到边缘，交给调用方拒绝
        below = project(entry, origin_x - side // 2, origin_y)
        above = project(entry, origin_x + side * 2, origin_y + side * 2)
        self.assertLess(below[0], 0)
        self.assertGreater(above[0], entry["image"]["width"])
        self.assertGreater(above[1], entry["image"]["height"])


class WorldMapToolTest(unittest.TestCase):
    """导入工具的失败分支：坏来源必须报错，且不得写出半份产物。"""

    def _write_source(self, root: Path, *, origin_x: int = 306000) -> None:
        config = {"maps": {}, "scene_res": {}}
        for map_id, pinned in PINNED_MAPS.items():
            config["maps"][map_id] = {
                "ox": origin_x if map_id == "10003" else pinned["origin"][0],
                "oy": pinned["origin"][1],
                "side": pinned["side"],
                "world": True,
            }
            config["scene_res"][map_id] = {"n": EXPECTED_NAMES[map_id], "s": 103}
            image_path = root / pinned["path"]
            image_path.parent.mkdir(parents=True, exist_ok=True)
            image_path.write_bytes(b"not-a-webp")
        config_path = root / "runtime_assets" / "desktop-data.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(config), encoding="utf-8")

    def test_missing_source_file_fails(self):
        with TemporaryDirectory() as directory:
            with self.assertRaises(ValueError) as caught:
                read_source(Path(directory), CONFIG_PATH)
        self.assertIn("缺少来源文件", str(caught.exception))

    def test_changed_projection_parameters_fail(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_source(root, origin_x=306001)
            config = (root / "runtime_assets" / "desktop-data.json").read_bytes()
            with self.assertRaises(ValueError) as caught:
                build_manifest(config, root)
        self.assertIn("坐标参数与固定版本不符", str(caught.exception))

    def test_image_hash_mismatch_fails(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_source(root)
            config = (root / "runtime_assets" / "desktop-data.json").read_bytes()
            with self.assertRaises(ValueError) as caught:
                build_manifest(config, root)
        self.assertIn("底图内容与固定版本不符", str(caught.exception))

    def test_verify_projection_rejects_tampered_origin(self):
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        entry = copy.deepcopy(manifest["maps"]["10003"])
        entry["projection"]["origin_x"] += 1000
        with self.assertRaises(ValueError):
            verify_projection("10003", entry)

    def test_publish_skips_identical_files_and_stages_new_ones(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / "10003.webp"
            publish({target: b"same"})
            self.assertEqual(target.read_bytes(), b"same")
            before = target.stat().st_mtime_ns
            publish({target: b"same"})
            self.assertEqual(target.stat().st_mtime_ns, before)
            self.assertEqual(list(Path(directory).glob(".*.importing")), [])

    def test_publish_failure_keeps_previous_product(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            product = root / "old.webp"
            product.write_bytes(b"old")
            blocker = root / "blocked"
            blocker.write_bytes(b"not-a-directory")
            with self.assertRaises(OSError):
                publish({blocker / "x.webp": b"new", product: b"new"})
            self.assertEqual(product.read_bytes(), b"old")
            self.assertEqual(list(root.glob(".*.importing")), [])

    def test_publish_rolls_back_when_later_replace_fails(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            old, new, last = root / "a", root / "b", root / "c"
            old.write_bytes(b"old-a"); last.write_bytes(b"old-c")
            original = os.replace
            count = 0
            def fail_third(source, target):
                nonlocal count
                count += 1
                if count == 3:
                    raise OSError("injected replace failure")
                return original(source, target)
            with patch("tools.import_world_maps.os.replace", side_effect=fail_third):
                with self.assertRaises(OSError):
                    publish({old: b"new-a", new: b"new-b", last: b"new-c"})
            self.assertEqual(old.read_bytes(), b"old-a")
            self.assertFalse(new.exists())
            self.assertEqual(last.read_bytes(), b"old-c")
            self.assertEqual(list(root.glob(".*.importing")), [])
            self.assertEqual(list(root.glob(".*.rollback")), [])

    def test_publish_cleans_partial_stage_write(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "map.webp"
            target.write_bytes(b"old")
            original = Path.write_bytes
            def partial(path, data):
                if path.suffix == ".importing":
                    original(path, b"partial")
                    raise OSError("injected stage failure")
                return original(path, data)
            with patch.object(Path, "write_bytes", partial):
                with self.assertRaises(OSError):
                    publish({target: b"new"})
            self.assertEqual(target.read_bytes(), b"old")
            self.assertEqual(list(root.glob(".*.importing")), [])

    def test_publish_preserves_backup_if_rollback_fails(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = root / "a", root / "b"
            first.write_bytes(b"old-a"); second.write_bytes(b"old-b")
            original = os.replace
            count = 0
            def fail_replace_and_rollback(source, target):
                nonlocal count
                count += 1
                if count in (2, 3):
                    raise OSError("injected failure")
                return original(source, target)
            with patch("tools.import_world_maps.os.replace", side_effect=fail_replace_and_rollback):
                with self.assertRaisesRegex(RuntimeError, "回滚不完整"):
                    publish({first: b"new-a", second: b"new-b"})
            backups = list(root.glob(".a.*.rollback"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), b"old-a")
            self.assertEqual(second.read_bytes(), b"old-b")
            self.assertEqual(list(root.glob(".*.importing")), [])


class WorldMapPackagingTest(unittest.TestCase):
    def test_build_includes_whole_static_dir(self):
        with BUILD_CONFIG_PATH.open("rb") as handle:
            config = tomllib.load(handle)
        include_dirs = {
            tuple(item.split("=", 1)) for item in config.get("include_data_dirs", [])
        }
        self.assertIn(("spritelens/web/static", "spritelens/web/static"), include_dirs)


class WorldMapPayloadTest(unittest.TestCase):
    """运行时接口只下发前端画图所需字段，导入台账与来源细节不进入载荷。"""

    def test_payload_matches_manifest_runtime_subset(self):
        payload = world_maps_payload(MANIFEST_PATH)
        raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], raw["schema_version"])
        self.assertEqual(payload["coordinate_version"], raw["coordinate_version"])
        self.assertEqual(set(payload["maps"]), set(EXPECTED_NAMES))
        self.assertEqual(set(payload), {"schema_version", "coordinate_version", "maps"})
        for map_id, entry in payload["maps"].items():
            source = raw["maps"][map_id]
            self.assertEqual(entry["name"], EXPECTED_NAMES[map_id])
            self.assertEqual(entry["availability"], source["availability"])
            self.assertEqual(entry["calibration"], {"level": source["calibration"]["level"]})
            self.assertEqual(entry["image"], {
                "url": source["image"]["url"],
                "width": source["image"]["width"],
                "height": source["image"]["height"],
            })
            self.assertEqual(entry["projection"], {
                "origin_x": EXPECTED_PROJECTIONS[map_id][0],
                "origin_y": EXPECTED_PROJECTIONS[map_id][1],
                "side": EXPECTED_PROJECTIONS[map_id][2],
            })
            self.assertNotIn("notes", entry)

    def test_payload_fails_without_manifest(self):
        with TemporaryDirectory() as directory:
            with self.assertRaises(ValueError) as caught:
                world_maps_payload(Path(directory) / "world_maps.json")
        self.assertIn("世界地图清单不可用", str(caught.exception))

    def test_payload_rejects_broken_entries(self):
        valid = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        mutations = {
            "availability": lambda manifest: manifest["maps"]["10003"].update(availability="ready"),
            "calibration": lambda manifest: manifest["maps"]["10003"].update(calibration={"level": "maybe"}),
            "image": lambda manifest: manifest["maps"]["10003"]["image"].update(url=""),
            "version": lambda manifest: manifest.update(coordinate_version="1"),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), TemporaryDirectory() as directory:
                broken = copy.deepcopy(valid)
                mutate(broken)
                path = Path(directory) / "world_maps.json"
                path.write_text(json.dumps(broken, ensure_ascii=False), encoding="utf-8")
                with self.assertRaises(ValueError):
                    world_maps_payload(path)


class WorldMapRouteTest(unittest.IsolatedAsyncioTestCase):
    async def test_route_serves_catalog_without_cache(self):
        app = web.Application()
        register_world_map_routes(app, MANIFEST_PATH)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            response = await client.get("/api/world-maps")
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            body = await response.json()
            self.assertEqual(set(body["maps"]), set(EXPECTED_NAMES))
            self.assertEqual(body["maps"]["10003"]["image"]["url"], "/static/maps/10003.webp")
            self.assertEqual(body["maps"]["10003"]["projection"], {
                "origin_x": 306000, "origin_y": 408000, "side": 408000,
            })
        finally:
            await client.close()

    async def test_route_reports_unavailable_manifest(self):
        with TemporaryDirectory() as directory:
            app = web.Application()
            register_world_map_routes(app, Path(directory) / "world_maps.json")
            client = TestClient(TestServer(app))
            await client.start_server()
            try:
                response = await client.get("/api/world-maps")
                self.assertEqual(response.status, 503)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertIn("世界地图清单不可用", (await response.json())["error"])
            finally:
                await client.close()


if __name__ == "__main__":
    unittest.main()
