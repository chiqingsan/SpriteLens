"""静态映射数据测试：加载、索引与降级行为。

重点覆盖「关联键必须正确」——这是实测踩过的坑：conf_id（实例 ID）与
base_conf_id（物种 ID）不是一回事，用错会索引到别的宠物。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from spritelens.domain.static_data import StaticData


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

    def test_species_index_is_not_conf_id(self):
        """回归：物种表按 base_conf_id 索引，用 conf_id 查不到（不通配）。"""
        _write(self.dir, "species.json", {"3033": {"name": "波波拉", "stats": {}}})
        sd = self._load()
        self.assertIsNotNone(sd.species(3033))
        self.assertIsNone(sd.species(2000671))  # conf_id 不该命中

    def test_malformed_table_ignored(self):
        (self.dir / "species.json").write_text("{ not json", encoding="utf-8")
        _write(self.dir, "skills.json", {"1": {"name": "有效技能"}})
        sd = self._load()
        self.assertIsNone(sd.species(1))
        self.assertEqual(sd.skill_name(1), "有效技能")  # 坏表不影响好表

if __name__ == "__main__":
    unittest.main()
