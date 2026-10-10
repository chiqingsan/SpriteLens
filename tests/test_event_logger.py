"""事件日志落盘测试。"""

import json
import tempfile
import unittest
from pathlib import Path

from spritelens.services.event_logger import EventLogWriter
from spritelens.services.monitor_service import PacketEvent


def _event(opcode: int = 0x134A, decoded: list | None = None) -> PacketEvent:
    return PacketEvent(
        ts=1700000000.0,
        session_id="10.0.0.1:1000",
        direction="s2c",
        opcode=opcode,
        opcode_name=f"op_0x{opcode:04X}",
        payload_len=32,
        decoded=decoded or [{"no": 1, "name": "gid", "type": "uint32", "value": "1", "raw": 1}],
    )


class EventLogWriterTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_write_and_read_back(self):
        writer = EventLogWriter(self.dir)
        writer.handle_packet(_event())
        writer.handle_packet(_event(0x0101))
        path = writer.current_path
        self.assertIsNotNone(path)
        self.assertIn("eventlog_", str(path))
        lines = Path(path).read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 2)
        first = json.loads(lines[0])
        self.assertEqual(first["opcode"], "0x134A")
        self.assertEqual(first["decoded"][0]["name"], "gid")
        self.assertEqual(writer.count, 2)

    def test_same_day_appends_one_file(self):
        writer = EventLogWriter(self.dir)
        writer.handle_packet(_event())
        first = writer.current_path
        writer.handle_packet(_event())
        self.assertEqual(writer.current_path, first)

    def test_unwritable_dir_degrades_silently(self):
        # log_dir 指向一个已存在的"文件" → mkdir/open 失败 → failed 态，后续调用 no-op 不抛
        blocker = self.dir / "not_a_dir"
        blocker.parent.mkdir(parents=True, exist_ok=True)
        blocker.write_text("occupied", encoding="utf-8")
        writer = EventLogWriter(blocker)
        writer.handle_packet(_event())  # open 失败 → failed
        writer.handle_packet(_event())  # no-op
        self.assertEqual(writer.count, 0)


if __name__ == "__main__":
    unittest.main()
