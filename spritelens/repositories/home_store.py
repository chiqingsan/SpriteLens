"""家园快照持久化：每个账号保留最近一次观察结果。"""

from __future__ import annotations

import json
import sqlite3
import threading
import time

from spritelens.domain.home import HomeCouple, HomeFurniture, HomeResident, HomeSceneEgg, HomeSnapshot
from spritelens.logs import get_logger
from spritelens.repositories.database import Database

logger = get_logger("home_store")
DEFAULT_FLUSH_INTERVAL = 0.5


def _encode(snapshot: HomeSnapshot) -> str:
    return json.dumps({
        "room_level": snapshot.room_level,
        "owner_uid": snapshot.owner_uid,
        "couples_stale": snapshot.couples_stale,
        "residents": [{
            "actor_id": row.actor_id, "name": row.name, "gender": row.gender,
            "level": row.level, "position": row.position, "instance_id": row.instance_id,
            "base_conf_id": row.base_conf_id, "conf_id": row.conf_id, "nest_guid": row.nest_guid,
        } for row in snapshot.residents],
        "nests": [{
            "config_id": row.config_id, "guid": row.guid, "kind": row.kind, "name": row.name,
            "position": row.position, "resident_ids": row.resident_ids,
            "position_known": row.position_known, "room_id": row.room_id,
            "room_name": row.room_name, "plane_id": row.plane_id,
        } for row in snapshot.nests],
        "couples": [{
            "female_actor_id": row.female_actor_id, "male_actor_ids": row.male_actor_ids,
        } for row in snapshot.couples],
        "scene_eggs": [{
            "actor_id": row.actor_id, "furniture_guid": row.furniture_guid,
            "npc_config_id": row.npc_config_id,
        } for row in snapshot.scene_eggs],
    }, ensure_ascii=False, separators=(",", ":"))


def _decode(raw: str) -> HomeSnapshot:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("snapshot must be an object")
    residents = tuple(HomeResident(
        actor_id=row["actor_id"], name=row["name"], gender=row["gender"], level=row["level"],
        position=tuple(row["position"]), instance_id=row["instance_id"],
        base_conf_id=row["base_conf_id"], conf_id=row["conf_id"], nest_guid=row["nest_guid"],
    ) for row in value["residents"])
    nests = tuple(HomeFurniture(
        config_id=row["config_id"], guid=row["guid"], kind=row["kind"], name=row["name"],
        position=tuple(row["position"]), resident_ids=tuple(row["resident_ids"]),
        position_known=row["position_known"], room_id=row["room_id"],
        room_name=row["room_name"], plane_id=row["plane_id"],
    ) for row in value["nests"])
    couples = tuple(HomeCouple(
        female_actor_id=row["female_actor_id"], male_actor_ids=tuple(row["male_actor_ids"]),
    ) for row in value["couples"])
    scene_eggs = tuple(HomeSceneEgg(
        actor_id=row["actor_id"], furniture_guid=row["furniture_guid"],
        npc_config_id=row["npc_config_id"],
    ) for row in value["scene_eggs"])
    return HomeSnapshot(
        room_level=value["room_level"], residents=residents, nests=nests, couples=couples,
        scene_eggs=scene_eggs, couples_stale=value["couples_stale"], owner_uid=value["owner_uid"],
    )


class HomeStore:
    """家园快照写回缓存 + 后台落盘，避免抓包回调等待 SQLite。"""

    def __init__(self, database: Database, *, flush_interval: float = DEFAULT_FLUSH_INTERVAL) -> None:
        self._db = database
        self._flush_interval = max(0.05, float(flush_interval))
        self._lock = threading.Lock()
        self._flush_lock = threading.Lock()
        self._pending: dict[int, HomeSnapshot] = {}
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._closed = False
        self._close_complete = False

    def put(self, uid: int, snapshot: HomeSnapshot) -> None:
        if uid <= 0:
            return
        with self._lock:
            if self._closed:
                logger.warning("HomeStore 已关闭，忽略 uid=%s 的家园快照", uid)
                return
            self._pending[uid] = snapshot
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._run, name="spritelens-home-store", daemon=True)
                self._worker.start()

    def load(self, uid: int) -> HomeSnapshot | None:
        if uid <= 0:
            return None
        # 读取历史账号时必须先把抓包线程已受理的最新快照写入数据库，
        # 否则 0.5 秒后台窗口会返回上一版甚至空记录。
        self.flush()
        rows = self._db.query("SELECT snapshot_json FROM home_snapshots WHERE uid = ?", (uid,))
        if not rows:
            return None
        try:
            snapshot = _decode(str(rows[0]["snapshot_json"]))
            if snapshot.owner_uid != uid:
                raise ValueError("snapshot owner does not match account")
            return snapshot
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            logger.warning("家园快照损坏，忽略历史记录：uid=%s (%s)", uid, exc)
            return None

    def _flush(self) -> None:
        with self._flush_lock:
            with self._lock:
                pending, self._pending = self._pending, {}
            if not pending:
                return
            now = time.time()
            try:
                self._db.execute_many(
                    "INSERT INTO home_snapshots (uid, snapshot_json, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(uid) DO UPDATE SET snapshot_json=excluded.snapshot_json, "
                    "updated_at=excluded.updated_at",
                    [(uid, _encode(snapshot), now) for uid, snapshot in pending.items()],
                )
            except sqlite3.Error:
                with self._lock:
                    for uid, snapshot in pending.items():
                        self._pending.setdefault(uid, snapshot)
                raise

    def flush(self) -> None:
        """同步写完调用前已排队的快照；写入失败向调用者传播。"""
        while True:
            self._flush()
            if not self._has_pending():
                return

    def _has_pending(self) -> bool:
        with self._lock:
            return bool(self._pending)

    def _run(self) -> None:
        while not self._stop.wait(self._flush_interval):
            try:
                self._flush()
            except sqlite3.Error as exc:
                logger.warning("家园快照写入失败，将重试：%s", exc)
        while self._has_pending():
            try:
                self._flush()
            except sqlite3.Error as exc:
                logger.warning("关闭时家园快照写入失败，将重试：%s", exc)
                time.sleep(self._flush_interval)

    def close(self) -> None:
        with self._lock:
            if self._close_complete:
                return
            self._closed = True
        self._stop.set()
        worker = self._worker
        if worker is not None:
            worker.join(timeout=5)
            if worker.is_alive():
                raise TimeoutError("HomeStore worker 未在 5 秒内退出")
        with self._lock:
            if self._pending:
                raise OSError(f"HomeStore 仍有 {len(self._pending)} 个账号快照待写")
            self._close_complete = True


__all__ = ["HomeStore"]
