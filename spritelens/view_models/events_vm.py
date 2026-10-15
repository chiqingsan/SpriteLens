"""事件流 ViewModel：拉取 PacketEvent、格式化行与解码树详情。"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

from spritelens.events import PacketEvent
from spritelens.services.monitor_service import MonitorService
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
        self._detail_events: dict[int, PacketEvent] = {}
        self._detail_order: deque[int] = deque()
        self._next_index = 0
        self.total_events = 0

    def drain(self) -> list[EventRow]:
        """取走 monitor 攒的事件，转为轻量行视图并有界保留详情源事件。"""
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
            self._detail_events[row.index] = event
            self._detail_order.append(row.index)
            new_rows.append(row)
        # 原始事件与已格式化详情合计有界，避免关闭详情页时仍保存大解码树。
        while len(self._detail_order) > MAX_DETAILS:
            expired = self._detail_order.popleft()
            self._detail_events.pop(expired, None)
            self._details.pop(expired, None)
        return new_rows

    def rows(self) -> list[EventRow]:
        return list(self._rows)

    def detail(self, index: int) -> str:
        cached = self._details.get(index)
        if cached is not None:
            return cached
        event = self._detail_events.pop(index, None)
        if event is None:
            return "(详情已随滚动淘汰)"
        formatted = self._format_detail(event)
        self._details[index] = formatted
        return formatted

    @staticmethod
    def _format_detail(event: PacketEvent) -> str:
        head = (
            f"会话 {event.session_id}\n方向 {event.direction}  "
            f"opcode {event.opcode_name} (0x{event.opcode:04X})  payload {event.payload_len}B"
        )
        if not event.decoded:
            return head + "\n(无字段解码结果)"
        return head + "\n\n" + render_decoded(event.decoded)
