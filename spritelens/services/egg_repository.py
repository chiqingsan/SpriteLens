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
from spritelens.events import PacketEvent

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
        self._loaded_uid = 0  # 离线恢复的蛋仓归属（R05：载荷据此标记身份）

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
            # 槽位快照独立落库（R06）：蛋条目的时间字段不可靠，槽位帧是
            # 唯一在孵证据；空槽快照同样落库（明确「无槽中蛋」，清旧状态）
            if self._store is not None and uid > 0:
                self._store.put_hatch_slots(uid, slots)
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
        """按本地蛋仓最近活跃账号恢复（无组合根统一选号时的兼容入口）。"""
        if self._store is None:
            return 0
        uid, _eggs = self._store.load_latest()
        return self.load_account(uid) if uid > 0 else 0

    def load_account(self, uid: int) -> int:
        """恢复指定账号的蛋仓；返回恢复条数（R05）。

        账号选择权在组合根：宠物与蛋仓必须按同一展示 uid 恢复。该账号
        无蛋记录时保持空仓并登记归属（loaded_uid），不拿其他账号的蛋
        补齐——宁可显示「该账号暂无蛋仓缓存」，也不展示别人的蛋。
        """
        if self._store is None or uid <= 0:
            return 0
        eggs = self._store.load(uid)
        # 槽位快照一并恢复（R06）：标记为历史状态——恢复后的槽位来自
        # 上次会话的观察，不能推断当前仍在孵
        slots = self._store.load_hatch_slots(uid)
        with self._lock:
            self._eggs = {egg.instance_id: egg for egg in eggs}
            self._hatch_slots = slots
            self._loaded_uid = uid
            self._account.note_loaded(uid)
            self._version += 1
        return len(eggs)

    @property
    def loaded_uid(self) -> int:
        """当前蛋仓数据归属的账号 uid（实时会话跟随身份，离线为恢复账号）。"""
        with self._lock:
            if self._account.uid > 0:
                return self._account.uid
            return self._loaded_uid

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
