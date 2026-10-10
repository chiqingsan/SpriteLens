"""接入层抽象：CaptureSource 协议与流数据类型。

解绑关键：上层只认识「按方向交付的有序字节流 + 会话标识」，
不感知流量来自网卡旁听（Npcap）还是代理中间人（未来 MITM）。
TCP 重组属于接入层职责——Npcap 旁听需要自行重组，MITM 的
socket 直读天然有序，接入层各自消化这一差异。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from spritelens.protocol.records import Direction


@dataclass(frozen=True)
class StreamChunk:
    """一段会话方向上的连续新字节（已按 TCP seq 重组或 socket 直读）。"""

    session_id: str
    direction: Direction
    data: bytes
    first_seq: int


SourceCallback = Callable[[StreamChunk], None]
SourceEventCallback = Callable[[str, str], None]  # (kind, detail)


class CaptureSource(Protocol):
    """抓包手段协议：未来 MITM 代理实现同一接口即可整体替换。"""

    name: str

    def start(self) -> None: ...

    def stop(self) -> None: ...

    @property
    def is_running(self) -> bool: ...


class SourceError(RuntimeError):
    """接入层启动/运行失败（缺驱动、无权限等），由 UI 层转述给用户。"""
