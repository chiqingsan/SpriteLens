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
# 停止时等待投递线程退出的预算（S03a）：超时转存 stale 句柄而非无限等。
_WORKER_JOIN_TIMEOUT = 5.0
# sniffer.stop 的预算（D05）：scapy AsyncSniffer.stop 默认 join=True 且无
# 上限，驱动卡死时会长期占用采集命令锁；超时把句柄转 stale 留诊断。
_SNIFFER_STOP_BUDGET = 5.0


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
        # 超时未退的投递线程句柄（S03a）：句柄即所有权证据，不能在 join
        # 超时后丢弃——restart 前可诊断 is_stale_worker_active()，避免
        # 新旧投递线程并存互踩。
        self._stale_workers: list[threading.Thread] = []
        # 停止超时的嗅探器句柄（D05）：scapy stop 默认无上限 join，卡住时
        # 不能把句柄当已退出丢掉；由 has_unfinished_sniffer 暴露诊断
        self._stale_sniffers: list[object] = []
        self._sniffer_stop_threads: dict[int, threading.Thread] = {}
        self._sniffer_stop_errors: dict[int, bool] = {}
        self._worker_join_timeout = _WORKER_JOIN_TIMEOUT
        self._sniffer_stop_budget = _SNIFFER_STOP_BUDGET
        self.dropped_chunks = 0

    def _build_bpf(self) -> str:
        """BPF 过滤器：主端口 + 可选附加端口（多连接游戏的数据端口）。"""
        ports = [self._port, *self._extra_ports]
        return " or ".join(f"tcp port {p}" for p in ports)

    # -- 生命周期 ------------------------------------------------------
    def start(self) -> None:
        if self._running:
            return
        # D04：旧投递线程未退时拒绝重启——同实例共享 queue，新 worker 会
        # 抢走旧哨兵；旧回调（on_chunk）还指向同一下游，重启即两代并存
        self._reap_stale_workers()
        if self.is_stale_worker_active():
            raise SourceError("上一会话的投递线程尚未退出，暂不能重新开始采集")
        if self.has_unfinished_sniffer():
            raise SourceError("上一会话的嗅探器尚未停止，暂不能重新开始采集")
        try:
            from scapy.all import AsyncSniffer  # 延迟导入，见模块 docstring
        except Exception as exc:  # noqa: BLE001 - scapy/npcap 环境问题统一转 SourceError
            raise SourceError(f"scapy/npcap 环境不可用: {exc}") from exc
        self.dropped_chunks = 0
        self._worker = threading.Thread(
            target=self._drain_queue, name="spritelens-chunk-dispatch", daemon=True
        )
        self._worker.start()
        # 启动中途失败统一回滚：worker 必须回收，否则反复点开始会累积
        # 等待 queue.get 的守护线程（R03）
        try:
            self._start_sniffer(AsyncSniffer)
        except BaseException:
            self._rollback_started_worker()
            raise
        self._running = True
        self._on_event("started", self._iface or "(默认路由网卡)")

    def _start_sniffer(self, async_sniffer) -> None:
        """创建并探活嗅探器；失败抛 SourceError（降级重建 buffer_size 兼容路径）。"""
        try:
            self._sniffer = async_sniffer(
                filter=self._build_bpf(),
                prn=self._handle_packet,
                store=False,
                iface=self._iface or None,
                buffer_size=PCAP_BUFFER_BYTES,
            )
            self._sniffer.start()
        except Exception as exc:  # noqa: BLE001
            self._sniffer = None
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
                self._sniffer = async_sniffer(
                    filter=self._build_bpf(),
                    prn=self._handle_packet,
                    store=False,
                    iface=self._iface or None,
                )
                self._sniffer.start()
                break
            if exc is not None:
                self._sniffer = None
                raise SourceError(f"抓包启动失败（Npcap 未安装或权限不足）: {exc}")
            time.sleep(0.05)
        else:
            exc = getattr(self._sniffer, "exception", None)
            if exc is not None:
                self._sniffer = None
                raise SourceError(f"抓包启动失败（Npcap 未安装或权限不足）: {exc}")

    def _rollback_started_worker(self) -> None:
        """启动失败时回收投递线程与队列：与 stop 的有界清理共用路径。"""
        self._sniffer = None
        self._running = False
        self._signal_worker_stop()
        with self._flow_lock:
            self._flows.clear()
            self._flow_seen.clear()
            self._flow_count = 0

    def stop(self) -> None:
        """停止采集：sniffer 与 worker 各自有界，单项失败不跳过其余（S03a）。

        sniffer.stop 走独立预算（scapy 默认 join 无上限，卡死会长期占用
        命令锁）；超时则句柄转入 stale 列表留诊断，不当作已退出。返回
        即代表停止流程完成，未退线程由 stale 诊断接口暴露。
        """
        # 不以 _running 为前置：失败启动留下的 worker/流表也要能被清掉（R03）
        self._running = False
        sniffer = self._sniffer
        self._sniffer = None
        if sniffer is not None:
            self._stop_sniffer_bounded(sniffer)
        for stale in list(self._stale_sniffers):
            helper = self._sniffer_stop_threads.get(id(stale))
            if stale is not sniffer and (helper is None or not helper.is_alive()):
                self._stop_sniffer_bounded(stale)
        self._signal_worker_stop()
        # 停止后不再有 FIN/RST 事件，流表与重组缓冲在这里统一释放
        with self._flow_lock:
            self._retired_dropped_segments += self._live_dropped_segments()
            self._flows.clear()
            self._flow_seen.clear()
            self._flow_count = 0
        self._on_event("stopped", "")

    def _signal_worker_stop(self) -> None:
        """有界地通知投递线程退出并限时等待；超时不再阻塞调用方。

        哨兵入队必须非阻塞：满队列时丢最旧一个数据块腾位（等价过载丢弃，
        与嗅探线程的丢新块语义一致），绝不无限等待下游消费（R03 实测
        满队列 stop 挂死）。join 限时后线程交由 daemon 兜底。
        """
        worker = self._worker
        if worker is None:
            return
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            try:
                victim = self._queue.get_nowait()  # 丢最旧腾位（不可能是哨兵：队列满时无人消费它）
            except queue.Empty:
                victim = None
            if victim is not None:
                self.dropped_chunks += 1
            try:
                self._queue.put_nowait(None)
            except queue.Full:  # pragma: no cover - 刚取出必然有位
                pass
        self._worker = None
        worker.join(timeout=self._worker_join_timeout)
        if worker.is_alive():
            # 句柄即所有权证据（S03a）：超时未退不等于不存在，转存诊断
            self._stale_workers.append(worker)
            logger.warning(
                "投递线程 join 超时未退（已转存 stale 列表，restart 前应确认）: %s", worker.name
            )

    def _stop_sniffer_bounded(self, sniffer) -> bool:
        """在独立线程执行 sniffer.stop 并限时等待（D05）。

        scapy 的 stop(join=True) 无上限，驱动卡死时会把采集命令锁拖住；
        这里用预算包裹：超时把句柄转入 stale 列表并继续后续清理，
        返回 False 表示未确认退出。
        """
        done = threading.Event()
        error: list[BaseException] = []

        def _runner() -> None:
            try:
                sniffer.stop()
            except Exception as exc:  # noqa: BLE001 - 停止失败不影响退出
                error.append(exc)
            finally:
                self._sniffer_stop_errors[id(sniffer)] = bool(error)
                done.set()

        thread = threading.Thread(target=_runner, name="spritelens-sniffer-stop", daemon=True)
        self._sniffer_stop_threads[id(sniffer)] = thread
        if sniffer not in self._stale_sniffers:
            self._stale_sniffers.append(sniffer)
        thread.start()
        deadline = time.monotonic() + self._sniffer_stop_budget
        if not done.wait(timeout=self._sniffer_stop_budget):
            logger.warning(
                "sniffer.stop 超出预算 %.1fs 未返回，句柄转 stale 留诊断", self._sniffer_stop_budget
            )
            return False
        thread.join(timeout=max(0.0, deadline - time.monotonic()))
        if error:
            logger.warning("sniffer 停止异常: %s", error[0])
        return not self.has_unfinished_sniffer()

    def has_unfinished_sniffer(self) -> bool:
        """退出须同时确认 stop helper 与嗅探线程，running=False 不够。"""
        active = []
        for sniffer in self._stale_sniffers:
            helper = self._sniffer_stop_threads.get(id(sniffer))
            sniff_thread = getattr(sniffer, "thread", None)
            if (
                (helper is not None and helper.is_alive())
                or (sniff_thread is not None and sniff_thread.is_alive())
                or getattr(sniffer, "running", False)
                or (sniff_thread is None and self._sniffer_stop_errors.get(id(sniffer), False))
            ):
                active.append(sniffer)
            else:
                self._sniffer_stop_threads.pop(id(sniffer), None)
                self._sniffer_stop_errors.pop(id(sniffer), None)
        self._stale_sniffers = active
        return bool(active)

    def is_stale_worker_active(self) -> bool:
        """是否有超时未退的旧投递线程仍活着（restart 前的安全诊断）。"""
        return any(worker.is_alive() for worker in self._stale_workers)

    def _reap_stale_workers(self) -> int:
        """清理已退出的 stale 句柄；返回剩余仍活着的个数。"""
        self._stale_workers = [worker for worker in self._stale_workers if worker.is_alive()]
        return len(self._stale_workers)

    # 兼容旧名（测试与外部诊断调用）
    reap_stale_workers = _reap_stale_workers

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
