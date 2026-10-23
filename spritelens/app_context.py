"""应用装配根：监听管线 + 持久化 + ViewModel 的统一组装。

Web 界面入口（`spritelens.web.run.run_web`）调用本模块完成一次性装配；
同一条管线、同一份库、同一批 VM 交给前端消费。

本模块不导入任何 UI 框架（pywebview 由入口负责创建）。
"""

from __future__ import annotations

from dataclasses import dataclass

from spritelens.capture.key_store import KeyStore
from spritelens.domain.color_cards import ColorCatalog
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
from spritelens.repositories.home_store import HomeStore
from spritelens.repositories.pet_store import PetStore
from spritelens.repositories.settings import DEFAULT_CAPTURE_PORT, SettingsRepository
from spritelens.services.egg_repository import EggBoxRepository
from spritelens.services.account_selection_service import AccountSelectionService
from spritelens.services.home_repository import HomeRepository
from spritelens.services.event_logger import EventLogWriter
from spritelens.services.game_capture_automation import GameCaptureAutomation
from spritelens.services.monitor_service import MonitorService
from spritelens.services.pet_repository import PetRepository
from spritelens.view_models import CaptureViewModel, PetViewModel

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
    pet_vm: PetViewModel
    pet_store: PetStore | None = None
    event_log: EventLogWriter | None = None
    egg_catalog: EggCatalog | None = None  # 蛋目录（缺失时蛋相关页面降级）
    color_catalog: ColorCatalog | None = None  # 色卡目录（缺失时色卡页降级）
    egg_store: EggStore | None = None
    home_store: HomeStore | None = None
    egg_box: EggBoxRepository | None = None  # 蛋仓聚合（缺失时蛋仓页面空态）
    home_repo: HomeRepository | None = None  # 家园快照（缺失时家园页空态）
    account_selection: AccountSelectionService | None = None
    game_automation: GameCaptureAutomation | None = None
    database: Database | None = None  # 组合根持有并负责关闭（R09）
    key_store: KeyStore | None = None  # 会话文件 writer 的生命周期归组合根持有
    _capture_stopped: bool = False

    def close(self) -> None:
        """停监听、排空异步写入并按逆序释放资源（幂等；退出路径唯一）。

        先停采集，再关闭事件日志、各 Store 与 KeyStore，最后关闭
        Database。任何持久化 worker 未确认退出或仍有待写数据时，保留
        其下游资源和可重试的关闭所有权。
        """
        if self._closed:
            return
        failures: list[tuple[str, BaseException]] = []

        def _try(label: str, action) -> None:
            try:
                action()
            except Exception as exc:  # noqa: BLE001 - 清理失败不阻断其余资源
                failures.append((label, exc))
                logger.warning("关闭 %s 失败: %s", label, exc)

        if not self._capture_stopped:
            try:
                self.capture_vm.stop()
            except TimeoutError:
                # 旧回调仍可能访问日志/Store/DB；保持可重试，不关闭其下游。
                logger.warning("采集未确认停止，延后关闭存储资源")
                raise
            except Exception as exc:
                logger.warning("停止采集失败，保留下游资源供重试: %s", exc)
                raise
            self._capture_stopped = True
        if self.event_log is not None:
            _try("事件日志", self.event_log.close)
        if self.key_store is not None:
            _try("密钥存储", self.key_store.close)
        store_failures: list[tuple[str, BaseException]] = []
        if self.pet_store is not None:
            try:
                self.pet_store.close()
            except Exception as exc:  # noqa: BLE001 - 两个 Store 都需停止 worker
                store_failures.append(("宠物仓库", exc))
                logger.warning("关闭宠物仓库失败: %s", exc)
        if self.egg_store is not None:
            try:
                self.egg_store.close()
            except Exception as exc:  # noqa: BLE001 - 失败时仍保留 Database
                store_failures.append(("蛋仓仓库", exc))
                logger.warning("关闭蛋仓仓库失败: %s", exc)
        if self.home_store is not None:
            try:
                self.home_store.close()
            except Exception as exc:  # noqa: BLE001 - 失败时仍保留 Database
                store_failures.append(("家园仓库", exc))
                logger.warning("关闭家园仓库失败: %s", exc)
        if store_failures:
            label, exc = store_failures[0]
            raise RuntimeError(f"关闭 {label} 失败: {exc}") from exc
        if self.database is not None:
            try:
                self.database.close()
            except Exception as exc:  # noqa: BLE001 - 保持可重试
                logger.warning("关闭数据库失败: %s", exc)
                raise RuntimeError(f"关闭数据库失败: {exc}") from exc
        if failures:
            label, exc = failures[0]
            raise RuntimeError(f"关闭 {label} 失败: {exc}") from exc
        self._closed = True

    _closed: bool = False


