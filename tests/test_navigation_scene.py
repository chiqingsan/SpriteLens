from __future__ import annotations

from dataclasses import replace
import unittest

from spritelens.domain.navigation_scene import NavigationScene
from spritelens.events import PacketEvent
from spritelens.web.ext_api import EXT_MAX_PAYLOAD, RING_MAX_EVENTS, ExtEventHub


def node(no, raw=None, children=None):
    return {"no": no, "raw": raw, **({"children": children} if children is not None else {})}


def npc(actor_id=10, option_id=293015, creator_id=None):
    base = [node(2, actor_id), node(8, children=[node(1, children=[
        node(1, 1000), node(2, 2000), node(3, 0)])])]
    npc_base = [node(1, 29401)]
    if creator_id is not None:
        npc_base.append(node(19, creator_id))
    return node(1, children=[node(11, children=[
        node(1, children=base),
        node(3, children=npc_base),
        node(5, children=[node(1, children=[node(1, option_id), node(2, 1)])]),
    ])])


def player(actor_id):
    return node(1, children=[node(12, children=[node(1, children=[node(2, actor_id)])])])


def packet(opcode, decoded, *, direction="s2c", uid=5, session="tcp", payload_len=50):
    return PacketEvent(1.0, session, direction, opcode, "test", payload_len, decoded, account_uid=uid)


