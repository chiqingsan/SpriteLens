"""头像映射、采集色卡解码及旧偏好迁移。"""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from spritelens.domain.color_cards import ColorCatalog
from spritelens.domain.pet_marks import pet_marks
from spritelens.paths import static_dir
from spritelens.repositories.settings import SettingsRepository
from spritelens.view_models.ui_preferences import UIPreferencesViewModel, normalize_preferences
from spritelens.web.payloads import pet_row, colors_payload
from tests.test_web_server import _pet


class PetPresentationTest(unittest.TestCase):
    def test_size_voice_marks_are_exclusive_and_use_exact_boundaries(self):
        pet = _pet(1, name="样本", level=1, first=False)
        for weight, voice, expected in ((1020, -96, ["小", "粗"]), (1980, 96, ["大", "婉"]),
                                        (1021, -95, []), (1979, 95, []), (0, 0, [])):
            with self.subTest(weight=weight, voice=voice):
                marks = pet_marks(replace(pet, weight=weight, voice=voice), (1000, 2000))
                self.assertEqual([m["label"] for m in marks], expected)
        self.assertEqual(pet_marks(replace(pet, weight=1000), (0, 0)), [])
        self.assertEqual(pet_marks(replace(pet, weight=1000), (1000, 1000)), [])
        marks = pet_marks(replace(pet, weight=1000, voice=-100, worn_medal_id=1001), (1000, 2000))
        self.assertEqual([m["label"] for m in marks], ["大", "粗"])
        self.assertEqual(marks[0]["source"], "worn")
        marks = pet_marks(replace(pet, weight=2000, voice=-100, worn_medal_id=1026), (1000, 2000))
        self.assertEqual([m["label"] for m in marks], ["大", "婉"])
        # 完美无瑕等纪念奖牌不进入紧凑的四种标记区。
        self.assertEqual(pet_marks(replace(pet, worn_medal_id=1010), (0, 0)), [])

    def test_saved_shortcuts_keep_other_filters_after_first_catch_removal(self):
        saved = [{"name": "条件", "filters": {"first_catch_only": True, "gender": 2, "natures": [3]}}]
        normalized = normalize_preferences({"shortcuts": saved})
        self.assertEqual(normalized["shortcuts"][-1], {"name": "条件", "filters": {"gender": 2, "natures": [3]}})
        with tempfile.TemporaryDirectory() as tmp:
            vm = UIPreferencesViewModel(SettingsRepository(Path(tmp) / "config.json"))
            with self.assertRaises(ValueError):
                vm.update({"shortcuts": saved})

    def test_home_display_order_is_saved_per_account_and_rejects_invalid_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            vm = UIPreferencesViewModel(SettingsRepository(Path(tmp) / "config.json"))
            orders = {"101": ["9007199254740993", "9007199254740994"]}
            saved = vm.update({"home_orders": orders})
            self.assertEqual(saved["home_orders"], orders)
            self.assertEqual(vm.snapshot()["home_orders"], orders)
            with self.assertRaises(ValueError):
                vm.update({"home_orders": {"101": ["01"]}})

    def test_real_glass_packed_card_and_particles(self):
        catalog = ColorCatalog(static_dir())
        # 觅觅蝠真实样本：卡 37、四角星。
        card = catalog.effect_for(1, 1048613)
        self.assertEqual((card["card_id"], card["particle_id"]), ("37", 1))
        self.assertEqual((card["base_color"], card["mix_color"]), ("#3c32cf", "#f1d397"))
        for particle in range(1, 5):
            self.assertEqual(catalog.effect_for(1, (particle << 20) | 37)["particle_id"], particle)
        self.assertEqual(catalog.effect_for(1, (9 << 20) | 37)["particle_id"], 0)
        self.assertIsNone(catalog.effect_for(1, 999999))
        self.assertEqual(catalog.effect_for(2, 1000)["card_id"], "1000")
        self.assertEqual(catalog.effect_for(2, 4)["card_id"], "s4")

    def test_color_card_requires_colorful_flag_and_shiny_is_independent(self):
        catalog = ColorCatalog(static_dir())
        pet = replace(_pet(1, name="觅觅蝠", level=55, first=True), glass_type=1, glass_value=1048613, mutation_type=9)
        row = pet_row(pet, None, 0, 0, catalog)
        self.assertTrue(row["is_shiny"])
        self.assertEqual(row["color_card"]["card_id"], "37")
        self.assertNotIn("is_first_catch", row)
        ordinary = pet_row(replace(pet, mutation_type=0), None, 0, 0, catalog)
        self.assertIsNone(ordinary["color_card"])
        self.assertFalse(ordinary["is_shiny"])
        class Repo:
            def consistent_snapshot(self):
                from types import SimpleNamespace
                return SimpleNamespace(pets=(replace(pet, mutation_type=0), pet), uid=0, version=0)
        matrix = colors_payload(Repo(), catalog, None)
        self.assertEqual(matrix["pet_total"], 1)
        self.assertEqual(next(iter(matrix["matrix"].values()))[0]["color_card"]["particle_id"], 1)
