"""配窝页「真实链路」冒烟用的本地服务（开发工具，不参与产品运行）。

为什么需要它：单元测试用 mock 替身，覆盖不到
`spritelens/web/static/account-requests.js`（X-Local-Token、取消在途请求）+ 真实草稿落盘这条链路。
这里复用 tests 夹具起一个真实 LocalServer（随机端口 + 本地令牌），并把
「只有目标、没有窝位」的草稿预置成用户现场（目标蛋首次出现在 2026-10-17 的保存）。

用法：
    .venv/Scripts/python.exe tools/planner_smoke_server.py
    # 打印 SMOKE_READY {"url": ..., "token": ..., "egg_key": ...} 后等待停止文件
    cd frontend
    SMOKE_PLANNER_URL=<url> SMOKE_PLANNER_TOKEN=<token> \
    SMOKE_PLANNER_EGG=<egg_key> node node_modules/vitest/vitest.mjs run src/smoke/plannerApi.test.ts
    # 收尾：创建停止文件（默认 .git/smoke_stop），服务端会先写一次窗口几何（等价关窗整份 cache
    # 落盘），再用**全新 SettingsRepository 实例**重新读配置并打印 SMOKE_RESULT —— 即「重新打开软件」。
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spritelens.domain.identity import PlayerIdentity  # noqa: E402
from spritelens.repositories.settings import SettingsRepository  # noqa: E402
from spritelens.web.server import LocalServer  # noqa: E402
from tests.test_breeding_planner import PlannerTests  # noqa: E402
from tests.test_web_server import _make_context  # noqa: E402

DEFAULT_STOP_FILE = ROOT / ".git" / "smoke_stop"
EGG_KEY = "大耳帽兜#3121001"  # 用户现场那只目标蛋（data/static/eggs.json 里存在）


def fetch_json(url: str, token: str) -> dict:
    request = urllib.request.Request(url, headers={"X-Local-Token": token})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def main() -> int:
    stop_file = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_STOP_FILE
    case = PlannerTests("test_out_of_board_legacy_draft_is_reported_as_a_position_issue")
    case.setUp()
    directory = TemporaryDirectory()
    context = _make_context(Path(directory.name), case.pets[:2])
    context.static_data, context.egg_catalog = case.static, case.eggs
    context.pet_repository._account.observe(PlayerIdentity(101, "合成账号", 1))
    server = LocalServer(context)
    server.start()
    root = f"http://127.0.0.1:{server.port}"
    config = Path(directory.name) / "config.json"
    try:
        info = fetch_json(root + "/api/breeding-planner/context", server.token)
        goal = {"goal_id": "goal-1792219148297-0", "egg_key": EGG_KEY, "size_mark": "", "voice_mark": "",
                "nature_id": 0, "priority": 0}
        # 必须走服务端自己的实例：另建一个 SettingsRepository 写盘会被本实例的旧缓存挡住。
        context.settings.set_checked("breeding-planner.101.target", {
            "mode": "target", "goals": [goal], "selected": [], "participation": "best", "capacity": 10,
            "academy": False, "placements": [], "approved": [], "rule_version": info["rule_version"],
            "geometry_version": info["geometry_version"], "uid": info["uid"], "version": info["version"],
            "catalog_version": info["catalog_version"], "revision": 1, "schema_version": 1})
        print("SMOKE_READY " + json.dumps({"url": root, "token": server.token, "config": str(config),
                                           "uid": info["uid"], "egg_key": EGG_KEY}), flush=True)
        deadline = time.monotonic() + 900
        while not stop_file.exists() and time.monotonic() < deadline:
            time.sleep(0.2)
        stop_file.unlink(missing_ok=True)
        # 关窗：真机走 run_web 的 set_window_geometry（整份 cache 落盘），这里等价复现。
        context.settings.set_window_geometry(width=1200, height=800, maximized=False, x=10, y=10)
        stored = SettingsRepository(config).get_value("breeding-planner.101.target", None)
        print("SMOKE_RESULT " + json.dumps({"goals": len((stored or {}).get("goals") or []),
                                            "revision": (stored or {}).get("revision"),
                                            "raw": stored}, ensure_ascii=False), flush=True)
        return 0
    finally:
        server.stop()
        context.close()


if __name__ == "__main__":
    sys.exit(main())
