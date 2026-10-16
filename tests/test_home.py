"""家园：0x014A 快照提取（按真实帧字段号构造合成树）、聚合与载荷。"""

from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

from spritelens.domain.home import HomeCouple, HomeFurniture, HomeResident, HomeSnapshot, extract_home, home_floor
from spritelens.domain.home_breeding import HomeBreedingProfile, infer_range_couples
from spritelens.domain.pets import Pet
from spritelens.services.home_repository import HomeRepoSnapshot, HomeRepository
from spritelens.events import PacketEvent
from spritelens.web.payloads_catalog import home_payload


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


def _resident_event(actor_id: int, name: str, gender: int = 1, level: int = 40,
                    *, session_id: str = "s") -> PacketEvent:
    resident = _actor_node(actor_id, actor_id, 10001, 90001, name, (1284, -882, 61))
    couple = _field(1, None, children=[
        _field(1, actor_id if gender == 2 else actor_id + 1),
        *([] if gender == 2 else [_field(2, actor_id)]),
    ])
    home = _field(22, None, children=[
        _field(2, 101), _field(5, 5), _field(22, None, children=[couple]),
    ])
    return PacketEvent(
        ts=0.0, session_id=session_id, direction="s2c", opcode=0x014A, opcode_name="ZoneGetHomeSceneRsp",
        payload_len=0,
        decoded=[resident, home],
    )


def _actor_node(actor_id: int, instance_id: int, base_conf_id: int, nest_guid: int,
                name: str, position: tuple[int, int, int]) -> dict:
    pet = _field(1, None, children=[
        _field(1, instance_id), _field(2, base_conf_id), _field(3, nest_guid),
        _field(11, name.encode("utf-8"), text=name),
        _field(13, None, children=[_field(1, position[0]), _field(2, position[1]), _field(3, position[2])]),
        _field(14, 12345),
    ])
    npc = [
        _field(1, None, children=[_field(1, 1), _field(2, actor_id)]),
        _field(22, None, children=[pet]),
    ]
    return _field(7, None, children=[_field(11, None, children=npc)])


def _nested_home_event(*, owner_uid: int = 134509467, session_id: str = "s", residents: list[dict] | None = None,
                       include_furniture_position: bool = True) -> PacketEvent:
    actor_id = 9518406239959121930
    actor = _actor_node(actor_id, 70001, 10001, 90001, "护主犬", (120, -30, 4))
    coordinates = _field(1, None, children=[_field(1, 150), _field(2, 250), _field(3, 2)])
    furniture_fields = [_field(1, 90001), _field(2, 0), _field(4, 0), _field(5, 1001072)]
    if include_furniture_position:
        furniture_fields.append(_field(6, None, children=[coordinates]))
    furniture = _field(20, None, children=furniture_fields)
    other_furniture = _field(20, None, children=[_field(1, 90002), _field(5, 888888)])
    plane = _field(20, None, children=[_field(1, 71), furniture, other_furniture])
    room = _field(1, None, children=[_field(1, 1), _field(2, None, text="一楼"), plane])
    couple = _field(1, None, children=[_field(1, actor_id), _field(2, 9518406239959121931)])
    home = _field(22, None, children=[
        _field(2, owner_uid), _field(4, 3), _field(5, 5), _field(20, None, children=[room]),
        _field(22, None, children=[couple]),
    ])
    return PacketEvent(0.0, session_id, "s2c", 0x014A, "home", 0, [*(residents if residents is not None else [actor]), home])


def _scene_event(resource_id: int, *, session_id: str = "s", opcode: int = 0x0152,
                 uid: int | None = None) -> PacketEvent:
    field_no = 3 if opcode == 0x0152 else 12
    return PacketEvent(0.0, session_id, "s2c", opcode, "scene", 0, [_field(field_no, resource_id)],
                       resumed_identity=(uid, "玩家", 1) if uid is not None else None)


