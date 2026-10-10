"""本地服务测试：鉴权、数据 API、随机端口、状态推送。

不依赖真实抓包与浏览器：用最小 AppContext（内存库 + 合成宠物）驱动服务，
验证前端契约与安全组合（token 常量时间比较、仅回环）。
"""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from spritelens.app_context import AppContext
from spritelens.capture.key_store import KeyStore
from spritelens.domain.pets import Pet, PetAttribute
from spritelens.protocol.opcodes import OpcodeCatalog
from spritelens.repositories.settings import SettingsRepository
from spritelens.services.monitor_service import MonitorService
from spritelens.services.pet_repository import PetRepository
from spritelens.view_models import CaptureViewModel, EventsViewModel, PetViewModel
from spritelens.web.payloads import handbook_payload, overview_payload, pets_payload
from spritelens.web.server import LocalServer


def _attr(value: int, race: int) -> PetAttribute:
    return PetAttribute(total_race=race, talent=10, base_value=value)


def _pet(gid: int, *, name: str, level: int, first: bool = False, base_conf: int = 100) -> Pet:
    return Pet(
        gid=gid,
        conf_id=2000000 + gid,
        name=name,
        level=level,
        exp=0,
        nature=1,
        gender=1,
        blood_id=1,
        talent_rank=4,
        is_first_catch=first,
        base_conf_id=base_conf,
        attributes=tuple(_attr(100 + i * 5, 90 + i * 3) for i in range(6)),
        height=120 + gid,
        weight=50000 + gid * 100,
        voice=-20 + gid,
        skills=(),
    )


