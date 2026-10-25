"""事件日志落盘测试。"""

import json
import tempfile
import time
import unittest
from pathlib import Path

from spritelens.services.event_logger import EventLogWriter
from spritelens.events import PacketEvent


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
    def test_disk_failure_is_visible_and_unrecorded_events_are_counted(self):
        from unittest.mock import patch

        writer = EventLogWriter(self.dir)
        with patch.object(writer, "_open_day_file", side_effect=OSError("disk full")):
            writer.handle_packet(_event())
            with self.assertRaises(OSError):
                writer.flush()
        self.assertIn("disk full", writer.error)
        writer.handle_packet(_event())
        self.assertEqual(writer.dropped_count, 2)
        with self.assertRaises(OSError):
            writer.close()
        self.assertFalse(writer._worker.is_alive())

    def test_failed_flush_and_failed_file_close_do_not_kill_worker_before_barrier(self):
        from unittest.mock import Mock, patch

        writer = EventLogWriter(self.dir)
        file = Mock()
        file.flush.side_effect = OSError("disk full")
        file.close.side_effect = OSError("close flush failed")
        writer._file = file
        with patch.object(writer, "_open_day_file", return_value=file):
            writer.handle_packet(_event())
            with self.assertRaises(OSError):
                writer.flush(timeout=1)
        with self.assertRaises(OSError):
            writer.close()
        self.assertFalse(writer._worker.is_alive())

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

    def test_batches_are_bounded_under_sustained_input(self):
        """持续输入时按批上限落盘，不把整个积压抓成一个无界批次（PERF05）。

        旧实现 worker 一直取到队列暂时为空才写，慢盘下批次可超过队列容量；
        这里先把队列压满，再确认每批都不超过 `batch_max_events`。
        """
        import threading

        writer = self._writer(batch_max_events=8)
        sizes: list[int] = []
        real_write = writer._write_batch
        release = threading.Event()

        def recording_write(events):
            sizes.append(len(events))
            release.wait(timeout=5)  # 第一拍卡住，让事件先在队列里积压
            real_write(events)

        writer._write_batch = recording_write
        writer.handle_packet(_event())  # worker 取走一条并卡在首拍
        deadline = 0
        while writer._queue.qsize() == 0 and deadline < 100:
            deadline += 1
            time.sleep(0.005)
        for _ in range(49):
            writer.handle_packet(_event())
        release.set()
        writer.flush()
        self.assertEqual(writer.dropped_count, 0)
        self.assertEqual(writer.count, 50)
        self.assertTrue(sizes, "应至少写入一批")
        self.assertLessEqual(max(sizes), 8, f"单批不得超过上限，实际 {sizes}")
        self.assertEqual(sum(sizes), 50)
        files = list(self.dir.glob("eventlog_*.jsonl"))
        self.assertEqual(
            sum(len(p.read_text(encoding="utf-8").strip().splitlines()) for p in files),
            50,
            "按上限分批后仍要完整落盘",
        )

    def test_written_tail_batch_is_released_while_worker_idles(self):
        """PERF05 返修：尾批落盘后 worker 空闲等新事件，不得继续持有已写入对象。"""
        import gc
        import weakref

        writer = self._writer()
        event = _event()
        reference = weakref.ref(event)
        writer.handle_packet(event)
        deadline = time.monotonic() + 5
        while writer.count == 0 or writer._queue.qsize():
            if time.monotonic() > deadline:
                self.fail("日志未在预算内写入")
            time.sleep(0.01)
        del event
        time.sleep(0.05)  # 等 worker 走完收尾分支进入阻塞等待
        gc.collect()
        self.assertIsNone(reference(), "空闲的 worker 仍持有已落盘事件")

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

        with self.assertRaises(TimeoutError):
            writer.close()  # 超时必须留出可重试的关闭状态
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
        writer.close()


    def test_part_rotation_switches_file_and_notifies(self):
        """当天分片写满目标大小就切下一个分片，旧分片不再追加。"""
        calls: list[Path] = []
        writer = self._writer(max_part_bytes=1, on_rollover=calls.append)
        writer.handle_packet(_event())
        writer.flush()
        parts = sorted(self.dir.glob("eventlog_*.jsonl"))
        self.assertEqual(len(parts), 2, "写满后应切出第二个分片")
        base = next(p for p in parts if "_p0" not in p.name)
        first_part = next(p for p in parts if "_p0" in p.name)
        self.assertTrue(first_part.name.endswith("_p02.jsonl"))
        self.assertEqual(calls, [first_part], "切换分片时应回调新分片路径")
        self.assertEqual(len(base.read_text(encoding="utf-8").strip().splitlines()), 1)
        self.assertEqual(first_part.read_text(encoding="utf-8"), "")

        writer.handle_packet(_event(0x0101))
        writer.flush()
        second_part = writer.current_path
        self.assertNotEqual(second_part, first_part)
        self.assertTrue(second_part.name.endswith("_p03.jsonl"))
        self.assertEqual(calls, [first_part, second_part])
        self.assertEqual(len(first_part.read_text(encoding="utf-8").strip().splitlines()), 1)
        self.assertEqual(second_part.read_text(encoding="utf-8"), "", "新分片在下一次写入前为空")
        self.assertEqual(len(base.read_text(encoding="utf-8").strip().splitlines()), 1, "旧分片不再追加")

    def test_existing_oversized_same_day_part_is_not_appended(self):
        """上次运行留下的大分片（当天）不再追加，另起 p02 分片。"""
        day = time.strftime("%Y%m%d")
        base = self.dir / f"eventlog_{day}.jsonl"
        original = b'{"opcode": "0x0000"}\n' * 20  # 500 字节，超过下面的上限
        base.write_bytes(original)
        calls: list[Path] = []
        writer = self._writer(max_part_bytes=400, on_rollover=calls.append)
        writer.handle_packet(_event())
        writer.flush()
        self.assertEqual(base.read_bytes(), original, "旧分片不得被追加")
        part = writer.current_path
        self.assertTrue(part.name.endswith("_p02.jsonl"))
        self.assertEqual(len(part.read_text(encoding="utf-8").strip().splitlines()), 1)
        self.assertEqual(calls, [], "首次打开新分片不触发清理回调（启动清理另行执行）")

    def test_rollover_callback_failure_does_not_break_writer(self):
        """清理回调异常只 warning，不影响日志写入。"""
        def boom(_path: Path) -> None:
            raise RuntimeError("cleanup failed")

        writer = self._writer(max_part_bytes=1, on_rollover=boom)
        with self.assertLogs("spritelens.event_log", level="WARNING"):
            writer.handle_packet(_event())
            writer.flush()
        self.assertEqual(writer.count, 1)
        self.assertEqual(writer.error, "")


if __name__ == "__main__":
    unittest.main()
