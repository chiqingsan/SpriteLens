"""家园语义层：0x014A 家园快照 → 居民 / 家具 / 产蛋窝（实证字段映射）。

映射依据：真实快照帧（eventlog 0x014A）实证 + 蛋神 home_scene.pyc 反汇编
交叉印证（docs/DANSHEN_FEATURE_SPEC.md §3.5）。字段号以实测为准：

    顶层   field7 = 房间（field1=roomLevel，field11=实体列表）
    居民   field2=actorId  field12=名字  field13=gender(1雄/2雌)
           field10=等级    field7→子消息(1)=position(x,y,z signed)
    家具   field1→子消息(1)=configId（710069=普通小窝）
           field19=guid    field26=朝向/状态
    窝     NEST_TYPES: configId → (kind, 名称)——710069=普通小窝
           （学院小窝 configId 未实证，出现时按 "#id" 显示）

已知边界：0x0413/0x0414 增量帧与 layEggCouples（产蛋配对）未解析——
待真实增量帧样本（需在游戏内挪动宠物/放窝时采集）。
"""

from __future__ import annotations

from dataclasses import dataclass

from spritelens.events import PacketEvent

OP_HOME_SNAPSHOT = 0x014A
OP_HOME_DELTA_A = 0x0413
OP_HOME_DELTA_B = 0x0414

# 家具 configId → (类型标识, 展示名)；与蛋神 NEST_TYPES 同源（反汇编还原）
NEST_TYPES: dict[int, tuple[str, str]] = {
    710069: ("ordinary", "普通小窝"),
}

_NO_ROOM = 7
_NO_ROOM_LEVEL = 1
_NO_ENTITIES = 11


@dataclass(frozen=True)
class HomeResident:
    """家园里的宠物居民。"""

    actor_id: int
    name: str
    gender: int  # 1 雄 / 2 雌 / 0 未知
    level: int
    position: tuple[int, int, int]


@dataclass(frozen=True)
class HomeFurniture:
    """家园家具（含产蛋窝标记）。"""

    config_id: int
    guid: str
    kind: str  # NEST_TYPES kind 或 "furniture"
    name: str  # 窝名 / "家具 #configId"
    position: tuple[int, int, int]


@dataclass(frozen=True)
class HomeSnapshot:
    """一次家园快照的解析结果。"""

    room_level: int
    residents: tuple[HomeResident, ...]
    furniture: tuple[HomeFurniture, ...]

    @property
    def nests(self) -> tuple[HomeFurniture, ...]:
        return tuple(f for f in self.furniture if f.kind != "furniture")


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


def _children_by_no(fields: list[dict], no: int) -> list[dict] | None:
    for item in fields:
        if item.get("no") == no:
            children = item.get("children")
            return children if isinstance(children, list) else None
    return None


def _text_by_no(fields: list[dict], no: int) -> str:
    for item in fields:
        if item.get("no") == no:
            text = item.get("text")
            return str(text) if isinstance(text, str) else ""
    return ""


def _position_of(fields: list[dict], no: int) -> tuple[int, int, int]:
    """字段号 no 的子消息 → (x, y, z) signed 三元组（field1/2/3）。"""
    children = _children_by_no(fields, no)
    if not children:
        return (0, 0, 0)
    inner = _children_by_no(children, 1) or []
    if not inner and len(children) >= 3:
        inner = children  # 已展开的 x/y/z
    xyz = [_coerce_int32(_raw_by_no(inner, i)) for i in (1, 2, 3)]
    return (xyz[0], xyz[1], xyz[2])


def _resident_from(fields: list[dict]) -> HomeResident | None:
    name = _text_by_no(fields, 12)
    if not name:
        return None
    actor_id = _coerce_int(_raw_by_no(fields, 2))
    if actor_id <= 0:
        return None
    return HomeResident(
        actor_id=actor_id,
        name=name,
        gender=_coerce_int(_raw_by_no(fields, 13)),
        level=_coerce_int(_raw_by_no(fields, 10)),
        position=_position_of(fields, 7),
    )


def _furniture_from(fields: list[dict]) -> HomeFurniture | None:
    # 实证：家具实体 field1 直接 = configId（如 710069=普通小窝）；
    # 居民实体的 field1 是重复子消息（raw=None）或伴随名字文本，天然排除
    config_id = _coerce_int(_raw_by_no(fields, 1))
    if config_id <= 0:
        return None
    if _text_by_no(fields, 12):  # 有宠物名文本 → 居民实体
        return None
    guid_raw = _raw_by_no(fields, 19)
    if isinstance(guid_raw, (bytes, bytearray)):
        guid = guid_raw.hex()
    elif isinstance(guid_raw, int) and guid_raw > 0:
        guid = f"{guid_raw:016x}"
    else:
        guid = ""
    if not guid and config_id not in NEST_TYPES:
        # 无实例 guid 且非已知窝 → 场景杂项实体（如类型标记 field1=1），排除
        return None
    kind, name = NEST_TYPES.get(config_id, ("furniture", f"家具 #{config_id}"))
    return HomeFurniture(
        config_id=config_id,
        guid=guid,
        kind=kind,
        name=name,
        position=_position_of(fields, 7),
    )


def _entities_of(event: PacketEvent) -> tuple[int, list[dict]]:
    """取房间层级：顶层 field7 → roomLevel + 实体列表。"""
    root = event.decoded or []
    room = _children_by_no(root, _NO_ROOM)
    if not room:
        return 0, []
    level = _coerce_int(_raw_by_no(room, _NO_ROOM_LEVEL))
    entities = _children_by_no(room, _NO_ENTITIES) or []
    return level, entities


def extract_home(event: PacketEvent) -> HomeSnapshot | None:
    """解析家园快照事件；非快照帧返回 None。"""
    if event.direction != "s2c" or event.opcode != OP_HOME_SNAPSHOT:
        return None
    level, entities = _entities_of(event)
    residents: list[HomeResident] = []
    furniture: list[HomeFurniture] = []
    seen_residents: set[int] = set()
    for entity in entities:
        fields = entity.get("children") if isinstance(entity, dict) else None
        if not isinstance(fields, list):
            continue
        resident = _resident_from(fields)
        if resident is not None and resident.actor_id not in seen_residents:
            seen_residents.add(resident.actor_id)
            residents.append(resident)
        piece = _furniture_from(fields)
        if piece is not None:
            furniture.append(piece)
    return HomeSnapshot(
        room_level=level,
        residents=tuple(residents),
        furniture=tuple(furniture),
    )


__all__ = [
    "HomeFurniture",
    "HomeResident",
    "HomeSnapshot",
    "NEST_TYPES",
    "extract_home",
]
