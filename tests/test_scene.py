"""C02 合成协议、归属与生命周期回归，不含本机流量样本。"""
from __future__ import annotations

import tempfile
import unittest
from urllib.request import Request, urlopen
from dataclasses import replace
import os
from pathlib import Path
from unittest.mock import patch

from spritelens.app_context import build_app_context
from spritelens.capture.base import StreamChunk
from spritelens.capture.key_store import KeyStore
from spritelens.events import PacketEvent
from spritelens.domain.scene import integer, removed_ids
from spritelens.domain.static_data import load_static_data
from spritelens.services.account_selection_service import AccountSelectionService
from spritelens.protocol.frames import CMD_SYN
from spritelens.paths import schema_dir, static_dir
from spritelens.protocol.opcodes import OpcodeCatalog
from spritelens.protocol.schema import load_library
from spritelens.recording.recorder import StreamRecorder, read_recording
from spritelens.recording.replay import ReplaySource
from spritelens.services.capture_service import CaptureService
from spritelens.services.monitor_service import MonitorService
from spritelens.services.scene_coverage import DEFAULT_CELL_SIZE_RAW, SceneCoverage
from spritelens.repositories.scene_coverage_store import SceneCoverageStore
from spritelens.services.scene_repository import SceneRepository
from spritelens.web.nearby import DEBUG_COORDINATES_ENV, nearby_payload
from spritelens.web.server import LocalServer
from tests._synth import SYNTH_KEY, make_ack_frame, make_data_frame, encode_frame
from tests.test_account_selection import _Store, _PetRepository, _Repo
from tests.test_web_server import _make_context, _http_get, _http_post


def field(no, raw=None, children=None):
    result = {"no": no, "raw": raw}
    if children is not None: result["children"] = children
    return result


def event(opcode, fields=(), *, uid=None, session="s", direction="s2c"):
    return PacketEvent(1.0, session, direction, opcode, "synthetic", 0, list(fields),
                       (uid, "synthetic", 1) if uid is not None else None)


def actor_node(actor_id=9007199254740993, *, measurements=True, x=0, y=-3, mutation=None):
    config = [field(1, 123)]
    if measurements: config.extend([field(11, 100), field(12, 200), field(31, (1 << 64) - 20)])
    if mutation is not None: config.append(field(14, mutation))
    return field(7, children=[field(11, children=[
        field(1, children=[field(2, actor_id), field(11, 5),
            field(8, children=[field(1, children=[field(1, x), field(2, y)])])]),
        field(3, children=config)])])


def seed(repo, uid=101, session="s"):
    repo.handle_packet(event(0x0152, [field(2, 1), field(3, 2), field(4, 3)], uid=uid, session=session))


