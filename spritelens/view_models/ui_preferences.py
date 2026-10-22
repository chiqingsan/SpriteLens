"""有限的界面偏好契约；业务筛选不持久化。"""
from __future__ import annotations

import math

from spritelens.repositories.settings import SettingsRepository

THEMES = frozenset({"miaomiao", "huohua", "shuilanlan"})
VIEWS = frozenset({"point", "card"})
FIELDS = ("groups", "height", "weight", "voice", "positions")
SHORTCUT_KEYS = frozenset({"search", "level_min", "level_max", "natures", "types", "gender", "egg_groups", "egg_mode",
    "pool", "pool_mode", "shiny", "colorful", "medals", "marks", "speciality", "acquisition", "captured_days",
    "voice_min", "voice_max",
    "height_position_min", "height_position_max", "weight_position_min", "weight_position_max"})


def validate_shortcuts(raw: object) -> list:
    if not isinstance(raw, list) or len(raw) > 256:
        raise ValueError("最多保存256组快捷条件")
    result = []
    for item in raw:
        if not isinstance(item, dict) or set(item) != {"name", "filters"}:
            raise ValueError("快捷条件格式无效")
        name, filters = item["name"], item["filters"]
        if not isinstance(name, str) or not name.strip() or len(name) > 40:
            raise ValueError("快捷条件名称无效")
        if not isinstance(filters, dict) or set(filters) - SHORTCUT_KEYS:
            raise ValueError("快捷条件字段无效")
        for key, value in filters.items():
            if key in ("shiny", "colorful"):
                valid = type(value) is bool
            elif key == "pool_mode":
                valid = value in ("and", "or")
            elif key in ("pool", "marks"):
                from spritelens.domain.pet_conditions import MARK_NAMES, POOL_KEYS
                allowed = POOL_KEYS if key == "pool" else MARK_NAMES
                valid = isinstance(value, list) and all(isinstance(item, str) and item in allowed for item in value)
            elif key in ("speciality", "acquisition", "captured_days"):
                valid = type(value) is int and value >= 0 and (key != "captured_days" or value in (0, 1, 3, 7))
            elif key in ("natures", "medals", "types", "egg_groups"):
                expected = int if key in ("natures", "medals") else str
                valid = isinstance(value, list) and len(value) <= 50 and all(type(v) is expected and (v >= (1 if key == "medals" else 0) if expected is int else 0 < len(v) <= 40) for v in value)
            elif key in ("search", "egg_mode"):
                valid = isinstance(value, str) and len(value) <= 100 and (key != "egg_mode" or value in ("any", "all"))
            elif key in ("level_min", "level_max", "gender"):
                valid = type(value) is int and 0 <= value <= 100 and (key != "gender" or value in (0, 1, 2))
            else:
                valid = value is None or (type(value) in (int, float) and math.isfinite(value) and abs(value) <= 1e9
                    and (key.startswith("voice") or value >= 0) and ("_position_" not in key or value <= 100))
            if not valid:
                raise ValueError("快捷条件值无效")
        result.append({"name": name.strip(), "filters": dict(filters)})
    return result


def validate_home_orders(raw: object) -> dict[str, list[str]]:
    if not isinstance(raw, dict) or len(raw) > 64:
        raise ValueError("家园排序账号数量无效")
    result: dict[str, list[str]] = {}
    for uid, actor_ids in raw.items():
        if (not isinstance(uid, str) or not uid.isascii() or not uid.isdecimal()
                or not 0 < int(uid) < 1 << 64 or str(int(uid)) != uid):
            raise ValueError("家园排序账号编号无效")
        if not isinstance(actor_ids, list) or len(actor_ids) > 2000:
            raise ValueError("家园排序列表无效")
        if any(not isinstance(actor_id, str) or not actor_id.isascii() or not actor_id.isdecimal()
               or not 0 < int(actor_id) < 1 << 64 or str(int(actor_id)) != actor_id for actor_id in actor_ids):
            raise ValueError("家园排序居民编号无效")
        if len(set(actor_ids)) != len(actor_ids):
            raise ValueError("家园排序居民编号重复")
        result[uid] = list(actor_ids)
    return result


def normalize_preferences(raw: object) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    fields = raw.get("fields") if isinstance(raw.get("fields"), dict) else {}
    try:
        shortcuts = validate_shortcuts(raw.get("shortcuts", []))
    except ValueError:
        shortcuts = []
    try:
        home_orders = validate_home_orders(raw.get("home_orders", {}))
    except ValueError:
        home_orders = {}
    return {"theme": raw.get("theme") if isinstance(raw.get("theme"), str) and raw.get("theme") in THEMES else "miaomiao",
            "pet_view": raw.get("pet_view") if isinstance(raw.get("pet_view"), str) and raw.get("pet_view") in VIEWS else "point",
            "fields": {key: fields[key] if isinstance(fields.get(key), bool) else key != "positions" for key in FIELDS},
            "shortcuts": shortcuts,
            "home_orders": home_orders}


class UIPreferencesViewModel:
    def __init__(self, settings: SettingsRepository) -> None:
        self._settings = settings

    def snapshot(self) -> dict:
        return normalize_preferences(self._settings.get_value("ui.preferences", {}))

    def update(self, changes: object) -> dict:
        if not isinstance(changes, dict) or set(changes) - {"theme", "pet_view", "fields", "shortcuts", "home_orders"}:
            raise ValueError("只允许界面偏好与快捷条件定义")
        if "theme" in changes and (not isinstance(changes["theme"], str) or changes["theme"] not in THEMES):
            raise ValueError("未知主题")
        if "pet_view" in changes and (not isinstance(changes["pet_view"], str) or changes["pet_view"] not in VIEWS):
            raise ValueError("未知背包视图")
        fields = changes.get("fields", {})
        if not isinstance(fields, dict) or set(fields) - set(FIELDS) or any(not isinstance(v, bool) for v in fields.values()):
            raise ValueError("显示字段必须是允许的布尔值")
        shortcuts = validate_shortcuts(changes["shortcuts"]) if "shortcuts" in changes else None
        home_orders = validate_home_orders(changes["home_orders"]) if "home_orders" in changes else None
        def merge(previous):
            value = normalize_preferences(previous)
            value.update({key: changes[key] for key in ("theme", "pet_view") if key in changes})
            value["fields"].update(fields)
            if shortcuts is not None:
                value["shortcuts"] = shortcuts
            if home_orders is not None:
                value["home_orders"] = home_orders
            return value
        return normalize_preferences(self._settings.update_checked("ui.preferences", merge))
