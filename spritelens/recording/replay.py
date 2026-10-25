"""离线回放：把录制的字节流喂回监听管线，输出事件摘要。

回放与实时监听共用 MonitorService 全管线，是「录制 → 回放 → 一致」
测试基建与问题复现的基础。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from spritelens.capture.base import CaptureSource, StreamChunk
from spritelens.capture.key_store import KeyStore
from spritelens.paths import keys_dir, project_root, schema_dir
from spritelens.protocol.opcodes import OpcodeCatalog
from spritelens.protocol.schema import load_library
from spritelens.recording.recorder import read_recording
from spritelens.services.monitor_service import MonitorService

SCHEMAS_DIR = schema_dir()
OPCODES_PATH = project_root() / "data" / "schemas" / "opcodes.json"


class ReplaySource(CaptureSource):
    """把录制 chunks 同步回放给管线的假接入层（满足 CaptureSource 协议）。"""

    name = "replay"

    def __init__(self, chunks: list[StreamChunk], *, on_chunk, on_event=None) -> None:
        self._chunks = chunks
        self.on_chunk = on_chunk
        self._running = False

    def start(self) -> None:
        self._running = True
        for chunk in self._chunks:
            if not self._running:
                return
            self.on_chunk(chunk)

    def stop(self) -> None:
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running


def run_replay(path: str, *, logger: logging.Logger) -> int:
    """CLI 回放入口：输出统计与事件摘要，返回进程退出码。"""
    file = Path(path)
    if not file.is_file():
        print(f"录制文件不存在: {file}")
        return 2
    chunks = read_recording(file)
    print(f"[replay] 载入 {len(chunks)} 段流数据")

    catalog = OpcodeCatalog.load(OPCODES_PATH)
    load_library(SCHEMAS_DIR)
    key_store = KeyStore(keys_dir())
    try:
        # 回放 CLI 靠 drain_events() 打印事件，需显式开启历史（桌面装配不需要）。
        monitor = MonitorService(catalog=catalog, key_store=key_store, keep_event_history=True)
        source = ReplaySource(chunks, on_chunk=monitor.on_chunk)
        monitor.bind(source)
        started = time.perf_counter()
        source.start()
        elapsed = time.perf_counter() - started

        sessions, totals = monitor.snapshot()
        print(f"[replay] 处理耗时 {elapsed * 1000:.1f}ms")
        print(
            f"[replay] 解密成功 {totals.decrypt_ok} | 解密失败 {totals.decrypt_fail}"
            f" | 缺密钥 {totals.key_miss} | 拆分失败 {totals.parse_fail}"
        )
        for session in sessions:
            key_state = "有密钥" if session.has_key else "无密钥"
            print(f"[replay] 会话 {session.session_id}  DATA {session.data_frames} 帧 ({key_state})")

        events = monitor.drain_events()
        print(f"[replay] 事件 {len(events)} 条（最多显示 30 条）:")
        for event in events[:30]:
            print(
                f"  {event.direction:>3} 0x{event.opcode:04X} {event.opcode_name:<24}"
                f" len={event.payload_len:<5} fields={len(event.decoded)}"
            )
        return 0
    finally:
        key_store.close()
