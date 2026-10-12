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
import secrets
import threading
from dataclasses import replace
from pathlib import Path

from aiohttp import WSMsgType, web

from spritelens.app_context import AppContext
from spritelens.logs import get_logger
from spritelens.view_models.ui_preferences import UIPreferencesViewModel
from spritelens.web.payloads import (
    overview_payload,
    pets_payload,
    type_color_for,
)
from spritelens.web.payloads_catalog import (
    egg_box_payload,
    egg_dex_payload,
    flowers_payload,
    colors_payload,
    handbook_payload,
    home_payload,
    male_matrix_payload,
)
from spritelens.web.routes_capture import CaptureRoutesMixin

logger = get_logger("web")


def _app_version() -> str:
    from spritelens import __version__

    return __version__

STATIC_DIR = Path(__file__).resolve().parent / "static"
PUSH_INTERVAL = 0.5  # 状态推送节拍（秒）

# query 解析助手统一在 server_helpers（路由 mixin 共用）；server 本地保留
# 原实现等价的历史入口（_id_set 的 isdigit 语义比 helpers 宽容版更严格，
# 沿用既有行为避免契约漂移）
from spritelens.web.server_helpers import _as_bool, _as_int, _name_set  # noqa: E402,F401


def _as_int(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _as_bool(value: str | None) -> bool:
    return str(value).lower() in {"1", "true", "yes", "on"}


def _id_set(value: str | None) -> set[int]:
    out: set[int] = set()
    for part in (value or "").split(","):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return out


def _quiet_connection_reset(loop: asyncio.AbstractEventLoop, context: dict) -> None:
    """连接重置类异常降级：窗口关闭时浏览器先断连属正常收尾，不打堆栈。"""
    exc = context.get("exception")
    if isinstance(exc, (ConnectionResetError, ConnectionAbortedError)):
        logger.debug("连接已断开（收尾阶段，忽略）: %s", exc)
        return
    loop.default_exception_handler(context)


class LocalServer(CaptureRoutesMixin):
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
    ) -> None:
        self._context = context
        self._token = token or secrets.token_urlsafe(32)
        self._host = host
        self._port = port
        self._static_dir = Path(static_dir) if static_dir is not None else STATIC_DIR
        self._loop: asyncio.AbstractEventLoop | None = None
        self._runner: web.AppRunner | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._start_error: Exception | None = None
        self._bound_port: int | None = None
        self._sockets: set[web.WebSocketResponse] = set()
        self._push_task: asyncio.Task | None = None
        self._last_state_json: str | None = None
        self._stopped = False

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

    def start(self, *, timeout: float = 15.0) -> None:
        """启动后台事件循环并等待端口就绪（失败抛异常，由入口决定提示）。

        超时回收（S02）：等待超时不能把仍在后台启动的事件循环留在进程
        里——标记停止并请求循环退出，让启动线程尽快收尾。
        """
        if self._thread is not None:
            raise RuntimeError("服务已启动")
        self._thread = threading.Thread(target=self._run_loop, name="spritelens-http", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            # 超时：通知后台循环停止（若它稍后才完成绑定，_shutdown 会收掉）
            logger.error("本地服务启动超时（%ss），回收后台启动", timeout)
            self._stopped = True
            loop = self._loop
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(loop.stop)
            raise TimeoutError(f"本地服务启动超时（{timeout}s）")
        if self._start_error is not None:
            raise self._start_error
        logger.info("本地服务已启动: http://%s:%d", self._host, self._bound_port or 0)

    def stop(self, *, timeout: float = 5.0) -> None:
        """停服务、关事件循环；幂等。"""
        loop = self._loop
        thread = self._thread
        if loop is None or thread is None:
            return
        self._stopped = True
        try:
            future = asyncio.run_coroutine_threadsafe(self._shutdown(), loop)
            future.result(timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - 停止失败不阻断退出
            logger.warning("本地服务停止异常: %s", exc)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=timeout)
        self._thread = None
        self._loop = None
        self._runner = None

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        # 窗口关闭时浏览器会先断开连接，asyncio 默认处理器会把它当异常打印
        # （WinError 10054）；本地服务下这是正常收尾，降为 debug 级。
        loop.set_exception_handler(_quiet_connection_reset)
        try:
            loop.run_until_complete(self._start_async())
        except Exception as exc:  # noqa: BLE001 - 启动失败转给 start()
            self._start_error = exc
            self._ready.set()
            loop.close()
            return
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            loop.close()

    async def _start_async(self) -> None:
        app = web.Application(
            middlewares=[self._auth_middleware, self._no_cache_middleware],
            client_max_size=8 * 1024 * 1024,
        )
        app.router.add_get("/", self._index)
        app.router.add_get("/favicon.ico", self._favicon)
        app.router.add_static("/static", self._static_dir, name="static")
        app.router.add_get("/api/bootstrap", self._api_bootstrap)
        app.router.add_get("/api/ui/preferences", self._api_ui_preferences)
        app.router.add_post("/api/ui/preferences", self._api_save_ui_preferences)
        app.router.add_get("/api/pets", self._api_pets)
        app.router.add_get("/api/handbook", self._api_handbook)
        app.router.add_get("/api/eggs", self._api_eggs)
        app.router.add_get("/api/egg-box", self._api_egg_box)
        app.router.add_get("/api/male-matrix", self._api_male_matrix)
        app.router.add_get("/api/home", self._api_home)
        app.router.add_get("/api/flowers", self._api_flowers)
        app.router.add_get("/api/colors", self._api_colors)
        app.router.add_get("/api/events", self._api_events)
        app.router.add_get("/api/events/detail", self._api_event_detail)
        app.router.add_get("/api/capture", self._api_capture)
        app.router.add_get("/api/capture/ifaces", self._api_capture_ifaces)
        app.router.add_post("/api/capture/iface", self._api_capture_iface)
        app.router.add_post("/api/capture/start", self._api_capture_start)
        app.router.add_post("/api/capture/stop", self._api_capture_stop)
        app.router.add_post("/api/capture/recording", self._api_capture_recording)
        app.router.add_post("/api/capture/autostart", self._api_capture_autostart)
        app.router.add_post("/api/capture/key", self._api_capture_key)
        app.router.add_post("/api/capture/npcap/install", self._api_npcap_install)
        app.router.add_post("/api/capture/rsc", self._api_rsc)
        app.router.add_get("/api/state", self._api_state)
        app.router.add_get("/ws", self._ws)

        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, self._host, self._port)
        await site.start()
        self._runner = runner
        addresses = getattr(runner, "addresses", None) or []
        if addresses:
            self._bound_port = int(addresses[0][1])
        else:  # 兜底：从套接字取（旧版 aiohttp 没有 addresses）
            sockets = getattr(getattr(site, "_server", None), "sockets", None) or []
            self._bound_port = int(sockets[0].getsockname()[1])
        loop = asyncio.get_running_loop()
        self._push_task = loop.create_task(self._push_loop())

    async def _shutdown(self) -> None:
        if self._push_task is not None:
            self._push_task.cancel()
            try:
                await self._push_task
            except (asyncio.CancelledError, Exception):  # noqa: B014 - 取消属正常路径
                pass
            self._push_task = None
        for ws in list(self._sockets):
            try:
                await ws.close(code=WSMsgType.CLOSE, message=b"server shutdown")
            except Exception:  # noqa: BLE001
                pass
        self._sockets.clear()
        if self._runner is not None:
            await self._runner.cleanup()
        logger.info("本地服务已停止")

    # -- 鉴权 ----------------------------------------------------------
    @web.middleware
    async def _auth_middleware(self, request: web.Request, handler):
        path = request.path
        if path.startswith("/api/") or path == "/ws":
            supplied = request.headers.get("X-Local-Token") or request.query.get("token") or ""
            if not self._token_ok(supplied):
                return web.json_response({"error": "unauthorized"}, status=401)
        return await handler(request)

    def _token_ok(self, supplied: str) -> bool:
        try:
            return secrets.compare_digest(supplied.encode("utf-8"), self._token.encode("utf-8"))
        except Exception:  # noqa: BLE001 - 畸形输入一律拒绝
            return False

    # -- 静态页 --------------------------------------------------------
    async def _index(self, request: web.Request) -> web.Response:
        path = self._static_dir / "index.html"
        if not path.is_file():
            return web.Response(status=500, text="前端资源缺失：static/index.html")
        return web.FileResponse(path, headers={"Cache-Control": "no-cache"})

    async def _favicon(self, request: web.Request) -> web.Response:
        """浏览器标签页图标；缺图时回 204 不留 404 噪声。"""
        icon = self._static_dir / "favicon.png"
        if not icon.is_file():
            return web.Response(status=204)
        return web.FileResponse(icon, headers={"Cache-Control": "no-cache"})

    @web.middleware
    async def _no_cache_middleware(self, request: web.Request, handler):
        """本地单机应用：静态资源禁用缓存。

        WebView2 与浏览器的内存/磁盘缓存会让改前端后刷新不生效（实测遇到），
        本地加载代价可忽略，直接 no-store 换掉这类玄学问题。
        """
        response = await handler(request)
        if request.path == "/" or request.path.startswith("/static"):
            response.headers["Cache-Control"] = "no-store"
        return response

    # -- 数据 API ------------------------------------------------------
    async def _api_bootstrap(self, request: web.Request) -> web.Response:
        ctx = self._context
        payload = {
            "app": {
                "name": "SpriteLens",
                "display_name": "小洛探探",
                "version": _app_version(),
            },
            "overview": overview_payload(ctx.pet_vm, ctx.pet_repository, ctx.static_data),
            "pets": pets_payload(ctx.pet_vm, ctx.static_data, ctx.color_catalog, ctx.egg_catalog),
            "capture": self._capture_payload(),
            "state": self._state_payload(),
            "ui_preferences": UIPreferencesViewModel(ctx.settings).snapshot(),
        }
        return web.json_response(payload)

    async def _api_ui_preferences(self, request: web.Request) -> web.Response:
        return web.json_response(UIPreferencesViewModel(self._context.settings).snapshot())

    async def _api_save_ui_preferences(self, request: web.Request) -> web.Response:
        try:
            changes = await request.json()
            result = await asyncio.to_thread(UIPreferencesViewModel(self._context.settings).update, changes)
            return web.json_response(result)
        except (ValueError, TypeError):
            return web.json_response({"error": "偏好格式无效，请检查主题、视图、显示字段或快捷条件"}, status=400)
        except OSError:
            return web.json_response({"error": "偏好保存失败，请检查配置目录是否可写"}, status=500)

    async def _api_pets(self, request: web.Request) -> web.Response:
        # 请求级查询（R08）：条件构造为不可变 PetFilters，经一次性视图
        # 出载荷，不写共享 VM——无参请求、bootstrap 与多客户端互不污染；
        # 保留 app.js 的请求序号机制防止旧响应覆盖新结果
        view = self._pet_view_from_query(request.query)
        return web.json_response(
            pets_payload(view, self._context.static_data, self._context.color_catalog, self._context.egg_catalog)
        )

    def _pet_view_from_query(self, query):
        """HTTP query → 不可变筛选 + 一次性视图（无共享状态写入）。"""
        from spritelens.view_models.pet_vm import PetFilters

        filters = PetFilters(
            search=(query.get("search") or "").strip().lower(),
            level_min=max(1, min(_as_int(query.get("level_min"), 1), _as_int(query.get("level_max"), 100))),
            level_max=max(_as_int(query.get("level_min"), 1), _as_int(query.get("level_max"), 100)),
            natures=frozenset(_id_set(query.get("natures"))),
            type_names=frozenset(_name_set(query.get("types"))),
            talent_min=max(0, _as_int(query.get("talent_min"), 0)),
            gender=(lambda g: g if g in (1, 2) else 0)(_as_int(query.get("gender"), 0)),
            egg_groups=frozenset(_name_set(query.get("egg_groups"))),
            egg_mode="all" if query.get("egg_mode") == "all" else "any",
        )
        vm = self._context.pet_vm
        measurement = vm.measurement_query(**{key: query.get(key) for key in (
            "height_min", "height_max", "weight_min", "weight_max", "voice_min", "voice_max",
            "height_position_min", "height_position_max", "weight_position_min", "weight_position_max")})
        filters = replace(filters, **measurement)
        sort_key = query.get("sort") or "gid"
        return vm.view_with(filters, sort_key, descending=_as_bool(query.get("desc")))

    async def _api_handbook(self, request: web.Request) -> web.Response:
        query = request.query
        return web.json_response(
            handbook_payload(
                self._context.static_data,
                self._context.pet_repository,
                search=query.get("search", ""),
                type_name=query.get("type", ""),
                collected_only=_as_bool(query.get("collected")),
                uncollected_only=_as_bool(query.get("uncollected")),
            )
        )

    async def _api_eggs(self, request: web.Request) -> web.Response:
        query = request.query
        return web.json_response(
            egg_dex_payload(
                self._context.egg_catalog,
                static=self._context.static_data,
                search=query.get("search", ""),
                group=query.get("group", ""),
                egg_type=query.get("egg_type", ""),
                hatch_min_hours=_as_int(query.get("hatch_min_hours"), 0),
            )
        )

    async def _api_egg_box(self, request: web.Request) -> web.Response:
        return web.json_response(
            egg_box_payload(self._context.egg_box, self._context.egg_catalog)
        )

    async def _api_male_matrix(self, request: web.Request) -> web.Response:
        return web.json_response(
            male_matrix_payload(
                self._context.pet_repository,
                self._context.static_data,
                gender=request.query.get("gender", "all"),
            )
        )

    async def _api_home(self, request: web.Request) -> web.Response:
        return web.json_response(
            home_payload(self._context.home_repo, self._context.static_data)
        )

    async def _api_flowers(self, request: web.Request) -> web.Response:
        return web.json_response(
            flowers_payload(
                self._context.flower_repo,
                self._context.static_data,
                self._context.egg_catalog,
                self._context.pet_repository,
            )
        )

    async def _api_colors(self, request: web.Request) -> web.Response:
        return web.json_response(
            colors_payload(
                self._context.pet_repository,
                self._context.color_catalog,
                self._context.static_data,
            )
        )

    async def _api_events(self, request: web.Request) -> web.Response:
        vm = self._context.events_vm
        rows = [
            {
                "index": row.index,
                "time": row.time_text,
                "direction": row.direction,
                "opcode": row.opcode_hex,
                "name": row.opcode_name,
                "payload_len": row.payload_len,
            }
            for row in vm.rows()
        ]
        return web.json_response({"rows": rows, "total": vm.total_events})

    async def _api_event_detail(self, request: web.Request) -> web.Response:
        index = _as_int(request.query.get("index"), -1)
        detail = self._context.events_vm.detail(index)
        return web.json_response({"index": index, "detail": detail})

    @staticmethod
    async def _json_body(request: web.Request) -> dict:
        try:
            data = await request.json()
        except (json.JSONDecodeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    # -- 状态推送 ------------------------------------------------------
    async def _push_loop(self) -> None:
        while True:
            try:
                # 事件行由本循环消费（前端按需拉取行视图）
                self._context.events_vm.drain()
                payload = self._state_payload()
                encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                if encoded != self._last_state_json:
                    self._last_state_json = encoded
                    await self._broadcast(encoded)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - 推送失败不拖垮服务
                logger.debug("状态推送异常: %s", exc)
            await asyncio.sleep(PUSH_INTERVAL)

    async def _broadcast(self, text: str) -> None:
        for ws in list(self._sockets):
            if ws.closed:
                self._sockets.discard(ws)
                continue
            try:
                await ws.send_str(text)
            except Exception:  # noqa: BLE001 - 单个连接异常不影响其他
                self._sockets.discard(ws)

    async def _ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        self._sockets.add(ws)
        # 连上先给一份当前状态，前端不必等下一拍
        try:
            await ws.send_str(
                json.dumps(self._state_payload(), ensure_ascii=False, separators=(",", ":"))
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            async for message in ws:
                if message.type == WSMsgType.ERROR:
                    break
        finally:
            self._sockets.discard(ws)
        return ws


__all__ = ["LocalServer", "PUSH_INTERVAL", "STATIC_DIR"]
