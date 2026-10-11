"""家园：0x014A 快照提取（按真实帧字段号构造合成树）、聚合与载荷。"""

from __future__ import annotations

import unittest

from spritelens.domain.home import extract_home
from spritelens.services.home_repository import HomeRepository
from spritelens.services.monitor_service import PacketEvent
from spritelens.web.payloads import home_payload


def _field(no: int, raw: object = None, text: str | None = None, children: list[dict] | None = None) -> dict:
    node = {"no": no, "name": f"field_{no}", "type": "", "value": "", "raw": raw}
    if text is not None:
        node["text"] = text
    if children is not None:
        node["children"] = children
    return node


def _position(x: int, y: int, z: int) -> dict:
    return _field(7, None, children=[_field(1, None, children=[
        _field(1, x), _field(2, y), _field(3, z)])])


def _resident_event(actor_id: int, name: str, gender: int = 1, level: int = 40) -> PacketEvent:
    resident = _field(11, None, children=[
        _field(1, 10),
        _field(2, actor_id),
        _field(5, 1778318003),
        _position(1284, -882, 61),
        _field(10, level),
        _field(11, gender),
        _field(12, None, text=name),
        _field(13, gender),
    ])
    return PacketEvent(
        ts=0.0, session_id="s", direction="s2c", opcode=0x014A, opcode_name="ZoneGetHomeSceneRsp",
        payload_len=0,
        decoded=[
            _field(1, None, children=[_field(1, 0)]),
            _field(7, None, children=[_field(1, 10), _field(11, None, children=[resident])]),
        ],
    )


def _snapshot_event() -> PacketEvent:
    # 实证结构：家具实体 field1 直接 = configId，guid = field19（int）
    nest = _field(11, None, children=[
        _field(1, 710069),
        _field(2, 2097178),
        _field(19, 0x70182c0b68100000),
        _position(100, 200, 1),
    ])
    plain = _field(11, None, children=[
        _field(1, 150011),
        _field(19, 0x65d37b61f2690),  # 无 guid 的杂项实体会被排除
    ])
    return PacketEvent(
        ts=0.0, session_id="s", direction="s2c", opcode=0x014A, opcode_name="x", payload_len=0,
        decoded=[
            _field(7, None, children=[_field(1, 10), _field(11, None, children=[nest, plain])]),
        ],
    )


class ExtractHomeTests(unittest.TestCase):
    def test_resident(self) -> None:
        snap = extract_home(_resident_event(0x84182c0b68a0000a, "护主犬"))
        self.assertIsNotNone(snap)
        self.assertEqual(snap.room_level, 10)
        self.assertEqual(len(snap.residents), 1)
        r = snap.residents[0]
        self.assertEqual(r.name, "护主犬")
        self.assertEqual(r.gender, 1)
        self.assertEqual(r.level, 40)
        self.assertEqual(r.position, (1284, -882, 61))

    def test_furniture_and_nests(self) -> None:
        snap = extract_home(_snapshot_event())
        self.assertEqual(len(snap.furniture), 2)  # 窝 + 带 guid 的普通家具
        nests = snap.nests
        self.assertEqual(len(nests), 1)
        self.assertEqual(nests[0].name, "普通小窝")
        self.assertEqual(nests[0].kind, "ordinary")
        self.assertEqual(nests[0].guid, "70182c0b68100000")

    def test_non_snapshot_ignored(self) -> None:
        event = PacketEvent(0.0, "s", "s2c", 0x0414, "delta", 0, [])
        self.assertIsNone(extract_home(event))


class HomeRepositoryTests(unittest.TestCase):
    def test_snapshot_and_delta_count(self) -> None:
        repo = HomeRepository()
        repo.handle_packet(_resident_event(123, "喵喵"))
        self.assertIsNotNone(repo.snapshot())
        base = repo.version()
        repo.handle_packet(PacketEvent(0.0, "s", "s2c", 0x0414, "delta", 0, []))
        self.assertEqual(repo.pending_deltas(), 1)
        self.assertEqual(repo.version(), base + 1)
        # 快照仍在（增量未合并）
        self.assertIsNotNone(repo.snapshot())


