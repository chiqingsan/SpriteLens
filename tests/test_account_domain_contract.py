"""F02：单域快照、跨域账号失配与历史恢复竞争（仅合成数据）。"""
from __future__ import annotations

import sqlite3
import unittest
from unittest.mock import Mock, patch

from spritelens.domain.pet_locations import Backpack
from spritelens.repositories.egg_store import EggStore
from spritelens.services.egg_repository import EggBoxRepository
from spritelens.services.home_repository import HomeRepository
from spritelens.services.pet_repository import PetRepository
from spritelens.web.account_state import account_domains_payload
from spritelens.web.payloads_catalog import egg_box_payload, home_payload
from tests.test_egg_box import _event, _egg_row, _identity_event, _hatch_event
from tests.test_home import _resident_event
from tests import test_home as home_fixtures
from tests.test_web_server import _pet


class AccountDomainContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.egg = EggBoxRepository()
        self.home = HomeRepository()
        for repo in (self.egg, self.home):
            repo.handle_packet(_identity_event(101))
        self.egg.handle_packet(_event(_egg_row(9001)))
        self.egg.handle_packet(_hatch_event([9001]))
        self.home.handle_packet(home_fixtures._scene_event(30001, session_id="s1"))
        self.home.handle_packet(_resident_event(99, "居民 A", session_id="s1"))

    def test_serialization_keeps_captured_owner_after_switch(self) -> None:
        for repo, build in ((self.egg, egg_box_payload), (self.home, home_payload)):
            with self.subTest(repo=type(repo).__name__):
                original = repo.consistent_snapshot
                before = original()

                def capture_then_switch():
                    snapshot = original()
                    repo.handle_packet(_identity_event(202))
                    return snapshot

                with patch.object(repo, "consistent_snapshot", side_effect=capture_then_switch) as take:
                    payload = build(repo, None)
                self.assertEqual(take.call_count, 1)
                self.assertEqual((payload["uid"], payload["version"]), (101, before.version))
                self.assertIsNone(payload["complete"])
                self.assertEqual(original().uid, 202)
                if repo is self.egg:
                    self.assertEqual((payload["total"], payload["hatching"]), (1, 1))
                elif repo is self.home:
                    self.assertEqual(payload["residents"][0]["name"], "居民 A")

    def test_cross_domain_mismatch_does_not_publish_other_account_count(self) -> None:
        self.egg.handle_packet(_identity_event(202))
        self.egg.handle_packet(_event(_egg_row(9002)))
        payload = account_domains_payload(101, self.egg, self.home)
        self.assertIsNone(payload["egg_box_total"])
        self.assertFalse(payload["domains"]["egg_box"]["consistent"])
        self.assertEqual(payload["domains"]["egg_box"]["source"], "unknown")
        self.assertTrue(payload["domains"]["home"]["consistent"])
        self.assertEqual(payload["egg_box_version"], self.egg.version())

    def test_pending_home_delta_and_unknown_keep_version(self) -> None:
        self.home.handle_packet(_event(opcode=0x0413))
        payload = home_payload(self.home, None)
        self.assertEqual((payload["source"], payload["pending_deltas"]), ("stale", 1))
        self.home.handle_packet(_identity_event(202))
        payload = home_payload(self.home, None)
        self.assertFalse(payload["available"])
        self.assertEqual(payload["source"], "unknown")
        self.assertGreater(payload["version"], 0)

    def test_empty_domains_are_unknown_not_complete(self) -> None:
        payload = account_domains_payload(101, None, None)
        self.assertIsNone(payload["egg_box_total"])
        for domain in payload["domains"].values():
            self.assertEqual(domain["source"], "unknown")
            self.assertIsNone(domain["complete"])


class HistoricalRestoreContractTest(unittest.TestCase):
    def setUp(self) -> None:
        observed = EggBoxRepository()
        observed.handle_packet(_event(_egg_row(9001), _egg_row(9002)))
        self.store = Mock()
        self.store.load.return_value = observed.snapshot()
        self.store.load_hatch_slots.return_value = {9001}
        self.repo = EggBoxRepository(self.store)

    def test_restored_slots_stay_historical_until_live_slot_frame(self) -> None:
        self.repo.load_account(101)
        self.repo.handle_packet(_identity_event(101))
        payload = egg_box_payload(self.repo, None)
        self.assertEqual((payload["uid"], payload["source"], payload["slots_source"]),
                         (101, "historical", "historical"))
        self.assertIsNone(payload["hatching"])
        self.assertEqual(payload["historical_hatching"], 1)
        self.assertFalse(payload["eggs"][0]["hatching"])
        self.assertFalse(payload["eggs"][0]["hatch_known"])
        self.repo.handle_packet(_event(_egg_row(9002)))
        self.assertEqual(egg_box_payload(self.repo, None)["source"], "mixed")
        self.repo.handle_packet(_hatch_event([]))
        payload = egg_box_payload(self.repo, None)
        self.assertEqual((payload["hatching"], payload["historical_hatching"]), (0, 0))
        self.assertTrue(all(row["hatch_known"] for row in payload["eggs"]))
        self.assertIsNone(payload["complete"])

    def test_missing_slots_do_not_confirm_empty_slots(self) -> None:
        self.store.load_hatch_slots.return_value = None
        self.repo.load_account(101)
        payload = egg_box_payload(self.repo, None)
        self.assertEqual(payload["slots_source"], "unknown")
        self.assertIsNone(payload["hatching"])

    def test_restore_rejects_switch_during_io_including_aba(self) -> None:
        self.repo.handle_packet(_identity_event(101))

        def switch_during_load(uid):
            self.repo.handle_packet(_identity_event(202))
            self.repo.handle_packet(_identity_event(101))
            self.repo.handle_packet(_event(_egg_row(9003)))
            return self.store.load.return_value

        self.store.load.side_effect = switch_during_load
        with self.assertRaisesRegex(RuntimeError, "历史数据未应用"):
            self.repo.load_account(101)
        self.assertEqual([e.instance_id for e in self.repo.snapshot()], [9003])

    def test_pet_restore_rejects_switch_during_io(self) -> None:
        store = Mock()
        store.load_backpack.return_value = Backpack()
        store.load_account.return_value = (101, "历史 A", 1)
        repo = PetRepository(store)
        repo.handle_packet(_identity_event(101))

        def switch_during_load(uid):
            repo.handle_packet(_identity_event(202))
            return [_pet(1, name="历史 A", level=1)]

        store.load.side_effect = switch_during_load
        with self.assertRaisesRegex(RuntimeError, "历史数据未应用"):
            repo.load_persisted(101)
        self.assertEqual(repo.consistent_snapshot().uid, 202)
        self.assertEqual(repo.snapshot(), ())
        with self.assertRaises(ValueError):
            repo.load_persisted(101)

    def test_slot_storage_distinguishes_absent_invalid_and_empty(self) -> None:
        db = Mock()
        store = EggStore(db)
        self.addCleanup(store.close)
        for rows, expected in (([], None), ([{"slots_json": "[]"}], set()),
                               ([{"slots_json": "[9001]"}], {9001}),
                               ([{"slots_json": "bad json"}], None),
                               ([{"slots_json": "{}"}], None),
                               ([{"slots_json": "[true]"}], None)):
            with self.subTest(rows=rows):
                db.query.return_value = rows
                self.assertEqual(store.load_hatch_slots(101), expected)
        db.query.side_effect = sqlite3.OperationalError("合成读失败")
        with self.assertRaises(sqlite3.OperationalError):
            store.load_hatch_slots(101)
