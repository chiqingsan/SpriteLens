"""参考范围位置与展示单位，不依赖当前筛选集合。"""
from __future__ import annotations


def range_position(value: int, limits: tuple[int, int] | list[int]) -> dict:
    low, high = limits
    if low <= 0 or high <= low or value <= 0:
        return {"ratio": None, "status": "unknown"}
    ratio = round((value - low) / (high - low), 4)
    return {"ratio": ratio, "status": "below" if ratio < 0 else "above" if ratio > 1 else "within"}


def range_text(limits: tuple[int, int] | list[int], scale: int, unit: str) -> str:
    low, high = limits
    if low <= 0 or high < low:
        return "暂无数据"
    return f"{low / scale:.2f}–{high / scale:.2f} {unit}"
