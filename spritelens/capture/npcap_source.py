"""Npcap 旁听接入：scapy AsyncSniffer + BPF 端口过滤 + 自研流重组。

scapy 采用延迟导入：顶层 import 会在 Windows 上触发 npcap 环境探测，
拖慢无抓包场景（如 --smoke-test、离线回放）的启动，且探测失败即抛错。

抓包回调只做流分类与重组（微秒级），重组产出的 StreamChunk 进入有界
队列由工作线程异步投递——登录/进场景时服务器会突发数百 KB 下行，若在
嗅探线程内同步做解密解码，libpcap 内核缓冲会溢出导致整批丢包。
"""

from __future__ import annotations

import queue
import threading
import time

from spritelens.capture.base import SourceCallback, SourceError, SourceEventCallback, StreamChunk
from spritelens.capture.reassembly import TcpStreamReassembler
from spritelens.logs import get_logger
from spritelens.protocol.records import Direction

logger = get_logger("npcap_source")

# libpcap 内核缓冲（字节）。默认值在秒级大流量突发下会溢出丢包。
PCAP_BUFFER_BYTES = 32 * 1024 * 1024
# chunk 队列上限：超出说明下游持续过载，丢新块保嗅探（计数上报）。
CHUNK_QUEUE_MAX = 4096


