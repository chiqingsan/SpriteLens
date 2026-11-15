"""伙伴标记增量：游戏内改/摘标记只发这条回执，不含完整 PetData。

实测（2026-10-29 真实对局，见 docs/PROTOCOL_NOTES.md「伙伴标记实时更新」）::

    c2s 0x0402 ZoneUpdatePetCollectTagReq
        {collection_info{3: partner_mark, 1: pet_gid}, 2: 1}
    s2c 0x0403 ZoneUpdatePetCollectTagRsp
        {ret_info{1: ret_code, 4: goods_change_info{1: changes{
            1: type=39, 2: op=2, 3: num=标记值, 14: gid}}}}

0x0403 既没有 conf_id 也没有完整宠物节点，``extract_pets`` 的形状搜索永远
命不中；不单独解析，伙伴标记就只能等下一次宠物背包分页刷新（0x1346）才更新。
"""

from __future__ import annotations

from spritelens.events import PacketEvent

# 0x0403 ZoneUpdatePetCollectTagRsp：设置收集标签（伙伴标记）的成功回执
_OPCODE_UPDATE_COLLECT_TAG_RSP = 0x0403

# RetInfo
_NO_RET_INFO = 1
_NO_RET_CODE = 1
_NO_GOODS_CHANGE_INFO = 4
# GoodsChange
_NO_CHANGES = 1
# GoodsChangeItem
_NO_CHANGE_TYPE = 1
_NO_CHANGE_NUM = 3
_NO_CHANGE_GID = 14
# 标记资源类型：实测样本恒为 39，num 与 c2s 请求里的 partner_mark 一致
_PARTNER_MARK_GOODS_TYPE = 39


def _raw(fields: list[dict], no: int) -> object:
    """按字段号取 raw（不依赖 schema 命名）。"""
    for item in fields:
        if item.get("no") == no:
            return item.get("raw")
    return None


def _change_field_lists(node: dict) -> list[list[dict]]:
    """展开一条 changes 节点里的 GoodsChangeItem 字段列表。

    解码器对 repeated 字段的处理是展平的：单条变化时 changes 的 children
    直接就是 type/op/num/gid 等字段（实测 0x0403）；若将来出现外层容器
    （children 里再套 children），这里一并兼容。
    """
    children = node.get("children")
    if not isinstance(children, list) or not children:
        return []
    if all("children" not in item for item in children):
        return [children]
    return [item["children"] for item in children if isinstance(item.get("children"), list)]


def extract_partner_marks(event: PacketEvent) -> dict[int, int] | None:
    """返回 {gid: 新伙伴标记值}；不是成功的 0x0403 回执时返回 None。

    标记值缺省按 0 解释（摘除标记的样本尚未采集，op 语义未确认）。
    """
    if event.direction != "s2c" or not event.decoded:
        return None
    # 回放/单测里的事件对象可能只带 direction+decoded，取不到 opcode 视为不匹配
    if getattr(event, "opcode", 0) != _OPCODE_UPDATE_COLLECT_TAG_RSP:
        return None
    ret_info = next((item for item in event.decoded if item.get("no") == _NO_RET_INFO), None)
    if not isinstance(ret_info, dict):
        return None
    ret_children = ret_info.get("children")
    if not isinstance(ret_children, list):
        return None
    ret_code = _raw(ret_children, _NO_RET_CODE)
    if not isinstance(ret_code, int) or ret_code != 0:
        return None
    goods = next((item for item in ret_children if item.get("no") == _NO_GOODS_CHANGE_INFO), None)
    goods_children = goods.get("children") if isinstance(goods, dict) else None
    if not isinstance(goods_children, list):
        return None
    marks: dict[int, int] = {}
    for node in goods_children:
        if node.get("no") != _NO_CHANGES:
            continue
        for fields in _change_field_lists(node):
            if _raw(fields, _NO_CHANGE_TYPE) != _PARTNER_MARK_GOODS_TYPE:
                continue
            gid = _raw(fields, _NO_CHANGE_GID)
            if not isinstance(gid, int) or gid <= 0:
                continue
            value = _raw(fields, _NO_CHANGE_NUM)
            marks[gid] = value if isinstance(value, int) and value >= 0 else 0
    return marks or None


__all__ = ["extract_partner_marks"]