def _ready_repo(uid: int = 134509467, *, resource_id: int = 30001, session_id: str = "s") -> HomeRepository:
    repo = HomeRepository()
    repo.handle_packet(_scene_event(resource_id, session_id=session_id, uid=uid))
    return repo


def _delta_event(*, actor_fields: list[dict] | None = None,
                 other_actor_fields: list[list[dict]] | None = None,
                 leaving: int | bytes | None = None) -> PacketEvent:
    action = []
    if actor_fields is not None:
        actor_rows = [actor_fields, *(other_actor_fields or [])]
        action.append(_field(1, None, children=[
            _field(1, None, children=fields) for fields in actor_rows
        ]))
    if leaving is not None:
        action.append(_field(2, None, children=[_field(1, leaving)]))
    return PacketEvent(0.0, "s", "s2c", 0x0414, "delta", 0, [_field(1, None, children=action)])


def _egg_actor_node(actor_id: int, nest_guid: int, config_id: int) -> list[dict]:
    return [_field(11, None, children=[
        _field(1, None, children=[_field(1, 13), _field(2, actor_id)]),
        _field(3, None, children=[_field(1, config_id)]),
        _field(23, None, children=[_field(2, nest_guid)]),
    ])]


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
    def test_generic_scene_layout_without_home_info_is_ignored(self) -> None:
        self.assertIsNone(extract_home(_snapshot_event()))

    def test_non_snapshot_ignored(self) -> None:
        event = PacketEvent(0.0, "s", "s2c", 0x0414, "delta", 0, [])
        self.assertIsNone(extract_home(event))

    def test_extracted_layout_includes_species_link_nest_and_couple(self) -> None:
        snap = extract_home(_nested_home_event())
        self.assertIsNotNone(snap)
        self.assertEqual(snap.room_level, 5)
        self.assertEqual(snap.owner_uid, 134509467)
        self.assertEqual(snap.residents[0].instance_id, 70001)
        self.assertEqual(snap.residents[0].base_conf_id, 10001)
        self.assertEqual(snap.residents[0].position, (120, -30, 4))
        self.assertEqual(snap.nests[0].kind, "academy")
        self.assertEqual(len(snap.nests), 1)
        self.assertEqual(snap.nests[0].guid, "90001")
        self.assertEqual(snap.nests[0].position, (1.5, 2.5, 0.02))
        self.assertTrue(snap.nests[0].position_known)
        self.assertEqual((snap.nests[0].room_id, snap.nests[0].room_name, snap.nests[0].plane_id), (1, "一楼", 71))
        self.assertEqual(snap.nests[0].resident_ids, (9518406239959121930,))
        self.assertEqual(snap.couples[0].female_actor_id, 9518406239959121930)
        self.assertEqual(snap.residents[0].gender, 2)

    def test_missing_furniture_position_is_not_reported_as_a_real_coordinate(self) -> None:
        snap = extract_home(_nested_home_event(include_furniture_position=False))
        self.assertEqual(snap.nests[0].position, (0, 0, 0))
        self.assertFalse(snap.nests[0].position_known)

    def test_floor_uses_position_polygon_and_height_and_is_shared_with_range_filter(self) -> None:
        self.assertEqual(home_floor((1500, 2000, 300)), "二楼")
        self.assertEqual(home_floor((1500, 500, -1)), "地下室")
        self.assertEqual(home_floor((1500, 1500, -1)), "一楼")
        residents = (
            HomeResident(11, "母本", 2, 20, (0, 0, 0), nest_guid="a"),
            HomeResident(12, "父本", 1, 20, (0, 0, 0), nest_guid="b"),
        )
        nests = (
            HomeFurniture(1001071, "a", "ordinary", "普通小窝", (1500, 1500, 300)),
            HomeFurniture(1001071, "b", "ordinary", "普通小窝", (1500, 1500, -1)),
        )
        profiles = {11: HomeBreedingProfile(2, ("野兽组",)), 12: HomeBreedingProfile(1, ("野兽组",))}
        self.assertEqual(infer_range_couples(residents, nests, profiles), ())


