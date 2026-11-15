"""宠物语义层与仓库聚合测试：形状提取、合并去重、管线集成。"""

import json
import tempfile
import unittest
from pathlib import Path

from spritelens.capture.base import StreamChunk
from spritelens.capture.key_store import KeyStore
from spritelens.domain.pets import extract_pets
from spritelens.protocol.opcodes import OpcodeCatalog, OpcodeInfo
from spritelens.protocol.records import Direction
from spritelens.protocol.schema import load_library
from spritelens.services.monitor_service import MonitorService
from spritelens.services.pet_repository import PetRepository
from tests._synth import SYNTH_KEY, make_ack_frame, make_data_frame, make_varint

SESSION = "10.9.9.1:7000"
OPCODE_PET_PAGE = 0x134A


def _brief(gid: int, conf_id: int, name: bytes, level: int) -> bytes:
    """按 PetBriefInfo 字段号合成一条宠物对象。"""
    return (
        make_varint((1 << 3) | 0) + make_varint(gid)
        + make_varint((2 << 3) | 0) + make_varint(conf_id)
        + make_varint((3 << 3) | 2) + make_varint(len(name)) + name
        + make_varint((10 << 3) | 0) + make_varint(level)
    )


def _page_rsp(pets: list[bytes]) -> bytes:
    """ZoneGetPetInfoByPageRsp{4: PetDataInfoList{1: repeated PetBriefInfo}}。"""
    listing = b"".join(make_varint((1 << 3) | 2) + make_varint(len(p)) + p for p in pets)
    return make_varint((4 << 3) | 2) + make_varint(len(listing)) + listing


def _named_pet_node(gid: int, conf_id: int, name: bytes, level: int) -> dict:
    """schema 命中后 decoded 里一个宠物节点应有的形状（手工构造）。"""
    return {
        "no": 1, "name": "pet_data", "type": "", "value": "", "raw": None,
        "children": [
            {"no": 1, "name": "gid", "type": "uint32", "value": str(gid), "raw": gid},
            {"no": 2, "name": "conf_id", "type": "uint32", "value": str(conf_id), "raw": conf_id},
            {"no": 3, "name": "name", "type": "bytes", "value": f'"{name.decode()}"', "raw": name},
            {"no": 10, "name": "level", "type": "uint32", "value": str(level), "raw": level},
        ],
    }


def _named_event(direction: str, pet_nodes: list[dict]):
    class FakeEvent:
        pass

    event = FakeEvent()
    event.direction = direction
    event.decoded = [{"no": 4, "name": "pet_info", "type": "", "value": "", "raw": None,
                      "children": pet_nodes}]
    return event


class ExtractPetsTest(unittest.TestCase):
    def test_extract_from_named_tree(self):
        event = _named_event("s2c", [
            _named_pet_node(1001, 20508, "喵喵".encode(), 35),
            _named_pet_node(1002, 20510, b"Dog", 12),
        ])
        pets = extract_pets(event)
        self.assertEqual(len(pets), 2)
        self.assertEqual(pets[0].gid, 1001)
        self.assertEqual(pets[0].name, "喵喵")
        self.assertEqual(pets[0].level, 35)
        self.assertEqual(pets[1].name, "Dog")

    def test_unnamed_tree_yields_nothing(self):
        """无 schema 时字段是 field_N 占位名，指纹不命中且不抛错。"""
        payload = _page_rsp([_brief(1, 2, b"x", 3)])

        tree = [
            {"no": f.no, "name": f.display_name(), "type": "", "value": f.display_value(),
             "raw": f.value, "children": [
                 {"no": c.no, "name": c.display_name(), "type": "", "value": c.display_value(),
                  "raw": c.value, "children": [
                      {"no": g.no, "name": g.display_name(), "type": "", "value": g.display_value(),
                       "raw": g.value} for g in (c.children or [])]} for c in _wire_children(payload)]}
            for f in _wire_children(payload)
        ]

        class FakeEvent:
            direction = "s2c"
            decoded = tree

        self.assertEqual(extract_pets(FakeEvent()), [])

    def test_c2s_ignored(self):
        event = _named_event("c2s", [_named_pet_node(1, 2, b"x", 3)])
        self.assertEqual(extract_pets(event), [])

    def test_missing_optional_fields_default(self):
        node = _named_pet_node(9, 9, b"", 1)
        node["children"] = node["children"][:3]  # 只留 gid/conf_id/name
        event = _named_event("s2c", [node])
        pets = extract_pets(event)
        self.assertEqual(len(pets), 1)
        self.assertEqual(pets[0].level, 0)
        self.assertFalse(pets[0].is_first_catch)
        self.assertEqual(pets[0].attributes, ())
        self.assertEqual(pets[0].skills, ())
        self.assertEqual(pets[0].height, 0)


def _v(no: int, raw: int) -> dict:
    return {"no": no, "name": f"field_{no}", "type": "varint", "value": str(raw), "raw": raw}


