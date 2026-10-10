"""wire 级 protobuf 解码测试。"""

import unittest

from spritelens.protocol import wire
from tests._synth import make_protobuf_payload, make_varint


class WireTest(unittest.TestCase):
    def test_mixed_fields(self):
        fields = wire.decode_wire(make_protobuf_payload())
        self.assertEqual(len(fields), 3)
        self.assertEqual(fields[0].no, 1)
        self.assertEqual(fields[0].value, 850)
        self.assertEqual(fields[1].no, 2)
        self.assertEqual(fields[1].text, "hello")
        self.assertEqual(fields[2].no, 3)
        self.assertIsNotNone(fields[2].children)
        self.assertEqual(fields[2].children[0].no, 1)
        self.assertEqual(fields[2].children[0].value, 7)

    def test_multibyte_varint(self):
        payload = make_varint((5 << 3) | 0) + make_varint(300)
        fields = wire.decode_wire(payload)
        self.assertEqual(fields[0].value, 300)

    def test_truncated_field_stops_gracefully(self):
        payload = make_varint((1 << 3) | 0) + make_varint(5) + make_varint((2 << 3) | 2) + make_varint(10) + b"abc"
        fields = wire.decode_wire(payload)
        self.assertEqual(len(fields), 1)  # 第二个字段声明 10 字节只到 3 字节：丢弃

    def test_field_zero_stops(self):
        payload = make_varint(0) + b"\x99" * 8
        fields = wire.decode_wire(payload)
        self.assertEqual(fields, ())

    def test_fixed32_fixed64(self):
        payload = (
            make_varint((1 << 3) | 5) + b"\x01\x02\x03\x04"
            + make_varint((2 << 3) | 1) + b"\x05" * 8
        )
        fields = wire.decode_wire(payload)
        self.assertEqual(fields[0].wire_type, wire.WIRE_FIXED32)
        self.assertEqual(fields[0].value, 0x04030201)
        self.assertEqual(fields[1].wire_type, wire.WIRE_FIXED64)
        self.assertEqual(fields[1].value, 0x0505050505050505)

    def test_binary_non_message_kept_as_hex(self):
        """无法按嵌套消息解析且非 utf8 的 len 字段保留原始 bytes。"""
        chunk = bytes([0x00, 0xFF, 0x00, 0xFF])  # 字段号 0 开头 → 不是合法消息
        payload = make_varint((4 << 3) | 2) + make_varint(len(chunk)) + chunk
        fields = wire.decode_wire(payload)
        self.assertEqual(len(fields), 1)
        self.assertIsNone(fields[0].children)
        self.assertIsNone(fields[0].text)
        self.assertEqual(fields[0].value, chunk)


if __name__ == "__main__":
    unittest.main()
