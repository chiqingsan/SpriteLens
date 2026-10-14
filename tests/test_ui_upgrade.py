"""主题偏好、参考范围、组合筛选和资源合并契约。"""
from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

from spritelens.domain.eggs import EggCatalog
from spritelens.domain.measurements import range_position
from spritelens.domain.static_data import StaticData
from spritelens.repositories.settings import SettingsRepository
from spritelens.view_models.pet_vm import PetViewModel
from spritelens.view_models.ui_preferences import UIPreferencesViewModel
from spritelens.web.server import LocalServer
from tests.test_web_server import _make_context, _pet, _http_get, _http_post
from tools.sync_catalog_resources import merge_species

ROOT = Path(__file__).resolve().parent.parent


class PreferencesTest(unittest.TestCase):
    def test_legacy_presets_migrate_once_and_empty_shortcuts_survive_restart(self):
        custom = {"name": "雌性", "filters": {"gender": 2}}
        self.repo.set("ui.preferences", {"shortcuts": [custom]})
        self.assertEqual([item["name"] for item in self.vm.snapshot()["shortcuts"]],
                         ["大块头", "小不点", "婉转声", "粗嗓门", "雌性"])
        self.vm.update({"shortcuts": []})
        self.assertEqual(UIPreferencesViewModel(SettingsRepository(self.path)).snapshot()["shortcuts"], [])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "config.json"
        self.repo = SettingsRepository(self.path)
        self.vm = UIPreferencesViewModel(self.repo)

    def test_reject_business_filters_and_bad_values(self):
        for changes in ({"search": "foo"}, {"theme": "dark"}, {"theme": []}, {"fields": {"height": 1}}, {"fields": {"foo": False}}, []):
            with self.assertRaises(ValueError):
                self.vm.update(changes)

    def test_write_failure_does_not_change_memory(self):
        with patch.object(Path, "replace", side_effect=OSError("read only")):
            with self.assertRaises(OSError):
                self.vm.update({"theme": "shuilanlan"})
        self.assertEqual(self.vm.snapshot()["theme"], "miaomiao")

    def test_concurrent_partial_saves_preserve_both(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(self.vm.update, ({"theme": "huohua"}, {"fields": {"voice": False}})))
        self.assertEqual(self.vm.snapshot()["theme"], "huohua")
        self.assertFalse(self.vm.snapshot()["fields"]["voice"])

    def test_shortcut_restart_and_display_preferences_are_independent(self):
        shortcut = {"name": "  植物体型  ", "filters": {"egg_groups": ["植物"], "egg_mode": "all", "height_position_min": 50, "voice_min": -100}}
        self.vm.update({"shortcuts": [shortcut]})
        self.vm.update({"theme": "huohua", "fields": {"positions": True}})
        restored = UIPreferencesViewModel(SettingsRepository(self.path)).snapshot()
        self.assertEqual(restored["shortcuts"][0]["name"], "植物体型")
        self.assertEqual(restored["shortcuts"][0]["filters"], shortcut["filters"])
        self.assertTrue(restored["fields"]["positions"])
        self.vm.update({"shortcuts": []})
        self.assertEqual(self.vm.snapshot()["shortcuts"], [])

    def test_invalid_shortcut_does_not_replace_saved_definitions(self):
        valid = {"name": "雌性", "filters": {"gender": 2}}
        self.vm.update({"shortcuts": [valid]})
        for filters in ({"sort": "gid"}, {"gender": True}, {"natures": [True]}, {"medals": [0]}, {"medals": [True]},
                        {"voice_min": float("nan")}, {"height_position_max": 101},
                        {"height_min": -1}, {"egg_groups": ["植物", {}]}):
            with self.subTest(filters=filters), self.assertRaises(ValueError):
                self.vm.update({"shortcuts": [{"name": "bad", "filters": filters}]})
        self.assertEqual(self.vm.snapshot()["shortcuts"], [valid])
        with self.assertRaises(ValueError):
            self.vm.update({"shortcuts": [valid] * 257})


