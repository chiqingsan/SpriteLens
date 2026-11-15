"""双开事件隔离、展示选择与重启接续的离线回归。"""
from __future__ import annotations

import os
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from spritelens.app_context import build_app_context, load_catalog
from spritelens.capture.base import StreamChunk
from spritelens.capture.key_store import KeyStore, SessionCheckpoint
from spritelens.services.monitor_service import MonitorService
from spritelens.paths import database_path, keys_dir
from spritelens.repositories.database import Database
from spritelens.repositories.pet_store import PetStore
from spritelens.repositories.settings import SettingsRepository
from tests._synth import SYNTH_KEY, make_ack_frame, make_data_frame
from tests.test_pet_locations import integer, message
from tests.test_pets import _brief, _page_rsp
from tests.test_egg_box import _event, _egg_row
from tests.test_scene import event, actor_node, field
from tests.test_home import _scene_event, _nested_home_event

FLOW_A = "10.0.0.5:51000"
FLOW_B = "10.0.0.5:52000"
KEY_B = b"fedcba9876543210"


class MultiAccountCaptureTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {"SPRITELENS_DATA_ROOT": self.tmp.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.ctx = build_app_context(autostart=False)
        self.addCleanup(self.ctx.close)

    def feed(self, flow, data, monitor=None):
        (monitor or self.ctx.monitor).on_chunk(StreamChunk(flow, "s2c", data, 1))

    def login(self, flow, uid, key, *, sequence=10, monitor=None):
        brief = integer(1, uid) + message(3, f"账号{uid}".encode()) + integer(5, 55)
        self.feed(flow, make_data_frame(key, 0x0102, message(2, message(1, brief)), sequence=sequence), monitor)

    def seed_two(self):
        for flow, uid, key in ((FLOW_A, 101, SYNTH_KEY), (FLOW_B, 202, KEY_B)):
            self.feed(flow, make_ack_frame(key))
            self.login(flow, uid, key)
            self.pet(flow, key, uid, sequence=11)

    def pet(self, flow, key, gid, *, sequence=12, monitor=None):
        self.feed(flow, make_data_frame(key, 0x134A, _page_rsp([_brief(gid, 3004, b"pet", 10)]), sequence=sequence), monitor)

    def test_interleaved_accounts_persist_and_display_independently(self):
        self.seed_two()
        self.assertEqual(self.ctx.pet_repository.consistent_snapshot().uid, 101)
        self.pet(FLOW_B, KEY_B, 222)
        self.pet(FLOW_A, SYNTH_KEY, 111)
        self.assertEqual({p.gid for p in self.ctx.pet_repository.snapshot()}, {101, 111})
        self.ctx.account_selection.select(202)
        self.assertEqual({p.gid for p in self.ctx.pet_repository.snapshot()}, {202, 222})
        self.login(FLOW_A, 101, SYNTH_KEY, sequence=13)
        self.pet(FLOW_A, SYNTH_KEY, 112, sequence=14)
        self.assertEqual(self.ctx.pet_repository.consistent_snapshot().uid, 202)
        self.assertEqual({p.gid for p in self.ctx.pet_store.load(101)}, {101, 111, 112})
        self.assertEqual({p.gid for p in self.ctx.pet_store.load(202)}, {202, 222})
        with patch.object(self.ctx.account_selection, "_capture_running", return_value=True):
            self.assertTrue(self.ctx.account_selection.accounts_payload()["can_switch"])
            self.ctx.account_selection.select(101)
            self.ctx.account_selection.select(202)
        self.assertEqual(self.ctx.account_selection.accounts_payload()["live_uids"], [101, 202])

    def test_history_read_does_not_overwrite_live_data_arriving_during_selection(self):
        self.seed_two()
        self.ctx.pet_store.put_account(303, "第三个账号", 10, "")
        entered, release = threading.Event(), threading.Event()
        load = self.ctx.egg_store.load
        failures = []
        def blocked_load(uid):
            entered.set()
            if not release.wait(3):
                raise TimeoutError("测试未释放历史读取")
            return load(uid)
        def select():
            try:
                self.ctx.account_selection.select(303)
            except Exception as exc:
                failures.append(exc)
        with patch.object(self.ctx.egg_store, "load", side_effect=blocked_load):
            worker = threading.Thread(target=select)
            worker.start()
            try:
                self.assertTrue(entered.wait(3))
                self.feed("third", make_ack_frame(KEY_B))
                self.login("third", 303, KEY_B)
                self.pet("third", KEY_B, 333)
                self.assertEqual(self.ctx.pet_repository.consistent_snapshot().uid, 101)
            finally:
                release.set()
                worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertFalse(failures)
        self.assertEqual(self.ctx.pet_repository.consistent_snapshot().uid, 303)
        self.assertEqual({p.gid for p in self.ctx.pet_repository.snapshot()}, {333})

