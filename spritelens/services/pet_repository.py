"""宠物仓库状态：跨包聚合会话内收到的全部宠物（按 gid 去重合并）。

持久化接入点（可选）：传入 store 后，仓库同时扮演「内存快照 + 落盘出口」——
- 身份到达时标记当前 uid（identity.py 提取，先于宠物推送到达）；
- 宠物分流入库（store.put 只并入待写表，不阻塞抓包线程）。

保持原内存语义不变：未注入 store 时行为与从前完全一致（测试与回放可用）。
"""

from __future__ import annotations

import threading

from spritelens.domain.identity import PlayerIdentity, extract_identity
from spritelens.domain.pets import Pet, extract_pets
from spritelens.repositories.pet_store import PetStore
from spritelens.services.monitor_service import PacketEvent

MAX_PETS = 2000


class PetRepository:
    """线程安全的会话内宠物快照；挂在 MonitorService 的事件监听上。"""

    def __init__(self, store: PetStore | None = None) -> None:
        self._lock = threading.Lock()
        self._pets: dict[int, Pet] = {}
        self._colorful_names: dict[int, str] = {}
        self._version = 0
        self._store = store
        self._identity: PlayerIdentity | None = None

    def handle_packet(self, event: PacketEvent) -> None:
        """PacketEvent 监听回调：先认身份，再提取宠物并合并（新的覆盖旧的）。"""
        # 炫彩形态名字学习：花种帧按 colorful_conf_id（130xxx 系）引用宠物，
        # 图鉴静态表不含该体系，只能从宠物帧的 (field58, name) 对现场学习
        for pet in extract_pets(event):
            if pet.colorful_conf_id > 0 and pet.name:
                self._colorful_names.setdefault(pet.colorful_conf_id, pet.name)
        if self._store is not None:
            identity = extract_identity(event)
            if identity is not None:
                with self._lock:
                    self._identity = identity
                self._store.put_account(identity.uid, identity.name, identity.level)

        pets = extract_pets(event)
        if not pets:
            return
        with self._lock:
            for pet in pets:
                if pet.gid <= 0 or len(self._pets) >= MAX_PETS and pet.gid not in self._pets:
                    continue
                self._pets[pet.gid] = pet
            self._version += 1
            uid = self._identity.uid if self._identity is not None else 0
        if self._store is not None and uid > 0:
            self._store.put(uid, pets)

    def colorful_name(self, conf_id: int) -> str | None:
        """炫彩形态 id → 宠物名（协议学习表；未见过返回 None）。"""
        with self._lock:
            return self._colorful_names.get(conf_id)

    def snapshot(self) -> tuple[Pet, ...]:
        """当前全部宠物（按 gid 排序）；UI 按版本号判断是否需要重建表。"""
        with self._lock:
            return tuple(sorted(self._pets.values(), key=lambda p: p.gid))

    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    @property
    def identity(self) -> PlayerIdentity | None:
        with self._lock:
            return self._identity

    def load_persisted(self, uid: int) -> int:
        """载入历史宠物（只补缺失的 gid，不覆盖本次会话已收到的新数据）。

        返回补入的条数；uid 无效或无 store 时不做任何事。
        """
        if self._store is None or uid <= 0:
            return 0
        with self._lock:
            existing = set(self._pets)
        loaded = self._store.load(uid)
        added = 0
        with self._lock:
            for pet in loaded:
                if pet.gid in existing:
                    continue
                self._pets[pet.gid] = pet
                added += 1
            if added:
                self._version += 1
        return added

    def cached_accounts(self) -> tuple[tuple[int, str], ...]:
        """本地库里有历史记录的账号（uid, 名字），按最近活跃排序。

        离线启动时据此加载上次账号的数据；无 store 时返回空元组。
        """
        if self._store is None:
            return ()
        return self._store.list_accounts()

    def load_last_account(self) -> int:
        """载入最近账号的历史宠物；返回补入条数。"""
        accounts = self.cached_accounts()
        return self.load_persisted(accounts[0][0]) if accounts else 0

    def clear(self) -> None:
        with self._lock:
            self._pets.clear()
            self._version += 1


__all__ = ["MAX_PETS", "PetRepository"]
