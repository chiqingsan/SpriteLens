"""采集运行服务：接入层创建与生命周期、录制 tee、手动密钥、串行命令。

从 CaptureViewModel 抽取（阶段1.3，路线图）：VM 之前同时承担「页面状态
展示」与「应用运行时职责」（构造抓包源、控制录制线程、安装流程）。
本服务承接运行时职责——副作用命令在命令锁内串行执行，状态读取走
monitor 自身锁，锁内不做等待与磁盘 IO。

CaptureViewModel 保留页面校验与展示，通过组合本服务实现命令；对外
接口不变（web/server 与测试无感知）。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path

from spritelens.capture.base import SourceError, StreamChunk
from spritelens.capture.key_store import KeyStore, parse_key_text
from spritelens.capture.npcap_source import NpcapCaptureSource
from spritelens.logs import get_logger
from spritelens.recording.recorder import StreamRecorder
from spritelens.services.monitor_service import MonitorService

logger = get_logger("capture_service")


@dataclass(frozen=True)
class CaptureRuntimeStatus:
    """运行服务的一轮只读状态（快照用，不含安装流程）。"""

    running: bool
    recording: bool
    recorded_chunks: int
    source_dropped_chunks: int
    source_dropped_segments: int
    last_error: str


class CaptureService:
    """采集会话的唯一所有者：start/stop/录制/手动密钥都在这里收口。"""

    def __init__(
        self,
        *,
        monitor: MonitorService,
        keys_dir: Path,
        recordings_dir: Path,
        port: int,
        extra_ports: tuple[int, ...] = (),
        iface: str | None = None,
        recording_wanted: bool = False,
    ) -> None:
        self._monitor = monitor
        self._key_store = KeyStore(keys_dir)
        self._recorder = StreamRecorder()
        self._recordings_dir = recordings_dir
        self._port = port
        self._extra_ports = extra_ports
        self._iface = iface
        self._source: NpcapCaptureSource | None = None
        self._last_error = ""
        self._recording_wanted = recording_wanted
        # 录制偏好持久化回调（S01）：由组合根注入，命令锁内调用；
        # 服务本身不依赖 SettingsRepository（保持可独立测试）。
        self._persist_recording = None
        # 副作用命令串行化（R09 同源）：start/stop/录制切换/手动密钥
        # 经 HTTP 的 to_thread 并发进入时互斥执行；快照不取该锁。
        self._command_lock = threading.Lock()

    # -- 命令（串行） ----------------------------------------------------
    def start(self) -> None:
        """构造接入层并启动；失败转 last_error 供页面提示。

        重启前检查旧 source 的未退线程（D04）：投递 worker 或嗅探器
        未确认退出时拒绝重启——同实例/同下游回调下两代并存会让旧回调
        污染新会话；已退出的 stale 句柄先清再判。
        """
        with self._command_lock:
            if self._monitor.is_running:
                return
            previous = self._source
            if previous is not None:
                previous.reap_stale_workers()
                if previous.is_stale_worker_active() or previous.has_unfinished_sniffer():
                    self._last_error = "上一会话的采集线程尚未退出，暂不能重新开始采集（稍后重试）"
                    logger.warning("拒绝重启：%s", self._last_error)
                    return
            self._last_error = ""
            source = NpcapCaptureSource(
                self._port,
                on_chunk=self._tee_chunk,
                on_event=self._handle_source_event,
                iface=self._iface or None,
                extra_ports=self._extra_ports,
            )
            self._source = source  # 先挂引用：启动期间的快照也能读到丢弃计数
            try:
                self._monitor.bind(source)
                self._monitor.start()
            except SourceError as exc:
                self._last_error = str(exc)
                logger.warning("采集启动失败: %s", exc)
                return
            self._maybe_start_recording_locked()

    def stop(self) -> None:
        """停止采集（S03a）：录制器失败仍尝试停 source/协议层。

        旧实现 recorder.stop 抛异常会跳过 monitor.stop，留下运行中的
        接入层。录制是旁路功能，停源才是停止命令的主目标。
        """
        with self._command_lock:
            try:
                self._recorder.stop()
            except Exception as exc:  # noqa: BLE001 - 录制失败不阻断停源
                logger.warning("录制器停止失败（继续停采集）: %s", exc)
            self._monitor.stop()

    def set_iface(self, name: str | None) -> None:
        with self._command_lock:
            self._iface = name or None

    def set_recording(self, enabled: bool) -> None:
        """录制开关命令（S01）：意愿、立即启停与持久化在同一串行区间完成。

        running 由本方法在命令锁内判定，不接收调用方传入的旧值——
        旧实现 VM 锁外读 running 再传进来，「调用方读到运行中 → stop
        完成 → 提交旧值」可让 stop 后误开录制。persist 回调（写配置）
        也在锁内执行：命令锁可包含必要 IO，保证四个动作的顺序对并发
        观察者原子。

        失败语义（D03）：意愿与录制器状态先提交、持久化在后——持久化
        失败（如 set_checked 抛 OSError）表示「运行状态已生效但未保存」，
        异常原样上抛由 HTTP 层转可读错误；再次查询状态时以内存意愿为准，
        重启后才会回到旧配置（这是唯一可接受的降级方向）。
        """
        with self._command_lock:
            self._recording_wanted = enabled
            running = self._monitor.is_running
            if enabled and running and not self._recorder.is_recording:
                self._start_recording_locked()
            elif not enabled and self._recorder.is_recording:
                self._recorder.stop()
            if self._persist_recording is not None:
                self._persist_recording(enabled)

    def recording_wanted(self) -> bool:
        """录制意愿（命令锁保护读，供快照/VM 无条件读取）。"""
        with self._command_lock:
            return self._recording_wanted

    def apply_manual_key(self, text: str) -> tuple[bool, str]:
        try:
            key = parse_key_text(text)
        except ValueError as exc:
            return False, str(exc)
        with self._command_lock:
            self._key_store.save_latest(key, "(manual)")
            self._monitor.set_preset_key(key)
        return True, "密钥已应用（对新旧会话生效）"

    # -- 快照（无命令锁） -------------------------------------------------
    def status(self) -> CaptureRuntimeStatus:
        source = self._source
        return CaptureRuntimeStatus(
            running=self._monitor.is_running,
            recording=self._recorder.is_recording,
            recorded_chunks=self._recorder.chunk_count,
            source_dropped_chunks=getattr(source, "dropped_chunks", 0) if source is not None else 0,
            source_dropped_segments=getattr(source, "dropped_segments", 0) if source is not None else 0,
            last_error=self._last_error,
        )

    # -- 内部 ------------------------------------------------------------
    def set_recording_persist(self, persist) -> None:
        """注入录制偏好持久化回调（组合根装配时调用一次）。"""
        self._persist_recording = persist

    def set_error(self, message: str) -> None:
        """页面动作错误登记（网卡枚举等）：唯一合法入口，替代直接写字段。"""
        self._last_error = message

    def _maybe_start_recording_locked(self) -> None:
        """start 成功后按需开录制（调用方已持命令锁）。"""
        if self._recording_wanted and not self._recorder.is_recording:
            self._start_recording_locked()

    def set_recording_wanted(self, wanted: bool) -> None:
        """记录录制意愿（下次 start 时生效）；立即开停走 set_recording。"""
        self._recording_wanted = wanted

    def _start_recording_locked(self) -> None:
        name = f"capture_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
        self._recorder.start(self._recordings_dir / name)

    def _handle_source_event(self, kind: str, detail: str) -> None:
        """接入层生命周期事件：连接关闭贯穿到协议层释放会话状态。

        flow_closed 由投递线程按序回调（排在本会话残余数据之后），
        close_session 不会清掉尚未处理的 DATA 所需的密钥。
        """
        logger.info("[source] %s %s", kind, detail)
        if kind == "flow_closed" and detail:
            self._monitor.close_session(detail)

    def _tee_chunk(self, chunk: StreamChunk) -> None:
        """录制与解析共用一个流入口（组合根不感知该分流）。"""
        self._recorder.append(chunk)
        self._monitor.on_chunk(chunk)


__all__ = ["CaptureRuntimeStatus", "CaptureService"]
