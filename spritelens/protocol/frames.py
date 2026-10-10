"""GCP（TGCP BE21）帧切分：21 字节大端头 + 变长 body。

线上格式（经真实流量逐字节验证）：
    magic(0x3366,2) head_ver(2) body_ver(2) command(2) flag(1)
    sequence(4) hdr_len(4) body_len(4)   -- 全部大端
    HEAD.extend = [21, hdr_len)，BODY = [hdr_len, hdr_len+body_len)

设计要点：
- 流式解析：调用方持续 feed 抓包重组后的字节流，不足一帧时留在缓冲。
- 假 magic 防护：magic 命中但头部校验失败时按字节前移重新同步，
  辅以 cmd 范围 / 长度上限校验，避免把 body 里的巧合字节当帧头。
"""

from __future__ import annotations

from dataclasses import dataclass

MAGIC = b"\x33\x66"
MAGIC_INT = 0x3366
FIXED_HEAD_LEN = 21
MAX_HEAD_EXTRA = 4096
MAX_TOTAL_LEN = 4 * 1024 * 1024
# 合法 command 观测范围为普通报文段，越界基本可判定为假 magic
_MIN_CMD = 0x0001
_MAX_CMD = 0x8000

CMD_SYN = 0x1001
CMD_ACK = 0x1002
CMD_DATA = 0x4013


@dataclass(frozen=True)
class GcpFrame:
    """一帧完整 GCP 报文（方向由持有会话的调用方标注）。"""

    command: int
    flag: int
    sequence: int
    header_extra: bytes
    body: bytes

    @property
    def is_data(self) -> bool:
        return self.command == CMD_DATA

    @property
    def is_ack(self) -> bool:
        return self.command == CMD_ACK


def _header_valid(buf: bytes, off: int) -> bool:
    if off + FIXED_HEAD_LEN > len(buf):
        return False
    command = int.from_bytes(buf[off + 6 : off + 8], "big")
    hdr_len = int.from_bytes(buf[off + 13 : off + 17], "big")
    body_len = int.from_bytes(buf[off + 17 : off + 21], "big")
    if not (_MIN_CMD <= command <= _MAX_CMD):
        return False
    if hdr_len < FIXED_HEAD_LEN or hdr_len - FIXED_HEAD_LEN > MAX_HEAD_EXTRA:
        return False
    if hdr_len + body_len > MAX_TOTAL_LEN:
        return False
    return True


def parse_frames(buf: bytes) -> tuple[list[GcpFrame], int]:
    """从缓冲解析所有完整帧，返回 (帧列表, 已消费字节数)。

    假 magic 时跳到下一个 magic 重新同步；尾部不足一帧的数据留在
    返回的已消费偏移之后，由调用方保留重试。
    """
    frames: list[GcpFrame] = []
    off = 0
    size = len(buf)
    while off + FIXED_HEAD_LEN <= size:
        if buf[off : off + 2] != MAGIC:
            nxt = buf.find(MAGIC, off + 1)
            if nxt < 0:
                # 缓冲里已无 magic：只有尾部一小段可能是被截断的帧头，
                # 其余全部丢弃（保守只保留最后 FIXED_HEAD_LEN-1 字节）
                keep = min(size - off, FIXED_HEAD_LEN - 1)
                return frames, size - keep
            off = nxt
            continue
        if not _header_valid(buf, off):
            off += 2
            continue
        hdr_len = int.from_bytes(buf[off + 13 : off + 17], "big")
        body_len = int.from_bytes(buf[off + 17 : off + 21], "big")
        total = hdr_len + body_len
        if off + total > size:
            break  # 帧未收全，等待后续数据
        frames.append(
            GcpFrame(
                command=int.from_bytes(buf[off + 6 : off + 8], "big"),
                flag=buf[off + 8],
                sequence=int.from_bytes(buf[off + 9 : off + 13], "big"),
                header_extra=bytes(buf[off + FIXED_HEAD_LEN : off + hdr_len]),
                body=bytes(buf[off + hdr_len : off + total]),
            )
        )
        off += total
    return frames, off


class FrameStream:
    """单方向流式帧解析器：feed 追加数据并吐出完整帧。"""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[GcpFrame]:
        self._buffer.extend(data)
        frames, consumed = parse_frames(bytes(self._buffer))
        if consumed:
            del self._buffer[:consumed]
        return frames
