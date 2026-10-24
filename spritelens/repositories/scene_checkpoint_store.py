"""附近精灵场景上下文的轻量持久化缓存，不保存实体与坐标。

这是可丢弃的派生缓存，不进入业务 SQLite；写入只由内存队列合并，后台线程
原子替换 JSON，避免抓包回调被磁盘 IO 阻塞。
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class SceneCheckpoint:
    uid: int
    flow_id: str
    scene_id: int | None
    resource_id: int | None
    instance_id: int | None
    updated_at: float | None


class SceneCheckpointStore:
    """按账号和抓包流保存最近一份附近观察基线。"""

    _VERSION = 2
    _MAX_RECORDS = 64

    def __init__(self, path: Path) -> None:
        self._path = path
        self._condition = threading.Condition()
        self._records: dict[tuple[int, str], SceneCheckpoint] = {}
        self._revision = 0
        self._written_revision = 0
        self._pending_revision: int | None = None
        self._writer: threading.Thread | None = None
        self._closing = False
        self._closed = False
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return
        if not isinstance(raw, dict) or raw.get("version") != self._VERSION:
            return
        rows = raw.get("checkpoints")
        if not isinstance(rows, list):
            return
        for row in rows[-self._MAX_RECORDS:]:
            try:
                checkpoint = self._parse(row)
            except (TypeError, ValueError, KeyError):
                continue
            self._records[(checkpoint.uid, checkpoint.flow_id)] = checkpoint

    @staticmethod
    def _optional_int(value: object) -> int | None:
        if value is None:
            return None
        if type(value) is not int:
            raise ValueError("场景基线整数格式错误")
        return value

    @classmethod
    def _parse(cls, value: object) -> SceneCheckpoint:
        if not isinstance(value, dict):
            raise ValueError("场景基线记录格式错误")
        uid, flow_id = value["uid"], value["flow_id"]
        if type(uid) is not int or uid <= 0 or not isinstance(flow_id, str) or not flow_id:
            raise ValueError("场景基线归属格式错误")
        updated_at = value.get("updated_at")
        if updated_at is not None and (not isinstance(updated_at, (int, float)) or isinstance(updated_at, bool)):
            raise ValueError("场景基线更新时间错误")
        return SceneCheckpoint(uid, flow_id, cls._optional_int(value.get("scene_id")),
                               cls._optional_int(value.get("resource_id")), cls._optional_int(value.get("instance_id")),
                               float(updated_at) if updated_at is not None else None)

    def load(self, uid: int, flow_id: str) -> SceneCheckpoint | None:
        with self._condition:
            return self._records.get((uid, flow_id))

    def save(self, checkpoint: SceneCheckpoint) -> None:
        with self._condition:
            self._ensure_open_locked()
            self._records[(checkpoint.uid, checkpoint.flow_id)] = checkpoint
            self._trim_locked()
            self._enqueue_locked()

    def clear(self, uid: int, flow_id: str) -> None:
        with self._condition:
            self._ensure_open_locked()
            if self._records.pop((uid, flow_id), None) is not None:
                self._enqueue_locked()

    def _trim_locked(self) -> None:
        while len(self._records) > self._MAX_RECORDS:
            del self._records[next(iter(self._records))]

    def _ensure_open_locked(self) -> None:
        if self._closing or self._closed:
            raise RuntimeError("SceneCheckpointStore 已进入关闭状态")

    def _enqueue_locked(self) -> None:
        self._revision += 1
        self._pending_revision = self._revision
        if self._writer is None:
            self._writer = threading.Thread(target=self._run_writer, name="spritelens-scene-checkpoint", daemon=True)
            self._writer.start()
        self._condition.notify_all()

    def _run_writer(self) -> None:
        while True:
            with self._condition:
                while self._pending_revision is None and not self._closing:
                    self._condition.wait()
                if self._pending_revision is None and self._closing:
                    return
                revision = self._pending_revision
                self._pending_revision = None
                records = tuple(self._records.values())
            try:
                payload = {"version": self._VERSION, "checkpoints": [asdict(item) for item in records]}
                self._path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self._path.with_suffix(f".{revision}.json.tmp")
                temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                temporary.replace(self._path)
            except OSError:
                with self._condition:
                    if self._pending_revision is None or self._pending_revision < revision:
                        self._pending_revision = revision
                    self._condition.wait(timeout=0.5)
                continue
            with self._condition:
                self._written_revision = max(self._written_revision, revision)
                self._condition.notify_all()

    def flush(self, *, timeout: float = 5) -> None:
        end = time.monotonic() + timeout
        with self._condition:
            revision = self._revision
            while self._written_revision < revision:
                remaining = end - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("附近场景基线未在等待期限内写入")
                self._condition.wait(timeout=remaining)

    def close(self, *, timeout: float = 5) -> None:
        with self._condition:
            if self._closed:
                return
            self._closing = True
            self._condition.notify_all()
            writer = self._writer
        if writer is not None:
            writer.join(timeout=timeout)
            if writer.is_alive():
                raise TimeoutError("附近场景基线 writer 未在关闭预算内完成")
        with self._condition:
            if self._written_revision < self._revision:
                raise OSError("附近场景基线仍有未写入记录")
            self._closed = True


__all__ = ["SceneCheckpoint", "SceneCheckpointStore"]
