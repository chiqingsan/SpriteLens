"""附近实体的临时观察快照；场景基线由独立缓存异步保存。"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, replace
from math import hypot

from spritelens.domain.identity import PlayerIdentity, extract_identity
from spritelens.domain.scene import SceneActor, actor, children, integer, nodes, position, removed_ids
from spritelens.events import PacketEvent
from spritelens.services.account_tracker import AccountTracker
from spritelens.services.scene_coverage import DEFAULT_CELL_SIZE_RAW, CoverageSnapshot, SceneCoverage
from spritelens.repositories.scene_checkpoint_store import SceneCheckpoint, SceneCheckpointStore
from spritelens.repositories.scene_coverage_store import SceneCoverageStore

MAX_ACTORS = 4096
# 删除阈值与雷达半径都用「原始坐标单位」；真实流量实测玩家↔实体距离
# p50≈7,990、p99≈8,994、max≈14,455，旧值 3,000 会删掉 85% 的实体。
DEFAULT_MAX_DISTANCE_RAW = 15000
RADAR_DELETE_DISTANCE = DEFAULT_MAX_DISTANCE_RAW  # 兼容旧引用；实例以构造参数为准
# 雷达显示半径（原始坐标单位），不代表服务器下发半径。
DEFAULT_RADAR_RADIUS_RAW = 10000
RESUMED_STALE = "resumed_stale"
# 连续移动采样的可信界限：客户端行走时约 10Hz 发 0x0133，to_pos 每个 tick
# 只前进约 100~200 原始单位（真实会话实测骑乘速度 p99≈1,723 原始单位/秒）。
# 间隔或位移超出该上限说明发生了传送、脱战回位或路线重算，此时只更新参考
# 位置，不把没走过的区域画成已探索。
MOVE_SAMPLE_MAX_GAP_MS = 2000
MOVE_SAMPLE_MAX_SPEED_RAW = 4000
MOVE_SAMPLE_TOLERANCE_RAW = 400


@dataclass(frozen=True)
class SceneSnapshot:
    uid: int
    version: int
    observation_id: int
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
    coverage: CoverageSnapshot | None = None
    coverage_paused: bool = False
    coverage_error: str | None = None


class SceneRepository:
    def __init__(
        self,
        *,
        checkpoint_store: SceneCheckpointStore | None = None,
        max_distance_raw: int = DEFAULT_MAX_DISTANCE_RAW,
        coverage_cell_raw: int = DEFAULT_CELL_SIZE_RAW,
        coverage_radius_raw: int = 0,
        coverage_enabled: bool = True,
        coverage_store: SceneCoverageStore | None = None,
        coverage_map_bounds: dict[int, tuple[int, int, int]] | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._account = AccountTracker()
        # 用户选择实测前暂停覆盖，雷达显示半径不作为覆盖依据。
        self._coverage_enabled = coverage_enabled
        self._coverage_store = coverage_store
        self._coverage = SceneCoverage(cell_size=coverage_cell_raw, radius_raw=coverage_radius_raw, enabled=coverage_enabled, store=coverage_store, map_bounds=coverage_map_bounds)
        self._checkpoint_store = checkpoint_store
        # 距离阈值只影响内存过筛，不是协议事实；由 config.json 调整，
        # 默认值来自真实流量回放（见模块常量注释）。
        self._max_distance_raw = max(1, int(max_distance_raw))
        self._version = 0
        self._observation_id = 0
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
        self._last_position_sample = 0
        self._last_move_sample = 0
        self._battle_id: int | None = None
        self._battle_backup: tuple[tuple[int | None, int | None, int | None] | None, tuple[SceneActor, ...]] | None = None
        self._updated_at: float | None = None
        self._actors: dict[int, SceneActor] = {}
        self._motions: dict[int, tuple[float, tuple[int, ...], tuple[tuple[int, int, int | None], ...]]] = {}
        self._unresolved = 0
        self._rejected = 0
        self._version += 1
        self._observation_id += 1

    def reset(self, phase: str = "stopped", *, uid: int = 0) -> None:
        with self._lock:
            if phase == "stopped":
                self._save_checkpoint_locked()
            self._account = AccountTracker()
            if uid:
                self._account.select_loaded(uid)
                self._coverage.select_account(uid)
            self._retired_sessions.clear()
            self._clear(phase)

    def restore_for(self, uid: int, flow_id: str) -> bool:
        """仅恢复监控层确认过的同一账号、同一抓包流基线。"""
        if self._checkpoint_store is None:
            return False
        with self._lock:
            return self._restore_for_locked(uid, flow_id)

    def _restore_for_locked(self, uid: int, flow_id: str) -> bool:
        if self._scene is not None or self._session is not None:
            return self._session == flow_id and self._phase == RESUMED_STALE
        checkpoint = self._checkpoint_store.load(uid, flow_id) if self._checkpoint_store else None
        if checkpoint is None:
            return False
        self._account = AccountTracker()
        self._account.note_loaded(uid)
        self._coverage.select_account(uid)
        self._phase = RESUMED_STALE
        self._session = checkpoint.flow_id
        self._scene = checkpoint.scene_id
        self._resource = checkpoint.resource_id
        self._instance = checkpoint.instance_id
        self._position = None
        self._position_source = None
        self._last_move_sample = 0
        self._updated_at = None
        self._actors = {}
        self._unresolved = 0
        self._rejected = 0
        self._version += 1
        self._observation_id += 1
        return True

    def _save_checkpoint_locked(self) -> None:
        if self._checkpoint_store is None or self._phase != "observing":
            return
        uid = self._account.display_uid
        if uid <= 0 or not self._session or self._scene is None:
            return
        self._checkpoint_store.save(SceneCheckpoint(
            uid, self._session, self._scene, self._resource, self._instance, self._updated_at,
        ))

    def _clear_checkpoint_locked(self, uid: int, session: str | None) -> None:
        if self._checkpoint_store is not None and uid > 0 and session:
            self._checkpoint_store.clear(uid, session)

    def session_closed(self, session_id: str) -> None:
        with self._lock:
            if session_id in self._retired_sessions:
                self._retired_sessions.remove(session_id)
            if session_id != self._session:
                return
            uid = self._account.display_uid
            self._clear_checkpoint_locked(uid, session_id)
            self._account = AccountTracker()
            self._account.note_loaded(uid)
            self._clear("disconnected")

    def advance(self, now: float | None = None) -> None:
        """把移动插值推进到 now（默认当前墙钟时间）。

        推进属于写路径：逐包处理时会顺带推进，推送循环每次取数前再推进
        一次即可。读接口（snapshot）不得再推进，否则同一时刻重复读取会
        得到不同位置与版本，前端被无变化的版本差异驱动重载。
        """
        with self._lock:
            self._advance_motion(time.time() if now is None else now)

    def reset_coverage(self, uid: int, resource_id: int, observation_id: int) -> bool:
        """清空当前地图的已探索足迹。

        只动覆盖格，不清实体、位置与观察周期；推进版本让在途的旧载荷
        因版本落后被前端丢弃，避免重置后又被晚到的响应画回旧足迹。
        """
        with self._lock:
            if (self._account.display_uid != uid or self._resource != resource_id
                    or self._observation_id != observation_id):
                return False
            self._coverage.clear(self._resource)
            self._version += 1
        if self._coverage_store is not None:
            self._coverage_store.flush()
        return True

    def snapshot(self) -> SceneSnapshot:
        """只读快照：不推进插值、不改版本，重复读取结果一致。"""
        with self._lock:
            return SceneSnapshot(self._account.display_uid, self._version, self._observation_id, self._phase, self._session,
                self._scene, self._resource, self._instance, self._position, self._updated_at, self._position_source,
                tuple(self._actors.values()), self._unresolved, self._rejected, self._coverage.snapshot(self._resource),
                not self._coverage_enabled, self._coverage.error or self._coverage.unavailable_reason(self._resource)
                or (self._coverage_store.error if self._coverage_store else None))

    def _add(self, node: dict, event: PacketEvent) -> None:
        value, invalid = actor(node, event)
        if invalid:
            self._rejected += 1
        if value is None:
            return
        self._motions.pop(value.actor_id, None)
        if self._has_confirmed_position() and self._is_beyond_radar_delete_distance(value):
            self._actors.pop(value.actor_id, None)
            return
        if value.actor_id not in self._actors and len(self._actors) >= MAX_ACTORS:
            self._rejected += 1
            return
        self._actors[value.actor_id] = value
        if self._phase in ("awaiting_scene", RESUMED_STALE):
            self._phase = "observing"

    def _is_beyond_radar_delete_distance(self, value: SceneActor) -> bool:
        if self._position is None or value.position is None:
            return False
        player_x, player_y = self._position[0], self._position[1]
        actor_x, actor_y = value.position[0], value.position[1]
        if player_x is None or player_y is None or actor_x is None or actor_y is None:
            return False
        return hypot(actor_x - player_x, actor_y - player_y) > self._max_distance_raw

    def _has_confirmed_position(self) -> bool:
        """客户端移动目标只用于展示参考，不能据此否定已观察到的实体。"""
        return self._position_source in ("teleport", "scene_entry")

    def _record_move_sample(self, target: tuple[int | None, int | None, int | None] | None,
                            request_time: int | None) -> None:
        """连续移动请求本身就是走过位置的证据。

        客户端在行走中以约 10Hz 发 0x0133，`to_pos` 贴着当前行走位置推进
        （每个 tick 约 100~200 原始单位）；传送、脱战回位和重新规划路线才会
        出现远超正常移动速度的跳变。只有与上一条移动请求在时间与位移上都
        相容时才记足迹，跳变只更新参考位置，保留未确认缺口。
        """
        previous = self._position
        elapsed = (request_time - self._last_move_sample) if (
            request_time is not None and self._last_move_sample > 0) else 0
        self._last_move_sample = request_time or 0
        if self._phase != "observing" or target is None or target[0] is None or target[1] is None:
            return
        if (previous is None or previous[0] is None or previous[1] is None
                or not 0 < elapsed <= MOVE_SAMPLE_MAX_GAP_MS):
            return
        distance = hypot(target[0] - previous[0], target[1] - previous[1])
        if distance <= MOVE_SAMPLE_MAX_SPEED_RAW * elapsed / 1000 + MOVE_SAMPLE_TOLERANCE_RAW:
            self._coverage.record(self._resource, target)

    def _prune_distant_actors(self) -> None:
        if not self._has_confirmed_position():
            return
        for actor_id, value in tuple(self._actors.items()):
            if self._is_beyond_radar_delete_distance(value):
                del self._actors[actor_id]
                self._motions.pop(actor_id, None)

    def _advance_motion(self, timestamp: float) -> None:
        changed = False
        for actor_id, (received, times, points) in tuple(self._motions.items()):
            elapsed = max(0, (timestamp - received) * 1000)
            target = points[-1]
            for index in range(1, len(points)):
                end = times[index] - times[0]
                if elapsed < end:
                    start = times[index - 1] - times[0]
                    ratio = max(0, (elapsed - start) / (end - start))
                    a, b = points[index - 1], points[index]
                    target = (round(a[0] + (b[0] - a[0]) * ratio), round(a[1] + (b[1] - a[1]) * ratio), a[2])
                    break
            value = self._actors.get(actor_id)
            if value is not None and value.position != target:
                self._actors[actor_id] = replace(value, position=target)
                changed = True
            if elapsed >= times[-1] - times[0]:
                del self._motions[actor_id]
        if changed:
            self._prune_distant_actors()
            self._version += 1

    def _move_actor(self, action: int, content: list[dict], event: PacketEvent) -> None:
        actor_id = integer(content, 1)
        value = self._actors.get(actor_id)
        if value is None:
            return
        self._motions.pop(actor_id, None)
        if action == 12:
            times = tuple(node.get("raw") for node in nodes(content, 3))
            points = tuple(position(node.get("children", [])) for node in nodes(content, 4))
            if (not times or len(times) != len(points) or any(not isinstance(t, int) for t in times)
                    or any(p is None or p[0] is None or p[1] is None for p in points)
                    or any(b <= a for a, b in zip(times, times[1:]))):
                self._unresolved += 1
                return
            target = points[0]
            self._motions[actor_id] = (event.ts, times, points)
        else:
            target = position(children(children(content, 3), 1)) if action == 13 else position(children(content, 2))
            if target is None or target[0] is None or target[1] is None:
                self._unresolved += 1
                return
        self._actors[actor_id] = replace(value, position=target, updated_at=event.ts, source_opcode=event.opcode)
        self._prune_distant_actors()

    def handle_packet(self, event: PacketEvent) -> None:
        identity = extract_identity(event) if event.direction == "s2c" else (
            PlayerIdentity(*event.resumed_identity) if event.resumed_identity is not None else None)
        with self._lock:
            if event.session_id in self._retired_sessions:
                return
            if event.resumed_identity is not None and identity is not None:
                self._restore_for_locked(identity.uid, event.session_id)
            if identity is not None:
                previous_uid = self._account.display_uid
                switched = self._account.observe(identity)
                self._coverage.select_account(identity.uid)
                if switched or self._session != event.session_id:
                    previous = self._session
                    if switched or (previous and previous != event.session_id):
                        self._clear_checkpoint_locked(previous_uid, previous)
                    self._clear("awaiting_scene")
                    if previous and previous != event.session_id:
                        self._retired_sessions.append(previous)
                    self._session = event.session_id
            if self._account.identity is None or event.session_id != self._session:
                return
            fs = event.decoded
            self._advance_motion(event.ts)
            if event.opcode == 0x0133 and event.direction == "c2s":
                # 客户端目标坐标不等同服务器确认位置，保留来源语义到 API。
                scene = integer(fs, 17)
                if self._phase != "battle_unverified" and scene is not None:
                    if self._scene is not None and scene != self._scene:
                        self._clear_checkpoint_locked(self._account.display_uid, self._session)
                        self._clear("awaiting_scene")
                        self._session = event.session_id
                    self._scene = scene
                    request_time = integer(fs, 1)
                    target = position(children(fs, 2))
                    # 连续移动请求本身是走过位置的证据；只有与上一条请求相容才记格。
                    self._record_move_sample(target, request_time)
                    self._position = target
                    self._position_source = "client_target" if target is not None else None
                    # 只接纳请求时刻以前的历史分段；计划目标仍只作参考。
                    for segment in nodes(fs, 12):
                        content = segment.get("children", [])
                        if not isinstance(content, list):
                            continue
                        sample_time = integer(content, 2)
                        sample = position(children(content, 1))
                        if (request_time is not None and sample_time is not None
                                and self._last_position_sample < sample_time <= request_time
                                and sample is not None and sample[0] is not None and sample[1] is not None):
                            self._last_position_sample = sample_time
                            self._position, self._position_source = sample, "client_sample"
                            if self._phase == "observing":
                                self._coverage.record(self._resource, sample)
                    if (integer(fs, 8) == 1 and request_time is not None
                            and request_time >= self._last_position_sample):
                        stopped = position(children(fs, 2))
                        if stopped is not None and stopped[0] is not None and stopped[1] is not None:
                            self._last_position_sample = request_time
                            self._position, self._position_source = stopped, "client_stop"
                            if self._phase == "observing":
                                self._coverage.record(self._resource, stopped)
                    self._prune_distant_actors()
                    self._updated_at = event.ts
                    self._version += 1
                return
            if event.direction != "s2c":
                return
            if event.opcode == 0x0102:
                self._clear_checkpoint_locked(self._account.display_uid, self._session)
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
                    self._clear_checkpoint_locked(self._account.display_uid, self._session)
                    self._clear("observing")
                    self._session = event.session_id
                self._scene, self._resource, self._instance = scene, resource, instance
                landing = None
                if event.opcode == 0x015C:
                    self._position = position(children(children(fs, 14), 1))
                    self._position_source = "teleport" if self._position is not None else None
                    landing = self._position
                else:
                    base = children(children(children(fs, 11), 12), 1)
                    entry_position = position(children(children(base, 8), 1))
                    if entry_position is not None:
                        self._position, self._position_source = entry_position, "scene_entry"
                        landing = entry_position
                # 只有本次事件自带落点才写足迹：0x0152 缺落点时位置保持旧值，
                # 用残留的客户端目标坐标会把未确认的位置当成已记录区域。
                if landing is not None:
                    self._coverage.record(self._resource, landing)
            elif event.opcode in (4886, 4908, 4909):
                if event.opcode == 4908 and self._battle_id is not None:
                    if integer(children(fs, 1), 19) != self._battle_id:
                        self._unresolved += 1
                        self._updated_at = event.ts
                        self._version += 1
                        return
                if event.opcode == 4886:
                    self._clear_checkpoint_locked(self._account.display_uid, self._session)
                    battle_id = integer(children(fs, 6), 1)
                    self._battle_backup = ((self._position, tuple(self._actors.values()))
                                           if self._phase == "observing" and self._scene is not None
                                           and battle_id is not None else None)
                backup = self._battle_backup if (event.opcode == 4908 and self._phase == "battle_unverified"
                                                  and self._battle_id is not None) else None
                self._last_position_sample = 0
                self._last_move_sample = 0
                self._actors.clear()
                self._motions.clear()
                self._observation_id += 1
                self._position = None
                self._position_source = None
                self._battle_id = integer(children(fs, 6), 1) if event.opcode == 4886 else None
                if event.opcode == 4886:
                    self._phase = "battle_unverified"
                else:
                    self._phase = "awaiting_scene"
                    self._battle_backup = None
                    if backup is not None:
                        self._position, actors = backup
                        self._position_source = "battle_return" if self._position is not None else None
                        self._actors = {value.actor_id: replace(value, stale=True) for value in actors}
                        self._phase = "observing"
            elif self._phase == "battle_unverified":
                # 战斗中场景离开消息仍可能移除战前实体（例如捕获目标）。只更新
                # 接续备份，不把战斗场景的新增或位置显示为野外观察。
                if event.opcode in (0x0413, 0x0414) and self._battle_backup is not None:
                    wrappers = nodes(fs, 1)
                    if event.opcode == 0x0413:
                        wrappers = [action for wrapper in wrappers for action in nodes(children([wrapper], 1), 1)]
                    removed: set[int] = set()
                    for wrapper in wrappers:
                        for action in children([wrapper], 1):
                            if action.get("no") == 2:
                                content = action.get("children")
                                if not isinstance(content, list):
                                    self._unresolved += 1
                                    continue
                                ids, invalid = removed_ids(content)
                                removed.update(ids)
                                self._unresolved += int(invalid)
                    if removed:
                        old_position, actors = self._battle_backup
                        self._battle_backup = (old_position, tuple(value for value in actors if value.actor_id not in removed))
                return
            elif event.opcode == 0x014A and self._scene is not None:
                if integer(children(fs, 1), 1) not in (None, 0):
                    return
                self._phase = "observing"
                self._actors = {key: value for key, value in self._actors.items() if not value.stale}
                for node in nodes(fs, 7):
                    self._add(node, event)
            elif event.opcode in (0x0413, 0x0414):
                wrappers = nodes(fs, 1)
                if event.opcode == 0x0413:
                    wrappers = [action for wrapper in wrappers for action in nodes(children([wrapper], 1), 1)]
                if self._phase == RESUMED_STALE:
                    self._phase = "observing"
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
                                self._motions.pop(actor_id, None)
                        elif action.get("no") in (12, 13, 222):
                            self._move_actor(action["no"], content, event)
                        else:
                            self._unresolved += 1
            else:
                return
            self._updated_at = event.ts
            self._version += 1
