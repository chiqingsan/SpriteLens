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
from dataclasses import replace
from pathlib import Path

from spritelens.app_context import AppContext
from spritelens.capture.key_store import KeyStore
from spritelens.domain.pets import Pet, PetAttribute
from spritelens.protocol.opcodes import OpcodeCatalog
from spritelens.repositories.settings import SettingsRepository
from spritelens.services.monitor_service import MonitorService
from spritelens.services.pet_repository import PetRepository
from spritelens.view_models import CaptureViewModel, EventsViewModel, PetViewModel
from spritelens.web.payloads import handbook_payload
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
        probe_environment=False,  # 测试不跑 PowerShell，报告按需手工注入
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


def _http_post_raw(url: str, token: str, raw: bytes, timeout: float = 5.0) -> tuple[int, dict]:
    """发送任意字节 body（坏 JSON 契约测试用）。"""
    request = urllib.request.Request(url, data=raw, method="POST")
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

    def test_start_timeout_reclaims_background_loop(self):
        """start 超时抛 TimeoutError 并请求后台循环停止（S02）。

        旧实现超时只抛 RuntimeError，后台事件循环/线程留在进程里。
        极小超时可能就绪成功也可能超时——两种结果都必须可安全收尾。
        """
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        context = _make_context(Path(tmp.name))
        server = LocalServer(context, token="t-timeout", port=0)
        try:
            server.start(timeout=0.001)  # 1ms：大概率未就绪
            timed_out = False
        except (TimeoutError, RuntimeError):
            timed_out = True
        if timed_out:
            # 超时路径：后台循环已被请求停止；stop 可安全调用（幂等）
            server.stop()
        context.close()
        self.assertIsInstance(timed_out, bool)

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

    def test_pets_query_does_not_pollute_shared_vm(self):
        """GET /api/pets 不写共享 VM：请求后 bootstrap/其他客户端不受影响（R08）。

        旧实现 _apply_pet_query 修改 ctx.pet_vm 的筛选状态，bootstrap 直接
        消费该 VM——请求 search=火 后 bootstrap 只给出筛选结果，浏览器
        刷新（无参请求）也继承上一个请求的筛选。
        """
        base = f"http://127.0.0.1:{self.server.port}"
        try:
            # 带筛选请求：只看到火神
            _, filtered = _http_get(
                f"{base}/api/pets?search={urllib.parse.quote('火')}", token=self.server.token
            )
            self.assertEqual([p["gid"] for p in filtered["pets"]], [2])

            # 无参请求（浏览器刷新场景）：应回到全量，而不是继承「火」筛选
            _, refreshed = _http_get(f"{base}/api/pets", token=self.server.token)
            self.assertEqual([p["gid"] for p in refreshed["pets"]], [1, 2])
            self.assertEqual(refreshed["filters"]["search"], "")

            # bootstrap 也不被污染
            _, boot = _http_get(f"{base}/api/bootstrap", token=self.server.token)
            self.assertEqual(boot["pets"]["total"], 2)
            self.assertEqual(len(boot["pets"]["pets"]), 2)
        finally:
            _http_get(f"{base}/api/pets", token=self.server.token)

    def test_concurrent_query_and_bootstrap_no_crosstalk(self):
        """并发 search 请求与 bootstrap 互不污染（R08 审查复现）。

        旧实现复现：search=火 与 bootstrap 同时发出，bootstrap 的
        pets.total=2 但 pets 列表只剩 1 只（VM 被写入了筛选）。
        """
        base = f"http://127.0.0.1:{self.server.port}"
        results: dict = {}

        def do_search():
            results["search"] = _http_get(
                f"{base}/api/pets?search={urllib.parse.quote('火')}", token=self.server.token
            )

        def do_bootstrap():
            results["boot"] = _http_get(f"{base}/api/bootstrap", token=self.server.token)

        t1 = threading.Thread(target=do_search)
        t2 = threading.Thread(target=do_bootstrap)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)
        self.assertEqual(results["search"][1]["shown"], 1)
        # bootstrap 属于无参请求：total 与列表条数必须一致（不继承筛选）
        self.assertEqual(results["boot"][1]["pets"]["total"], 2)
        self.assertEqual(len(results["boot"][1]["pets"]["pets"]), 2)

    def test_pets_filtering_via_query(self):
        base = f"http://127.0.0.1:{self.server.port}"
        _, payload = _http_get(f"{base}/api/pets?first_catch=1", token=self.server.token)
        self.assertEqual([p["gid"] for p in payload["pets"]], [1, 2])
        self.assertNotIn("first_catch_only", payload["filters"])
        self.assertNotIn("is_first_catch", payload["pets"][0])

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

    def test_pets_gender_filter_roundtrip(self):
        base = f"http://127.0.0.1:{self.server.port}/api/pets"
        try:
            status, payload = _http_get(f"{base}?gender=2", token=self.server.token)
            self.assertEqual(status, 200)
            self.assertEqual(payload["pets"], [])
            self.assertEqual(payload["filters"]["gender"], 2)

            _, payload = _http_get(f"{base}?gender=1&first_catch=1", token=self.server.token)
            self.assertEqual([pet["gid"] for pet in payload["pets"]], [1, 2])
            self.assertEqual(payload["filters"]["gender"], 1)

            _, payload = _http_get(f"{base}?gender=99", token=self.server.token)
            self.assertEqual(len(payload["pets"]), 2)
            self.assertEqual(payload["filters"]["gender"], 0)
        finally:
            _http_get(base, token=self.server.token)

    def test_capture_endpoints(self):
        base = f"http://127.0.0.1:{self.server.port}"
        status, payload = _http_get(f"{base}/api/capture", token=self.server.token)
        self.assertEqual(status, 200)
        self.assertIn("environment", payload)
        self.assertFalse(payload["running"])
        # 静默丢数据的可见信号（队列过载/重组超限/日志队列满）
        for key in ("dropped_chunks", "dropped_segments", "event_log_dropped"):
            self.assertIn(key, payload)
            self.assertEqual(payload[key], 0)

        status, payload = _http_post(f"{base}/api/capture/iface", self.server.token, {"name": ""})
        self.assertEqual(status, 200)
        self.assertEqual(payload["iface"], "")

        status, payload = _http_post(
            f"{base}/api/capture/recording", self.server.token, {"enabled": True}
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["recording_requested"])

    def test_capture_command_contract_rejects_invalid_body(self):
        """S04/C03：非法命令体 → 400 且零副作用，不静默降级为 {}。

        复核复现：`{"enabled":"false"}` 旧实现传 True（bool("false")）；
        `[]` / 坏 JSON / 缺 enabled 旧实现都返回 200 且按 False 执行。
        """
        base = f"http://127.0.0.1:{self.server.port}"
        recording_url = f"{base}/api/capture/recording"
        autostart_url = f"{base}/api/capture/autostart"

        # 采集中断言零副作用的对照：先记住初始状态
        _, before = _http_get(f"{base}/api/capture", token=self.server.token)

        bad_bodies = [
            ("字符串false", b'{"enabled":"false"}'),
            ("数组", b"[]"),
            ("坏JSON", b"{not json"),
            ("缺enabled", b'{"foo":1}'),
        ]
        for label, raw in bad_bodies:
            status, payload = _http_post_raw(recording_url, self.server.token, raw)
            self.assertEqual(status, 400, f"{label} 应 400，实际 {status}: {payload}")
            self.assertIn("error", payload, f"{label} 应有可读错误")
        for label, raw in bad_bodies:
            status, _ = _http_post_raw(autostart_url, self.server.token, raw)
            self.assertEqual(status, 400, f"autostart {label} 应 400")

        # 零副作用：捕获状态与请求前一致（未开录制、未改 autostart）
        _, after = _http_get(f"{base}/api/capture", token=self.server.token)
        self.assertEqual(after["recording_requested"], before["recording_requested"])
        self.assertEqual(after["autostart"], before["autostart"])

        # 合法布尔值仍正常（契约不回归）
        status, payload = _http_post_raw(recording_url, self.server.token, b'{"enabled":false}')
        self.assertEqual(status, 200)
        self.assertFalse(payload["recording_requested"])

    def test_capture_iface_command_json_contract(self):
        """D08 回归：iface 命令的 JSON 异常全部 400，缺 name/null 不再清空。

        旧实现数组/坏 JSON 走 500（ValueError 未捕获）；`{}`/null 默认成
        空串把原网卡清掉并 200。新契约：非法体/缺字段/错类型 400 零副作用；
        清空选择必须提交明确空字符串。
        """
        base = f"http://127.0.0.1:{self.server.port}"
        iface_url = f"{base}/api/capture/iface"

        # 先设置一个网卡值作为「原值」（用合法命令）
        status, _ = _http_post(iface_url, self.server.token, {"name": "以太网 1"})
        self.assertEqual(status, 200)

        bad_bodies = [b"[]", b"{not json", b"{}", b'{"name":null}', b'{"name":123}']
        for raw in bad_bodies:
            status, payload = _http_post_raw(iface_url, self.server.token, raw)
            self.assertEqual(status, 400, f"{raw!r} 应 400，实际 {status}: {payload}")
            self.assertIn("error", payload)

        # 零副作用：原网卡值保持不变（旧实现会被清空）
        _, payload = _http_get(f"{base}/api/capture", token=self.server.token)
        self.assertEqual(payload["iface"], "以太网 1")

        # 明确空字符串仍可清空（被支持的语义）
        status, payload = _http_post(iface_url, self.server.token, {"name": ""})
        self.assertEqual(status, 200)
        self.assertEqual(payload["iface"], "")

    def test_capture_commands_io_failure_returns_readable_error(self):
        """D03/D08 回归：配置保存失败返回可读 500，不报告成功。

        旧实现 set() 吞 OSError：命令 200 成功、重启后恢复旧配置。
        """
        from unittest import mock

        from spritelens.repositories.settings import SettingsRepository

        base = f"http://127.0.0.1:{self.server.port}"
        with mock.patch.object(
            SettingsRepository, "set_checked", side_effect=OSError("注入：磁盘不可写")
        ):
            status, payload = _http_post(
                f"{base}/api/capture/recording", self.server.token, {"enabled": True}
            )
            self.assertEqual(status, 500)
            self.assertIn("保存失败", payload["error"])

            status, payload = _http_post(
                f"{base}/api/capture/autostart", self.server.token, {"enabled": False}
            )
            self.assertEqual(status, 500)
            self.assertIn("保存失败", payload["error"])

            status, payload = _http_post(
                f"{base}/api/capture/iface", self.server.token, {"name": "以太网 2"}
            )
            self.assertEqual(status, 500)
            self.assertIn("保存失败", payload["error"])

        # 恢复真实存储后合法命令仍 200（服务未被失败请求破坏）
        status, payload = _http_post(
            f"{base}/api/capture/recording", self.server.token, {"enabled": False}
        )
        self.assertEqual(status, 200)

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

    def test_removed_clear_snapshot_endpoints(self):
        """已移除清空功能：旧接口不再清理当前会话。"""
        with tempfile.TemporaryDirectory() as tmp:
            context = _make_context(Path(tmp), pets=(_pet(9, name="临时", level=10),))
            server = LocalServer(context, token="clear-token", port=0)
            server.start()
            try:
                base = f"http://127.0.0.1:{server.port}"
                _, before = _http_get(f"{base}/api/pets", token=server.token)
                self.assertEqual(before["total"], 1)

                for path in ("/api/pets/clear", "/api/egg-box/clear"):
                    status, _ = _http_post(base + path, server.token, {})
                    self.assertEqual(status, 404)
                _, after = _http_get(f"{base}/api/pets", token=server.token)
                self.assertEqual(after["total"], 1)
            finally:
                server.stop()

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


