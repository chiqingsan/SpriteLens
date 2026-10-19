"""配窝核心回归：实际个体、迭代准许、全父本、几何和保存失败。"""
from dataclasses import asdict, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from unittest import TestCase
from unittest.mock import patch

from spritelens.domain.breeding_planner import Goal, Placement, Request, build_pool, evaluate, pair_match
from spritelens.domain.breeding_solver import solve
from spritelens.domain.eggs import EggCatalog
from spritelens.domain.identity import PlayerIdentity
from spritelens.repositories.settings import SettingsRepository
from spritelens.services.breeding_planner_service import BreedingPlannerService, StalePlannerInput
from spritelens.web.breeding_planner import parse_draft
from tests.test_breeder_library import BreederLibraryTests


class PlannerTests(TestCase):
    def setUp(self):
        fixture = BreederLibraryTests()
        fixture.setUp()
        self.fixture, self.repo, self.static = fixture, fixture.repo, fixture.static
        self.eggs = EggCatalog(Path("data/static"))
        self.goal = Goal("g1", "test", "大块头", "婉转声", 2)
        self.pets = tuple([fixture.pet(1)] + [fixture.pet(i, 2) for i in range(2, 13)])
        self.pool = build_pool(self.pets, self.static, self.eggs, {})
        self.pool.eggs.update({str(p.gid): "test" for p in self.pets})
        self.request = Request(goals=(self.goal,))

    def test_relaxed_marks_and_95_raw_db_need_explicit_iteration(self):
        self.assertEqual(pair_match(self.pool, "1", "2", self.goal)["kind"], "exact")
        near = build_pool((replace(self.pets[0], voice=95), self.pets[1]), self.static, self.eggs, {})
        near.eggs.update({"2": "test"})
        match = pair_match(near, "1", "2", self.goal)
        self.assertEqual((match["kind"], match["candidate_voice"], match["gap"]), ("iterative", 95, 1))
        self.assertIsNone(match["minimum_candidate_voice"])
        positions = (Placement("1", 0, 0), Placement("2", 2, 0))
        self.assertFalse(evaluate(near, self.request, positions)["goals"][0]["covered"])
        approved = replace(self.request, approved=frozenset(("g1:1:2",)))
        result = evaluate(near, approved, positions)
        self.assertTrue(result["goals"][0]["covered"])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["goals"][0]["exact_mothers"], 0)

    def test_plain_egg_goal_selects_compatible_parents_without_marks_or_nature(self):
        request = replace(self.request, goals=(Goal("plain", "test"),), capacity=2)
        planned = solve(self.pool, request, Event())["plans"][0]
        self.assertEqual(planned["status"], "ready")
        self.assertEqual({self.pool.parents[p["gid"]].pet.gender for p in planned["placements"]}, {1, 2})
        self.assertTrue(planned["edges"])
        self.assertTrue(planned["goals"][0]["covered"])

    def test_plain_goal_fills_connected_capacity_and_balances_gender(self):
        pets = tuple(self.fixture.pet(i, 1 if i <= 6 else 2) for i in range(1, 13))
        pool = build_pool(pets, self.static, self.eggs, {})
        pool.eggs.update({str(p.gid): "test" for p in pets if p.gid > 6})
        planned = solve(pool, Request(goals=(Goal("plain", "test"),), capacity=11), Event())["plans"][0]
        self.assertEqual(len(planned["placements"]), 11)
        self.assertLessEqual(planned["metrics"]["gender_gap"], 1)
        self.assertEqual(planned["metrics"]["unused_slots"], 0)
        self.assertAlmostEqual((min(p["x"] for p in planned["placements"]) + max(p["x"] for p in planned["placements"]) + 2) / 2, 10)
        self.assertAlmostEqual((min(p["y"] for p in planned["placements"]) + max(p["y"] for p in planned["placements"]) + 2) / 2, 10)

    def test_plain_goal_prefers_target_egg_evolution_chain(self):
        pets = (self.fixture.pet(1, base=3), self.fixture.pet(2, base=1), self.fixture.pet(3, 2, base=1))
        pool = build_pool(pets, self.static, self.eggs, {})
        pool.eggs["3"] = "test"
        planned = solve(pool, Request(goals=(Goal("plain", "test"),), capacity=2), Event())["plans"][0]
        self.assertEqual({p["gid"] for p in planned["placements"]}, {"2", "3"})
        self.assertEqual(planned["metrics"]["same_chain"], 2)

    def test_replanning_recenters_unlocked_saved_layout(self):
        request = replace(self.request, goals=(Goal("plain", "test"),), capacity=2,
                          placements=(Placement("1", 0, 0), Placement("2", 2, 0)))
        planned = solve(self.pool, request, Event())["plans"][0]
        self.assertAlmostEqual((min(p["x"] for p in planned["placements"]) + max(p["x"] for p in planned["placements"]) + 2) / 2, 10)
        self.assertAlmostEqual((min(p["y"] for p in planned["placements"]) + max(p["y"] for p in planned["placements"]) + 2) / 2, 10)

    def test_unknown_not_false_negative_and_opposing_marks_not_automatic(self):
        for voice, kind in ((0, "unknown"), (-99, "none")):
            pool = build_pool((replace(self.pets[0], voice=voice), self.pets[1]), self.static, self.eggs, {})
            pool.eggs["2"] = "test"
            self.assertEqual(pair_match(pool, "1", "2", self.goal)["kind"], kind)
        pool = build_pool((replace(self.pets[0], weight=0, height=200), self.pets[1]), self.static, self.eggs, {})
        pool.eggs["2"] = "test"
        self.assertNotEqual(pair_match(pool, "1", "2", self.goal)["kind"], "exact")

    def test_all_fathers_and_academy_branch_are_evaluated(self):
        pets = (self.pets[0], self.pets[1], self.fixture.pet(3, nature=11, voice=-99), self.fixture.pet(4, 2))
        pool = build_pool(pets, self.static, self.eggs, {})
        pool.eggs.update({"2": "test", "4": "test"})
        positions = (Placement("1", 0, 0), Placement("2", 2, 0), Placement("3", 4, 0), Placement("4", 6, 0, "academy"))
        result = evaluate(pool, replace(self.request, academy=True), positions)
        self.assertEqual(len(result["edges"]), 3)
        reference = next(m for m in result["mothers"] if m["gid"] == "2")["references"][0]
        self.assertEqual(reference["father_fraction"], .5)
        self.assertEqual(reference["nature_contribution"], .3)
        self.assertEqual(reference["interference"], ["3"])
        academy_mother = next(m for m in result["mothers"] if m["gid"] == "4")
        self.assertEqual(academy_mother["nature"]["known"][self.static.nature(2).name], 1.0)
        self.assertEqual(result["status"], "partial")

    def test_academy_nest_rejects_father(self):
        result = evaluate(self.pool, replace(self.request, academy=True),
                          (Placement("1", 0, 0, "academy"), Placement("2", 2, 0)))
        self.assertEqual(result["status"], "invalid")
        self.assertIn("学院绿窝必须放置母本", result["issues"])

    def test_solver_prefers_target_nature_mother_for_academy_nest(self):
        pets = (self.pets[0], self.pets[1], replace(self.pets[2], nature=11))
        pool = build_pool(pets, self.static, self.eggs, {})
        pool.eggs.update({"2": "test", "3": "test"})
        request = replace(self.request, capacity=2, academy=True)
        planned = solve(pool, request, Event())["plans"][0]
        academy = next(p for p in planned["placements"] if p["kind"] == "academy")
        self.assertEqual(academy["gid"], "2")
        self.assertEqual(planned["metrics"]["academy_nature_matches"], 1)

    def test_geometry_contact_half_grid_range_and_no_duplicate_instance(self):
        for x, y, expected in ((2, 0, "ready"), (2.5, 2.5, "ready"), (3, 2.5, "no_plan"), (1.5, 0, "invalid")):
            result = evaluate(self.pool, self.request, (Placement("1", 0, 0), Placement("2", x, y)))
            self.assertEqual(result["status"], expected)
        self.assertEqual(evaluate(self.pool, self.request, (Placement("1", 0, 0), Placement("1", 2, 0)))["status"], "invalid")

    def test_shared_goal_coverage_does_not_double_count_mother_resources(self):
        request = replace(self.request, goals=(self.goal, Goal("g2", "test", "大块头")))
        result = evaluate(self.pool, request, (Placement("1", 0, 0), Placement("2", 2, 0)))
        self.assertTrue(all(g["covered"] for g in result["goals"]))
        self.assertEqual(sum(g["mother_count"] for g in result["goals"]), 1)
        self.assertEqual(sum(g["shared_mothers"] for g in result["goals"]), 1)

    def test_explicit_iteration_can_trade_exact_mothers_for_extra_goal_coverage(self):
        pets = (*self.pets[:4], self.fixture.pet(5, 2, voice=95))
        pool = build_pool(pets, self.static, self.eggs, {})
        pool.eggs.update({str(p.gid): "test" for p in pets})
        pool.eggs["5"] = "other"
        request = replace(self.request, goals=(self.goal, replace(self.goal, goal_id="g2", egg_key="other")), approved=frozenset(("g2:1:5",)))
        exact = evaluate(pool, request, (Placement("1", 2, 2), Placement("2", 0, 0), Placement("3", 2, 0), Placement("4", 4, 0)))
        mixed = evaluate(pool, request, (Placement("1", 2, 2), Placement("2", 0, 0), Placement("3", 2, 0), Placement("5", 4, 0)))
        self.assertGreater(mixed["score"], exact["score"])
        self.assertEqual(sum(g["exact_mothers"] for g in mixed["goals"]), 2)
        self.assertEqual(mixed["status"], "partial")
        planned = solve(pool, replace(request, capacity=4), Event())
        self.assertEqual(sum(g["covered"] for g in planned["plans"][0]["goals"]), 2)

    def test_opportunity_first_and_joint_search_across_separate_egg_groups(self):
        more = evaluate(self.pool, self.request, (Placement("1", 2, 2), Placement("2", 0, 0), Placement("3", 4, 0)))
        # 学院需在容量内；比较更多有效母本优先于性格贡献。
        fewer = evaluate(self.pool, replace(self.request, academy=True), (Placement("1", 2, 2, "academy"), Placement("2", 0, 0)))
        self.assertGreater(more["score"], fewer["score"])
        pets = (self.pets[0], self.pets[1], self.fixture.pet(20, base=5), self.fixture.pet(21, 2, base=5))
        pool = build_pool(pets, self.static, self.eggs, {})
        pool.eggs.update({"2": "test", "21": "dragon"})
        request = replace(self.request, capacity=4, goals=(self.goal, replace(self.goal, goal_id="g2", egg_key="dragon")))
        result = solve(pool, request, Event())
        self.assertEqual(sum(g["covered"] for g in result["plans"][0]["goals"]), 2)

    def test_participation_lock_can_move_while_position_lock_stays_fixed(self):
        request = replace(self.request, capacity=2, placements=(Placement("1", 900, 900, lock="participation"),))
        result = solve(self.pool, request, Event())["plans"][0]
        self.assertEqual(result["status"], "ready")
        self.assertIn("1", {p["gid"] for p in result["placements"]})
        self.assertNotEqual(next(p["x"] for p in result["placements"] if p["gid"] == "1"), 900)

    def test_replanning_keeps_a_better_existing_valid_layout_with_position_locks(self):
        original = solve(self.pool, self.request, Event())["plans"][0]
        placements = tuple(Placement(**p) for p in original["placements"])
        locked = tuple(replace(p, lock="position") if i == 1 else p for i, p in enumerate(placements))
        request = replace(self.request, placements=locked)
        result = solve(self.pool, request, Event())["plans"][0]
        self.assertGreaterEqual(result["score"], original["score"])
        self.assertEqual(result["metrics"]["effective_mothers"], 9)

    def test_search_quantity_and_selected_all_capacity_and_position_lock(self):
        result = solve(self.pool, self.request, Event())
        plan = result["plans"][0]
        self.assertGreaterEqual(plan["metrics"]["effective_mothers"], 5)
        self.assertLessEqual(len(plan["placements"]), 10)
        self.assertEqual(result["search_status"], "bounded")
        locked = replace(self.request, placements=(Placement("1", 8.5, 8, lock="position"),))
        result = solve(self.pool, locked, Event())
        self.assertTrue(all(any(p["gid"] == "1" and p["x"] == 8.5 and p["y"] == 8 for p in plan["placements"]) for plan in result["plans"]))
        all_request = Request(mode="selected", selected=tuple(self.pool.parents), participation="all")
        self.assertEqual(solve(self.pool, all_request, Event())["status"], "invalid")

    def test_known_group_survives_unknown_tag_and_conflicting_group_is_reported(self):
        self.static._species["1"] = replace(self.static._species["1"], egg_groups=("动物", "未知"))
        self.assertTrue(build_pool(self.pets, self.static, self.eggs, {}).parents)
        self.static._species["1"] = replace(self.static._species["1"], egg_groups=("动物", "无法孵蛋"))
        pool = build_pool(self.pets, self.static, self.eggs, {})
        self.assertFalse(pool.parents)
        self.assertTrue(pool.issues)

    def test_account_snapshot_save_failure_and_restore_exact_ids(self):
        with TemporaryDirectory() as directory:
            settings = SettingsRepository(Path(directory) / "settings.json")
            self.repo._pets = {p.gid: p for p in self.pets}
            service = BreedingPlannerService(self.repo, self.static, self.eggs, settings)
            inventory, _ = service.snapshot()
            value = {"placements": [{"gid": str(2**63 + 1), "x": 2, "y": 0}]}
            service.save_draft(inventory.uid, inventory.version, "target", value)
            self.assertEqual(service.load_draft(101, "target"), value)
            self.assertIsNone(service.load_draft(202, "target"))
            with patch.object(settings, "set_checked", side_effect=OSError("full")), self.assertRaises(OSError):
                service.save_draft(101, inventory.version, "target", {})
            self.assertEqual(service.load_draft(101, "target"), value)
            self.repo._account.observe(PlayerIdentity(202, "other", 1))
            with self.assertRaises(StalePlannerInput):
                service.check(101, inventory.version)

    def test_external_draft_rejects_invalid_half_grid_and_rule_version(self):
        value = {**asdict(self.request), "goals": [asdict(self.goal)], "selected": [], "approved": [],
                 "placements": [], "rule_version": "planner-dual-mark-v1", "geometry_version": "community-grid-v1"}
        self.assertEqual(parse_draft(value), self.request)
        for change in ({"capacity": 11}, {"academy": 1}, {"rule_version": "old"}, {"approved": ["没有结构"]},
                       {"placements": [{**asdict(Placement("1", 0, 0)), "x": float("nan")}]}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                parse_draft({**value, **change})

    def test_solver_never_places_nests_outside_the_board(self):
        # 位置锁在角落、或参与锁残留越界旧坐标时，新生成的方案必须落在 0～18 内。
        corner = solve(self.pool, replace(self.request, capacity=3, placements=(Placement("1", 18, 18, lock="position"),)), Event())
        self.assertTrue(corner["plans"], corner["issues"])
        for plan in corner["plans"]:
            for placement in plan["placements"]:
                self.assertTrue(0 <= placement["x"] <= 18 and 0 <= placement["y"] <= 18, placement)
            self.assertEqual(next(p["x"] for p in plan["placements"] if p["gid"] == "1"), 18)
        moved = solve(self.pool, replace(self.request, capacity=3, placements=(Placement("1", 900, 900, lock="participation"),)), Event())
        self.assertTrue(moved["plans"], moved["issues"])
        for plan in moved["plans"]:
            for placement in plan["placements"]:
                self.assertTrue(0 <= placement["x"] <= 18 and 0 <= placement["y"] <= 18, placement)
            self.assertIn("1", {p["gid"] for p in plan["placements"]})

    def test_out_of_board_legacy_draft_is_reported_as_a_position_issue(self):
        outside = (Placement("1", 20, 18), Placement("2", 22, 18))
        result = evaluate(self.pool, self.request, outside)
        self.assertEqual(result["status"], "invalid")
        self.assertIn("超出 20×20 草图范围", "".join(result["issues"]))
        # 越界旧草稿仍可读取和保存：提示由评估给出，解析阶段不拒绝。
        value = {**asdict(self.request), "goals": [asdict(self.goal)], "selected": [], "approved": [],
                 "placements": [asdict(p) for p in outside],
                 "rule_version": "planner-dual-mark-v1", "geometry_version": "community-grid-v1"}
        self.assertEqual(len(parse_draft(value).placements), 2)

    def test_negative_edit_margin_is_valid_for_manual_layouts(self):
        result = evaluate(self.pool, self.request, (Placement("1", -2, -2),))
        self.assertNotIn("超出 20×20 草图范围", "".join(result["issues"]))

    def test_voice_override_and_snapshot_share_one_version(self):
        from types import SimpleNamespace
        changed, release, snapshot_done = Event(), Event(), Event()
        voices, snapshots = {}, []
        def save(uid, gid, voice):
            voices[gid] = voice
            changed.set()
            if not release.wait(2):
                raise TimeoutError("test writer was not released")
        self.repo._store = SimpleNamespace(has_pet=lambda uid, gid: True, set_voice_override=save, voice_overrides=lambda uid: dict(voices))
        writer = Thread(target=lambda: self.repo.save_voice_override(101, 1, 95))
        reader = Thread(target=lambda: (snapshots.append(self.repo.breeding_snapshot()), snapshot_done.set()))
        writer.start()
        try:
            self.assertTrue(changed.wait(2)); reader.start()
            self.assertFalse(snapshot_done.is_set())
        finally:
            release.set(); writer.join(2)
            if reader.ident is not None: reader.join(2)
        self.assertEqual(snapshots[0][0].version, 1)
        self.assertEqual(snapshots[0][1], {1: 95})

    def test_authenticated_api_roundtrip_stale_and_failed_save(self):
        import json
        import urllib.error
        import urllib.request
        from tests.test_web_server import _make_context, _http_get
        from spritelens.web.server import LocalServer
        with TemporaryDirectory() as directory:
            context = _make_context(Path(directory), self.pets[:2])
            context.static_data, context.egg_catalog = self.static, self.eggs
            context.pet_repository._account.observe(PlayerIdentity(101, "合成账号", 1))
            server = LocalServer(context); server.start()
            root = f"http://127.0.0.1:{server.port}/api/breeding-planner/"
            def post(action, body):
                request = urllib.request.Request(root + action, json.dumps(body).encode(), {"Content-Type": "application/json", "X-Local-Token": server.token})
                try:
                    with urllib.request.urlopen(request, timeout=5) as response:
                        return response.status, json.load(response)
                except urllib.error.HTTPError as error:
                    return error.code, json.load(error)
            try:
                self.assertEqual(_http_get(root + "context")[0], 401)
                status, info = _http_get(root + "context", server.token)
                self.assertEqual(status, 200)
                request = Request(mode="selected", selected=("1", "2"))
                body = {**asdict(request), "selected": list(request.selected), "goals": [], "placements": [], "approved": [],
                        "uid": 101, "version": info["version"], "revision": 4, "catalog_version": info["catalog_version"],
                        "rule_version": info["rule_version"], "geometry_version": info["geometry_version"]}
                status, result = post("solve", body)
                self.assertEqual(status, 200, result)
                self.assertEqual(result["plans"][0]["metrics"]["effective_mothers"], 1)
                saved = {**body, "placements": result["plans"][0]["placements"]}
                self.assertEqual(post("draft", saved)[0], 200)
                restored = _http_get(root + "draft?mode=selected", server.token)[1]["draft"]
                self.assertEqual(restored["placements"], saved["placements"])
                self.assertEqual(post("evaluate", {**saved, "uid": 202})[0], 409)
                self.assertEqual(post("evaluate", {**saved, "catalog_version": "old"})[0], 409)
                with patch.object(context.settings, "set_checked", side_effect=OSError("full")):
                    self.assertEqual(post("draft", saved)[0], 500)
                context.settings.set_checked("breeding-planner.101.selected", {**restored, "geometry_version": "old-grid"})
                self.assertIsNotNone(_http_get(root + "draft?mode=selected", server.token)[1]["draft"])
                context.settings.set_checked("breeding-planner.101.selected", {"schema_version": "bad"})
                self.assertIn("error", _http_get(root + "draft?mode=selected", server.token)[1])
            finally:
                server.stop(); context.close()
