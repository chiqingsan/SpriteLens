"""按连接路由业务事件；展示账号与正在采集的账号独立。"""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace

from spritelens.domain.identity import extract_identity
from spritelens.events import PacketEvent
from spritelens.logs import get_logger
from spritelens.repositories.pet_store import PetStore
from spritelens.repositories.egg_store import EggStore
from spritelens.repositories.home_store import HomeStore
from spritelens.services.pet_repository import PetRepository
from spritelens.services.egg_repository import EggBoxRepository
from spritelens.services.home_repository import HomeRepository
from spritelens.services.scene_repository import DEFAULT_MAX_DISTANCE_RAW, SceneRepository
from spritelens.repositories.scene_checkpoint_store import SceneCheckpointStore
from spritelens.repositories.scene_coverage_store import SceneCoverageStore

logger = get_logger("account_sessions")


@dataclass(frozen=True)
class AccountRepositories:
    pets: PetRepository
    eggs: EggBoxRepository
    home: HomeRepository
    scene: SceneRepository


class SelectedRepository:
    """保持 VM 的仓库引用稳定，每次调用才取得当前展示账号的仓库。"""

    def __init__(self, owner: AccountSessions, domain: str) -> None:
        self._owner = owner
        self._domain = domain

    def __getattr__(self, name: str) -> object:
        if name == "handle_packet":
            return self._owner.handle_packet
        if self._domain == "scene" and name == "reset":
            return self._owner.reset_scenes
        with self._owner.lock:
            value = getattr(getattr(self._owner.selected, self._domain), name)
        if not callable(value):
            return value

        def call(*args: object, **kwargs: object) -> object:
            with self._owner.lock:
                target = getattr(self._owner.selected, self._domain)
            # 仓库自己保护快照；历史读取的 IO 不得阻塞其他账号的事件路由。
            return getattr(target, name)(*args, **kwargs)

        return call


class AccountSessions:
    """唯一的会话归属与展示选择所有者；每个账号独占一组业务仓库。"""

    def __init__(
        self, initial: AccountRepositories, *, uid: int,
        pet_store: PetStore, egg_store: EggStore, home_store: HomeStore,
        scene_checkpoint_store: SceneCheckpointStore | None = None,
        scene_max_distance_raw: int = DEFAULT_MAX_DISTANCE_RAW,
        scene_coverage_radius_raw: int = 0,
        scene_coverage_enabled: bool = True,
        scene_coverage_store: SceneCoverageStore | None = None,
        scene_coverage_map_bounds: dict[int, tuple[int, int, int]] | None = None,
    ) -> None:
        self.lock = threading.RLock()
        self.selected = initial
        self._accounts = {uid: initial} if uid else {}
        self._sessions: dict[str, int] = {}
        self._identities: dict[str, tuple[int, str, int]] = {}
        self._pet_store = pet_store
        self._egg_store = egg_store
        self._home_store = home_store
        self._scene_checkpoint_store = scene_checkpoint_store
        self._scene_max_distance_raw = max(1, int(scene_max_distance_raw))
        self._scene_coverage_radius_raw = max(0, int(scene_coverage_radius_raw))
        self._scene_coverage_enabled = scene_coverage_enabled
        self._scene_coverage_store = scene_coverage_store
        self._scene_coverage_map_bounds = scene_coverage_map_bounds

    def view(self, domain: str) -> SelectedRepository:
        return SelectedRepository(self, domain)

    def new_account(self, uid: int = 0) -> AccountRepositories:
        return AccountRepositories(PetRepository(self._pet_store), EggBoxRepository(self._egg_store),
                                   HomeRepository(self._home_store), SceneRepository(
                                       checkpoint_store=self._scene_checkpoint_store,
                                       max_distance_raw=self._scene_max_distance_raw,
                                       coverage_radius_raw=self._scene_coverage_radius_raw,
                                       coverage_enabled=self._scene_coverage_enabled,
                                       coverage_store=self._scene_coverage_store,
                                       coverage_map_bounds=self._scene_coverage_map_bounds,
                                   ))

    def handle_packet(self, event: PacketEvent) -> None:
        identity = extract_identity(event)
        with self.lock:
            previous_live = set(self._sessions.values())
            if identity is not None:
                previous = self._sessions.get(event.session_id)
                if previous is not None and previous != identity.uid:
                    self._accounts[previous].eggs.clear_pickups(event.session_id)
                    self._accounts[previous].scene.session_closed(event.session_id)
                    self._accounts[previous].home.session_closed(event.session_id)
                self._sessions[event.session_id] = identity.uid
                self._identities[event.session_id] = (identity.uid, identity.name, identity.level)
            uid = self._sessions.get(event.session_id, 0)
            # 没有本连接的身份证据，禁止借用展示账号或其他连接的身份。
            if not uid or (event.account_uid and event.account_uid != uid):
                return
            repos = self._accounts.get(uid)
            if repos is None:
                repos = self._accounts[uid] = self.new_account(uid)
            # 采集重新开始会清场景；只在本连接已确认身份时恢复观察归属。
            scene_event = event if identity is not None else replace(
                event, resumed_identity=self._identities[event.session_id])
            natures = {}
            if event.direction == "c2s" and event.opcode == 0x0137:
                pets = repos.pets.consistent_snapshot()
                if pets.uid == uid:
                    natures = {pet.gid: pet.nature for pet in pets.pets}
            repos.eggs.observe_pickup(event, repos.home.consistent_snapshot(), natures)
            for repo, packet in ((repos.pets, event), (repos.eggs, event),
                                 (repos.home, event), (repos.scene, scene_event)):
                try:
                    repo.handle_packet(packet)
                except Exception:  # 业务回调故障不阻断同一事件的其他领域，保留可定位错误。
                    logger.exception("账号事件处理失败: domain=%s uid=%s opcode=0x%04X",
                                     type(repo).__name__, uid, event.opcode)
            if previous_live != set(self._sessions.values()):
                self._follow_single_live_account()

    def _follow_single_live_account(self) -> None:
        # 仅在在线账号集合变化时跟随；普通推送不能抢走用户手动选择的历史账号。
        live = set(self._sessions.values())
        if len(live) == 1:
            self.selected = self._accounts[next(iter(live))]

    def session_closed(self, session_id: str) -> None:
        with self.lock:
            previous_live = set(self._sessions.values())
            uid = self._sessions.pop(session_id, None)
            self._identities.pop(session_id, None)
            if uid is not None:
                self._accounts[uid].eggs.clear_pickups(session_id)
                self._accounts[uid].scene.session_closed(session_id)
                self._accounts[uid].home.session_closed(session_id)
                if previous_live != set(self._sessions.values()):
                    self._follow_single_live_account()

    def select_cached(self, uid: int) -> bool:
        with self.lock:
            repos = self._accounts.get(uid)
            if repos is None:
                return False
            self.selected = repos
            return True

    def select_prepared(self, uid: int, repos: AccountRepositories) -> None:
        with self.lock:
            # 读取历史期间可能已收到目标账号的实时事件，实时仓库优先。
            self.selected = self._accounts.setdefault(uid, repos)

    def live_uids(self) -> tuple[int, ...]:
        with self.lock:
            return tuple(sorted(set(self._sessions.values())))

    def reset_scenes(self, phase: str) -> None:
        with self.lock:
            accounts = list(self._accounts.values())
            if self.selected not in accounts:
                accounts.append(self.selected)
            for repos in accounts:
                repos.eggs.clear_pickups()
                uid = repos.pets.consistent_snapshot().uid
                repos.scene.reset(phase, uid=uid)