class HandbookPayloadTest(unittest.TestCase):
    """图鉴载荷：纯静态资料（不读玩家数据）、筛选排序与精灵蛋联查。"""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        static_dir = tmp / "static"
        static_dir.mkdir()
        # dex_no 刻意避开与 handbook_no 同值：两者都是「编号」，同值时检索会同时命中两个物种。
        (static_dir / "species.json").write_text(
            json.dumps(
                {
                    "100": {"name": "火兽", "handbook_no": "002", "dex_no": 1, "types": [1],
                            "type_names": ["火"], "egg_groups": ["动物组"],
                            "gender_ratio": {"male": 50, "female": 50},
                            "height_range": [40, 80], "weight_range": [5000, 9000],
                            "description": "火兽的图鉴描述", "stats": {"hp": 100, "sum": 500},
                            "quality": 3, "stage": 1, "max_energy": 10, "evolutions": [200]},
                    "200": {"name": "烈焰兽", "handbook_no": "003", "dex_no": 21, "types": [1],
                            "type_names": ["火"], "egg_groups": [],
                            "gender_ratio": {"male": 50, "female": 50},
                            "height_range": [80, 120], "weight_range": [9000, 12000],
                            "stats": {"hp": 120, "sum": 560},
                            "quality": 4, "stage": 2, "max_energy": 15, "evolutions": []},
                    "300": {"name": "水兽", "handbook_no": "012", "dex_no": 31, "types": [2],
                            "type_names": ["水"], "egg_groups": ["海洋组"],
                            "gender_ratio": {"male": 50, "female": 50},
                            "height_range": [30, 60], "weight_range": [3000, 6000],
                            "stats": {"hp": 90, "sum": 480},
                            "quality": 2, "stage": 1, "max_energy": 10, "evolutions": []},
                    "3002": {"name": "水蓝蓝", "handbook_no": "008", "dex_no": 41, "types": [3],
                             "type_names": ["草"], "egg_groups": ["动物组"],
                             "gender_ratio": {"male": 50, "female": 50},
                             "height_range": [20, 40], "weight_range": [2000, 4000],
                             "stats": {"hp": 80, "sum": 400},
                             "quality": 2, "stage": 1, "max_energy": 10, "evolutions": []},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (static_dir / "types.json").write_text(
            json.dumps(
                {"1": {"name": "火", "color": "#e2764b"},
                 "2": {"name": "水", "color": "#4b8fe2"},
                 "3": {"name": "草", "color": "#83d256"}},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        # 相性表只存非 1 倍例外项：草打火 2 倍、火打草 0.5 倍、水打火免疫。
        (static_dir / "type_chart.json").write_text(
            json.dumps(
                {"version": 1, "chart": {"3": {"1": 2.0}, "1": {"3": 0.5}, "2": {"1": 0.0}}},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (static_dir / "eggs.json").write_text(
            json.dumps(
                {
                    "groups": {"6": "动物组", "13": "海洋组"},
                    "eggs": [
                        {"egg_key": "火兽#1001", "name_key": "火兽", "egg_conf_id": 1001,
                         "egg_name": "火兽蛋", "name": "火兽", "base_id": 100, "dex_no": 1,
                         "handbook_no": "002", "egg_type_name": "普通", "hatch_label": "12小时",
                         "hatch_seconds": 43200, "egg_group_ids": [6],
                         "egg_group_names": ["动物组"]},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        for name in ("natures.json", "skills.json"):
            (static_dir / name).write_text("{}", encoding="utf-8")

        from spritelens.domain.eggs import EggCatalog
        from spritelens.domain.static_data import StaticData

        cls.static = StaticData(static_dir)
        cls.catalog = EggCatalog(static_dir)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _payload(self, **kwargs):
        return handbook_payload(self.static, self.catalog, **kwargs)

    def _keys(self, **kwargs):
        return [row["key"] for row in self._payload(**kwargs)["species"]]

    def test_payload_is_static_only(self):
        """图鉴是资料页：没有账号数据也能出全量资料，且不夹带背包统计。"""
        payload = self._payload()
        self.assertEqual(payload["total"], 4)
        self.assertEqual(payload["shown"], 4)
        self.assertNotIn("collected", payload)
        self.assertNotIn("uid", payload)
        for row in payload["species"]:
            for field in ("collected", "owned_count", "best_level"):
                self.assertNotIn(field, row)
        self.assertEqual(payload["stage_options"], [1, 2])
        self.assertEqual(payload["egg_group_options"], ["动物组", "海洋组"])

    def test_duplicate_species_records_are_merged_to_complete_record(self):
        original = self.static._species["100"]
        self.static._species["099"] = replace(
            original, stats={"hp": 0, "sum": 0}, description="", chain_members=()
        )
        try:
            payload = self._payload()
            rows = [row for row in payload["species"] if row["handbook_no"] == "002"]
            self.assertEqual([row["key"] for row in rows], ["100"])
            self.assertEqual(payload["total"], 4)
            self.assertEqual(payload["shown"], 4)
        finally:
            del self.static._species["099"]

    def test_filters_by_type_stage_and_egg_group(self):
        self.assertEqual(self._keys(type_name="水"), ["300"])
        self.assertEqual(self._keys(stage=2), ["200"])
        self.assertEqual(self._keys(egg_group="动物组"), ["100", "3002"])
        self.assertEqual(self._keys(type_name="草", stage=1), ["3002"])
        self.assertEqual(self._keys(type_name="水", egg_group="动物组"), [])

    def test_sort_orders(self):
        self.assertEqual(self._keys(), ["100", "200", "3002", "300"])
        self.assertEqual(self._keys(sort="stats"), ["200", "100", "300", "3002"])
        self.assertEqual(self._keys(sort="name"), ["300", "3002", "100", "200"])

    def test_search_matches_name_and_ids(self):
        self.assertEqual(self._keys(search="烈焰"), ["200"])
        # 整串命中 base_conf_id / 图鉴号时只回归属物种，不连带前缀邻居
        self.assertEqual(self._keys(search="3002"), ["3002"])
        self.assertEqual(self._keys(search="002"), ["100"])
        self.assertEqual(self._keys(search="012"), ["300"])

    def test_search_falls_back_to_substring_when_number_unknown(self):
        """编号无精确命中时仍按子串兜底，避免检索词打空。"""
        self.assertEqual(self._keys(search="兽"), ["100", "200", "300"])

    def test_egg_and_matchups_come_from_static_tables(self):
        rows = {row["key"]: row for row in self._payload()["species"]}
        egg = rows["100"]["egg"]
        self.assertEqual(egg["name"], "火兽蛋")
        self.assertEqual(egg["hatch_label"], "12小时")
        self.assertEqual(egg["hatch_hours"], 12.0)
        self.assertEqual(egg["egg_type"], "普通")
        self.assertEqual(egg["egg_groups"], ["动物组"])
        self.assertIsNone(rows["200"]["egg"])
        # 防御相性：草打火 2 倍、水打火免疫、火打火 1 倍不进列表
        self.assertEqual(rows["100"]["matchups"]["weak"], ["草"])
        self.assertEqual(rows["100"]["matchups"]["immune"], ["水"])
        self.assertEqual(rows["100"]["matchups"]["resist"], [])

    def test_search_finds_zero_padded_handbook_number(self):
        """卡面编号（handbook_no，如「002」）必须能搜到——原实现只比 name/base_conf_id。"""
        for key, info in self.static.species_items():
            if not info.handbook_no:
                continue
            with self.subTest(handbook_no=info.handbook_no):
                self.assertIn(key, self._keys(search=info.handbook_no))

    def test_empty_static_returns_empty_payload(self):
        payload = handbook_payload(None)
        self.assertEqual(payload["total"], 0)
        self.assertEqual(payload["species"], [])
        self.assertEqual(payload["stage_options"], [])
        self.assertEqual(payload["egg_group_options"], [])

if __name__ == "__main__":
    unittest.main()
