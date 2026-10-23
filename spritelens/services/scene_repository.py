"""附近实体的临时观察快照；单锁所有权，无持久化、无后台线程。"""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass

from spritelens.domain.identity import extract_identity
from spritelens.domain.scene import SceneActor, actor, children, integer, nodes, position, removed_ids
from spritelens.events import PacketEvent
from spritelens.services.account_tracker import AccountTracker

MAX_ACTORS = 4096


@dataclass(frozen=True)
class SceneSnapshot:
    uid: int
    version: int
    phase: str
    session_id: str | None
    scene_id: int | None
    resource_id: int | None
    instance_id: int | None
    player_position: tuple[int | None, int | None, int | None] | None
    updated_at: float | None
    position_source: str | None
    actors: tuple[SceneActor, ...]
    unresolved_updates: int
    rejected_actors: int


class SceneRepository:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._account = AccountTracker()
        self._version = 0
        self._retired_sessions: deque[str] = deque(maxlen=256)
        self._clear("awaiting_identity")

    def _clear(self, phase: str) -> None:
        self._phase = phase
        self._session: str | None = None
        self._scene: int | None = None
        self._resource: int | None = None
        self._instance: int | None = None
        self._position: tuple[int | None, int | None, int | None] | None = None
        self._position_source: str | None = None
        self._updated_at: float | None = None
        self._actors: dict[int, SceneActor] = {}
        self._unresolved = 0
        self._rejected = 0
        self._version += 1

    def reset(self, phase: str = "stopped", *, uid: int = 0) -> None:
        with self._lock:
            self._account = AccountTracker()
            if uid:
                self._account.select_loaded(uid)
            self._retired_sessions.clear()
            self._clear(phase)

    def session_closed(self, session_id: str) -> None:
        with self._lock:
            if session_id in self._retired_sessions:
                self._retired_sessions.remove(session_id)
            if session_id != self._session:
                return
            uid = self._account.display_uid
            self._account = AccountTracker()
            self._account.note_loaded(uid)
            self._clear("disconnected")

    def snapshot(self) -> SceneSnapshot:
        with self._lock:
            return SceneSnapshot(self._account.display_uid, self._version, self._phase, self._session,
                self._scene, self._resource, self._instance, self._position, self._updated_at, self._position_source,
                tuple(self._actors.values()), self._unresolved, self._rejected)

    def _add(self, node: dict, event: PacketEvent) -> None:
        value, invalid = actor(node, event)
        if invalid:
            self._rejected += 1
        if value is None:
            return
        if value.actor_id not in self._actors and len(self._actors) >= MAX_ACTORS:
            self._rejected += 1
            return
        self._actors[value.actor_id] = value

    def handle_packet(self, event: PacketEvent) -> None:
        identity = extract_identity(event) if event.direction == "s2c" else None
        with self._lock:
            if event.session_id in self._retired_sessions:
                return
            if identity is not None:
                switched = self._account.observe(identity)
                if switched or self._session != event.session_id:
                    previous = self._session
                    self._clear("awaiting_scene")
                    if previous and previous != event.session_id:
                        self._retired_sessions.append(previous)
                    self._session = event.session_id
            if self._account.identity is None or event.session_id != self._session:
                return
            fs = event.decoded
            if event.opcode == 0x0133 and event.direction == "c2s":
                # 客户端目标坐标不等同服务器确认位置，保留来源语义到 API。
                scene = integer(fs, 17)
                if self._phase != "battle_unverified" and self._scene is not None and scene == self._scene:
                    self._position = position(children(fs, 2))
                    self._position_source = "client_target" if self._position is not None else None
                    self._updated_at = event.ts
                    self._version += 1
                return
            if event.direction != "s2c":
                return
            if event.opcode == 0x0102:
                self._clear("awaiting_scene")
                self._session = event.session_id
            elif event.opcode in (0x0152, 0x015C):
                if event.opcode == 0x0152 and integer(children(fs, 1), 1) not in (None, 0):
                    return
                offset = 0 if event.opcode == 0x0152 else 9
                scene, resource = integer(fs, 2 + offset), integer(fs, 3 + offset)
                instance = integer(fs, 4 + offset)
                # 传送即使返回同一场景也开启新观察周期，实体 id 可能复用。
                if event.opcode == 0x015C or (scene, resource, instance) != (self._scene, self._resource, self._instance):
                    self._clear("observing")
                    self._session = event.session_id
                self._scene, self._resource, self._instance = scene, resource, instance
                if event.opcode == 0x015C:
                    self._position = position(children(children(fs, 14), 1))
                    self._position_source = "teleport" if self._position is not None else None
            elif event.opcode in (4886, 4908, 4909):
                self._actors.clear()
                self._position = None
                self._position_source = None
                self._phase = "battle_unverified" if event.opcode == 4886 else "awaiting_scene"
            elif self._phase == "battle_unverified":
                return
            elif event.opcode == 0x014A and self._scene is not None:
                if integer(children(fs, 1), 1) not in (None, 0):
                    return
                self._phase = "observing"
                for node in nodes(fs, 7):
                    self._add(node, event)
            elif event.opcode in (0x0413, 0x0414) and self._scene is not None:
                wrappers = nodes(fs, 1)
                if event.opcode == 0x0413:
                    wrappers = [action for wrapper in wrappers for action in nodes(children([wrapper], 1), 1)]
                if not wrappers:
                    self._unresolved += 1
                for wrapper in wrappers:
                    actions = children([wrapper], 1)
                    if not actions:
                        self._unresolved += 1
                    for action in actions:
                        raw_content = action.get("children")
                        if not isinstance(raw_content, list):
                            self._unresolved += 1
                            continue
                        content = raw_content
                        if action.get("no") == 1:
                            for node in nodes(content, 1):
                                self._add(node, event)
                        elif action.get("no") == 2:
                            ids, invalid = removed_ids(content)
                            self._unresolved += int(invalid)
                            for actor_id in ids:
                                self._actors.pop(actor_id, None)
                        else:
                            self._unresolved += 1
            else:
                return
            self._updated_at = event.ts
            self._version += 1
