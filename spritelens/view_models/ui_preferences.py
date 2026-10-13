"""有限的界面偏好契约；业务筛选不持久化。"""
from __future__ import annotations

import math

from spritelens.repositories.settings import SettingsRepository

THEMES = frozenset({"miaomiao", "huohua", "shuilanlan"})
VIEWS = frozenset({"point", "card", "table"})
IMAGE_MODES = frozenset({"portrait", "artwork"})
FIELDS = ("groups", "height", "weight", "voice", "positions")
SHORTCUT_KEYS = frozenset({"search", "level_min", "level_max", "natures", "types", "talent_min", "gender", "egg_groups", "egg_mode",
    "pool", "pool_mode", "shiny", "colorful", "medal", "marks", "speciality", "acquisition", "captured_days",
    "height_min", "height_max", "weight_min", "weight_max", "voice_min", "voice_max",
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
            elif key in ("medal", "speciality", "acquisition", "captured_days"):
                valid = type(value) is int and value >= 0 and (key != "captured_days" or value in (0, 1, 3, 7))
            elif key in ("natures", "types", "egg_groups"):
                expected = int if key == "natures" else str
                valid = isinstance(value, list) and len(value) <= 50 and all(type(v) is expected and (v >= 0 if expected is int else 0 < len(v) <= 40) for v in value)
            elif key in ("search", "egg_mode"):
                valid = isinstance(value, str) and len(value) <= 100 and (key != "egg_mode" or value in ("any", "all"))
            elif key in ("level_min", "level_max", "talent_min", "gender"):
                valid = type(value) is int and 0 <= value <= 100 and (key != "gender" or value in (0, 1, 2))
            else:
                valid = value is None or (type(value) in (int, float) and math.isfinite(value) and abs(value) <= 1e9
                    and (key.startswith("voice") or value >= 0) and ("_position_" not in key or value <= 100))
            if not valid:
                raise ValueError("快捷条件值无效")
        result.append({"name": name.strip(), "filters": dict(filters)})
    return result


def normalize_preferences(raw: object) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    fields = raw.get("fields") if isinstance(raw.get("fields"), dict) else {}
    try:
        saved = raw.get("shortcuts", [])
        if isinstance(saved, list):
            saved = [{**item, "filters": {k: v for k, v in item["filters"].items() if k != "first_catch_only"}}
                     if isinstance(item, dict) and isinstance(item.get("filters"), dict) else item for item in saved]
        shortcuts = validate_shortcuts(saved)
    except ValueError:
        shortcuts = []
    return {"theme": raw.get("theme") if isinstance(raw.get("theme"), str) and raw.get("theme") in THEMES else "miaomiao",
            "pet_view": raw.get("pet_view") if isinstance(raw.get("pet_view"), str) and raw.get("pet_view") in VIEWS else "point",
            "pet_image": raw.get("pet_image") if isinstance(raw.get("pet_image"), str) and raw["pet_image"] in IMAGE_MODES else "portrait",
            "fields": {key: fields[key] if isinstance(fields.get(key), bool) else key != "positions" for key in FIELDS},
            "shortcuts": shortcuts}


class UIPreferencesViewModel:
    def __init__(self, settings: SettingsRepository) -> None:
        self._settings = settings

    def snapshot(self) -> dict:
        return normalize_preferences(self._settings.get_value("ui.preferences", {}))

    def update(self, changes: object) -> dict:
        if not isinstance(changes, dict) or set(changes) - {"theme", "pet_view", "pet_image", "fields", "shortcuts"}:
            raise ValueError("只允许界面偏好与快捷条件定义")
        if "theme" in changes and (not isinstance(changes["theme"], str) or changes["theme"] not in THEMES):
            raise ValueError("未知主题")
        if "pet_view" in changes and (not isinstance(changes["pet_view"], str) or changes["pet_view"] not in VIEWS):
            raise ValueError("未知背包视图")
        if "pet_image" in changes and (not isinstance(changes["pet_image"], str) or changes["pet_image"] not in IMAGE_MODES):
            raise ValueError("未知精灵图片模式")
        fields = changes.get("fields", {})
        if not isinstance(fields, dict) or set(fields) - set(FIELDS) or any(not isinstance(v, bool) for v in fields.values()):
            raise ValueError("显示字段必须是允许的布尔值")
        shortcuts = validate_shortcuts(changes["shortcuts"]) if "shortcuts" in changes else None
        def merge(previous):
            value = normalize_preferences(previous)
            value.update({key: changes[key] for key in ("theme", "pet_view", "pet_image") if key in changes})
            value["fields"].update(fields)
            if shortcuts is not None:
                value["shortcuts"] = shortcuts
            return value
        return self._settings.update_checked("ui.preferences", merge)
