"""DATA 帧解密后明文的内层消息拆分：tsf4g trailer 剥离 + opcode 提取。

内层头有两种实测布局（按内容自适应判定，不依赖方向）：

- 30 字节结构头（c2s 实测，判据 [12:16]==00 00 00 01）：
  [0:4]=counter1(=gcp seq)  [4:6]=0x55aa  [22:24]=opcode
  [24:26]=常量  [28:32]=counter2 区域（部分计入 payload 侧）
  payload 从 30 起
- 短头（社区经验布局，s2c 待真实样本校验）：
  opcode@[2:4]，[4:6]=0x55aa 锚点，seq@[6:10]，payload 从 10 起
- s2c 26 字节结构头（实测）：[18:20]=opcode、[20:22]=0x55aa、payload 从 26 起

解析失败返回 None，由调用方计数（c2s 偶发非标准包属正常现象）。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

S2C_OPCODE_OFFSET = 2
S2C_ANCHOR_OFFSET = 4
S2C_SEQ_OFFSET = 6
S2C_PAYLOAD_OFFSET = 10

STRUCT_OPCODE_OFFSET = 22
# c2s 结构头实测为 30 字节（[30:] 即 protobuf payload；开源实现注释同为 30B）。
# 早期误定为 32——把 payload 前 2 字节当成了头，导致 trailer 剥离后 len<32 全部漏判。
STRUCT_PAYLOAD_OFFSET = 30
STRUCT_CONST1_OFFSET = 12
# 32 字节结构头（c2s）的判据：[12:16] 恒为 00 00 00 01（c2s 真实样本全部命中）
STRUCT_CONST1 = b"\x00\x00\x00\x01"
ANCHOR = b"\x55\xaa"
ANCHOR_OFFSET = 4

# s2c 结构头（实测样本：背包 0x013D/0x013F、活动 0x186A、心跳 0x0414）
S2C_STRUCT_OPCODE_OFFSET = 18
S2C_STRUCT_ANCHOR_OFFSET = 20
S2C_STRUCT_PAYLOAD_OFFSET = 26
# 判据：[10:18] 全零 且 [20:22]==0x55aa（短头布局下 [12:20] 是 protobuf 内容，不可能恒零）
S2C_STRUCT_ZEROS_OFFSET = 10
S2C_STRUCT_ZEROS_LEN = 8

TSF4G_MARKER = b"tsf4g"
TSF4G_MIN_TRAILER = 6
TSF4G_MAX_TRAILER = 22


class Direction(StrEnum):
    C2S = "c2s"
    S2C = "s2c"


@dataclass(frozen=True)
class Record:
    """一条应用层业务消息。"""

    direction: Direction
    opcode: int
    payload: bytes
    seq: int


def split_tsf4g_trailer(plaintext: bytes) -> tuple[bytes, int]:
    """剥离尾部 tsf4g trailer（随机填充 + "tsf4g" 标记 + 长度字节）。

    无有效 trailer 时按无 trailer 处理（原样返回），保持宽容。
    """
    if len(plaintext) < TSF4G_MIN_TRAILER + 1:
        return plaintext, 0
    trailer_len = plaintext[-1]
    if not (TSF4G_MIN_TRAILER <= trailer_len <= TSF4G_MAX_TRAILER):
        return plaintext, 0
    if trailer_len > len(plaintext):
        return plaintext, 0
    trailer = plaintext[-trailer_len:]
    if trailer[-6:-1] != TSF4G_MARKER:
        return plaintext, 0
    return plaintext[:-trailer_len], trailer_len


def _split_struct_head(body: bytes) -> Record | None:
    """32 字节结构头布局：opcode@[22:24]，payload 从 32 起。"""
    if len(body) < STRUCT_PAYLOAD_OFFSET:
        return None
    if body[STRUCT_CONST1_OFFSET : STRUCT_CONST1_OFFSET + 4] != STRUCT_CONST1:
        return None
    if body[ANCHOR_OFFSET : ANCHOR_OFFSET + 2] != ANCHOR:
        return None
    return Record(
        direction=Direction.C2S,
        opcode=int.from_bytes(body[STRUCT_OPCODE_OFFSET : STRUCT_OPCODE_OFFSET + 2], "big"),
        seq=0,
        payload=bytes(body[STRUCT_PAYLOAD_OFFSET:]),
    )


def _split_short_head(body: bytes, direction: Direction) -> Record | None:
    """社区经验短头布局（s2c）：opcode@[2:4]，0x55aa 锚点@[4:6]。"""
    if len(body) < S2C_PAYLOAD_OFFSET:
        return None
    if body[S2C_ANCHOR_OFFSET : S2C_ANCHOR_OFFSET + 2] != ANCHOR:
        return None
    return Record(
        direction=direction,
        opcode=int.from_bytes(body[S2C_OPCODE_OFFSET : S2C_OPCODE_OFFSET + 2], "big"),
        seq=int.from_bytes(body[S2C_SEQ_OFFSET : S2C_SEQ_OFFSET + 4], "big"),
        payload=bytes(body[S2C_PAYLOAD_OFFSET:]),
    )


def _split_s2c_struct(body: bytes, direction: Direction) -> Record | None:
    """s2c 结构头（实测）：opcode@[18:20]，锚点 55aa@[20:22]，payload 从 26 起。"""
    if len(body) < S2C_STRUCT_PAYLOAD_OFFSET:
        return None
    if body[S2C_STRUCT_ANCHOR_OFFSET : S2C_STRUCT_ANCHOR_OFFSET + 2] != ANCHOR:
        return None
    if any(body[S2C_STRUCT_ZEROS_OFFSET : S2C_STRUCT_ZEROS_OFFSET + S2C_STRUCT_ZEROS_LEN]):
        return None
    return Record(
        direction=direction,
        opcode=int.from_bytes(body[S2C_STRUCT_OPCODE_OFFSET : S2C_STRUCT_OPCODE_OFFSET + 2], "big"),
        seq=0,
        payload=bytes(body[S2C_STRUCT_PAYLOAD_OFFSET:]),
    )


def split_record(plaintext: bytes, direction: Direction) -> Record | None:
    """从解密明文提取一条业务消息；格式不符返回 None。

    判定顺序（均为实测布局，按内容自适应）：
    1. 32 字节结构头（c2s，判据 [12:16]==00000001）
    2. s2c 26 字节结构头（判据 [10:20] 全零 + [20:22]==55aa）
    3. 短头经验布局回退（s2c）
    """
    body, _trailer_len = split_tsf4g_trailer(plaintext)
    struct = _split_struct_head(body)
    if struct is not None:
        return Record(direction=direction, opcode=struct.opcode, payload=struct.payload, seq=struct.seq)
    if direction is Direction.S2C:
        s2c_struct = _split_s2c_struct(body, direction)
        if s2c_struct is not None:
            return s2c_struct
        return _split_short_head(body, direction)
    return None
