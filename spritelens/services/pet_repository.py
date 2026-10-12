"""宠物仓库状态：跨包聚合会话内收到的全部宠物（按 gid 去重合并）。

持久化接入点（可选）：传入 store 后，仓库同时扮演「内存快照 + 落盘出口」——
- 身份到达时标记当前 uid（identity.py 提取，先于宠物推送到达）；
- 身份变更为另一账号时清空内存快照（账号级隔离，防 A/B 数据混合）；
- 宠物分流入库（store.put 只并入待写表，不阻塞抓包线程）。

未注入 store 时保持纯内存语义（测试与回放可用），身份跟踪与切换清空
照常生效——跨账号数据混合与是否有本地库无关。
"""

from __future__ import annotations

import threading

from spritelens.domain.identity import PlayerIdentity, extract_identity
from spritelens.domain.pets import Pet, extract_pets
from spritelens.domain.pet_locations import Backpack, PetBox, PetLocation, update_backpack
from spritelens.repositories.pet_store import PetStore
from spritelens.services.account_tracker import AccountTracker
from spritelens.events import PacketEvent

MAX_PETS = 2000


class PetRepository:
    """线程安全的会话内宠物快照；挂在 MonitorService 的事件监听上。"""

    def __init__(self, store: PetStore | None = None) -> None:
        self._lock = threading.Lock()
        self._pets: dict[int, Pet] = {}
        self._locations: dict[int, PetLocation] = {}
        self._backpack = Backpack()
        self._colorful_names: dict[int, str] = {}
        self._version = 0
        self._store = store
        self._account = AccountTracker()
        self._cached_identity: PlayerIdentity | None = None

    def handle_packet(self, event: PacketEvent) -> None:
        """PacketEvent 监听回调：先认身份，再提取宠物并合并（新的覆盖旧的）。"""
        # 炫彩形态名字学习：花种帧按 colorful_conf_id（130xxx 系）引用宠物，
        # 图鉴静态表不含该体系，只能从宠物帧的 (field58, name) 对现场学习。
        # 该表是全局学习结果（与账号无关），账号切换时不清空。
        for pet in extract_pets(event):
            if pet.colorful_conf_id > 0 and pet.name:
                self._colorful_names.setdefault(pet.colorful_conf_id, pet.name)
        # 身份跟踪无条件进行（无 store 的回放场景同样要防跨账号混合）
        identity = extract_identity(event)
        if identity is not None:
            with self._lock:
                switched = self._account.observe(identity)
                self._cached_identity = identity
                if switched:
                    # 切换账号：旧账号快照整体作废，新账号数据随后分帧到达
                    self._pets.clear()
                    self._locations.clear()
                    self._backpack = Backpack()
                    self._version += 1
            if self._store is not None:
                self._store.put_account(identity.uid, identity.name, identity.level)

        with self._lock:
            backpack = update_backpack(event, self._backpack)
            if backpack is not None:
                self._backpack = backpack
                self._locations = backpack.locations()
                self._version += 1
            uid = self._account.uid
        if backpack is not None and self._store is not None and uid > 0:
            self._store.put_backpack(uid, backpack)
        pets = extract_pets(event, include_non_owned=True)
        if not pets:
            return
        with self._lock:
            for pet in pets:
                if pet.gid <= 0 or len(self._pets) >= MAX_PETS and pet.gid not in self._pets:
                    continue
                self._pets[pet.gid] = pet
            self._version += 1
            uid = self._account.uid
        if self._store is not None and uid > 0:
            self._store.put(uid, pets)

    def colorful_name(self, conf_id: int) -> str | None:
        """炫彩形态 id → 宠物名（协议学习表；未见过返回 None）。"""
        with self._lock:
            return self._colorful_names.get(conf_id)

    def snapshot(self) -> tuple[Pet, ...]:
        """当前全部宠物（按 gid 排序）；UI 按版本号判断是否需要重建表。"""
        with self._lock:
            return tuple(sorted((pet for pet in self._pets.values() if not pet.is_trial_pet and not pet.is_mirror_pet), key=lambda p: p.gid))

    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    @property
    def identity(self) -> PlayerIdentity | None:
        with self._lock:
            return self._account.identity

    @property
    def cached_identity(self) -> PlayerIdentity | None:
        with self._lock:
            return self._cached_identity

    def location(self, gid: int) -> PetLocation | None:
        with self._lock:
            return self._locations.get(gid)

    def backpack(self) -> Backpack:
        with self._lock:
            return Backpack(dict(self._backpack.boxes), self._backpack.teams, self._backpack.active_team)

    def load_persisted(self, uid: int) -> int:
        """载入历史宠物（只补缺失的 gid，不覆盖本次会话已收到的新数据）。

        同时用历史宠物的 (colorful_conf_id, name) 重建炫彩名字学习表——
        花种帧按该 id 引用宠物，重启后若只恢复字段不恢复映射，花田载荷
        会退化成「#130001」。返回补入的条数；uid 无效或无 store 时不做任何事。
        """
        if self._store is None or uid <= 0:
            return 0
        with self._lock:
            existing = set(self._pets)
        loaded = self._store.load(uid)
        backpack = self._store.load_backpack(uid)
        account = self._store.load_account(uid)
        if not loaded and not backpack.boxes and not backpack.teams and not account:
            return 0
        added = 0
        with self._lock:
            # 记住离线数据的归属：该账号登录时不算「切换」，不清快照
            self._account.note_loaded(uid)
            if self._account.identity is None and account:
                self._cached_identity = PlayerIdentity(*account)
            current = self._backpack
            current_gids = set(current.locations()) | {gid for team in current.teams for gid in team.slots if gid}
            boxes = {box_id: PetBox(box_id, tuple(0 if gid in current_gids else gid for gid in box.slots), box.name, box.historical)
                     for box_id, box in backpack.boxes.items()}
            boxes.update(current.boxes)
            teams = current.teams or tuple(PetBox(team.box_id, tuple(0 if gid in current_gids else gid for gid in team.slots), team.name, team.historical)
                                           for team in backpack.teams)
            team_gids = {gid for team in teams for gid in team.slots if gid}
            boxes = {box_id: PetBox(box_id, tuple(0 if gid in team_gids else gid for gid in box.slots), box.name, box.historical)
                     for box_id, box in boxes.items()}
            self._backpack = Backpack(boxes, teams, current.active_team or backpack.active_team)
            self._locations = self._backpack.locations()
            for pet in loaded:
                if not pet.is_trial_pet and not pet.is_mirror_pet and pet.colorful_conf_id > 0 and pet.name:
                    self._colorful_names.setdefault(pet.colorful_conf_id, pet.name)
                if pet.gid in existing:
                    continue
                self._pets[pet.gid] = pet
                added += int(not pet.is_trial_pet and not pet.is_mirror_pet)
            if added or backpack.boxes or backpack.teams:
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
            self._locations.clear()
            self._backpack = Backpack()
            self._version += 1


__all__ = ["MAX_PETS", "PetRepository"]
