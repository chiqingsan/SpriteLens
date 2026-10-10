"""事件日志落盘：PacketEvent 逐条写 JSONL（复盘与离线再分析用）。

文件按天分片（eventlog_YYYYMMDD.jsonl），含完整 decoded 字段树；
线程安全（挂载于 MonitorService 的抓包线程回调）。写入失败降级
为停止记录并告警，不影响监听。
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from spritelens.logs import get_logger
from spritelens.services.monitor_service import PacketEvent

logger = get_logger("event_log")


class EventLogWriter:
    """事件日志监听器；组合根挂到 monitor.add_packet_listener。"""

    def __init__(self, log_dir: Path) -> None:
        self._dir = log_dir
        self._lock = threading.Lock()
        self._file = None
        self._day = ""
        self._count = 0
        self._failed = False

    @property
    def count(self) -> int:
        with self._lock:
            return self._count

    @property
    def current_path(self) -> Path | None:
        with self._lock:
            return self._file.name if self._file is not None else None

    def handle_packet(self, event: PacketEvent) -> None:
        if self._failed:
            return
        try:
            # bytes 字段（宠物名等）不能直接 JSON 序列化，default 兜底转可读文本
            line = json.dumps(
                {
                    "ts": event.ts,
                    "session": event.session_id,
                    "direction": event.direction,
                    "opcode": f"0x{event.opcode:04X}",
                    "name": event.opcode_name,
                    "payload_len": event.payload_len,
                    "decoded": event.decoded,
                },
                ensure_ascii=False,
                separators=(",", ":"),
                default=lambda b: b.decode("utf-8", errors="replace") if isinstance(b, (bytes, bytearray)) else str(b),
            )
        except Exception:  # noqa: BLE001 - 单条事件序列化失败不拖垮日志
            logger.exception("事件序列化失败 opcode=0x%04X", event.opcode)
            return
        try:
            with self._lock:
                self._open_locked()
                self._file.write(line + "\n")
                self._file.flush()  # 复盘场景要求实时可见（崩溃/强退后不丢）
                self._count += 1
        except OSError as exc:
            logger.warning("事件日志写入失败，停止记录: %s", exc)
            self._failed = True
            self._close_locked()

    def _open_locked(self) -> None:
        day = time.strftime("%Y%m%d")
        if self._file is not None and day == self._day:
            return
        if self._file is not None:
            self._file.close()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._day = day
        self._file = (self._dir / f"eventlog_{day}.jsonl").open("a", encoding="utf-8")

    def _close_locked(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    def close(self) -> None:
        with self._lock:
            self._close_locked()
