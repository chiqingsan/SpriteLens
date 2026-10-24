"""事件日志落盘：PacketEvent 逐条写 JSONL（复盘与离线再分析用）。

文件按天分片（eventlog_YYYYMMDD.jsonl），含完整 decoded 字段树。

写入策略（实测教训）：抓包回调运行在 MonitorService 锁内，同步 flush()
在登录突发下让事件消费者的 drain_events 最长等 57ms，chunk 队列随之面临过载。
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
from typing import Callable

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
    """事件日志监听器；组合根挂到 monitor.add_packet_listener。

    on_day_rollover：可选跨天回调（worker 线程、无锁调用），参数是切换后
    新一天的文件路径，供保留策略把旧分片当 keep 之外的文件清理。回调异常
    只 warning，不影响日志写入；默认 None 保持既有行为。
    """

    def __init__(
        self,
        log_dir: Path,
        *,
        queue_max: int = QUEUE_MAX,
        close_join_timeout: float = 5.0,
        on_day_rollover: Callable[[Path], None] | None = None,
    ) -> None:
        self._dir = log_dir
        self._on_day_rollover = on_day_rollover
        self._lock = threading.Lock()  # 只保护计数与句柄视图，不覆盖 IO
        self._file = None
        self._day = ""
        self._count = 0
        self._dropped = 0
        self._failed = False
        self._error = ""
        self._closed = threading.Event()
        self._close_lock = threading.Lock()
        self._close_enqueued = False
        self._close_complete = False
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

    @property
    def error(self) -> str:
        with self._lock:
            return self._error

    def handle_packet(self, event: PacketEvent) -> None:
        """抓包线程回调：只入队（无 IO 不等待），worker 负责序列化与落盘。"""
        if self._closed.is_set():
            return
        with self._lock:
            if self._failed:
                self._dropped += 1
                return
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            with self._lock:
                self._dropped += 1
                if self._dropped % 100 == 1:
                    logger.warning("事件日志队列满，累计丢弃 %d 条", self._dropped)

    def flush(self, timeout: float = 5.0) -> None:
        """等待此前事件写入；失败或超时必须向调用者报告。"""
        if self.error:
            raise OSError(self.error)
        barrier = _Barrier()
        try:
            self._queue.put(barrier, timeout=timeout)
        except queue.Full:
            raise TimeoutError("事件日志队列未在保存预算内排空")
        if not barrier.done.wait(timeout):
            raise TimeoutError("事件日志未在保存预算内写完")
        if self.error:
            raise OSError(self.error)

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
        with self._lock:
            if self._failed:
                self._dropped += len(events)
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
            with self._lock:
                self._failed = True
                self._error = f"事件日志已停止记录：{exc}；请修复存储问题后重启程序"
                self._dropped += len(events)  # 本批次未确认完整写入。
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
        path = self._dir / f"eventlog_{day}.jsonl"
        file = path.open("a", encoding="utf-8")
        with self._lock:
            old = self._file
            self._file = file
            self._day = day
        if old is not None:
            old.close()
            # 旧分片已关闭且不持锁：此时回调清理旧文件不会与写入/加锁重入冲突
            self._notify_day_rollover(path)
        return file

    def _notify_day_rollover(self, path: Path) -> None:
        """跨天回调：仅为保留策略服务，失败只 warning 不影响日志写入。"""
        callback = self._on_day_rollover
        if callback is None:
            return
        try:
            callback(path)
        except Exception as exc:  # noqa: BLE001 - 清理失败不得影响日志写入
            logger.warning("事件日志跨天清理回调失败: %s", exc)

    def _close_owned_file(self) -> None:
        """关闭日志文件（仅限 worker 线程调用——文件句柄由 worker 独占）。"""
        with self._lock:
            file, self._file = self._file, None
        if file is not None:
            try:
                file.close()
            except OSError as exc:
                logger.warning("事件日志文件关闭失败: %s", exc)
                with self._lock:
                    self._failed = True
                    self._error = self._error or f"事件日志文件关闭失败：{exc}；请修复存储后重启程序"

    def close(self) -> None:
        """停止 worker 并做最后落盘（幂等；退出路径唯一）。

        文件句柄只由 worker 线程关闭：join 超时（磁盘卡死）时不再跨线程
        close——worker 正在写的那条日志会抛 ValueError 且丢失（已复现）。
        超时情况下句柄留待进程退出由 OS 回收，比丢日志安全。
        """
        with self._close_lock:
            if self._close_complete:
                if self.error:
                    raise OSError(self.error)
                return
            self._closed.set()
            # 哨兵只入队一次；join 超时后下一次 close 继续等待同一 worker。
            if not self._close_enqueued:
                try:
                    self._queue.put(_QUEUE_SENTINEL, timeout=1.0)
                except queue.Full:
                    try:
                        self._queue.get_nowait()  # 丢最旧一条腾位
                    except queue.Empty:
                        pass
                    self._queue.put(_QUEUE_SENTINEL, timeout=1.0)
                self._close_enqueued = True
        self._worker.join(timeout=self._close_join_timeout)
        if self._worker.is_alive():
            logger.warning("事件日志 worker 未在超时内退出，文件句柄留给进程回收")
            raise TimeoutError("事件日志 worker 未在关闭预算内完成")
        with self._close_lock:
            self._close_complete = True
        if self.error:
            raise OSError(self.error)


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
