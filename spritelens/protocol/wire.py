"""protobuf wire 级通用解码：不依赖 schema 也能解出字段树。

线上 protobuf 只携带 字段号 + wire type，无字段名。本模块输出
"字段号树"，作为 schema 缺失或版本不匹配时的兜底视图。

容错策略：c2s 消息尾部存在变长 trailer（非 protobuf），因此解码
遇到第一个非法字段头即停，保留已解析部分而非整体失败。
"""

from __future__ import annotations

from dataclasses import dataclass

WIRE_VARINT = 0
WIRE_FIXED64 = 1
WIRE_LEN = 2
WIRE_FIXED32 = 5

_MAX_DEPTH = 8
_MAX_FIELDS = 2000
_MAX_TEXT_SHOW = 96


@dataclass(frozen=True)
class WireField:
    """一个 wire 级字段；len 字段可能带嵌套 children 或 utf8 文本。"""

    no: int
    wire_type: int
    value: int | bytes
    children: tuple["WireField", ...] | None = None
    text: str | None = None

    def display_name(self) -> str:
        return f"field_{self.no}"

    def display_value(self) -> str:
        if self.children is not None:
            return f"<{len(self.children)} 字段>"
        if isinstance(self.value, bytes):
            if self.text is not None:
                return f'"{self.text}"'
            return f"hexpkt[{len(self.value)}B]"
        return str(self.value)


def read_varint(data: bytes, off: int) -> tuple[int, int] | None:
    """读一个 varint，返回 (值, 下一偏移)；越界/超长返回 None。"""
    result = 0
    shift = 0
    while True:
        if off >= len(data) or shift > 63:
            return None
        byte = data[off]
        off += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, off
        shift += 7


def _looks_like_message(data: bytes, depth: int) -> tuple[WireField, ...] | None:
    """尝试把 bytes 解析为嵌套消息。

    判定从严：全部字段可解析且恰好消费到末尾。随机二进制与短文本
    （如 "hello"）常能骗过前几个字段头，但几乎无法完整消费，
    以「消费到末尾」为硬条件可显著降低误判。
    """
    fields, consumed = _decode_fields(data, depth)
    if not fields or consumed != len(data):
        return None
    return fields


def _decode_fields(data: bytes, depth: int) -> tuple[tuple[WireField, ...], int]:
    fields: list[WireField] = []
    off = 0
    size = len(data)
    while off < size:
        if len(fields) >= _MAX_FIELDS:
            break
        head = read_varint(data, off)
        if head is None:
            break
        tag, off = head
        field_no = tag >> 3
        wire_type = tag & 0x07
        if field_no == 0:
            break  # 字段号 0 非法：视为进入 trailer
        if wire_type == WIRE_VARINT:
            value = read_varint(data, off)
            if value is None:
                break
            val, off = value
            fields.append(WireField(no=field_no, wire_type=wire_type, value=val))
        elif wire_type == WIRE_FIXED64:
            if off + 8 > size:
                break
            fields.append(
                WireField(no=field_no, wire_type=wire_type, value=int.from_bytes(data[off : off + 8], "little"))
            )
            off += 8
        elif wire_type == WIRE_FIXED32:
            if off + 4 > size:
                break
            fields.append(
                WireField(no=field_no, wire_type=wire_type, value=int.from_bytes(data[off : off + 4], "little"))
            )
            off += 4
        elif wire_type == WIRE_LEN:
            length = read_varint(data, off)
            if length is None:
                break
            ln, off = length
            if off + ln > size:
                break
            chunk = data[off : off + ln]
            off += ln
            children = None
            text = None
            if depth > 0:
                nested = _looks_like_message(chunk, depth - 1)
                if nested is not None:
                    children = nested
                else:
                    try:
                        decoded = chunk.decode("utf-8")
                        if decoded.isprintable() or "\n" in decoded:
                            text = decoded[:_MAX_TEXT_SHOW]
                    except UnicodeDecodeError:
                        pass
            fields.append(
                WireField(no=field_no, wire_type=wire_type, value=chunk, children=children, text=text)
            )
        else:
            break  # wire type 3/4（废弃组）或损坏数据：停在解析异常点
    return tuple(fields), off


def decode_wire(data: bytes, *, depth: int = _MAX_DEPTH) -> tuple[WireField, ...]:
    """解码为字段树；遇到非 protobuf 尾部（trailer）时截断保留已解析部分。

    顶层不要求消费到末尾：c2s 消息尾部存在变长 trailer（非 protobuf）。
    """
    fields, _off = _decode_fields(data, depth)
    return fields
