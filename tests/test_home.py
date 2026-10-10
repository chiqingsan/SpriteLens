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


if __name__ == "__main__":
    unittest.main()
