"""附近场景基线接续回归。"""
from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
import os
import json
from pathlib import Path
from unittest.mock import patch

from spritelens.app_context import build_app_context
from spritelens.repositories.scene_checkpoint_store import SceneCheckpointStore
from spritelens.services.scene_repository import SceneRepository
from tests.test_scene import actor_node, event, field, seed


class SceneCheckpointTests(unittest.TestCase):
    def test_midstream_stop_saves_only_context_and_resumes_fresh_entities(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "scene.json"
            store = SceneCheckpointStore(path)
            repo = SceneRepository(checkpoint_store=store)
            repo.handle_packet(replace(event(0x0133, [field(17, 103), field(2, children=[field(1, 100), field(2, 200)])], direction="c2s"), resumed_identity=(101, "玩家", 55)))
            add = field(1, children=[field(1, children=[field(1, children=actor_node(7)["children"])])])
            repo.handle_packet(event(0x0414, [add]))
            repo.reset("stopped"); store.close()
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(raw["version"], 2)
            self.assertEqual(set(raw["checkpoints"][0]), {"uid", "flow_id", "scene_id", "resource_id", "instance_id", "updated_at"})
            reopened = SceneCheckpointStore(path)
            try:
                restarted = SceneRepository(checkpoint_store=reopened)
                self.assertFalse(restarted.restore_for(202, "s"))
                self.assertFalse(restarted.restore_for(101, "other"))
                self.assertTrue(restarted.restore_for(101, "s"))
                self.assertEqual(restarted.snapshot().scene_id, 103)
                self.assertFalse(restarted.snapshot().actors)
                self.assertIsNone(restarted.snapshot().player_position)
                restarted.handle_packet(replace(event(0x0414, [add]), resumed_identity=(101, "玩家", 55)))
                restarted.handle_packet(event(0x014A, [actor_node(8)]))
                self.assertEqual({a.actor_id for a in restarted.snapshot().actors}, {7, 8})
            finally:
                reopened.close()

    def test_old_cache_format_is_discarded_without_restoring_entities(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "scene.json"
            path.write_text(json.dumps({"version": 1, "checkpoints": [{"uid": 101, "flow_id": "s", "scene_id": 103, "actors": []}]}), encoding="utf-8")
            store = SceneCheckpointStore(path)
            try:
                self.assertIsNone(store.load(101, "s"))
            finally:
                store.close()
    def test_app_context_reopens_checkpoint_for_resumed_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"SPRITELENS_DATA_ROOT": temp}):
            first = build_app_context(autostart=False)
            try:
                first.scene_repository.handle_packet(event(0x0152, [field(2, 1), field(3, 2), field(4, 3)],
                                                          uid=101, session="flow-a"))
                first.scene_repository.handle_packet(event(0x014A, [actor_node(11)], session="flow-a"))
            finally:
                first.close()

            second = build_app_context(autostart=False)
            try:
                resumed = replace(event(0x014A, [actor_node(12)], session="flow-a"),
                                  resumed_identity=(101, "玩家", 55))
                second.scene_repository.handle_packet(resumed)
                self.assertEqual({row.actor_id for row in second.scene_repository.snapshot().actors}, {12})
            finally:
                second.close()

    def test_resumed_same_flow_restores_stale_baseline_then_accepts_fresh_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = SceneCheckpointStore(Path(temp) / "scene.json")
            try:
                repo = SceneRepository(checkpoint_store=store)
                seed(repo, uid=101, session="flow-a")
                repo.handle_packet(event(0x014A, [actor_node(11)], session="flow-a"))
                repo.reset("stopped")
                store.flush()

                restarted = SceneRepository(checkpoint_store=store)
                self.assertTrue(restarted.restore_for(101, "flow-a"))
                self.assertFalse(restarted.snapshot().actors)
                self.assertIsNone(restarted.snapshot().player_position)
                resumed = replace(event(0x014A, [actor_node(12)], session="flow-a"),
                                  resumed_identity=(101, "玩家", 55))
                restarted.handle_packet(resumed)
                snapshot = restarted.snapshot()
                self.assertEqual(snapshot.phase, "observing")
                self.assertEqual(snapshot.scene_id, 1)
                self.assertEqual({row.actor_id for row in snapshot.actors}, {12})
            finally:
                store.close()

    def test_new_scene_invalidates_checkpoint_before_next_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = SceneCheckpointStore(Path(temp) / "scene.json")
            try:
                repo = SceneRepository(checkpoint_store=store)
                seed(repo, uid=101, session="flow-a")
                repo.handle_packet(event(0x014A, [actor_node(11)], session="flow-a"))
                repo.handle_packet(event(0x0152, [field(2, 9), field(3, 8), field(4, 7)], session="flow-a"))
                store.flush()
                self.assertIsNone(store.load(101, "flow-a"))
                repo.reset("stopped")
                store.flush()
                restarted = SceneRepository(checkpoint_store=store)
                resumed = replace(event(0x014A, [actor_node(12)], session="flow-a"),
                                  resumed_identity=(101, "玩家", 55))
                restarted.handle_packet(resumed)
                self.assertEqual(restarted.snapshot().phase, "observing")
                self.assertEqual(restarted.snapshot().scene_id, 9)
                self.assertEqual({a.actor_id for a in restarted.snapshot().actors}, {12})
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
