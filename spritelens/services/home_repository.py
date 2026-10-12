"""家园聚合：0x014A 快照覆盖 + 增量帧版本提示。

增量帧（0x0413/0x0414）本轮只做"数据已变化"的版本 bump（页面据此提示
快照可能过期），完整增量合并待真实增量样本采集后实现。

账号隔离：家园快照属于账号级数据，身份变更为另一账号时清空（防止切号
后仍显示上一账号的家园布局）。
"""

from __future__ import annotations

import threading

from spritelens.domain.home import HomeSnapshot, extract_home
from spritelens.domain.identity import extract_identity
from spritelens.logs import get_logger
from spritelens.services.account_tracker import AccountTracker
from spritelens.events import PacketEvent

logger = get_logger("home_repository")

OP_HOME_DELTA_A = 0x0413
OP_HOME_DELTA_B = 0x0414


class HomeRepository:
    """家园状态聚合器；monitor.add_packet_listener(self.handle_packet) 接入。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot: HomeSnapshot | None = None
        self._version = 0
        self._delta_count = 0  # 收到但未合并的增量帧数（>0 表示快照可能过期）
        self._account = AccountTracker()

    def handle_packet(self, event: PacketEvent) -> None:
        if event.direction != "s2c":
            return
        identity = extract_identity(event)
        if identity is not None:
            with self._lock:
                if self._account.observe(identity):
                    logger.info("账号切换 → 清空家园快照（uid %s）", identity.uid)
                    self._snapshot = None
                    self._delta_count = 0
                    self._version += 1
            return
        if event.opcode in (OP_HOME_DELTA_A, OP_HOME_DELTA_B):
            with self._lock:
                self._delta_count += 1
                self._version += 1
            return
        snapshot = extract_home(event)
        if snapshot is None:
            return
        with self._lock:
            self._snapshot = snapshot
            self._delta_count = 0
            self._version += 1
        logger.info(
            "家园快照更新：房间 %d 级，居民 %d，家具 %d（窝 %d）",
            snapshot.room_level,
            len(snapshot.residents),
            len(snapshot.furniture),
            len(snapshot.nests),
        )

    def snapshot(self) -> HomeSnapshot | None:
        with self._lock:
            return self._snapshot

    def pending_deltas(self) -> int:
        with self._lock:
            return self._delta_count

    def version(self) -> int:
        with self._lock:
            return self._version


__all__ = ["HomeRepository"]
