"""事件日志落盘：PacketEvent 逐条写 JSONL（复盘与离线再分析用）。

文件按天分片（eventlog_YYYYMMDD.jsonl），含完整 decoded 字段树。

写入策略（实测教训）：抓包回调运行在 MonitorService 锁内，同步 flush()
在登录突发下让 UI 的 drain_events 最长等 57ms，chunk 队列随之面临过载。
因此 handle_packet 只把事件放进有界队列（无 IO），由后台 worker 线程
批量落盘；队列满时丢新事件并计数（丢日志不阻塞采集主链路）。

锁设计：文件 IO 全程不持锁——worker 是文件句柄的唯一写者，锁只保护
计数与句柄的读取视图，保证 handle_packet 在磁盘卡死时也不阻塞。
"""

from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path

from spritelens.logs import get_logger
from spritelens.events import PacketEvent

logger = get_logger("event_log")

# 待写队列上限：抓包突发（每秒数百事件）下给 worker 数秒腾挪空间
QUEUE_MAX = 8192
_QUEUE_SENTINEL = object()


class _Barrier:
    """flush 同步点：worker 处理到它时置位，保证此前事件已落盘。"""

    __slots__ = ("done",)

    def __init__(self) -> None:
        self.done = threading.Event()


class EventLogWriter:
    """事件日志监听器；组合根挂到 monitor.add_packet_listener。"""

    def __init__(
        self, log_dir: Path, *, queue_max: int = QUEUE_MAX, close_join_timeout: float = 5.0
    ) -> None:
        self._dir = log_dir
        self._lock = threading.Lock()  # 只保护计数与句柄视图，不覆盖 IO
        self._file = None
        self._day = ""
        self._count = 0
        self._dropped = 0
        self._failed = False
        self._closed = threading.Event()
        self._close_join_timeout = max(0.0, float(close_join_timeout))
        self._queue: queue.Queue = queue.Queue(maxsize=max(1, int(queue_max)))
        self._worker = threading.Thread(
            target=self._run, name="spritelens-event-log", daemon=True
        )
        self._worker.start()

    @property
    def count(self) -> int:
        with self._lock:
            return self._count

    @property
    def dropped_count(self) -> int:
        """队列满丢弃的事件数（磁盘跟不上采集时的可见信号）。"""
        with self._lock:
            return self._dropped

    @property
    def current_path(self) -> Path | None:
        with self._lock:
            return self._file.name if self._file is not None else None

    def handle_packet(self, event: PacketEvent) -> None:
        """抓包线程回调：只入队（无 IO 不等待），worker 负责序列化与落盘。"""
        if self._closed.is_set() or self._failed:
            return
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            with self._lock:
                self._dropped += 1
                if self._dropped % 100 == 1:
                    logger.warning("事件日志队列满，累计丢弃 %d 条", self._dropped)

    def flush(self, timeout: float = 5.0) -> None:
        """等此前全部事件落盘（close 与测试用；超时返回不阻塞退出）。"""
        barrier = _Barrier()
        try:
            self._queue.put(barrier, timeout=timeout)
        except queue.Full:
            return
        barrier.done.wait(timeout)

    # -- worker ---------------------------------------------------------
    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is _QUEUE_SENTINEL:
                self._close_owned_file()
                return
            batch: list[PacketEvent] = []
            barriers: list[_Barrier] = []
            if isinstance(item, _Barrier):
                barriers.append(item)
            else:
                batch.append(item)
            stop_after = False
            # 一次取出当前全部积压：批量写 + 单次 flush，降磁盘次数
            while True:
                try:
                    nxt = self._queue.get_nowait()
                except queue.Empty:
                    break
                if nxt is _QUEUE_SENTINEL:
                    stop_after = True
                    break
                if isinstance(nxt, _Barrier):
                    barriers.append(nxt)
                    continue
                batch.append(nxt)
            self._write_batch(batch)
            for barrier in barriers:
                barrier.done.set()
            if stop_after:
                self._close_owned_file()
                return

    def _write_batch(self, events: list[PacketEvent]) -> None:
        if not events:
            return
        try:
            file = self._open_day_file()
            written = 0
            for event in events:
                line = _serialize(event)
                if line is None:
                    continue
                file.write(line + "\n")
                written += 1
            file.flush()  # 复盘场景要求及时可见（崩溃/强退后不丢）
        except OSError as exc:
            logger.warning("事件日志写入失败，停止记录: %s", exc)
            self._failed = True
            self._close_owned_file()
            return
        with self._lock:
            self._count += written

    def _open_day_file(self):
        """按天开文件（worker 独占写者）；跨天切文件。"""
        day = time.strftime("%Y%m%d")
        with self._lock:
            if self._file is not None and day == self._day:
                return self._file
        self._dir.mkdir(parents=True, exist_ok=True)
        file = (self._dir / f"eventlog_{day}.jsonl").open("a", encoding="utf-8")
        with self._lock:
            old = self._file
            self._file = file
            self._day = day
        if old is not None:
            old.close()
        return file

    def _close_owned_file(self) -> None:
        """关闭日志文件（仅限 worker 线程调用——文件句柄由 worker 独占）。"""
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None

    def close(self) -> None:
        """停止 worker 并做最后落盘（幂等；退出路径唯一）。

        文件句柄只由 worker 线程关闭：join 超时（磁盘卡死）时不再跨线程
        close——worker 正在写的那条日志会抛 ValueError 且丢失（已复现）。
        超时情况下句柄留待进程退出由 OS 回收，比丢日志安全。
        """
        if self._closed.is_set():
            return
        self._closed.set()
        # 哨兵排在已入队事件之后：worker 先写完再退出
        try:
            self._queue.put(_QUEUE_SENTINEL, timeout=1.0)
        except queue.Full:
            try:
                self._queue.get_nowait()  # 丢最旧一条腾位
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(_QUEUE_SENTINEL)
            except queue.Full:
                pass
        self._worker.join(timeout=self._close_join_timeout)
        if self._worker.is_alive():
            logger.warning("事件日志 worker 未在超时内退出，文件句柄留给进程回收")


def _serialize(event: PacketEvent) -> str | None:
    """单条事件 → JSONL 行；序列化失败返回 None（不拖垮其他事件）。"""
    try:
        # bytes 字段（宠物名等）不能直接 JSON 序列化，default 兜底转可读文本
        return json.dumps(
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
        return None


__all__ = ["QUEUE_MAX", "EventLogWriter"]