class HomePayloadTests(unittest.TestCase):
    def test_empty(self) -> None:
        payload = home_payload(HomeRepository(), None)
        self.assertFalse(payload["available"])

    def test_available(self) -> None:
        repo = HomeRepository()
        repo.handle_packet(_resident_event(123, "喵喵"))
        payload = home_payload(repo, None)
        self.assertTrue(payload["available"])
        self.assertEqual(payload["residents"][0]["name"], "喵喵")


class FlowerTests(unittest.TestCase):
    """0x0375 花田帧提取（按真实帧结构构造）。"""

    def _flower_event(self) -> PacketEvent:
        # 实测层级：field2/field3 各一个节点，children 为重复 field1 子消息
        own = {"no": 2, "name": "f2", "type": "", "value": "", "raw": None, "children": [
            {"no": 1, "name": "f1", "type": "", "value": "", "raw": None, "children": [
                {"no": 1, "name": "f1", "type": "", "value": "20131", "raw": 20131},
                {"no": 3, "name": "f3", "type": "", "value": "4", "raw": 4},
                {"no": 10, "name": "f10", "type": "", "value": "1791748800", "raw": 1791748800},
                {"no": 13, "name": "f13", "type": "", "value": "130308", "raw": 130308},
                {"no": 19, "name": "f19", "type": "", "value": "1", "raw": 1},
            ]},
        ]}
        friend = {"no": 3, "name": "f3", "type": "", "value": "", "raw": None, "children": [
            {"no": 1, "name": "f1", "type": "", "value": "", "raw": None, "children": [
                {"no": 1, "name": "f1", "type": "", "value": "65516", "raw": 65516},
                {"no": 13, "name": "f13", "type": "", "value": "130310", "raw": 130310},
                {"no": 14, "name": "f14", "type": "", "value": "", "raw": None, "children": [
                    {"no": 1, "name": "h", "type": "", "value": "403695", "raw": 403695},
                    {"no": 2, "name": "w", "type": "", "value": "675368", "raw": 675368},
                    {"no": 3, "name": "v", "type": "", "value": "64", "raw": 64},
                ]},
            ]},
        ]}
        return PacketEvent(
            ts=0.0, session_id="s", direction="s2c", opcode=0x0375, opcode_name="x", payload_len=0,
            decoded=[
                {"no": 1, "name": "ok", "type": "", "value": "", "raw": None, "children": [
                    {"no": 1, "name": "code", "type": "", "value": "0", "raw": 0}]},
                own, friend,
            ],
        )

    def test_extract(self) -> None:
        from spritelens.domain.flowers import extract_flowers
        snap = extract_flowers(self._flower_event())
        self.assertIsNotNone(snap)
        self.assertEqual(len(snap.own), 1)
        self.assertEqual(snap.own[0].slot_id, 20131)
        self.assertEqual(snap.own[0].pet_conf_id, 130308)
        self.assertEqual(len(snap.friends), 1)
        self.assertEqual(snap.friends[0].height, 403695)
        self.assertEqual(snap.friends[0].owner, "friend")

    def test_repo_and_payload(self) -> None:
        from spritelens.services.flower_repository import FlowerRepository
        from spritelens.web.payloads import flowers_payload
        repo = FlowerRepository()
        repo.handle_packet(self._flower_event())
        payload = flowers_payload(repo, None, None)
        self.assertTrue(payload["available"])
        self.assertEqual(payload["own"][0]["pet_name"], "#130308")
        self.assertEqual(payload["friends"][0]["owner"], "friend")

    def test_non_flower_ignored(self) -> None:
        from spritelens.domain.flowers import extract_flowers
        self.assertIsNone(extract_flowers(
            PacketEvent(0.0, "s", "s2c", 0x0376, "x", 0, [])))


if __name__ == "__main__":
    unittest.main()
