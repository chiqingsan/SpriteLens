"""蛋仓持久化网关：写回缓存 + 后台批量落盘 + 读取（与 PetStore 同型）。

为什么异步：put() 由 EggBoxRepository 在 MonitorService 锁内的抓包回调
里调用，同步 SQLite 提交会让磁盘变慢时拖住后续解码与 UI 事件拉取
（PetStore 文件头记录了同类实测：每条 flush 净增约 14ms、UI 轮询最长
57ms）。因此 put() 只并入内存待写表，落盘由独立 worker 线程批量执行。

语义：同一 (uid, instance_id) 的重复更新在待写表天然合并；写库异常整批
回滚回待写表（新值优先），下轮重试。读取前先 flush 待写表，保证
「写出去的数据立刻读得到」。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time

from spritelens.domain.egg_box import EggBoxEntry
from spritelens.logs import get_logger
from spritelens.repositories.database import Database

logger = get_logger("egg_store")

DEFAULT_FLUSH_INTERVAL = 0.5

_UPSERT_EGG = """
INSERT INTO eggs (uid, instance_id, egg_conf_id, pet_conf_id, quantity,
                  obtained_at, hatching, detail_json, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (uid, instance_id) DO UPDATE SET
    egg_conf_id = excluded.egg_conf_id,
    pet_conf_id = excluded.pet_conf_id,
    quantity    = excluded.quantity,
    obtained_at = excluded.obtained_at,
    hatching    = excluded.hatching,
    detail_json = excluded.detail_json,
    updated_at  = excluded.updated_at
"""


def _detail_json(egg: EggBoxEntry) -> str:
    return json.dumps(
        {
            "height_cm": egg.height_cm,
            "weight_g": egg.weight_g,
            "hatch_seconds": egg.hatch_seconds,
            "hatched_seconds": egg.hatched_seconds,
            "hatch_updated_at": egg.hatch_updated_at,
            "start_hatch_time": egg.start_hatch_time,
            "category": egg.category,
            "special_egg_conf_id": egg.special_egg_conf_id,
            "appearance_type": egg.appearance_type,
            "extension_type": egg.extension_type,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


class EggStore:
    """eggs 表的读写网关；写入方（抓包线程）永不等待磁盘。"""

    def __init__(self, database: Database, *, flush_interval: float = DEFAULT_FLUSH_INTERVAL) -> None:
        self._db = database
        self._flush_interval = max(0.05, float(flush_interval))
        self._lock = threading.Lock()
        # 批次串行化：保护「换出批次 → 写库/失败回填」整段顺序（与 PetStore
        # 同型，R02）；load 前的同步 flush 与 worker 的定时 flush 并发时，
        # 保证读到的批次顺序与取出顺序一致。
        self._flush_lock = threading.Lock()
        self._pending: dict[tuple[int, int], EggBoxEntry] = {}
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._closed = False
        self._written = 0

    # -- 写入（任意线程，无 IO）----------------------------------------
    def put(self, uid: int, eggs: list[EggBoxEntry]) -> int:
        """并入待写表（同 (uid, instance_id) 以最新为准）；返回受理条数。"""
        if uid <= 0 or not eggs:
            return 0
        accepted = [egg for egg in eggs if egg.instance_id > 0]
        if not accepted:
            return 0
        with self._lock:
            if self._closed:
                logger.warning("EggStore 已关闭，忽略 %d 枚蛋的写入", len(accepted))
                return 0
            for egg in accepted:
                self._pending[(uid, egg.instance_id)] = egg
            self._ensure_worker_locked()
        return len(accepted)

    # -- 落盘 ----------------------------------------------------------
    def flush(self) -> int:
        """把待写表批量写入 SQLite；返回本次写入的条数。

        待写表在锁内换出；整次提交由落盘锁串行化（与 PetStore 同型），
        并发 flush 按取得批次的先后顺序落库。
        """
        with self._lock:
            pending = self._pending
            self._pending = {}
        if not pending:
            return 0
        with self._flush_lock:
            return self._commit_batch(pending)

    def _commit_batch(self, pending: dict[tuple[int, int], EggBoxEntry]) -> int:
        now = time.time()
        rows = [
            (
                uid,
                egg.instance_id,
                egg.egg_conf_id,
                egg.pet_conf_id,
                egg.quantity,
                egg.obtained_at,
                1 if egg.hatching else 0,
                _detail_json(egg),
                now,
            )
            for (uid, _iid), egg in pending.items()
        ]
        try:
            self._db.execute_many(_UPSERT_EGG, rows)
        except sqlite3.Error as exc:
            logger.warning("蛋仓写库失败，留待下轮重试: %s", exc)
            with self._lock:
                for key, egg in pending.items():  # 新值优先：不覆盖期间已合并的新数据
                    self._pending.setdefault(key, egg)
            return 0
        with self._lock:
            self._written += len(rows)
        return len(rows)

    # -- 读取 ----------------------------------------------------------
    def load(self, uid: int) -> tuple[EggBoxEntry, ...]:
        """读取某账号全部蛋（按获取时间排序）；先落一次待写表保证一致。"""
        self.flush()
        try:
            rows = self._db.query(
                "SELECT instance_id, egg_conf_id, pet_conf_id, quantity, obtained_at,"
                " hatching, detail_json FROM eggs WHERE uid = ? ORDER BY obtained_at, instance_id",
                (uid,),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("蛋仓读取失败: %s", exc)
            return ()
        out: list[EggBoxEntry] = []
        for row in rows:
            try:
                detail = json.loads(row["detail_json"] or "{}")
            except json.JSONDecodeError:
                detail = {}
            out.append(
                EggBoxEntry(
                    instance_id=int(row["instance_id"]),
                    egg_conf_id=int(row["egg_conf_id"]),
                    pet_conf_id=int(row["pet_conf_id"]),
                    quantity=int(row["quantity"]),
                    obtained_at=int(row["obtained_at"]),
                    bag_type=8,
                    height_cm=int(detail.get("height_cm") or 0),
                    weight_g=int(detail.get("weight_g") or 0),
                    hatch_seconds=int(detail.get("hatch_seconds") or 0),
                    hatched_seconds=int(detail.get("hatched_seconds") or 0),
                    hatch_updated_at=int(detail.get("hatch_updated_at") or 0),
                    start_hatch_time=int(detail.get("start_hatch_time") or 0),
                    category=int(detail.get("category") or 0),
                    special_egg_conf_id=int(detail.get("special_egg_conf_id") or 0),
                    appearance_type=int(detail.get("appearance_type") or 0),
                    extension_type=int(detail.get("extension_type") or 0),
                )
            )
        return tuple(out)

    def load_latest(self) -> tuple[int, tuple[EggBoxEntry, ...]]:
        """最近活跃账号的蛋仓快照（离线展示用）。"""
        self.flush()
        try:
            rows = self._db.query(
                "SELECT uid, MAX(updated_at) AS recent FROM eggs GROUP BY uid ORDER BY recent DESC LIMIT 1"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("蛋仓账号查询失败: %s", exc)
            return 0, ()
        if not rows:
            return 0, ()
        uid = int(rows[0]["uid"])
        return uid, self.load(uid)

    # -- 生命周期 ------------------------------------------------------
    def close(self) -> None:
        """停止 worker 并做最后一次落盘（退出不丢数据）。"""
        with self._lock:
            self._closed = True
        self._stop.set()
        worker = self._worker
        if worker is not None:
            worker.join(timeout=5)
        self.flush()

    def _ensure_worker_locked(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=self._run, name="spritelens-egg-store", daemon=True)
        self._worker.start()

    def _run(self) -> None:
        while not self._stop.wait(self._flush_interval):
            self.flush()

    # -- 观测 ----------------------------------------------------------
    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    @property
    def written_count(self) -> int:
        with self._lock:
            return self._written


__all__ = ["DEFAULT_FLUSH_INTERVAL", "EggStore"]