class HomeDeltaTests(unittest.TestCase):
    def test_delta_updates_and_removes_residents_without_marking_snapshot_stale(self) -> None:
        repo = _ready_repo(101)
        repo.handle_packet(_resident_event(123, "喵喵"))
        changed = _actor_node(123, 123, 10001, 90001, "喵喵", (200, 300, 1))
        repo.handle_packet(_delta_event(actor_fields=changed["children"]))
        self.assertEqual(repo.snapshot().residents[0].position, (200, 300, 1))
        self.assertEqual(repo.snapshot().residents[0].gender, 1)
        self.assertEqual(repo.pending_deltas(), 0)
        self.assertTrue(repo.snapshot().couples_stale)
        repo.handle_packet(_delta_event(leaving=123))
        self.assertEqual(repo.snapshot().residents, ())
        self.assertEqual(repo.pending_deltas(), 0)

    def test_extracted_delta_actor_wrapper_and_packed_removal(self) -> None:
        repo = _ready_repo()
        repo.handle_packet(_nested_home_event())
        actor_id = 9518406239959121930
        changed_actor = _actor_node(actor_id, 70001, 10001, 90001, "护主犬", (320, 250, 2))
        repo.handle_packet(_delta_event(actor_fields=changed_actor["children"]))
        self.assertEqual(repo.snapshot().residents[0].position, (320, 250, 2))
        self.assertTrue(repo.snapshot().couples_stale)
        self.assertEqual(repo.pending_deltas(), 0)
        repo.handle_packet(_delta_event(leaving=actor_id))
        self.assertEqual(repo.snapshot().residents, ())
        self.assertEqual(repo.pending_deltas(), 0)

    def test_partial_actor_delta_matches_actor_id_and_keeps_other_fields(self) -> None:
        repo = _ready_repo()
        repo.handle_packet(_nested_home_event())
        actor_id = 9518406239959121930
        sparse_pet = _field(1, None, children=[
            _field(13, None, children=[_field(1, 320), _field(2, 250), _field(3, 2)]),
        ])
        sparse_actor = _field(7, None, children=[_field(11, None, children=[
            _field(1, None, children=[_field(2, actor_id)]),
            _field(22, None, children=[sparse_pet]),
        ])])
        repo.handle_packet(_delta_event(actor_fields=sparse_actor["children"]))
        resident = repo.snapshot().residents[0]
        self.assertEqual(resident.actor_id, actor_id)
        self.assertEqual(resident.instance_id, 70001)
        self.assertEqual(resident.position, (320, 250, 2))
        self.assertEqual(resident.name, "护主犬")
        self.assertEqual(repo.pending_deltas(), 0)

    def test_mixed_resident_update_and_unrelated_npc_keeps_update_without_pending(self) -> None:
        repo = _ready_repo()
        repo.handle_packet(_nested_home_event())
        actor_id = 9518406239959121930
        resident = _actor_node(actor_id, 70001, 10001, 90001, "护主犬", (321, 250, 2))
        unrelated_npc = [_field(11, None, children=[
            _field(1, None, children=[_field(1, 1), _field(2, 88001)]),
        ])]
        repo.handle_packet(_delta_event(actor_fields=resident["children"], other_actor_fields=[unrelated_npc]))
        self.assertEqual(repo.snapshot().residents[0].position, (321, 250, 2))
        self.assertEqual(repo.pending_deltas(), 0)

    def test_explicit_zero_position_and_nest_clear_are_applied(self) -> None:
        repo = _ready_repo()
        repo.handle_packet(_nested_home_event())
        actor_id = 9518406239959121930
        sparse_pet = _field(1, None, children=[
            _field(3, 0), _field(13, None, children=[_field(1, 0), _field(2, 0), _field(3, 0)]),
        ])
        sparse_actor = _field(7, None, children=[_field(11, None, children=[
            _field(1, None, children=[_field(2, actor_id)]),
            _field(22, None, children=[sparse_pet]),
        ])])
        repo.handle_packet(_delta_event(actor_fields=sparse_actor["children"]))
        resident = repo.snapshot().residents[0]
        self.assertEqual(resident.position, (0, 0, 0))
        self.assertEqual(resident.nest_guid, "")
        self.assertEqual(repo.pending_deltas(), 0)

    def test_relevant_unresolved_actor_marks_pending_but_keeps_same_batch_update(self) -> None:
        repo = _ready_repo()
        repo.handle_packet(_nested_home_event())
        actor_id = 9518406239959121930
        valid = _actor_node(actor_id, 70001, 10001, 90001, "护主犬", (400, 250, 2))
        unresolved = [_field(11, None, children=[
            _field(1, None, children=[_field(1, 1), _field(2, actor_id)]),
            _field(22, None, children=[]),
        ])]
        repo.handle_packet(_delta_event(actor_fields=valid["children"], other_actor_fields=[unresolved]))
        self.assertEqual(repo.snapshot().residents[0].position, (400, 250, 2))
        self.assertEqual(repo.pending_deltas(), 1)
        self.assertEqual(repo.consistent_snapshot().source, "stale")

    def test_scene_egg_addition_and_packed_removal(self) -> None:
        repo = _ready_repo()
        repo.handle_packet(_nested_home_event())
        repo.handle_packet(_delta_event(actor_fields=_egg_actor_node(901, 90001, 1001071)))
        self.assertEqual(repo.snapshot().scene_eggs[0].actor_id, 901)
        repo.handle_packet(_delta_event(leaving=bytes([0x85, 0x07])))
        self.assertEqual(repo.snapshot().scene_eggs, ())

    def test_duplicate_delta_does_not_advance_version(self) -> None:
        repo = _ready_repo()
        repo.handle_packet(_nested_home_event())
        actor = _actor_node(9518406239959121930, 70001, 10001, 90001, "护主犬", (120, -30, 4))
        repo.handle_packet(_delta_event(actor_fields=actor["children"]))
        version = repo.version()
        repo.handle_packet(_delta_event(actor_fields=actor["children"]))
        self.assertEqual(repo.version(), version)