class NavigationSceneTests(unittest.TestCase):
    def test_late_client_gets_interactables_after_ring_has_overflowed(self):
        hub = ExtEventHub()
        hub.submit(packet(0x0133, [node(17, 1), node(2, children=[
            node(1, (1 << 64) - 100), node(2, 200), node(3, 0)])], direction="c2s"))
        # 大 AOI 只保留精简投影，不受事件体积限制和 200 条回看环覆盖。
        hub.submit(packet(0x014A, [dict(npc(), no=7)], payload_len=EXT_MAX_PAYLOAD + 1))
        for _ in range(RING_MAX_EVENTS + 1):
            hub.submit(packet(0x1324, []))
        snapshot = hub.navigation_snapshot(5, "tcp")
        self.assertEqual(snapshot["position"], (-100, 200, 0))
        self.assertEqual(snapshot["position_seq"], 1)
        self.assertEqual(snapshot["actors"][0]["actor_id"], "10")
        self.assertIsNone(hub.navigation_snapshot(6, "tcp"))
        self.assertIsNone(hub.navigation_snapshot(5, "other"))
        hub.close()
        self.assertIsNone(hub.navigation_snapshot(5, "tcp"))

    def test_add_remove_scene_and_battle_lifecycle(self):
        scene = NavigationScene()
        add = packet(0x0414, [node(1, children=[node(1, children=[npc()])])])
        scene.submit(add, 1)
        self.assertEqual(len(scene.snapshot()["actors"]), 1)
        scene.submit(packet(0x0137, [node(1, 10), node(2, 293015)], direction="c2s"), 2)
        scene.submit(packet(0x1316, [node(6, children=[node(1, 77)])]), 3)
        self.assertTrue(scene.snapshot()["in_battle"])
        self.assertFalse(scene.snapshot()["actors"])
        scene.submit(packet(0x132C, [node(1, children=[node(19, 99)])]), 4)
        self.assertTrue(scene.snapshot()["in_battle"])
        scene.submit(packet(0x132C, [node(1, children=[node(19, 77)])]), 5)
        self.assertFalse(scene.snapshot()["in_battle"])
        scene.submit(add, 6)
        scene.submit(packet(0x0414, [node(1, children=[node(2, children=[node(1, 10)])])]), 7)
        self.assertFalse(scene.snapshot()["actors"])
        scene.submit(add, 8)
        scene.submit(packet(0x015C, [node(11, 2)]), 9)
        self.assertEqual(scene.snapshot()["scene_id"], 2)
        self.assertEqual(scene.snapshot()["scene_generation"], 9)
        self.assertFalse(scene.snapshot()["actors"])

    def test_owner_and_self_actor_are_exposed_for_encounter_ownership(self):
        scene = NavigationScene()
        scene.submit(packet(0x0152, [node(2, 1), node(11, children=[node(12, children=[node(1, children=[
            node(2, 555), node(8, children=[node(1, children=[
                node(1, 100), node(2, 200), node(3, 0)])])])])])]), 1)
        scene.submit(packet(0x014A, [dict(npc(10, creator_id=555), no=7),
                                     dict(npc(20, creator_id=777), no=7),
                                     dict(npc(30), no=7)]), 2)
        snapshot = scene.snapshot()
        self.assertEqual(snapshot["self_actor_id"], "555")
        creators = {row["actor_id"]: row["creator_id"] for row in snapshot["actors"]}
        self.assertEqual(creators, {"10": "555", "20": "777", "30": None})

    def test_visible_players_are_reported_for_ownership_fallback(self):
        scene = NavigationScene()
        scene.submit(packet(0x014A, [dict(player(777), no=7),
                                     dict(npc(10, creator_id=777), no=7),
                                     dict(npc(20), no=7)]), 1)
        snapshot = scene.snapshot()
        self.assertEqual(snapshot["player_actor_ids"], ["777"])
        self.assertEqual(sorted(row["actor_id"] for row in snapshot["actors"]), ["10", "20"])

    def test_teleport_notify_also_reports_self_actor(self):
        scene = NavigationScene()
        scene.submit(packet(0x015C, [node(11, 7), node(14, children=[node(1, children=[
            node(1, 300), node(2, 400), node(3, 0)])]), node(21, children=[
                node(12, children=[node(1, children=[node(2, 999)])])])]), 3)
        snapshot = scene.snapshot()
        self.assertEqual(snapshot["self_actor_id"], "999")
        self.assertEqual(snapshot["position"], (300, 400, 0))

    def test_move_request_reports_player_heading(self):
        scene = NavigationScene()
        scene.submit(packet(0x0133, [node(17, 1), node(2, children=[
            node(1, 100), node(2, 200), node(3, 0)]),
            node(3, children=[node(1, 0), node(2, 0), node(3, (1 << 32) - 1225)])],
            direction="c2s"), 1)
        self.assertEqual(scene.snapshot()["heading"], -1225)
        # to_rot 缺失时回落 ctrl_rot；两处都没有则保持上一次朝向。
        scene.submit(packet(0x0133, [node(17, 1), node(2, children=[
            node(1, 300), node(2, 400), node(3, 0)]),
            node(15, children=[node(1, 0), node(2, 3548), node(3, 900)])],
            direction="c2s"), 2)
        self.assertEqual(scene.snapshot()["heading"], 900)
        scene.submit(packet(0x0133, [node(17, 1), node(2, children=[
            node(1, 500), node(2, 600), node(3, 0)])], direction="c2s"), 3)
        self.assertEqual(scene.snapshot()["heading"], 900)
        self.assertEqual(scene.snapshot()["position"], (500, 600, 0))

    def test_session_and_account_snapshots_are_isolated(self):
        hub = ExtEventHub()
        event = packet(0x014A, [dict(npc(), no=7)])
        hub.submit(event)
        hub.submit(replace(event, account_uid=6, decoded=[dict(npc(20), no=7)]))
        self.assertEqual(hub.navigation_snapshot(5, "tcp")["actors"][0]["actor_id"], "10")
        self.assertEqual(hub.navigation_snapshot(6, "tcp")["actors"][0]["actor_id"], "20")
        hub.session_closed("tcp")
        self.assertIsNone(hub.navigation_snapshot(5, "tcp"))
        self.assertIsNone(hub.navigation_snapshot(6, "tcp"))

    def test_capture_restart_does_not_reuse_previous_scene(self):
        hub = ExtEventHub()
        hub.submit(packet(0x014A, [dict(npc(), no=7)]), generation=1)
        self.assertIsNotNone(hub.navigation_snapshot(5, "tcp", generation=1))
        self.assertIsNone(hub.navigation_snapshot(5, "tcp", generation=2))
        hub.submit(packet(0x1324, []), generation=2)
        self.assertIsNone(hub.navigation_snapshot(5, "tcp", generation=2))


if __name__ == "__main__":
    unittest.main()
