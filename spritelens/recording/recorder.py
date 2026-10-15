"""原始流录制：jsonl 逐行落盘 StreamChunk，供离线回放与测试 fixture。

录制点在接入层与协议层之间（tee），记录的是「重组后的连续流」——
回放时喂回同一条管线，保证与实时监听行为一致。
"""

from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path

from spritelens.capture.base import StreamChunk
from spritelens.logs import get_logger
from spritelens.protocol.records import Direction

logger = get_logger("recorder")
MAX_QUEUED_CHUNKS = 2048
BATCH_CHUNKS = 64
_STOP = object()


class StreamRecorder:
    """有界旁路队列与单写者批量落盘；过载丢录制并累计计数。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._file = None
        self._count = 0
        self._dropped = 0
        self._count_lock = threading.Lock()  # 状态查询不等待文件写入/关闭
        self._queue: queue.Queue = queue.Queue(maxsize=MAX_QUEUED_CHUNKS)
        self._worker: threading.Thread | None = None
        self._stop_enqueued = False
        self._write_error: OSError | None = None

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._file is not None

    @property
    def chunk_count(self) -> int:
        with self._count_lock:
            return self._count

    @property
    def dropped_count(self) -> int:
        with self._count_lock:
            return self._dropped

    def start(self, path: Path) -> None:
        with self._lock:
            if self._file is not None:
                return
            if self._worker is not None and self._worker.is_alive():
                raise OSError("上一次录制 worker 尚未退出")
            if self._write_error is not None:
                raise OSError("上一次录制写入失败，请先停止录制") from self._write_error
            path.parent.mkdir(parents=True, exist_ok=True)
            file = path.open("a", encoding="utf-8")
            self._queue = queue.Queue(maxsize=MAX_QUEUED_CHUNKS)
            self._stop_enqueued = False
            self._write_error = None
            with self._count_lock:
                self._count = 0
                self._dropped = 0
            self._file = file
            self._worker = threading.Thread(
                target=self._write_loop, args=(file, self._queue),
                name="spritelens-recorder", daemon=True,
            )
            self._worker.start()
            logger.info("开始录制: %s", path)

    def stop(self) -> None:
        with self._lock:
            worker = self._worker
            if worker is None:
                return
            should_stop = worker.is_alive() and not self._stop_enqueued
            self._file = None
            if should_stop:
                self._stop_enqueued = True
            pending = self._queue
        if should_stop:
            try:
                pending.put(_STOP, timeout=5)
            except queue.Full as exc:
                with self._lock:
                    self._stop_enqueued = False
                raise TimeoutError("录制队列在 5 秒内未能接受停止信号") from exc
        worker.join(timeout=5)
        if worker.is_alive():
            raise TimeoutError("录制 worker 未在 5 秒内退出")
        with self._lock:
            write_error = self._write_error
            self._write_error = None
            if self._worker is worker:
                self._worker = None
                self._stop_enqueued = False
        if write_error is not None:
            raise OSError("录制写入失败，部分片段未保存") from write_error
        logger.info("录制结束，共 %d 段，丢弃 %d 段", self._count, self._dropped)

    def append(self, chunk: StreamChunk) -> None:
        with self._lock:
            if self._file is None:
                return
            try:
                self._queue.put_nowait(chunk)
            except queue.Full:
                with self._count_lock:
                    self._dropped += 1

    def _write_loop(self, file, chunks: queue.Queue) -> None:
        batch = []
        try:
            stopping = False
            while not stopping:
                item = chunks.get()
                if item is _STOP:
                    break
                batch = [item]
                while len(batch) < BATCH_CHUNKS:
                    try:
                        item = chunks.get_nowait()
                    except queue.Empty:
                        break
                    if item is _STOP:
                        stopping = True
                        break
                    batch.append(item)
                lines = [
                    json.dumps(
                        {"ts": time.time(), "session": chunk.session_id,
                         "direction": str(chunk.direction), "seq": chunk.first_seq,
                         "data": chunk.data.hex()},
                        ensure_ascii=False, separators=(",", ":"),
                    ) + "\n"
                    for chunk in batch
                ]
                file.writelines(lines)
                file.flush()
                with self._count_lock:
                    self._count += len(batch)
        except OSError as exc:
            logger.warning("录制写入失败，停止录制: %s", exc)
            with self._lock:
                self._file = None
                self._write_error = exc
            with self._count_lock:
                self._dropped += len(batch)
                while True:
                    try:
                        dropped = chunks.get_nowait()
                    except queue.Empty:
                        break
                    if dropped is not _STOP:
                        self._dropped += 1
        finally:
            try:
                file.close()
            except OSError as exc:
                logger.warning("录制文件关闭失败: %s", exc)
                with self._lock:
                    if self._write_error is None:
                        self._write_error = exc
            with self._lock:
                if self._file is file:
                    self._file = None


def read_recording(path: Path) -> list[StreamChunk]:
    """读取录制文件还原 StreamChunk 列表；坏行跳过并告警。"""
    chunks: list[StreamChunk] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
            chunks.append(
                StreamChunk(
                    session_id=str(item["session"]),
                    direction=Direction(item["direction"]),
                    data=bytes.fromhex(item["data"]),
                    first_seq=int(item["seq"]),
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("录制行 %d 解析失败，跳过: %s", line_no, exc)
    return chunks
