"""采集控制 ViewModel：网卡/启停/录制/手动密钥与会话快照。

纯 Python 类（不依赖任何 UI 框架/异步运行时），本地服务经
`asyncio.to_thread` 调其命令，前端按 WebSocket 推送拉取状态快照。

阶段1.3 起，运行时职责（接入层创建/录制/手动密钥/命令串行化）在
`services.capture_service.CaptureService`；本类保留页面校验、偏好
持久化与安装引导，命令经组合的服务执行——对外接口不变。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from spritelens.capture.base import SourceError
from spritelens.capture.key_store import KeyStore
from spritelens.capture.npcap_source import NpcapCaptureSource
from spritelens.logs import get_logger
from spritelens.repositories.settings import SettingsRepository
from spritelens.services.capture_service import CaptureService
from spritelens.services.monitor_service import MonitorService
from spritelens.services.session_tracker import Totals
from spritelens.system.environment import (
    NpcapReport,
    check_npcap,
    disable_rsc,
    download_installer,
    launch_installer,
    resolve_latest_installer,
)

logger = get_logger("capture_vm")

IFACE_SETTING_KEY = "capture.iface"
RECORD_SETTING_KEY = "capture.record_on_start"
AUTOSTART_SETTING_KEY = "capture.autostart"


class EnvironmentBusyError(RuntimeError):
    """环境检测已有执行者。"""


@dataclass(frozen=True)
class InstallState:
    """一键安装流程的只读状态。"""

    phase: str  # idle/resolving/downloading/launching/checking/completed/failed
    message: str
    progress: float | None


@dataclass(frozen=True)
class SessionRow:
    """会话表行视图数据。"""

    session_id: str
    has_key: bool
    data_frames: int


@dataclass(frozen=True)
class CaptureSnapshot:
    """采集页一轮刷新所需的全部只读状态。"""

    running: bool
    iface: str
    flow_count: int
    sessions: tuple[SessionRow, ...]
    totals: Totals
    recording: bool
    recorded_chunks: int
    last_error: str
    any_key: bool
    event_log_name: str = ""
    dropped_chunks: int = 0  # 队列过载丢弃的 chunk 数（下游处理不及时）
    dropped_segments: int = 0  # 重组层丢弃的乱序段数（pending 超限）
    event_log_dropped: int = 0  # 事件日志队列满丢弃的条数（磁盘跟不上）
    event_log_error: str = ""


class CaptureViewModel:
    """采集页状态与命令；接入层构造在 CaptureService（可插拔点）。"""

    def __init__(
        self,
        *,
        monitor: MonitorService,
        settings: SettingsRepository,
        keys_dir: Path,
        recordings_dir: Path,
        port: int,
        key_store: KeyStore | None = None,
        installer_dir: Path | None = None,
        event_log=None,
        resolver=None,
        downloader=None,
        launcher=None,
        environment_probe: callable | None = None,
        probe_environment: bool = True,
    ) -> None:
        self._monitor = monitor
        self._settings = settings
        self._recordings_dir = recordings_dir
        self._event_log = event_log
        self._iface = settings.get_str(IFACE_SETTING_KEY)
        # 打开即采集：默认开启（用户可关）；环境不满足时 start() 会转成可读错误
        self._autostart = settings.get_bool(AUTOSTART_SETTING_KEY, True)
        self._ifaces: list[tuple[str, str]] = []
        # 附加采集端口（排障用，多端口游戏/新连接），逗号分隔配置 capture.ports
        ports: list[int] = []
        for part in settings.get_str("capture.ports", "").split(","):
            part = part.strip()
            if part.isdigit() and int(part) != port and int(part) not in ports:
                ports.append(int(part))
        self._port = port
        self._extra_ports = tuple(ports)
        # 运行时职责收口到服务（命令锁/接入层/录制/密钥）
        self._service = CaptureService(
            monitor=monitor,
            keys_dir=keys_dir,
            recordings_dir=recordings_dir,
            port=port,
            key_store=key_store,
            extra_ports=self._extra_ports,
            iface=self._iface or None,
            recording_wanted=settings.get_bool(RECORD_SETTING_KEY, False),
        )
        # 录制偏好持久化经服务回调（S01/D03）：与意愿/启停同一命令区间；
        # 用 set_checked——显式命令的保存失败必须传回调用者（set 会吞 OSError）
        self._service.set_recording_persist(
            lambda enabled: settings.set_checked(RECORD_SETTING_KEY, bool(enabled))
        )
        # 快速检查（毫秒级）：只查驱动文件存在性，installed 立即可用，
        # autostart 不必等探测；RSC 检查（PowerShell 实测约 1.8s）随后异步补齐。
        self._environment_lock = threading.Lock()
        self._environment_error = ""
        self._npcap_report = check_npcap(quick=True)
        self._install_phase = "idle"
        self._install_message = ""
        self._install_progress: float | None = None
        self._installing = False
        from spritelens.paths import data_root

        self._installer_dir = installer_dir or (data_root() / "downloads")
        # 安装依赖可注入（测试用 fake），默认官方源真实实现
        self._resolver = resolver or resolve_latest_installer
        self._downloader = downloader or download_installer
        self._launcher = launcher or launch_installer
        self._environment_probe = environment_probe or check_npcap
        if probe_environment:
            threading.Thread(
                target=self._probe_environment,
                name="npcap-probe",
                daemon=True,
            ).start()

    # -- 环境探测 --------------------------------------------------------
    def _probe_environment(self) -> None:
        """后台执行完整环境检查（含 RSC 的 PowerShell 探测），完成后替换占位报告。

        为什么不在这里触发 autostart：autostart 只依赖 installed 字段，
        快速检查（毫秒级）已经能给出正确结论，装配路径无需等探测。
        """
        try:
            self.refresh_environment()
        except Exception:  # noqa: BLE001 - 探测失败不影响其他功能
            logger.exception("环境探测失败")
            return

    # -- 网卡 ----------------------------------------------------------
    def refresh_ifaces(self) -> list[tuple[str, str]]:
        try:
            self._ifaces = NpcapCaptureSource.list_ifaces()
        except SourceError as exc:
            self._set_error(str(exc))
            raise
        return list(self._ifaces)

    @property
    def selected_iface(self) -> str:
        return self._iface

    def select_iface(self, name: str) -> None:
        """选择网卡；显式命令保存失败必须可见（D03，set_checked）。

        运行态已切到新网卡但配置未保存时抛 OSError，HTTP 层转可读错误。
        """
        self._iface = name
        self._service.set_iface(name or None)
        self._settings.set_checked(IFACE_SETTING_KEY, name)

    # -- 启停（委托运行服务；页面只做校验与状态同步）----------------------
    def start(self) -> None:
        """构造接入层并启动；失败转 last_error 供页面提示。"""
        self._service.start()

    def _set_error(self, message: str) -> None:
        """页面动作错误（网卡枚举等）：经服务唯一入口登记，不跨层写字段。"""
        self._service.set_error(message)

    @property
    def extra_ports(self) -> tuple[int, ...]:
        return self._extra_ports

    # -- 自动采集 ------------------------------------------------------
    @property
    def autostart(self) -> bool:
        """打开即采集开关（默认开；关掉后需手动点「开始采集」）。"""
        return self._autostart

    def set_autostart(self, enabled: bool) -> None:
        """打开即采集开关；显式命令保存失败必须可见（D03，set_checked）。"""
        self._autostart = bool(enabled)
        self._settings.set_checked(AUTOSTART_SETTING_KEY, bool(enabled))

    def start_if_autostart(self) -> bool:
        """启动流程调用：开关开着且环境可用时自动开始采集。

        返回是否真正发起了采集。环境不满足（缺 Npcap 驱动）时不尝试——
        避免每次启动都往用户脸上弹一次失败提示，交给采集页横幅引导安装。
        """
        if not self._autostart or self._monitor.is_running:
            return False
        if not self._npcap_report.installed:
            logger.info("自动采集跳过：未检测到 Npcap 抓包驱动")
            return False
        self.start()
        return self._monitor.is_running

    def stop(self) -> None:
        self._service.stop()

    def command_scope(self):
        """账号切换等组合命令使用采集服务的同一所有权边界。"""
        return self._service.command_scope()

    @property
    def is_running(self) -> bool:
        return self._monitor.is_running

    # -- 录制 ----------------------------------------------------------
    @property
    def recording_requested(self) -> bool:
        """录制意愿（单一所有者：读服务状态，VM 不保留平行缓存，D02）。"""
        return self._service.recording_wanted()

    def set_recording_requested(self, enabled: bool) -> None:
        """录制开关：整条命令（意愿+启停+持久化）由服务在命令锁内完成（S01）。

        VM 只转发、不再回写本地缓存——旧实现 `self._recording_requested =
        enabled` 在服务锁释放后执行，能把较新的相反命令覆盖回旧值（D02）。
        持久化失败（set_checked 抛 OSError）原样上抛，HTTP 返回可读错误。
        """
        self._service.set_recording(bool(enabled))

    # -- 手动密钥 ------------------------------------------------------
    def apply_manual_key(self, text: str) -> tuple[bool, str]:
        return self._service.apply_manual_key(text)

    # -- Npcap 环境 ----------------------------------------------------
    def environment_report(self) -> NpcapReport:
        return self._npcap_report

    @property
    def port(self) -> int:
        return self._port

    @property
    def environment_checking(self) -> bool:
        return self._environment_lock.locked()

    @property
    def environment_error(self) -> str:
        return self._environment_error

    def refresh_environment(self) -> NpcapReport:
        """显式检测失败保留旧报告；重复请求不并发执行系统探测。"""
        if not self._environment_lock.acquire(blocking=False):
            raise EnvironmentBusyError("环境检测正在进行，请稍后重试")
        try:
            report = self._environment_probe()
            self._npcap_report = report
            self._environment_error = ""
            return report
        except Exception as exc:
            self._environment_error = str(exc)
            raise
        finally:
            self._environment_lock.release()

    def start_disable_rsc(self) -> None:
        """一键禁用 RSC（UAC 提权）；完成后重新检测环境。"""
        if self._installing or not self._npcap_report.rsc_enabled:
            return
        adapter = self._npcap_report.rsc_adapter
        self._installing = True
        self._set_install("resolving", f"正在禁用网卡「{adapter}」的 RSC（请在 UAC 弹窗中确认）……", None)

        def worker() -> None:
            try:
                disable_rsc(adapter)
                self.refresh_environment()
                if self._npcap_report.rsc_enabled:
                    self._set_install("failed", "RSC 仍未禁用（UAC 被取消或命令失败），请手动执行", None)
                else:
                    self._set_install("completed", "RSC 已禁用，抓包环境正常（无需重启）", None)
            except Exception as exc:  # noqa: BLE001
                logger.warning("禁用 RSC 失败: %s", exc)
                self._set_install("failed", f"禁用 RSC 失败：{exc}", None)
            finally:
                self._installing = False

        threading.Thread(target=worker, name="rsc-disable", daemon=True).start()

    def install_state(self) -> InstallState:
        return InstallState(
            phase=self._install_phase,
            message=self._install_message,
            progress=self._install_progress,
        )

    def start_npcap_install(self) -> None:
        """一键安装：后台下载官方安装器并提权拉起向导（幂等，进行中忽略）。"""
        if self._installing:
            return
        if self._npcap_report.installed:
            return
        self._installing = True
        worker = threading.Thread(target=self._install_worker, name="npcap-install", daemon=True)
        worker.start()

    def _set_install(self, phase: str, message: str, progress: float | None) -> None:
        self._install_phase = phase
        self._install_message = message
        self._install_progress = progress

    def _install_worker(self) -> None:
        try:
            self._set_install("resolving", "正在查询 Npcap 最新版本…", None)
            url, version = self._resolver()
            self._set_install("downloading", f"正在下载 npcap-{version}…", 0.0)

            def on_progress(value: float) -> None:
                self._set_install("downloading", f"正在下载 npcap-{version}…", value)

            dest = self._downloader(url, self._installer_dir, progress_cb=on_progress)
            self._set_install("launching", "安装包下载完成，正在运行安装向导…", None)
            exit_code = self._launcher(dest)
            self._set_install("checking", "安装器已退出，正在重新检测 Npcap…", None)
            report = self.refresh_environment()
            if not report.installed:
                suffix = f"（安装器退出代码 {exit_code}）" if exit_code not in (None, 0) else ""
                raise RuntimeError(f"安装器已退出但仍未检测到 Npcap{suffix}")
            self._set_install(
                "completed",
                "Npcap 安装完成，抓包环境已就绪；如采集未恢复，请重启 SpriteLens。",
                None,
            )
        except Exception as exc:  # noqa: BLE001 - 安装引导失败转用户可读消息
            logger.warning("Npcap 一键安装失败: %s", exc)
            self._set_install(
                "failed",
                f"一键安装失败：{exc}。请到 https://npcap.com/#download 手动下载安装。",
                None,
            )
        finally:
            self._installing = False

    # -- 快照 ----------------------------------------------------------
    def snapshot(self) -> CaptureSnapshot:
        sessions_raw, totals = self._monitor.snapshot()
        sessions = tuple(
            SessionRow(session_id=s.session_id, has_key=s.has_key, data_frames=s.data_frames)
            for s in sessions_raw
        )
        status = self._service.status()
        return CaptureSnapshot(
            running=status.running,
            iface=self._iface,
            flow_count=len(sessions),
            sessions=sessions,
            totals=totals,
            recording=status.recording,
            recorded_chunks=status.recorded_chunks,
            last_error=status.last_error,
            any_key=any(s.has_key for s in sessions),
            event_log_name=(
                Path(self._event_log.current_path).name
                if self._event_log is not None and self._event_log.current_path
                else ""
            ),
            # 丢弃计数：队列过载（下游处理不及时）与重组层超限，均是静默丢数据，
            # 必须在状态接口可见（采集页据此提示"有数据未进入分析"）
            dropped_chunks=status.source_dropped_chunks,
            dropped_segments=status.source_dropped_segments,
            event_log_dropped=(
                self._event_log.dropped_count
                if self._event_log is not None and hasattr(self._event_log, "dropped_count")
                else 0
            ),
            event_log_error=self._event_log.error if self._event_log is not None else "",
        )


__all__ = [
    "AUTOSTART_SETTING_KEY",
    "CaptureSnapshot",
    "CaptureViewModel",
    "IFACE_SETTING_KEY",
    "InstallState",
    "RECORD_SETTING_KEY",
    "SessionRow",
]
