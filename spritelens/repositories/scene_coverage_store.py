"""搜索覆盖记录：内存合并、后台原子落盘，采集线程不执行磁盘 IO。

记录按 (账号, 世界所有者, 地图) 归属，与覆盖层的分桶一致：0 表示自己的世界，
其他 uid 表示正在访问的他人世界（见 SceneCoverage 的 3 天保留规则）。
version=1 的旧文件没有 owner 字段，按自己的世界（0）读入。
"""
from __future__ import annotations

import json
import math
import threading
import time
from pathlib import Path

STORE_VERSION = 2


class SceneCoverageStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._condition = threading.Condition()
        self._records: dict[tuple[int, int, int], dict] = {}
        self._revision = 0
        self._written = 0
        self._closing = False
        self._closed = False
        self._error: str | None = None
        self._writer: threading.Thread | None = None
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or raw.get("version") not in (1, STORE_VERSION) or not isinstance(raw.get("records"), list):
                raise ValueError("搜索覆盖记录格式不兼容，原文件已保留")
            for row in raw["records"]:
                if not isinstance(row, dict) or type(row.get("uid")) is not int or row["uid"] <= 0 or type(row.get("map_id")) is not int or row["map_id"] <= 0:
                    raise ValueError("搜索覆盖记录归属无效，原文件已保留")
                owner = row.get("owner", 0)
                if type(owner) is not int or owner < 0:
                    raise ValueError("搜索覆盖记录归属无效，原文件已保留")
                if (row.get("coordinate_version") != 1 or type(row.get("cell_size")) is not int or row["cell_size"] <= 0
                        or type(row.get("radius")) is not int or row["radius"] < 0
                        or type(row.get("updated_at")) not in (int, float) or not math.isfinite(row["updated_at"])
                        or not isinstance(row.get("rows"), list)):
                    raise ValueError("搜索覆盖记录格式不兼容，原文件已保留")
                total = 0
                for run in row["rows"]:
                    if (not isinstance(run, list) or len(run) != 3 or any(type(n) is not int for n in run)
                            or run[2] <= 0):
                        raise ValueError("搜索覆盖格格式无效，原文件已保留")
                    total += run[2]
                    if total > 65536:
                        raise ValueError("搜索覆盖格数量超过上限，原文件已保留")
                key = (row["uid"], owner, row["map_id"])
                if key in self._records:
                    raise ValueError("搜索覆盖记录归属重复，原文件已保留")
                started = row.get("started_at", row["updated_at"])
                if type(started) not in (int, float) or not math.isfinite(started) or started < 0:
                    raise ValueError("搜索覆盖记录开始时间无效，原文件已保留")
                self._records[key] = {**row, "owner": owner, "started_at": started}

    def load(self, uid: int, map_id: int, owner: int = 0) -> dict | None:
        with self._condition:
            return self._records.get((uid, owner, map_id))

    def purge_expired(self, ttl_seconds: float, *, now: float | None = None) -> int:
        """删除到达保留期的他人世界记录；保留期从开始记录时间算，自己的世界不参与。"""
        deadline = (time.time() if now is None else now) - ttl_seconds
        with self._condition:
            expired = [key for key, row in self._records.items()
                       if key[1] != 0 and row.get("started_at", row.get("updated_at", 0)) < deadline]
            for key in expired:
                self._records.pop(key, None)
            if not expired:
                return 0
            self._revision += 1
            self._ensure_writer_locked()
            return len(expired)

    @property
    def error(self) -> str | None:
        with self._condition:
            return self._error

    def put(self, uid: int, map_id: int, value: dict | None, owner: int = 0) -> int:
        with self._condition:
            if self._closing or self._closed:
                raise RuntimeError("搜索覆盖存储已关闭")
            if value is None:
                self._records.pop((uid, owner, map_id), None)
            else:
                self._records[(uid, owner, map_id)] = {"uid": uid, "owner": owner, "map_id": map_id, **value}
            self._revision += 1
            revision = self._revision
            self._ensure_writer_locked()
            self._condition.notify_all()
            return revision

    def _ensure_writer_locked(self) -> None:
        if self._writer is None:
            self._writer = threading.Thread(target=self._run, name="spritelens-coverage", daemon=True)
            self._writer.start()

    def _run(self) -> None:
        while True:
            with self._condition:
                while self._written == self._revision and not self._closing:
                    self._condition.wait()
                if self._written == self._revision and self._closing:
                    return
                revision = self._revision
                rows = list(self._records.values())
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self._path.with_suffix(".tmp")
                temporary.write_text(json.dumps({"version": STORE_VERSION, "records": rows}, ensure_ascii=False), encoding="utf-8")
                temporary.replace(self._path)
            except (OSError, ValueError) as exc:
                with self._condition:
                    self._error = str(exc)
                    self._condition.notify_all()
                    self._condition.wait(timeout=0.5)
                continue
            with self._condition:
                self._written = revision
                self._error = None
                self._condition.notify_all()

    def flush(self, revision: int | None = None, *, timeout: float = 5) -> None:
        end = time.monotonic() + timeout
        with self._condition:
            target = self._revision if revision is None else revision
            while self._written < target:
                remaining = end - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"搜索覆盖记录未保存：{self._error or '写入超时'}")
                self._condition.wait(remaining)

    def close(self, *, timeout: float = 5) -> None:
        with self._condition:
            if self._closed:
                return
            self._closing = True
            self._condition.notify_all()
            writer = self._writer
        if writer is not None:
            writer.join(timeout)
            if writer.is_alive():
                raise TimeoutError(f"搜索覆盖记录未保存：{self._error or '写入超时'}")
        with self._condition:
            self._closed = True