    def test_single_account_login_change_follows_all_domains(self):
        self.feed(FLOW_A, make_ack_frame(SYNTH_KEY))
        self.login(FLOW_A, 101, SYNTH_KEY)
        self.pet(FLOW_A, SYNTH_KEY, 111)
        self.login(FLOW_A, 202, SYNTH_KEY, sequence=13)
        self.assertEqual(self.ctx.pet_repository.consistent_snapshot().uid, 202)
        self.assertEqual(self.ctx.egg_box.consistent_snapshot().uid, 202)
        self.assertEqual(self.ctx.home_repo.consistent_snapshot().uid, 202)
        scene = self.ctx.scene_repository.snapshot()
        self.assertEqual(scene.uid, 202)
        self.assertFalse(scene.actors)
        self.pet(FLOW_A, SYNTH_KEY, 222, sequence=14)
        self.assertEqual({p.gid for p in self.ctx.pet_repository.snapshot()}, {222})
        self.assertEqual({p.gid for p in self.ctx.pet_store.load(101)}, {111})

    def test_closing_one_of_two_accounts_follows_remaining_account(self):
        self.seed_two()
        self.ctx.monitor.close_session(FLOW_A)
        self.assertEqual(self.ctx.account_selection.accounts_payload()["selected_uid"], 202)
        self.assertEqual({p.gid for p in self.ctx.pet_repository.snapshot()}, {202})
        self.ctx.monitor.close_session(FLOW_B)
        self.assertEqual(self.ctx.pet_repository.consistent_snapshot().uid, 202)
        self.assertFalse(self.ctx.scene_repository.snapshot().actors)

    def test_manual_history_selection_survives_updates_and_same_account_reconnect(self):
        self.seed_two()
        self.ctx.monitor.close_session(FLOW_B)
        self.ctx.account_selection.select(202)
        self.login(FLOW_A, 101, SYNTH_KEY, sequence=13)
        self.pet(FLOW_A, SYNTH_KEY, 112, sequence=14)
        self.feed("same-account", make_ack_frame(KEY_B))
        self.login("same-account", 101, KEY_B)
        self.ctx.monitor.close_session(FLOW_A)
        self.assertEqual(self.ctx.pet_repository.consistent_snapshot().uid, 202)
        self.assertEqual(self.ctx.account_selection.accounts_payload()["live_uids"], [101])

    def test_unknown_connection_never_writes_to_selected_account(self):
        self.seed_two()
        self.pet("10.0.0.5:53000", SYNTH_KEY, 999)
        self.feed("10.0.0.5:53000", make_ack_frame(SYNTH_KEY))
        self.pet("10.0.0.5:53000", SYNTH_KEY, 998)
        self.assertNotIn(998, {p.gid for p in self.ctx.pet_store.load(101)})
        self.assertNotIn(998, {p.gid for p in self.ctx.pet_store.load(202)})
        rows, _ = self.ctx.monitor.snapshot()
        unknown = next(row for row in rows if row.session_id.endswith(":53000"))
        self.assertEqual(unknown.uid, 0)
        self.assertGreater(unknown.decrypt_ok, 0)

    def test_eggs_and_scene_are_routed_by_connection(self):
        self.seed_two()
        # 已确认连接的 decoded 事件复用生产入口，验证其他业务域也使用同一归属。
        for flow, uid in ((FLOW_A, 101), (FLOW_B, 202)):
            self.ctx.egg_box.handle_packet(replace(_event(_egg_row(uid, 150001)), session_id=flow))
            self.ctx.scene_repository.handle_packet(event(0x0152, [field(2, 1), field(3, 2), field(4, 3)], uid=uid, session=flow))
            self.ctx.scene_repository.handle_packet(event(0x014A, [actor_node(uid)], session=flow))
        self.assertEqual({egg.instance_id for egg in self.ctx.egg_store.load(101)}, {101})
        self.assertEqual({egg.instance_id for egg in self.ctx.egg_store.load(202)}, {202})
        self.ctx.account_selection.select(202)
        self.assertEqual(self.ctx.scene_repository.snapshot().uid, 202)
        self.assertEqual({row.actor_id for row in self.ctx.scene_repository.snapshot().actors}, {202})
        self.ctx.monitor.close_session(FLOW_A)
        self.assertEqual(self.ctx.scene_repository.snapshot().uid, 202)
        self.assertTrue(self.ctx.scene_repository.snapshot().actors)

