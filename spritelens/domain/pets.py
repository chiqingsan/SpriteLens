"""宠物语义层：从 PacketEvent 的字段树中提取宠物业务对象。

采用「形状搜索」而非固定消息路径：只要某个嵌套节点拥有宠物对象的
指纹字段（gid/conf_id/level），即判定为宠物并提取——不依赖 opcode
映射是否齐全，也不怕外层消息结构随版本变化。

字段取值同时支持两条路径：优先按 **字段号**（no）定位，名字仅作辅助。
实测表明 schema 命名会随版本漂移（如手写文件覆盖全量定义导致大量
field_N），而字段号与 raw 值稳定，因此关键字段一律以字段号为准。
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from spritelens.events import PacketEvent

# 形状指纹：gid/conf_id 必含（唯一标识 + 图鉴 ID），再加至少一个宠物特征字段。
# 不强制 level/name——proto 可选字段未设置时 wire 上不会出现。
_PET_REQUIRED = frozenset({"gid", "conf_id"})
_PET_TRAITS = frozenset({"name", "level", "exp", "nature", "gender", "blood_id", "talent_rank", "is_first_catch"})

# PetData 字段号（实测确认，见 data/schemas/messages/all.json）
_NO_GID = 1
_NO_CONF_ID = 2
_NO_NAME = 3
_NO_NATURE = 7
_NO_GENDER = 8
_NO_EXP = 9
_NO_LEVEL = 10
_NO_BALL_ID = 11
_NO_SKILL = 12
_NO_ATTRIBUTE = 14
_NO_BASE_CONF_ID = 15
# 炫彩形态 conf_id（130xxx/5400xxx 系，花种帧引用的就是它；实测 210/214 覆盖）
_NO_COLORFUL_CONF_ID = 58
# glass 外观参数（色卡来源，decode_handbook_glass：field86 子消息 {1:type, 2:value}；
# 实测 162/266 只携带，普通宠物 type=1/value=1，赛季卡 type=2 值含赛季位）
_NO_GLASS = 86
_GLASS_TYPE = 1
_GLASS_VALUE = 2
_NO_HEIGHT = 26
_NO_WEIGHT = 27
_NO_CLASSIS = 28
_NO_BREAKTHROUGH = 30
_NO_MUTATION = 45
_NO_BLOOD = 47
_NO_TALENT_RANK = 55
_NO_SPECIALITY = 82
_NO_VOICE = 93

# PetAttributeInfo 六维顺序（字段号 → 名称）
_ATTR_SLOTS: tuple[tuple[int, str], ...] = (
    (1, "hp"),
    (2, "atk"),
    (3, "spa"),
    (4, "def"),
    (5, "spd"),
    (6, "spe"),
)

# PetAttributeData 子字段号
_ATTR_SUB = {"total_race": 1, "talent": 2, "base_value": 3, "effort_add": 6, "talent_add": 7}


@dataclass(frozen=True)
class PetAttribute:
    """六维中的一维：种族值 / 天赋 / 实际值。"""

    total_race: int = 0
    talent: int = 0
    base_value: int = 0
    effort_add: int = 0
    talent_add: int = 0

    @property
    def final_value(self) -> int:
        """实际面板值 = 基础值 + 天赋修正 + 努力加成。"""
        return self.base_value + self.talent_add + self.effort_add


@dataclass(frozen=True)
class PetSkill:
    """宠物技能条目（PetSkillData）。"""

    skill_id: int = 0
    conf_idx: int = 0
    is_learned: bool = False
    is_equipped: bool = False
    pos: int = 0
    unlock_need_lv: int = 0
    use_times: int = 0


@dataclass(frozen=True)
class Pet:
    """仓库里的一只宠物（会话内快照行）。"""

    gid: int
    conf_id: int
    name: str
    level: int
    exp: int
    nature: int
    gender: int
    blood_id: int
    talent_rank: int
    is_first_catch: bool
    # -- v2 扩展：六维与外观（缺失时为零值，不参与形状判定）-------------
    base_conf_id: int = 0
    attributes: tuple[PetAttribute, ...] = ()
    height: int = 0
    weight: int = 0
    voice: int = 0
    mutation_type: int = 0
    classis: int = 0
    breakthrough_lv: int = 0
    speciality_id: int = 0
    ball_id: int = 0
    colorful_conf_id: int = 0  # 炫彩形态 id（花种帧按它引用；0=未知）
    glass_type: int = 0  # glass 外观参数（色卡底色维度；0=帧中无）
    glass_value: int = 0  # glass 混色维度
    worn_medal_id: int = 0  # 服务端佩戴奖牌，不从体型阈值推算
    awarded_medal_ids: tuple[int, ...] | None = None  # None=集合未采集；空元组=已确认没有
    skills: tuple[PetSkill, ...] = ()
    is_trial_pet: bool = False  # 服务端试用个体，不属于自己的精灵库存
    is_mirror_pet: bool = False  # 好友队伍镜像，不属于自己的精灵库存
    catch_way: int = 0  # PetData 字段67，0为未提供
    add_time: int = 0  # PetData 字段32，游戏获得时间（Unix秒），不使用落库时间

    def attribute(self, slot: str) -> PetAttribute:
        """按名称（hp/atk/spa/def/spd/spe）取某一维；越界返回零值。"""
        index = next((i for i, (_, name) in enumerate(_ATTR_SLOTS) if name == slot), None)
        if index is None or index >= len(self.attributes):
            return PetAttribute()
        return self.attributes[index]


def _node_fields(fields: list[dict]) -> dict[str, object] | None:
    """把一个节点（字段 dict 列表）转成 名称→raw 映射；非宠物形状返回 None。"""
    names: dict[str, object] = {}
    for field_dict in fields:
        name = field_dict.get("name")
        if isinstance(name, str) and name in (_PET_REQUIRED | _PET_TRAITS):
            names[name] = field_dict.get("raw")
    if not _PET_REQUIRED.issubset(names):
        return None
    return names if _PET_TRAITS & names.keys() else None


def _coerce_int(value: object) -> int:
    return value if isinstance(value, int) else 0


def _coerce_int32(value: object) -> int:
    """按 int32 解释（wire 上是无符号 varint，负数会表现为 2^64 附近的巨值）。"""
    raw = _coerce_int(value)
    if 0 <= raw < (1 << 31):
        return raw
    if raw >= (1 << 63):  # 无符号回绕：还原为负值
        raw -= 1 << 64
    if -(1 << 31) <= raw < (1 << 31):
        return raw
    return 0


def _coerce_pet(fields_map: dict[str, object]) -> Pet:
    name_raw = fields_map.get("name")
    if isinstance(name_raw, bytes):
        name = name_raw.decode("utf-8", errors="replace")
    elif isinstance(name_raw, str):
        name = name_raw
    else:
        name = ""
    first_catch = fields_map.get("is_first_catch")
    return Pet(
        gid=_coerce_int(fields_map.get("gid")),
        conf_id=_coerce_int(fields_map.get("conf_id")),
        name=name,
        level=_coerce_int(fields_map.get("level")),
        exp=_coerce_int(fields_map.get("exp")),
        nature=_coerce_int(fields_map.get("nature")),
        gender=_coerce_int(fields_map.get("gender")),
        blood_id=_coerce_int(fields_map.get("blood_id")),
        talent_rank=_coerce_int(fields_map.get("talent_rank")),
        is_first_catch=bool(first_catch) if isinstance(first_catch, int) else False,
    )


def _raw_by_no(fields: list[dict], no: int) -> object:
    """按字段号取 raw（schema 命名漂移时仍可用）。"""
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


def _attr_from_children(children: list[dict] | None) -> PetAttribute:
    if not children:
        return PetAttribute()
    return PetAttribute(
        total_race=_coerce_int(_raw_by_no(children, _ATTR_SUB["total_race"])),
        talent=_coerce_int(_raw_by_no(children, _ATTR_SUB["talent"])),
        base_value=_coerce_int(_raw_by_no(children, _ATTR_SUB["base_value"])),
        effort_add=_coerce_int(_raw_by_no(children, _ATTR_SUB["effort_add"])),
        talent_add=_coerce_int(_raw_by_no(children, _ATTR_SUB["talent_add"])),
    )


def _skills_from_children(children: list[dict] | None) -> tuple[PetSkill, ...]:
    """技能列表：field 12 → repeated PetSkillInfo{1: PetSkillData}。"""
    if not children:
        return ()
    skills: list[PetSkill] = []
    for entry in children:
        data_children = entry.get("children")
        if not isinstance(data_children, list):
            continue
        skills.append(
            PetSkill(
                skill_id=_coerce_int(_raw_by_no(data_children, 1)),
                is_learned=bool(_coerce_int(_raw_by_no(data_children, 3))),
                is_equipped=bool(_coerce_int(_raw_by_no(data_children, 4))),
                pos=_coerce_int(_raw_by_no(data_children, 5)),
                unlock_need_lv=_coerce_int(_raw_by_no(data_children, 8)),
                conf_idx=_coerce_int(_raw_by_no(data_children, 13)),
                use_times=_coerce_int(_raw_by_no(data_children, 16)),
            )
        )
    return tuple(skills)


def _extend_pet(base: Pet, node: list[dict]) -> Pet:
    """在基础字段之上补齐六维与外观字段（全部按字段号取值）。"""
    attributes: list[PetAttribute] = []
    attr_root = _children_by_no(node, _NO_ATTRIBUTE)
    if attr_root is not None:
        for slot_no, _slot_name in _ATTR_SLOTS:
            attributes.append(_attr_from_children(_children_by_no(attr_root, slot_no)))
    return Pet(
        gid=base.gid,
        conf_id=base.conf_id,
        name=base.name,
        level=base.level,
        exp=base.exp,
        nature=base.nature,
        gender=base.gender,
        blood_id=base.blood_id,
        talent_rank=base.talent_rank,
        is_first_catch=base.is_first_catch,
        base_conf_id=_coerce_int(_raw_by_no(node, _NO_BASE_CONF_ID)),
        attributes=tuple(attributes),
        height=_coerce_int(_raw_by_no(node, _NO_HEIGHT)),
        weight=_coerce_int(_raw_by_no(node, _NO_WEIGHT)),
        voice=_coerce_int32(_raw_by_no(node, _NO_VOICE)),
        mutation_type=_coerce_int(_raw_by_no(node, _NO_MUTATION)),
        classis=_coerce_int(_raw_by_no(node, _NO_CLASSIS)),
        breakthrough_lv=_coerce_int(_raw_by_no(node, _NO_BREAKTHROUGH)),
        speciality_id=_coerce_int(_raw_by_no(node, _NO_SPECIALITY)),
        ball_id=_coerce_int(_raw_by_no(node, _NO_BALL_ID)),
        colorful_conf_id=_coerce_int(_raw_by_no(node, _NO_COLORFUL_CONF_ID)),
        glass_type=_glass_dim(node, _GLASS_TYPE),
        glass_value=_glass_dim(node, _GLASS_VALUE),
        worn_medal_id=_coerce_int(_raw_by_no(node, 73)),
        catch_way=max(0, _coerce_int32(_raw_by_no(node, 67))),
        add_time=_coerce_int(_raw_by_no(node, 32)),
        skills=_skills_from_children(_children_by_no(node, _NO_SKILL)),
        is_trial_pet=bool(_coerce_int(_raw_by_no(node, 81))),
    )


def _glass_dim(node: dict[str, object], child_no: int) -> int:
    """glass 子消息（field86: {1: type, 2: value}）的维度值；缺失返回 0。"""
    children = _children_by_no(node, _NO_GLASS)
    if not children:
        return 0
    return _coerce_int(_raw_by_no(children, child_no))


def _walk(fields: list[dict], out: list[Pet], *, mirror: bool = False) -> None:
    node = _node_fields(fields)
    if node is not None:
        out.append(replace(_extend_pet(_coerce_pet(node), fields), is_mirror_pet=mirror))
        return  # 命中后不再下钻（宠物内的嵌套属性不是独立宠物）
    for field_dict in fields:
        children = field_dict.get("children")
        if isinstance(children, list):
            _walk(children, out, mirror=mirror or field_dict.get("name") == "mirror_pet_data")


def extract_pets(event: PacketEvent, *, include_non_owned: bool = False) -> list[Pet]:
    """提取宠物；默认排除试用/镜像，仓库保留归属标记以修正历史误收。"""
    if event.direction != "s2c" or not event.decoded:
        return []
    pets: list[Pet] = []
    _walk(event.decoded, pets)
    return pets if include_non_owned else [pet for pet in pets if not pet.is_trial_pet and not pet.is_mirror_pet]
