"""JSON 配置仓库：网卡选择、端口等少量运行设置。

新项目设置项很少，JSON 文件比 meow toolkit 的 SQLite KV 更合适，
且允许用户手工编辑；脏值一律归一为默认（不抛错中断启动）。
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from spritelens.logs import get_logger

logger = get_logger("settings")

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
            if self._path.is_file():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._cache = data
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("配置读取失败，使用默认值: %s", exc)
        self._loaded = True
        return self._cache

    def _save_locked(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(self._cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            tmp.replace(self._path)
        except OSError as exc:
            logger.warning("配置写入失败: %s", exc)

    def get_str(self, key: str, default: str = "") -> str:
        with self._lock:
            value = self._load().get(key, default)
        return value if isinstance(value, str) else default

    def get_bool(self, key: str, default: bool = False) -> bool:
        with self._lock:
            value = self._load().get(key, default)
        return value if isinstance(value, bool) else default

    def get_int(self, key: str, default: int, *, lo: int, hi: int) -> int:
        with self._lock:
            value = self._load().get(key, default)
        return _clamp_int(value, default, lo=lo, hi=hi)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._load()
            self._cache[key] = value
            self._save_locked()
