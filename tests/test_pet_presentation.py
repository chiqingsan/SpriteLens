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
                                        (1021, -95, []), (1979, 95, []), (0, 0, []),
                                        (999, 0, []), (2001, 0, [])):
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

    def test_colors_payload_keeps_unresolved_numbers_out_of_the_grid(self):
        """编号解析不出来的持有者进 unknown，不能让前端渲染没有编号的裸卡面。"""
        from types import SimpleNamespace

        catalog = ColorCatalog(static_dir())
        unresolved = replace(_pet(1, name="假帧", level=10, first=True), glass_type=2, glass_value=99, mutation_type=8)
        unknown_number = replace(_pet(2, name="未来卡", level=10, first=True), glass_type=1, glass_value=41, mutation_type=8)
        seasonal = replace(_pet(3, name="赛季", level=10, first=True), glass_type=2, glass_value=4, mutation_type=8)

        class Repo:
            def consistent_snapshot(self):
                return SimpleNamespace(pets=(unresolved, unknown_number, seasonal), uid=7, version=3)

        payload = colors_payload(Repo(), catalog, None)
        self.assertEqual(payload["pet_total"], 3)
        self.assertEqual(payload["matrix"], {})
        # card_id_for 只认目录里有的编号：赛季值不在 {1..4,1000}、或编号不在 44 张里，都返回空串。
        # 这些持有者进 unknown，前端按「编号未解析」提示，不会再渲染孤立的「#」。
        self.assertEqual([row["card_id"] for row in payload["unknown"]], ["", ""])
        self.assertEqual([row["unresolved"] for row in payload["unknown"]], [True, True])
        self.assertEqual([row["gid"] for row in payload["seasonal"]], [seasonal.gid])
        self.assertEqual([row["card_id"] for row in payload["seasonal"]], ["s4"])

    def test_colors_payload_exposes_full_grid_and_card_labels(self):
        from types import SimpleNamespace

        class EmptyRepo:
            def consistent_snapshot(self):
                return SimpleNamespace(pets=(), uid=0, version=0)

        catalog = ColorCatalog(static_dir())
        rows = catalog.cards()
        if not rows or not getattr(rows[0], "card_id", ""):
            self.skipTest("色卡目录缺失")
        fair = [card for card in rows if not ColorCatalog.is_seasonal(card.card_id)]
        by_base: dict[str, set[str]] = {}
        for card in fair:
            by_base.setdefault(card.base_name, set()).add(card.mix_name)
        fair_keys = {f"{card.base_name}|{card.mix_name}" for card in fair}

        payload = colors_payload(EmptyRepo(), catalog, None)
        self.assertEqual(payload["card_total"], len(rows))
        self.assertEqual(len(payload["catalogs"]), len(rows))
        # 格子元数据 = 每张卡一组底色×混色（含赛季卡自己那组），供前端区分「空位」与「有卡未持有」
        self.assertTrue(fair_keys <= set(payload["cells"]))
        self.assertEqual(len(payload["cells"]), len(fair_keys) + len(rows) - len(fair))
        self.assertLessEqual(len(payload["cells"]), len(rows))
        for key, cell in payload["cells"].items():
            self.assertEqual(key, f"{cell['base_name']}|{cell['mix_name']}")
            self.assertEqual(cell["pet_count"], 0)
            self.assertTrue(cell["label"])
        # 赛季卡不进坐标轴：否则矩阵会多出永远不可能有普通卡的一行四列
        base_order: list[str] = []
        for card in fair:
            if card.base_name not in base_order:
                base_order.append(card.base_name)
        self.assertEqual([a["name"] for a in payload["base_axis"]], base_order)
        self.assertNotIn("赛季", [a["name"] for a in payload["base_axis"]])
        self.assertFalse([a for a in payload["mix_axis"] if a["name"].startswith("S")])
        # 轴字母按首次出现顺序编号，和轴向量的下标一一对应
        self.assertEqual(
            [a["letter"] for a in payload["base_axis"]],
            [chr(ord("A") + i) for i in range(len(base_order))],
        )
        # 卡面标签 = 底色字母 + 混色序号，且不重名（字母按轴内首次出现编号）
        labels = [c["label"] for c in payload["catalogs"]]
        self.assertEqual(len(set(labels)), len(labels))
        self.assertEqual(payload["catalogs"][0]["label"], "A1")
        self.assertEqual(
            [a["letter"] for a in payload["base_axis"]],
            [chr(ord("A") + i) for i in range(len(by_base))],
        )
