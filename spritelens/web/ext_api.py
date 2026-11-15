"""对外只读数据接口（ext API）：REST 查询 + 事件 WebSocket 推送。

定位：给本机其它程序（meow toolkit 等）提供「协议事实」——战斗/捕获/场景
等事件的原始解码结果，不替代现有 UI 接口。约定与安全边界见 docs/EXT_API.md。

安全：沿用 LocalServer 的 127.0.0.1 回环绑定；使用独立于 UI 的 ext token，
token 只由宿主写入数据目录的 ext-runtime.json（本机用户可读），不进日志。

线程：add_packet_listener 回调在采集管线线程内同步执行且持有管线锁，本模块
`ExtEventHub.submit()` 只做过滤/入队，绝不做 IO 或等待（event_logger 的教训：
曾在锁内同步 flush，登录突发下让事件消费者最长等 57ms）。
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass

from aiohttp import web

from spritelens import APP_DISPLAY_NAME, APP_NAME, __version__
from spritelens.events import PacketEvent
from spritelens.domain.navigation_scene import NAVIGATION_OPCODES, NavigationScene
from spritelens.logs import get_logger

logger = get_logger("web.ext")

API_VERSION = 2

# 默认订阅集：战斗、捕获、场景/移动、访客/奖励/星灵/图鉴等本机外部消费方
# 关心的权威事件。0x0414/0x0413 是场景 act 洪峰（实测约占 83%），外部可用
# `?opcodes=` 排除；默认保留是因为附近实体/场景变化都来自这两个 opcode。
DEFAULT_EXT_OPCODES = frozenset({
    # 战斗
    0x1316, 0x131A, 0x1324, 0x132C, 0x132D, 0x13F3, 0x13F4,
    0x1305, 0x130B, 0x130C, 0x1313, 0x1314, 0x1322, 0x1339,
    # 捕获/丢球
    0x0200, 0x0201, 0x0202, 0x0203, 0x1982, 0x1983,
    # 场景/移动/传送
    0x0102, 0x0133, 0x0137, 0x014A, 0x0152, 0x015C, 0x015D, 0x015E, 0x0160, 0x0413, 0x0414,
    # 访客/奖励/星灵/世界图标记/图鉴
    0x02E3, 0x02E6, 0x0243, 0x15E0, 0x01DF, 0x0220, 0x039D,
    0x1492, 0x1493, 0x159D,
})

RING_MAX_EVENTS = 200            # REST 回看环形缓冲条数
RING_MAX_FULL_PAYLOAD = 8192     # 超过则只留元数据（大包 decoded 可达 MB 级）
EXT_MAX_PAYLOAD = 256 * 1024     # 超过直接丢弃，避免单包撑爆订阅队列
EXT_MAX_BATCH_BYTES = 512 * 1024  # 单条 WS 消息上限，超限丢 decoded 保元数据
SUB_QUEUE_MAX = 1024             # 每连接积压上限（事件约 17/s，留足突发余量）
STREAM_BATCH_MAX = 64
STREAM_HEARTBEAT_SECONDS = 5.0
WS_SEND_TIMEOUT = 0.1


def _json_default(value: object) -> str:
    """与 event_logger._serialize 一致：bytes 按 UTF-8 兜底，避免 500。"""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", errors="replace")
    return str(value)


def _json_text(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        default=_json_default,
    )


def _record(event: PacketEvent, seq: int) -> dict:
    """对外事件记录：与 eventlog 单行 schema 对齐，另加进程内递增 seq。"""
    record = {
        "seq": seq,
        "ts": event.ts,
        "session": event.session_id,
        "direction": event.direction,
        "opcode": f"0x{event.opcode:04X}",
        "name": event.opcode_name,
        "payload_len": event.payload_len,
        "account_uid": event.account_uid,
        "decoded": event.decoded,
    }
    # 在 decoded 容量裁剪前提取小型事实，HTTP 回看和 WS 共用同一契约。
    path = {0x1316: (6, 1, "entered"), 0x131A: (2, 1, "round"),
            0x132C: (1, 19, "ended")}.get(event.opcode)
    if path is not None and event.direction == "s2c":
        parent_no, id_no, phase = path
        parent = next((node for node in event.decoded if node.get("no") == parent_no), {})
        battle_id = next((node.get("raw") for node in parent.get("children", [])
                          if node.get("no") == id_no), None)
        if type(battle_id) is int and battle_id > 0:
            record["battle"] = {"id": str(battle_id), "phase": phase}
    return record


def parse_opcodes(raw: str | None) -> tuple[frozenset[int] | None, str | None]:
    """解析 opcodes 查询参数；缺省=默认集合，all=不过滤。"""
    if raw is None or not raw.strip():
        return DEFAULT_EXT_OPCODES, None
    text = raw.strip()
    if text.lower() == "all":
        return None, None
    values: set[int] = set()
    for token in text.replace(",", " ").split():
        try:
            value = int(token, 16) if token.lower().startswith("0x") else int(token, 10)
        except ValueError:
            return None, f"非法 opcode：{token}"
        values.add(value)
    if not values:
        return None, "opcodes 不能为空"
    return frozenset(values), None


def _opcode_label(opcodes: frozenset[int] | None) -> str | list[str]:
    if opcodes is None:
        return "all"
    return [f"0x{opcode:04X}" for opcode in sorted(opcodes)]


def _encode_events(records: list[dict]) -> str:
    """编码一批事件；超限时丢 decoded 只保元数据，保证单条消息必然可发。"""
    text = _json_text({"type": "events", "data": records})
    if len(text.encode("utf-8")) <= EXT_MAX_BATCH_BYTES:
        return text
    trimmed = [
        {**record, "decoded": [], "decoded_omitted": True}
        for record in records
    ]
    return _json_text({"type": "events", "data": trimmed})


@dataclass
class _Subscriber:
    """一条事件流连接；queue 由 hub 在管线线程投递、由 aiohttp loop 消费。"""

    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue
    opcodes: frozenset[int] | None
    uid: int


class ExtEventHub:
    """事件分发中枢：管线回调 → 环形缓冲 + 各订阅连接的有界队列。"""

    def __init__(self, *, enabled: bool = True) -> None:
        self._lock = threading.Lock()
        self._enabled = enabled
        self._ring: deque[dict] = deque(maxlen=RING_MAX_EVENTS)
        self._subscribers: dict[int, _Subscriber] = {}
        self._next_subscriber_id = 1
        self._seq = 0
        self._dropped_oversize = 0
        self._dropped_queue = 0
        self._navigation: OrderedDict[tuple[int, str], NavigationScene] = OrderedDict()
        self._capture_generation = 0

    @property
    def enabled(self) -> bool:
        return self._enabled

    def submit(self, event: PacketEvent, *, generation: int = 0) -> None:
        """采集管线回调入口：不阻塞、不外抛异常。"""
        try:
            self._submit(event, generation)
        except Exception:  # noqa: BLE001 - 外部接口故障不能影响采集管线
            logger.exception("ext API 事件分发失败")

    def _submit(self, event: PacketEvent, generation: int) -> None:
        if not self._enabled:
            return
        with self._lock:
            if generation != self._capture_generation:
                self._navigation.clear()
                self._capture_generation = generation
            self._seq += 1
            seq = self._seq
            if event.account_uid and event.opcode in NAVIGATION_OPCODES:
                key = (event.account_uid, event.session_id)
                scene = self._navigation.get(key)
                if scene is None:
                    scene = NavigationScene()
                    self._navigation[key] = scene
                self._navigation.move_to_end(key)
                scene.submit(event, seq)
                if len(scene.actors) > 4096:
                    self._navigation.pop(key)
                if len(self._navigation) > 16:
                    self._navigation.popitem(last=False)
            # 与 battle 投影一样，紧凑场景字段先于事件容量裁剪提取；大 AOI 包不能丢掉所有奇遇。
            if event.payload_len > EXT_MAX_PAYLOAD:
                self._dropped_oversize += 1
                return
            ring_keep = event.opcode in DEFAULT_EXT_OPCODES
            targets = [
                subscriber
                for subscriber in self._subscribers.values()
                if subscriber.opcodes is None or event.opcode in subscriber.opcodes
            ]
            if not targets and not ring_keep:
                return
            record = _record(event, seq)
            if ring_keep:
                if event.payload_len > RING_MAX_FULL_PAYLOAD:
                    record = {**record, "decoded": [], "decoded_omitted": True}
                self._ring.append(record)
            for subscriber in targets:
                if subscriber.uid and event.account_uid != subscriber.uid:
                    continue
                try:
                    subscriber.loop.call_soon_threadsafe(self._enqueue, subscriber, record)
                except RuntimeError:  # 订阅者 loop 已关闭
                    continue

    def _enqueue(self, subscriber: _Subscriber, record: dict) -> None:
        try:
            subscriber.queue.put_nowait(record)
        except asyncio.QueueFull:
            with self._lock:
                self._dropped_queue += 1

    def add_subscriber(
        self,
        loop: asyncio.AbstractEventLoop,
        *,
        opcodes: frozenset[int] | None,
        uid: int = 0,
    ) -> tuple[int, _Subscriber]:
        subscriber = _Subscriber(
            loop=loop,
            queue=asyncio.Queue(maxsize=SUB_QUEUE_MAX),
            opcodes=opcodes,
            uid=uid,
        )
        with self._lock:
            subscriber_id = self._next_subscriber_id
            self._next_subscriber_id += 1
            self._subscribers[subscriber_id] = subscriber
        return subscriber_id, subscriber

    def remove_subscriber(self, subscriber_id: int) -> None:
        with self._lock:
            self._subscribers.pop(subscriber_id, None)

    def recent(
        self,
        *,
        since: float | None = None,
        limit: int = 50,
        opcodes: frozenset[int] | None = None,
    ) -> list[dict]:
        with self._lock:
            records = list(self._ring)
        if opcodes is not None:
            records = [record for record in records if int(record["opcode"], 16) in opcodes]
        if since is not None:
            records = [record for record in records if float(record["ts"]) > since]
        if limit > 0:
            records = records[-limit:]
        return records

    def stats(self) -> dict:
        with self._lock:
            return {
                "ring": len(self._ring),
                "ring_max": RING_MAX_EVENTS,
                "subscribers": len(self._subscribers),
                "seq": self._seq,
                "dropped_oversize": self._dropped_oversize,
                "dropped_queue": self._dropped_queue,
            }

    def navigation_snapshot(self, uid: int, session: str, *, generation: int = 0) -> dict | None:
        with self._lock:
            if generation != self._capture_generation:
                return None
            scene = self._navigation.get((uid, session))
            if scene is None:
                return None
            return {"uid": str(uid), "session": session, "seq": self._seq,
                    "source": "observed_partial", **scene.snapshot()}

    def session_closed(self, session: str) -> None:
        with self._lock:
            for key in list(self._navigation):
                if key[1] == session:
                    self._navigation.pop(key)

    def close(self) -> None:
        with self._lock:
            self._enabled = False
            self._subscribers.clear()
            self._navigation.clear()


class ExtRoutesMixin:
    """ext API 路由（/api/ext/v1/*）。

    宿主 LocalServer 需提供 `_ext_hub`、`_ext_enabled`、`_run_blocking` 与
    CaptureRoutesMixin 的 `_capture_payload`。
    """

    def _ext_disabled_response(self) -> web.Response | None:
        if getattr(self, "_ext_enabled", False):
            return None
        return web.json_response(
            {"error": "external api disabled", "hint": "配置项 ext_api.enabled=false"},
            status=403,
        )

    async def _api_ext_ping(self, request: web.Request) -> web.Response:
        disabled = self._ext_disabled_response()
        if disabled is not None:
            return disabled
        return web.json_response({
            "ok": True,
            "api": API_VERSION,
            "app": APP_NAME,
            "display_name": APP_DISPLAY_NAME,
            "version": __version__,
            "server_time": time.time(),
            "endpoints": {
                "state": "/api/ext/v1/state",
                "events": "/api/ext/v1/events",
                "stream": "/api/ext/v1/stream",
            },
            "opcodes_default": _opcode_label(DEFAULT_EXT_OPCODES),
        })

    async def _api_ext_state(self, request: web.Request) -> web.Response:
        disabled = self._ext_disabled_response()
        if disabled is not None:
            return disabled
        capture = await self._run_blocking(self._capture_payload)
        payload = {
            "api": API_VERSION,
            "app": APP_NAME,
            "version": __version__,
            "server_time": time.time(),
            "capture": capture,
            "ext": self._ext_hub.stats(),
        }
        targets = [(int(s["uid"]), s["session_id"]) for s in capture.get("sessions", [])
                   if int(s["uid"]) > 0 and s.get("has_key")]
        generation = self._context.monitor.capture_generation
        payload["navigation"] = (await self._run_blocking(lambda: self._ext_hub.navigation_snapshot(
            *targets[0], generation=generation))
                                 if capture["running"] and len(targets) == 1 else None)
        text = await self._run_blocking(lambda: _json_text(payload))
        return web.Response(text=text, content_type="application/json")

    async def _api_ext_events(self, request: web.Request) -> web.Response:
        disabled = self._ext_disabled_response()
        if disabled is not None:
            return disabled
        since: float | None = None
        raw_since = request.query.get("since")
        if raw_since:
            try:
                since = float(raw_since)
            except ValueError:
                return web.json_response({"error": f"非法 since：{raw_since}"}, status=400)
        limit = RING_MAX_EVENTS
        raw_limit = request.query.get("limit")
        if raw_limit:
            try:
                limit = max(1, min(int(raw_limit), RING_MAX_EVENTS))
            except ValueError:
                return web.json_response({"error": f"非法 limit：{raw_limit}"}, status=400)
        opcodes, opcode_error = parse_opcodes(request.query.get("opcodes"))
        if opcode_error is not None:
            return web.json_response({"error": opcode_error}, status=400)
        records = self._ext_hub.recent(since=since, limit=limit, opcodes=opcodes)
        payload = {
            "api": API_VERSION,
            "server_time": time.time(),
            "count": len(records),
            "events": records,
        }
        return web.Response(text=_json_text(payload), content_type="application/json")

    async def _api_ext_stream(self, request: web.Request) -> web.StreamResponse:
        disabled = self._ext_disabled_response()
        if disabled is not None:
            return disabled
        opcodes, opcode_error = parse_opcodes(request.query.get("opcodes"))
        if opcode_error is not None:
            return web.json_response({"error": opcode_error}, status=400)
        uid = 0
        raw_uid = request.query.get("uid")
        if raw_uid:
            try:
                uid = int(raw_uid)
            except ValueError:
                return web.json_response({"error": f"非法 uid：{raw_uid}"}, status=400)
        loop = asyncio.get_running_loop()
        websocket = web.WebSocketResponse(heartbeat=30.0)
        await websocket.prepare(request)
        subscriber_id, subscriber = self._ext_hub.add_subscriber(
            loop, opcodes=opcodes, uid=uid
        )
        try:
            await self._ext_send(websocket, _json_text({
                "type": "hello",
                "api": API_VERSION,
                "app": APP_NAME,
                "version": __version__,
                "opcodes": _opcode_label(opcodes),
                "uid": uid,
                "server_time": time.time(),
            }))
            while not websocket.closed:
                try:
                    first = await asyncio.wait_for(
                        subscriber.queue.get(), timeout=STREAM_HEARTBEAT_SECONDS
                    )
                except asyncio.TimeoutError:
                    if not await self._ext_send(
                        websocket, _json_text({"type": "heartbeat", "ts": time.time()})
                    ):
                        break
                    continue
                batch = [first]
                while len(batch) < STREAM_BATCH_MAX:
                    try:
                        batch.append(subscriber.queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break
                if not await self._ext_send(websocket, _encode_events(batch)):
                    break
        except (asyncio.CancelledError, ConnectionResetError, ConnectionAbortedError):
            logger.debug("ext 事件流断开")
        except Exception:  # noqa: BLE001 - 单连接故障不影响服务
            logger.exception("ext 事件流异常")
        finally:
            self._ext_hub.remove_subscriber(subscriber_id)
            if not websocket.closed:
                await websocket.close()
        return websocket

    async def _ext_send(self, websocket: web.WebSocketResponse, text: str) -> bool:
        try:
            await asyncio.wait_for(websocket.send_str(text), timeout=WS_SEND_TIMEOUT)
            return True
        except (asyncio.TimeoutError, ConnectionResetError, ConnectionAbortedError):
            logger.debug("ext 事件流发送超时或断开，主动关闭连接")
            return False
