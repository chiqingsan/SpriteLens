"""家园聚合：0x014A 完整快照与 0x0413/0x0414 已识别增量合并。

能解析的增量更新居民和场景蛋；无法识别的增量累计为待更新数，页面据此
提示快照可能过期。增量使配对数据失效，但不会把已合并的居民标成过期。

账号隔离：家园快照属于账号级数据，身份变更为另一账号时清空（防止切号
后仍显示上一账号的家园布局）。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from spritelens.domain.home import HomeSnapshot, apply_home_delta, extract_home
from spritelens.domain.identity import extract_identity
from spritelens.logs import get_logger
from spritelens.services.account_tracker import AccountTracker
from spritelens.events import PacketEvent

logger = get_logger("home_repository")

OP_HOME_DELTA_A = 0x0413
OP_HOME_DELTA_B = 0x0414
OP_SCENE_ENTER = 0x0152
OP_SCENE_CHANGE = 0x015C
HOME_SCENE_RESOURCE = 30001


@dataclass(frozen=True)
class HomeRepoSnapshot:
    data: HomeSnapshot | None
    uid: int
    version: int
    pending_deltas: int
    source: str = "unknown"


class HomeRepository:
    """家园状态聚合器；monitor.add_packet_listener(self.handle_packet) 接入。"""

    def __init__(self, store=None) -> None:  # store: repositories.home_store.HomeStore | None
        self._store = store
        self._lock = threading.Lock()
        self._snapshot: HomeSnapshot | None = None
        self._version = 0
        self._delta_count = 0  # 收到但未合并的增量帧数（>0 表示快照可能过期）
        self._account = AccountTracker()
        self._active_session: str | None = None
        self._active_scene_resource: int | None = None
        self._active_home_observed = False

    @staticmethod
    def _field_int(event: PacketEvent, no: int) -> int | None:
        for field in event.decoded or []:
            if field.get("no") == no:
                raw = field.get("raw")
                return raw if isinstance(raw, int) else None
        return None

    def handle_packet(self, event: PacketEvent) -> None:
        if event.direction != "s2c":
            return
        identity = extract_identity(event)
        if identity is not None:
            with self._lock:
                account_changed = self._account.observe(identity)
                if account_changed:
                    logger.info("账号切换 → 清空家园快照（uid %s）", identity.uid)
                    self._snapshot = None
                    self._delta_count = 0
                    self._active_session = None
                    self._active_scene_resource = None
                    self._active_home_observed = False
                    self._version += 1
                if self._active_session != event.session_id:
                    self._active_session = event.session_id
                    self._active_scene_resource = None
                    self._active_home_observed = False
                    self._delta_count = 0
                    self._version += 1
        with self._lock:
            if event.session_id != self._active_session:
                return
            if event.opcode == OP_SCENE_ENTER:
                resource = self._field_int(event, 3)
                if resource is not None:
                    self._active_scene_resource = resource
                    self._active_home_observed = False
                    self._delta_count = 0
                    self._version += 1
                return
            if event.opcode == OP_SCENE_CHANGE:
                resource = self._field_int(event, 12)
                if resource is not None:
                    self._active_scene_resource = resource
                    self._active_home_observed = False
                    self._delta_count = 0
                    self._version += 1
                return
        if event.opcode in (OP_HOME_DELTA_A, OP_HOME_DELTA_B):
            changed_snapshot = None
            changed_uid = 0
            with self._lock:
                if (event.session_id != self._active_session
                        or self._active_scene_resource != HOME_SCENE_RESOURCE
                        or not self._active_home_observed
                        or self._snapshot is None
                        or self._snapshot.owner_uid != self._account.uid):
                    return
                result = apply_home_delta(event, self._snapshot)
                if result is None:
                    self._delta_count += 1
                    self._version += 1
                    return
                changed = result.snapshot != self._snapshot
                if changed:
                    self._snapshot = result.snapshot
                    changed_snapshot = result.snapshot
                    changed_uid = result.snapshot.owner_uid
                if result.unresolved:
                    self._delta_count += 1
                if changed or result.unresolved:
                    self._version += 1
            if changed_snapshot is not None and self._store is not None:
                self._store.put(changed_uid, changed_snapshot)
            return
        snapshot = extract_home(event)
        if (snapshot is None or snapshot.owner_uid <= 0):
            return
        with self._lock:
            if (event.session_id != self._active_session
                    or self._active_scene_resource != HOME_SCENE_RESOURCE
                    or snapshot.owner_uid != self._account.uid):
                return
            self._snapshot = snapshot
            self._active_home_observed = True
            self._delta_count = 0
            self._version += 1
        if self._store is not None:
            self._store.put(snapshot.owner_uid, snapshot)
        logger.info(
            "家园快照更新：房间 %d 级，居民 %d，小窝 %d",
            snapshot.room_level,
            len(snapshot.residents),
            len(snapshot.nests),
        )

    def snapshot(self) -> HomeSnapshot | None:
        with self._lock:
            return self._snapshot

    def session_closed(self, session_id: str) -> None:
        """断线或新握手后保留历史快照，但禁止继续接收旧家园增量。"""
        with self._lock:
            if self._active_session == session_id:
                self._active_session = None
                self._active_scene_resource = None
                self._active_home_observed = False
                self._delta_count = 0
                self._version += 1

    def load_account(self, uid: int) -> bool:
        """恢复指定账号最近一次家园观察；恢复结果始终标为 history。"""
        if self._store is None or uid <= 0:
            return False
        with self._lock:
            if self._account.uid and self._account.uid != uid:
                raise ValueError("不能将历史家园加载到另一实时账号")
            version = self._version
        snapshot = self._store.load(uid)
        with self._lock:
            if self._version != version or self._account.uid and self._account.uid != uid:
                raise RuntimeError("恢复期间账号或家园状态已变化，历史数据未应用")
            self._snapshot = snapshot
            self._active_session = None
            self._active_scene_resource = None
            self._active_home_observed = False
            self._delta_count = 0
            self._account.note_loaded(uid)
            self._version += 1
        return snapshot is not None

    def select_historical_account(self, uid: int, snapshot: HomeSnapshot | None) -> None:
        """应用已读取完成的历史家园快照；无快照时明确进入未知状态。"""
        if uid <= 0:
            raise ValueError("账号 uid 无效")
        with self._lock:
            self._account.select_loaded(uid)
            self._snapshot = snapshot
            self._active_session = None
            self._active_scene_resource = None
            self._active_home_observed = False
            self._delta_count = 0
            self._version += 1

    def pending_deltas(self) -> int:
        with self._lock:
            return self._delta_count

    def consistent_snapshot(self) -> HomeRepoSnapshot:
        with self._lock:
            observed = (
                self._snapshot is not None
                and self._account.uid > 0
                and self._snapshot.owner_uid == self._account.uid
                and self._active_session is not None
                and self._active_scene_resource == HOME_SCENE_RESOURCE
                and self._active_home_observed
            )
            source = ("stale" if self._delta_count else "observed") if observed else "history" if self._snapshot else "unknown"
            return HomeRepoSnapshot(
                self._snapshot, self._account.display_uid, self._version, self._delta_count, source
            )

    def version(self) -> int:
        with self._lock:
            return self._version


__all__ = ["HomeRepository"]
