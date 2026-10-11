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
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def _writer(self, log_dir: Path | None = None, **kwargs) -> EventLogWriter:
        writer = EventLogWriter(log_dir or self.dir, **kwargs)
        self.addCleanup(writer.close)
        return writer

    def test_write_and_read_back(self):
        writer = self._writer()
        writer.handle_packet(_event())
        writer.handle_packet(_event(0x0101))
        writer.flush()  # 异步落盘：等待队列排空后再读回
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
        writer = self._writer()
        writer.handle_packet(_event())
        writer.flush()
        first = writer.current_path
        writer.handle_packet(_event())
        writer.flush()
        self.assertEqual(writer.current_path, first)

    def test_close_flushes_pending_events(self):
        """close 落盘全部积压（退出不丢日志）。"""
        writer = self._writer()
        for _ in range(50):
            writer.handle_packet(_event())
        writer.close()
        files = list(self.dir.glob("eventlog_*.jsonl"))
        self.assertEqual(len(files), 1)
        lines = files[0].read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 50)
        self.assertGreaterEqual(writer.count, 50)

    def test_unwritable_dir_degrades_silently(self):
        # log_dir 指向一个已存在的"文件" → mkdir/open 失败 → failed 态，后续调用 no-op 不抛
        blocker = self.dir / "not_a_dir"
        blocker.parent.mkdir(parents=True, exist_ok=True)
        blocker.write_text("occupied", encoding="utf-8")
        writer = self._writer(blocker)
        writer.handle_packet(_event())  # worker 打开失败 → failed
        writer.flush()
        writer.handle_packet(_event())  # no-op
        writer.flush()
        self.assertEqual(writer.count, 0)

    def test_queue_full_drops_and_counts(self):
        """磁盘阻塞时队列满丢新事件并计数（不反压抓包主链路）。"""
        import threading

        writer = self._writer(queue_max=4)
        release = threading.Event()

        def blocked(events):
            release.wait(timeout=5)  # worker 卡死在这个批次上

        writer._write_batch = blocked
        writer.handle_packet(_event())  # 让 worker 取走一条并卡住
        deadline = 0
        while writer._queue.qsize() == 0 and deadline < 100:  # 等 worker 进入阻塞
            deadline += 1
            import time as _t

            _t.sleep(0.005)
        for _ in range(20):
            writer.handle_packet(_event())  # 队列（上限 4）很快满
        self.assertGreater(writer.dropped_count, 0)
        self.assertEqual(writer.count, 0)
        release.set()

    def test_close_timeout_does_not_close_file_under_worker(self):
        """回归（P2）：worker 写盘卡死时，close 超时路径不得跨线程关文件。

        旧实现 join 超时后无条件 close_file()：worker 恢复写盘时抛
        `ValueError: I/O operation on closed file`，该条日志静默丢失。
        """
        import threading

        writer = self._writer(close_join_timeout=0.1)
        release = threading.Event()
        wrote_after_release = threading.Event()

        real_write = writer._write_batch

        def slow_write(events):
            release.wait(timeout=5)  # 模拟磁盘卡死超过 join 超时
            real_write(events)
            wrote_after_release.set()

        writer._write_batch = slow_write
        writer.handle_packet(_event())  # worker 取走后卡在 slow_write

        deadline = 0
        while writer._queue.qsize() == 0 and deadline < 100:
            deadline += 1
            import time as _t

            _t.sleep(0.005)

        writer.close()  # 应在超时后返回，不关闭文件
        release.set()  # worker 恢复写盘
        self.assertTrue(
            wrote_after_release.wait(timeout=3),
            "worker 应在 release 后完成写盘",
        )
        # 文件未被跨线程关闭：那条日志成功写入
        self.assertEqual(writer.count, 1)
        files = list(self.dir.glob("eventlog_*.jsonl"))
        self.assertEqual(len(files), 1)
        self.assertEqual(len(files[0].read_text(encoding="utf-8").strip().splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
