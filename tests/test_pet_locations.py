"""真实登录路径、空位保留、移动增量及离线恢复的回归。"""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from spritelens.domain.identity import extract_identity
from spritelens.domain.pet_locations import Backpack, PetBox, PetLocation, update_backpack, update_locations
from spritelens.domain.pets import extract_pets
from spritelens.protocol.opcodes import OpcodeCatalog
from spritelens.protocol.schema import load_library
from spritelens.repositories.database import Database
from spritelens.repositories.pet_store import PetStore
from spritelens.events import PacketEvent
from spritelens.services.pet_repository import PetRepository
from tests._synth import make_varint
from tests.test_persistence import identity_event

ROOT = Path(__file__).resolve().parent.parent


def integer(no, value):
    return make_varint(no << 3) + make_varint(value)


def message(no, value):
    return make_varint((no << 3) | 2) + make_varint(len(value)) + value


def login_event(avatar_url: str = ""):
    brief = integer(1, 123) + message(3, "测试角色".encode()) + integer(5, 55)
    if avatar_url:
        brief += message(9, avatar_url.encode())
    slots = [0, 0, 26925] + [0] * 27
    box = integer(1, 2) + b"".join(integer(3, gid) for gid in slots)
    backpack = message(3, box)
    payload = message(2, message(1, brief) + message(4, message(9, backpack)))
    library = load_library(ROOT / "data/schemas")
    mapping = OpcodeCatalog.load(ROOT / "data/schemas/opcodes.json").lookup(0x0102)
    decoded = library.decode(payload, mapping.message)
    return PacketEvent(0, "test", "s2c", 0x0102, mapping.name, len(payload), decoded)


def move_event(gid, box, slot, team=0, direction="s2c"):
    fields = [{"no": no, "raw": value} for no, value in ((1, gid), (2, team), (3, box), (4, slot))]
    return PacketEvent(0, "test", direction, 0x1111, "move", 0, [{"type": "PetBoxPetChange", "children": fields}])


def team_event(teams, team_type=1, main=0, direction="s2c"):
    children = [{"no": 1, "raw": main}, {"no": 4, "raw": team_type}]
    for gids in teams:
        children.append({"no": 2, "type": "PetTeam", "children": [
            {"no": 2, "type": "PetTeam_PetInfo", "children": [{"no": 1, "raw": gid}] if gid else []} for gid in gids]})
    node = {"name": "team_info", "type": "PetTeamInfo", "children": children}
    return PacketEvent(0, "test", direction, 0x1888, "swap", 0, [
        {"name": "ret_info", "children": [{"name": "goods_change_info", "children": [{"name": "changes", "children": [node]}]}]}])


