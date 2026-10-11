"""蛋仓语义层：从 PacketEvent 的字段树中提取蛋条目（形状搜索）。

形状指纹（字段号实测规格，见 docs/DANSHEN_FEATURE_SPEC.md §4）：
    蛋行   field1=instanceId(>0)  field2=itemConfId(>0)  field3=quantity
           field4=obtainedAtUnix  field14=bagType(==8)   field15=detail 子消息
    detail field1=petConfId  2=height_cm  3=weight_g  4=hatchedSeconds
           5=hatchUpdatedAt  6=hatchSeconds  9=startHatchTime  10=category
           17=specialEggConfId  18=appearanceType  21=extensionType

bagType==8 是蛋背包的独占标记；detail 子消息必须含孵化/身高/体重特征之一，
用于与宠物节点（field1/field2 同为 int 但无 bagType）区分。

来源覆盖：0x1344 蛋背包分页（全量快照）、0x0243 家园拾蛋结果、0x0164/0x0300
蛋操作响应——形状搜索不区分路径，任何深度的蛋形状节点都会被提取。
"""

from __future__ import annotations

from dataclasses import dataclass

from spritelens.services.monitor_service import PacketEvent

_NO_INSTANCE_ID = 1
_NO_ITEM_CONF_ID = 2
_NO_QUANTITY = 3
_NO_OBTAINED_AT = 4
_NO_BAG_TYPE = 14
_NO_DETAIL = 15
# detail 子消息内的字段号
_D_PET_CONF_ID = 1
_D_HEIGHT_CM = 2
_D_WEIGHT_G = 3
_D_HATCHED_SECONDS = 4
_D_HATCH_UPDATED_AT = 5
_D_HATCH_SECONDS = 6
_D_START_HATCH_TIME = 9
_D_CATEGORY = 10
_D_SPECIAL_EGG_CONF_ID = 17
_D_APPEARANCE_TYPE = 18
_D_EXTENSION_TYPE = 21

BAG_TYPE_EGG = 8
OP_HATCH_SLOTS = 0x0312

_EGG_TRAIT_NOS = (_D_HATCH_SECONDS, _D_HEIGHT_CM, _D_WEIGHT_G, _D_CATEGORY)


@dataclass(frozen=True)
class EggBoxEntry:
    """一枚蛋（按 instance_id 唯一；quantity>1 表示堆叠的同类蛋）。"""

    instance_id: int
    egg_conf_id: int  # itemConfId，联查蛋目录（data/static/eggs.json 的 egg_conf_id）
    pet_conf_id: int  # detail.petConfId（物种侧 ID）
    quantity: int
    obtained_at: int  # unix 秒
    bag_type: int
    height_cm: int
    weight_g: int
    hatch_seconds: int  # 总孵化时长
    hatched_seconds: int  # 已孵化时长（>0 即在孵）
    hatch_updated_at: int
    start_hatch_time: int
    category: int
    special_egg_conf_id: int
    appearance_type: int
    extension_type: int

    @property
    def hatching(self) -> bool:
        return self.hatched_seconds > 0 or self.start_hatch_time > 0

    @property
    def hatch_progress(self) -> float:
        """孵化进度 0..1（无孵化时长数据时为 0）。"""
        if self.hatch_seconds <= 0:
            return 0.0
        return min(1.0, self.hatched_seconds / self.hatch_seconds)


def _coerce_int(value: object) -> int:
    return value if isinstance(value, int) else 0


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


def _egg_from_node(fields: list[dict]) -> EggBoxEntry | None:
    """节点字段列表 → 蛋条目；形状不符返回 None。"""
    bag_type = _coerce_int(_raw_by_no(fields, _NO_BAG_TYPE))
    if bag_type != BAG_TYPE_EGG:
        return None
    instance_id = _coerce_int(_raw_by_no(fields, _NO_INSTANCE_ID))
    item_conf_id = _coerce_int(_raw_by_no(fields, _NO_ITEM_CONF_ID))
    if instance_id <= 0 or item_conf_id <= 0:
        return None
    detail = _children_by_no(fields, _NO_DETAIL)
    if detail is None:
        return None
    # detail 特征：孵化时长/身高/体重/分类至少出现一项（排除巧合的同号节点）
    if not any(_raw_by_no(detail, no) is not None for no in _EGG_TRAIT_NOS):
        return None

    def detail_int(no: int) -> int:
        return _coerce_int(_raw_by_no(detail, no))

    return EggBoxEntry(
        instance_id=instance_id,
        egg_conf_id=item_conf_id,
        pet_conf_id=detail_int(_D_PET_CONF_ID),
        quantity=max(0, _coerce_int(_raw_by_no(fields, _NO_QUANTITY))),
        obtained_at=_coerce_int(_raw_by_no(fields, _NO_OBTAINED_AT)),
        bag_type=bag_type,
        height_cm=detail_int(_D_HEIGHT_CM),
        weight_g=detail_int(_D_WEIGHT_G),
        hatch_seconds=detail_int(_D_HATCH_SECONDS),
        hatched_seconds=detail_int(_D_HATCHED_SECONDS),
        hatch_updated_at=detail_int(_D_HATCH_UPDATED_AT),
        start_hatch_time=detail_int(_D_START_HATCH_TIME),
        category=detail_int(_D_CATEGORY),
        special_egg_conf_id=detail_int(_D_SPECIAL_EGG_CONF_ID),
        appearance_type=detail_int(_D_APPEARANCE_TYPE),
        extension_type=detail_int(_D_EXTENSION_TYPE),
    )


def _walk(fields: list[dict], out: list[EggBoxEntry]) -> None:
    entry = _egg_from_node(fields)
    if entry is not None:
        out.append(entry)
        return  # 命中后不再下钻（detail 内部不会再有蛋）
    for field_dict in fields:
        children = field_dict.get("children")
        if isinstance(children, list):
            _walk(children, out)


def extract_eggs(event: PacketEvent) -> list[EggBoxEntry]:
    """从事件字段树提取蛋条目（形状搜索，s2c 才可能有）。"""
    if event.direction != "s2c" or not event.decoded:
        return []
    out: list[EggBoxEntry] = []
    _walk(event.decoded, out)
    return out


def extract_hatch_slots(event: PacketEvent) -> tuple[int, ...] | None:
    """0x0312 孵化槽帧 → 正在孵化的蛋 instanceId 列表（实测结构）。

    root.field1(成功).field4 = 版本对；顶层 field2 = 重复 varint（槽中蛋 id），
    field3 = 重复 varint（已完成/关联队列，非槽位）——与蛋神规格
    decode_egg_hatch_slots 的"root.field2 = 重复值"一致。
    """
    if event.direction != "s2c" or event.opcode != OP_HATCH_SLOTS or not event.decoded:
        return None
    ids: list[int] = []
    for item in event.decoded:
        if item.get("no") != 2:
            continue
        value = item.get("raw")
        if isinstance(value, int) and 0 < value <= 0xFFFFFFFF:
            ids.append(value)
    return tuple(ids)


__all__ = ["BAG_TYPE_EGG", "EggBoxEntry", "extract_eggs", "extract_hatch_slots", "OP_HATCH_SLOTS"]