def _make_context(tmp: Path, pets: tuple[Pet, ...] = ()) -> AppContext:
    settings = SettingsRepository(tmp / "config.json")
    monitor = MonitorService(catalog=OpcodeCatalog({}), key_store=KeyStore(tmp / "keys"))
    repository = PetRepository(store=None)
    for pet in pets:
        repository._pets[pet.gid] = pet  # 直接注入快照（合成数据，免走协议）
    capture_vm = CaptureViewModel(
        monitor=monitor,
        settings=settings,
        keys_dir=tmp / "keys",
        recordings_dir=tmp / "recordings",
        port=8195,
    )
    return AppContext(
        settings=settings,
        static_data=None,
        monitor=monitor,
        pet_repository=repository,
        capture_vm=capture_vm,
        events_vm=EventsViewModel(monitor=monitor),
        pet_vm=PetViewModel(repository, static_data=None),
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


def _http_post(url: str, token: str, payload: dict, timeout: float = 5.0) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    request.add_header("X-Local-Token", token)
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {}
        return exc.code, parsed


class LocalServerTest(unittest.TestCase):
    """服务端到端：起真实 HTTP 服务（随机端口）跑请求。"""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        cls.context = _make_context(
            tmp,
            pets=(
                _pet(1, name="迪莫", level=60, first=True),
                _pet(2, name="火神", level=30),
            ),
        )
        cls.server = LocalServer(cls.context, token="test-token-abc", port=0)
        cls.server.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        cls._tmp.cleanup()

    def test_random_port_assigned(self):
        """端口交给系统分配（非固定），且只绑回环。"""
        self.assertGreater(self.server.port, 0)
        self.assertEqual(self.server.host, "127.0.0.1")

    def test_url_carries_token_in_fragment(self):
        """token 走 fragment：不进请求行/服务端日志。"""
        self.assertTrue(self.server.url.endswith("/#token=test-token-abc"))
        self.assertIn("/#token=", self.server.url)

    def test_api_requires_token(self):
        status, _ = _http_get(f"http://127.0.0.1:{self.server.port}/api/bootstrap")
        self.assertEqual(status, 401)
        status, _ = _http_get(f"http://127.0.0.1:{self.server.port}/api/bootstrap", token="wrong")
        self.assertEqual(status, 401)

    def test_index_is_public(self):
        """静态页与资源不需要 token（页面本身不含数据）。"""
        request = urllib.request.Request(f"http://127.0.0.1:{self.server.port}/")
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("小洛探探", response.read().decode("utf-8"))

    def test_bootstrap_payload_shape(self):
        status, payload = _http_get(
            f"http://127.0.0.1:{self.server.port}/api/bootstrap", token=self.server.token
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["app"]["name"], "SpriteLens")
        self.assertIn("overview", payload)
        self.assertIn("pets", payload)
        self.assertIn("capture", payload)
        self.assertIn("state", payload)
        self.assertEqual(payload["pets"]["total"], 2)
        self.assertEqual(payload["overview"]["stats"]["total"], 2)

    def test_pets_filtering_via_query(self):
        base = f"http://127.0.0.1:{self.server.port}"
        _, payload = _http_get(f"{base}/api/pets?first_catch=1", token=self.server.token)
        self.assertEqual([p["gid"] for p in payload["pets"]], [1])

        _, payload = _http_get(
            f"{base}/api/pets?search={urllib.parse.quote('火')}", token=self.server.token
        )
        self.assertEqual([p["gid"] for p in payload["pets"]], [2])

        _, payload = _http_get(
            f"{base}/api/pets?level_min=50&level_max=100", token=self.server.token
        )
        self.assertEqual([p["gid"] for p in payload["pets"]], [1])

        _, payload = _http_get(f"{base}/api/pets?sort=level&desc=1", token=self.server.token)
        self.assertEqual([p["gid"] for p in payload["pets"]], [1, 2])

    def test_pet_row_has_display_fields(self):
        _, payload = _http_get(
            f"http://127.0.0.1:{self.server.port}/api/pets", token=self.server.token
        )
        row = payload["pets"][0]
        for key in ("gid", "name", "level", "stats", "height_text", "weight_text", "talent_color"):
            self.assertIn(key, row)
        self.assertEqual(len(row["stats"]), 6)
        self.assertEqual(row["height_text"], "1.21m")

    def test_capture_endpoints(self):
        base = f"http://127.0.0.1:{self.server.port}"
        status, payload = _http_get(f"{base}/api/capture", token=self.server.token)
        self.assertEqual(status, 200)
        self.assertIn("environment", payload)
        self.assertFalse(payload["running"])

        status, payload = _http_post(f"{base}/api/capture/iface", self.server.token, {"name": ""})
        self.assertEqual(status, 200)
        self.assertEqual(payload["iface"], "")

        status, payload = _http_post(
            f"{base}/api/capture/recording", self.server.token, {"enabled": True}
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["recording_requested"])

    def test_manual_key_validation(self):
        base = f"http://127.0.0.1:{self.server.port}"
        status, payload = _http_post(
            f"{base}/api/capture/key", self.server.token, {"text": "not-a-valid-key"}
        )
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])

        good = "0123456789abcdef0123456789abcdef"  # 32 hex = 16 字节
        status, payload = _http_post(f"{base}/api/capture/key", self.server.token, {"text": good})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])

    def test_state_endpoint(self):
        status, payload = _http_get(
            f"http://127.0.0.1:{self.server.port}/api/state", token=self.server.token
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["pets_total"], 2)
        self.assertIn("capture", payload)

    def test_type_color_in_stats(self):
        """系别分布带主题色（前端条形图直接着色，不必自己映射）。"""
        status, payload = _http_get(
            f"http://127.0.0.1:{self.server.port}/api/state", token=self.server.token
        )
        self.assertEqual(status, 200)
        for item in payload["stats"]["types"]:
            self.assertIn("color", item)

    def test_clear_snapshot_endpoint(self):
        """清空快照：独立实例验证（class 级服务共享数据，不能污染其他用例）。"""
        with tempfile.TemporaryDirectory() as tmp:
            context = _make_context(Path(tmp), pets=(_pet(9, name="临时", level=10),))
            server = LocalServer(context, token="clear-token", port=0)
            server.start()
            try:
                base = f"http://127.0.0.1:{server.port}"
                _, before = _http_get(f"{base}/api/pets", token=server.token)
                self.assertEqual(before["total"], 1)

                status, after = _http_post(f"{base}/api/pets/clear", server.token, {})
                self.assertEqual(status, 200)
                self.assertEqual(after["total"], 0)
                self.assertEqual(after["pets"], [])
            finally:
                server.stop()

    def test_events_endpoints(self):
        base = f"http://127.0.0.1:{self.server.port}"
        status, payload = _http_get(f"{base}/api/events", token=self.server.token)
        self.assertEqual(status, 200)
        self.assertIn("rows", payload)

        status, payload = _http_get(f"{base}/api/events/detail?index=0", token=self.server.token)
        self.assertEqual(status, 200)
        self.assertIn("detail", payload)

    def test_handbook_endpoint(self):
        """图鉴：无静态表时返回空壳（不报错），保证前端可渲染空态。"""
        status, payload = _http_get(
            f"http://127.0.0.1:{self.server.port}/api/handbook", token=self.server.token
        )
        self.assertEqual(status, 200)
        self.assertIn("species", payload)
        self.assertIn("total", payload)
        self.assertIn("filters", payload)

    def test_websocket_requires_token(self):
        """WebSocket 走查询参数鉴权（浏览器无法自定义头）；错 token 被拒、对 token 可连。"""
        import asyncio

        async def scenario() -> tuple[int, dict]:
            import aiohttp

            port = self.server.port
            async with aiohttp.ClientSession() as session:
                # 错误 token：握手阶段即被拒（401）
                async with session.ws_connect(
                    f"http://127.0.0.1:{port}/ws?token=wrong"
                ) as _:
                    pass  # 能连上说明鉴权失效，下面断言会失败
                return -1, {}
            return 0, {}

        async def good_scenario() -> dict:
            import aiohttp

            port = self.server.port
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(
                    f"http://127.0.0.1:{port}/ws?token={self.server.token}"
                ) as ws:
                    message = await ws.receive(timeout=5)
                    return json.loads(message.data)

        with self.assertRaises(Exception):
            asyncio.run(scenario())
        first = asyncio.run(good_scenario())
        self.assertIn("pets_total", first)
        self.assertIn("capture", first)


