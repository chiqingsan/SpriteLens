"""对外数据接口（ext API）测试：hub 过滤、鉴权隔离、REST/WS 契约与发现文件。

不依赖真实抓包：直接向 MonitorService 的监听链投递合成 PacketEvent，
验证「管线回调零阻塞 → 环形缓冲/订阅队列 → aiohttp 响应」这条链路。
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
from pathlib import Path

from spritelens.app_context import AppContext
from spritelens.capture.key_store import KeyStore
from spritelens.events import PacketEvent
from spritelens.protocol.opcodes import OpcodeCatalog
from spritelens.repositories.settings import SettingsRepository
from spritelens.services.monitor_service import MonitorService
from spritelens.services.pet_repository import PetRepository
from spritelens.view_models import CaptureViewModel, PetViewModel
from spritelens.web.ext_api import (
    API_VERSION,
    DEFAULT_EXT_OPCODES,
    EXT_MAX_PAYLOAD,
    RING_MAX_EVENTS,
    RING_MAX_FULL_PAYLOAD,
    ExtEventHub,
    parse_opcodes,
)
from spritelens.web.server import LocalServer


def _make_context(tmp: Path, *, ext_enabled: bool = True) -> AppContext:
    settings = SettingsRepository(tmp / "config.json")
    settings.set_checked("ext_api.enabled", ext_enabled)
    monitor = MonitorService(catalog=OpcodeCatalog({}), key_store=KeyStore(tmp / "keys"))
    repository = PetRepository(store=None)
    capture_vm = CaptureViewModel(
        monitor=monitor,
        settings=settings,
        keys_dir=tmp / "keys",
        recordings_dir=tmp / "recordings",
        port=8195,
        probe_environment=False,
    )
    return AppContext(
        settings=settings,
        static_data=None,
        monitor=monitor,
        pet_repository=repository,
        capture_vm=capture_vm,
        pet_vm=PetViewModel(repository, static_data=None),
    )


def _event(
    opcode: int = 0x1316,
    *,
    name: str = "BattleEnterNotify",
    payload_len: int = 42,
    ts: float | None = None,
    account_uid: int = 0,
    decoded: list[dict] | None = None,
) -> PacketEvent:
    return PacketEvent(
        ts=time.time() if ts is None else ts,
        session_id="127.0.0.1:50000",
        direction="s2c",
        opcode=opcode,
        opcode_name=name,
        payload_len=payload_len,
        decoded=decoded if decoded is not None else [{"no": 1, "name": "battle_id", "value": "1"}],
        account_uid=account_uid,
    )


def _http_get(url: str, token: str | None = None, timeout: float = 5.0) -> tuple[int, dict]:
    request = urllib.request.Request(url)
    if token is not None:
        request.add_header("X-Local-Token", token)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {}
        return exc.code, parsed


class ExtEventHubTest(unittest.TestCase):
    def test_battle_projection_survives_decoded_trimming(self):
        hub = ExtEventHub()
        hub.submit(_event(payload_len=30000, decoded=[
            {"no": 6, "children": [{"no": 1, "raw": 9007199254740993}]}]))
        record = hub.recent(limit=1)[0]
        self.assertTrue(record["decoded_omitted"])
        self.assertEqual(record["battle"], {"id": "9007199254740993", "phase": "entered"})

    def test_filters_default_opcodes_and_ring(self):
        hub = ExtEventHub()
        hub.submit(_event(0x9999))
        self.assertEqual(hub.stats()["ring"], 0)

        hub.submit(_event(0x1316))
        records = hub.recent(limit=RING_MAX_EVENTS)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["opcode"], "0x1316")
        self.assertEqual(records[0]["seq"], 2)
        self.assertEqual(records[0]["session"], "127.0.0.1:50000")

    def test_oversize_payload_dropped(self):
        hub = ExtEventHub()
        hub.submit(_event(0x132C, payload_len=EXT_MAX_PAYLOAD + 1))
        self.assertEqual(hub.stats()["dropped_oversize"], 1)
        self.assertEqual(hub.stats()["ring"], 0)

    def test_big_payload_keeps_metadata_only(self):
        hub = ExtEventHub()
        hub.submit(_event(0x131A, payload_len=RING_MAX_FULL_PAYLOAD + 1))
        record = hub.recent(limit=1)[0]
        self.assertEqual(record["decoded"], [])
        self.assertTrue(record["decoded_omitted"])

    def test_ring_bounded(self):
        hub = ExtEventHub()
        for _ in range(RING_MAX_EVENTS + 20):
            hub.submit(_event(0x1316))
        self.assertEqual(len(hub.recent(limit=RING_MAX_EVENTS)), RING_MAX_EVENTS)
        self.assertEqual(hub.stats()["seq"], RING_MAX_EVENTS + 20)

    def test_recent_filters_since_and_opcodes(self):
        hub = ExtEventHub()
        hub.submit(_event(0x1316, ts=100.0))
        hub.submit(_event(0x132C, ts=200.0))
        since = hub.recent(since=150.0, limit=10)
        self.assertEqual([record["opcode"] for record in since], ["0x132C"])
        filtered = hub.recent(limit=10, opcodes=frozenset({0x132C}))
        self.assertEqual(len(filtered), 1)

    def test_disabled_hub_ignores_events(self):
        hub = ExtEventHub(enabled=False)
        hub.submit(_event(0x1316))
        self.assertEqual(hub.stats()["ring"], 0)

    def test_parse_opcodes(self):
        self.assertEqual(parse_opcodes(None), (DEFAULT_EXT_OPCODES, None))
        self.assertEqual(parse_opcodes("all"), (None, None))
        self.assertEqual(parse_opcodes("0x1316, 0x1324"), (frozenset({0x1316, 0x1324}), None))
        self.assertIsNotNone(parse_opcodes("zzz")[1])


class ExtApiServerTest(unittest.TestCase):
    """真实 HTTP/WS：独立 ext token 鉴权 + 事件推送 + 发现文件生命周期。"""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls._tmp.name)
        cls.runtime_path = cls.tmp / "ext-runtime.json"
        cls.context = _make_context(cls.tmp)
        cls.server = LocalServer(
            cls.context,
            token="ui-token-abc",
            port=0,
            ext_runtime_path=cls.runtime_path,
        )
        cls.server.start()
        cls.base = f"http://127.0.0.1:{cls.server.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        cls.context.close()
        cls._tmp.cleanup()

    def test_discovery_file_written(self):
        payload = json.loads(self.runtime_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["token"], self.server.ext_token)
        self.assertEqual(payload["port"], self.server.port)
        self.assertEqual(payload["api"], API_VERSION)
        self.assertIn("stream", payload["endpoints"])

    def test_ping_requires_ext_token(self):
        status, _ = _http_get(f"{self.base}/api/ext/v1/ping")
        self.assertEqual(status, 401)
        status, _ = _http_get(f"{self.base}/api/ext/v1/ping", token=self.server.token)
        self.assertEqual(status, 401)
        status, payload = _http_get(f"{self.base}/api/ext/v1/ping", token=self.server.ext_token)
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["api"], API_VERSION)

    def test_ui_api_rejects_ext_token(self):
        status, _ = _http_get(f"{self.base}/api/state", token=self.server.ext_token)
        self.assertEqual(status, 401)

    def test_state_payload(self):
        status, payload = _http_get(
            f"{self.base}/api/ext/v1/state", token=self.server.ext_token
        )
        self.assertEqual(status, 200)
        self.assertIn("capture", payload)
        self.assertIn("ext", payload)
        self.assertIsInstance(payload["ext"]["ring"], int)

    def test_state_includes_navigation_only_for_unique_active_connection(self):
        self.server._ext_hub.submit(_event(0x0133, account_uid=5))
        capture = {"running": True, "sessions": [{"uid": 5, "session_id": "127.0.0.1:50000", "has_key": True}]}
        with patch.object(self.server, "_capture_payload", return_value=capture):
            status, payload = _http_get(f"{self.base}/api/ext/v1/state", token=self.server.ext_token)
            self.assertEqual(status, 200)
            self.assertEqual(payload["navigation"]["uid"], "5")
            capture["running"] = False
            _, payload = _http_get(f"{self.base}/api/ext/v1/state", token=self.server.ext_token)
            self.assertIsNone(payload["navigation"])

    def test_events_roundtrip(self):
        before = self.server._ext_hub.stats()["seq"]
        self.server._ext_hub.submit(_event(0x1324, name="BattlePerformStartNotify", ts=time.time()))
        status, payload = _http_get(
            f"{self.base}/api/ext/v1/events?since=0&limit=10",
            token=self.server.ext_token,
        )
        self.assertEqual(status, 200)
        self.assertGreaterEqual(payload["count"], 1)
        latest = payload["events"][-1]
        self.assertEqual(latest["opcode"], "0x1324")
        self.assertEqual(latest["seq"], before + 1)

    def test_events_bad_query(self):
        status, _ = _http_get(
            f"{self.base}/api/ext/v1/events?limit=zzz", token=self.server.ext_token
        )
        self.assertEqual(status, 400)
        status, _ = _http_get(
            f"{self.base}/api/ext/v1/events?opcodes=nope", token=self.server.ext_token
        )
        self.assertEqual(status, 400)

    def test_stream_hello_and_events(self):
        async def scenario():
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(
                    f"{self.base}/api/ext/v1/stream?token={self.server.ext_token}"
                ) as ws:
                    hello = json.loads((await ws.receive(timeout=5)).data)
                    self.server._ext_hub.submit(
                        _event(0x131A, name="BattleRoundStartNotify", payload_len=30000,
                               decoded=[{"no": 2, "children": [{"no": 1, "raw": 17}]}])
                    )
                    message = json.loads((await ws.receive(timeout=5)).data)
                    return hello, message

        hello, message = asyncio.run(scenario())
        self.assertEqual(hello["type"], "hello")
        self.assertEqual(hello["api"], API_VERSION)
        self.assertEqual(message["type"], "events")
        self.assertEqual(message["data"][-1]["opcode"], "0x131A")
        self.assertEqual(message["data"][-1]["battle"], {"id": "17", "phase": "round"})
        self.assertTrue(message["data"][-1]["decoded_omitted"])

    def test_stream_requires_ext_token(self):
        async def scenario():
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(
                    f"{self.base}/api/ext/v1/stream?token=wrong"
                ):
                    pass

        with self.assertRaises(Exception):
            asyncio.run(scenario())


class ExtApiDisabledTest(unittest.TestCase):
    def test_disabled_server_returns_403_and_writes_no_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_path = root / "ext-runtime.json"
            context = _make_context(root, ext_enabled=False)
            server = LocalServer(context, token="ui-token", port=0, ext_runtime_path=runtime_path)
            server.start()
            try:
                base = f"http://127.0.0.1:{server.port}"
                status, payload = _http_get(
                    f"{base}/api/ext/v1/ping", token=server.ext_token
                )
                self.assertEqual(status, 403)
                self.assertFalse(runtime_path.exists())
            finally:
                server.stop()
                context.close()


if __name__ == "__main__":
    unittest.main()
