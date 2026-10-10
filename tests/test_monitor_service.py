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


if __name__ == "__main__":
    unittest.main()
