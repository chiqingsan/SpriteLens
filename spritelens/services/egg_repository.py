"""蛋仓聚合： PacketEvent → 蛋快照（uid 归属 + 去重合并 + 版本号 + 入库出口）。

与 PetRepository 同型：内存快照供 UI 即时读，可选 store 做写透持久化
（蛋仓每次登录由服务器全量重推，内存快照天然自愈；持久化让"重启不丢"
离线可看）。蛋条目按 instance_id 去重，新的覆盖旧的。

账号隔离：身份变更为另一账号时，内存蛋仓与孵化槽一并清空（复现过的
串扰：B 登录后仍看到 A 的蛋，且孵化槽帧把 A 的蛋写进 B 的库记录）。
"""

from __future__ import annotations

import threading

from spritelens.domain.egg_box import EggBoxEntry, extract_eggs, extract_hatch_slots
from spritelens.domain.identity import extract_identity
from spritelens.logs import get_logger
from spritelens.services.account_tracker import AccountTracker
from spritelens.services.monitor_service import PacketEvent

logger = get_logger("egg_repository")

MAX_EGGS = 5000  # 安全上限（蛋仓实测几百枚量级）


class EggBoxRepository:
    """蛋仓聚合器；monitor.add_packet_listener(self.handle_packet) 接入管线。"""

    def __init__(self, store=None) -> None:  # store: repositories.egg_store.EggStore | None
        self._store = store
        self._lock = threading.Lock()
        self._eggs: dict[int, EggBoxEntry] = {}
        self._hatch_slots: set[int] = set()  # 0x0312 槽中蛋 id
        self._account = AccountTracker()
        self._version = 0

    def handle_packet(self, event: PacketEvent) -> None:
        # 身份跟踪无条件进行：账号切换要把内存蛋仓/孵化槽一起作废，
        # 即便没有 store（回放场景）也不允许跨账号混合
        identity = extract_identity(event)
        if identity is not None:
            with self._lock:
                switched = self._account.observe(identity)
                if switched:
                    logger.info("账号切换 → 清空蛋仓快照（uid %s）", identity.uid)
                    self._eggs.clear()
                    self._hatch_slots.clear()
                    self._version += 1

        slots = extract_hatch_slots(event)
        if slots is not None:
            with self._lock:
                self._hatch_slots = set(slots)
                self._version += 1
                uid = self._account.uid
                eggs = list(self._eggs.values())
            # 落库标记在孵状态（快照里已有这些蛋时）
            if self._store is not None and uid > 0 and eggs:
                self._store.put(uid, eggs)
            return
        eggs = extract_eggs(event)
        if not eggs:
            return
        with self._lock:
            for egg in eggs:
                if egg.instance_id <= 0 or len(self._eggs) >= MAX_EGGS and egg.instance_id not in self._eggs:
                    continue
                self._eggs[egg.instance_id] = egg
            self._version += 1
            uid = self._account.uid
        if self._store is not None and uid > 0:
            self._store.put(uid, eggs)

    def load_last_account(self) -> int:
        """启动时从本地库恢复最近账号的蛋仓；返回恢复条数。"""
        if self._store is None:
            return 0
        uid, eggs = self._store.load_latest()
        if not eggs:
            return 0
        with self._lock:
            self._eggs = {egg.instance_id: egg for egg in eggs}
            self._account.note_loaded(uid)
            self._version += 1
        return len(eggs)

    def snapshot(self) -> tuple[EggBoxEntry, ...]:
        with self._lock:
            return tuple(sorted(self._eggs.values(), key=lambda e: (e.obtained_at, e.instance_id)))

    def version(self) -> int:
        with self._lock:
            return self._version

    def hatch_slots(self) -> set[int]:
        with self._lock:
            return set(self._hatch_slots)

    def clear(self) -> None:
        with self._lock:
            self._eggs.clear()
            self._hatch_slots.clear()
            self._version += 1


__all__ = ["EggBoxRepository", "MAX_EGGS"]
