"""搜索覆盖历史的归属、落盘及失败恢复。"""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from spritelens.repositories.scene_coverage_store import SceneCoverageStore
from spritelens.services.scene_coverage import EXTERNAL_WORLD_TTL_SECONDS, SceneCoverage


class CoverageStoreTest(unittest.TestCase):
    def test_incremental_rows_match_cells_after_load_clear_and_account_switch(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SceneCoverageStore(Path(tmp) / "coverage.json")
            coverage = SceneCoverage(radius_raw=2500, store=store)
            coverage.select_account(1)
            for point in ((-4000, -1000), (0, 0), (4000, 0), (0, 4000)):
                coverage.record(10003, point)
                rows = coverage.snapshot(10003).rows
                decoded = {(gy, gx) for gy, start, length in rows for gx in range(start, start + length)}
                self.assertEqual(decoded, coverage._cells[(0, 10003)])
            store.flush()
            expected = coverage.snapshot(10003).rows
            coverage.select_account(2)
            coverage.record(10003, (100000, 100000))
            coverage.select_account(1)
            self.assertEqual(coverage.snapshot(10003).rows, expected)
            coverage.record(10003, (8000, 0))
            rows = coverage.snapshot(10003).rows
            self.assertEqual({(gy, gx) for gy, start, length in rows for gx in range(start, start + length)}, coverage._cells[(0, 10003)])
            coverage.clear(10003)
            coverage.record(10003, (20000, 20000))
            rows = coverage.snapshot(10003).rows
            self.assertEqual({(gy, gx) for gy, start, length in rows for gx in range(start, start + length)}, coverage._cells[(0, 10003)])
            store.close()

    def test_restart_isolates_accounts_maps_and_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "coverage.json"
            store = SceneCoverageStore(path)
            first = SceneCoverage(radius_raw=500, store=store)
            first.select_account(1)
            first.record(10003, (500, 500))
            first.record(10018, (2500, 500))
            second = SceneCoverage(radius_raw=500, store=store)
            second.select_account(2)
            second.record(10003, (4500, 500))
            expected = first.snapshot(10003).rows
            store.close()

            store = SceneCoverageStore(path)
            restored = SceneCoverage(enabled=False, store=store)
            restored.select_account(1)
            self.assertEqual(restored.snapshot(10003).rows, expected)
            self.assertIsNotNone(restored.snapshot(10018))
            self.assertFalse(restored.record(10003, (9999, 9999)))
            restored.clear(10003)
            store.flush()
            restored.select_account(2)
            self.assertIsNotNone(restored.snapshot(10003))
            store.close()

            store = SceneCoverageStore(path)
            restored = SceneCoverage(enabled=False, store=store)
            restored.select_account(1)
            self.assertIsNone(restored.snapshot(10003))
            self.assertIsNotNone(restored.snapshot(10018))
            store.close()

    def test_full_map_exceeds_old_limit_and_radius_changes_cannot_mix(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "coverage.json"
            store = SceneCoverageStore(path)
            store.put(1, 10003, {"coordinate_version": 1, "cell_size": 2000, "radius": 8000,
                "updated_at": 1, "rows": [[y, 0, 204] for y in range(204)]})
            store.close()
            store = SceneCoverageStore(path)
            coverage = SceneCoverage(radius_raw=10000, store=store)
            coverage.select_account(1)
            self.assertEqual(coverage.snapshot(10003).cells, 41616)
            self.assertFalse(coverage.record(10003, (1000, 1000)))
            self.assertIn("半径已变化", coverage.error)
            store.close()

    def test_history_not_exposed_without_compatible_map_and_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "coverage.json"
            store = SceneCoverageStore(path)
            coverage = SceneCoverage(radius_raw=500, store=store)
            coverage.select_account(1)
            coverage.record(10003, (500, 500))
            store.close()
            original = path.read_bytes()

            store = SceneCoverageStore(path)
            unsupported = SceneCoverage(enabled=False, store=store, map_bounds={})
            unsupported.select_account(1)
            self.assertIsNone(unsupported.snapshot(10003))
            self.assertIn("历史搜索记录已保留", unsupported.unavailable_reason(10003))
            store.close()
            self.assertEqual(path.read_bytes(), original)

            store = SceneCoverageStore(path)
            supported = SceneCoverage(enabled=False, store=store, map_bounds={10003: (0, 0, 10000)})
            supported.select_account(1)
            self.assertIsNotNone(supported.snapshot(10003))
            store.close()

    def test_failed_write_is_reported_and_retried_without_losing_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "coverage.json"
            store = SceneCoverageStore(path)
            attempted = threading.Event()
            def fail_once(source, target):
                attempted.set()
                raise OSError("injected failure")
            with patch.object(Path, "replace", fail_once):
                store.put(1, 2, {"coordinate_version": 1, "cell_size": 2000, "radius": 8000,
                    "updated_at": 1, "rows": [[0, 0, 1]]})
                self.assertTrue(attempted.wait(2))
                with self.assertRaises(TimeoutError):
                    store.flush(timeout=0.1)
                self.assertIsNotNone(store.error)
            store.flush(timeout=3)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["records"][0]["uid"], 1)
            self.assertIsNone(store.error)
            store.close()

    def test_clear_waits_for_inflight_write_and_old_coverage_does_not_return(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "coverage.json"
            store = SceneCoverageStore(path)
            started, release = threading.Event(), threading.Event()
            original = Path.replace
            def blocked(source, target):
                started.set()
                if not release.wait(3):
                    raise OSError("等待测试释放超时")
                return original(source, target)
            with patch.object(Path, "replace", blocked):
                coverage = SceneCoverage(radius_raw=500, store=store)
                coverage.select_account(1)
                coverage.record(10003, (500, 500))
                self.assertTrue(started.wait(2))
                coverage.clear(10003)
                with self.assertRaises(TimeoutError):
                    store.flush(timeout=0.1)
                release.set()
                store.flush(timeout=3)
            store.close()
            reopened = SceneCoverageStore(path)
            self.assertIsNone(reopened.load(1, 10003))
            reopened.close()

    def test_world_owner_buckets_isolate_and_persist(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "coverage.json"
            store = SceneCoverageStore(path)
            coverage = SceneCoverage(radius_raw=500, store=store)
            coverage.select_account(1)
            coverage.record(10003, (500, 500))
            own = coverage.snapshot(10003)
            self.assertEqual(own.owner, 0)
            # 他人世界是另一份进度：看不到也写不进自己的桶。
            self.assertTrue(coverage.select_owner(369460069))
            self.assertIsNone(coverage.snapshot(10003))
            coverage.record(10003, (100500, 500))
            external = coverage.snapshot(10003)
            self.assertEqual(external.owner, 369460069)
            self.assertNotEqual(external.rows, own.rows)
            # 切回自己的世界，原进度不变。
            coverage.select_owner(0)
            self.assertEqual(coverage.snapshot(10003).rows, own.rows)
            store.flush()
            store.close()

            store = SceneCoverageStore(path)
            restored = SceneCoverage(enabled=False, store=store)
            restored.select_account(1)
            self.assertEqual(restored.snapshot(10003).cells, own.cells)
            restored.select_owner(369460069)
            self.assertEqual(restored.snapshot(10003).cells, external.cells)
            store.close()

    def test_external_world_progress_expires_three_days_after_first_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "coverage.json"
            now = time.time()
            # 关键：保留期从开始记录时间算，最近才写入也不会延长。
            row = {"coordinate_version": 1, "cell_size": 2000, "radius": 500,
                   "updated_at": now - 60, "started_at": now - EXTERNAL_WORLD_TTL_SECONDS - 60,
                   "rows": [[0, 0, 2]]}
            store = SceneCoverageStore(path)
            store.put(1, 10003, dict(row), owner=369460069)
            store.put(1, 10003, dict(row), owner=0)
            # 启动清理：从开始记录算已满 3 天的他人世界记录被删掉，自己的世界长期保留。
            SceneCoverage(radius_raw=500, store=store)
            store.flush()
            self.assertIsNone(store.load(1, 10003, 369460069))
            self.assertIsNotNone(store.load(1, 10003, 0))

            # 运行中：从开始记录算满 3 天即清除，之后重新记录会重新计时。
            coverage = SceneCoverage(radius_raw=500, store=store)
            coverage.select_account(1)
            coverage.select_owner(369460069)
            coverage.record(10003, (500, 500))
            started = coverage._started[(369460069, 10003)]
            self.assertIsNotNone(coverage.snapshot(10003))
            self.assertEqual(coverage.purge_expired(now=started + EXTERNAL_WORLD_TTL_SECONDS - 60), 0)
            # 继续记录不延长保留期。
            coverage.record(10003, (9000, 9000))
            self.assertEqual(coverage.purge_expired(now=started + EXTERNAL_WORLD_TTL_SECONDS + 1), 1)
            self.assertIsNone(coverage.snapshot(10003))
            store.flush()
            self.assertIsNone(store.load(1, 10003, 369460069))
            self.assertIsNotNone(store.load(1, 10003, 0))
            self.assertTrue(coverage.record(10003, (500, 500)))
            self.assertGreater(coverage.snapshot(10003).cells, 0)
            self.assertGreater(coverage._started[(369460069, 10003)], started)
            store.close()

    def test_version_one_file_loads_as_own_world(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "coverage.json"
            path.write_text(json.dumps({"version": 1, "records": [{"uid": 1, "map_id": 10003,
                "coordinate_version": 1, "cell_size": 2000, "radius": 500, "updated_at": 1,
                "rows": [[0, 0, 2]]}]}), encoding="utf-8")
            store = SceneCoverageStore(path)
            self.assertIsNotNone(store.load(1, 10003, 0))
            self.assertIsNone(store.load(1, 10003, 369460069))
            store.close()

    def test_bad_existing_file_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "coverage.json"
            path.write_text('{"version":1,"records":[{}]}', encoding="utf-8")
            original = path.read_bytes()
            with self.assertRaises(ValueError):
                SceneCoverageStore(path)
            self.assertEqual(path.read_bytes(), original)