    def test_home_snapshots_survive_other_account_updates_and_close(self):
        self.seed_two()
        for flow, uid in ((FLOW_A, 101), (FLOW_B, 202)):
            self.ctx.home_repo.handle_packet(_scene_event(30001, uid=uid, session_id=flow))
            self.ctx.home_repo.handle_packet(_nested_home_event(owner_uid=uid, session_id=flow))
        self.assertEqual(self.ctx.home_store.load(101).owner_uid, 101)
        self.assertEqual(self.ctx.home_store.load(202).owner_uid, 202)
        self.ctx.account_selection.select(202)
        self.assertEqual(self.ctx.home_repo.consistent_snapshot().source, "observed")
        self.ctx.monitor.close_session(FLOW_A)
        self.assertEqual(self.ctx.home_repo.consistent_snapshot().source, "observed")
        self.ctx.monitor.close_session(FLOW_B)
        self.assertEqual(self.ctx.home_repo.consistent_snapshot().source, "history")

    def test_same_connection_new_account_retires_previous_scene_and_home(self):
        self.seed_two()
        self.ctx.scene_repository.handle_packet(event(0x0152, [field(2, 1), field(3, 30001), field(4, 3)], uid=101, session=FLOW_A))
        self.ctx.home_repo.handle_packet(_nested_home_event(owner_uid=101, session_id=FLOW_A))
        self.assertEqual(self.ctx.home_repo.consistent_snapshot().source, "observed")
        self.login(FLOW_A, 303, SYNTH_KEY, sequence=15)
        self.assertEqual(self.ctx.scene_repository.snapshot().phase, "disconnected")
        self.assertEqual(self.ctx.home_repo.consistent_snapshot().source, "history")
        self.assertEqual(self.ctx.account_selection.accounts_payload()["live_uids"], [202, 303])
        self.assertEqual(self.ctx.pet_repository.consistent_snapshot().uid, 101)

