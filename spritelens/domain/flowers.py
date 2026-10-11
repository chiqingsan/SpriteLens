"""炫彩花种语义层：0x0375 花田帧 → 我的花 / 好友花田（实证字段映射）。

帧结构（本机 0x0375 实测，与蛋神 flower_seeds 的 list/detail 模式对应）：
    field1 = 成功码（子消息 field1 == 0）
    field2 = 重复子消息，自己的花田槽位：
             field1=槽位 id(2012x)  field2=花种类型(5)  field3=槽位序号
             field5=数值  field6/7=guid 对  field8=实例 id
             field10=种植时间(unix)  field13=花对应的宠物 conf_id
             field19=1  field25=(2)
    field3 = 重复子消息，好友花田（比我的花多 field14=(height/weight/voice?)
             field15/16/17/19/21）
    field4 = 重复子消息，好友分组摘要（field2=日期 unix、field3=数量）

0x0376（field1=700xxx 记录，field10 为未来时间）暂不解析——样本少，
待二次采集确认语义后并入。
"""

from __future__ import annotations

from dataclasses import dataclass

from spritelens.services.monitor_service import PacketEvent

OP_FLOWER_SNAPSHOT = 0x0375


@dataclass(frozen=True)
class FlowerRecord:
    """一个花田槽位上的花。"""

    slot_id: int
    slot_index: int
    pet_conf_id: int  # 花对应的宠物（花种结出的蛋/宠）
    planted_at: int
    height: int
    weight: int
    voice: int
    owner: str  # "self" / "friend"


@dataclass(frozen=True)
class FlowerSnapshot:
    own: tuple[FlowerRecord, ...]
    friends: tuple[FlowerRecord, ...]

    @property
    def all_records(self) -> tuple[FlowerRecord, ...]:
        return self.own + self.friends


def _coerce_int(value: object) -> int:
    return value if isinstance(value, int) else 0


def _raw_by_no(fields: list[dict], no: int) -> object:
    for item in fields:
        if item.get("no") == no:
            return item.get("raw")
    return None


def _record_from(fields: list[dict], owner: str) -> FlowerRecord | None:
    slot_id = _coerce_int(_raw_by_no(fields, 1))
    if slot_id <= 0:
        return None
    extra = _children_by_no_(fields, 14)
    dims = [0, 0, 0]
    if extra:
        dims = [_coerce_int(_raw_by_no(extra, i)) for i in (1, 2, 3)]
    return FlowerRecord(
        slot_id=slot_id,
        slot_index=_coerce_int(_raw_by_no(fields, 3)),
        pet_conf_id=_coerce_int(_raw_by_no(fields, 13)),
        planted_at=_coerce_int(_raw_by_no(fields, 10)),
        height=dims[0],
        weight=dims[1],
        voice=dims[2],
        owner=owner,
    )


def _children_by_no_(fields: list[dict], no: int) -> list[dict] | None:
    for item in fields:
        if item.get("no") == no:
            children = item.get("children")
            return children if isinstance(children, list) else None
    return None


def _success(fields: list[dict]) -> bool:
    ok_block = _children_by_no_(fields, 1)
    if not ok_block:
        return False
    return _coerce_int(_raw_by_no(ok_block, 1)) == 0


def _repeated(fields: list[dict], no: int) -> list[list[dict]]:
    """字段 no 的重复子消息 → 每条的字段列表。

    实测：0x0375 的 field2/field3 各是单个节点，其 children 为重复的
    field1 子消息（每条一朵花），因此下钻两层。
    """
    out = []
    for item in fields:
        if item.get("no") == no:
            children = item.get("children") or []
            for sub in children:
                sub_children = sub.get("children")
                if isinstance(sub_children, list):
                    out.append(sub_children)
    return out


def extract_flowers(event: PacketEvent) -> FlowerSnapshot | None:
    if event.direction != "s2c" or event.opcode != OP_FLOWER_SNAPSHOT or not event.decoded:
        return None
    if not _success(event.decoded):
        return None
    own = [
        r for block in _repeated(event.decoded, 2)
        if (r := _record_from(block, "self")) is not None
    ]
    friends = [
        r for block in _repeated(event.decoded, 3)
        if (r := _record_from(block, "friend")) is not None
    ]
    if not own and not friends:
        return None
    return FlowerSnapshot(own=tuple(own), friends=tuple(friends))


__all__ = ["FlowerRecord", "FlowerSnapshot", "extract_flowers"]
