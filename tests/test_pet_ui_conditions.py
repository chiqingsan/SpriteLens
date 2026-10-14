"""定稿筛选：真实奖牌、参考标记、条件池与查询边界。"""
from __future__ import annotations

import unittest
from dataclasses import replace
from unittest.mock import Mock

from spritelens.domain.pet_conditions import matches_conditions
from spritelens.web.pet_queries import pet_ui_query
from spritelens.domain.pets import Pet


class PetUIConditionsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.static = Mock()
        self.static.species.return_value.weight_range = (1000, 2000)
        self.static.species.return_value.height_range = (50, 100)
        self.pet = replace(Pet(1, 1, "合成精灵", 60, 0, 1, 1, 0, 0, False), height=100, weight=2000,
                           gender=1, mutation_type=1, worn_medal_id=0, voice=98, speciality_id=7)

    def matches(self, pet=None, **values) -> bool:
        defaults = dict(pool=frozenset(), pool_mode="and", shiny=False, colorful=False,
                        medal=0, marks=frozenset(), speciality=0)
        return matches_conditions(pet or self.pet, self.static, **(defaults | values))

    def test_pool_and_or_and_reference_is_not_awarded_medal(self) -> None:
        pool = frozenset({"male", "medal"})
        self.assertFalse(self.matches(pool=pool))
        self.assertTrue(self.matches(pool=pool, pool_mode="or"))
        self.assertTrue(self.matches(marks=frozenset({"大块头", "婉转声"})))
        self.assertFalse(self.matches(marks=frozenset({"小不点"})))
        self.assertTrue(self.matches(pool=frozenset({"max_height", "max_weight"})))
        self.assertFalse(self.matches(replace(self.pet, height=101), pool=frozenset({"max_height"})))

    def test_direct_filters_combine_and_unknown_values_do_not_match(self) -> None:
        self.assertTrue(self.matches(shiny=True, speciality=7))
        self.assertFalse(self.matches(shiny=True, colorful=True))
        self.assertFalse(self.matches(speciality=8))
        self.assertTrue(self.matches(replace(self.pet, worn_medal_id=1001), medal=1001))
        self.assertFalse(self.matches(medal=1001))

    def test_multiple_medals_obey_global_mode_and_query_keeps_all_ids(self) -> None:
        pet = replace(self.pet, worn_medal_id=1010)
        choices = frozenset({1010, 1006})
        self.assertFalse(self.matches(pet, medals=choices))
        self.assertTrue(self.matches(pet, medals=choices, pool_mode="or"))
        self.assertTrue(self.matches(pet, medals=frozenset({1010}), marks=frozenset({"大块头", "婉转声"})))
        self.assertEqual(pet_ui_query({"medals": "1010,1006,1010"})["medals"], choices)
        for value in ("-1", "0", "bad"):
            with self.assertRaises(ValueError):
                pet_ui_query({"medals": value})

    def test_invalid_external_queries_fail_and_defaults_are_unrestricted(self) -> None:
        for query in ({"pool": "unknown"}, {"pool_mode": "xor"}, {"shiny": "yes"}, {"medal": "-1"}, {"marks": "unknown"}):
            with self.assertRaises(ValueError):
                pet_ui_query(query)
        self.assertFalse(pet_ui_query({})["shiny"])
        self.assertEqual(pet_ui_query({"pool": "male,shiny", "pool_mode": "or"})["pool"], frozenset({"male", "shiny"}))