class NpcapCaptureSource:
    """网卡旁听抓包源：只读，不注入不修改任何报文。"""

    name = "npcap"

    def __init__(
        self,
        port: int,
        *,
        on_chunk: SourceCallback,
        on_event: SourceEventCallback | None = None,
        iface: str | None = None,
        extra_ports: tuple[int, ...] = (),
    ) -> None:
        self._port = port
        self._extra_ports = tuple(p for p in extra_ports if p and p != port)
        self._on_chunk = on_chunk
        self._on_event = on_event or (lambda kind, detail: None)
        self._iface = iface
        self._sniffer = None
        self._running = False
        self._flows: dict[str, dict[str, TcpStreamReassembler]] = {}
        self._flow_count = 0
        self._queue: queue.Queue[StreamChunk | None] = queue.Queue(maxsize=CHUNK_QUEUE_MAX)
        self._worker: threading.Thread | None = None
        self.dropped_chunks = 0

    def _build_bpf(self) -> str:
        """BPF 过滤器：主端口 + 可选附加端口（多连接游戏的数据端口）。"""
        ports = [self._port, *self._extra_ports]
        return " or ".join(f"tcp port {p}" for p in ports)

    # -- 生命周期 ------------------------------------------------------
    def start(self) -> None:
        if self._running:
            return
        try:
            from scapy.all import AsyncSniffer  # 延迟导入，见模块 docstring
        except Exception as exc:  # noqa: BLE001 - scapy/npcap 环境问题统一转 SourceError
            raise SourceError(f"scapy/npcap 环境不可用: {exc}") from exc
        self.dropped_chunks = 0
        self._worker = threading.Thread(
            target=self._drain_queue, name="spritelens-chunk-dispatch", daemon=True
        )
        self._worker.start()
        # 新版 scapy 支持调大 libpcap 内核缓冲；旧实现不认识该参数——
        # 但 TypeError 发生在嗅探线程内（存入 .exception），无法同步捕获，
        # 只能在探活时识别并降级重建
        try:
            self._sniffer = AsyncSniffer(
                filter=self._build_bpf(),
                prn=self._handle_packet,
                store=False,
                iface=self._iface or None,
                buffer_size=PCAP_BUFFER_BYTES,
            )
            self._sniffer.start()
        except Exception as exc:  # noqa: BLE001
            raise SourceError(f"抓包启动失败（缺 Npcap 或权限不足）: {exc}") from exc
        deadline = time.monotonic() + 0.6
        while time.monotonic() < deadline:
            exc = getattr(self._sniffer, "exception", None)
            if exc is not None and isinstance(exc, TypeError) and "buffer_size" in str(exc):
                # 降级：不带 buffer_size 重建（用 libpcap 默认缓冲）
                logger.info("当前 scapy 不支持 buffer_size，降级用默认内核缓冲")
                try:
                    self._sniffer.stop()
                except Exception:  # noqa: BLE001
                    pass
                self._sniffer = AsyncSniffer(
                    filter=self._build_bpf(),
                    prn=self._handle_packet,
                    store=False,
                    iface=self._iface or None,
                )
                self._sniffer.start()
                break
            if exc is not None:
                self._running = False
                self._sniffer = None
                raise SourceError(f"抓包启动失败（Npcap 未安装或权限不足）: {exc}")
            time.sleep(0.05)
        else:
            exc = getattr(self._sniffer, "exception", None)
            if exc is not None:
                self._running = False
                self._sniffer = None
                raise SourceError(f"抓包启动失败（Npcap 未安装或权限不足）: {exc}")
        self._running = True
        self._on_event("started", self._iface or "(默认路由网卡)")

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._sniffer is not None:
            try:
                self._sniffer.stop()
            except Exception:  # noqa: BLE001 - 停止失败不影响退出
                logger.debug("sniffer 停止异常", exc_info=True)
            self._sniffer = None
        if self._worker is not None:
            self._queue.put(None)  # 哨兵：结束工作线程
            self._worker.join(timeout=5)
            self._worker = None
        self._on_event("stopped", "")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def flow_count(self) -> int:
        return self._flow_count

    # -- 抓包回调（运行于 scapy 后台线程）-----------------------------
    def _handle_packet(self, packet) -> None:
        try:
            if not packet.haslayer("TCP"):
                return
            tcp = packet["TCP"]
            try:
                ip_layer = packet["IP"] if packet.haslayer("IP") else packet["IPv6"]
            except (KeyError, IndexError):
                return
            sport, dport = int(tcp.sport), int(tcp.dport)
            flags = int(tcp.flags)
            payload = bytes(tcp.payload)
            game_ports = {self._port, *self._extra_ports}
            if dport in game_ports:
                direction = Direction.C2S
                client = (ip_layer.src, sport)
            elif sport in game_ports:
                direction = Direction.S2C
                client = (ip_layer.dst, dport)
            else:
                return
            flow_id = f"{client[0]}:{client[1]}"
            if flags & 0x01 or flags & 0x04:  # FIN / RST：会话结束
                self._on_event("flow_closed", flow_id)
                return
            if not payload:
                return
            reassembler = self._flows.get(flow_id, {}).get(direction)
            if reassembler is None:
                reassembler = TcpStreamReassembler(name=flow_id)
                self._flows.setdefault(flow_id, {})[direction] = reassembler
                self._flow_count += 1
            seq = int(tcp.seq)
            data = reassembler.feed(seq, payload)
            if data:
                chunk = StreamChunk(
                    session_id=flow_id, direction=direction, data=data, first_seq=seq
                )
                try:
                    self._queue.put_nowait(chunk)
                except queue.Full:
                    self.dropped_chunks += 1
                    if self.dropped_chunks % 100 == 1:
                        logger.warning(
                            "chunk 队列满，累计丢弃 %d 块（下游处理过载）", self.dropped_chunks
                        )
        except Exception:  # noqa: BLE001 - 抓包线程内绝不让异常外泄中断嗅探
            logger.exception("处理抓包帧失败")

    def _drain_queue(self) -> None:
        """工作线程：把重组后的 chunk 依次投递给监听管线（重活在下游）。"""
        while True:
            chunk = self._queue.get()
            if chunk is None:
                return
            try:
                self._on_chunk(chunk)
            except Exception:  # noqa: BLE001 - 下游缺陷不反噬抓包线程
                logger.exception("投递 chunk 失败")

    # -- 网卡枚举 ------------------------------------------------------
    @staticmethod
    def list_ifaces() -> list[tuple[str, str]]:
        try:
            from scapy.all import conf

            return [
                (iface.name, getattr(iface, "description", "") or "")
                for iface in conf.ifaces.values()
            ]
        except Exception as exc:  # noqa: BLE001
            raise SourceError(f"网卡枚举失败: {exc}") from exc
