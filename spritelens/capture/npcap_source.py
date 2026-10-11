"""Npcap 旁听接入：scapy AsyncSniffer + BPF 端口过滤 + 自研流重组。

scapy 采用延迟导入：顶层 import 会在 Windows 上触发 npcap 环境探测，
拖慢无抓包场景（如 --smoke-test、离线回放）的启动，且探测失败即抛错。

抓包回调只做流分类与重组（微秒级），重组产出的 StreamChunk 进入有界
队列由工作线程异步投递——登录/进场景时服务器会突发数百 KB 下行，若在
嗅探线程内同步做解密解码，libpcap 内核缓冲会溢出导致整批丢包。

流关闭（FIN/RST）同样经该队列保序投递（FlowClosed），嗅探线程不直接
触碰协议层：既保证「残余数据先于关闭处理」，也让抓包线程不等待协议锁。
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass

from spritelens.capture.base import SourceCallback, SourceError, SourceEventCallback, StreamChunk
from spritelens.capture.reassembly import TcpStreamReassembler
from spritelens.logs import get_logger
from spritelens.protocol.records import Direction

logger = get_logger("npcap_source")

# libpcap 内核缓冲（字节）。默认值在秒级大流量突发下会溢出丢包。
PCAP_BUFFER_BYTES = 32 * 1024 * 1024
# chunk 队列上限：超出说明下游持续过载，丢新块保嗅探（计数上报）。
CHUNK_QUEUE_MAX = 4096
# 流空闲淘汰：拔网线/进程被杀等异常断连收不到 FIN/RST，重组器必须按
# 空闲时间回收（长时间挂机时流表与重组缓冲的内存边界）。
FLOW_IDLE_SECONDS = 30 * 60
_FLOW_SWEEP_INTERVAL = 60.0


@dataclass(frozen=True)
class FlowClosed:
    """流关闭事件：经 chunk 队列保序投递（见 _announce_flow_closed）。

    FIN/RST 到达时此前产生的 chunk 可能仍在队列里，直接回调会让协议层
    先清会话密钥、再处理残余数据（复现过 DATA 解码失败 key_miss）。
    """

    flow_id: str


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
        self._flow_lock = threading.Lock()  # 保护流表（嗅探线程写、UI 线程读计数）
        self._flow_seen: dict[str, float] = {}
        self._last_flow_sweep = 0.0
        self._retired_dropped_segments = 0
        self._flow_count = 0
        self._queue: queue.Queue[StreamChunk | FlowClosed | None] = queue.Queue(maxsize=CHUNK_QUEUE_MAX)
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
        # 停止后不再有 FIN/RST 事件，流表与重组缓冲在这里统一释放
        with self._flow_lock:
            self._retired_dropped_segments += self._live_dropped_segments()
            self._flows.clear()
            self._flow_seen.clear()
            self._flow_count = 0
        self._on_event("stopped", "")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def flow_count(self) -> int:
        return self._flow_count

    @property
    def dropped_segments(self) -> int:
        """重组层丢弃的乱序段总数（pending 超限 + 已关闭流的历史累计）。"""
        with self._flow_lock:
            return self._retired_dropped_segments + self._live_dropped_segments()

    def _live_dropped_segments(self) -> int:
        return sum(r.dropped_segments for flows in self._flows.values() for r in flows.values())

    def _drop_flow(self, flow_id: str) -> int:
        """移除流及其重组器；返回被移除的重组器个数（维护 flow_count）。"""
        with self._flow_lock:
            flows = self._flows.pop(flow_id, None)
            self._flow_seen.pop(flow_id, None)
            if not flows:
                return 0
            self._retired_dropped_segments += sum(r.dropped_segments for r in flows.values())
            self._flow_count = max(0, self._flow_count - len(flows))
            return len(flows)

    def _sweep_flows(self, now: float) -> None:
        """淘汰长时间无活动的流（异常断连时收不到 FIN/RST）。"""
        with self._flow_lock:
            stale = [fid for fid, seen in self._flow_seen.items() if now - seen > FLOW_IDLE_SECONDS]
        for flow_id in stale:
            logger.info("流空闲超时，释放重组器: %s", flow_id)
            self._drop_flow(flow_id)
            self._announce_flow_closed(flow_id)

    def _announce_flow_closed(self, flow_id: str) -> None:
        """把关闭事件排入 chunk 队列，由投递线程按序处理后回调。

        顺序保证：关闭事件总排在「此前已入队的数据」之后，协议层因此
        先解完残余数据、再释放会话（反之会清掉密钥导致 key_miss）。
        满载时丢最旧一个数据块腾位——关闭事件必须按时送达，否则会话
        状态泄漏；但绝不丢停止哨兵（None），它关系投递线程能否退出。
        """
        event = FlowClosed(flow_id=flow_id)
        try:
            self._queue.put_nowait(event)
            return
        except queue.Full:
            pass
        try:
            victim = self._queue.get_nowait()
        except queue.Empty:
            victim = None  # 竞态：队列已被腾空，直接重试投递
        else:
            if victim is None:
                try:
                    self._queue.put_nowait(victim)  # 放回哨兵（刚取出必然有位）
                except queue.Full:
                    pass
                logger.warning("流关闭事件未能入队（队列持续满载）: %s", flow_id)
                return
            if not isinstance(victim, FlowClosed):
                self.dropped_chunks += 1  # 腾位丢弃的数据块计入过载统计
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            logger.warning("流关闭事件未能入队（队列持续满载）: %s", flow_id)

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
                self._drop_flow(flow_id)
                self._announce_flow_closed(flow_id)
                return
            if not payload:
                return
            now = time.monotonic()
            with self._flow_lock:
                self._flow_seen[flow_id] = now
                sweep_due = now - self._last_flow_sweep >= _FLOW_SWEEP_INTERVAL
                if sweep_due:
                    self._last_flow_sweep = now
            if sweep_due:
                self._sweep_flows(now)
            with self._flow_lock:
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
        """工作线程：按入队顺序投递 chunk 与流关闭事件（保序是语义要求）。

        关闭事件必须由本线程处理：若在嗅探线程直接回调，协议层会越过
        队列里尚未处理的残余数据先释放会话（复现过 key_miss 与关闭后
        会话被重新建出的场景）；经本线程后顺序天然正确，且嗅探线程
        不再触碰协议层锁。
        """
        while True:
            item = self._queue.get()
            if item is None:
                return
            try:
                if isinstance(item, FlowClosed):
                    self._on_event("flow_closed", item.flow_id)
                else:
                    self._on_chunk(item)
            except Exception:  # noqa: BLE001 - 下游缺陷不反噬抓包线程
                logger.exception("投递流数据失败")

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
