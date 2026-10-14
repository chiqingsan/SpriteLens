"""宠物 ViewModel 测试：筛选、排序与聚合（无 UI 框架依赖）。

覆盖 roco_helper 式筛选器的核心维度：等级范围 / 性格 / 系别 / 天赋 /
首捕 / 搜索，以及排序与统计接口。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from spritelens.domain.pets import Pet, PetAttribute
from spritelens.domain.static_data import StaticData
from spritelens.services.pet_repository import PetRepository
from spritelens.view_models.pet_vm import PetViewModel


def _attr(value: int, race: int = 100) -> PetAttribute:
    return PetAttribute(total_race=race, talent=10, base_value=value)


def _pet(
    gid: int,
    *,
    name: str = "宠物",
    level: int = 30,
    nature: int = 1,
    talent: int = 3,
    base_conf: int = 100,
    first: bool = False,
    stat_sum: int = 600,
) -> Pet:
    per = stat_sum // 6
    return Pet(
        gid=gid,
        conf_id=2000000 + gid,
        name=name,
        level=level,
        exp=0,
        nature=nature,
        gender=1,
        blood_id=1,
        talent_rank=talent,
        is_first_catch=first,
        base_conf_id=base_conf,
        attributes=tuple(_attr(per) for _ in range(6)),
    )


def _make_static(tmp: Path) -> StaticData:
    """三只物种构成的迷你可控静态表。"""
    (tmp / "species.json").write_text(
        json.dumps(
            {
                "100": {"name": "火兽", "types": [1], "type_names": ["火"], "stats": {"hp": 100, "sum": 500}, "dex_no": 10},
                "200": {"name": "水兽", "types": [2], "type_names": ["水"], "stats": {"hp": 90, "sum": 480}, "dex_no": 20},
                "300": {"name": "双系兽", "types": [1, 3], "type_names": ["火", "草"], "stats": {"hp": 80, "sum": 460}, "dex_no": 30},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (tmp / "natures.json").write_text(
        json.dumps(
            {
                "1": {"name": "开朗", "positive_stat": "spe", "negative_stat": "spa"},
                "2": {"name": "固执", "positive_stat": "atk", "negative_stat": "spa"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return StaticData(tmp)


class PetViewModelTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        self.static = _make_static(tmp)
        self.repo = PetRepository()
        for pet in (
            _pet(1, name="小火兽", level=50, nature=1, talent=5, base_conf=100, first=True, stat_sum=700),
            _pet(2, name="大水兽", level=30, nature=2, talent=3, base_conf=200),
            _pet(3, name="双系兽", level=10, nature=1, talent=1, base_conf=300),
            _pet(4, name="火兽", level=60, nature=2, talent=5, base_conf=100, first=True),
        ):
            self.repo._pets[pet.gid] = pet
        self.vm = PetViewModel(self.repo, static_data=self.static)

    # -- 搜索 ----------------------------------------------------------
    def test_search_matches_name_gid_conf(self):
        self.vm.set_search("小火")
        self.assertEqual([p.gid for p in self.vm.filtered_pets()], [1])
        self.vm.set_search("2000002")
        self.assertEqual([p.gid for p in self.vm.filtered_pets()], [2])
        self.vm.set_search("")
        self.assertEqual(len(self.vm.filtered_pets()), 4)

    # -- 维度筛选 ------------------------------------------------------
    def test_gender_composes_and_resets(self):
        self.repo._pets[2] = replace(self.repo._pets[2], gender=2)
        self.repo._pets[3] = replace(self.repo._pets[3], gender=0)
        self.vm.set_gender(2)
        self.assertTrue(self.vm.filters.active)
        self.assertEqual([p.gid for p in self.vm.filtered_pets()], [2])
        self.vm.set_level_range(40, 100)
        self.assertEqual(self.vm.filtered_pets(), ())
        self.vm.reset_filters()
        self.assertEqual(len(self.vm.filtered_pets()), 4)
        self.vm.set_gender(1)
        self.assertEqual([p.gid for p in self.vm.filtered_pets()], [1, 4])
        self.vm.set_gender(99)
        self.assertFalse(self.vm.filters.active)

    def test_type_filter_uses_static_species(self):
        self.vm.set_types(frozenset({"水"}))
        self.assertEqual([p.gid for p in self.vm.filtered_pets()], [2])
        # 双系兽带火，应按交集命中
        self.vm.set_types(frozenset({"火"}))
        self.assertEqual(sorted(p.gid for p in self.vm.filtered_pets()), [1, 3, 4])

    def test_filters_compose(self):
        self.vm.set_level_range(20, 60)
        self.vm.set_natures(frozenset({2}))
        self.assertEqual(sorted(p.gid for p in self.vm.filtered_pets()), [2, 4])

    # -- 排序 ----------------------------------------------------------
    def test_sort_by_level_desc(self):
        self.vm.set_sort("level", descending=True)
        self.assertEqual([p.gid for p in self.vm.filtered_pets()], [4, 1, 2, 3])

    def test_default_sort_is_dex_no(self):
        # 默认按图鉴 ID(newdex) 升序：dex10(gid1,gid4), dex20(gid2), dex30(gid3)。
        self.assertEqual([p.gid for p in self.vm.filtered_pets()], [1, 4, 2, 3])

    def test_sort_ties_break_by_dex_then_capture_time(self):
        self.repo._pets[1] = replace(self.repo._pets[1], add_time=500)
        self.repo._pets[4] = replace(self.repo._pets[4], add_time=100)
        # gid1 与 gid4 同为图鉴 10，并列时按捕捉时间升序 → gid4 在前。
        self.assertEqual([p.gid for p in self.vm.filtered_pets()], [4, 1, 2, 3])

if __name__ == "__main__":
    unittest.main()
