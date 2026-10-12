"""花种聚合：0x0375 快照覆盖 + 版本号。

账号隔离：花田（自己的花 + 好友花田）属于账号级数据，身份变更为另一
账号时清空，防止切号后仍显示上一账号的花田。
"""

from __future__ import annotations

import threading

from spritelens.domain.flowers import FlowerSnapshot, extract_flowers
from spritelens.domain.identity import extract_identity
from spritelens.logs import get_logger
from spritelens.services.account_tracker import AccountTracker
from spritelens.events import PacketEvent

logger = get_logger("flower_repository")


class FlowerRepository:
    """花田状态聚合器；monitor.add_packet_listener(self.handle_packet) 接入。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot: FlowerSnapshot | None = None
        self._version = 0
        self._account = AccountTracker()

    def handle_packet(self, event: PacketEvent) -> None:
        identity = extract_identity(event)
        if identity is not None:
            with self._lock:
                if self._account.observe(identity):
                    logger.info("账号切换 → 清空花田快照（uid %s）", identity.uid)
                    self._snapshot = None
                    self._version += 1
            return
        snapshot = extract_flowers(event)
        if snapshot is None:
            return
        with self._lock:
            self._snapshot = snapshot
            self._version += 1
        logger.info(
            "花田快照更新：自己的花 %d 朵，好友花田 %d 条",
            len(snapshot.own),
            len(snapshot.friends),
        )

    def snapshot(self) -> FlowerSnapshot | None:
        with self._lock:
            return self._snapshot

    def version(self) -> int:
        with self._lock:
            return self._version


__all__ = ["FlowerRepository"]
