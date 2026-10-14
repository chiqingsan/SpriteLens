"""蛋目录：加载 / 索引 / 降级 / 载荷筛选。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from spritelens.domain.eggs import EggCatalog
from spritelens.web.payloads import egg_dex_payload


def _sample_data() -> dict:
    return {
        "groups": {"6": "动物组", "9": "拟人组", "5": "天空组"},
        "eggs": [
            {
                "egg_key": "喵喵#3001001", "name_key": "喵喵", "egg_conf_id": 3001001,
                "pet_egg_pet_id": 3001001, "egg_name": "喵喵蛋", "name": "喵喵",
                "owner_base_id": 3001, "base_id": 3001, "dex_no": 2, "handbook_no": "002",
                "egg_item_id": 107001, "egg_item_name": "精灵蛋",
                "egg_type_id": 0, "egg_type_name": "普通",
                "hatch_label": "12小时", "hatch_seconds": 43200,
                "egg_group_ids": [6, 9], "egg_group_names": ["动物组", "拟人组"],
                "height_low": 23, "height_high": 31, "weight_low": 1267, "weight_high": 1840,
                "chain_key": "bwiki:2", "chain_members": [3001, 3025, 3007],
                "gender_male": 50, "gender_female": 50,
            },
            {
                "egg_key": "岚鸟#3002001", "name_key": "岚鸟", "egg_conf_id": 3002001,
                "pet_egg_pet_id": 3002001, "egg_name": "岚鸟蛋", "name": "岚鸟",
                "owner_base_id": 3002, "base_id": 3002, "dex_no": 3, "handbook_no": "003",
                "egg_item_id": 107002, "egg_item_name": "精灵蛋",
                "egg_type_id": 0, "egg_type_name": "活动蛋",
                "hatch_label": "8小时", "hatch_seconds": 28800,
                "egg_group_ids": [5], "egg_group_names": ["天空组"],
                "height_low": 40, "height_high": 60, "weight_low": 3000, "weight_high": 4000,
                "chain_key": "bwiki:3", "chain_members": [3002],
            },
        ],
        "egg_conf_index": {"3001001": "喵喵#3001001", "3002001": "岚鸟#3002001"},
    }


class EggCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.tmp.name)
        (self.dir_path / "eggs.json").write_text(
            json.dumps(_sample_data(), ensure_ascii=False), encoding="utf-8"
        )
        self.catalog = EggCatalog(self.dir_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_entries_sorted_and_indexed(self) -> None:
        entries = self.catalog.entries()
        self.assertEqual([e.name_key for e in entries], ["喵喵", "岚鸟"])
        self.assertEqual(self.catalog.egg(3001001).egg_name, "喵喵蛋")
        self.assertIsNone(self.catalog.egg(999))
        self.assertEqual(self.catalog.egg_by_base_id(3002).name_key, "岚鸟")
        self.assertEqual(self.catalog.stats()["eggs"], 2)

    def test_payload_filters(self) -> None:
        by_group = egg_dex_payload(self.catalog, group="天空组")
        self.assertEqual([e["name"] for e in by_group["eggs"]], ["岚鸟"])
        by_type = egg_dex_payload(self.catalog, egg_type="普通")
        self.assertEqual([e["name"] for e in by_type["eggs"]], ["喵喵"])
        by_hatch = egg_dex_payload(self.catalog, hatch_min_hours=10)
        self.assertEqual([e["name"] for e in by_hatch["eggs"]], ["喵喵"])
        by_search = egg_dex_payload(self.catalog, search="3002")
        self.assertEqual([e["name"] for e in by_search["eggs"]], ["岚鸟"])

if __name__ == "__main__":
    unittest.main()
