"""内层消息拆分测试：tsf4g trailer 剥离、s2c 锚点、c2s 偏移。"""

import unittest

from spritelens.protocol.records import Direction, split_record, split_tsf4g_trailer
from tests._synth import make_data_frame
from spritelens.protocol.crypto import decrypt_data_body
from spritelens.protocol.frames import parse_frames
from tests._synth import SYNTH_KEY


def decrypt_single_s2c(opcode: int, payload: bytes) -> bytes:
    """借助合成帧走一遍「帧 → 解密」拿到明文，再针对拆分函数做断言。"""
    raw = make_data_frame(SYNTH_KEY, opcode, payload, direction="s2c", seq=0x12345678)
    frames, _consumed = parse_frames(raw)
    (frame,) = frames
    return decrypt_data_body(SYNTH_KEY, frame.body)


class TrailerTest(unittest.TestCase):
    def test_strip_valid_trailer(self):
        inner = b"\x00" * 10
        plain = inner + os_urandom_trailer(len(inner))
        body, trailer_len = split_tsf4g_trailer(plain)
        self.assertEqual(body, inner)
        self.assertGreaterEqual(trailer_len, 6)

    def test_no_trailer_passthrough(self):
        data = b"\x00" * 16
        body, trailer_len = split_tsf4g_trailer(data)
        self.assertEqual(body, data)
        self.assertEqual(trailer_len, 0)

    def test_bad_marker_passthrough(self):
        data = b"\x00" * 10 + b"nope!" + bytes([11])
        body, trailer_len = split_tsf4g_trailer(data)
        self.assertEqual(body, data)
        self.assertEqual(trailer_len, 0)


def os_urandom_trailer(plain_len: int) -> bytes:
    """与合成器一致的 trailer 构造（就地实现避免循环依赖）。"""
    import os

    rem = plain_len % 16
    trailer_len = 16 - rem if rem <= 10 else 32 - rem
    return os.urandom(trailer_len - 6) + b"tsf4g" + bytes([trailer_len])


class SplitRecordTest(unittest.TestCase):
    def test_s2c_split(self):
        payload = b"\x01\x02\x03"
        plain = decrypt_single_s2c(0x1316, payload)
        record = split_record(plain, Direction.S2C)
        self.assertIsNotNone(record)
        self.assertEqual(record.opcode, 0x1316)
        # 实测结构头无独立 seq 字段（Record.seq 恒 0）
        self.assertEqual(record.seq, 0)
        self.assertEqual(record.payload, payload)

    def test_s2c_bad_anchor_rejected(self):
        bad = b"\x00\x00" + (0x0001).to_bytes(2, "big") + b"\x00\x00" + b"\x00" * 4 + b"xx"
        self.assertIsNone(split_record(bad, Direction.S2C))

    def test_c2s_struct_head_from_real_capture(self):
        """真实抓包样本（18:20 会话 seq4 登录大包）按 32 字节结构头解析。"""
        real_plain = bytes.fromhex(
            "00000004 55aa0000 0742 0000 00000001 211fd530 23ef 0101 0108 0000 0001 1a84".replace(" ", "")
        )
        record = split_record(real_plain, Direction.C2S)
        self.assertIsNotNone(record)
        self.assertEqual(record.opcode, 0x0101)  # ZoneLoginReq
        # 样本 32B = 30B 头 + 2B payload 开头（无 trailer 部分）
        self.assertEqual(len(record.payload), 2)
        self.assertEqual(record.payload, b"\x1a\x84")

    def test_c2s_short_head_rejected(self):
        """旧经验布局（opcode@6）在真实样本上必须失效（历史 bug 的回归防护）。"""
        inner = b"\x00" * 6 + (0x0101).to_bytes(2, "big") + b"\x00" * 6 + b"body"
        # 没有 32 字节结构特征 → c2s 直接返回 None
        self.assertIsNone(split_record(inner, Direction.C2S))

    def test_s2c_struct_head_from_real_capture(self):
        """真实 s2c 样本（活动响应 0x186A）：opcode@[18:20]，payload 从 26 起。"""
        real_plain = bytes.fromhex(
            "00000000 001e 060b02da 00000000 00000000 186a 55aa 00000000 0a020800 5b6e07ce".replace(" ", "")
        )
        record = split_record(real_plain, Direction.S2C)
        self.assertIsNotNone(record)
        self.assertEqual(record.opcode, 0x186A)
        self.assertTrue(record.payload.startswith(b"\x0a\x02\x08\x00"))  # protobuf field1 开头

    def test_too_short_returns_none(self):
        self.assertIsNone(split_record(b"\x00", Direction.S2C))
        self.assertIsNone(split_record(b"\x00" * 4, Direction.C2S))


if __name__ == "__main__":
    unittest.main()