class HomeBreedingTests(unittest.TestCase):
    def test_infers_only_confirmed_compatible_residents_within_nest_edge_range(self) -> None:
        residents = (
            HomeResident(11, "母本", 2, 20, (0, 0, 0), instance_id=101, nest_guid="a"),
            HomeResident(12, "父本", 1, 20, (0, 0, 0), instance_id=102, nest_guid="b"),
        )
        nests = (
            HomeFurniture(1001071, "a", "ordinary", "普通小窝", (0, 0, 0)),
            HomeFurniture(1001071, "b", "ordinary", "普通小窝", (560, 0, 0)),
        )
        profiles = {
            11: HomeBreedingProfile(2, ("野兽组",)),
            12: HomeBreedingProfile(1, ("野兽组", "飞行组")),
        }
        self.assertEqual(infer_range_couples(residents, nests, profiles), (HomeCouple(11, (12,)),))

        outside_range = (nests[0], HomeFurniture(1001071, "b", "ordinary", "普通小窝", (600, 0, 0)))
        self.assertEqual(infer_range_couples(residents, outside_range, profiles), ())
        unknown = {11: profiles[11], 12: HomeBreedingProfile(1, ("未知",))}
        self.assertEqual(infer_range_couples(residents, nests, unknown), ())


class HomePayloadTests(unittest.TestCase):
    def test_instance_id_joins_pet_profile_and_base_id_resolves_species(self) -> None:
        repo = _ready_repo()
        repo.handle_packet(_nested_home_event())
        pet = Pet(70001, 10001, "护主犬", 56, 0, 3, 2, 0, 0, False,
                  base_conf_id=10001, height=123, weight=456, voice=-45)
        pets = Mock()
        pets.consistent_snapshot.return_value = SimpleNamespace(uid=134509467, pets=(pet,))
        pets.voice_overrides.return_value = {}
        static = Mock()
        static.species.return_value = SimpleNamespace(
            name="护主犬", egg_groups=("野兽组",),
            height_range=(100, 200), weight_range=(300, 600),
        )
        static.nature_name.return_value = "勇敢"

        resident = home_payload(repo, static, pets)["residents"][0]
        self.assertEqual((resident["instance_id"], resident["base_conf_id"]), ("70001", 10001))
        self.assertEqual((resident["level"], resident["gender"], resident["nature_name"]), (56, 2, "勇敢"))
        self.assertEqual((resident["voice"], resident["height_text"], resident["weight_text"]), (-45, "1.23 m", "0.46 kg"))
        self.assertEqual(resident["egg_groups"], ["野兽组"])
        static.species.assert_called_once_with(10001)
        self.assertEqual((resident["height_pct"], resident["weight_pct"]), (0.23, 0.52))
        self.assertNotIn("furniture", home_payload(repo, static, pets))

        catalog = Mock()
        catalog.egg_by_base_id.return_value = SimpleNamespace(
            egg_name="护主犬蛋", egg_item_id=80001, weight_low=12000, weight_high=18000,
        )
        resident = home_payload(repo, static, pets, catalog)["residents"][0]
        self.assertEqual((resident["egg_name"], resident["egg_icon_url"]),
                         ("护主犬蛋", "/static/egg-icons/80001.png"))

    def test_manual_zero_voice_is_a_known_value_and_missing_voice_is_null(self) -> None:
        repo = _ready_repo()
        repo.handle_packet(_nested_home_event())
        pet = Pet(70001, 10001, "护主犬", 56, 0, 3, 2, 0, 0, False,
                  base_conf_id=10001, voice=-45)
        pets = Mock()
        pets.consistent_snapshot.return_value = SimpleNamespace(uid=134509467, pets=(pet,))
        pets.voice_overrides.return_value = {70001: 0}
        static = Mock()
        static.species.return_value = SimpleNamespace(
            base_conf_id=10001, name="护主犬", egg_groups=("野兽组",),
            height_range=(100, 200), weight_range=(1000, 2000),
        )
        static.nature_name.return_value = "勇敢"
        resident = home_payload(repo, static, pets)["residents"][0]
        self.assertEqual(resident["voice"], 0)
        self.assertEqual(resident["height_pct"], None)

        pets.voice_overrides.return_value = {}
        pets.consistent_snapshot.return_value = SimpleNamespace(
            uid=134509467, pets=(replace(pet, voice=0),)
        )
        self.assertIsNone(home_payload(repo, static, pets)["residents"][0]["voice"])

    def test_pair_predictions_use_nature_rules_and_average_parent_voices(self) -> None:
        residents = (
            HomeResident(901, "母本", 2, 56, (0, 0, 0), 70001, 10001, 123, "a"),
            HomeResident(902, "父本", 1, 56, (0, 0, 0), 70002, 10002, 124, "b"),
        )
        nests = (
            HomeFurniture(1001071, "a", "ordinary", "普通小窝", (0, 0, 0)),
            HomeFurniture(1001071, "b", "ordinary", "普通小窝", (560, 0, 0)),
        )
        pets = Mock()
        pets.consistent_snapshot.return_value = SimpleNamespace(uid=7, pets=(
            Pet(70001, 123, "母本", 56, 0, 1, 2, 0, 0, False, base_conf_id=10001, voice=-45),
            Pet(70002, 124, "父本", 56, 0, 2, 1, 0, 0, False, base_conf_id=10002, voice=-35),
        ))
        pets.voice_overrides.return_value = {}
        static = Mock()
        static.species.side_effect = lambda base_id: SimpleNamespace(
            name="精灵", egg_groups=("野兽组",),
            height_range=(100, 200), weight_range=(1000, 2000))
        static.nature_name.side_effect = {1: "勇敢", 2: "冷静"}.__getitem__

        def payload(female_nest_config: int, *, stale: bool = False, pending_deltas: int = 0) -> dict:
            furniture = (HomeFurniture(female_nest_config, "a", "academy" if female_nest_config == 1001072 else "ordinary",
                                       "学院小窝" if female_nest_config == 1001072 else "普通小窝", (0, 0, 0)), nests[1])
            snapshot = HomeSnapshot(10, residents, furniture, (HomeCouple(901, (902,)),), couples_stale=stale)
            repository = Mock()
            repository.consistent_snapshot.return_value = HomeRepoSnapshot(snapshot, 7, 1, pending_deltas)
            return home_payload(repository, static, pets)

        ordinary = payload(1001071)["couples"][0]
        self.assertEqual(ordinary["nature_prediction"]["distribution"], {"勇敢": 30.0, "冷静": 30.0})
        self.assertEqual(ordinary["nature_prediction"]["random_percent"], 40.0)
        self.assertEqual(ordinary["voice_predictions"][0]["father_actor_id"], "902")
        self.assertEqual(ordinary["voice_predictions"][0]["voice"], -40)

        academy = payload(1001072)["couples"][0]
        self.assertEqual(academy["mode"], "academy-mother")
        self.assertEqual(academy["nature_prediction"]["distribution"], {"勇敢": 100.0})

        inferred = payload(1001071, pending_deltas=3)
        self.assertEqual(inferred["couples"][0]["pairing_basis"], "scene")
        self.assertTrue(inferred["couples_stale"])
        self.assertEqual(inferred["inferred_couples"][0]["pairing_basis"], "nest-range")
        self.assertEqual(inferred["inferred_couples"][0]["male_actor_ids"], ["902"])


