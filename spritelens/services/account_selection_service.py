"""本地账号列表与独立展示选择；历史数据读取完成后再发布。"""

from __future__ import annotations

import threading
from contextlib import nullcontext
from collections.abc import Callable
from dataclasses import dataclass

from spritelens.domain.egg_box import EggBoxEntry
from spritelens.domain.home import HomeSnapshot
from spritelens.domain.pets import Pet
from spritelens.domain.pet_locations import Backpack
from spritelens.repositories.egg_store import EggStore
from spritelens.repositories.home_store import HomeStore
from spritelens.repositories.pet_store import PetStore
from spritelens.services.egg_repository import EggBoxRepository
from spritelens.services.home_repository import HomeRepository
from spritelens.services.pet_repository import PetRepository
from spritelens.services.scene_repository import SceneRepository
from spritelens.services.account_sessions import AccountSessions


class AccountSwitchBusy(Exception):
    """采集进行中，不能切换历史账号。"""


class AccountNotFound(Exception):
    """本地没有目标账号。"""


@dataclass(frozen=True)
class AccountSelection:
    """一次账号切换需要先读完的全部历史数据。"""

    profile: tuple[int, str, int, str]
    pets: tuple[Pet, ...]
    backpack: Backpack
    eggs: tuple[EggBoxEntry, ...]
    hatch_slots: set[int] | None
    home: HomeSnapshot | None


class AccountSelectionService:
    """组合根调用的账号切换服务，串行完成跨域读取与应用。"""

    def __init__(
        self,
        *,
        pet_store: PetStore,
        egg_store: EggStore,
        home_store: HomeStore,
        pet_repository: PetRepository,
        egg_box: EggBoxRepository,
        home_repo: HomeRepository,
        capture_running: Callable[[], bool],
        capture_command_scope: Callable[[], object] | None = None,
        scene_repository: SceneRepository | None = None,
        account_sessions: AccountSessions | None = None,
        remember_selected: Callable[[int], None] | None = None,
    ) -> None:
        self._account_sessions = account_sessions
        self._scene_repository = scene_repository
        self._pet_store = pet_store
        self._egg_store = egg_store
        self._home_store = home_store
        self._pet_repository = pet_repository
        self._egg_box = egg_box
        self._home_repo = home_repo
        self._capture_running = capture_running
        self._capture_command_scope = capture_command_scope or nullcontext
        self._remember_selected = remember_selected
        self._lock = threading.Lock()

    def accounts_payload(self) -> dict:
        """账号列表与当前展示/实时归属，供管理浮层使用。"""
        profiles = self._pet_repository.cached_account_profiles()
        snapshot = self._pet_repository.consistent_snapshot()
        current_uid = snapshot.uid
        live_identity = self._pet_repository.identity if self._account_sessions is None else snapshot.identity
        running = self._capture_running()
        can_switch = self._account_sessions is not None or not running
        return {
            "accounts": [
                {
                    "uid": uid,
                    "name": name,
                    "level": level,
                    "avatar_url": avatar_url,
                }
                for uid, name, level, avatar_url in profiles
            ],
            "selected_uid": current_uid,
            "live_uid": live_identity.uid if live_identity is not None else 0,
            "live_uids": list(self._account_sessions.live_uids()) if self._account_sessions else [],
            "can_switch": can_switch,
            "reason": "" if can_switch else "请先停止采集后再切换账号",
        }

    def select(self, uid: int) -> None:
        """先读完目标账号所有历史域，再替换内存快照。"""
        if uid <= 0:
            raise ValueError("账号 uid 必须是正整数")
        with self._lock:
            # 采集服务的命令锁覆盖整个「检查、读取、应用」窗口；否则
            # start/stop 可在读取期间插入，历史快照会与实时会话混合。
            with self._capture_command_scope():
                if self._account_sessions is not None and self._account_sessions.select_cached(uid):
                    if self._remember_selected is not None:
                        self._remember_selected(uid)
                    return
                if self._account_sessions is None and self._capture_running():
                    raise AccountSwitchBusy("请先停止采集后再切换账号")
                profile = next(
                    (item for item in self._pet_repository.cached_account_profiles() if item[0] == uid),
                    None,
                )
                if profile is None:
                    raise AccountNotFound("本地不存在该账号")

                # 所有读取都在应用内存前完成；任一 Store 抛错时，当前账号仍保持不变。
                staged = AccountSelection(
                    profile=profile,
                    pets=self._pet_store.load(uid),
                    backpack=self._pet_store.load_backpack(uid),
                    eggs=self._egg_store.load(uid),
                    hatch_slots=self._egg_store.load_hatch_slots(uid),
                    home=self._home_store.load(uid),
                )

                if self._account_sessions is not None:
                    repos = self._account_sessions.new_account()
                    repos.pets.select_historical_account(uid, staged.profile, staged.pets, staged.backpack)
                    repos.eggs.select_historical_account(uid, staged.eggs, staged.hatch_slots)
                    repos.home.select_historical_account(uid, staged.home)
                    repos.scene.reset("historical_account", uid=uid)
                    if self._remember_selected is not None:
                        self._remember_selected(uid)
                    self._account_sessions.select_prepared(uid, repos)
                    return

                self._pet_repository.select_historical_account(
                    uid, staged.profile, staged.pets, staged.backpack
                )
                self._egg_box.select_historical_account(uid, staged.eggs, staged.hatch_slots)
                self._home_repo.select_historical_account(uid, staged.home)
                if self._scene_repository is not None:
                    self._scene_repository.reset("historical_account", uid=uid)
                if self._remember_selected is not None:
                    self._remember_selected(uid)


__all__ = [
    "AccountNotFound",
    "AccountSelectionService",
    "AccountSwitchBusy",
]