class SceneTests(unittest.TestCase):
    def test_coverage_records_past_samples_but_not_future_targets_and_survives_battle(self):
        repo = SceneRepository(); seed(repo)
        point = lambda x, y: [field(1, x), field(2, y)]
        segments = [field(12, children=[field(1, children=point(320000, 420000)), field(2, 900)]),
                    field(12, children=[field(1, children=point(600000, 700000)), field(2, 1100)])]
        repo.handle_packet(event(0x0133, [field(1, 1000), field(17, 1), field(2, children=point(650000, 750000)), *segments], direction="c2s"))
        current = repo.snapshot()
        self.assertEqual(current.position_source, "client_sample")
        self.assertEqual(current.player_position[:2], (320000, 420000))
        # 只记采样所在格：cell=2000 → gx=160、gy=210；请求时刻之后的分段与
        # 计划目标 (650000, 750000) 都不入覆盖。
        coverage = current.coverage
        self.assertEqual((coverage.cell_size, coverage.cells, coverage.revision), (2000, 1, 1))
        self.assertEqual(coverage.rows, ((210, 160, 1),))
        repo.handle_packet(event(4886))
        self.assertEqual(repo.snapshot().coverage, coverage)
        self.assertIsNone(repo.snapshot().player_position)
        self.assertFalse(repo.snapshot().actors)
        seed(repo, uid=102)
        self.assertIsNone(repo.snapshot().coverage)

    def test_coverage_records_confirmed_continuous_move_samples(self):
        """连续移动请求本身就是走过路径的证据：只有相邻请求相容才记格。"""
        repo = SceneRepository(); seed(repo)

        def move(t, x, y):
            return event(0x0133, [field(1, t), field(17, 1),
                field(2, children=[field(1, x), field(2, y)])], direction="c2s")

        repo.handle_packet(move(1000, 320000, 420000))
        self.assertIsNone(repo.snapshot().coverage)  # 第一条只作为基准位置
        repo.handle_packet(move(1100, 320150, 420000))
        coverage = repo.snapshot().coverage
        self.assertEqual((coverage.cells, coverage.revision), (1, 1))
        self.assertEqual(coverage.rows, ((210, 160, 1),))
        # 远距离跳变（传送/脱战回位/重算路线）不记格，只更新基准位置。
        repo.handle_packet(move(1200, 900000, 900000))
        self.assertEqual(repo.snapshot().coverage, coverage)
        repo.handle_packet(move(1300, 900150, 900000))
        self.assertEqual(repo.snapshot().coverage.cells, 2)
        # 间隔过久同样只更新基准，不把中间没走过的区域补成已探索。
        repo.handle_packet(move(5000, 900300, 900000))
        self.assertEqual(repo.snapshot().coverage.cells, 2)

    def test_coverage_records_move_samples_again_right_after_clear(self):
        """清除足迹后继续跑动应立即重新出格，不必等到下一个停止点。"""
        repo = SceneRepository(); seed(repo)

        def move(t, x, y):
            return event(0x0133, [field(1, t), field(17, 1),
                field(2, children=[field(1, x), field(2, y)])], direction="c2s")

        repo.handle_packet(move(1000, 321900, 420000))
        repo.handle_packet(move(1100, 322100, 420000))
        before = repo.snapshot()
        self.assertIsNotNone(before.coverage)
        self.assertTrue(repo.reset_coverage(before.uid, before.resource_id, before.observation_id))
        self.assertIsNone(repo.snapshot().coverage)
        repo.handle_packet(move(1200, 322300, 420000))
        self.assertEqual(repo.snapshot().coverage.rows, ((210, 161, 1),))

    def test_coverage_is_recorded_without_opening_map_and_returning_to_map_keeps_it(self):
        repo = SceneRepository(); seed(repo)
        repo.handle_packet(event(0x014A, [actor_node(7, x=320000, y=420000)]))
        self.assertIsNone(repo.snapshot().coverage)
        repo.handle_packet(event(0x0133, [field(1, 1000), field(8, 1), field(17, 1),
            field(2, children=[field(1, 320000), field(2, 420000)])], direction="c2s"))
        before = repo.snapshot().coverage
        self.assertIsNotNone(before)
        repo.handle_packet(event(0x0152, [field(2, 2), field(3, 3), field(4, 4)]))
        self.assertIsNone(repo.snapshot().coverage)
        repo.handle_packet(event(0x0152, [field(2, 1), field(3, 2), field(4, 3)]))
        self.assertEqual(repo.snapshot().coverage, before)

    def test_midstream_rebuild_without_checkpoint_or_initial_scene(self):
        repo = SceneRepository()
        move = replace(event(0x0133, [field(17, 103), field(2, children=[field(1, 100), field(2, 200)])], direction="c2s"),
                       resumed_identity=(101, "synthetic", 1))
        repo.handle_packet(replace(move, resumed_identity=None))
        self.assertIsNone(repo.snapshot().scene_id)
        repo.handle_packet(move)
        self.assertEqual(repo.snapshot().scene_id, 103)
        add = field(1, children=[field(1, children=[field(1, children=actor_node(7, x=120, y=220)["children"])])])
        repo.handle_packet(event(0x0414, [add]))
        self.assertEqual(repo.snapshot().phase, "observing")
        self.assertEqual([a.actor_id for a in repo.snapshot().actors], [7])
        foreign = replace(move, session_id="other", resumed_identity=None)
        repo.handle_packet(foreign)
        self.assertEqual([a.actor_id for a in repo.snapshot().actors], [7])
        repo.handle_packet(event(0x0414, [field(1, children=[field(2, children=[field(1, 7)])])]))
        self.assertFalse(repo.snapshot().actors)

    def test_coverage_uses_configured_cell_size_and_ignores_npc_positions(self):
        repo = SceneRepository(coverage_cell_raw=1000); seed(repo)
        repo.handle_packet(event(0x014A, [actor_node(7, x=600000, y=700000)]))
        self.assertIsNone(repo.snapshot().coverage)
        repo.handle_packet(event(0x0133, [field(1, 1000), field(8, 1), field(17, 1),
            field(2, children=[field(1, 320000), field(2, 420000)])], direction="c2s"))
        coverage = repo.snapshot().coverage
        self.assertEqual(coverage.cell_size, 1000)
        self.assertEqual(coverage.cells, 1)
        self.assertEqual(coverage.rows, ((420, 320, 1),))

    def test_coverage_grid_merges_runs_and_floors_negative_coordinates(self):
        coverage = SceneCoverage()
        coverage.select_account(101)
        coverage.record(1, None)
        coverage.record(None, (0, 0))
        self.assertIsNone(coverage.snapshot(1))
        for point in ((0, 0), (1999, 0), (2000, 0), (-2001, -1), (4000, -1)):
            coverage.record(1, point)
        snapshot = coverage.snapshot(1)
        self.assertEqual(snapshot.cell_size, DEFAULT_CELL_SIZE_RAW)
        self.assertEqual(snapshot.cells, 4)
        # gy=-1 的 gx=-2 与 gx=2 中间缺格，不能合并；gy=0 的 gx=0..1 连续合并。
        self.assertEqual(snapshot.rows, ((-1, -2, 1), (-1, 2, 1), (0, 0, 2)))
        self.assertEqual(snapshot.revision, 4)
        coverage.select_account(102)
        self.assertIsNone(coverage.snapshot(1))

    def test_coverage_expands_to_observation_radius(self):
        """覆盖记「采样点 + 观察半径」交集到的格：雷达看得到多远，就记多远。"""
        coverage = SceneCoverage(cell_size=1000, radius_raw=500)
        coverage.select_account(101)
        self.assertTrue(coverage.record(1, (500, 500)))
        snapshot = coverage.snapshot(1)
        # 四个边界相切格都计入，四个斜角最近点距离约 707，不计。
        self.assertEqual(snapshot.cells, 5)
        self.assertEqual(snapshot.rows, ((-1, 0, 1), (0, -1, 3), (1, 0, 1)))
        self.assertEqual(snapshot.revision, 1)
        # 同一观察圆内的下一次采样没有新格：不重算、不推进版本。
        self.assertFalse(coverage.record(1, (520, 500)))
        self.assertEqual(coverage.snapshot(1).revision, 1)
        # 半径 0 只记采样所在格（无配置或测试场景）。
        single = SceneCoverage(cell_size=1000)
        single.select_account(101)
        single.record(1, (500, 500))
        self.assertEqual((single.snapshot(1).cells, single.snapshot(1).rows), (1, ((0, 0, 1),)))

    def test_coverage_circle_touches_grid_corner_with_negative_coordinates(self):
        coverage = SceneCoverage(cell_size=1000, radius_raw=500)
        coverage.select_account(101)
        coverage.record(1, (-300, -400))
        cells = {(y, x) for y, x, length in coverage.snapshot(1).rows for x in range(x, x + length)}
        # 圆经过原点，四个围绕原点的格均包含该交点。
        self.assertTrue({(-1, -1), (-1, 0), (0, -1), (0, 0)} <= cells)

    def test_coverage_clips_map_bounds_and_rejects_unsupported_map(self):
        coverage = SceneCoverage(cell_size=1000, radius_raw=500, map_bounds={1: (0, 0, 3000)})
        coverage.select_account(101)
        self.assertFalse(coverage.record(2, (100, 100)))
        self.assertFalse(coverage.record(1, (-1, 100)))
        self.assertTrue(coverage.record(1, (100, 100)))
        self.assertEqual(coverage.snapshot(1).rows, ((0, 0, 1),))
        self.assertTrue(coverage.record(1, (2900, 2900)))
        self.assertEqual(coverage.snapshot(1).rows, ((0, 0, 1), (2, 2, 1)))

    def test_coverage_radius_comes_from_repository_configuration(self):
        """应用装配把雷达观察半径传给覆盖，避免看得见却只记一格。"""
        repo = SceneRepository(coverage_cell_raw=1000, coverage_radius_raw=2000)
        seed(repo)
        repo.handle_packet(event(0x0133, [field(1, 1000), field(8, 1), field(17, 1),
            field(2, children=[field(1, 320000), field(2, 420000)])], direction="c2s"))
        coverage = repo.snapshot().coverage
        self.assertGreater(coverage.cells, 1)
        self.assertEqual(sum(run for _, _, run in coverage.rows), coverage.cells)

    def test_coverage_clear_scopes_to_one_map_and_revision_restarts(self):
        coverage = SceneCoverage()
        coverage.select_account(101)
        coverage.record(1, (0, 0))
        coverage.record(2, (0, 0))
        coverage.record(2, (2000, 0))
        coverage.clear(1)
        self.assertIsNone(coverage.snapshot(1))
        self.assertEqual(coverage.snapshot(2).cells, 2)
        # 清空后重新记录从 revision 1 开始，前端不会把新足迹当成旧足迹的延续。
        coverage.record(1, (0, 0))
        restarted = coverage.snapshot(1)
        self.assertEqual((restarted.cells, restarted.revision), (1, 1))
        # 支持清空全部地图，供将来整账号重置复用；当前路由只清当前地图。
        coverage.clear()
        self.assertIsNone(coverage.snapshot(1))
        self.assertIsNone(coverage.snapshot(2))

    def test_reset_coverage_clears_only_footprint_and_bumps_version(self):
        repo = SceneRepository(); seed(repo)
        repo.handle_packet(event(0x014A, [actor_node(7, x=320000, y=420000)]))
        sample = [field(1, 1000), field(8, 1), field(17, 1),
                  field(2, children=[field(1, 320000), field(2, 420000)])]
        repo.handle_packet(event(0x0133, sample, direction="c2s"))
        before = repo.snapshot()
        self.assertIsNotNone(before.coverage)
        self.assertFalse(repo.reset_coverage(before.uid, before.resource_id, before.observation_id + 1))
        self.assertIsNotNone(repo.snapshot().coverage)
        self.assertTrue(repo.reset_coverage(before.uid, before.resource_id, before.observation_id))
        after = repo.snapshot()
        self.assertIsNone(after.coverage)
        self.assertEqual(after.actors, before.actors)
        self.assertEqual(after.phase, before.phase)
        self.assertGreater(after.version, before.version)
        # 清零只是覆盖层：同一位置再次上报仍能重新记录足迹。
        repo.handle_packet(event(0x0133, sample, direction="c2s"))
        self.assertEqual(repo.snapshot().coverage.cells, 1)

    def test_persisted_coverage_restored_while_new_recording_is_paused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "coverage.json"
            store = SceneCoverageStore(path)
            repo = SceneRepository(coverage_radius_raw=1000, coverage_store=store)
            seed(repo)
            repo.handle_packet(event(0x0133, [field(1, 1000), field(8, 1), field(17, 1),
                field(2, children=[field(1, 320000), field(2, 420000)])], direction="c2s"))
            before = repo.snapshot().coverage
            store.close()
            store = SceneCoverageStore(path)
            restored = SceneRepository(coverage_enabled=False, coverage_store=store)
            seed(restored)
            snap = restored.snapshot()
            self.assertEqual(snap.coverage.rows, before.rows)
            self.assertTrue(snap.coverage_paused)
            self.assertEqual(nearby_payload(snap)["coverage"]["scope"], "history")
            restored.handle_packet(event(0x0133, [field(1, 1100), field(8, 1), field(17, 1),
                field(2, children=[field(1, 500000), field(2, 600000)])], direction="c2s"))
            self.assertEqual(restored.snapshot().coverage.rows, before.rows)
            self.assertTrue(restored.reset_coverage(snap.uid, snap.resource_id, snap.observation_id))
            store.close()
            store = SceneCoverageStore(path)
            restored = SceneRepository(coverage_enabled=False, coverage_store=store)
            seed(restored)
            self.assertIsNone(restored.snapshot().coverage)
            store.close()

    def test_scene_reentry_without_landing_point_does_not_write_footprint(self):
        """换图/进场事件没带落点时，位置保持旧值，但旧坐标不能当成已记录区域。"""
        repo = SceneRepository(); seed(repo)
        repo.handle_packet(event(0x0133, [field(1, 1000), field(17, 1),
            field(2, children=[field(1, 500000), field(2, 600000)])], direction="c2s"))
        self.assertEqual(repo.snapshot().position_source, "client_target")
        self.assertIsNone(repo.snapshot().coverage)
        repo.handle_packet(event(0x0152, [field(2, 1), field(3, 2), field(4, 3)]))
        self.assertIsNone(repo.snapshot().coverage)

    def test_server_motion_interpolates_and_interrupt_uses_confirmed_position(self):
        repo = SceneRepository(); seed(repo)
        repo.handle_packet(event(0x014A, [actor_node(7, x=0, y=0)]))
        point = lambda x, y: [field(1, x), field(2, y), field(3, 0)]
        move = field(12, children=[field(1, 7), field(3, 1000), field(3, 3000),
                                  field(4, children=point(0, 0)), field(4, children=point(100, 200))])
        repo.handle_packet(event(0x0414, [field(1, children=[move])]))
        with patch("spritelens.services.scene_repository.time.time", return_value=2):
            repo.advance()
            self.assertEqual(repo.snapshot().actors[0].position, (50, 100, 0))
        stop = field(13, children=[field(1, 7), field(3, children=[field(1, children=point(25, 75))])])
        repo.handle_packet(replace(event(0x0414, [field(1, children=[stop])]), ts=2))
        with patch("spritelens.services.scene_repository.time.time", return_value=10):
            repo.advance()
            self.assertEqual(repo.snapshot().actors[0].position, (25, 75, 0))
        repo.handle_packet(event(0x0414, [field(1, children=[field(222, children=[field(1, 7), field(2, children=point(30, 80))])])]))
        self.assertEqual(repo.snapshot().actors[0].position, (30, 80, 0))

    def test_client_movement_target_does_not_discard_observed_entities(self):
        repo = SceneRepository(max_distance_raw=3000); seed(repo)
        repo.handle_packet(event(0x0133, [field(17, 1), field(2, children=[field(1, 0), field(2, 0)])], direction="c2s"))
        repo.handle_packet(event(0x014A, [actor_node(1, x=2000, y=0), actor_node(2, x=3001, y=0)]))
        self.assertEqual(tuple(item.actor_id for item in repo.snapshot().actors), (1, 2))
        repo.handle_packet(event(0x0133, [field(17, 1), field(2, children=[field(1, -1001), field(2, 0)])], direction="c2s"))
        self.assertEqual(tuple(item.actor_id for item in repo.snapshot().actors), (1, 2))

    def test_default_distance_threshold_does_not_filter_against_client_target(self):
        """客户端目标位置不是服务器确认位置，不能裁剪观察集合。"""
        repo = SceneRepository(); seed(repo)
        repo.handle_packet(event(0x0133, [field(17, 1), field(2, children=[field(1, 0), field(2, 0)])], direction="c2s"))
        repo.handle_packet(event(0x014A, [actor_node(1, x=10000, y=0), actor_node(2, x=15001, y=0)]))
        self.assertEqual(tuple(item.actor_id for item in repo.snapshot().actors), (1, 2))

    def test_snapshot_is_read_only_and_stable(self):
        """读接口不得推进插值：同一时刻重复 snapshot 的位置与版本一致。"""
        repo = SceneRepository(); seed(repo)
        repo.handle_packet(event(0x014A, [actor_node(7, x=0, y=0)]))
        point = lambda x, y: [field(1, x), field(2, y), field(3, 0)]
        move = field(12, children=[field(1, 7), field(3, 1000), field(3, 3000),
                                   field(4, children=point(0, 0)), field(4, children=point(100, 200))])
        repo.handle_packet(event(0x0414, [field(1, children=[move])]))
        first, second = repo.snapshot(), repo.snapshot()
        self.assertEqual(first.version, second.version)
        self.assertEqual(first.actors, second.actors)
        repo.advance(2.0)  # 只有写路径推进后位置才变化
        self.assertEqual(repo.snapshot().actors[0].position, (50, 100, 0))

    def test_nearby_payload_carries_raw_radar_radius(self):
        repo = SceneRepository(); seed(repo)
        self.assertEqual(nearby_payload(repo.snapshot())["radar_radius_raw"], 10000)
        self.assertEqual(nearby_payload(repo.snapshot(), radar_radius_raw=1234)["radar_radius_raw"], 1234)

    def test_nearby_payload_carries_grid_coverage(self):
        repo = SceneRepository(); seed(repo)
        self.assertIsNone(nearby_payload(repo.snapshot())["coverage"])
        repo.handle_packet(event(0x0133, [field(1, 1000), field(8, 1), field(17, 1),
            field(2, children=[field(1, 320000), field(2, 420000)])], direction="c2s"))
        payload = nearby_payload(repo.snapshot())["coverage"]
        self.assertIsInstance(payload.pop("updated_at"), float)
        self.assertEqual(payload.pop("radius_raw"), 0)
        self.assertEqual(payload, {
            "uid": "101", "map_id": "2", "layer": "visit", "scope": "session",
            "revision": 1, "cell_size": 2000, "cells": 1, "rows": [[210, 160, 1]],
        })

    def test_debug_coordinates_follow_environment_switch(self):
        """调试坐标默认关闭；只有环境变量打开时才下发，供现场地标校准。"""
        repo = SceneRepository(); seed(repo)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(DEBUG_COORDINATES_ENV, None)
            self.assertFalse(nearby_payload(repo.snapshot())["debug_coordinates"])
        for value in ("1", "true", "yes", "on", " ON "):
            with patch.dict(os.environ, {DEBUG_COORDINATES_ENV: value}):
                self.assertTrue(nearby_payload(repo.snapshot())["debug_coordinates"])
        for value in ("0", "false", "", "maybe"):
            with patch.dict(os.environ, {DEBUG_COORDINATES_ENV: value}):
                self.assertFalse(nearby_payload(repo.snapshot())["debug_coordinates"])

    def test_nearby_payload_exposes_scene_ids_as_strings(self):
        """资源与实例编号按字符串下发：实例号是 64 位，前端不能依赖 JS 安全整数。"""
        repo = SceneRepository()
        self.assertIsNone(nearby_payload(repo.snapshot())["resource_id"])
        replaced = replace(repo.snapshot(), resource_id=10003, instance_id=18446744073709551615)
        payload = nearby_payload(replaced)
        self.assertEqual(payload["resource_id"], "10003")
        self.assertEqual(payload["instance_id"], "18446744073709551615")

    def test_exact_npc_catalog_mapping_and_observation_epoch(self):
        repo = SceneRepository(); seed(repo)
        node = actor_node()
        node["children"][0]["children"][1]["children"][0]["raw"] = 10011
        repo.handle_packet(event(0x014A, [node]))
        static = load_static_data(static_dir())
        payload = nearby_payload(repo.snapshot(), static)
        self.assertTrue(payload["mapping_available"])
        self.assertEqual(payload["actors"][0]["base_id"], 3004)
        self.assertEqual(payload["actors"][0]["name"], "迪莫")
        # 进化链名称随载荷下发：附近页搜索用同一规则扩展到整条链。
        self.assertIn("迪莫", payload["actors"][0]["chain_names"])
        old = payload["observation_id"]
        repo.handle_packet(event(0x015C, [field(11, 1), field(12, 2), field(13, 3)]))
        self.assertGreater(repo.snapshot().observation_id, old)
        self.assertEqual(repo.snapshot().actors, ())
        self.assertIsNone(static.scene_species_id(123))

    def test_pet_info_supplies_species_for_unmapped_scene_config(self):
        repo = SceneRepository(); seed(repo)
        node = actor_node()
        npc = node["children"][0]["children"]
        npc[1]["children"][0]["raw"] = 50571
        npc.append(field(8, children=[field(1, 92243), field(4, 3229)]))
        repo.handle_packet(event(0x014A, [node]))
        row = nearby_payload(repo.snapshot(), load_static_data(static_dir()))["actors"][0]
        self.assertEqual((row["config_id"], row["base_id"], row["name"]), (50571, 3229, "友爱星飞"))
        self.assertTrue(row["icon_url"])

    def test_fields_unknowns_precision_and_partial_status(self):
        repo = SceneRepository(); seed(repo)
        repo.handle_packet(event(0x014A, [actor_node(), actor_node(77, measurements=False)]))
        row = repo.snapshot().actors[0]
        self.assertEqual(row.position, (0, -3, None)); self.assertEqual(row.voice, -20)
        self.assertIsNone(row.mutation)
        self.assertEqual(integer([field(1, (1 << 32) - 7)], 1, signed=True), -7)
        self.assertEqual(removed_ids([field(1, b"\x01\x80\x01")]), ((1, 128), False))
        self.assertTrue(removed_ids([field(1, b"\x80")])[1])
        payload = nearby_payload(repo.snapshot())
        self.assertFalse(payload["mapping_available"])
        self.assertEqual(payload["actors"][0]["actor_id"], "9007199254740993")
        self.assertFalse(payload["complete"]); self.assertEqual(payload["coordinate_unit"], "unverified")
        self.assertNotIn("session_id", payload)
        self.assertEqual(len(payload["actors"]), 1)

    def test_colorful_marks_colorful_from_mutation_bit_independent_of_attention(self):
        repo = SceneRepository(); seed(repo)
        repo.handle_packet(event(0x014A, [actor_node(1, mutation=8 | 1), actor_node(2, mutation=0), actor_node(3)]))
        by_id = {row["actor_id"]: row for row in nearby_payload(repo.snapshot())["actors"]}
        # 炫彩看变异类型第 4 位（与背包 is_colorful 同口径），和本地推的 attention 互不覆盖。
        self.assertTrue(by_id["1"]["colorful"])
        self.assertFalse(by_id["2"]["colorful"])
        self.assertFalse(by_id["3"]["colorful"])
        self.assertEqual(by_id["1"]["mutation"], 9)
        self.assertEqual(by_id["1"]["attention"], "normal")

    def test_add_remove_wrapping_limits_and_unknown_actions(self):
        for opcode in (0x0413, 0x0414):
            repo = SceneRepository(); seed(repo)
            add = field(1, children=[field(1, children=[field(1, children=actor_node().get("children"))])])
            # acts -> actor_enter -> actors, plus an unsupported delta.
            actions = [add, field(1, children=[field(999, children=[])])]
            fs = [field(1, children=actions)] if opcode == 0x0413 else actions
            repo.handle_packet(event(opcode, fs))
            self.assertEqual(len(repo.snapshot().actors), 1)
            self.assertEqual(repo.snapshot().unresolved_updates, 1)
            remove = field(1, children=[field(2, children=[field(1, 9007199254740993)])])
            repo.handle_packet(event(opcode, [field(1, children=[remove])] if opcode == 0x0413 else [remove]))
            self.assertEqual(repo.snapshot().actors, ())
        repo = SceneRepository(); seed(repo)
        with patch("spritelens.services.scene_repository.MAX_ACTORS", 1):
            repo.handle_packet(event(0x014A, [actor_node(1), actor_node(2)]))
        self.assertEqual(len(repo.snapshot().actors), 1)
        self.assertEqual(repo.snapshot().rejected_actors, 1)

    def test_scene_instance_teleport_account_session_and_battle_invalidation(self):
        repo = SceneRepository(); seed(repo)
        repo.handle_packet(event(0x014A, [actor_node()]))
        snapshot = repo.snapshot(); seed(repo)
        self.assertEqual(repo.snapshot().actors, snapshot.actors)
        repo.handle_packet(event(0x0152, [field(2, 1), field(3, 2), field(4, 4)], uid=101))
        self.assertFalse(repo.snapshot().actors)
        repo.handle_packet(event(0x014A, [actor_node()]))
        repo.handle_packet(event(0x015C, [field(11, 1), field(12, 2), field(13, 4)]))
        self.assertFalse(repo.snapshot().actors)
        repo.handle_packet(event(0x014A, [actor_node()]))
        repo.handle_packet(event(4886)); self.assertFalse(repo.snapshot().actors)
        repo.handle_packet(event(0x014A, [actor_node()])); self.assertFalse(repo.snapshot().actors)
        repo.handle_packet(event(4909)); repo.handle_packet(event(0x014A, [actor_node()]))
        self.assertTrue(repo.snapshot().actors)
        seed(repo, 202, "new"); self.assertFalse(repo.snapshot().actors)
        seed(repo, 101, "s"); self.assertEqual(repo.snapshot().uid, 202)
        repo.session_closed("new"); self.assertEqual(repo.snapshot().phase, "disconnected")
        self.assertFalse(repo.snapshot().actors)
        repo.handle_packet(event(0x014A, [actor_node()], session="new")); self.assertFalse(repo.snapshot().actors)
        repo.reset("historical_account", uid=303)
        self.assertEqual(repo.snapshot().uid, 303)

    def test_direction_movement_failed_scene_and_snapshot_immutability(self):
        repo = SceneRepository(); seed(repo)
        repo.handle_packet(event(0x014A, [actor_node()], direction="c2s"))
        self.assertFalse(repo.snapshot().actors)
        repo.handle_packet(event(0x0133, [field(17, 99), field(2, children=[field(1, 8)])], direction="c2s"))
        self.assertEqual(repo.snapshot().scene_id, 99)
        self.assertEqual(repo.snapshot().player_position, (8, None, None))
        repo.handle_packet(event(0x0133, [field(17, 1), field(2, children=[field(1, 8)])], direction="c2s"))
        self.assertEqual(repo.snapshot().player_position, (8, None, None))
        self.assertEqual(repo.snapshot().position_source, "client_target")
        repo.handle_packet(event(0x014A, [actor_node()]))
        old = repo.snapshot()
        repo.handle_packet(event(0x0152, [field(1, children=[field(1, 5)]), field(2, 99)]))
        self.assertEqual(repo.snapshot().scene_id, 1)
        repo.reset(); self.assertEqual(len(old.actors), 1)

    def test_battle_finish_matches_active_battle_and_recovers_from_increment(self):
        repo = SceneRepository(); seed(repo)
        repo.handle_packet(event(0x014A, [actor_node()]))
        repo.handle_packet(event(4886, [field(6, children=[field(1, 1234)])]))
        self.assertFalse(repo.snapshot().actors)
        repo.handle_packet(event(4908, [field(1, children=[field(19, 999)])]))
        self.assertEqual(repo.snapshot().phase, "battle_unverified")
        self.assertEqual(repo.snapshot().unresolved_updates, 1)
        repo.handle_packet(event(4908))
        self.assertEqual(repo.snapshot().phase, "battle_unverified")
        self.assertEqual(repo.snapshot().unresolved_updates, 2)
        add = field(1, children=[field(1, children=[field(1, children=actor_node().get("children"))])])
        repo.handle_packet(event(0x0414, [add]))
        self.assertFalse(repo.snapshot().actors)
        repo.handle_packet(event(4908, [field(1, children=[field(19, 1234)])]))
        self.assertEqual(repo.snapshot().phase, "observing")
        self.assertTrue(repo.snapshot().actors[0].stale)
        repo.handle_packet(event(0x0414, [add]))
        self.assertEqual(repo.snapshot().phase, "observing")
        self.assertGreaterEqual(len(repo.snapshot().actors), 1)
        self.assertFalse(repo.snapshot().actors[0].stale)
        self.assertFalse(nearby_payload(repo.snapshot())["complete"])

    def test_battle_resume_marks_old_position_and_actors_until_confirmed(self):
        repo = SceneRepository(); seed(repo)
        move = event(0x0133, [field(17, 1), field(2, children=[field(1, 100), field(2, 200)])], direction="c2s")
        repo.handle_packet(move)
        repo.handle_packet(event(0x014A, [actor_node(7), actor_node(8)]))
        repo.handle_packet(event(4886, [field(6, children=[field(1, 1234)])]))
        self.assertEqual(repo.snapshot().actors, ())
        self.assertIsNone(repo.snapshot().player_position)
        repo.handle_packet(event(4908, [field(1, children=[field(19, 1234)])]))
        restored = repo.snapshot()
        self.assertEqual(restored.player_position[:2], (100, 200))
        self.assertEqual(restored.position_source, "battle_return")
        self.assertEqual([(actor.actor_id, actor.stale) for actor in restored.actors], [(7, True), (8, True)])
        add = field(1, children=[field(1, children=[field(1, children=actor_node(7)["children"])])])
        remove = field(1, children=[field(2, children=[field(1, 8)])])
        repo.handle_packet(event(0x0414, [add, remove]))
        self.assertEqual([(actor.actor_id, actor.stale) for actor in repo.snapshot().actors], [(7, False)])
        repo.handle_packet(move)
        self.assertEqual(repo.snapshot().position_source, "client_target")

    def test_battle_backup_is_discarded_on_switch_and_unknown_finish(self):
        repo = SceneRepository(); seed(repo)
        repo.handle_packet(event(0x014A, [actor_node(7)]))
        repo.handle_packet(event(4886, [field(6, children=[field(1, 1234)])]))
        repo.session_closed("s")
        seed(repo, session="new")
        repo.handle_packet(event(4908, [field(1, children=[field(19, 1234)])], session="new"))
        self.assertFalse(repo.snapshot().actors)
        repo.handle_packet(event(0x014A, [actor_node(8)], session="new"))
        repo.handle_packet(event(4886, [field(6, children=[field(1, 1234)])], session="new"))
        repo.handle_packet(event(4909, session="new"))
        self.assertFalse(repo.snapshot().actors)

    def test_full_scene_snapshot_replaces_unconfirmed_battle_actors(self):
        repo = SceneRepository(); seed(repo)
        repo.handle_packet(event(0x014A, [actor_node(7), actor_node(8)]))
        repo.handle_packet(event(4886, [field(6, children=[field(1, 1234)])]))
        repo.handle_packet(event(4908, [field(1, children=[field(19, 1234)])]))
        repo.handle_packet(event(0x014A, [actor_node(7)]))
        self.assertEqual([(actor.actor_id, actor.stale) for actor in repo.snapshot().actors], [(7, False)])

    def test_battle_backup_is_discarded_after_teleport(self):
        repo = SceneRepository(); seed(repo)
        repo.handle_packet(event(0x014A, [actor_node(7)]))
        repo.handle_packet(event(4886, [field(6, children=[field(1, 1234)])]))
        repo.handle_packet(event(0x015C, [field(11, 1), field(12, 2), field(13, 3)]))
        repo.handle_packet(event(4908, [field(1, children=[field(19, 1234)])]))
        self.assertFalse(repo.snapshot().actors)

    def test_battle_removals_are_not_restored_after_battle(self):
        for opcode in (0x0413, 0x0414):
            with self.subTest(opcode=opcode):
                repo = SceneRepository(); seed(repo)
                repo.handle_packet(event(0x014A, [actor_node(7), actor_node(8)]))
                repo.handle_packet(event(4886, [field(6, children=[field(1, 1234)])]))
                remove = field(1, children=[field(2, children=[field(1, 7)])])
                payload = [field(1, children=[remove])] if opcode == 0x0413 else [remove]
                repo.handle_packet(event(opcode, payload, session="other"))
                self.assertEqual(repo.snapshot().actors, ())
                repo.handle_packet(event(opcode, payload))
                self.assertEqual(repo.snapshot().actors, ())
                repo.handle_packet(event(4908, [field(1, children=[field(19, 1234)])]))
                self.assertEqual([(actor.actor_id, actor.stale) for actor in repo.snapshot().actors], [(8, True)])

    def test_battle_exit_leaves_radar_empty_until_new_observation_arrives(self):
        repo = SceneRepository(); seed(repo)
        repo.handle_packet(event(0x014A, [actor_node()]))
        before = repo.snapshot()
        repo.handle_packet(event(4886, [field(6, children=[field(1, 1234)])]))
        self.assertFalse(repo.snapshot().actors)
        repo.handle_packet(event(4909))
        after = repo.snapshot()
        self.assertEqual(after.phase, "awaiting_scene")
        self.assertEqual(after.actors, ())
        self.assertIsNone(after.player_position)

    def test_scene_change_discards_previous_battle_identifier(self):
        repo = SceneRepository(); seed(repo)
        repo.handle_packet(event(4886, [field(6, children=[field(1, 1234)])]))
        repo.handle_packet(event(0x015C, [field(11, 2), field(12, 2), field(13, 3)]))
        repo.handle_packet(event(0x014A, [actor_node()]))
        self.assertEqual(repo.snapshot().phase, "observing")
        self.assertEqual(len(repo.snapshot().actors), 1)
        repo.handle_packet(event(4908, [field(1, children=[field(19, 5678)])]))
        self.assertEqual(repo.snapshot().unresolved_updates, 0)
        self.assertEqual(repo.snapshot().phase, "awaiting_scene")

    def test_stop_and_monitor_close_clear_observations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); keys = KeyStore(root / "keys")
            monitor = MonitorService(catalog=OpcodeCatalog({}), key_store=keys)
            repo = SceneRepository(); seed(repo)
            monitor.add_session_close_listener(repo.session_closed)
            monitor.close_session("s"); self.assertEqual(repo.snapshot().phase, "disconnected")
            seed(repo); repo.handle_packet(event(0x014A, [actor_node()]))
            monitor.on_chunk(StreamChunk("s", "s2c", encode_frame(CMD_SYN, 0, 0, b"", b""), 0))
            self.assertEqual(repo.snapshot().phase, "disconnected")
            seed(repo); repo.handle_packet(event(0x014A, [actor_node()]))
            monitor.on_chunk(StreamChunk("s", "s2c", make_ack_frame(SYNTH_KEY), 0))
            self.assertEqual(repo.snapshot().phase, "disconnected")
            self.assertFalse(repo.snapshot().actors)
            seed(repo); repo.handle_packet(event(0x014A, [actor_node()]))
            service = CaptureService(monitor=monitor, keys_dir=root / "keys", recordings_dir=root,
                                     port=8195, key_store=keys, scene_repository=repo)
            with patch.object(monitor, "stop", side_effect=TimeoutError("停止未确认")):
                with self.assertRaises(TimeoutError): service.stop()
            self.assertTrue(repo.snapshot().actors)
            service.stop(); self.assertEqual(repo.snapshot().phase, "stopped")
            self.assertFalse(repo.snapshot().actors); keys.close()

    def test_http_auth_and_optional_assembly(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _make_context(Path(tmp)); ctx.scene_repository = SceneRepository(); seed(ctx.scene_repository)
            ctx.scene_repository.handle_packet(event(0x014A, [actor_node()]))
            server = LocalServer(ctx, port=0); server.start()
            try:
                url = f"http://127.0.0.1:{server.port}/api/nearby"
                self.assertEqual(_http_get(url)[0], 401)
                code, payload = _http_get(url, server.token)
                self.assertEqual(code, 200); self.assertEqual(payload["uid"], "101")
                self.assertEqual(payload["actors"][0]["actor_id"], "9007199254740993")
                with urlopen(Request(url, headers={"X-Local-Token": server.token}), timeout=5) as response:
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                _, state = _http_get(f"http://127.0.0.1:{server.port}/api/state", server.token)
                self.assertEqual(state["nearby"]["version"], payload["version"])
            finally: server.stop(); ctx.close()

    def test_http_coverage_reset_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _make_context(Path(tmp)); ctx.scene_repository = SceneRepository(); seed(ctx.scene_repository)
            ctx.scene_repository.handle_packet(event(0x0133, [field(1, 1000), field(8, 1), field(17, 1),
                field(2, children=[field(1, 320000), field(2, 420000)])], direction="c2s"))
            server = LocalServer(ctx, port=0); server.start()
            try:
                base = f"http://127.0.0.1:{server.port}/api/nearby"
                before = _http_get(base, server.token)[1]
                self.assertIsNotNone(before["coverage"])
                reset = base + "/coverage/reset"
                self.assertEqual(_http_post(reset, "", {})[0], 401)
                self.assertEqual(_http_post(reset, server.token, {})[0], 400)
                self.assertEqual(_http_post(reset, server.token, {"uid": "999", "resource_id": before["resource_id"], "observation_id": before["observation_id"]})[0], 409)
                self.assertIsNotNone(_http_get(base, server.token)[1]["coverage"])
                code, body = _http_post(reset, server.token, {"uid": before["uid"], "resource_id": before["resource_id"], "observation_id": before["observation_id"]})
                self.assertEqual((code, body), (200, {"ok": True}))
                after = _http_get(base, server.token)[1]
                self.assertIsNone(after["coverage"])
                self.assertGreater(after["version"], before["version"])
            finally: server.stop(); ctx.close()

    def test_http_coverage_reset_requires_scene_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _make_context(Path(tmp)); ctx.scene_repository = None
            server = LocalServer(ctx, port=0); server.start()
            try:
                code, body = _http_post(f"http://127.0.0.1:{server.port}/api/nearby/coverage/reset", server.token, {})
                self.assertEqual((code, body), (503, {"error": "当前实例未装配场景观察"}))
            finally: server.stop(); ctx.close()

    def test_historical_selection_failure_preserves_scene(self):
        repo = SceneRepository(); seed(repo); repo.handle_packet(event(0x014A, [actor_node()]))
        events = []; profiles = ((101, "A", 1, ""), (202, "B", 1, ""))
        pets = _Store(profiles, events=events)
        eggs = _Store(profiles, failure=OSError("读取失败"), events=events)
        service = AccountSelectionService(pet_store=pets, egg_store=eggs,
            home_store=_Store(profiles), pet_repository=_PetRepository(pets, events),
            egg_box=_Repo(events, "eggs"), home_repo=_Repo(events, "home"),
            capture_running=lambda: False, scene_repository=repo)
        with self.assertRaises(OSError): service.select(202)
        self.assertEqual(repo.snapshot().uid, 101); self.assertTrue(repo.snapshot().actors)
        eggs.failure = None; service.select(202)
        self.assertEqual(repo.snapshot().uid, 202); self.assertFalse(repo.snapshot().actors)
        self.assertEqual(repo.snapshot().phase, "historical_account")

    def test_actual_assembly_and_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"SPRITELENS_DATA_ROOT": tmp}):
                ctx = build_app_context(autostart=False)
                try:
                    repo = ctx.scene_repository
                    self.assertIsNotNone(repo)
                    repo.handle_packet(event(0x0152, [field(2, 103), field(3, 10003), field(4, 3)], uid=101))
                    repo.handle_packet(event(0x014A, [actor_node()]))
                    # 大陆启用独立的 9000 原始单位估计覆盖。
                    repo.handle_packet(event(0x0133, [field(1, 1000), field(8, 1), field(17, 1),
                        field(2, children=[field(1, 320000), field(2, 420000)])], direction="c2s"))
                    # 前一请求场景号不匹配不能写旧地图。
                    self.assertIsNone(repo.snapshot().coverage)
                    repo.handle_packet(event(0x0152, [field(2, 103), field(3, 10003), field(4, 3)]))
                    repo.handle_packet(event(0x0133, [field(1, 1100), field(8, 1), field(17, 103),
                        field(2, children=[field(1, 320000), field(2, 420000)])], direction="c2s"))
                    self.assertGreater(repo.snapshot().coverage.cells, 50)
                    self.assertFalse(repo.snapshot().coverage_paused)
                    ctx.monitor.close_session("s")
                    self.assertEqual(repo.snapshot().phase, "disconnected")
                    seed(repo); repo.handle_packet(event(0x014A, [actor_node()]))
                finally:
                    ctx.close()
                self.assertEqual(repo.snapshot().phase, "stopped")
                self.assertFalse(repo.snapshot().actors)

    def test_recorded_stream_replays_to_same_observations(self):
        def varint(value):
            data = bytearray()
            while value > 127: data.append((value & 127) | 128); value >>= 7
            data.append(value); return bytes(data)
        def number(no, value): return varint(no << 3) + varint(value)
        def message(no, value): return varint((no << 3) | 2) + varint(len(value)) + value
        base = number(2, 9007199254740993) + number(11, 5)
        config = number(1, 123) + number(11, 100) + number(12, 200)
        npc = message(11, message(1, base) + message(3, config))
        stream = make_ack_frame(SYNTH_KEY) + make_data_frame(SYNTH_KEY, 0x014A, message(7, npc), sequence=2)
        chunks = [StreamChunk("s", "s2c", stream[:35], 0), StreamChunk("s", "s2c", stream[35:], 35)]
        load_library(schema_dir())
        def consume(root, source_chunks, replay):
            keys = KeyStore(root); monitor = MonitorService(catalog=OpcodeCatalog({}), key_store=keys)
            repo = SceneRepository(); seed(repo); monitor.add_packet_listener(repo.handle_packet)
            try:
                if replay: ReplaySource(source_chunks, on_chunk=monitor.on_chunk).start()
                else:
                    for chunk in source_chunks: monitor.on_chunk(chunk)
                return tuple(replace(row, updated_at=0) for row in repo.snapshot().actors)
            finally: keys.close()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); recorder = StreamRecorder(); recorder.start(root / "synthetic.jsonl")
            for chunk in chunks: recorder.append(chunk)
            recorder.stop()
            direct = consume(root / "a", chunks, False)
            replayed = consume(root / "b", read_recording(root / "synthetic.jsonl"), True)
            self.assertTrue(direct); self.assertEqual(direct, replayed)
