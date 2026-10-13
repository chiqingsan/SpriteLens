"""背包新增筛选的 HTTP 边界；不写共享 ViewModel 状态。"""
from __future__ import annotations

from collections.abc import Mapping
from spritelens.domain.pet_conditions import MARK_NAMES, POOL_KEYS


def pet_ui_query(query: Mapping[str, str]) -> dict:
    pool = frozenset(filter(None, query.get("pool", "").split(",")))
    marks = frozenset(filter(None, query.get("marks", "").split(",")))
    mode = query.get("pool_mode", "and")
    if pool - POOL_KEYS or marks - set(MARK_NAMES) or mode not in ("and", "or"):
        raise ValueError("条件池或快捷条件无效")
    result = {"pool": pool, "pool_mode": mode, "marks": marks}
    for key in ("shiny", "colorful"):
        value = query.get(key, "0")
        if value not in ("0", "1"):
            raise ValueError("异色与炫彩条件无效")
        result[key] = value == "1"
    for key in ("medal", "speciality", "acquisition", "captured_days"):
        value = query.get(key, "0")
        if not value.isdecimal():
            raise ValueError("奖牌或特性条件无效")
        result[key] = int(value)
    if result["captured_days"] not in (0, 1, 3, 7):
        raise ValueError("捕获日期条件无效")
    return result
