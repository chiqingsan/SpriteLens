"""监听管线编排：字节流 → GCP 帧 → 提 key → 解密 → 拆分 → schema/wire 解码 → PacketEvent。

线程模型：on_chunk 由接入层后台线程（scapy 嗅探线程）调用，内部用锁保护
会话状态；UI 线程通过 drain_events() / snapshot 拉取，不做跨线程回调。
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from spritelens.capture.base import CaptureSource, SourceCallback, StreamChunk
from spritelens.capture.key_store import KeyStore, parse_key_text
from spritelens.logs import get_logger
from spritelens.protocol.crypto import extract_ack_key, iter_decrypt_variants
from spritelens.protocol.frames import FrameStream, GcpFrame
from spritelens.protocol.opcodes import OpcodeCatalog
from spritelens.protocol.records import Direction, Record, split_record
from spritelens.protocol.schema import SchemaLibrary, get_library
from spritelens.services.session_tracker import SessionTracker, Totals

logger = get_logger("monitor")

MAX_BUFFERED_EVENTS = 2000


@dataclass(frozen=True)
class PacketEvent:
    """协议层产出的统一事件：功能层与 UI 的唯一消费类型。"""

    ts: float
    session_id: str
    direction: str
    opcode: int
    opcode_name: str
    payload_len: int
    decoded: list[dict]


class _SessionState:
    """单会话可变状态（由 MonitorService 锁保护）。"""

    __slots__ = ("streams", "key")

    def __init__(self) -> None:
        self.streams: dict[str, FrameStream] = {Direction.C2S: FrameStream(), Direction.S2C: FrameStream()}
        self.key: bytes | None = None


class MonitorService:
    """把一个 CaptureSource 的字节流翻译成 PacketEvent 流。"""

    def __init__(
        self,
        *,
        catalog: OpcodeCatalog,
        key_store: KeyStore,
        schema_library: SchemaLibrary | None = None,
        tracker: SessionTracker | None = None,
        preset_key: bytes | None = None,
    ) -> None:
        self._catalog = catalog
        self._key_store = key_store
        self._schema = schema_library if schema_library is not None else get_library()
        self._tracker = tracker if tracker is not None else SessionTracker()
        self._lock = threading.Lock()
        self._sessions: dict[str, _SessionState] = {}
        self._events: deque[PacketEvent] = deque(maxlen=MAX_BUFFERED_EVENTS)
        self._source: CaptureSource | None = None
        self._preset_key = preset_key
        self._packet_listeners: list[Callable[[PacketEvent], None]] = []
        # 实例属性绑定回调，供接入层以 SourceCallback 协议持有
        self.on_chunk: SourceCallback = self._handle_chunk

    def add_packet_listener(self, callback: Callable[[PacketEvent], None]) -> None:
        """注册业务监听（应用层语义化入口）；回调异常不影响管线。"""
        with self._lock:
            self._packet_listeners.append(callback)

    # -- 生命周期 ------------------------------------------------------
    def bind(self, source: CaptureSource) -> None:
        """组合根把接入层交给管线；回调接线由此完成。"""
        self._source = source

    def start(self) -> None:
        if self._source is None:
            raise RuntimeError("尚未 bind 接入层")
        self._source.start()

    def stop(self) -> None:
        if self._source is not None:
            self._source.stop()
        # 停止即落一条最终统计，事后诊断不再靠猜
        _sessions, totals = self._tracker.snapshot()
        logger.info(
            "[stats] 停止采集：原始流 %d 段 / %d 字节，解密成功 %d，解密失败 %d，"
            "缺密钥 %d，拆分失败 %d，事件 %d 条",
            totals.raw_chunks, totals.raw_bytes, totals.decrypt_ok, totals.decrypt_fail,
            totals.key_miss, totals.parse_fail, len(self._events),
        )

    @property
    def is_running(self) -> bool:
        return self._source is not None and self._source.is_running

    def set_preset_key(self, key: bytes | None) -> None:
        """手动注入密钥：作用于现有全部会话及后续新会话（重启续解场景）。"""
        with self._lock:
            self._preset_key = key
            if key is None:
                return
            for session_id, state in self._sessions.items():
                if state.key is None:
                    state.key = key
                    self._tracker.mark_key(session_id)

    # -- 接入层回调（运行于抓包线程）----------------------------------

    def _handle_chunk(self, chunk: StreamChunk) -> None:
        self._tracker.count_raw(len(chunk.data))
        with self._lock:
            state = self._sessions.setdefault(chunk.session_id, _SessionState())
            if state.key is None and self._preset_key is not None:
                state.key = self._preset_key
                self._tracker.mark_key(chunk.session_id)
            stream = state.streams.get(chunk.direction)
            if stream is None:
                stream = state.streams[chunk.direction] = FrameStream()
            frames = stream.feed(chunk.data)
            key = state.key
            for frame in frames:
                self._handle_frame(chunk.session_id, chunk.direction, frame, state, key)

    # -- 帧处理 --------------------------------------------------------
    def _handle_frame(
        self, session_id: str, direction: str, frame: GcpFrame, state: _SessionState, key: bytes | None
    ) -> None:
        if frame.is_ack:
            key_candidate = extract_ack_key(frame.header_extra)
            if key_candidate is None:
                # 密钥提取失败曾有静默盲区：dump 原始字节以便诊断 ACK 布局差异
                logger.warning(
                    "[ack] 0x1002 未提取到密钥: flow=%s header_extra=%s body=%s",
                    session_id, frame.header_extra.hex(), frame.body.hex()[:64],
                )
            if key_candidate is not None and key_candidate != key:
                state.key = key_candidate
                self._key_store.save_latest(key_candidate, session_id)
                self._tracker.mark_key(session_id)
                logger.info("[ack] 会话 %s 捕获会话密钥", session_id)
            return
        if not frame.is_data:
            return  # 心跳/握手等控制帧：协议层无需处理
        self._tracker.count(session_id, "data_frame")
        if state.key is None:
            self._tracker.count(session_id, "key_miss")
            return
        record = self._decrypt_and_split(state.key, frame.body, direction, session_id)
        if record is None:
            # c2s 偶发非标准控制包属正常；s2c 解析失败才值得留意
            self._tracker.count(session_id, "parse_fail")
            logger.debug("拆分失败 session=%s dir=%s seq=%s", session_id, direction, frame.sequence)
            return
        self._emit(session_id, record)

    def _decrypt_and_split(
        self, key: bytes, body: bytes, direction: str, session_id: str
    ) -> Record | None:
        """两种实测加密变体（固定 IV / 自带 IV）× 拆分自适应；全失败计数并返回 None。"""
        decrypted = False
        for plaintext in iter_decrypt_variants(key, body):
            decrypted = True
            record = split_record(plaintext, Direction(direction))
            if record is not None:
                return record
        if decrypted:
            return None  # 有解密成功但格式不符 → parse_fail（由调用方计数）
        logger.debug("解密失败 session=%s seq=%s", session_id, body[:8].hex())
        self._tracker.count(session_id, "decrypt_fail")
        return None

    def _emit(self, session_id: str, record: Record) -> None:
        self._tracker.count(session_id, "decrypt_ok")
        info = self._catalog.lookup(record.opcode)
        message = info.message if info else None
        try:
            decoded = self._schema.decode(record.payload, message)
        except Exception:  # noqa: BLE001 - 解码缺陷不应中断监听
            logger.exception("schema 解码异常 opcode=0x%04X", record.opcode)
            decoded = []
        event = PacketEvent(
            ts=time.time(),
            session_id=session_id,
            direction=record.direction,
            opcode=record.opcode,
            opcode_name=info.name if info else f"op_0x{record.opcode:04X}",
            payload_len=len(record.payload),
            decoded=decoded,
        )
        self._events.append(event)
        for listener in self._packet_listeners:
            try:
                listener(event)
            except Exception:  # noqa: BLE001 - 业务回调缺陷不拖垮监听
                logger.exception("packet listener 异常 opcode=0x%04X", record.opcode)

    # -- UI / 功能层读取 ------------------------------------------------
    def drain_events(self) -> list[PacketEvent]:
        with self._lock:
            events = list(self._events)
            self._events.clear()
        return events

    def snapshot(self) -> tuple[list, Totals]:
        return self._tracker.snapshot()
