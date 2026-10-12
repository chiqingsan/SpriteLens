"""server 的共享小助手：query 解析与版本号（独立模块便于路由 mixin 复用）。"""

from __future__ import annotations


def _as_int(value: str | None, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value: str | None) -> bool:
    return (value or "").lower() in ("1", "true", "yes", "on")


def _id_set(value: str | None) -> set[int]:
    try:
        return {int(part) for part in (value or "").split(",") if part.strip()}
    except ValueError:
        return set()


def _name_set(value: str | None) -> set[str]:
    return {part.strip() for part in (value or "").split(",") if part.strip()}
