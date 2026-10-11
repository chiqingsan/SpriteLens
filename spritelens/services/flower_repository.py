"""花种聚合：0x0375 快照覆盖 + 版本号。"""

from __future__ import annotations

import threading

from spritelens.domain.flowers import FlowerSnapshot, extract_flowers
from spritelens.logs import get_logger
from spritelens.services.monitor_service import PacketEvent

logger = get_logger("flower_repository")


class FlowerRepository:
    """花田状态聚合器；monitor.add_packet_listener(self.handle_packet) 接入。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot: FlowerSnapshot | None = None
        self._version = 0

    def handle_packet(self, event: PacketEvent) -> None:
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