class PayloadsUnitTest(unittest.TestCase):
    """载荷构造的纯函数测试（不起服务）。"""

    def test_pet_row_without_static_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = _make_context(Path(tmp), pets=(_pet(7, name="彩蝶鲨", level=48),))
            payload = pets_payload(context.pet_vm, None)
            row = payload["pets"][0]
            self.assertEqual(row["name"], "彩蝶鲨")
            self.assertEqual(row["nature_name"], "1")  # 无静态表退回原始 ID
            self.assertEqual(row["type_names"], [])
            self.assertEqual(row["species_name"], "")
            self.assertEqual(row["stat_sum"], sum(100 + i * 5 for i in range(6)))

    def test_overview_payload_no_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = _make_context(Path(tmp), pets=(_pet(1, name="A", level=61, first=True),))
            payload = overview_payload(context.pet_vm, context.pet_repository, None)
            self.assertIsNone(payload["identity"])
            self.assertEqual(payload["stats"]["total"], 1)
            self.assertEqual(payload["stats"]["first_catch"], 1)
            self.assertEqual(payload["stats"]["max_level"], 61)
            self.assertEqual(payload["stats"]["maxed"], 1)


class HandbookPayloadTest(unittest.TestCase):
    """图鉴载荷：收集状态、筛选与进化链解析（用迷你静态表驱动）。"""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        static_dir = tmp / "static"
        static_dir.mkdir()
        (static_dir / "species.json").write_text(
            json.dumps(
                {
                    "100": {"name": "火兽", "types": [1], "type_names": ["火"],
                            "stats": {"hp": 100, "sum": 500}, "quality": 3, "stage": 1,
                            "max_energy": 10, "evolutions": [200]},
                    "200": {"name": "烈焰兽", "types": [1], "type_names": ["火"],
                            "stats": {"hp": 120, "sum": 560}, "quality": 4, "stage": 2,
                            "max_energy": 15, "evolutions": []},
                    "300": {"name": "水兽", "types": [2], "type_names": ["水"],
                            "stats": {"hp": 90, "sum": 480}, "quality": 2, "stage": 1,
                            "max_energy": 10, "evolutions": []},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        for name in ("natures.json", "types.json", "skills.json"):
            (static_dir / name).write_text("{}", encoding="utf-8")

        from spritelens.domain.static_data import StaticData

        cls.static = StaticData(static_dir)
        # 已收集 100（两只，取最高等级）与 300；200 未收集
        cls.context = _make_context(
            tmp,
            pets=(
                _pet(1, name="火兽", level=20, base_conf=100),
                _pet(2, name="火兽", level=45, base_conf=100),
                _pet(3, name="水兽", level=30, base_conf=300),
            ),
        )

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _payload(self, **kwargs):
        return handbook_payload(self.static, self.context.pet_repository, **kwargs)

    def test_collection_status_from_snapshot(self):
        payload = self._payload()
        self.assertEqual(payload["total"], 3)
        self.assertEqual(payload["collected"], 2)
        by_key = {row["key"]: row for row in payload["species"]}
        self.assertTrue(by_key["100"]["collected"])
        self.assertEqual(by_key["100"]["owned_count"], 2)
        self.assertEqual(by_key["100"]["best_level"], 45)
        self.assertFalse(by_key["200"]["collected"])
        self.assertEqual(by_key["200"]["owned_count"], 0)

    def test_uncollected_filter(self):
        payload = self._payload(uncollected_only=True)
        self.assertEqual([row["key"] for row in payload["species"]], ["200"])

    def test_collected_filter(self):
        payload = self._payload(collected_only=True)
        self.assertEqual(sorted(row["key"] for row in payload["species"]), ["100", "300"])

    def test_type_filter(self):
        payload = self._payload(type_name="水")
        self.assertEqual([row["key"] for row in payload["species"]], ["300"])

    def test_search_matches_name_and_key(self):
        self.assertEqual(
            [row["key"] for row in self._payload(search="烈焰")["species"]], ["200"]
        )
        self.assertEqual([row["key"] for row in self._payload(search="300")["species"]], ["300"])

    def test_evolution_links_resolve_to_names(self):
        rows = {row["key"]: row for row in self._payload()["species"]}
        self.assertEqual(rows["100"]["evolutions"], [{"key": "200", "name": "烈焰兽"}])
        self.assertEqual(rows["200"]["evolutions"], [])

    def test_no_static_data_returns_empty_shell(self):
        payload = handbook_payload(None, self.context.pet_repository)
        self.assertEqual(payload["species"], [])
        self.assertEqual(payload["total"], 0)


if __name__ == "__main__":
    unittest.main()
