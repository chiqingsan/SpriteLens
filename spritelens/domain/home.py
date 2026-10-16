"""家园语义层：0x014A 家园元数据与场景实体 → 居民 / 家具 / 配对。"""

from __future__ import annotations

from dataclasses import dataclass, replace

from spritelens.events import PacketEvent
from spritelens.protocol.wire import read_varint

OP_HOME_SNAPSHOT = 0x014A
OP_HOME_DELTA_A = 0x0413
OP_HOME_DELTA_B = 0x0414

# 已识别小窝 configId → (窝型标识, 展示名)
NEST_TYPES: dict[int, tuple[str, str]] = {
    710069: ("ordinary", "普通小窝"),
    1001071: ("ordinary", "普通小窝"),
    1001072: ("academy", "学院小窝"),
}

_FLOOR_AREAS: tuple[tuple[str, int, tuple[tuple[int, int], ...]], ...] = (
    ("二楼", 298, ((1284, 2827), (1264, 1376), (2535, 1386), (2535, 2841))),
    ("二楼", 320, ((462, 1408), (1256, 1408), (1246, 2018), (465, 2018))),
    ("二楼", 310, ((1361, 1460), (1200, 1460), (1200, 1893), (1346, 1893))),
    ("地下室", -600, ((2842, 809), (1198, 809), (1161, 154), (2838, 154))),
    ("地下室", -600, ((2829, -905), (2829, 152), (1625, 152), (1628, -883))),
    ("地下室", -600, ((1215, 158), (1215, -902), (1629, -907), (1629, 158))),
    ("地下室", -484, ((801, 115), (1231, 115), (1231, -900), (801, -897))),
)


def home_floor(position: tuple[float, float, float]) -> str:
    """按蛋神本地家园规则，以家具世界坐标和高度识别楼层。"""
    x, y, z = position
    for name, minimum_z, points in _FLOOR_AREAS:
        inside = False
        previous = points[-1]
        for current in points:
            xi, yi = current
            xj, yj = previous
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
            previous = current
        if inside and (z < 0 if name == "地下室" else z >= minimum_z):
            return name
    return "一楼"

@dataclass(frozen=True)
class HomeResident:
    """家园里的宠物居民。"""

    actor_id: int
    name: str
    gender: int  # 1 雄 / 2 雌 / 0 未知
    level: int
    position: tuple[int, int, int]
    instance_id: int = 0
    base_conf_id: int = 0
    conf_id: int = 0
    nest_guid: str = ""


@dataclass(frozen=True)
class HomeFurniture:
    """家园中已识别的小窝及其位置。"""

    config_id: int
    guid: str
    kind: str  # NEST_TYPES kind
    name: str
    position: tuple[float, float, float]
    resident_ids: tuple[int, ...] = ()
    position_known: bool = True
    room_id: int = 0
    room_name: str = ""
    plane_id: int = 0


@dataclass(frozen=True)
class HomeCouple:
    female_actor_id: int
    male_actor_ids: tuple[int, ...]


@dataclass(frozen=True)
class HomeSceneEgg:
    actor_id: int
    furniture_guid: str
    npc_config_id: int


@dataclass(frozen=True)
class HomeSnapshot:
    """一次家园快照的解析结果。"""

    room_level: int
    residents: tuple[HomeResident, ...]
    nests: tuple[HomeFurniture, ...]
    couples: tuple[HomeCouple, ...] = ()
    scene_eggs: tuple[HomeSceneEgg, ...] = ()
    couples_stale: bool = False
    owner_uid: int = 0

@dataclass(frozen=True)
class HomeDeltaResult:
    snapshot: HomeSnapshot
    unresolved: bool


def _coerce_int(value: object) -> int:
    return value if isinstance(value, int) else 0


def _coerce_int32(value: object) -> int:
    raw = _coerce_int(value)
    if 0 <= raw < (1 << 31):
        return raw
    if raw >= (1 << 63):
        raw -= 1 << 64
    if -(1 << 31) <= raw < (1 << 31):
        return raw
    return 0


def _raw_by_no(fields: list[dict], no: int) -> object:
    for item in fields:
        if item.get("no") == no:
            return item.get("raw")
    return None


def _has_no(fields: list[dict], no: int) -> bool:
    return any(item.get("no") == no for item in fields)


def _nodes_by_no(fields: list[dict], no: int) -> list[dict]:
    return [item for item in fields if item.get("no") == no]


def _children_by_no(fields: list[dict], no: int) -> list[dict] | None:
    for item in fields:
        if item.get("no") == no:
            children = item.get("children")
            return children if isinstance(children, list) else None
    return None


