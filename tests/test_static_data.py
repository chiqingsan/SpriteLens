"""静态映射数据测试：加载、索引与降级行为。

重点覆盖「关联键必须正确」——这是实测踩过的坑：conf_id（实例 ID）与
base_conf_id（物种 ID）不是一回事，用错会索引到别的宠物。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from spritelens.domain.static_data import StaticData, load_static_data


def _write(dir_path: Path, name: str, payload: dict) -> None:
    (dir_path / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _make_dir(test: unittest.TestCase) -> Path:
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    test.addCleanup(tmp.cleanup)
    return Path(tmp.name)


class StaticDataTest(unittest.TestCase):
    def setUp(self):
        self.dir = _make_dir(self)

    def _load(self) -> StaticData:
        return StaticData(self.dir)

    def test_loads_species_by_base_conf_id(self):
        _write(self.dir, "species.json", {
            "3033": {
                "name": "波波拉", "types": [2], "type_names": ["水"],
                "stats": {"hp": 100, "atk": 50, "spa": 60, "def": 55, "spd": 58, "spe": 62, "sum": 385},
                "quality": 2, "stage": 2, "max_energy": 10, "evolutions": [1, 2],
            }
        })
        sd = self._load()
        info = sd.species(3033)
        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(info.name, "波波拉")
        self.assertEqual(info.type_names, ("水",))
        self.assertEqual(info.stat_sum, 385)
        self.assertEqual(info.evolutions, (1, 2))

    def test_species_index_is_not_conf_id(self):
        """回归：物种表按 base_conf_id 索引，用 conf_id 查不到（不通配）。"""
        _write(self.dir, "species.json", {"3033": {"name": "波波拉", "stats": {}}})
        sd = self._load()
        self.assertIsNotNone(sd.species(3033))
        self.assertIsNone(sd.species(2000671))  # conf_id 不该命中

    def test_loads_natures_types_skills(self):
        _write(self.dir, "natures.json", {
            "15": {"name": "理性", "positive_stat": "spa", "negative_stat": "atk"},
        })
        _write(self.dir, "types.json", {
            "2": {"name": "水", "name_en": "Water", "color": "#6890F0"},
        })
        _write(self.dir, "skills.json", {
            "7050210": {"name": "天洪", "desc": "造成魔伤", "type_id": 2, "energy_cost": 7},
        })
        sd = self._load()
        self.assertEqual(sd.nature(15).name, "理性")
        self.assertEqual(sd.nature_name(15), "理性")
        self.assertEqual(sd.type_info(2).color, "#6890F0")
        self.assertEqual(sd.skill(7050210).name, "天洪")
        self.assertEqual(sd.skill(7050210).energy_cost, 7)

    def test_fallback_when_missing(self):
        """缺表/缺条目时返回 None 或原值，不抛错。"""
        sd = self._load()  # 目录为空
        self.assertIsNone(sd.species(1))
        self.assertIsNone(sd.nature(1))
        self.assertIsNone(sd.type_info(1))
        self.assertIsNone(sd.skill(1))
        self.assertEqual(sd.nature_name(9), "9")
        self.assertEqual(sd.skill_name(9), "9")
        self.assertEqual(sd.type_color(9), "")
        self.assertFalse(sd.available)

    def test_none_directory_is_empty(self):
        sd = StaticData(None)
        self.assertFalse(sd.available)
        self.assertEqual(sd.stats()["species_total"], 0)

    def test_malformed_table_ignored(self):
        (self.dir / "species.json").write_text("{ not json", encoding="utf-8")
        _write(self.dir, "skills.json", {"1": {"name": "有效技能"}})
        sd = self._load()
        self.assertIsNone(sd.species(1))
        self.assertEqual(sd.skill_name(1), "有效技能")  # 坏表不影响好表

    def test_hit_miss_counters(self):
        _write(self.dir, "species.json", {"1": {"name": "甲", "stats": {}}})
        sd = self._load()
        sd.species(1)
        sd.species(2)
        sd.species(3)
        stats = sd.stats()
        self.assertEqual(stats["species_hits"], 1)
        self.assertEqual(stats["species_misses"], 2)


class BundledStaticDataTest(unittest.TestCase):
    """随仓库分发的 data/static/ 应可用（缺文件则跳过，不误报失败）。"""

    def test_bundled_tables_load(self):
        sd = load_static_data()
        if not sd.available:
            self.skipTest("data/static/ 未随仓库分发")
        stats = sd.stats()
        self.assertGreater(stats["species_total"], 100)
        self.assertGreater(stats["skills"], 100)
        self.assertGreater(stats["natures"], 0)


if __name__ == "__main__":
    unittest.main()
