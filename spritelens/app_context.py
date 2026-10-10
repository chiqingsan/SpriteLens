"""应用装配根：监听管线 + 持久化 + ViewModel 的统一组装。

Web 界面入口（`spritelens.web.run.run_web`）调用本模块完成一次性装配；
同一条管线、同一份库、同一批 VM 交给前端消费。

本模块不导入任何 UI 框架（pywebview 由入口负责创建）。
"""

from __future__ import annotations

from dataclasses import dataclass

from spritelens.capture.key_store import KeyStore
from spritelens.domain.eggs import EggCatalog
from spritelens.domain.static_data import StaticData, load_static_data
from spritelens.logs import get_logger
from spritelens.paths import (
    config_path,
    data_root,
    database_path,
    keys_dir,
    project_root,
    recordings_dir,
    schema_dir,
    static_dir,
)
from spritelens.protocol.opcodes import OpcodeCatalog
from spritelens.protocol.schema import load_library
from spritelens.repositories.database import Database
from spritelens.repositories.egg_store import EggStore
from spritelens.repositories.pet_store import PetStore
from spritelens.repositories.settings import DEFAULT_CAPTURE_PORT, SettingsRepository
from spritelens.services.egg_repository import EggBoxRepository
from spritelens.services.home_repository import HomeRepository
from spritelens.services.event_logger import EventLogWriter
from spritelens.services.monitor_service import MonitorService
from spritelens.services.pet_repository import PetRepository
from spritelens.view_models import CaptureViewModel, EventsViewModel, PetViewModel

logger = get_logger("app_context")


def load_catalog() -> OpcodeCatalog:
    return OpcodeCatalog.load(project_root() / "data" / "schemas" / "opcodes.json")


@dataclass
class AppContext:
    """一次装配出的运行环境；前端只读消费，`close()` 释放全部资源。"""

    settings: SettingsRepository
    static_data: StaticData | None
    monitor: MonitorService
    pet_repository: PetRepository
    capture_vm: CaptureViewModel
    events_vm: EventsViewModel
    pet_vm: PetViewModel
    pet_store: PetStore | None = None
    event_log: EventLogWriter | None = None
    egg_catalog: EggCatalog | None = None  # 蛋目录（缺失时蛋相关页面降级）
    egg_store: EggStore | None = None
    egg_box: EggBoxRepository | None = None  # 蛋仓聚合（缺失时蛋仓页面空态）
    home_repo: HomeRepository | None = None  # 家园快照（缺失时家园页空态）

    def close(self) -> None:
        """停监听、落盘、关日志（幂等；退出路径唯一）。"""
        if self._closed:
            return
        self._closed = True
        self.capture_vm.stop()
        if self.event_log is not None:
            self.event_log.close()
        if self.pet_store is not None:
            self.pet_store.close()

    _closed: bool = False


def build_app_context(*, autostart: bool = True) -> AppContext:
    """装配业务环境（不含任何 UI）；调用方负责日志初始化与单实例守卫。

    autostart：装配完成后是否按配置自动开始采集（打开即采集，默认开）。
    """
    settings = SettingsRepository(config_path())
    load_library(schema_dir())
    static_data = load_static_data(static_dir())
    egg_catalog = EggCatalog(static_dir())

    # 启动即恢复上次捕获的会话密钥：连接未重连时（AES 无跨包状态）可立即续解
    key_store = KeyStore(keys_dir())
    monitor = MonitorService(
        catalog=load_catalog(),
        key_store=key_store,
        preset_key=key_store.load_latest(),
    )

    # 应用层组装：宠物仓库订阅协议事件流（语义化 → 状态聚合 → 持久化）
    database = Database(database_path())
    pet_store = PetStore(database)
    pet_repository = PetRepository(store=pet_store)
    monitor.add_packet_listener(pet_repository.handle_packet)
    restored = pet_repository.load_last_account()
    if restored:
        logger.info("已载入历史宠物 %d 只（来自本地库）", restored)

    # 事件日志落盘（复盘用）：data/eventlog/eventlog_YYYYMMDD.jsonl
    event_log = EventLogWriter(data_root() / "eventlog")
    monitor.add_packet_listener(event_log.handle_packet)

    # 家园快照聚合（0x014A 全量 + 增量版本提示）
    home_repo = HomeRepository()
    monitor.add_packet_listener(home_repo.handle_packet)

    # 蛋仓聚合：订阅协议事件流 + SQLite 持久化（重启不丢，离线可看）
    egg_store = EggStore(database)
    egg_box = EggBoxRepository(store=egg_store)
    monitor.add_packet_listener(egg_box.handle_packet)
    restored_eggs = egg_box.load_last_account()
    if restored_eggs:
        logger.info("已载入历史蛋仓 %d 枚（来自本地库）", restored_eggs)

    capture_vm = CaptureViewModel(
        monitor=monitor,
        settings=settings,
        keys_dir=keys_dir(),
        recordings_dir=recordings_dir(),
        port=settings.get_int("capture.port", DEFAULT_CAPTURE_PORT, lo=1, hi=65535),
        event_log=event_log,
    )
    events_vm = EventsViewModel(monitor=monitor)
    pet_vm = PetViewModel(pet_repository, static_data=static_data)
    context = AppContext(
        settings=settings,
        static_data=static_data,
        monitor=monitor,
        pet_repository=pet_repository,
        capture_vm=capture_vm,
        events_vm=events_vm,
        pet_vm=pet_vm,
        egg_box=egg_box,
        pet_store=pet_store,
        event_log=event_log,
        egg_catalog=egg_catalog,
        egg_store=egg_store,
        home_repo=home_repo,
    )
    if autostart and capture_vm.start_if_autostart():
        logger.info("已自动开始采集（可在采集页关闭「打开即采集」）")
    return context


__all__ = ["AppContext", "build_app_context", "load_catalog"]
