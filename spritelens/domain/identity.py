"""玩家身份语义层：从 PacketEvent 字段树中提取「自己」的账号标识。

只认当前玩家的两条已核验路径：登录响应 0x0102 的
`player_info → brief_info`，以及进场景的 `self_info → avatar → base`。
不能递归搜索所有玩家结构——实测
ZoneSceneClientEnterSceneFinishNtyAck 的 other_actors 下 NPC 也带
logic_id（如「护主犬」435444924297510922），误取会把 NPC 编号当账号。

实测依据（2026-10-09 真实流量）：ZoneEnterSceneRsp(0x0152) 的
self_info.avatar.base.{logic_id=101384922, name="话绵雨", lv=55}；
logic_id 与外部工具记录的账号 uid 一致，且该消息先于宠物推送到达
（同一会话内行号 853 vs 933），因此宠物可稳定归属到账号。
"""

from __future__ import annotations

from dataclasses import dataclass

from spritelens.services.monitor_service import PacketEvent

_SELF_INFO = "self_info"
_AVATAR = "avatar"
_BASE = "base"
_LOGIC_ID = "logic_id"
_NAME = "name"
_LEVEL = "lv"


@dataclass(frozen=True)
class PlayerIdentity:
    """当前登录角色：uid（logic_id）为账号级标识，会话内唯一。"""

    uid: int
    name: str
    level: int


def _find(fields: list[dict], name: str) -> dict | None:
    for field in fields:
        if field.get("name") == name:
            return field
    return None


def _descend(fields: list[dict], *names: str) -> dict | None:
    """按名字逐层下钻；任一层缺失返回 None（结构不完整不猜测）。"""
    node: dict | None = None
    current = fields
    for name in names:
        node = _find(current, name)
        if node is None:
            return None
        current = node.get("children") or []
    return node


def _raw_int(field: dict | None, default: int = 0) -> int:
    if field is None:
        return default
    raw = field.get("raw")
    return raw if isinstance(raw, int) else default


def _raw_text(field: dict | None) -> str:
    """raw 可能是 bytes（wire 原值）或 str（经 JSONL 落盘回读），两者都收。"""
    if field is None:
        return ""
    raw = field.get("raw")
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return raw if isinstance(raw, str) else ""


def extract_identity(event: PacketEvent) -> PlayerIdentity | None:
    """从一条 s2c 事件中提取当前角色身份；无命中返回 None。"""
    if event.direction != "s2c":
        return None
    # 登录响应早于进场景；只认经核验的当前玩家路径，不能搜索其他玩家/NPC。
    if getattr(event, "opcode", None) == 0x0102:
        brief = _descend(event.decoded, "player_info", "brief_info")
        if brief is not None:
            children = brief.get("children") or []
            uid = _raw_int(_find(children, "uin"))
            if uid > 0:
                return PlayerIdentity(uid, _raw_text(_find(children, "name")), _raw_int(_find(children, "role_level")))
    for node in event.decoded:
        if node.get("name") != _SELF_INFO:
            continue
        base = _descend(node.get("children") or [], _AVATAR, _BASE)
        if base is None:
            continue
        children = base.get("children") or []
        uid = _raw_int(_find(children, _LOGIC_ID))
        if uid <= 0:
            continue
        return PlayerIdentity(
            uid=uid,
            name=_raw_text(_find(children, _NAME)),
            level=_raw_int(_find(children, _LEVEL)),
        )
    resumed = getattr(event, "resumed_identity", None)
    return PlayerIdentity(*resumed) if resumed is not None else None


__all__ = ["PlayerIdentity", "extract_identity"]
