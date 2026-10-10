"""事件流 ViewModel：拉取 PacketEvent、格式化行与解码树详情。"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

from spritelens.services.monitor_service import MonitorService, PacketEvent
from spritelens.view_models._shared import render_decoded

MAX_ROWS = 500
MAX_DETAILS = 200


@dataclass(frozen=True)
class EventRow:
    """事件表行视图数据（detail 由索引惰性取用）。"""

    index: int
    time_text: str
    direction: str
    opcode_hex: str
    opcode_name: str
    payload_len: int


class EventsViewModel:
    """持有最近事件的行视图与详情缓存；页面按 tick 拉增量。"""

    def __init__(self, *, monitor: MonitorService, max_rows: int = MAX_ROWS) -> None:
        self._monitor = monitor
        self._rows: deque[EventRow] = deque(maxlen=max_rows)
        self._details: dict[int, str] = {}
        self._next_index = 0
        self.total_events = 0

    def drain(self) -> list[EventRow]:
        """取走 monitor 攒的事件，转为行视图（含详情缓存）。"""
        new_rows: list[EventRow] = []
        for event in self._monitor.drain_events():
            row = EventRow(
                index=self._next_index,
                time_text=time.strftime("%H:%M:%S", time.localtime(event.ts)),
                direction=event.direction,
                opcode_hex=f"0x{event.opcode:04X}",
                opcode_name=event.opcode_name,
                payload_len=event.payload_len,
            )
            self._next_index += 1
            self._rows.append(row)
            self.total_events += 1
            self._details[row.index] = self._format_detail(event)
            new_rows.append(row)
        # 详情缓存与行同步有界，防长会话内存增长
        if len(self._details) > MAX_DETAILS:
            for idx in sorted(self._details)[: len(self._details) - MAX_DETAILS]:
                del self._details[idx]
        return new_rows

    def rows(self) -> list[EventRow]:
        return list(self._rows)

    def detail(self, index: int) -> str:
        return self._details.get(index, "(详情已随滚动淘汰)")

    @staticmethod
    def _format_detail(event: PacketEvent) -> str:
        head = (
            f"会话 {event.session_id}\n方向 {event.direction}  "
            f"opcode {event.opcode_name} (0x{event.opcode:04X})  payload {event.payload_len}B"
        )
        if not event.decoded:
            return head + "\n(无字段解码结果)"
        return head + "\n\n" + render_decoded(event.decoded)
