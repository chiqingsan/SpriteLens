"""录制回放一致性测试：合成流 → 落盘 → 读回 → 回放管线 → 事件一致。"""

import tempfile
import unittest
from pathlib import Path

from spritelens.capture.base import StreamChunk
from spritelens.capture.key_store import KeyStore
from spritelens.protocol.opcodes import OpcodeCatalog
from spritelens.protocol.records import Direction
from spritelens.recording.recorder import StreamRecorder, read_recording
from spritelens.recording.replay import ReplaySource
from spritelens.services.monitor_service import MonitorService
from spritelens.services.session_tracker import SessionTracker
from tests._synth import SYNTH_KEY, make_ack_frame, make_data_frame, make_protobuf_payload

SESSION = "192.168.1.20:55000"


class RecorderTest(unittest.TestCase):
    def test_roundtrip_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rec.jsonl"
            recorder = StreamRecorder()
            recorder.start(path)
            chunks = [
                StreamChunk(session_id=SESSION, direction=Direction.S2C, data=b"\x01\x02", first_seq=100),
                StreamChunk(session_id=SESSION, direction=Direction.C2S, data=b"\x03", first_seq=5),
            ]
            for chunk in chunks:
                recorder.append(chunk)
            recorder.stop()
            self.assertFalse(recorder.is_recording)
            self.assertEqual(recorder.chunk_count, 2)
            restored = read_recording(path)
        self.assertEqual([(c.session_id, str(c.direction), c.data, c.first_seq) for c in restored],
                         [(SESSION, "s2c", b"\x01\x02", 100), (SESSION, "c2s", b"\x03", 5)])

    def test_bad_lines_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rec.jsonl"
            recorder = StreamRecorder()
            recorder.start(path)
            recorder.append(
                StreamChunk(session_id=SESSION, direction=Direction.S2C, data=b"\x09", first_seq=1)
            )
            recorder.stop()
            text = path.read_text(encoding="utf-8")
            path.write_text("{broken json\n" + text + '{"session":"x"}\n', encoding="utf-8")
            chunks = read_recording(path)
        self.assertEqual(len(chunks), 1)

class ReplayPipelineTest(unittest.TestCase):
    def test_replay_reproduces_events(self):
        """录制的合成流回放后应产出与直接喂入一致的事件。"""
        ack = make_ack_frame(SYNTH_KEY)
        data = make_data_frame(SYNTH_KEY, 0x1888, make_protobuf_payload(), sequence=2)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rec.jsonl"
            recorder = StreamRecorder()
            recorder.start(path)
            # 模拟 TCP 分段：一切为二录制
            stream = ack + data
            mid = len(stream) // 2
            for i, part in enumerate((stream[:mid], stream[mid:])):
                recorder.append(
                    StreamChunk(
                        session_id=SESSION, direction=Direction.S2C, data=part, first_seq=i * 100
                    )
                )
            recorder.stop()
            chunks = read_recording(path)

        with tempfile.TemporaryDirectory() as tmp_keys:
            monitor = MonitorService(
                catalog=OpcodeCatalog({}),
                key_store=KeyStore(Path(tmp_keys)),
                tracker=SessionTracker(),
            )
        source = ReplaySource(chunks, on_chunk=monitor.on_chunk)
        monitor.bind(source)
        source.start()

        events = monitor.drain_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].opcode, 0x1888)
        self.assertEqual(events[0].payload_len, len(make_protobuf_payload()))
        _sessions, totals = monitor.snapshot()
        self.assertEqual(totals.decrypt_ok, 1)


if __name__ == "__main__":
    unittest.main()
