"""原始流录制：jsonl 逐行落盘 StreamChunk，供离线回放与测试 fixture。

录制点在接入层与协议层之间（tee），记录的是「重组后的连续流」——
回放时喂回同一条管线，保证与实时监听行为一致。
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from spritelens.capture.base import StreamChunk
from spritelens.logs import get_logger
from spritelens.protocol.records import Direction

logger = get_logger("recorder")


class StreamRecorder:
    """线程安全的流录制器；写失败只告警（录制是旁路功能）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._file = None
        self._count = 0

    @property
    def is_recording(self) -> bool:
        return self._file is not None

    @property
    def chunk_count(self) -> int:
        with self._lock:
            return self._count

    def start(self, path: Path) -> None:
        with self._lock:
            if self._file is not None:
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            self._file = path.open("a", encoding="utf-8")
            self._count = 0
            logger.info("开始录制: %s", path)

    def stop(self) -> None:
        with self._lock:
            if self._file is None:
                return
            self._file.close()
            self._file = None
            logger.info("录制结束，共 %d 段", self._count)

    def append(self, chunk: StreamChunk) -> None:
        file = self._file
        if file is None:
            return
        line = (
            json.dumps(
                {
                    "ts": time.time(),
                    "session": chunk.session_id,
                    "direction": str(chunk.direction),
                    "seq": chunk.first_seq,
                    "data": chunk.data.hex(),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
        )
        try:
            with self._lock:
                file = self._file
                if file is None:
                    return
                file.write(line)
                file.flush()  # 供外部实时读取/诊断，不做缓冲延迟
                self._count += 1
        except OSError as exc:
            logger.warning("录制写入失败，停止录制: %s", exc)
            self.stop()


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
