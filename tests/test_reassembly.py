"""TCP 流重组测试：顺序、乱序、重复、重叠冲突、空洞补齐、内存有界。"""

import unittest

from spritelens.capture.reassembly import MAX_HISTORY_BYTES, TcpStreamReassembler


class ReassemblyTest(unittest.TestCase):
    def test_in_order_segments(self):
        r = TcpStreamReassembler()
        self.assertEqual(r.feed(1000, b"abc"), b"abc")
        self.assertEqual(r.feed(1003, b"def"), b"def")  # 返回值为新增数据

    def test_out_of_order_then_fill(self):
        r = TcpStreamReassembler()
        self.assertEqual(r.feed(1000, b"abc"), b"abc")  # 基准段
        self.assertEqual(r.feed(1006, b"ghi"), b"")  # 空洞后段，缓存
        self.assertEqual(r.feed(1003, b"def"), b"defghi")  # 补齐后按序吐出

    def test_stale_segment_before_base_dropped(self):
        """中段接入：早于基准的历史段直接丢弃（负偏移防护）。"""
        r = TcpStreamReassembler()
        self.assertEqual(r.feed(1003, b"def"), b"def")
        self.assertEqual(r.feed(1000, b"abc"), b"")
        self.assertEqual(r.feed(1003, b"def"), b"")  # 完全重复

    def test_duplicate_segment_ignored(self):
        r = TcpStreamReassembler()
        r.feed(1000, b"abcdef")
        self.assertEqual(r.feed(1000, b"abcdef"), b"")
        self.assertEqual(r.feed(1003, b"def"), b"")
        self.assertEqual(r.conflicts, 0)

    def test_consistent_overlap_continues(self):
        r = TcpStreamReassembler()
        r.feed(1000, b"abcdef")
        # 重复携带 2 字节旧数据 + 3 字节新数据
        self.assertEqual(r.feed(1004, b"efghi"), b"ghi")

    def test_conflicting_overlap_accepts_tail(self):
        """一般冲突：既有字节已下发、无法回退，接纳新段尾部继续（不丢整段）。"""
        r = TcpStreamReassembler()
        self.assertEqual(r.feed(1000, b"abcdef"), b"abcdef")
        out = r.feed(1002, b"XXghi")  # 重叠区 cdef ≠ XXgh，仅接纳尾部 "i"
        self.assertEqual(out, b"i")
        self.assertEqual(r.conflicts, 1)
        # 流位置随尾部推进：后续对齐段正常接收
        self.assertEqual(r.feed(1007, b"jkl"), b"jkl")

    def test_zero_tail_probe_held_until_confirmed(self):
        """全零短段暂缓下发；后续正常段到达即确认放行。"""
        r = TcpStreamReassembler()
        self.assertEqual(r.feed(100, b"\x00" * 6), b"")  # 暂缓，不下发
        out = r.feed(106, b"XY")
        self.assertEqual(out, b"\x00" * 6 + b"XY")  # 确认后连暂缓字节一起放行
        self.assertEqual(r.conflicts, 0)

    def test_zero_tail_probe_retracted_on_real_data(self):
        """实测模式：突发前 6 字节全零段与真实段同 seq。
        新策略回滚重收——真实数据零丢失（旧策略整段丢弃造成永久空洞）。"""
        r = TcpStreamReassembler()
        self.assertEqual(r.feed(100, b"\x00" * 6), b"")
        real = b"REAL!" + bytes(range(64))
        out = r.feed(100, real)  # 同 seq 冲突 → 回滚暂缓字节，整段按真实数据收
        self.assertEqual(out, real)
        self.assertEqual(r.conflicts, 1)
        self.assertEqual(r.retractions, 1)
        self.assertNotIn(b"\x00" * 6, bytes(r._buffer))  # 可疑字节已被撤销
        # 流位置正确推进：后续数据无缝衔接
        self.assertEqual(r.feed(100 + len(real), b"Z"), b"Z")

    def test_zero_tail_retraction_then_pending_drain(self):
        """回滚后 pending 中的后续突发段被正确排空。"""
        r = TcpStreamReassembler()
        self.assertEqual(r.feed(100, b"\x00" * 6), b"")  # 可疑段暂缓
        first = b"first-chunk-" * 8  # 100B
        out = r.feed(100, first)  # 同 seq 真实段 → 回滚重收
        self.assertEqual(out, first)
        nxt = 100 + len(first)
        self.assertEqual(r.feed(nxt + 50, b"B" * 70), b"")  # 空洞后段，进 pending
        self.assertEqual(r.feed(nxt, b"A" * 50), b"A" * 50 + b"B" * 70)  # 补齐后排空

    def test_gap_then_burst_drain(self):
        r = TcpStreamReassembler()
        self.assertEqual(r.feed(1000, b"A"), b"A")
        self.assertEqual(r.feed(1006, b"G"), b"")
        self.assertEqual(r.feed(1003, b"DEF"), b"")
        self.assertEqual(r.feed(1001, b"BC"), b"BCDEFG")

    def test_empty_payload_noop(self):
        r = TcpStreamReassembler()
        self.assertEqual(r.feed(1000, b""), b"")
        self.assertIsNone(r._base_seq)

    def test_delivered_bytes_released(self):
        """回归：交付的字节必须有界保留（旧实现累计流量后缓冲不释放）。

        连续交付 8 MiB 后，_buffer 只应保留历史窗口，而不是全部流量。
        """
        r = TcpStreamReassembler(name="t")
        chunk = b"x" * 65536
        seq = 0
        emitted = 0
        total = 8 * 1024 * 1024
        while emitted < total:
            out = r.feed(seq, chunk)
            emitted += len(out)
            seq += len(chunk)
        self.assertEqual(emitted, total)
        self.assertLessEqual(len(r._buffer), MAX_HISTORY_BYTES + len(chunk) + 16)
        self.assertLess(len(r._buffer), total)  # 绝不再是全量

    def test_conflict_detection_within_window_after_trim(self):
        """裁剪后窗口内的重传冲突比对仍工作（既有字节校验不被破坏）。"""
        r = TcpStreamReassembler(name="t")
        chunk = b"a" * 65536
        seq = 0
        total = 4 * 1024 * 1024
        while seq < total:
            r.feed(seq, chunk)
            seq += len(chunk)
        # 全部落在已交付区的重复段：直接忽略（不比对、不冲突）
        self.assertEqual(r.feed(seq - len(chunk), b"b" * len(chunk)), b"")
        self.assertEqual(r.conflicts, 0)
        # 窗口内、越过交付前沿的重传冲突段：既有字节不同 → 计冲突并按尾部接纳
        out = r.feed(seq - 1000, b"b" * 2000)
        self.assertEqual(r.conflicts, 1)
        self.assertEqual(out, b"b" * 1000)
        # 前沿推进后衔接正常
        self.assertEqual(r.feed(seq + 1000, b"tail"), b"tail")

    def test_stale_segment_straddling_trim_boundary(self):
        """跨越已裁剪区域与交付前沿的老段：仅接纳越过前沿的尾部。"""
        r = TcpStreamReassembler(name="t")
        chunk = b"a" * 65536
        seq = 0
        total = 2 * 1024 * 1024
        while seq < total:
            r.feed(seq, chunk)
            seq += len(chunk)
        straddle_start = seq - 1000
        out = r.feed(straddle_start, b"z" * 2000)
        # 前 1000 字节在已交付区（忽略），后 1000 字节为新数据
        self.assertEqual(out, b"z" * 1000)
        self.assertEqual(r.feed(seq + 1000, b"next"), b"next")


if __name__ == "__main__":
    unittest.main()