class LocationTest(unittest.TestCase):
    def test_cached_role_is_distinct_from_live_identity_and_login_push_replaces_it(self):
        import aiohttp
        from spritelens.web.server import LocalServer
        from tests.test_web_server import _make_context
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = Database(root / "db.sqlite")
            store = PetStore(db, flush_interval=60)
            store.put_account(123, "上次角色", 50)
            store.flush()
            context = _make_context(root, [])
            context.pet_repository._store = store
            context.pet_repository.load_last_account()
            self.assertIsNone(context.pet_repository.identity)
            self.assertEqual(context.pet_repository.cached_identity.name, "上次角色")
            server = LocalServer(context, token="cached-role", port=0)
            server.start()
            async def verify():
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(f"http://127.0.0.1:{server.port}/ws?token=cached-role") as socket:
                        initial = await socket.receive_json(timeout=3)
                        self.assertIsNone(initial["identity"])
                        self.assertEqual(initial["cached_identity"], {"uid": 123, "name": "上次角色", "level": 50})
                        context.pet_repository.handle_packet(login_event())
                        updated = await socket.receive_json(timeout=3)
                        self.assertEqual(updated["identity"], {"uid": 123, "name": "测试角色", "level": 55})
                        self.assertEqual(updated["cached_identity"], updated["identity"])
            try:
                asyncio.run(verify())
            finally:
                server.stop(); context.close(); store.close(); db.close()

    def test_friend_mirror_pets_are_excluded_and_history_mark_survives_restart(self):
        from tests.test_pets import _named_pet_node, _named_event
        from spritelens.view_models.pet_vm import PetViewModel
        from spritelens.web.payloads import pets_payload
        mirror = _named_pet_node(2181071761, 410113, "彩蝶鲨".encode(), 60)
        mirror["name"] = "mirror_pet_data"
        mirror["type"] = "PetData"
        event = PacketEvent(0, "test", "s2c", 0x15FD, "ZonePetTeamFriendGetMirrorPetDataRsp", 0, [mirror])
        self.assertEqual(extract_pets(event), [])
        parsed = extract_pets(event, include_non_owned=True)[0]
        self.assertTrue(parsed.is_mirror_pet)
        self.assertFalse(parsed.is_trial_pet)
        with tempfile.TemporaryDirectory() as temporary:
            db = Database(Path(temporary) / "db.sqlite")
            store = PetStore(db, flush_interval=60)
            try:
                store.put(123, [replace(parsed, is_mirror_pet=False)])
                store.flush()
                repo = PetRepository(store)
                repo.load_persisted(123)
                repo.handle_packet(identity_event(uid=123))
                repo.handle_packet(_named_event("s2c", [_named_pet_node(12, 410113, "彩蝶鲨".encode(), 60)]))
                repo.handle_packet(move_event(12, 2, 8))
                repo.handle_packet(event)
                store.flush()
                restored = PetRepository(store)
                restored.load_persisted(123)
                payload = pets_payload(PetViewModel(restored), None)
                self.assertEqual([pet["gid"] for pet in payload["pets"]], [12])
                self.assertEqual(payload["backpack"]["unlocated_total"], 0)
                self.assertTrue(next(pet for pet in store.load(123) if pet.gid == parsed.gid).is_mirror_pet)
            finally:
                store.close(); db.close()

    def test_trial_duplicates_do_not_hide_owned_dimo_or_return_after_restart(self):
        from tests.test_pets import _named_pet_node, _named_event
        from spritelens.view_models.pet_vm import PetViewModel
        from spritelens.web.payloads import pets_payload
        owned = _named_pet_node(6, 3004002, "迪莫".encode(), 60)
        trial = _named_pet_node(2164300865, 3004002, "迪莫".encode(), 60)
        trial["children"].append({"no": 81, "name": "is_trial_pet", "raw": 1})
        event = _named_event("s2c", [owned, trial])
        self.assertEqual([pet.gid for pet in extract_pets(event)], [6])
        self.assertEqual(len(extract_pets(event, include_non_owned=True)), 2)
        with tempfile.TemporaryDirectory() as temporary:
            db = Database(Path(temporary) / "db.sqlite")
            store = PetStore(db, flush_interval=60)
            # 旧版本误收入库，重新收到明确试用标记后修正，保留原记录。
            store.put(123, [replace(extract_pets(event, include_non_owned=True)[1], is_trial_pet=False)])
            store.flush()
            repo = PetRepository(store)
            repo.load_persisted(123)
            repo.handle_packet(identity_event(uid=123))
            repo.handle_packet(event)
            repo.handle_packet(move_event(6, 2, 7))
            store.flush()
            restored = PetRepository(store)
            restored.load_persisted(123)
            payload = pets_payload(PetViewModel(restored), None)
            self.assertEqual(payload["total"], 1)
            self.assertEqual(payload["backpack"]["unlocated_total"], 0)
            self.assertEqual(payload["pets"][0]["name"], "迪莫")
            self.assertEqual(payload["pets"][0]["location"], {"box_id": 2, "slot": 7, "row": 2, "column": 1})
            self.assertTrue(next(pet for pet in store.load(123) if pet.gid == 2164300865).is_trial_pet)
            store.close(); db.close()

    def test_history_restore_does_not_duplicate_live_box_or_team_members(self):
        with tempfile.TemporaryDirectory() as temporary:
            db = Database(Path(temporary) / "db.sqlite")
            store = PetStore(db, flush_interval=60)
            store.put_backpack(123, Backpack({2: PetBox(2, (1, 2) + (0,) * 28)},
                                           (PetBox(1, (3,) + (0,) * 5),)))
            store.flush()
            repo = PetRepository(store)
            repo.handle_packet(move_event(3, 7, 4))
            repo.handle_packet(team_event([[1], [], []]))
            repo.load_persisted(123)
            restored = repo.backpack()
            self.assertEqual(restored.boxes[2].slots[:2], (0, 2))
            self.assertEqual(restored.teams[0].slots[0], 1)
            self.assertEqual(restored.locations()[3], PetLocation(7, 4))
            self.assertNotIn(1, restored.locations())
            store.close(); db.close()

            db = Database(Path(temporary) / "box.sqlite")
            store = PetStore(db, flush_interval=60)
            store.put_backpack(123, Backpack(teams=(PetBox(1, (3,) + (0,) * 5),)))
            store.flush()
            repo = PetRepository(store)
            repo.handle_packet(move_event(3, 7, 4))
            repo.load_persisted(123)
            self.assertEqual(repo.backpack().teams[0].slots[0], 0)
            self.assertEqual(repo.location(3), PetLocation(7, 4))
            store.close(); db.close()

    def test_team_swap_updates_actual_slot_and_excludes_mirror_and_other_types(self):
        before = Backpack({2: PetBox(2, (0, 0, 39165) + (0,) * 27)})
        after = update_backpack(team_event([[39165, 2, 3, 4, 5, 6], [7, 8, 9, 10, 11, 12], [13, 14, 15, 16, 17, 18]]), before)
        self.assertNotIn(39165, after.locations())
        self.assertEqual(after.boxes[2].slots[2], 0)
        self.assertEqual(after.teams[0].slots[0], 39165)
        second = update_backpack(team_event([[2, 3, 4, 5, 6], [7, 8, 9, 39165, 11, 12], [13, 14, 15, 16, 17, 18]], main=1), after)
        self.assertEqual(second.teams[1].slots[3], 39165)
        self.assertEqual(second.teams[0].slots[-1], 0)
        self.assertEqual(second.active_team, 2)
        boxed = update_backpack(move_event(39165, 2, 25), second)
        self.assertEqual(boxed.locations()[39165], PetLocation(2, 25))
        self.assertNotIn(39165, boxed.teams[1].slots)
        self.assertIsNone(update_backpack(team_event([[1], [], []], team_type=5), boxed))
        self.assertIsNone(update_backpack(team_event([[1], [], []], direction="c2s"), boxed))
        mirror = team_event([[1], [], []])
        mirror.decoded[0]["children"][0]["children"][0]["children"][0]["children"][2]["children"].append({"no": 6, "raw": 1})
        self.assertIsNone(update_backpack(mirror, boxed))

    def test_team_payload_and_persistence_keep_empty_slots_and_unknown_location_count(self):
        from spritelens.view_models.pet_vm import PetViewModel
        from spritelens.web.payloads import pets_payload
        from tests.test_web_server import _pet
        with tempfile.TemporaryDirectory() as temporary:
            db = Database(Path(temporary) / "db.sqlite")
            store = PetStore(db, flush_interval=60)
            repo = PetRepository(store)
            repo.handle_packet(identity_event(uid=123))
            repo._pets = {1: _pet(1, name="队员", level=32)}
            store.put(123, repo.snapshot())
            repo.handle_packet(team_event([[1, 0, 0, 0, 0, 0], [], []], main=2))
            store.flush()
            restored = PetRepository(store)
            restored.load_persisted(123)
            vm = PetViewModel(restored)
            payload = pets_payload(vm, None)
            self.assertEqual(payload["pets"][0]["location"], {"team_id": 1, "slot": 1, "historical": True})
            self.assertEqual(payload["backpack"]["unlocated_total"], 0)
            self.assertEqual(payload["backpack"]["active_team"], 3)
            self.assertEqual(len(payload["backpack"]["teams"]), 3)
            self.assertEqual(payload["backpack"]["teams"][1]["slots"], [{"gid": 0, "state": "empty"}] * 6)
            store.close(); db.close()

    def test_full_box_preserves_empty_slots_and_name(self):
        event = login_event()
        def find(fields):
            for node in fields:
                if node.get("type") == "PetBox":
                    return node
                result = find(node.get("children") or [])
                if result:
                    return result
        find(event.decoded)["children"].append({"no": 5, "raw": "常用".encode()})
        backpack = update_backpack(event, Backpack())
        self.assertEqual(backpack.boxes[2].name, "常用")
        self.assertEqual(backpack.boxes[2].slots[:4], (0, 0, 26925, 0))
        self.assertFalse(backpack.boxes[2].historical)

    def test_partial_move_does_not_invent_empty_slots_and_invalid_is_ignored(self):
        backpack = update_backpack(move_event(1, 7, 24), Backpack())
        self.assertEqual(backpack.boxes[7].slots[23], 1)
        self.assertEqual(backpack.boxes[7].slots.count(None), 29)
        after = update_backpack(move_event(1, 2, 3), backpack)
        self.assertEqual(after.boxes[7].slots[23], 0)
        self.assertEqual(after.locations(), {1: PetLocation(2, 3)})
        self.assertIsNone(update_backpack(move_event(1, 2, 0), after))

    def test_payload_distinguishes_filtered_missing_empty_and_unknown(self):
        from spritelens.view_models.pet_vm import PetViewModel
        from spritelens.web.payloads import pets_payload
        from tests.test_web_server import _pet
        repo = PetRepository()
        repo._pets = {1: _pet(1, name="匹配", level=32), 2: _pet(2, name="其它", level=32), 4: _pet(4, name="未知位置", level=32)}
        repo._backpack = Backpack({2: PetBox(2, (0, 1, 2, 999, None) + (0,) * 25), 7: PetBox(7, (0,) * 30)})
        repo._locations = repo._backpack.locations()
        vm = PetViewModel(repo)
        vm.set_search("匹配")
        vm.set_sort("gid", descending=True)
        payload = pets_payload(vm, None)
        box = payload["backpack"]["boxes"][0]
        self.assertEqual([slot["state"] for slot in box["slots"][:5]], ["empty", "matched", "filtered", "missing", "unknown"])
        self.assertEqual(box["matched"], 1)
        self.assertEqual(box["unknown"], 1)
        self.assertEqual(payload["backpack"]["unlocated_total"], 1)
        self.assertEqual(payload["pets"][0]["location"]["slot"], 2)
        self.assertEqual(len(payload["backpack"]["boxes"][1]["slots"]), 30)

    def test_empty_box_survives_restart_without_pets_and_old_format_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            db = Database(Path(temporary) / "db.sqlite")
            store = PetStore(db, flush_interval=60)
            store.put_backpack(123, Backpack({8: PetBox(8, (0,) * 30, "空箱")}))
            store.flush()
            repo = PetRepository(store)
            repo.load_persisted(123)
            self.assertEqual(repo.backpack().boxes[8].slots, (0,) * 30)
            self.assertTrue(repo.backpack().boxes[8].historical)
            self.assertIsNone(repo.identity)
            store.close(); db.close()
        with self.assertRaises(ValueError):
            Backpack.restore([[1, 2, 3]])

    def test_account_switch_clears_empty_box_metadata(self):
        repo = PetRepository()
        repo.handle_packet(login_event())
        repo.handle_packet(identity_event(uid=456))
        self.assertEqual(repo.backpack().boxes, {})

    def test_catalog_decodes_login_identity_and_actual_empty_slots(self):
        event = login_event()
        identity = extract_identity(event)
        self.assertEqual((identity.uid, identity.name, identity.level), (123, "测试角色", 55))
        locations = update_locations(event, {999: PetLocation(8, 1)})
        self.assertEqual(locations, {26925: PetLocation(2, 3)})
        self.assertEqual(locations[26925].payload(), {"box_id": 2, "slot": 3, "row": 1, "column": 3})

    def test_login_platform_avatar_is_not_used_as_game_avatar(self):
        from spritelens.view_models import PetViewModel
        from spritelens.web.payloads import pet_summary_payload

        avatar_url = "https://example.com/platform-avatar.png"
        repo = PetRepository()
        repo.handle_packet(login_event(avatar_url))
        self.assertEqual(extract_identity(login_event(avatar_url)).avatar_url, "")
        vm = PetViewModel(repo)
        payload = pet_summary_payload(vm.view_with(vm.filters), None)
        self.assertNotIn("avatar_url", payload["identity"])
        self.assertNotIn("avatar_url", payload["cached_identity"])

    def test_move_empty_slot_replaces_target_and_removes_old_position(self):
        before = {1: PetLocation(7, 3), 2: PetLocation(7, 24)}
        after = update_locations(move_event(1, 7, 24), before)
        self.assertEqual(after, {1: PetLocation(7, 24)})
        self.assertEqual(after[1].payload()["row"], 4)
        self.assertEqual(after[1].payload()["column"], 6)
        self.assertEqual(update_locations(move_event(0, 7, 24), after), {})
        self.assertEqual(before[1], PetLocation(7, 3))

    def test_invalid_client_move_and_team_do_not_invent_box_positions(self):
        before = {1: PetLocation(2, 3)}
        self.assertIsNone(update_locations(move_event(1, 2, 8, direction="c2s"), before))
        self.assertIsNone(update_locations(move_event(1, 2, 31), before))
        self.assertEqual(update_locations(move_event(1, 1, 4, team=1), before), {})
        self.assertIsNone(extract_identity(replace(login_event(), direction="c2s")))

    def test_account_switch_clears_positions_and_move_changes_version(self):
        repo = PetRepository()
        repo.handle_packet(login_event())
        version = repo.version
        repo.handle_packet(move_event(26925, 7, 24))
        self.assertGreater(repo.version, version)
        repo.handle_packet(identity_event(uid=456))
        self.assertIsNone(repo.location(26925))

    def test_restart_preserves_medal_and_last_location(self):
        from tests.test_web_server import _pet
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "db.sqlite"
            db = Database(path)
            store = PetStore(db, flush_interval=60)
            store.put(123, [replace(_pet(26925, name="觅觅蝠", level=32), worn_medal_id=1010)])
            store.put_locations(123, {26925: PetLocation(2, 3)})
            store.put_locations(123, {26925: PetLocation(7, 24)})
            store.close(); db.close()
            reopened = Database(path); restored = PetStore(reopened)
            try:
                repo = PetRepository(restored)
                repo.load_persisted(123)
                self.assertEqual(repo.snapshot()[0].worn_medal_id, 1010)
                self.assertEqual(repo.location(26925), PetLocation(7, 24))
                self.assertIsNone(repo.identity)  # 历史箱位不冒充本次登录角色。
            finally:
                restored.close(); reopened.close()

    def test_worn_medal_is_parsed_without_inferred_threshold(self):
        from tests.test_persistence import pet_event
        event = pet_event([(1, "测试", 32)])
        event.decoded[0]["children"][0]["children"].append({"no": 73, "raw": 1010})
        self.assertEqual(extract_pets(event)[0].worn_medal_id, 1010)

    def test_late_login_pushes_role_and_box_location_to_api(self):
        import aiohttp
        from spritelens.web.server import LocalServer
        from tests.test_web_server import _make_context, _pet
        with tempfile.TemporaryDirectory() as temporary:
            context = _make_context(Path(temporary), [replace(_pet(26925, name="觅觅蝠", level=32), worn_medal_id=1010, mutation_type=9)])
            server = LocalServer(context, token="role-test", port=0)
            server.start()
            async def verify():
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(f"http://127.0.0.1:{server.port}/ws?token=role-test") as socket:
                        initial = await socket.receive_json(timeout=3)
                        self.assertIsNone(initial["identity"])
                        context.pet_repository.handle_packet(login_event())
                        updated = await socket.receive_json(timeout=3)
                        self.assertEqual(updated["identity"], {"uid": 123, "name": "测试角色", "level": 55})
                        async with session.get(f"http://127.0.0.1:{server.port}/api/pets", headers={"X-Local-Token": "role-test"}) as response:
                            row = (await response.json())["pets"][0]
                            self.assertEqual(row["location"]["column"], 3)
                            self.assertTrue(row["is_colorful"])
                        async with session.get(
                            f"http://127.0.0.1:{server.port}/api/pets/26925?uid=123&version=0",
                            headers={"X-Local-Token": "role-test"},
                        ) as response:
                            detail = (await response.json())["pet"]
                            self.assertEqual(detail["worn_medal_id"], 1010)
            try:
                asyncio.run(verify())
            finally:
                server.stop(); context.close()
