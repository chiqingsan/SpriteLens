"""本地 HTTP 服务：aiohttp + 仅回环 + 启动 token 鉴权。

为什么单开线程跑事件循环：桌面壳（pywebview）占用主线程，业务层都是线程安全的
同步代码；把 aiohttp 放进专属线程的独立事件循环，两边互不阻塞，停止时
经 `run_coroutine_threadsafe` 优雅收尾。

安全组合（与竞品同款三件套，见 docs/ARCHITECTURE_DECISION.md §0.3）：
- 只绑定 127.0.0.1；
- 每次启动随机端口（port=0 由系统分配，避免固定端口被其他程序探测/占用）；
- 每次启动随机 token（`secrets.token_urlsafe`），经 URL fragment 交给前端
  （fragment 不进服务端日志、不发 Referer）；请求带 `X-Local-Token` 头，
  WebSocket 因浏览器限制改用 `?token=` 查询参数；服务端 `compare_digest`
  常量时间比较。

业务读写全部经 AppContext（业务层与界面层解耦，界面可替换）。
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import sqlite3
import threading
import time
import webbrowser
from dataclasses import replace
from pathlib import Path

from aiohttp import WSMsgType, web

from spritelens.app_context import AppContext
from spritelens.logs import get_logger
from spritelens.paths import data_root, static_dir as static_data_dir
from spritelens.view_models.ui_preferences import UIPreferencesViewModel
from spritelens.web.payloads import (
    pet_row,
    pets_payload,
)
from spritelens.web.payloads_catalog import (
    egg_box_payload,
    egg_dex_payload,
    colors_payload,
    handbook_payload,
    home_payload,
)
from spritelens.web.pet_media_cache import PetMediaCache
from spritelens.web.account_avatar_cache import AccountAvatarCache
from spritelens.web.egg_icon_cache import EggIconCache
from spritelens.web.background import RUN_BLOCKING
from spritelens.web.nearby import register_nearby_routes
from spritelens.web.world_maps import register_world_map_routes
from spritelens.web.routes_capture import CaptureRoutesMixin
from spritelens.web.routes_accounts import AccountRoutesMixin
from spritelens.web.ext_api import (
    API_VERSION as EXT_API_VERSION,
    DEFAULT_EXT_OPCODES,
    ExtEventHub,
    ExtRoutesMixin,
)
from spritelens.web.collection_lines import register_collection_routes
from spritelens.web.breeder_library import register_breeder_routes
from spritelens.web.breeding_planner import register_planner_routes

logger = get_logger("web")
QQ_GROUP_NUMBER = "1057031552"
QQ_GROUP_JOIN_URL = (
    "https://qm.qq.com/cgi-bin/qm/qr?k=RD4TmYWeZmHX5jQDPlbO0iZkNbDzprrP&jump_from=webapi"
    "&authKey=nhf6qrpsOxIAydLdyaEWvP3Y+Sbv5bdEs8Vvqbx7lpfRXYD9Vb+iGsBHhEsuUUtS"
)


def _app_version() -> str:
    from spritelens import __version__

    return __version__


def render_index_html(html: str) -> str:
    """首屏注入版本号：窗口标题、页面 title 与关于页由模板占位符一次填好，避免加载后再改文案。"""
    from spritelens import APP_DISPLAY_NAME, APP_NAME

    title = f"{APP_DISPLAY_NAME} {APP_NAME} v{_app_version()}"
    return html.replace("{{APP_TITLE}}", title).replace("{{APP_VERSION}}", _app_version())

STATIC_DIR = Path(__file__).resolve().parent / "static"
PUSH_INTERVAL = 0.5  # 状态推送节拍（秒）
WS_SEND_TIMEOUT = 0.1
WS_SEND_BATCH = 8

# query 解析助手统一在 server_helpers（S04：消除重复定义，锁定原语义）
from spritelens.web.server_helpers import _as_bool, _as_int, _id_set, _name_set  # noqa: E402,F401


def _quiet_connection_reset(loop: asyncio.AbstractEventLoop, context: dict) -> None:
    """连接重置类异常降级：窗口关闭时浏览器先断连属正常收尾，不打堆栈。"""
    exc = context.get("exception")
    if isinstance(exc, (ConnectionResetError, ConnectionAbortedError)):
        logger.debug("连接已断开（收尾阶段，忽略）: %s", exc)
        return
    loop.default_exception_handler(context)


class LocalServer(AccountRoutesMixin, CaptureRoutesMixin, ExtRoutesMixin):
    """本地服务生命周期与路由；start() 后 `url` 可直接交给 pywebview。

    采集域 handler（/api/capture*、/api/state 与 capture/state 载荷）
    由 CaptureRoutesMixin 提供；本类保留鉴权、生命周期、静态页、数据
    API 与 WS 推送（阶段1.4 拆分）。
    """

    def __init__(
        self,
        context: AppContext,
        *,
        token: str | None = None,
        host: str = "127.0.0.1",
        port: int = 0,
        static_dir: Path | None = None,
        ext_runtime_path: Path | None = None,
    ) -> None:
        self._context = context
        from spritelens.web.debug_preview import PreviewManager
        self._preview = PreviewManager()
        self._token = token or secrets.token_urlsafe(32)
        self._host = host
        self._port = port
        self._static_dir = Path(static_dir) if static_dir is not None else STATIC_DIR
        # 对外数据接口（docs/EXT_API.md）：默认开启，配置 ext_api.enabled=false 关闭。
        settings = getattr(context, "settings", None)
        self._ext_enabled = (
            bool(settings.get_bool("ext_api.enabled", True))
            if settings is not None
            else True
        )
        self._ext_runtime_path = (
            Path(ext_runtime_path) if ext_runtime_path is not None else None
        )
        self._ext_token = secrets.token_urlsafe(32)
        self._ext_hub = ExtEventHub(enabled=self._ext_enabled)
        self._ext_listener = lambda event: self._ext_hub.submit(
            event, generation=self._context.monitor.capture_generation)
        self._ext_attached = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._runner: web.AppRunner | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._start_error: Exception | None = None
        self._bound_port: int | None = None
        self._sockets: set[web.WebSocketResponse] = set()
        self._blocking_tasks: set[asyncio.Task] = set()
        self._push_task: asyncio.Task | None = None
        self._last_state_json: str | None = None
        # 宠物摘要按（uid/版本/身份/账号代次）复用，见 CaptureRoutesMixin._pet_summary
        self._pet_summary_cache: tuple[object, dict] | None = None
        self._account_epoch = 0
        self._pet_media_cache: PetMediaCache | None = None
        self._account_avatar_cache: AccountAvatarCache | None = None
        self._egg_icon_cache: EggIconCache | None = None
        self._stopped = False
        self._stop_future = None

    # -- 生命周期 ------------------------------------------------------
    @property
    def token(self) -> str:
        return self._token

    @property
    def port(self) -> int:
        return self._bound_port or 0

    @property
    def host(self) -> str:
        return self._host

    @property
    def url(self) -> str:
        """窗口入口 URL；token 走 fragment（不进日志、不发 Referer）。"""
        if not self._bound_port:
            raise RuntimeError("服务尚未启动")
        return f"http://{self._host}:{self._bound_port}/#token={self._token}"

    @property
    def running(self) -> bool:
        return self._runner is not None and not self._stopped

    @property
    def ext_token(self) -> str:
        """对外数据接口的独立 token（与 UI token 分离）。"""
        return self._ext_token

    @property
    def ext_enabled(self) -> bool:
        return self._ext_enabled

    @property
    def ext_runtime_path(self) -> Path | None:
        return self._ext_runtime_path

    def start(self, *, timeout: float = 15.0) -> None:
        """启动后台事件循环并等待端口就绪（失败抛异常，由入口决定提示）。

        超时回收（D06）：超时后走确定性取消握手，覆盖三种到达时机——
        loop 未创建（_run_loop 入口直接退出）、启动中（loop.stop 让
        run_until_complete 抛出并清理半成品 runner）、绑定后（启动完成
        前复查 _stopped，转入 _shutdown 后退出，不进入 run_forever）。
        后台线程未在回收预算内退出时保留句柄供 stop 重试。
        """
        if self._thread is not None:
            raise RuntimeError("服务已启动")
        self._thread = threading.Thread(target=self._run_loop, name="spritelens-http", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            logger.error("本地服务启动超时（%ss），回收后台启动", timeout)
            self._abort_start()
            raise TimeoutError(f"本地服务启动超时（{timeout}s）")
        if self._start_error is not None:
            self._thread.join(timeout=5.0)
            if not self._thread.is_alive():
                self._thread = None
            raise self._start_error
        logger.info("本地服务已启动: http://%s:%d", self._host, self._bound_port or 0)

    def _abort_start(self) -> None:
        """启动超时的取消握手：停 loop、等线程退出（有界）、清句柄。"""
        self._stopped = True
        loop = self._loop
        if loop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(loop.stop)
            except RuntimeError:
                pass  # 循环已关闭：不再触碰
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5.0)
            if thread.is_alive():
                logger.warning("启动线程未在回收预算内退出；保留句柄供 stop 重试")
                return
        self._thread = None
        self._loop = None
        self._runner = None

    def stop(self, *, timeout: float = 5.0) -> None:
        """线程拥有清理；等待超时保留句柄与同一停止任务，允许重试。"""
        thread = self._thread
        if thread is None:
            return
        self._stopped = True
        loop = self._loop
        if loop is not None and not loop.is_closed():
            if self._stop_future is None:
                shutdown = self._stop_async()
                try:
                    self._stop_future = asyncio.run_coroutine_threadsafe(shutdown, loop)
                except RuntimeError:
                    shutdown.close()  # 与启动失败收尾的 loop.close 竞态
                    if not loop.is_closed():
                        raise
        thread.join(timeout=timeout)
        if thread.is_alive():
            raise TimeoutError("本地服务停止超时，保留线程和资源，等待重试")
        if self._stop_future is not None and self._stop_future.done():
            try:
                self._stop_future.result()
            except Exception as exc:
                logger.warning("本地服务停止异常: %s", exc)
        self._thread = None
        self._loop = None
        self._runner = None
        self._stop_future = None

    async def _stop_async(self) -> None:
        try:
            await self._shutdown()
        finally:
            # 留出当前协程完成与 future 传递结果的一拍，不截断 runner.cleanup。
            asyncio.get_running_loop().call_soon(asyncio.get_running_loop().stop)

    def _run_loop(self) -> None:
        if self._stopped:  # 超时发生在 loop 创建前：不进入启动
            self._ready.set()
            return
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        # 窗口关闭时浏览器会先断开连接，asyncio 默认处理器会把它当异常打印
        # （WinError 10054）；本地服务下这是正常收尾，降为 debug 级。
        loop.set_exception_handler(_quiet_connection_reset)
        if self._stopped:  # 创建与检查之间的竞态窗口：不绑定
            self._ready.set()
            loop.close()
            return
        try:
            loop.run_until_complete(self._start_async())
        except Exception as exc:  # noqa: BLE001 - 启动失败转给 start()
            if not self._stopped:  # 取消算不上启动错误
                self._start_error = exc
            self._ready.set()
            self._finish_start_abort(loop)
            loop.close()
            return
        if self._stopped:
            # 绑定完成但已被判超时：立即清整退出，绝不进入 run_forever
            self._finish_start_abort(loop)
            self._ready.set()
            loop.close()
            return
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            # 兜底（D06）：正常 stop 已清理过则 no-op；取消/异常路径确保
            # runner 不随本地变量残留（socket 随 loop 关闭前回收）
            self._finish_start_abort(loop)
            loop.close()

    def _finish_start_abort(self, loop: asyncio.AbstractEventLoop) -> None:
        """启动取消/超时后的收尾：取消未完成任务 → 清 runner。

        取消路径下 run_until_complete 被 loop.stop 打断，_start_async 与
        push_loop 任务可能仍 pending；loop.close 前必须取消并让它们退出，
        否则报 "Task was destroyed but it is pending" 且协程资源不回收。
        """
        self._detach_ext_listener()
        self._clear_ext_runtime()
        if self._push_task is not None:
            self._push_task.cancel()
            self._push_task = None
        if not loop.is_closed() and not loop.is_running():
            try:
                pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
            except RuntimeError:
                pending = []
            if pending:
                for task in pending:
                    task.cancel()
                try:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
                except Exception:  # noqa: BLE001 - 收尾失败不阻断关闭
                    pass
        self._cleanup_partial_runner(loop)
        # Windows Proactor 的 socket/transport close 通过下一轮回调完成。
        if not loop.is_closed():
            loop.run_until_complete(asyncio.sleep(0))

    def _cleanup_partial_runner(self, loop: asyncio.AbstractEventLoop) -> None:
        """清理启动中途留下的 runner/site（取消或异常路径）。"""
        runner = self._runner
        if runner is None or loop.is_closed() or loop.is_running():
            return
        try:
            loop.run_until_complete(runner.cleanup())
            self._runner = None
        except Exception as exc:  # noqa: BLE001 - 清理失败不阻断退出
            logger.debug("半成品 runner 清理异常: %s", exc)

    # -- 对外数据接口（ext API，见 docs/EXT_API.md）---------------------
    def _write_ext_runtime(self) -> None:
        """把端口/独立 token 原子写入发现文件；仅入口显式给路径时写。"""
        path = self._ext_runtime_path
        if not self._ext_enabled or path is None or not self._bound_port:
            return
        payload = {
            "app": "SpriteLens",
            "version": _app_version(),
            "api": EXT_API_VERSION,
            "pid": os.getpid(),
            "host": self._host,
            "port": self._bound_port,
            "base": f"http://{self._host}:{self._bound_port}",
            "token": self._ext_token,
            "endpoints": {
                "ping": "/api/ext/v1/ping",
                "state": "/api/ext/v1/state",
                "events": "/api/ext/v1/events",
                "stream": "/api/ext/v1/stream",
            },
            "opcodes_default": [
                f"0x{opcode:04X}" for opcode in sorted(DEFAULT_EXT_OPCODES)
            ],
            "started_at": time.time(),
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(path)
            logger.info(
                "对外数据接口已就绪: http://%s:%d/api/ext/v1/",
                self._host,
                self._bound_port,
            )
        except OSError as exc:
            logger.warning("对外数据接口发现文件写入失败：%s", exc)

    def _clear_ext_runtime(self) -> None:
        path = self._ext_runtime_path
        if path is None:
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(payload, dict) or payload.get("token") != self._ext_token:
            return
        try:
            path.unlink()
        except OSError as exc:
            logger.debug("对外数据接口发现文件清理失败：%s", exc)

    def _attach_ext_listener(self) -> None:
        """挂到采集管线；回调只做内存聚合与入队，不做 IO。"""
        if not self._ext_enabled or self._ext_attached:
            return
        monitor = getattr(self._context, "monitor", None)
        if monitor is None:
            return
        monitor.add_packet_listener(self._ext_listener)
        monitor.add_session_close_listener(self._ext_hub.session_closed)
        self._ext_attached = True

    def _detach_ext_listener(self) -> None:
        if not self._ext_attached:
            return
        self._ext_attached = False
        monitor = getattr(self._context, "monitor", None)
        if monitor is not None:
            monitor.remove_packet_listener(self._ext_listener)
            monitor.remove_session_close_listener(self._ext_hub.session_closed)

    async def _start_async(self) -> None:
        self._pet_media_cache = PetMediaCache(
            self._static_dir,
            data_root() / "pet-media-cache",
            static_data_dir() / "pet_media_manifest.json",
        )
        self._account_avatar_cache = AccountAvatarCache(
            self._static_dir, data_root() / "account-avatar-cache"
        )
        self._egg_icon_cache = EggIconCache(
            self._static_dir, data_root() / "egg-icon-cache"
        )
        app = web.Application(
            middlewares=[self._auth_middleware, self._no_cache_middleware],
            client_max_size=8 * 1024 * 1024,
        )
        app[RUN_BLOCKING] = self._run_blocking
        app.router.add_get("/", self._index)
        app.router.add_get("/favicon.ico", self._favicon)
        app.router.add_get("/static/pet-media/{asset}", self._pet_media_asset)
        app.router.add_get("/static/account-avatars/{asset}", self._account_avatar_asset)
        # 蛋图标：安装包内的同名文件直接命中；新版本蛋缺图时按道具 ID 补一次并缓存
        app.router.add_get("/static/egg-icons/{asset}", self._egg_icon_asset)
        app.router.add_static("/static", self._static_dir, name="static")
        app.router.add_post("/api/debug-preview/start", self._api_debug_preview_start)
        app.router.add_post("/api/debug-preview/stop", self._api_debug_preview_stop)
        app.router.add_get("/api/bootstrap", self._api_bootstrap)
        app.router.add_get("/api/accounts", self._api_accounts)
        app.router.add_post("/api/accounts/select", self._api_accounts_select)
        app.router.add_get("/api/ui/preferences", self._api_ui_preferences)
        app.router.add_post("/api/ui/preferences", self._api_save_ui_preferences)
        app.router.add_post("/api/ui/open-browser", self._api_open_browser)
        app.router.add_post("/api/ui/open-qq-group", self._api_open_qq_group)
        app.router.add_get("/api/pets", self._api_pets)
        app.router.add_get(r"/api/pets/{gid:\d+}", self._api_pet_detail)
        app.router.add_get("/api/handbook", self._api_handbook)
        app.router.add_get("/api/eggs", self._api_eggs)
        app.router.add_get("/api/egg-box", self._api_egg_box)
        app.router.add_post("/api/egg-box/annotations", self._api_save_egg_annotations)
        app.router.add_post("/api/egg-box/favorite", self._api_save_egg_favorite)
        app.router.add_get("/api/home", self._api_home)
        register_nearby_routes(
            app, self._context.scene_repository, self._context.static_data, self._context.settings
        )
        register_world_map_routes(app)
        register_collection_routes(app, self._context)
        register_breeder_routes(app, self._context)
        register_planner_routes(app, self._context)
        app.router.add_get("/api/colors", self._api_colors)
        app.router.add_get("/api/capture", self._api_capture)
        app.router.add_post("/api/capture/environment", self._api_capture_environment)
        app.router.add_get("/api/capture/ifaces", self._api_capture_ifaces)
        app.router.add_post("/api/capture/iface", self._api_capture_iface)
        app.router.add_post("/api/capture/start", self._api_capture_start)
        app.router.add_post("/api/capture/stop", self._api_capture_stop)
        app.router.add_post("/api/capture/recording", self._api_capture_recording)
        app.router.add_post("/api/capture/autostart", self._api_capture_autostart)
        app.router.add_post("/api/capture/automation", self._api_capture_automation)
        app.router.add_post("/api/capture/key", self._api_capture_key)
        app.router.add_post("/api/capture/npcap/install", self._api_npcap_install)
        app.router.add_post("/api/capture/rsc", self._api_rsc)
        app.router.add_get("/api/state", self._api_state)
        app.router.add_get("/api/ext/v1/ping", self._api_ext_ping)
        app.router.add_get("/api/ext/v1/state", self._api_ext_state)
        app.router.add_get("/api/ext/v1/events", self._api_ext_events)
        app.router.add_get("/api/ext/v1/stream", self._api_ext_stream)
        app.router.add_get("/ws", self._ws)

        runner = web.AppRunner(app, access_log=None)
        # 先登记 runner（D06）：启动中途被取消/超时时，_cleanup_partial_runner
        # 才能找到半成品并 cleanup；等待点在 setup 与 site.start 之间
        self._runner = runner
        await runner.setup()
        if self._stopped:
            raise RuntimeError("启动已被取消（超时回收）")
        site = web.TCPSite(runner, self._host, self._port)
        await site.start()
        if self._stopped:
            raise RuntimeError("启动已被取消（超时回收）")
        addresses = getattr(runner, "addresses", None) or []
        if addresses:
            self._bound_port = int(addresses[0][1])
        else:  # 兜底：从套接字取（旧版 aiohttp 没有 addresses）
            sockets = getattr(getattr(site, "_server", None), "sockets", None) or []
            self._bound_port = int(sockets[0].getsockname()[1])
        loop = asyncio.get_running_loop()
        self._attach_ext_listener()
        self._write_ext_runtime()
        self._push_task = loop.create_task(self._push_loop())

    async def _shutdown(self) -> None:
        self._detach_ext_listener()
        self._ext_hub.close()
        self._clear_ext_runtime()
        await asyncio.to_thread(self._preview.stop)
        if self._push_task is not None:
            self._push_task.cancel()
            try:
                await self._push_task
            except (asyncio.CancelledError, Exception):  # noqa: B014 - 取消属正常路径
                pass
            self._push_task = None
        for ws in list(self._sockets):
            try:
                await asyncio.wait_for(
                    ws.close(code=WSMsgType.CLOSE, message=b"server shutdown"),
                    timeout=WS_SEND_TIMEOUT,
                )
            except Exception:  # noqa: BLE001
                pass
        self._sockets.clear()
        runner = self._runner
        if runner is not None:
            await runner.cleanup()
            self._runner = None  # cleanup 完成前由 loop 唯一持有
        for cache in (self._pet_media_cache, self._account_avatar_cache, self._egg_icon_cache):
            if cache is not None:
                await cache.close()
        self._pet_media_cache = None
        self._account_avatar_cache = None
        self._egg_icon_cache = None
        if self._blocking_tasks:
            await asyncio.gather(*list(self._blocking_tasks), return_exceptions=True)
        await asyncio.sleep(0)
        logger.info("本地服务已停止")

    # -- 鉴权 ----------------------------------------------------------
    @web.middleware
    async def _auth_middleware(self, request: web.Request, handler):
        path = request.path
        if path.startswith("/api/ext/"):
            supplied = request.headers.get("X-Local-Token") or request.query.get("token") or ""
            if not self._ext_token_ok(supplied):
                return web.json_response({"error": "unauthorized"}, status=401)
        elif path.startswith("/api/") or path == "/ws":
            supplied = request.headers.get("X-Local-Token") or request.query.get("token") or ""
            if not self._token_ok(supplied):
                return web.json_response({"error": "unauthorized"}, status=401)
        if os.environ.get("SPRITELENS_DEBUG_PREVIEW") == "1" and request.method != "GET":
            if path.startswith("/api/capture/") or path.startswith("/api/debug-preview/") or path in ("/api/ui/open-browser", "/api/ui/open-qq-group"):
                return web.json_response({"error": "预览模式不能执行系统操作"}, status=403)
        return await handler(request)

    def _token_ok(self, supplied: str) -> bool:
        try:
            return secrets.compare_digest(supplied.encode("utf-8"), self._token.encode("utf-8"))
        except Exception:  # noqa: BLE001 - 畸形输入一律拒绝
            return False

    def _ext_token_ok(self, supplied: str) -> bool:
        try:
            return secrets.compare_digest(
                supplied.encode("utf-8"), self._ext_token.encode("utf-8")
            )
        except Exception:  # noqa: BLE001 - 畸形输入一律拒绝
            return False

    # -- 静态页 --------------------------------------------------------
    async def _index(self, request: web.Request) -> web.Response:
        from spritelens.web.frontend_assets import check_frontend_assets
        failures = check_frontend_assets(self._static_dir / "vue")
        if failures:
            return web.Response(status=500, text="\n".join(failures))
        path = self._static_dir / "index.html"
        if not path.is_file():
            return web.Response(status=500, text="前端资源缺失：static/index.html")
        html = await asyncio.to_thread(path.read_text, encoding="utf-8")
        return web.Response(text=render_index_html(html), content_type="text/html",
                            headers={"Cache-Control": "no-cache"})

    async def _favicon(self, request: web.Request) -> web.Response:
        """浏览器标签页图标；缺图时回 204 不留 404 噪声。"""
        icon = self._static_dir / "favicon.png"
        if not icon.is_file():
            return web.Response(status=204)
        return web.FileResponse(icon, headers={"Cache-Control": "no-cache"})

    async def _pet_media_asset(self, request: web.Request) -> web.Response:
        """先读安装包/用户缓存，缺图时按需下载官方 CDN 素材。"""
        if self._pet_media_cache is None:
            raise RuntimeError("精灵图片缓存尚未初始化")
        path = await self._pet_media_cache.resolve(request.match_info["asset"])
        if path is None:
            return web.Response(status=404)
        return web.FileResponse(path)

    async def _account_avatar_asset(self, request: web.Request) -> web.Response:
        """头像只按需从映射的云端来源下载，成功后读用户缓存。"""
        if self._account_avatar_cache is None:
            raise RuntimeError("账号头像缓存尚未初始化")
        path = await self._account_avatar_cache.resolve(request.match_info["asset"])
        if path is None:
            return web.Response(status=404)
        return web.FileResponse(path)

    async def _egg_icon_asset(self, request: web.Request) -> web.Response:
        """蛋图标先查安装包，缺图的新蛋按道具 ID 补一次再缓存；失败交给占位图。"""
        if self._egg_icon_cache is None:
            raise RuntimeError("蛋图标缓存尚未初始化")
        path = await self._egg_icon_cache.resolve(request.match_info["asset"])
        if path is None:
            return web.Response(status=404)
        # Windows 的 mime 表未必认识 webp，显式声明避免回成 octet-stream
        return web.FileResponse(path, headers={"Content-Type": "image/webp"})

    @web.middleware
    async def _no_cache_middleware(self, request: web.Request, handler):
        """本地单机应用：每次都要重新校验，但不禁止条件请求。

        页面与 API 用 no-store；静态资源用 no-cache：浏览器仍会重新校验，
        改前端后刷新照旧生效（WebView2/浏览器缓存曾让改动静默失效），
        但底图等大文件未变化时可命中 304，不必每次重传数 MB。
        """
        response = await handler(request)
        if request.path == "/":
            response.headers["Cache-Control"] = "no-store"
        elif request.path.startswith("/static"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    # -- 数据 API ------------------------------------------------------
    async def _api_debug_preview_start(self, request: web.Request) -> web.Response:
        try:
            url = await self._run_blocking(self._preview.start)
            return web.json_response({"url": url})
        except (OSError, RuntimeError, TimeoutError) as exc:
            logger.exception("启动调试预览失败")
            return web.json_response({"error": f"启动调试预览失败：{exc}"}, status=500)

    async def _api_debug_preview_stop(self, request: web.Request) -> web.Response:
        try:
            await self._run_blocking(self._preview.stop)
            return web.json_response({"ok": True})
        except (OSError, RuntimeError, TimeoutError) as exc:
            logger.exception("关闭调试预览失败")
            return web.json_response({"error": f"关闭调试预览失败：{exc}"}, status=500)

    async def _api_bootstrap(self, request: web.Request) -> web.Response:
        try:
            return await self._thread_json_response(self._bootstrap_payload)
        except sqlite3.Error:
            logger.exception("启动数据读取失败")
            return web.json_response({"error": "本地数据读取失败，请检查数据库"}, status=500)

    def _bootstrap_payload(self) -> dict:
        ctx = self._context
        from spritelens.view_models.pet_vm import PetFilters
        view = ctx.pet_vm.view_with(PetFilters())
        payload = {
            "app": {
                "name": "SpriteLens",
                "display_name": "小洛探探",
                "version": _app_version(),
            },
            "pets": pets_payload(view, ctx.static_data, ctx.color_catalog, ctx.egg_catalog),
            "capture": self._capture_payload(),
            "state": self._state_payload(view),
            "ui_preferences": UIPreferencesViewModel(ctx.settings).snapshot(),
        }
        return payload

    async def _thread_json_response(self, build_payload) -> web.Response:
        """在线程池完成同步载荷构造和 JSON 编码，避免阻塞 aiohttp 事件循环。"""
        body = await self._run_blocking(
            lambda: json.dumps(build_payload(), ensure_ascii=False, separators=(",", ":"))
        )
        return web.Response(text=body, content_type="application/json")

    async def _run_blocking(self, function, *args, **kwargs):
        """跟踪同步工作；HTTP 取消后仍等线程结束再释放组合根资源。"""
        task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
        self._blocking_tasks.add(task)
        task.add_done_callback(self._blocking_tasks.discard)
        return await asyncio.shield(task)

    async def _api_ui_preferences(self, request: web.Request) -> web.Response:
        return web.json_response(UIPreferencesViewModel(self._context.settings).snapshot())

    async def _api_open_browser(self, request: web.Request) -> web.Response:
        # 使用服务自身的入口，携带 fragment token；不接受客户端指定任意 URL。
        try:
            opened = await self._run_blocking(webbrowser.open, self.url, new=2)
        except (OSError, webbrowser.Error):
            logger.exception("打开系统浏览器失败")
            opened = False
        if not opened:
            return web.json_response(
                {"error": "无法打开默认浏览器，请检查系统默认浏览器设置后重试"}, status=503
            )
        return web.json_response({"ok": True})

    async def _api_open_qq_group(self, request: web.Request) -> web.Response:
        try:
            opened = await self._run_blocking(webbrowser.open, QQ_GROUP_JOIN_URL, new=2)
        except (OSError, webbrowser.Error):
            logger.exception("打开 QQ 群加入页面失败")
            opened = False
        if not opened:
            return web.json_response(
                {"error": "无法打开 QQ 加群页面，请复制群号后在 QQ 中搜索"}, status=503
            )
        return web.json_response({"ok": True})

    async def _api_save_ui_preferences(self, request: web.Request) -> web.Response:
        try:
            changes = await request.json()
            result = await self._run_blocking(UIPreferencesViewModel(self._context.settings).update, changes)
            return web.json_response(result)
        except (ValueError, TypeError):
            return web.json_response({"error": "偏好格式无效，请检查主题、视图、显示字段或快捷条件"}, status=400)
        except OSError:
            return web.json_response({"error": "偏好保存失败，请检查配置目录是否可写"}, status=500)

    async def _api_pets(self, request: web.Request) -> web.Response:
        # 请求级查询（R08）：条件构造为不可变 PetFilters，经一次性视图
        # 出载荷，不写共享 VM——无参请求、bootstrap 与多客户端互不污染；
        # 保留 app.js 的请求序号机制防止旧响应覆盖新结果
        query = request.query
        return await self._thread_json_response(
            lambda: self._pets_payload_for_query(query)
        )

    def _pets_payload_for_query(self, query) -> dict:
        view = self._pet_view_from_query(query)
        return pets_payload(
            view, self._context.static_data, self._context.color_catalog, self._context.egg_catalog,
            include_options=query.get("options_version") != str(view.version()),
        )

    async def _api_pet_detail(self, request: web.Request) -> web.Response:
        try:
            uid = int(request.query["uid"])
            version = int(request.query["version"])
            gid = int(request.match_info["gid"])
        except (KeyError, ValueError):
            return web.json_response({"error": "账号、精灵编号或版本无效"}, status=400)
        if uid < 0 or gid <= 0 or version < 0:
            return web.json_response({"error": "账号、精灵编号或版本无效"}, status=400)
        status, payload = await self._run_blocking(self._pet_detail_payload, uid, version, gid)
        if status != 200:
            return web.json_response(payload, status=status)
        return await self._thread_json_response(lambda: payload)

    def _pet_detail_payload(self, uid: int, version: int, gid: int) -> tuple[int, dict]:
        ctx = self._context
        snapshot = ctx.pet_repository.consistent_snapshot()
        if snapshot.uid != uid or snapshot.version < version:
            return 409, {"error": "精灵数据已更新，请刷新列表"}
        pet = next((item for item in snapshot.pets if item.gid == gid), None)
        if pet is None:
            return 404, {"error": "找不到该账号下的精灵"}
        location = snapshot.locations.get(gid)
        location_payload = location.payload() if location else None
        if location_payload is None:
            for team in snapshot.backpack.teams:
                if gid in team.slots:
                    location_payload = {
                        "team_id": team.box_id,
                        "slot": team.slots.index(gid) + 1,
                        "historical": team.historical,
                    }
                    break
        detail = pet_row(
            pet, ctx.static_data,
            max((item.height for item in snapshot.pets), default=0),
            max((item.weight for item in snapshot.pets), default=0),
            ctx.color_catalog, ctx.egg_catalog,
        )
        detail["location"] = location_payload
        return 200, {"uid": snapshot.uid, "version": snapshot.version, "gid": gid, "pet": detail}

    async def _api_save_egg_annotations(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except (ValueError, TypeError):
            return web.json_response({"error": "标签数据格式无效"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"error": "标签数据格式无效"}, status=400)
        uid, instance_id = body.get("uid"), body.get("instance_id")
        nature_id = body.get("nature_id", 0)
        nest = body.get("nest_override", "")
        note = body.get("note", "")
        voice_tag = body.get("voice_tag", "")
        voice_db = body.get("voice_db")
        valid_natures = (
            {nature_id for nature_id, _ in self._context.static_data.nature_items()}
            if self._context.static_data else set()
        )
        if type(uid) is not int or uid <= 0 or type(instance_id) is not int or instance_id <= 0 \
                or type(nature_id) is not int or nature_id != 0 and nature_id not in valid_natures \
                or nest not in ("", "normal", "green") \
                or not isinstance(note, str) or len(note) > 500 \
                or voice_tag not in ("", "婉转声", "满分", "粗嗓门", "底分") \
                or not (voice_db is None or type(voice_db) is int and -100 <= voice_db <= 100):
            return web.json_response({"error": "性格、窝类型、备注、声音标签或分贝值无效"}, status=400)
        repository = self._context.egg_box
        if self._context.egg_store is None or repository is None:
            return web.json_response({"error": "蛋仓存储不可用"}, status=503)
        try:
            await self._run_blocking(
                repository.save_annotations,
                uid, instance_id, nature_id, nest, note, voice_tag, voice_db,
            )
        except KeyError:
            return web.json_response({"error": "找不到该账号下的蛋"}, status=404)
        except sqlite3.Error:
            logger.exception("保存蛋仓标注失败")
            return web.json_response({"error": "保存标注失败，请检查本地数据库"}, status=500)
        return web.json_response({"uid": uid, "instance_id": instance_id})

    async def _api_save_egg_favorite(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except (ValueError, TypeError):
            return web.json_response({"error": "收藏数据格式无效"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"error": "收藏数据格式无效"}, status=400)
        uid, instance_id, favorite = body.get("uid"), body.get("instance_id"), body.get("favorite")
        if type(uid) is not int or uid <= 0 or type(instance_id) is not int or instance_id <= 0 \
                or type(favorite) is not bool:
            return web.json_response({"error": "账号、蛋编号或收藏状态无效"}, status=400)
        repository = self._context.egg_box
        if self._context.egg_store is None or repository is None:
            return web.json_response({"error": "蛋仓存储不可用"}, status=503)
        try:
            await self._run_blocking(repository.save_favorite, uid, instance_id, favorite)
        except KeyError:
            return web.json_response({"error": "找不到该账号下的蛋"}, status=404)
        except sqlite3.Error:
            logger.exception("保存蛋仓收藏失败")
            return web.json_response({"error": "保存收藏失败，请检查本地数据库"}, status=500)
        return web.json_response({"uid": uid, "instance_id": instance_id, "favorite": favorite})

    def _pet_view_from_query(self, query):
        """HTTP query → 不可变筛选 + 一次性视图（无共享状态写入）。"""
        from spritelens.view_models.pet_vm import PetFilters

        from spritelens.web.pet_queries import pet_ui_query
        try:
            ui_conditions = pet_ui_query(query)
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        filters = PetFilters(
            search=(query.get("search") or "").strip().lower(),
            level_min=max(1, min(60, _as_int(query.get("level_min"), 1), _as_int(query.get("level_max"), 60))),
            level_max=min(60, max(1, _as_int(query.get("level_min"), 1), _as_int(query.get("level_max"), 60))),
            natures=frozenset(_id_set(query.get("natures"))),
            type_names=frozenset(_name_set(query.get("types"))),
            talent_min=max(0, _as_int(query.get("talent_min"), 0)),
            gender=(lambda g: g if g in (1, 2) else 0)(_as_int(query.get("gender"), 0)),
            egg_groups=frozenset(_name_set(query.get("egg_groups"))),
            egg_mode="all" if query.get("egg_mode") == "all" else "any",
            **ui_conditions,
        )
        vm = self._context.pet_vm
        measurement = vm.measurement_query(**{key: query.get(key) for key in (
            "height_min", "height_max", "weight_min", "weight_max", "voice_min", "voice_max",
            "height_position_min", "height_position_max", "weight_position_min", "weight_position_max")})
        filters = replace(filters, **measurement)
        sort_key = query.get("sort") or "dex_no"
        return vm.view_with(filters, sort_key, descending=_as_bool(query.get("desc")))

    async def _api_handbook(self, request: web.Request) -> web.Response:
        query = request.query
        return await self._thread_json_response(lambda: handbook_payload(
                self._context.static_data,
                self._context.egg_catalog,
                search=query.get("search", ""),
                type_name=query.get("type", ""),
                stage=_as_int(query.get("stage"), 0),
                egg_group=query.get("egg_group", ""),
                sort=query.get("sort", "dex"),
                details=_as_bool(query.get("details")),
            ))

    async def _api_eggs(self, request: web.Request) -> web.Response:
        query = request.query
        return await self._thread_json_response(lambda: egg_dex_payload(
                self._context.egg_catalog,
                static=self._context.static_data,
                search=query.get("search", ""),
                group=query.get("group", ""),
                egg_type=query.get("egg_type", ""),
                hatch_min_hours=_as_int(query.get("hatch_min_hours"), 0),
                details=_as_bool(query.get("details")),
            ))

    async def _api_egg_box(self, request: web.Request) -> web.Response:
        try:
            return await self._thread_json_response(self._egg_box_payload)
        except sqlite3.Error:
            logger.exception("蛋仓数据读取失败")
            return web.json_response({"error": "蛋仓数据读取失败，请检查本地数据库"}, status=500)

    def _egg_box_payload(self) -> dict:
        ctx = self._context
        view = ctx.egg_box.consistent_snapshot() if ctx.egg_box is not None else None
        uid = view.uid if view is not None else 0
        pets = ctx.pet_repository.consistent_snapshot().pets if ctx.pet_repository is not None else ()
        return egg_box_payload(
            view, ctx.egg_catalog,
            static=ctx.static_data,
            annotations=ctx.egg_box.annotations(uid) if ctx.egg_box is not None else {},
            nature_options=tuple((key, info.name) for key, info in ctx.static_data.nature_items()) if ctx.static_data else (),
            # 亲代声音推算蛋的声音：需要 gid → voice，宠物快照里取
            pet_voices={pet.gid: pet.voice for pet in pets},
        )

    async def _api_home(self, request: web.Request) -> web.Response:
        return await self._thread_json_response(lambda: home_payload(
                         self._context.home_repo, self._context.static_data,
                         self._context.pet_repository, self._context.egg_catalog)
        )

    async def _api_colors(self, request: web.Request) -> web.Response:
        return await self._thread_json_response(lambda: colors_payload(
                self._context.pet_repository,
                self._context.color_catalog,
                self._context.static_data,
            ))

    @staticmethod
    async def _json_body(request: web.Request) -> dict:
        """解析 JSON 命令体；非对象/坏 JSON 抛 ValueError 由 handler 转 400（S04）。

        旧实现把非法输入静默降级为 {}，`{"enabled":"false"}` 之类一路
        200 成功——命令契约必须显式拒绝而非猜默认值。
        """
        try:
            data = await request.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError("请求体不是有效的 JSON") from exc
        if not isinstance(data, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return data

    @staticmethod
    def _require_bool(body: dict, key: str) -> bool:
        """提取必填布尔字段（严格类型：字符串 "false" 不是布尔）。"""
        value = body.get(key)
        if not isinstance(value, bool):
            raise ValueError(f"字段 {key} 必须是布尔值")
        return value

    # -- 状态推送 ------------------------------------------------------
    async def _push_loop(self) -> None:
        while True:
            try:
                await self._push_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - 推送失败不拖垮服务
                logger.debug("状态推送异常: %s", exc)
            await asyncio.sleep(PUSH_INTERVAL)

    async def _push_once(self) -> None:
        """一拍推送：无人订阅时只推进场景插值，跳过整份状态构造与编码（PERF07）。"""
        if not self._sockets:
            await self._run_blocking(self._advance_scene)
            return
        payload = await self._run_blocking(self._push_payload)
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if encoded != self._last_state_json:
            self._last_state_json = encoded
            await self._broadcast(encoded)

    def _advance_scene(self) -> None:
        """推进一次移动插值（只发生在写路径，GET 只读快照）。"""
        scene = self._context.scene_repository
        if scene is not None:
            scene.advance()

    def _push_payload(self) -> dict:
        self._advance_scene()
        return self._state_payload()

    async def _broadcast(self, text: str) -> None:
        sockets = list(self._sockets)
        for start in range(0, len(sockets), WS_SEND_BATCH):
            batch = sockets[start:start + WS_SEND_BATCH]
            await asyncio.gather(*(self._send_socket(ws, text) for ws in batch))

    async def _send_socket(self, ws: web.WebSocketResponse, text: str) -> None:
        if ws.closed:
            self._sockets.discard(ws)
            return
        try:
            await asyncio.wait_for(ws.send_str(text), timeout=WS_SEND_TIMEOUT)
        except Exception:  # noqa: BLE001 - 单连接异常或超时不拖住其他连接
            self._sockets.discard(ws)
            try:
                await asyncio.wait_for(ws.close(), timeout=WS_SEND_TIMEOUT)
            except Exception:  # noqa: BLE001 - 关闭本身也必须有预算
                pass

    async def _ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        self._sockets.add(ws)
        # 连上先给一份当前状态，前端不必等下一拍
        try:
            await asyncio.wait_for(
                ws.send_str(json.dumps(await self._run_blocking(self._state_payload), ensure_ascii=False, separators=(",", ":"))),
                timeout=WS_SEND_TIMEOUT,
            )
        except Exception:  # noqa: BLE001
            self._sockets.discard(ws)
            try:
                await asyncio.wait_for(ws.close(), timeout=WS_SEND_TIMEOUT)
            except Exception:  # noqa: BLE001
                pass
            return ws
        try:
            async for message in ws:
                if message.type == WSMsgType.ERROR:
                    break
        finally:
            self._sockets.discard(ws)
        return ws


__all__ = ["LocalServer", "PUSH_INTERVAL", "STATIC_DIR"]