def _attr_group(race: int, talent: int, base: int, talent_add: int = 0, effort_add: int = 0) -> dict:
    """一个六维维度的 PetAttributeData 节点。"""
    return {
        "no": 0, "name": "", "type": "len", "value": "", "raw": None,
        "children": [
            _v(1, race), _v(2, talent), _v(3, base),
            _v(6, effort_add), _v(7, talent_add),
        ],
    }


def _attribute_info(groups: list[dict]) -> dict:
    """field 14：六维持器，字段号 1..6 依次对应 hp/atk/spa/def/spd/spe。"""
    return {
        "no": 14, "name": "field_14", "type": "len", "value": "", "raw": None,
        "children": [{**g, "no": i + 1} for i, g in enumerate(groups)],
    }


class ExtendedPetFieldsTest(unittest.TestCase):
    """v2 扩展字段：一律按字段号取值，不依赖 schema 命名。"""

    def _pet_node(self, extra: list[dict]) -> dict:
        node = _named_pet_node(1001, 2000671, "波波拉".encode(), 30)
        node["children"].extend(extra)
        return node

    def test_attributes_by_field_number(self):
        groups = [
            _attr_group(100, 24, 163, talent_add=8, effort_add=40),
            _attr_group(46, 0, 47, effort_add=20),
            _attr_group(102, 24, 101, talent_add=8, effort_add=20),
            _attr_group(75, 0, 70, effort_add=20),
            _attr_group(106, 24, 104, talent_add=8, effort_add=20),
            _attr_group(68, 0, 64, effort_add=20),
        ]
        event = _named_event("s2c", [self._pet_node([_attribute_info(groups)])])
        pet = extract_pets(event)[0]
        self.assertEqual(len(pet.attributes), 6)
        hp = pet.attribute("hp")
        self.assertEqual((hp.total_race, hp.talent, hp.base_value), (100, 24, 163))
        self.assertEqual(hp.final_value, 163 + 8 + 40)
        self.assertEqual(pet.attribute("spe").total_race, 68)
        # 未知槽位返回零值而非抛错
        self.assertEqual(pet.attribute("nope").final_value, 0)

    def test_skills_and_appearance_by_field_number(self):
        skills = {
            "no": 12, "name": "field_12", "type": "len", "value": "", "raw": None,
            "children": [
                {"no": 1, "name": "field_1", "type": "len", "value": "", "raw": None,
                 "children": [
                     _v(1, 7050210), _v(3, 1), _v(4, 0), _v(5, 0),
                     _v(8, 48), _v(13, 13), _v(14, 3),
                 ]},
                {"no": 1, "name": "field_1", "type": "len", "value": "", "raw": None,
                 "children": [_v(1, 200107), _v(3, 1), _v(4, 1), _v(5, 12)]},
            ],
        }
        extra = [
            _v(26, 98), _v(27, 33242), _v(28, 6), _v(30, 30), _v(78, 4),
            _v(45, 0), _v(82, 103), _v(93, -100),
            skills,
        ]
        pet = extract_pets(_named_event("s2c", [self._pet_node(extra)]))[0]
        self.assertEqual(pet.height, 98)
        self.assertEqual(pet.weight, 33242)
        self.assertEqual(pet.classis, 6)
        self.assertEqual(pet.breakthrough_lv, 30)
        self.assertEqual(pet.speciality_id, 103)
        self.assertEqual(pet.voice, -100)
        self.assertEqual(pet.partner_mark, 4)
        self.assertEqual(len(pet.skills), 2)
        self.assertEqual(pet.skills[0].skill_id, 7050210)
        self.assertTrue(pet.skills[0].is_learned)
        self.assertFalse(pet.skills[0].is_equipped)
        self.assertTrue(pet.skills[1].is_equipped)
        self.assertEqual(pet.skills[1].pos, 12)

    def test_voice_unsigned_wraparound_becomes_negative(self):
        """wire 上是无符号 varint，负值会表现为 2^64 附近的巨值。"""
        pet = extract_pets(_named_event("s2c", [self._pet_node([_v(93, (1 << 64) - 100)])]))[0]
        self.assertEqual(pet.voice, -100)

    def test_extended_fields_do_not_break_shape_detection(self):
        """扩展字段全部缺失时仍是合法宠物（形状判定只依赖 gid/conf_id + 特征字段）。"""
        node = _named_pet_node(5, 6, b"x", 1)
        pets = extract_pets(_named_event("s2c", [node]))
        self.assertEqual(len(pets), 1)
        self.assertEqual(pets[0].gid, 5)


def _wire_children(data: bytes):
    from spritelens.protocol import wire

    return list(wire.decode_wire(data))


