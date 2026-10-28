"""历史事件日志回放：从收蛋请求与入仓奖励重建蛋仓来源（补录用）。

EggPickupTracker 只在实时抓包时记关联；功能上线前收取的蛋在蛋仓里没有
来源。这里按时间顺序重放 eventlog 分片，复用在线路径的
HomeRepository / PetRepository / EggPickupTracker 还原「收蛋请求 → 奖励
帧 → 蛋实例」的关联，供 tools/backfill_egg_origins.py 补写。

边界：只读日志、不写库，也不推断在线路径记不下来的东西——日志里没有
收蛋请求的蛋（例如请求帧没被采集到）仍然关联不了。

为什么流式归并：event_logger 在分片未满 64MB 时会把当天事件继续追加回
base 文件，所以文件名顺序不等于时间顺序；各分片内部单调，用
heapq.merge 按 ts 归并即可得到全局顺序，不需要把 200MB 日志读进内存。
"""

from __future__ import annotations

import heapq
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from spritelens.domain.egg_box import EggPickupOrigin, extract_eggs
from spritelens.domain.identity import extract_identity
from spritelens.events import PacketEvent
from spritelens.logs import get_logger
from spritelens.services.egg_pickup import EggPickupTracker
from spritelens.services.home_repository import HomeRepository
from spritelens.services.pet_repository import PetRepository

logger = get_logger("egg_origin_backfill")

OP_EGG_PICKUP_REQUEST = 0x0137


@dataclass(frozen=True)
class PickupRecord:
    """一条可补录的历史收蛋关联；source 是产出它的日志分片文件名。"""

    uid: int
    instance_id: int
    origin: EggPickupOrigin
    source: str = ""


def _opcode(value: object) -> int:
    if isinstance(value, int):
        return value
    return int(str(value), 16)


def iter_events(path: Path) -> Iterator[PacketEvent]:
    """逐行解析一个 eventlog 分片；写入中的半行与坏行跳过并计数。"""
    skipped = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                event = PacketEvent(
                    ts=float(row["ts"]),
                    session_id=str(row["session"]),
                    direction=str(row["direction"]),
                    opcode=_opcode(row["opcode"]),
                    opcode_name=str(row.get("name") or ""),
                    payload_len=int(row.get("payload_len") or 0),
                    decoded=row.get("decoded") or [],
                )
            except (KeyError, TypeError, ValueError):
                skipped += 1
                continue
            yield event
    if skipped:
        logger.warning("事件日志 %s 有 %d 行无法解析，已跳过", path.name, skipped)


def _tagged(path: Path) -> Iterator[tuple[str, PacketEvent]]:
    name = path.name
    for event in iter_events(path):
        yield name, event


def iter_event_stream(paths: Iterable[Path]) -> Iterator[tuple[str, PacketEvent]]:
    """按 ts 归并多个分片（各分片内部单调）；产出 (分片名, 事件)。"""
    return heapq.merge(*(_tagged(path) for path in paths), key=lambda item: item[1].ts)


def _is_pickup_reward(event: PacketEvent) -> bool:
    """0x0243 是通用奖励；收蛋奖励分支由字段 2=13、字段 3=223 标记。"""
    fields = {node.get("no"): node.get("raw") for node in event.decoded or []}
    return (event.direction == "s2c" and event.opcode == 0x0243
            and fields.get(2) == 13 and fields.get(3) == 223)


class EggOriginScanner:
    """按时间顺序喂事件，产出历史收蛋关联。

    装配顺序镜像 AccountSessions：身份 → 连接归属 → 收蛋请求现场快照 →
    再让 pets/home 处理同一事件；奖励帧只在本事件提取到唯一一枚数量为
    1 的蛋时落一条记录（与 EggBoxRepository 的落库条件一致）。
    """

    def __init__(self) -> None:
        self._sessions: dict[str, int] = {}
        self._homes: dict[int, HomeRepository] = {}
        self._pets: dict[int, PetRepository] = {}
        self._trackers: dict[int, EggPickupTracker] = {}
        self._records: list[PickupRecord] = []
        self._unmatched_rewards = 0

    @property
    def records(self) -> tuple[PickupRecord, ...]:
        return tuple(self._records)

    @property
    def unmatched_rewards(self) -> int:
        """收到收蛋奖励但没关联上请求的次数（请求帧未被采集或已超时）。"""
        return self._unmatched_rewards

    def feed(self, event: PacketEvent, source: str = "") -> None:
        identity = extract_identity(event)
        if identity is not None:
            previous = self._sessions.get(event.session_id)
            if previous is not None and previous != identity.uid:
                self._trackers_for(previous).clear(event.session_id)
                self._homes_for(previous).session_closed(event.session_id)
            self._sessions[event.session_id] = identity.uid
        uid = self._sessions.get(event.session_id, 0)
        # 没有本连接的身份证据，禁止借用其他连接的身份（同在线路径）。
        if uid <= 0:
            return
        home = self._homes_for(uid)
        pets = self._pets_for(uid)
        tracker = self._trackers_for(uid)
        natures: dict[int, int] = {}
        if event.direction == "c2s" and event.opcode == OP_EGG_PICKUP_REQUEST:
            snapshot = pets.consistent_snapshot()
            if snapshot.uid == uid:
                natures = {pet.gid: pet.nature for pet in snapshot.pets}
        tracker.observe(event, home.consistent_snapshot(), natures)
        origin = tracker.take(event)
        try:
            pets.handle_packet(event)
            home.handle_packet(event)
        except Exception:  # 与在线路径一致：单领域故障不阻断回放。
            logger.exception("回放事件处理失败：uid=%s opcode=0x%04X", uid, event.opcode)
        if origin is None:
            if _is_pickup_reward(event):
                # 请求帧没被采集到、或超出 3 秒窗口：这类收蛋只能留空来源。
                self._unmatched_rewards += 1
            return
        eggs = extract_eggs(event)
        if len(eggs) != 1 or eggs[0].quantity != 1:
            return
        self._records.append(PickupRecord(uid, eggs[0].instance_id, origin, source))

    def _homes_for(self, uid: int) -> HomeRepository:
        repo = self._homes.get(uid)
        if repo is None:
            repo = self._homes[uid] = HomeRepository()
        return repo

    def _pets_for(self, uid: int) -> PetRepository:
        repo = self._pets.get(uid)
        if repo is None:
            repo = self._pets[uid] = PetRepository()
        return repo

    def _trackers_for(self, uid: int) -> EggPickupTracker:
        tracker = self._trackers.get(uid)
        if tracker is None:
            tracker = self._trackers[uid] = EggPickupTracker()
        return tracker


__all__ = ["EggOriginScanner", "OP_EGG_PICKUP_REQUEST", "PickupRecord", "iter_event_stream", "iter_events"]
