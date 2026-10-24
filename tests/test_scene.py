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
from spritelens.services.scene_repository import SceneRepository
from spritelens.web.nearby import nearby_payload
from spritelens.web.server import LocalServer
from tests._synth import SYNTH_KEY, make_ack_frame, make_data_frame, encode_frame
from tests.test_account_selection import _Store, _PetRepository, _Repo
from tests.test_web_server import _make_context, _http_get


def field(no, raw=None, children=None):
    result = {"no": no, "raw": raw}
    if children is not None: result["children"] = children
    return result


def event(opcode, fields=(), *, uid=None, session="s", direction="s2c"):
    return PacketEvent(1.0, session, direction, opcode, "synthetic", 0, list(fields),
                       (uid, "synthetic", 1) if uid is not None else None)


def actor_node(actor_id=9007199254740993, *, measurements=True, x=0, y=-3):
    config = [field(1, 123)]
    if measurements: config.extend([field(11, 100), field(12, 200), field(31, (1 << 64) - 20)])
    return field(7, children=[field(11, children=[
        field(1, children=[field(2, actor_id), field(11, 5),
            field(8, children=[field(1, children=[field(1, x), field(2, y)])])]),
        field(3, children=config)])])


def seed(repo, uid=101, session="s"):
    repo.handle_packet(event(0x0152, [field(2, 1), field(3, 2), field(4, 3)], uid=uid, session=session))


class SceneTests(unittest.TestCase):
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

    def test_radar_distance_removes_only_entities_beyond_delete_threshold(self):
        repo = SceneRepository(max_distance_raw=3000); seed(repo)
        repo.handle_packet(event(0x0133, [field(17, 1), field(2, children=[field(1, 0), field(2, 0)])], direction="c2s"))
        repo.handle_packet(event(0x014A, [actor_node(1, x=2000, y=0), actor_node(2, x=3001, y=0)]))
        self.assertEqual(tuple(item.actor_id for item in repo.snapshot().actors), (1,))
        repo.handle_packet(event(0x0133, [field(17, 1), field(2, children=[field(1, -1001), field(2, 0)])], direction="c2s"))
        self.assertFalse(repo.snapshot().actors)

    def test_default_distance_threshold_covers_realistic_entity_ranges(self):
        """真实流量里 85% 实体在 3,000 之外；默认阈值必须用 15,000 原始单位。"""
        repo = SceneRepository(); seed(repo)
        repo.handle_packet(event(0x0133, [field(17, 1), field(2, children=[field(1, 0), field(2, 0)])], direction="c2s"))
        repo.handle_packet(event(0x014A, [actor_node(1, x=10000, y=0), actor_node(2, x=15001, y=0)]))
        self.assertEqual(tuple(item.actor_id for item in repo.snapshot().actors), (1,))

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
        old = payload["observation_id"]
        repo.handle_packet(event(0x015C, [field(11, 1), field(12, 2), field(13, 3)]))
        self.assertGreater(repo.snapshot().observation_id, old)
        self.assertEqual(repo.snapshot().actors, ())
        self.assertIsNone(static.scene_species_id(123))

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
        self.assertEqual(repo.snapshot().phase, "awaiting_scene")
        self.assertFalse(repo.snapshot().actors)
        repo.handle_packet(event(0x0414, [add]))
        self.assertEqual(repo.snapshot().phase, "observing")
        self.assertGreaterEqual(len(repo.snapshot().actors), 1)
        self.assertFalse(nearby_payload(repo.snapshot())["complete"])

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
                    seed(repo); repo.handle_packet(event(0x014A, [actor_node()]))
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