class PetRepositoryTest(unittest.TestCase):
    def _feed(self, repo: PetRepository, gid: int, name: bytes, level: int) -> None:
        repo.handle_packet(_named_event("s2c", [_named_pet_node(gid, 20508, name, level)]))

    def test_merge_by_gid_and_clear(self):
        repo = PetRepository()
        self._feed(repo, 7, b"Cat", 5)
        self._feed(repo, 8, b"Dog", 9)
        self._feed(repo, 7, b"CatX", 6)  # 同 gid 更新
        pets = repo.snapshot()
        self.assertEqual([p.gid for p in pets], [7, 8])
        self.assertEqual(pets[0].name, "CatX")
        self.assertEqual(pets[0].level, 6)
        version_after = repo.version
        repo.clear()
        self.assertEqual(repo.snapshot(), ())
        self.assertGreater(repo.version, version_after)

    def test_invalid_gid_skipped(self):
        repo = PetRepository()
        self._feed(repo, 0, b"x", 1)
        self.assertEqual(repo.snapshot(), ())

    def test_limit_applies_per_repository_and_existing_pets_can_update(self):
        repo = PetRepository()
        repo.handle_packet(_named_event("s2c", [
            _named_pet_node(gid, 20508, b"Cat", 5) for gid in range(1, 10000)
        ]))
        self.assertEqual(len(repo.snapshot()), 9999)
        self._feed(repo, 10000, b"New", 5)
        self._feed(repo, 1, b"Updated", 6)
        self.assertEqual(len(repo.snapshot()), 9999)
        self.assertEqual(repo.snapshot()[0].name, "Updated")

        other = PetRepository()
        self._feed(other, 10000, b"Other", 5)
        self.assertEqual(len(other.snapshot()), 1)


class PipelineIntegrationTest(unittest.TestCase):
    """端到端：合成 GCP 流 → 管线 → schema 命中 → 形状提取 → 仓库聚合。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.key_store = KeyStore(Path(self._tmp.name) / "keys")
        self.addCleanup(self.key_store.close)
        self.monitor = _make_monitor_with_schema(Path(self._tmp.name), self.key_store)
        self.repo = PetRepository()
        self.monitor.add_packet_listener(self.repo.handle_packet)

    def test_full_pipeline_collects_pets(self):
        self.monitor.on_chunk(
            StreamChunk(session_id=SESSION, direction=Direction.S2C, data=make_ack_frame(SYNTH_KEY), first_seq=1)
        )
        self.monitor.on_chunk(
            StreamChunk(
                session_id=SESSION,
                direction=Direction.S2C,
                data=make_data_frame(
                    SYNTH_KEY, OPCODE_PET_PAGE,
                    _page_rsp([_brief(3001, 20508, "小火花".encode(), 20), _brief(3002, 20510, b"Pidgy", 44)]),
                    sequence=2,
                ),
                first_seq=2,
            )
        )
        pets = self.repo.snapshot()
        self.assertEqual(len(pets), 2)
        self.assertEqual(pets[0].name, "小火花")
        self.assertEqual(pets[1].gid, 3002)
        _sessions, totals = self.monitor.snapshot()
        self.assertEqual(totals.decrypt_ok, 1)

    def test_no_schema_still_safe(self):
        """无 schema 环境（wire 占位名）下提取不到宠物但不抛错。"""
        key_store = KeyStore(Path(self._tmp.name) / "k2")
        self.addCleanup(key_store.close)
        monitor = MonitorService(catalog=OpcodeCatalog({}), key_store=key_store)
        repo = PetRepository()
        monitor.add_packet_listener(repo.handle_packet)
        monitor.on_chunk(
            StreamChunk(
                session_id=SESSION,
                direction=Direction.S2C,
                data=make_data_frame(SYNTH_KEY, 0x134A, _page_rsp([_brief(1, 2, b"x", 3)]), sequence=1),
                first_seq=1,
            )
        )
        self.assertEqual(repo.snapshot(), ())


def _make_monitor_with_schema(tmp: Path, key_store: KeyStore) -> MonitorService:
    """带完整宠物 schema 的监视器（临时 schema 目录，模拟导入后的环境）。"""
    messages_dir = tmp / "messages"
    messages_dir.mkdir(exist_ok=True)
    (messages_dir / "all.json").write_text(
        json.dumps(
            {
                "messages": {
                    "ZoneGetPetInfoByPageRsp": {
                        "fields": {"4": {"name": "pet_info", "type": "PetDataInfoList"}}
                    },
                    "PetDataInfoList": {
                        "fields": {"1": {"name": "pet_data", "type": "PetBriefInfo"}}
                    },
                    "PetBriefInfo": {
                        "fields": {
                            "1": {"name": "gid", "type": "uint32"},
                            "2": {"name": "conf_id", "type": "uint32"},
                            "3": {"name": "name", "type": "bytes"},
                            "10": {"name": "level", "type": "uint32"},
                        }
                    },
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    load_library(tmp)
    catalog = OpcodeCatalog(
        {OPCODE_PET_PAGE: OpcodeInfo("GetPetInfoByPageRsp", "pet", "ZoneGetPetInfoByPageRsp")}
    )
    return MonitorService(catalog=catalog, key_store=key_store)


if __name__ == "__main__":
    unittest.main()
