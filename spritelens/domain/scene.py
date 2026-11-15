"""场景观察字段提取；不推断完整 AOI，不换算坐标单位。"""
from __future__ import annotations

from dataclasses import dataclass

from spritelens.events import PacketEvent
from spritelens.protocol.wire import read_varint


@dataclass(frozen=True)
class SceneActor:
    actor_id: int
    config_id: int | None
    level: int | None
    position: tuple[int | None, int | None, int | None] | None
    height: int | None
    weight: int | None
    voice: int | None
    mutation: int | None
    glass_type: int | None
    glass_value: int | None
    updated_at: float
    source_opcode: int
    stale: bool = False
    pet_base_id: int | None = None


def nodes(fields: list[dict], no: int) -> list[dict]:
    return [field for field in fields if field.get("no") == no]


def children(fields: list[dict], no: int) -> list[dict]:
    node = next(iter(nodes(fields, no)), None)
    value = node.get("children") if node else None
    return value if isinstance(value, list) else []


def integer(fields: list[dict], no: int, *, signed: bool = False) -> int | None:
    node = next(iter(nodes(fields, no)), None)
    value = node.get("raw") if node else None
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    if signed:
        value &= (1 << 32) - 1
        if value >= 1 << 31:
            value -= 1 << 32
    return value


def position(fields: list[dict]) -> tuple[int | None, int | None, int | None] | None:
    if not fields:
        return None
    return (integer(fields, 1, signed=True), integer(fields, 2, signed=True),
            integer(fields, 3, signed=True))


def actor(node: dict, event: PacketEvent) -> tuple[SceneActor | None, bool]:
    """仅收录带测量字段的 NPC；其它 NPC/玩家不冒充野外精灵。"""
    raw = node.get("children")
    if not isinstance(raw, list):
        return None, True
    npc = children(raw, 11)
    base, config = children(npc, 1), children(npc, 3)
    # 家园蛋使用 detail_type 13 并附着在窝上；测量字段虽存在却全为零。
    if integer(base, 1) == 13 and integer(children(npc, 23), 2):
        return None, False
    if not any(nodes(config, no) for no in (11, 12, 31)):
        return None, False
    actor_id = integer(base, 2)
    if actor_id is None or actor_id <= 0:
        return None, True
    glass = children(config, 30)
    return SceneActor(actor_id, integer(config, 1), integer(base, 11),
        position(children(children(base, 8), 1)), integer(config, 11), integer(config, 12),
        integer(config, 31, signed=True), integer(config, 14), integer(glass, 1), integer(glass, 2),
        event.ts, event.opcode, pet_base_id=integer(children(npc, 8), 4)), False


def removed_ids(fields: list[dict]) -> tuple[tuple[int, ...], bool]:
    result = []
    invalid = False
    for field in nodes(fields, 1):
        raw = field.get("raw")
        if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0:
            result.append(raw)
        elif isinstance(raw, bytes):
            offset = 0
            while offset < len(raw):
                item = read_varint(raw, offset)
                if item is None:
                    invalid = True
                    break
                value, offset = item
                if value > 0:
                    result.append(value)
                else:
                    invalid = True
        else:
            invalid = True
    return tuple(result), invalid
