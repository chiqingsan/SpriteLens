"""收蛋请求与入仓奖励关联；只使用同连接、当前家园的现场快照。

收蛋交互的 `option_id` 不是固定值：实测同一账号、同类收蛋里出现过
830000165 / 830000166 / 830000217（普通窝）与 830000009（学院窝），
所以判据是「`0x0137` 的目标 actor 能在当前快照里解析为场景蛋」，而不是
选项白名单。奖励帧本身没有目标 ID，只能按「最近一次收蛋交互」配对：
3 秒内连续收不同蛋时，每次奖励都归给最近一条请求。
"""
from __future__ import annotations

from dataclasses import replace

from spritelens.domain.egg_box import EggParent, EggPickupOrigin
from spritelens.events import PacketEvent
from spritelens.services.home_repository import HomeRepoSnapshot

# 请求与奖励的配对窗口（秒）。奖励帧在请求后约 1 毫秒到达，窗口只用于
# 容忍抓包重排与重复请求帧。
PICKUP_WINDOW_SECONDS = 3.0


class EggPickupTracker:
    def __init__(self) -> None:
        self._pending: dict[str, EggPickupOrigin] = {}

    def clear(self, session_id: str | None = None) -> None:
        if session_id is None:
            self._pending.clear()
        else:
            self._pending.pop(session_id, None)

    def observe(self, event: PacketEvent, home: HomeRepoSnapshot, natures: dict[int, int]) -> None:
        if event.direction == "s2c" and event.opcode in (0x0152, 0x015C):
            self.clear(event.session_id)
        if event.direction != "c2s" or event.opcode != 0x0137:
            return
        snap = home.data
        if (snap is None or home.source not in ("observed", "stale")
                or home.session_id != event.session_id or snap.owner_uid != home.uid):
            return
        fields = {node["no"]: node.get("raw") for node in event.decoded or []}
        egg = next((row for row in snap.scene_eggs if row.actor_id == fields.get(1)), None)
        nest = next((row for row in snap.nests if egg and row.guid == egg.furniture_guid), None)
        if egg is None or nest is None:
            return
        mothers = [row for row in snap.residents if row.nest_guid == nest.guid and row.gender == 2]
        mother = mothers[0] if len(mothers) == 1 else None
        couple = next((row for row in snap.couples if mother and row.female_actor_id == mother.actor_id), None)
        residents = {row.actor_id: row for row in snap.residents}
        fathers = [residents[actor] for actor in couple.male_actor_ids if actor in residents] if couple else []
        self._pending[event.session_id] = EggPickupOrigin(
            egg.actor_id, nest.guid, nest.kind, nest.config_id,
            EggParent(mother.instance_id, mother.name, mother.base_conf_id) if mother else None,
            tuple(EggParent(row.instance_id, row.name, row.base_conf_id) for row in fathers),
            event.ts, snap.couples_stale or home.pending_deltas > 0,
            natures.get(mother.instance_id, 0) if mother else 0,
        )

    def take(self, event: PacketEvent) -> EggPickupOrigin | None:
        fields = {node["no"]: node.get("raw") for node in event.decoded or []}
        # 0x0243 是通用奖励；只关联本次已核对的家园收蛋奖励分支。
        if event.opcode != 0x0243 or fields.get(2) != 13 or fields.get(3) != 223:
            return None
        origin = self._pending.pop(event.session_id, None)
        if origin is None or not 0 <= event.ts - origin.observed_at <= PICKUP_WINDOW_SECONDS:
            return None
        return replace(origin, observed_at=event.ts)
