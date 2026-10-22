"""监听管线编排：字节流 → GCP 帧 → 提 key → 解密 → 拆分 → schema/wire 解码 → PacketEvent。

线程模型：on_chunk 与连接关闭（close_session）均由接入层**投递线程**
按序调用（嗅探线程只做分类/重组/入队，见 npcap_source 模块注释——
关闭事件排在残余数据之后，不会被抢跑）。内部用锁保护会话状态；
事件消费者通过 drain_events() / snapshot 拉取，不做跨线程回调；运行中的 UI 不再提供协议流页面。
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import replace

from spritelens.capture.base import CaptureSource, SourceCallback, StreamChunk
from spritelens.capture.key_store import KeyStore, SessionCheckpoint
from spritelens.events import PacketEvent  # noqa: F401 - 过渡期重导出，见下
from spritelens.logs import get_logger
from spritelens.protocol.crypto import extract_ack_key, iter_decrypt_variants
from spritelens.protocol.frames import CMD_SYN, FrameStream, GcpFrame
from spritelens.protocol.opcodes import OpcodeCatalog
from spritelens.protocol.records import Direction, Record, split_record
from spritelens.protocol.schema import SchemaLibrary, get_library
from spritelens.services.session_tracker import SessionTracker, Totals

logger = get_logger("monitor")

MAX_BUFFERED_EVENTS = 2000
# 会话状态上限与空闲回收：抓包中途接入/异常断连会留下永不关闭的会话，
# 帧流缓冲与密钥状态必须随连接关闭或长时间无活动释放（复现过 _sessions
# 只增不减的长期运行泄漏）。
MAX_SESSIONS = 256
SESSION_IDLE_SECONDS = 30 * 60
_SWEEP_INTERVAL = 60.0


# PacketEvent 已移到中立叶子模块 spritelens/events.py（解除 domain→services
# 反向依赖）。旧调用方 `from services.monitor_service import PacketEvent`
# 经上面这行 import 仍可用（过渡期兼容，ROADMAP 阶段1）；新代码一律
# `from spritelens.events import PacketEvent`。全部调用方迁移完成后
# 删除该重导出。


class _SessionState:
    """单会话可变状态（由 MonitorService 锁保护）。"""

    __slots__ = ("streams", "key", "last_activity", "identity", "resume_checked", "checkpoint_at", "server_sequence")

    def __init__(self) -> None:
        self.streams: dict[str, FrameStream] = {Direction.C2S: FrameStream(), Direction.S2C: FrameStream()}
        self.key: bytes | None = None
        self.last_activity = time.monotonic()
        self.identity: tuple[int, str, int] | None = None
        self.resume_checked = False
        self.checkpoint_at = 0.0
        self.server_sequence = 0


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
        self._checkpoint = key_store.load_session()
        if self._preset_key is None and self._checkpoint is not None:
            self._preset_key = self._checkpoint.key
        self._packet_listeners: list[Callable[[PacketEvent], None]] = []
        self._last_sweep = 0.0
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
        with self._lock:
            confirmed = [(sid, state) for sid, state in self._sessions.items() if state.identity and state.key]
            if confirmed:
                sid, state = max(confirmed, key=lambda item: item[1].last_activity)
                self._checkpoint = SessionCheckpoint(sid, state.key, state.identity, state.server_sequence)
                self._key_store.save_session(self._checkpoint)
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

    def close_session(self, session_id: str) -> None:
        """连接关闭：释放该会话的帧流缓冲与密钥状态（由接入层事件驱动）。

        返回后同一 session_id 再来数据会按新会话重建状态（需重新提 key）。
        """
        with self._lock:
            removed = self._sessions.pop(session_id, None)
            if self._checkpoint is not None and self._checkpoint.flow_id == session_id:
                self._checkpoint = replace(self._checkpoint, identity=None)
                self._key_store.save_session(self._checkpoint)
        if removed is not None:
            self._tracker.drop(session_id)

    @property
    def session_count(self) -> int:
        with self._lock:
            return len(self._sessions)

    # -- 接入层回调（运行于抓包线程）----------------------------------

    def _handle_chunk(self, chunk: StreamChunk) -> None:
        self._tracker.count_raw(len(chunk.data))
        now = time.monotonic()
        with self._lock:
            self._sweep_locked(now)
            state = self._sessions.get(chunk.session_id)
            if state is None:
                state = _SessionState()
                self._sessions[chunk.session_id] = state
                self._evict_lru_locked()
            state.last_activity = now
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

    def _sweep_locked(self, now: float) -> None:
        """定期回收长时间无活动的会话（连接异常断开时收不到 flow_closed）。"""
        if now - self._last_sweep < _SWEEP_INTERVAL:
            return
        self._last_sweep = now
        stale = [
            session_id
            for session_id, state in self._sessions.items()
            if now - state.last_activity > SESSION_IDLE_SECONDS
        ]
        for session_id in stale:
            del self._sessions[session_id]
            self._tracker.drop(session_id)
        if stale:
            logger.info("回收空闲会话 %d 个（超时 %ds）", len(stale), SESSION_IDLE_SECONDS)

    def _evict_lru_locked(self) -> None:
        """会话数超限时淘汰最久未活动者（硬上限兜底，防内存无界增长）。"""
        while len(self._sessions) > MAX_SESSIONS:
            oldest = min(self._sessions, key=lambda sid: self._sessions[sid].last_activity)
            del self._sessions[oldest]
            self._tracker.drop(oldest)

    # -- 帧处理 --------------------------------------------------------
    def _handle_frame(
        self, session_id: str, direction: str, frame: GcpFrame, state: _SessionState, key: bytes | None
    ) -> None:
        if frame.command == CMD_SYN:
            state.resume_checked = True
            state.identity = None
            if self._checkpoint is not None and self._checkpoint.flow_id == session_id:
                self._checkpoint = replace(self._checkpoint, identity=None)
                self._key_store.save_session(self._checkpoint)
            return
        if frame.is_ack:
            state.identity = None
            state.resume_checked = True
            if self._checkpoint is not None and self._checkpoint.flow_id == session_id:
                self._checkpoint = replace(self._checkpoint, identity=None)
                self._key_store.save_session(self._checkpoint)
            key_candidate = extract_ack_key(frame.header_extra)
            if key_candidate is None:
                logger.warning(
                    "[ack] 0x1002 未提取到密钥: flow=%s header_extra_len=%d body_len=%d",
                    session_id, len(frame.header_extra), len(frame.body),
                )
            if key_candidate is not None:
                state.key = key_candidate
                self._key_store.save_latest(key_candidate, session_id)
                self._checkpoint = SessionCheckpoint(session_id, key_candidate)
                self._key_store.save_session(self._checkpoint)
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
        self._emit(session_id, record, state, frame.sequence)

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

    def _emit(self, session_id: str, record: Record, state: _SessionState, sequence: int) -> None:
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
        # 延迟导入：identity 语义层使用 PacketEvent，不在模块初始化时形成环。
        from spritelens.domain.identity import extract_identity
        identity = extract_identity(event)
        resumed = False
        if record.direction == "s2c":
            if identity is not None:
                state.identity = (identity.uid, identity.name, identity.level)
            elif not state.resume_checked:
                checkpoint = self._checkpoint
                if (checkpoint is not None and checkpoint.identity is not None
                        and checkpoint.flow_id == session_id and checkpoint.key == state.key
                        and sequence > checkpoint.server_sequence):
                    state.identity = checkpoint.identity
                    event = replace(event, resumed_identity=checkpoint.identity)
                    resumed = True
                    logger.info("已确认原会话接续: %s", session_id)
                elif checkpoint is not None and checkpoint.flow_id == session_id:
                    # 首帧不连续时使旧关联失效，不能等新连接序号涨过旧值后再误恢复。
                    self._checkpoint = replace(checkpoint, identity=None)
                    self._key_store.save_session(self._checkpoint)
            state.resume_checked = True
            state.server_sequence = sequence
            now = time.monotonic()
            if state.identity and state.key and (identity is not None or resumed or now - state.checkpoint_at >= 5):
                self._checkpoint = SessionCheckpoint(session_id, state.key, state.identity, sequence)
                self._key_store.save_session(self._checkpoint)
                state.checkpoint_at = now
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
