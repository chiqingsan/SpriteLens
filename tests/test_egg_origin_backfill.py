"""历史收蛋来源回放与补录写库的回归测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from spritelens.domain.egg_box import EggParent, EggPickupOrigin, extract_eggs
from spritelens.events import PacketEvent
from spritelens.repositories.database import Database
from spritelens.repositories.egg_store import EggStore
from spritelens.services.egg_origin_backfill import EggOriginScanner, iter_event_stream, iter_events
from tests.test_egg_box import _egg_row, _event, _field as _bag_field, _identity_event
from tests.test_home import _actor_node, _egg_actor_node, _field, _nested_home_event, _scene_event

UID = 42
SESSION = "s1"
MOTHER_ACTOR = 9518406239959121930
FATHER_ACTOR = 9518406239959121931


def _row(ts: float, *, session: str = SESSION, direction: str = "s2c", opcode: int = 0x0152,
         name: str = "event", decoded: list[dict] | None = None) -> str:
    return json.dumps(
        {
            "ts": ts,
            "session": session,
            "direction": direction,
            "opcode": f"0x{opcode:04X}",
            "name": name,
            "payload_len": 0,
            "decoded": decoded or [],
        },
        ensure_ascii=False,
        # 与 event_logger 一致：bytes 字段（宠物名等）写入时转可读文本。
        default=lambda value: value.decode("utf-8", errors="replace")
        if isinstance(value, (bytes, bytearray)) else str(value),
    )


def _request(ts: float, actor_id: int = 901) -> PacketEvent:
    return PacketEvent(ts, SESSION, "c2s", 0x0137, "ZoneSceneNpcNextActReq", 0,
                       [_bag_field(1, actor_id), _bag_field(2, 830000165)])


def _reward(ts: float, instance_id: int = 5897) -> PacketEvent:
    event = _event(_egg_row(instance_id), opcode=0x0243)
    return replace(event, ts=ts, session_id=SESSION,
                   decoded=[*event.decoded, _bag_field(2, 13), _bag_field(3, 223)])


def _home_events() -> list[PacketEvent]:
    """身份 → 场景 30001 → 家园快照（学院窝 + 母本 + 父本 + 场景蛋）。"""
    residents = [
        _actor_node(MOTHER_ACTOR, 70001, 10001, 90001, "护主犬", (120, -30, 4)),
        _actor_node(FATHER_ACTOR, 70002, 10002, 90002, "候选父本", (0, 0, 0)),
        _field(7, None, children=_egg_actor_node(901, 90001, 1001071)),
    ]
    return [
        replace(_identity_event(UID), ts=0.0, session_id=SESSION),
        replace(_scene_event(30001, session_id=SESSION), ts=0.1),
        replace(_nested_home_event(owner_uid=UID, session_id=SESSION, residents=residents), ts=0.2),
    ]


class EventLogParsingTest(unittest.TestCase):
    def test_iter_events_skips_unparsable_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "eventlog_20261028.jsonl"
            path.write_text(
                "\n".join([
                    _row(1.5, opcode=0x0137, direction="c2s", name="ZoneSceneNpcNextActReq",
                         decoded=[_bag_field(1, 901)]),
                    "写到一半的坏行",
                    _row(2.5),
                ]) + "\n",
                encoding="utf-8",
            )
            events = list(iter_events(path))

        self.assertEqual([event.ts for event in events], [1.5, 2.5])
        self.assertEqual(events[0].opcode, 0x0137)
        self.assertEqual(events[0].decoded, [_bag_field(1, 901)])

    def test_iter_event_stream_merges_parts_by_ts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "eventlog_20261028.jsonl"
            part = Path(tmp) / "eventlog_20261028_p01.jsonl"
            base.write_text("\n".join(_row(ts) for ts in (1.0, 3.0)) + "\n", encoding="utf-8")
            part.write_text("\n".join(_row(ts) for ts in (2.0, 4.0)) + "\n", encoding="utf-8")

            merged = [(source, event.ts) for source, event in iter_event_stream([base, part])]

        self.assertEqual([ts for _, ts in merged], [1.0, 2.0, 3.0, 4.0])
        self.assertEqual(merged[1][0], part.name)


class EggOriginScannerTest(unittest.TestCase):
    def test_links_request_and_reward_into_pickup_origin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            earlier = Path(tmp) / "eventlog_20261028_p06.jsonl"
            later = Path(tmp) / "eventlog_20261028_p07.jsonl"
            early = _home_events()
            earlier.write_text("\n".join(
                _row(event.ts, direction=event.direction, opcode=event.opcode,
                     name=event.opcode_name, decoded=event.decoded) for event in early
            ) + "\n", encoding="utf-8")
            later.write_text("\n".join([
                _row(_request(1.0).ts, direction="c2s", opcode=0x0137,
                     name="ZoneSceneNpcNextActReq", decoded=_request(1.0).decoded),
                _row(_reward(1.05).ts, direction="s2c", opcode=0x0243,
                     name="ZoneGoodsRewardNotify", decoded=_reward(1.05).decoded),
            ]) + "\n", encoding="utf-8")

            scanner = EggOriginScanner()
            for source, event in iter_event_stream([earlier, later]):
                scanner.feed(event, source)

        self.assertEqual(len(scanner.records), 1)
        record = scanner.records[0]
        self.assertEqual((record.uid, record.instance_id), (UID, 5897))
        self.assertEqual(record.source, later.name)
        origin = record.origin
        self.assertEqual(origin.actor_id, 901)
        self.assertEqual((origin.nest_guid, origin.nest_kind), ("90001", "academy"))
        self.assertEqual(origin.nest_config_id, 1001072)
        self.assertEqual(origin.mother, EggParent(70001, "护主犬", 10001))
        self.assertEqual(origin.fathers, (EggParent(70002, "候选父本", 10002),))
        self.assertAlmostEqual(origin.observed_at, 1.05)
        self.assertEqual(origin.mother_nature_id, 0)

    def test_reward_without_request_is_counted_not_recorded(self) -> None:
        scanner = EggOriginScanner()
        for event in [*_home_events(), _reward(1.05)]:
            scanner.feed(event, "eventlog_20261028_p07.jsonl")

        self.assertEqual(scanner.records, ())
        self.assertEqual(scanner.unmatched_rewards, 1)

    def test_other_pickup_options_and_actors_do_not_link(self) -> None:
        """非收蛋交互选项的 0x0137 不产生关联。"""
        scanner = EggOriginScanner()
        for event in _home_events():
            scanner.feed(event, "p06")
        unknown = replace(_request(1.0), decoded=[_bag_field(1, 901), _bag_field(2, 830000999)])
        scanner.feed(unknown, "p07")
        scanner.feed(_reward(1.05), "p07")

        self.assertEqual(scanner.records, ())
        self.assertEqual(scanner.unmatched_rewards, 1)


class EggStorePickupMergeTest(unittest.TestCase):
    def test_merges_only_pickup_and_keeps_existing(self) -> None:
        origin = EggPickupOrigin(
            actor_id=901,
            nest_guid="90001",
            nest_kind="academy",
            nest_config_id=1001072,
            mother=EggParent(70001, "护主犬", 10001),
            fathers=(),
            observed_at=1.05,
            pairing_stale=False,
            mother_nature_id=3,
        )
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "db.sqlite")
            store = EggStore(db, flush_interval=60.0)
            try:
                store.put(UID, extract_eggs(_event(_egg_row(701), _egg_row(702))))
                store.flush()
                before = _details(db)

                result = store.put_pickups(UID, {701: origin, 703: origin})
                self.assertEqual((result.applied, result.kept, result.missing), (1, 0, (703,)))
                again = store.put_pickups(UID, {701: replace(origin, nest_guid="other")})
                self.assertEqual((again.applied, again.kept), (0, 1))
                after = _details(db)
            finally:
                store.close()
                db.close()

        self.assertEqual(_without_pickup(after[701]), _without_pickup(before[701]))
        self.assertEqual(after[701]["pickup"]["nest_guid"], "90001")
        self.assertEqual(after[701]["pickup"]["mother"]["instance_id"], 70001)
        self.assertEqual(after[701]["pickup"]["mother_nature_id"], 3)
        self.assertIsNone(after[702]["pickup"])


def _details(db: Database) -> dict[int, dict]:
    rows = db.query("SELECT instance_id, detail_json FROM eggs WHERE uid = ?", (UID,))
    return {int(row["instance_id"]): json.loads(row["detail_json"]) for row in rows}


def _without_pickup(detail: dict) -> dict:
    return {key: value for key, value in detail.items() if key != "pickup"}


if __name__ == "__main__":
    unittest.main()
