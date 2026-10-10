"""GCP 帧切分测试：正常帧、粘包、跨段、假 magic 同步、异常守护。"""

import unittest

from spritelens.protocol.frames import CMD_DATA, FIXED_HEAD_LEN, FrameStream, MAGIC, MAGIC_INT, parse_frames
from tests._synth import make_data_frame, encode_frame, SYNTH_KEY


class ParseFramesTest(unittest.TestCase):
    def test_single_frame_fields(self):
        raw = encode_frame(CMD_DATA, flag=0x01, sequence=0x11223344, header_extra=b"\x00\x00\x00\x00", body=b"\x11" * 32)
        frames, consumed = parse_frames(raw)
        self.assertEqual(consumed, len(raw))
        self.assertEqual(len(frames), 1)
        frame = frames[0]
        self.assertEqual(frame.command, CMD_DATA)
        self.assertEqual(frame.flag, 0x01)
        self.assertEqual(frame.sequence, 0x11223344)
        self.assertEqual(frame.body, b"\x11" * 32)
        self.assertTrue(frame.is_data)
        self.assertFalse(frame.is_ack)

    def test_two_frames_back_to_back(self):
        a = make_data_frame(SYNTH_KEY, 0x0001, b"A" * 16, sequence=1)
        b = make_data_frame(SYNTH_KEY, 0x0002, b"B" * 32, sequence=2)
        frames, consumed = parse_frames(a + b)
        self.assertEqual(consumed, len(a) + len(b))
        self.assertEqual([f.sequence for f in frames], [1, 2])

    def test_body_containing_magic_does_not_confuse_boundary(self):
        """body 内出现 magic 字节时必须按 hdr_len/body_len 跳帧，而非重新同步。"""
        a = make_data_frame(SYNTH_KEY, 0x0001, MAGIC + b"\x00" * 16, sequence=1)
        b = make_data_frame(SYNTH_KEY, 0x0002, b"B" * 16, sequence=2)
        frames, _consumed = parse_frames(a + b)
        self.assertEqual(len(frames), 2)
        # body 为密文：s2c 明文 26B 头 + 18B 载荷 = 44，补 trailer 20 → 64（16 对齐）
        self.assertEqual(len(frames[0].body), 64)
        self.assertEqual(frames[1].sequence, 2)

    def test_garbage_prefix_resync(self):
        frame = make_data_frame(SYNTH_KEY, 0x0001, b"A" * 16, sequence=1)
        frames, consumed = parse_frames(b"\x00garbage" + frame)
        self.assertEqual(len(frames), 1)
        self.assertEqual(consumed, 8 + len(frame))

    def test_partial_frame_kept_for_next_feed(self):
        frame = make_data_frame(SYNTH_KEY, 0x0001, b"A" * 16, sequence=1)
        cut = 5
        head_frames, head_consumed = parse_frames(frame[:cut])
        self.assertEqual(head_frames, [])
        self.assertEqual(head_consumed, 0)
        frames, consumed = parse_frames(frame)  # 补齐后完整解析
        self.assertEqual(len(frames), 1)
        self.assertEqual(consumed, len(frame))

    def test_no_magic_tail_kept_minimal(self):
        """无 magic 的纯垃圾：只保留可能被截断的帧头尾部，其余丢弃。"""
        garbage = bytes(range(1, 100))  # 保证不含 MAGIC 的非零数据
        self.assertNotIn(MAGIC_INT.to_bytes(2, "big"), [garbage[i : i + 2] for i in range(len(garbage) - 1)])
        _frames, consumed = parse_frames(garbage)
        self.assertLessEqual(consumed, len(garbage))
        self.assertGreaterEqual(consumed, len(garbage) - (FIXED_HEAD_LEN - 1))


class FrameStreamTest(unittest.TestCase):
    def test_byte_by_byte_feed(self):
        raw = make_data_frame(SYNTH_KEY, 0x0001, b"A" * 32, sequence=1) + make_data_frame(
            SYNTH_KEY, 0x0002, b"B" * 16, sequence=2
        )
        stream = FrameStream()
        collected: list = []
        for i in range(len(raw)):
            collected.extend(stream.feed(raw[i : i + 1]))
        self.assertEqual(len(collected), 2)
        self.assertEqual([f.sequence for f in collected], [1, 2])

    def test_oversized_total_rejected_as_garbage(self):
        """hdr_len/body_len 指向超 4MB 的组合应被视为假 magic 跳过。"""
        bad = bytearray(MAGIC)
        bad += (0x000B).to_bytes(2, "big") + (0x000B).to_bytes(2, "big")
        bad += (0x4013).to_bytes(2, "big") + b"\x00"
        bad += (1).to_bytes(4, "big")
        bad += (5 * 1024 * 1024).to_bytes(4, "big")  # hdr_len 超上限
        bad += (0).to_bytes(4, "big")
        frames, _consumed = parse_frames(bytes(bad) + b"\x33\x66junkjunkjunkjunk")
        self.assertEqual(frames, [])


if __name__ == "__main__":
    unittest.main()