    def test_restart_restores_each_key_and_identity_and_survives_single_reconnect(self):
        self.seed_two()
        self.ctx.monitor.stop()
        self.ctx.key_store.flush()
        keys = KeyStore(Path(self.tmp.name) / "keys")
        self.addCleanup(keys.close)
        # 下方断言 drain_events() 的历史，需显式开启事件历史。
        restarted = MonitorService(catalog=load_catalog(), key_store=keys, keep_event_history=True)
        self.pet(FLOW_A, SYNTH_KEY, 113, sequence=12, monitor=restarted)
        self.pet(FLOW_B, KEY_B, 223, sequence=12, monitor=restarted)
        events = restarted.drain_events()
        self.assertEqual([(e.session_id, e.account_uid) for e in events], [(FLOW_A, 101), (FLOW_B, 202)])
        restarted.close_session(FLOW_A)
        self.pet(FLOW_A, SYNTH_KEY, 999, sequence=13, monitor=restarted)
        self.pet(FLOW_B, KEY_B, 224, sequence=13, monitor=restarted)
        self.assertEqual([(e.session_id, e.account_uid) for e in restarted.drain_events()], [(FLOW_B, 202)])
        self.feed(FLOW_A, make_ack_frame(KEY_B), restarted)
        self.pet(FLOW_A, KEY_B, 998, sequence=14, monitor=restarted)
        self.assertEqual(restarted.drain_events()[0].account_uid, 0)
        self.login(FLOW_A, 303, KEY_B, sequence=15, monitor=restarted)
        self.assertEqual(restarted.drain_events()[0].account_uid, 303)
        keys.flush()
        saved = {item.flow_id: item for item in keys.load_sessions()}
        self.assertEqual(saved[FLOW_A].identity[0], 303)
        self.assertEqual(saved[FLOW_B].identity[0], 202)


class StartupAccountSelectionTest(unittest.TestCase):
    def test_single_resumed_account_is_initial_display_account(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"SPRITELENS_DATA_ROOT": temp}):
            database = Database(database_path())
            store = PetStore(database)
            store.put_account(202, "账号202", 55)
            store.put_account(101, "账号101", 55)
            store.flush()
            database.execute("UPDATE accounts SET last_seen = ? WHERE uid = ?", (1.0, 202))
            database.execute("UPDATE accounts SET last_seen = ? WHERE uid = ?", (2.0, 101))
            store.close()
            database.close()

            key_store = KeyStore(keys_dir())
            key_store.save_session(SessionCheckpoint(
                "flow-resumed", SYNTH_KEY, (202, "账号202", 55), server_sequence=10,
            ))
            key_store.flush()
            key_store.close()

            context = build_app_context(autostart=False)
            try:
                self.assertEqual(context.pet_repository.consistent_snapshot().uid, 202)
                self.assertEqual(context.account_selection.accounts_payload()["selected_uid"], 202)
            finally:
                context.close()

    def test_last_selected_account_wins_over_latest_key_without_live_flow(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"SPRITELENS_DATA_ROOT": temp}):
            database = Database(database_path())
            store = PetStore(database)
            store.put_account(101, "账号101", 55)
            store.put_account(202, "账号202", 55)
            store.flush()
            store.close()
            database.close()

            settings = SettingsRepository(Path(temp) / "config.json")
            settings.set("account.last_uid", 202)
            key_store = KeyStore(keys_dir())
            key_store.save_session(SessionCheckpoint("flow-a", SYNTH_KEY, (101, "账号101", 55), server_sequence=10))
            key_store.save_session(SessionCheckpoint("flow-b", KEY_B, (202, "账号202", 55), server_sequence=10))
            key_store.save_latest(SYNTH_KEY, "flow-a")
            key_store.flush()
            key_store.close()

            context = build_app_context(autostart=False)
            try:
                self.assertEqual(context.pet_repository.consistent_snapshot().uid, 202)
                self.assertEqual(context.account_selection.accounts_payload()["selected_uid"], 202)
            finally:
                context.close()

    def test_single_live_account_replaces_remembered_offline_selection(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"SPRITELENS_DATA_ROOT": temp}):
            database = Database(database_path())
            store = PetStore(database)
            store.put_account(101, "账号101", 55)
            store.put_account(202, "账号202", 55)
            store.flush()
            store.close()
            database.close()

            settings = SettingsRepository(Path(temp) / "config.json")
            settings.set("account.last_uid", 202)
            key_store = KeyStore(keys_dir())
            key_store.save_session(SessionCheckpoint("flow-a", SYNTH_KEY, (101, "账号101", 55), server_sequence=10))
            key_store.save_latest(SYNTH_KEY, "flow-a")
            key_store.flush()
            key_store.close()

            context = build_app_context(autostart=False)
            try:
                context.monitor.on_chunk(StreamChunk(FLOW_A, "s2c", make_ack_frame(SYNTH_KEY), 1))
                brief = integer(1, 101) + message(3, "账号101".encode()) + integer(5, 55)
                login = make_data_frame(
                    SYNTH_KEY, 0x0102, message(2, message(1, brief)), sequence=11
                )
                context.monitor.on_chunk(StreamChunk(FLOW_A, "s2c", login, 2))
                self.assertEqual(context.account_selection.accounts_payload()["selected_uid"], 101)
                self.assertEqual(context.account_selection.accounts_payload()["live_uids"], [101])
            finally:
                context.close()

    def test_last_selected_account_is_fallback_when_latest_key_has_no_identity(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"SPRITELENS_DATA_ROOT": temp}):
            database = Database(database_path())
            store = PetStore(database)
            store.put_account(101, "账号101", 55)
            store.put_account(202, "账号202", 55)
            store.flush()
            store.close()
            database.close()

            settings = SettingsRepository(Path(temp) / "config.json")
            settings.set("account.last_uid", 202)
            key_store = KeyStore(keys_dir())
            key_store.save_session(SessionCheckpoint("flow-a", SYNTH_KEY, (101, "账号101", 55), server_sequence=10))
            key_store.save_session(SessionCheckpoint("flow-b", KEY_B))
            key_store.save_latest(KEY_B, "flow-b")
            key_store.flush()
            key_store.close()

            context = build_app_context(autostart=False)
            try:
                self.assertEqual(context.pet_repository.consistent_snapshot().uid, 202)
            finally:
                context.close()


if __name__ == "__main__":
    unittest.main()
