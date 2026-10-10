"""合成帧生成器：协议层测试与录制回放共用的离线数据源。

按真实线上格式反向构造合法 GCP 流，使「key 捕获 → 解密 → 拆分 → 解码」
全链路测试完全不依赖游戏客户端。
"""

from __future__ import annotations

import random

from spritelens.protocol.crypto import encrypt_data_body
from spritelens.protocol.frames import CMD_ACK, CMD_DATA, FIXED_HEAD_LEN, MAGIC

SYNTH_KEY = b"0123456789abcdef"


def _trailer_for(plain_len: int) -> bytes:
    """按 16 字节对齐规则构造 tsf4g trailer：伪随机填充 + 标记 + 长度字节。

    用确定种子的伪随机而非 os.urandom：测试必须逐字节可复现，
    否则密文中的巧合字节会让失败时隐时现无法定位。
    """
    rem = plain_len % 16
    trailer_len = 16 - rem if rem <= 10 else 32 - rem
    filler = random.Random(plain_len).randbytes(trailer_len - 6)
    return filler + b"tsf4g" + bytes([trailer_len])


def encode_frame(command: int, flag: int, sequence: int, header_extra: bytes, body: bytes) -> bytes:
    """组装一帧完整 GCP 报文（21 字节头 + extend + body）。"""
    hdr_len = FIXED_HEAD_LEN + len(header_extra)
    head = (
        MAGIC
        + (0x000B).to_bytes(2, "big")
        + (0x000B).to_bytes(2, "big")
        + command.to_bytes(2, "big")
        + bytes([flag])
        + sequence.to_bytes(4, "big")
        + hdr_len.to_bytes(4, "big")
        + len(body).to_bytes(4, "big")
    )
    return head + header_extra + body


def make_ack_frame(key: bytes, sequence: int = 1) -> bytes:
    """构造 0x1002 ACK：HEAD.extend[2:18] 明文携带 16 字节会话密钥。"""
    return encode_frame(CMD_ACK, flag=0x01, sequence=sequence, header_extra=b"\x00\x00" + key, body=b"")


def _build_inner(direction: str, opcode: int, payload: bytes, sequence: int) -> bytes:
    """拼内层头 + payload（不含 trailer）。"""
    if direction == "s2c":
        # 实测 s2c 26 字节结构头：opcode@[18:20]、55aa@[20:22]、payload 从 26 起
        return (
            b"\x00\x00"
            + len(payload).to_bytes(4, "big")
            + b"\x06\x0b\x02\xda"
            + b"\x00" * 8
            + opcode.to_bytes(2, "big")
            + b"\x55\xaa"
            + b"\x00\x00\x00\x00"
            + payload
        )
    counter2 = sequence  # 结构头里的连接内递增计数，合成时复用 seq 语义
    return (
        sequence.to_bytes(4, "big")
        + b"\x55\xaa\x00\x00"
        + len(payload).to_bytes(2, "big")
        + b"\x00\x00"
        + b"\x00\x00\x00\x01"
        + b"\x21\x1f\xd5\x30"
        + b"\x23\xef"
        + opcode.to_bytes(2, "big")
        + b"\x01\x08"
        + b"\x00\x00"
        + counter2.to_bytes(4, "big")
        + payload
    )


def make_data_frame(
    key: bytes,
    opcode: int,
    payload: bytes,
    sequence: int = 1,
    *,
    direction: str = "s2c",
    seq: int = 0,
) -> bytes:
    """构造 0x4013 DATA：按方向拼内层头 + trailer，再 AES-CBC（固定 IV）加密。

    c2s 用实测的 32 字节结构头（counter1=seq、0x55aa@4、00000001@12、
    opcode@22、counter2@28）；s2c 用社区经验短头（opcode@2、0x55aa@4）。
    """
    inner = _build_inner(direction, opcode, payload, sequence)
    plain = inner + _trailer_for(len(inner))
    body = encrypt_data_body(key, plain)
    flag = 0x01 if direction == "s2c" else 0x00
    return encode_frame(CMD_DATA, flag=flag, sequence=sequence, header_extra=b"\x00\x00\x00\x00", body=body)


def make_data_frame_ivct(
    key: bytes,
    opcode: int,
    payload: bytes,
    sequence: int = 1,
    *,
    direction: str = "s2c",
) -> bytes:
    """构造自带 IV 变体的 0x4013 DATA：body = IV(16) + 密文。

    实测见于 c2s 短心跳帧（rocom-helper 同款解法）；IV 用确定种子，
    保证测试逐字节可复现。
    """
    inner = _build_inner(direction, opcode, payload, sequence)
    plain = inner + _trailer_for(len(inner))
    from Crypto.Cipher import AES

    iv = random.Random(f"ivct-{sequence}-{opcode}").randbytes(16)
    body = iv + AES.new(key, AES.MODE_CBC, iv).encrypt(plain)
    flag = 0x01 if direction == "s2c" else 0x00
    return encode_frame(CMD_DATA, flag=flag, sequence=sequence, header_extra=b"\x00\x00\x00\x00", body=body)


def make_varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def make_protobuf_payload() -> bytes:
    """合成一条 protobuf：field1 varint=850, field2 文本, field3 嵌套{1:7}。"""
    nested = make_varint((1 << 3) | 0) + make_varint(7)
    return (
        make_varint((1 << 3) | 0)
        + make_varint(850)
        + make_varint((2 << 3) | 2)
        + make_varint(len(b"hello"))
        + b"hello"
        + make_varint((3 << 3) | 2)
        + make_varint(len(nested))
        + nested
    )
