"""监听管线端到端测试：合成 GCP 流走完整「切帧→提 key→解密→拆分→解码」。"""

import tempfile
import unittest
from pathlib import Path

from spritelens.capture.base import StreamChunk
from spritelens.capture.key_store import KeyStore
from spritelens.protocol.opcodes import OpcodeCatalog
from spritelens.protocol.records import Direction
from spritelens.protocol.schema import load_library
from spritelens.services.monitor_service import MonitorService
from spritelens.services.session_tracker import SessionTracker
from tests._synth import (
    SYNTH_KEY,
    make_ack_frame,
    make_data_frame,
    make_data_frame_ivct,
    make_protobuf_payload,
)

SESSION = "10.0.0.5:51000"


class MonitorServiceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        self.tracker = SessionTracker()
        self.monitor = MonitorService(
            catalog=OpcodeCatalog({}),
            key_store=KeyStore(self.tmp_path / "keys"),
            tracker=self.tracker,
        )

    def _feed_raw(self, raw: bytes, direction: Direction = Direction.S2C, seq: int = 1):
        self.monitor.on_chunk(StreamChunk(session_id=SESSION, direction=direction, data=raw, first_seq=seq))

    def test_injected_schema_library_takes_priority_over_global(self):
        """注入的 SchemaLibrary 完全生效，不回读全局库（阶段1边界锁定）。

        MonitorService 未显式加载全局库时（独立测试/回放），注入实例
        决定解码命名；即使全局库为空也不退化为 field_N。
        """
        from spritelens.protocol import schema as schema_mod
        from spritelens.protocol.opcodes import OpcodeInfo
        from spritelens.protocol.schema import SchemaLibrary

        library = SchemaLibrary(
            messages={"SynthMsg": {1: {"name": "injected_name", "type": ""}}},
            source_dir=None,
        )
        monitor = MonitorService(
            catalog=OpcodeCatalog({0x1234: OpcodeInfo("SynthTest", "test", "SynthMsg")}),
            key_store=KeyStore(self.tmp_path / "keys"),
            tracker=self.tracker,
            schema_library=library,
        )
        saved = schema_mod._library
        schema_mod._library = None  # 全局库为空：解码若回读全局将退化为 field_1
        try:
            # DATA 前需要 ACK 提供会话密钥（无密钥帧被 key_miss 计数丢弃）
            monitor.on_chunk(StreamChunk(
                session_id=SESSION, direction=Direction.S2C,
                data=make_ack_frame(SYNTH_KEY), first_seq=1,
            ))
            monitor.on_chunk(StreamChunk(
                session_id=SESSION, direction=Direction.S2C,
                data=make_data_frame(SYNTH_KEY, 0x1234, make_protobuf_payload(), sequence=2),
                first_seq=2,
            ))
        finally:
            schema_mod._library = saved
        events = monitor.drain_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].opcode_name, "SynthTest")
        self.assertEqual(events[0].decoded[0]["name"], "injected_name")

    def test_ack_then_data_yields_event(self):
        self._feed_raw(make_ack_frame(SYNTH_KEY))
        self._feed_raw(make_data_frame(SYNTH_KEY, 0x1888, make_protobuf_payload(), sequence=2))
        events = self.monitor.drain_events()
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.session_id, SESSION)
        self.assertEqual(event.direction, "s2c")
        self.assertEqual(event.opcode, 0x1888)
        self.assertEqual(event.opcode_name, "op_0x1888")
        self.assertEqual(event.payload_len, len(make_protobuf_payload()))
        self.assertEqual(len(event.decoded), 3)

        _sessions, totals = self.monitor.snapshot()
        self.assertEqual(totals.decrypt_ok, 1)
        self.assertEqual(totals.key_miss, 0)

    def test_key_persisted_to_store(self):
        self._feed_raw(make_ack_frame(SYNTH_KEY))
        latest = KeyStore(self.tmp_path / "keys").load_latest()
        self.assertEqual(latest, SYNTH_KEY)

    def test_data_without_key_counts_miss(self):
        self._feed_raw(make_data_frame(SYNTH_KEY, 0x0001, b"\x00" * 16, sequence=1))
        events = self.monitor.drain_events()
        self.assertEqual(events, [])
        _sessions, totals = self.monitor.snapshot()
        self.assertEqual(totals.key_miss, 1)
        self.assertEqual(totals.decrypt_ok, 0)

    def test_embedded_iv_frame_yields_event(self):
        """自带 IV 变体（body = IV+密文）的 DATA 帧走双变体自适应正常产出事件。"""
        self._feed_raw(make_ack_frame(SYNTH_KEY))
        self._feed_raw(make_data_frame_ivct(SYNTH_KEY, 0x1889, make_protobuf_payload(), sequence=2))
        events = self.monitor.drain_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].opcode, 0x1889)
        self.assertEqual(events[0].payload_len, len(make_protobuf_payload()))
        _sessions, totals = self.monitor.snapshot()
        self.assertEqual(totals.decrypt_ok, 1)
        self.assertEqual(totals.decrypt_fail, 0)
        self.assertEqual(totals.parse_fail, 0)

    def test_mixed_variants_both_yield_events(self):
        """同一会话内固定 IV 与自带 IV 两种变体帧混发均能解析。"""
        self._feed_raw(make_ack_frame(SYNTH_KEY))
        self._feed_raw(make_data_frame(SYNTH_KEY, 0x0102, b"\x0a" * 16, sequence=2))
        self._feed_raw(make_data_frame_ivct(SYNTH_KEY, 0x0103, b"\x0b" * 16, sequence=3))
        events = self.monitor.drain_events()
        self.assertEqual([e.opcode for e in events], [0x0102, 0x0103])
        _sessions, totals = self.monitor.snapshot()
        self.assertEqual(totals.decrypt_ok, 2)
        self.assertEqual(totals.parse_fail, 0)

    def test_stream_split_across_chunks(self):
        """帧被 TCP 分段切开仍能解析（FrameStream 缓冲）。"""
        ack = make_ack_frame(SYNTH_KEY)
        data = make_data_frame(SYNTH_KEY, 0x0002, b"\x01" * 32, sequence=2)
        stream = ack + data
        half = len(stream) // 2
        self._feed_raw(stream[:half])
        self.assertEqual(self.monitor.drain_events(), [])
        self._feed_raw(stream[half:])
        events = self.monitor.drain_events()
        self.assertEqual(len(events), 1)

    def test_preset_key_replays_without_ack(self):
        """工具重启续解：无 ACK 时用 preset key 直接解密。"""
        monitor = MonitorService(
            catalog=OpcodeCatalog({}),
            key_store=KeyStore(self.tmp_path / "keys"),
            tracker=SessionTracker(),
            preset_key=SYNTH_KEY,
        )
        monitor.on_chunk(
            StreamChunk(
                session_id=SESSION,
                direction=Direction.S2C,
                data=make_data_frame(SYNTH_KEY, 0x0003, b"\x02" * 16, sequence=1),
                first_seq=1,
            )
        )
        events = monitor.drain_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].opcode, 0x0003)

    def test_manual_preset_key_applies_to_existing_sessions(self):
        self._feed_raw(make_data_frame(SYNTH_KEY, 0x0004, b"\x03" * 16, sequence=1))
        self.assertEqual(self.monitor.drain_events(), [])
        self.monitor.set_preset_key(SYNTH_KEY)
        self._feed_raw(make_data_frame(SYNTH_KEY, 0x0005, b"\x04" * 16, sequence=2))
        events = self.monitor.drain_events()
        self.assertEqual([e.opcode for e in events], [0x0005])

    def test_c2s_direction(self):
        self._feed_raw(make_ack_frame(SYNTH_KEY))
        self._feed_raw(
            make_data_frame(SYNTH_KEY, 0x0101, b"abc", sequence=3, direction="c2s"),
            direction=Direction.C2S,
            seq=2,
        )
        events = self.monitor.drain_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].direction, "c2s")
        self.assertEqual(events[0].opcode, 0x0101)

    def test_per_session_isolation(self):
        other = "10.0.0.6:52000"
        self._feed_raw(make_ack_frame(SYNTH_KEY))
        self.monitor.on_chunk(
            StreamChunk(
                session_id=other,
                direction=Direction.S2C,
                data=make_data_frame(SYNTH_KEY, 0x0006, b"\x05" * 16, sequence=1),
                first_seq=1,
            )
        )
        # other 会话没收到自己的 ACK，但 preset 未设置 → key_miss
        _sessions, totals = self.monitor.snapshot()
        self.assertEqual(totals.key_miss, 1)
        self.assertEqual(totals.decrypt_ok, 0)

    def test_close_session_releases_state(self):
        """连接关闭事件释放管线会话状态（回归：_sessions 曾只增不减）。"""
        self._feed_raw(make_ack_frame(SYNTH_KEY))
        self.assertEqual(self.monitor.session_count, 1)
        self.monitor.close_session(SESSION)
        self.assertEqual(self.monitor.session_count, 0)
        # 统计表同步移除该会话行
        sessions, _totals = self.monitor.snapshot()
        self.assertEqual([s.session_id for s in sessions], [])
        # 同一 session_id 再次到来按新会话重建（需重新提 key）
        self._feed_raw(make_data_frame(SYNTH_KEY, 0x0007, b"\x06" * 16, sequence=5))
        _sessions, totals = self.monitor.snapshot()
        self.assertEqual(totals.key_miss, 1)

    def test_idle_session_swept(self):
        """空闲超时回收：抓包异常断连（收不到 flow_closed）也能释放。"""
        import spritelens.services.monitor_service as mod

        self._feed_raw(make_ack_frame(SYNTH_KEY))
        self.assertEqual(self.monitor.session_count, 1)
        original = mod.SESSION_IDLE_SECONDS
        mod.SESSION_IDLE_SECONDS = 0.0
        try:
            self.monitor._last_sweep = 0.0
            self._feed_raw(make_data_frame(SYNTH_KEY, 0x0008, b"\x07" * 16, sequence=6))
            # 上一条 chunk 里旧会话被清扫，同 id 重建
            self.assertEqual(self.monitor.session_count, 1)
        finally:
            mod.SESSION_IDLE_SECONDS = original

    def test_session_hard_cap(self):
        """会话数硬上限（LRU 淘汰），防止内存无界增长。"""
        import spritelens.services.monitor_service as mod

        original = mod.MAX_SESSIONS
        mod.MAX_SESSIONS = 3
        try:
            for i in range(6):
                self.monitor.on_chunk(StreamChunk(
                    session_id=f"10.9.9.{i}:5000",
                    direction=Direction.S2C,
                    data=b"\x33\x66" + b"\x00" * 30,
                    first_seq=1,
                ))
            self.assertLessEqual(self.monitor.session_count, 3)
        finally:
            mod.MAX_SESSIONS = original

    def test_source_events_preserve_data_before_close(self):
        """回归（P1）：接入层关闭事件排在本会话数据之后，密钥不被提前清掉。

        旧实现：FIN 在嗅探线程直接回调 close_session，越过仍排队的 DATA，
        协议层先清密钥再处理残余数据 → key_miss，且会话被重新建出。
        """
        from spritelens.capture.npcap_source import FlowClosed, NpcapCaptureSource

        source = NpcapCaptureSource(
            port=8195,
            on_chunk=self.monitor.on_chunk,
            on_event=lambda kind, detail: self.monitor.close_session(detail) if kind == "flow_closed" else None,
        )
        # 依次投递：ACK（此时入会话）→ DATA → 关闭事件（模拟已排队的顺序）
        self.monitor.on_chunk(StreamChunk(
            session_id=SESSION, direction=Direction.S2C, data=make_ack_frame(SYNTH_KEY), first_seq=1))
        self.monitor.on_chunk(StreamChunk(
            session_id=SESSION, direction=Direction.S2C,
            data=make_data_frame(SYNTH_KEY, 0x0009, b"\x08" * 16, sequence=2), first_seq=2))
        source._announce_flow_closed(SESSION)  # 排队（本测试未起投递线程）

        # 顺序处理队列：DATA 先解出事件、关闭事件再释放会话
        while not source._queue.empty():
            item = source._queue.get_nowait()
            if isinstance(item, FlowClosed):
                source._on_event("flow_closed", item.flow_id)
            else:
                source._on_chunk(item)

        events = self.monitor.drain_events()
        self.assertEqual([e.opcode for e in events], [0x0009])  # DATA 正常解出
        _sessions, totals = self.monitor.snapshot()
        self.assertEqual(totals.key_miss, 0)
        # 关闭后会话已释放，且不会被残余数据重新建出
        self.assertEqual(self.monitor.session_count, 0)


if __name__ == "__main__":
    unittest.main()
