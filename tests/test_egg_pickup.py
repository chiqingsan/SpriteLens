"""收蛋现场关联、归属隔离、持久化及学院窝性格。"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from spritelens.domain.home import HomeCouple, HomeFurniture, HomeResident, HomeSceneEgg, HomeSnapshot
from spritelens.events import PacketEvent
from spritelens.repositories.database import Database
from spritelens.repositories.egg_store import EggStore
from spritelens.services.egg_pickup import EggPickupTracker
from spritelens.services.egg_repository import EggBoxRepository
from spritelens.services.home_repository import HomeRepoSnapshot
from spritelens.web.payloads_catalog import egg_box_payload
from tests.test_egg_box import _egg_row, _event, _field, _identity_event


def home(kind: str = "academy") -> HomeRepoSnapshot:
    residents = tuple(HomeResident(actor, name, gender, 1, (0, 0, 0), instance, 3001,
                                   nest_guid="nest" if gender == 2 else "other")
                      for actor, name, gender, instance in ((10, "母本", 2, 1), (20, "父本一", 1, 2), (30, "父本二", 1, 3)))
    snap = HomeSnapshot(1, residents, (HomeFurniture(1001072, "nest", kind, "小窝", (0, 0, 0)),),
                        (HomeCouple(10, (20, 30)),), (HomeSceneEgg(500, "nest", 0), HomeSceneEgg(501, "nest", 0)), owner_uid=42)
    return HomeRepoSnapshot(snap, 42, 1, 0, "observed", "s1")


def request(actor: int = 500) -> PacketEvent:
    return PacketEvent(10, "s1", "c2s", 0x0137, "interact", 0, [_field(1, actor), _field(2, 830000165)])


def reward() -> PacketEvent:
    event = _event(_egg_row(7), opcode=0x0243)
    return replace(event, ts=10.1, decoded=[*event.decoded, _field(2, 13), _field(3, 223)])


class EggPickupTests(unittest.TestCase):
    def test_any_interaction_option_on_a_scene_egg_records_origin(self):
        # 实测 option_id 不固定：普通窝出现过 830000165/166/217，学院窝出现过 830000009。
        for option in (830000165, 830000166, 830000217, 830000009):
            with self.subTest(option=option):
                repo = EggBoxRepository(); repo.handle_packet(_identity_event(42))
                event = replace(request(), decoded=[_field(1, 500), _field(2, option)])
                repo.observe_pickup(event, home(), {1: 7}); repo.handle_packet(reward())
                origin = repo.snapshot()[0].pickup
                self.assertIsNotNone(origin)
                self.assertEqual(origin.nest_kind, "academy")
                self.assertEqual(origin.mother.instance_id, 1)

    def test_freezes_parents_and_nest_and_marks_stale_pairing(self):
        tracker = EggPickupTracker()
        tracker.observe(request(), replace(home(), pending_deltas=3), {1: 7})
        origin = tracker.take(reward())
        self.assertEqual(origin.mother.instance_id, 1)
        self.assertEqual([row.instance_id for row in origin.fathers], [2, 3])
        self.assertEqual(origin.nest_kind, "academy")
        self.assertEqual(origin.mother_nature_id, 7)
        self.assertTrue(origin.pairing_stale)
        self.assertIsNone(tracker.take(reward()))

    def test_rejects_history_other_session_owner_timeout_and_closed_session(self):
        for snapshot in (replace(home(), source="history"), replace(home(), session_id="other"), replace(home(), uid=84)):
            tracker = EggPickupTracker(); tracker.observe(request(), snapshot, {})
            self.assertIsNone(tracker.take(reward()))
        tracker = EggPickupTracker(); tracker.observe(request(), home(), {})
        self.assertIsNone(tracker.take(replace(reward(), ts=14)))
        tracker.observe(request(), home(), {}); tracker.clear("s1")
        self.assertIsNone(tracker.take(reward()))

    def test_restart_history_requires_a_fresh_home_snapshot_before_pickup(self):
        repo = EggBoxRepository(); repo.handle_packet(_identity_event(42))
        cached = replace(home(), source="history", session_id=None)
        repo.observe_pickup(request(), cached, {1: 7}); repo.handle_packet(reward())
        self.assertIsNone(repo.snapshot()[0].pickup)
        # 重新进家园取得现场快照后，同一收蛋分支可以记录关联。
        repo.observe_pickup(request(), home(), {1: 7})
        next_reward = replace(reward(), decoded=[*_event(_egg_row(8), opcode=0x0243).decoded,
                                                _field(2, 13), _field(3, 223)])
        repo.handle_packet(next_reward)
        self.assertEqual(next(row for row in repo.snapshot() if row.instance_id == 8).pickup.mother.instance_id, 1)

    def test_does_not_assign_generic_rewards_and_matches_latest_request(self):
        tracker = EggPickupTracker(); tracker.observe(request(), home(), {})
        self.assertIsNone(tracker.take(replace(reward(), decoded=[_field(2, 22)])))
        # 连续快速收不同蛋：奖励按最近一次请求配给，不再把整段窗口丢弃。
        tracker.observe(replace(request(501), ts=10.01), home(), {})
        latest = tracker.take(reward())
        self.assertIsNotNone(latest)
        self.assertEqual(latest.actor_id, 501)
        self.assertIsNone(tracker.take(reward()))
        # 目标不是场景蛋时不会建立待关联请求。
        tracker.observe(replace(request(999), ts=10.2), home(), {})
        self.assertIsNone(tracker.take(replace(reward(), ts=10.3)))

    def test_refresh_retry_restart_and_academy_nature_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.sqlite"
            db = Database(path); store = EggStore(db, flush_interval=60)
            try:
                repo = EggBoxRepository(store); repo.handle_packet(_identity_event(42))
                repo.observe_pickup(request(), home(), {1: 7}); repo.handle_packet(reward())
                original = repo.snapshot()[0].pickup
                repo.handle_packet(_event(_egg_row(7)))
                self.assertEqual(repo.snapshot()[0].pickup, original)
                with patch.object(db, "execute_batches", side_effect=sqlite3.OperationalError("synthetic")):
                    with self.assertRaises(sqlite3.OperationalError): store.flush()
            finally:
                store.close(); db.close()
            db = Database(path); store = EggStore(db)
            try:
                repo = EggBoxRepository(store); repo.load_account(42)
                row = egg_box_payload(repo, None, nature_options=[(7, "固执"), (9, "勇敢")])["eggs"][0]
                self.assertEqual(row["tags"]["nest"], "学院绿窝")
                self.assertEqual(row["annotations"]["nature_id"], 7)
                self.assertEqual(row["tags"]["nature"], "固执")
                self.assertEqual(row["pickup"]["mother"]["instance_id"], 1)
                row = egg_box_payload(repo, None, annotations={7: {"nature_id": 9, "nest_override": "normal"}})["eggs"][0]
                self.assertEqual(row["annotations"]["nature_id"], 9)
                self.assertEqual(row["tags"]["nest"], "普通窝")
                repo.load_account(84); self.assertEqual(repo.snapshot(), ())
            finally:
                store.close(); db.close()

    def test_ordinary_or_missing_mother_nature_is_not_inferred(self):
        for snapshot, natures in ((home("ordinary"), {1: 7}), (home(), {})):
            repo = EggBoxRepository(); repo.handle_packet(_identity_event(42))
            repo.observe_pickup(request(), snapshot, natures); repo.handle_packet(reward())
            self.assertEqual(egg_box_payload(repo, None)["eggs"][0]["annotations"]["nature_id"], 0)