def build_app_context(*, autostart: bool = True) -> AppContext:
    """装配业务环境（不含任何 UI）；调用方负责日志初始化与单实例守卫。

    autostart：装配完成后是否按配置自动开始采集（打开即采集，默认开）。

    装配失败回滚（S02）：每个资源创建成功即登记，任一节点抛异常（含
    autostart 阶段）时逆序清理已登记资源（EventLogWriter 构造即启动
    worker，采集可能已起 source，不清理会泄漏线程/监听），然后原样
    抛出。装配成功后所有权转交 context.close，登记表在**外层**作废，
    避免成功路径再次触碰内层作用域（D01 回归：此前 clear 写在内层，
    正常装配必然 NameError）。
    """
    created: list = []
    try:
        context = _build_app_context_inner(created, autostart=autostart)
    except BaseException:
        for cleanup in reversed(created):
            try:
                cleanup()
            except TimeoutError:
                logger.warning("装配回滚仍有活跃采集，保留下游资源")
                break
            except Exception as exc:  # noqa: BLE001 - 回滚失败不阻断其余清理
                logger.warning("装配回滚清理失败: %s", exc)
        raise
    created.clear()
    return context


def _build_app_context_inner(created: list, *, autostart: bool) -> AppContext:
    _created = created.append
    settings = SettingsRepository(config_path())
    game_automation = GameCaptureAutomation(settings)
    load_library(schema_dir())
    static_data = load_static_data(static_dir())
    egg_catalog = EggCatalog(static_dir())
    color_catalog = ColorCatalog(static_dir())

    # 启动即恢复上次捕获的会话密钥：连接未重连时（AES 无跨包状态）可立即续解
    key_store = KeyStore(keys_dir())
    _created(key_store.close)
    monitor = MonitorService(
        catalog=load_catalog(),
        key_store=key_store,
        preset_key=key_store.load_latest(),
    )

    # 应用层组装：宠物仓库订阅协议事件流（语义化 → 状态聚合 → 持久化）
    database = Database(database_path())
    _created(database.close)
    pet_store = PetStore(database)
    _created(pet_store.close)
    pet_repository = PetRepository(store=pet_store)
    monitor.add_packet_listener(pet_repository.handle_packet)

    # 统一离线展示 uid（R05）：accounts 表记录最近登录（登录即写，各域
    # 同源），宠物与蛋仓都按它恢复，避免两个域各自选号出现「宠物归 B、
    # 蛋仓归 A」的串号。该账号无某域记录时明确空缓存，不拿别的账号补齐。
    display_uid = next((uid for uid, _name in pet_store.list_accounts()), 0)
    restored = pet_repository.load_persisted(display_uid) if display_uid else 0
    if restored:
        logger.info("已载入历史宠物 %d 只（来自本地库）", restored)

    # 事件日志落盘（复盘用）：data/eventlog/eventlog_YYYYMMDD.jsonl
    event_log = EventLogWriter(data_root() / "eventlog")
    _created(event_log.close)  # 构造即启动 worker：失败必须回收线程
    monitor.add_packet_listener(event_log.handle_packet)

    # 家园快照聚合（0x014A 全量 + 增量合并 + 本地历史快照）
    home_store = HomeStore(database)
    _created(home_store.close)
    home_repo = HomeRepository(store=home_store)
    monitor.add_packet_listener(home_repo.handle_packet)
    restored_home = home_repo.load_account(display_uid) if display_uid else False
    if restored_home:
        logger.info("已载入历史家园快照（账号 %s）", display_uid)

    # 蛋仓聚合：订阅协议事件流 + SQLite 持久化（重启不丢，离线可看）
    egg_store = EggStore(database)
    _created(egg_store.close)
    egg_box = EggBoxRepository(store=egg_store)
    monitor.add_packet_listener(egg_box.handle_packet)
    if display_uid:
        restored_eggs = egg_box.load_account(display_uid)
        if restored_eggs:
            logger.info("已载入历史蛋仓 %d 枚（来自本地库）", restored_eggs)

    capture_vm = CaptureViewModel(
        monitor=monitor,
        settings=settings,
        keys_dir=keys_dir(),
        recordings_dir=recordings_dir(),
        port=settings.get_int("capture.port", DEFAULT_CAPTURE_PORT, lo=1, hi=65535),
        key_store=key_store,
        event_log=event_log,
    )
    # autostart 之后失败也必须停源（D01）：capture 停机在逆序回滚里先于
    # 存储关闭执行；未启动时 stop 幂等（recorder/monitor 各自处理空态）
    _created(capture_vm.stop)
    account_selection = AccountSelectionService(
        pet_store=pet_store,
        egg_store=egg_store,
        home_store=home_store,
        pet_repository=pet_repository,
        egg_box=egg_box,
        home_repo=home_repo,
        capture_running=lambda: capture_vm.snapshot().running,
        capture_command_scope=capture_vm.command_scope,
    )
    pet_vm = PetViewModel(pet_repository, static_data=static_data)
    context = AppContext(
        settings=settings,
        static_data=static_data,
        monitor=monitor,
        pet_repository=pet_repository,
        capture_vm=capture_vm,
        pet_vm=pet_vm,
        egg_box=egg_box,
        pet_store=pet_store,
        event_log=event_log,
        egg_catalog=egg_catalog,
        color_catalog=color_catalog,
        egg_store=egg_store,
        home_store=home_store,
        home_repo=home_repo,
        account_selection=account_selection,
        game_automation=game_automation,
        database=database,
        key_store=key_store,
    )
    if autostart and capture_vm.start_if_autostart():
        logger.info("已自动开始采集（可在采集页关闭「打开即采集」）")
    # 成功路径不在这里作废登记：由外层 build_app_context 在拿到 context 后
    # 统一 clear（D01：内层再来一次会在混入新语句时重新引入作用域错误）
    return context


__all__ = ["AppContext", "build_app_context", "load_catalog"]