class HomeRepositoryTests(unittest.TestCase):
    def test_snapshot_and_delta_count(self) -> None:
        repo = _ready_repo(101)
        repo.handle_packet(_resident_event(123, "喵喵"))
        self.assertIsNotNone(repo.snapshot())
        base = repo.version()
        repo.handle_packet(PacketEvent(0.0, "s", "s2c", 0x0414, "delta", 0, []))
        self.assertEqual(repo.pending_deltas(), 1)
        self.assertEqual(repo.version(), base + 1)
        # 快照仍在（增量未合并）
        self.assertIsNotNone(repo.snapshot())

    def test_scene_changes_preserve_last_home_as_history_and_reject_foreign_scene_packets(self) -> None:
        repo = _ready_repo()
        repo.handle_packet(_nested_home_event())
        self.assertEqual(repo.consistent_snapshot().source, "observed")
        original = repo.snapshot()

        repo.handle_packet(_scene_event(10003, opcode=0x015C))
        self.assertEqual(repo.consistent_snapshot().source, "history")
        repo.handle_packet(_snapshot_event())
        self.assertIs(repo.snapshot(), original)

        repo.handle_packet(_scene_event(30002, opcode=0x0152))
        repo.handle_packet(_nested_home_event())
        self.assertIs(repo.snapshot(), original)

        repo.handle_packet(_scene_event(30001, opcode=0x0152))
        self.assertEqual(repo.consistent_snapshot().source, "history")
        repo.handle_packet(_nested_home_event())
        self.assertEqual(repo.consistent_snapshot().source, "observed")

    def test_home_owner_must_match_account_and_valid_empty_home_is_accepted(self) -> None:
        repo = _ready_repo()
        repo.handle_packet(_nested_home_event(owner_uid=999))
        self.assertIsNone(repo.snapshot())
        repo.handle_packet(_nested_home_event(residents=[]))
        self.assertEqual(repo.snapshot().residents, ())

    def test_old_session_cannot_restore_home_after_account_switch(self) -> None:
        repo = _ready_repo()
        repo.handle_packet(_nested_home_event())
        repo.handle_packet(_scene_event(30001, session_id="s2", uid=202))
        repo.handle_packet(_nested_home_event(owner_uid=134509467, session_id="s"))
        self.assertIsNone(repo.snapshot())
        repo.handle_packet(_nested_home_event(owner_uid=202, session_id="s2"))
        self.assertIsNotNone(repo.snapshot())


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
