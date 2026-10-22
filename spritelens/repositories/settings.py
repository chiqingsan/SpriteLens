"""JSON 配置仓库：网卡选择、端口等少量运行设置。

新项目设置项很少，JSON 文件比 meow toolkit 的 SQLite KV 更合适，
且允许用户手工编辑；文件读取失败必须暴露，不能以空配置覆盖已有草稿。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

DEFAULT_CAPTURE_PORT = 8195


def _clamp_int(value: Any, default: int, *, lo: int, hi: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, parsed))


class SettingsRepository:
    """线程安全的 JSON 配置读写；写入走临时文件 + 原子替换。"""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._cache: dict[str, Any] = {}
        self._loaded = False

    def _load(self) -> dict[str, Any]:
        if self._loaded:
            return self._cache
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            data = {}
        if not isinstance(data, dict):
            raise ValueError(f"配置文件必须是 JSON 对象：{self._path}")
        self._cache = data
        self._loaded = True
        return self._cache

    def _save_locked(self, pending: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(pending, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self._path)
        self._cache = pending

    def get_str(self, key: str, default: str = "") -> str:
        with self._lock:
            value = self._load().get(key, default)
        return value if isinstance(value, str) else default

    def get_value(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._load().get(key, default)

    def set_checked(self, key: str, value: Any) -> None:
        """界面显式保存必须把失败传回调用者；写入成功后才更新内存。"""
        self.update_checked(key, lambda previous: value)

    def update_checked(self, key: str, transform) -> Any:
        """持锁合并并保存，避免并发的部分偏好更新互相覆盖。"""
        with self._lock:
            value = transform(self._load().get(key))
            pending = {**self._cache, key: value}
            self._save_locked(pending)
            return value

    def get_bool(self, key: str, default: bool = False) -> bool:
        with self._lock:
            value = self._load().get(key, default)
        return value if isinstance(value, bool) else default

    def get_int(self, key: str, default: int, *, lo: int, hi: int) -> int:
        with self._lock:
            value = self._load().get(key, default)
        return _clamp_int(value, default, lo=lo, hi=hi)

    def window_geometry(self) -> dict | None:
        """上次窗口几何；旧记录未保存坐标时仍使用默认位置。"""
        width = self.get_int("window.width", 0, lo=0, hi=20000)
        height = self.get_int("window.height", 0, lo=0, hi=20000)
        if width <= 0 or height <= 0:
            return None
        x, y = self.get_value("window.x"), self.get_value("window.y")
        if type(x) is not int or type(y) is not int:
            x = y = None
        return {
            "width": width,
            "height": height,
            "maximized": self.get_bool("window.maximized"),
            "x": x, "y": y,
        }

    def set_window_geometry(self, *, width: int, height: int, maximized: bool,
                            x: int | None = None, y: int | None = None) -> None:
        with self._lock:
            pending = {**self._load(), "window.width": int(width), "window.height": int(height),
                       "window.maximized": bool(maximized)}
            if x is not None and y is not None:
                pending.update({"window.x": int(x), "window.y": int(y)})
            self._save_locked(pending)

    def set(self, key: str, value: Any) -> None:
        self.set_checked(key, value)