def _text_value(node: dict | None) -> str:
    if node is None:
        return ""
    text = node.get("text")
    if isinstance(text, str):
        return text
    raw = node.get("raw")
    if isinstance(raw, bytes):
        for encoding in ("utf-8", "gb18030"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
    return ""


def _position_fields(fields: list[dict] | None) -> tuple[int, int, int]:
    if not fields:
        return (0, 0, 0)
    inner = _children_by_no(fields, 1) or fields
    return tuple(_coerce_int32(_raw_by_no(inner, i)) for i in (1, 2, 3))  # type: ignore[return-value]


def _home_actor(node: dict, *, allow_partial: bool = False) -> HomeResident | None:
    """蛋神 v1.2.0 home_scene actor 布局，已对照反汇编字段号。"""
    actor = node.get("children")
    if not isinstance(actor, list):
        return None
    npc = _children_by_no(actor, 11)
    if not npc:
        return None
    pet_container = _children_by_no(npc, 22)
    pet = _children_by_no(pet_container or [], 1)
    if not pet:
        return None
    instance_id = _coerce_int(_raw_by_no(pet, 1))
    base_conf_id = _coerce_int(_raw_by_no(pet, 2))
    nest_guid = str(_coerce_int(_raw_by_no(pet, 3)) or "")
    if not allow_partial and (not instance_id or not base_conf_id or not nest_guid):
        return None
    identity = _children_by_no(npc, 1) or []
    actor_id = _coerce_int(_raw_by_no(identity, 2))
    if actor_id <= 0:
        return None
    name_node = next(iter(_nodes_by_no(pet, 11)), None)
    name = _text_value(name_node)
    pet_position = _children_by_no(pet, 13)
    identity_position = _children_by_no(_children_by_no(identity, 8) or [], 1)
    position = _position_fields(pet_position if pet_position is not None else identity_position)
    if allow_partial and not any(_has_no(pet, field) for field in (1, 2, 3, 11, 13, 14)) \
            and not identity_position:
        return None
    return HomeResident(
        actor_id=actor_id,
        name=name,
        gender=0,
        level=0,
        position=position,
        instance_id=instance_id,
        base_conf_id=base_conf_id,
        conf_id=_coerce_int(_raw_by_no(pet, 14)),
        nest_guid=nest_guid,
    )


def _home_egg(node: dict) -> HomeSceneEgg | None:
    actor = node.get("children")
    if not isinstance(actor, list):
        return None
    npc = _children_by_no(actor, 11)
    if not npc:
        return None
    identity = _children_by_no(npc, 1) or []
    if _coerce_int(_raw_by_no(identity, 1)) != 13:
        return None
    attachment = _children_by_no(npc, 23)
    nest_guid = str(_coerce_int(_raw_by_no(attachment or [], 2)) or "")
    actor_id = _coerce_int(_raw_by_no(identity, 2))
    if actor_id <= 0 or not nest_guid:
        return None
    egg_config = _children_by_no(_children_by_no(npc, 3) or [], 1) or []
    return HomeSceneEgg(actor_id, nest_guid, _coerce_int(_raw_by_no(egg_config, 1)))


def _home_nest_rows(home: list[dict]) -> list[HomeFurniture]:
    rows: list[HomeFurniture] = []
    for room_node in _nodes_by_no(_children_by_no(home, 20) or [], 1):
        room = room_node.get("children")
        if not isinstance(room, list):
            continue
        for plane_node in _nodes_by_no(room, 20):
            plane = plane_node.get("children")
            if not isinstance(plane, list):
                continue
            for item_node in _nodes_by_no(plane, 20):
                fields = item_node.get("children")
                if not isinstance(fields, list):
                    continue
                config_id = _coerce_int(_raw_by_no(fields, 5))
                if config_id not in NEST_TYPES:
                    continue
                guid_raw = _raw_by_no(fields, 1)
                guid = (guid_raw.hex() if isinstance(guid_raw, bytes)
                        else str(guid_raw) if isinstance(guid_raw, int) and guid_raw > 0 else "")
                kind, name = NEST_TYPES[config_id]
                location = _children_by_no(fields, 6) or []
                coordinates = _children_by_no(location, 1)
                position_known = coordinates is not None and all(
                    _has_no(coordinates, axis) for axis in (1, 2, 3)
                )
                raw_position = _position_fields(coordinates)
                position = tuple(value / 100 for value in raw_position)
                rows.append(HomeFurniture(
                    config_id, guid, kind, name, position,
                    position_known=position_known,
                    room_id=_coerce_int(_raw_by_no(room, 1)),
                    room_name=_text_value(next(iter(_nodes_by_no(room, 2)), None)),
                    plane_id=_coerce_int(_raw_by_no(plane, 1)),
                ))
    return rows


def _couples_from(home: list[dict]) -> tuple[HomeCouple, ...]:
    container = _children_by_no(home, 22) or []
    couples: dict[int, list[int]] = {}
    for node in _nodes_by_no(container, 1):
        fields = node.get("children")
        if not isinstance(fields, list):
            continue
        female = _coerce_int(_raw_by_no(fields, 1))
        if female <= 0:
            continue
        males: list[int] = []
        for male_node in _nodes_by_no(fields, 2):
            raw = male_node.get("raw")
            if isinstance(raw, int):
                males.append(raw)
            elif isinstance(raw, bytes):
                offset = 0
                while offset < len(raw):
                    decoded = read_varint(raw, offset)
                    if decoded is None:
                        break
                    value, offset = decoded
                    males.append(value)
        known_males = couples.setdefault(female, [])
        known_males.extend(actor_id for actor_id in males if actor_id not in known_males)
    return tuple(HomeCouple(female, tuple(males)) for female, males in couples.items())


def _nested_snapshot(event: PacketEvent) -> HomeSnapshot | None:
    root = event.decoded or []
    home = _children_by_no(root, 22)
    if home is None:
        return None
    residents: list[HomeResident] = []
    scene_eggs: list[HomeSceneEgg] = []
    for node in _nodes_by_no(root, 7):
        resident = _home_actor(node)
        if resident is not None:
            residents.append(resident)
        egg = _home_egg(node)
        if egg is not None:
            scene_eggs.append(egg)
    couples = _couples_from(home)
    sexes: dict[int, set[int]] = {}
    for couple in couples:
        sexes.setdefault(couple.female_actor_id, set()).add(2)
        for actor_id in couple.male_actor_ids:
            sexes.setdefault(actor_id, set()).add(1)
    residents = [replace(resident, gender=next(iter(sexes[resident.actor_id])))
                 if len(sexes.get(resident.actor_id, ())) == 1 else resident
                 for resident in residents]
    occupants: dict[str, list[int]] = {}
    for resident in residents:
        if resident.nest_guid:
            occupants.setdefault(resident.nest_guid, []).append(resident.actor_id)
    nests = tuple(replace(piece, resident_ids=tuple(occupants.get(piece.guid, ())))
                  for piece in _home_nest_rows(home))
    return HomeSnapshot(
        room_level=_coerce_int(_raw_by_no(home, 5)),
        residents=tuple(residents),
        nests=nests,
        couples=couples,
        scene_eggs=tuple(scene_eggs),
        owner_uid=_coerce_int(_raw_by_no(home, 2)),
    )


def extract_home(event: PacketEvent) -> HomeSnapshot | None:
    """解析家园快照事件；非快照帧返回 None。"""
    if event.direction != "s2c" or event.opcode != OP_HOME_SNAPSHOT:
        return None
    return _nested_snapshot(event)


def _packed_ids(raw: object) -> list[int]:
    if isinstance(raw, int):
        return [raw]
    if not isinstance(raw, bytes):
        return []
    values: list[int] = []
    offset = 0
    while offset < len(raw):
        decoded = read_varint(raw, offset)
        if decoded is None:
            break
        value, offset = decoded
        values.append(value)
    return values


def _actor_identity(node: dict) -> tuple[int, int, list[dict] | None] | None:
    actor = node.get("children")
    npc = _children_by_no(actor, 11) if isinstance(actor, list) else None
    if npc is None:
        return None
    identity = _children_by_no(npc, 1) or []
    return (_coerce_int(_raw_by_no(identity, 1)),
            _coerce_int(_raw_by_no(identity, 2)),
            _children_by_no(npc, 22))


def _merge_delta_resident(previous: HomeResident | None, resident: HomeResident,
                          actor_node: dict) -> HomeResident:
    actor_fields = actor_node.get("children") or []
    npc = _children_by_no(actor_fields, 11) or []
    identity = _children_by_no(npc, 1) or []
    pet = _children_by_no(_children_by_no(npc, 22) or [], 1) or []
    old = previous or HomeResident(resident.actor_id, "", 0, 0, (0, 0, 0))
    position_fields = _children_by_no(pet, 13)
    if position_fields is None:
        position_fields = _children_by_no(_children_by_no(identity, 8) or [], 1)
    position = list(old.position)
    if position_fields is not None:
        coordinates = _children_by_no(position_fields, 1) or position_fields
        for index, no in enumerate((1, 2, 3)):
            if _has_no(coordinates, no):
                position[index] = _coerce_int32(_raw_by_no(coordinates, no))
    return replace(
        resident,
        name=resident.name if _has_no(pet, 11) else old.name,
        gender=old.gender,
        level=old.level,
        position=tuple(position),
        instance_id=resident.instance_id if _has_no(pet, 1) else old.instance_id,
        base_conf_id=resident.base_conf_id if _has_no(pet, 2) else old.base_conf_id,
        conf_id=resident.conf_id if _has_no(pet, 14) else old.conf_id,
        nest_guid=resident.nest_guid if _has_no(pet, 3) else old.nest_guid,
    )


def apply_home_delta(event: PacketEvent, snapshot: HomeSnapshot | None) -> HomeDeltaResult | None:
    """合并目标家园变化；None 表示动作包自身无法解析。"""
    if event.direction != "s2c" or event.opcode not in (OP_HOME_DELTA_A, OP_HOME_DELTA_B) or snapshot is None:
        return None
    actions = _nodes_by_no(event.decoded or [], 1)
    if not actions:
        return None

    residents = {row.actor_id: row for row in snapshot.residents}
    eggs = {row.actor_id: row for row in snapshot.scene_eggs}
    residents_changed = False
    unresolved = False
    for action in actions:
        fields = action.get("children")
        if not isinstance(fields, list):
            unresolved = True
            continue
        actor_wrappers = _nodes_by_no(fields, 1)
        leaving_wrappers = _nodes_by_no(fields, 2)
        if not actor_wrappers and not leaving_wrappers:
            unresolved = True
            continue
        for wrapper in actor_wrappers:
            actor_container = wrapper.get("children")
            if not isinstance(actor_container, list):
                unresolved = True
                continue
            for actor_node in _nodes_by_no(actor_container, 1):
                resident = _home_actor(actor_node, allow_partial=True)
                egg = _home_egg(actor_node)
                actor_identity = _actor_identity(actor_node)
                if resident is None and egg is None:
                    if actor_identity is not None:
                        detail_type, actor_id, pet_container = actor_identity
                        if actor_id in residents or actor_id in eggs or detail_type == 13 or pet_container is not None:
                            unresolved = True
                    continue
                if egg is not None and eggs.get(egg.actor_id) != egg:
                    eggs[egg.actor_id] = egg
                if resident is not None:
                    key = resident.actor_id
                    previous_key = next((actor for actor, row in residents.items()
                                         if actor == resident.actor_id or
                                         (resident.instance_id and row.instance_id == resident.instance_id)), None)
                    previous = residents.get(previous_key) if previous_key is not None else None
                    if previous is None and not all((resident.instance_id, resident.base_conf_id, resident.nest_guid)):
                        unresolved = True
                        continue
                    resident = _merge_delta_resident(previous, resident, actor_node)
                    if previous_key is not None and previous_key != key:
                        del residents[previous_key]
                    if residents.get(key) != resident:
                        residents[key] = resident
                        residents_changed = True
        for wrapper in leaving_wrappers:
            leaving_container = wrapper.get("children")
            if not isinstance(leaving_container, list):
                unresolved = True
                continue
            leaving = {
                value
                for node in _nodes_by_no(leaving_container, 1)
                for value in _packed_ids(node.get("raw"))
            }
            if leaving:
                for key, resident in tuple(residents.items()):
                    if resident.actor_id in leaving:
                        del residents[key]
                        residents_changed = True
                for actor_id in leaving:
                    eggs.pop(actor_id, None)
    if not actions:
        return None
    occupants: dict[str, list[int]] = {}
    for resident in residents.values():
        if resident.nest_guid:
            occupants.setdefault(resident.nest_guid, []).append(resident.actor_id)
    nests = tuple(replace(piece, resident_ids=tuple(occupants.get(piece.guid, ())))
                  for piece in snapshot.nests)
    updated = HomeSnapshot(
        room_level=snapshot.room_level,
        residents=tuple(residents.values()),
        nests=nests,
        couples=snapshot.couples,
        scene_eggs=tuple(eggs.values()),
        couples_stale=snapshot.couples_stale or residents_changed,
        owner_uid=snapshot.owner_uid,
    )
    return HomeDeltaResult(updated, unresolved)


__all__ = [
    "HomeCouple",
    "HomeDeltaResult",
    "HomeFurniture",
    "HomeResident",
    "HomeSceneEgg",
    "HomeSnapshot",
    "NEST_TYPES",
    "apply_home_delta",
    "extract_home",
    "home_floor",
]