class MeasurementsTest(unittest.TestCase):
    def test_positions_and_bounds(self):
        self.assertEqual(range_position(64, (53, 75)), {"ratio": .5, "status": "within"})
        self.assertEqual(range_position(52, (53, 75))["status"], "below")
        self.assertEqual(range_position(80, (53, 75))["status"], "above")
        self.assertIsNone(range_position(0, (53, 75))["ratio"])

    def test_merge_is_idempotent_preserves_valid_values(self):
        table = {"1": {"name": "existing", "height_range": [50, 70]}}
        refs = [{"id": 1, "name": "different", "heightLow": 60, "heightHigh": 90},
                {"id": 2, "name": "new", "heightLow": 40, "heightHigh": 60}]
        added, conflicts = merge_species(table, refs)
        self.assertEqual(added, ["2"])
        self.assertEqual(table["1"]["height_range"], [50, 70])
        self.assertTrue(any(x["field"] == "name" for x in conflicts))
        snapshot = json.dumps(table, sort_keys=True)
        self.assertEqual(merge_species(table, refs)[0], [])
        self.assertEqual(json.dumps(table, sort_keys=True), snapshot)

    def test_merge_repairs_invalid_range_only(self):
        table = {"1": {"name": "one", "height_range": [90, 50]}}
        merge_species(table, [{"id": 1, "heightLow": 50, "heightHigh": 80}])
        self.assertEqual(table["1"]["height_range"], [50, 80])


class UpgradeAPITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.ctx = _make_context(root, (
            replace(_pet(1, name="A", level=60, first=True, base_conf=3001), height=64, weight=4000, voice=-20),
            replace(_pet(2, name="B", level=30, base_conf=3002), height=80, weight=8000, voice=30),
            replace(_pet(3, name="C", level=60, base_conf=3001), height=90, weight=8000, voice=0),
        ))
        (root / "species.json").write_text(json.dumps({
            "3001": {"name": "A", "display_name": "物种甲", "dex_no": 9876, "egg_groups": ["植物", "精灵"], "height_range": [53, 75], "weight_range": [3620, 4600]},
            "3002": {"name": "B", "egg_groups": ["精灵"]},
        }), encoding="utf-8")
        (root / "natures.json").write_text(json.dumps({"1": {"name": "合成性格"}, "99": {"name": "未持有性格"}}), encoding="utf-8")
        (root / "types.json").write_text(json.dumps({"1": {"name": "未持有系别"}}), encoding="utf-8")
        (root / "medals.json").write_text(json.dumps({"1001": "未佩戴奖牌"}), encoding="utf-8")
        cls.ctx.static_data = StaticData(root)
        cls.ctx.pet_vm = PetViewModel(cls.ctx.pet_repository, cls.ctx.static_data)
        cls.ctx.egg_catalog = EggCatalog(ROOT / "data/static")
        cls.server = LocalServer(cls.ctx, token="upgrade-test", port=0)
        cls.server.start()
        cls.url = f"http://127.0.0.1:{cls.server.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        cls.ctx.close()
        cls.tmp.cleanup()

    def get_pets(self, **query):
        status, payload = _http_get(self.url + "/api/pets?" + urlencode(query), "upgrade-test")
        self.assertEqual(status, 200)
        return payload

    def test_search_species_dex_and_egg_group_with_other_conditions(self):
        for search in ("物种甲", "9876", "植物"):
            self.assertEqual([pet["gid"] for pet in self.get_pets(search=search)["pets"]], [1, 3])
        self.assertEqual([pet["gid"] for pet in self.get_pets(search="植物", voice_max=-10)["pets"]], [1])

    def test_filter_options_include_catalog_choices_not_owned_yet(self):
        options = self.get_pets()["options"]
        self.assertIn({"id": 99, "name": "未持有性格"}, options["natures"])
        self.assertIn("未持有系别", options["types"])
        self.assertIn({"id": 1001, "name": "未佩戴奖牌"}, options["medals"])

    def test_slider_limits_use_full_inventory_even_after_filtering(self):
        limits = self.get_pets()["options"]["measurement_limits"]
        self.assertEqual(limits, {"height": {"min": 0, "max": 1}, "weight": {"min": 0, "max": 8}, "voice": {"min": -100, "max": 100}})
        self.assertEqual(self.get_pets(search="A")["options"]["measurement_limits"], limits)

    def test_any_all_and_combined_range_reset(self):
        self.assertEqual(self.get_pets(egg_groups="植物,精灵", pool_mode="or")["shown"], 3)
        self.assertEqual(self.get_pets(egg_groups="植物,精灵", pool_mode="and")["shown"], 2)
        payload = self.get_pets(egg_groups="植物", height_min=.6, height_max=.7, weight_max=5, voice_max=-10, first_catch=1)
        self.assertEqual([x["gid"] for x in payload["pets"]], [1])
        self.assertEqual(self.get_pets()["shown"], 3)
        self.assertFalse(self.ctx.pet_vm.filters.active)

    def test_pool_mode_applies_to_each_detail_condition(self):
        self.assertEqual(self.get_pets(level_min=60, voice_min=20, pool_mode="and")["shown"], 0)
        self.assertEqual(self.get_pets(level_min=60, voice_min=20, pool_mode="or")["shown"], 3)
        self.assertEqual(self.get_pets(search="a", level_min=60, voice_min=20, pool_mode="or")["shown"], 2)
        self.assertEqual(self.get_pets(voice_min=20, pool_mode="or")["shown"], 1)

    def test_invalid_range_normalization(self):
        filters = self.get_pets(height_min="nan", weight_max="inf", voice_min=40, voice_max=-30, egg_mode="bad")["filters"]
        self.assertIsNone(filters["height_min"])
        self.assertIsNone(filters["weight_max"])
        self.assertEqual((filters["voice_min"], filters["voice_max"]), (-30, 40))
        self.assertEqual(filters["egg_mode"], "any")

    def test_unavailable_measurement_does_not_match_zero_range(self):
        self.assertEqual(self.get_pets(voice_min=0, voice_max=0)["shown"], 0)

    def test_positions_combine_exclude_unknown_and_outside(self):
        result = self.get_pets(height_position_min=50, height_position_max=50, weight_position_max=50, egg_groups="植物", height_max=.7)
        self.assertEqual([pet["gid"] for pet in result["pets"]], [1])
        self.assertEqual(self.get_pets(height_position_min=0, height_position_max=100)["shown"], 1)
        filters = self.get_pets(height_position_min=80, height_position_max=20, weight_position_min=-1, weight_position_max=101)["filters"]
        self.assertEqual((filters["height_position_min"], filters["height_position_max"]), (20, 80))
        self.assertIsNone(filters["weight_position_min"])
        self.assertIsNone(filters["weight_position_max"])
        self.assertEqual(self.get_pets()["shown"], 3)

    def test_saving_shortcut_does_not_apply_business_filters(self):
        self.get_pets()
        definition = {"name": "植物", "filters": {"egg_groups": ["植物"], "height_position_min": 50}}
        self.assertEqual(_http_post(self.url + "/api/ui/preferences", "wrong", {"shortcuts": [definition]})[0], 401)
        status, result = _http_post(self.url + "/api/ui/preferences", "upgrade-test", {"shortcuts": [definition]})
        self.assertEqual(status, 200)
        self.assertEqual(result["shortcuts"], [definition])
        self.assertFalse(self.ctx.pet_vm.filters.active)
        self.assertEqual(_http_post(self.url + "/api/ui/preferences", "upgrade-test", {"shortcuts": [{"name": "bad", "filters": {"height_position_min": 150}}]})[0], 400)

    def test_ratios_do_not_depend_on_filter_result(self):
        first = next(pet for pet in self.get_pets()["pets"] if pet["gid"] == 1)
        filtered = self.get_pets(search="A")["pets"][0]
        self.assertEqual(first["height_pct"], .5)
        self.assertEqual(first["range_positions"], filtered["range_positions"])
        self.assertEqual(first["egg_ranges"]["height"], "0.23–0.31 m")
        unknown = self.get_pets(search="B")["pets"][0]
        self.assertEqual(unknown["reference_ranges"]["height"], "暂无数据")
        self.assertIsNone(unknown["range_positions"]["height"]["ratio"])

    def test_preferences_auth_validation_and_bootstrap(self):
        self.assertEqual(_http_get(self.url + "/api/ui/preferences")[0], 401)
        self.assertEqual(_http_post(self.url + "/api/ui/preferences", "wrong", {"theme": "huohua"})[0], 401)
        self.assertEqual(_http_post(self.url + "/api/ui/preferences", "upgrade-test", {"search": "A"})[0], 400)
        status, result = _http_post(self.url + "/api/ui/preferences", "upgrade-test", {"theme": "shuilanlan", "fields": {"height": False}})
        self.assertEqual(status, 200)
        self.assertFalse(result["fields"]["height"])
        payload = _http_get(self.url + "/api/bootstrap", "upgrade-test")[1]
        self.assertEqual(payload["ui_preferences"], result)
        restored = UIPreferencesViewModel(SettingsRepository(Path(self.tmp.name) / "config.json")).snapshot()
        self.assertEqual(restored, result)

    def test_write_failure_returns_500(self):
        with patch.object(SettingsRepository, "update_checked", side_effect=OSError("denied")):
            status, value = _http_post(self.url + "/api/ui/preferences", "upgrade-test", {"theme": "huohua"})
        self.assertEqual(status, 500)
        self.assertIn("保存失败", value["error"])
