"""游戏获得信息的提取、持久化和筛选；不使用首次落库时间。"""
from __future__ import annotations

import unittest
from dataclasses import replace
from unittest.mock import patch

from spritelens.domain.pets import extract_pets
from spritelens.services.pet_repository import PetRepository
from spritelens.view_models.pet_vm import PetFilters, PetViewModel
from spritelens.web.pet_queries import pet_ui_query
from tests.test_pets import _named_event, _named_pet_node
from tests.test_web_server import _pet


class PetAcquisitionTest(unittest.TestCase):
    def test_protocol_fields_and_brief_update_preserve_observed_information(self):
        node = _named_pet_node(1, 100, b"synthetic", 1)
        node["children"].extend({"no": no, "name": "field_" + str(no), "raw": value}
                                for no, value in [(67, 2), (32, 1700000000)])
        event = _named_event("s2c", [node])
        pet = extract_pets(event)[0]
        self.assertEqual((pet.catch_way, pet.add_time), (2, 1700000000))
        repo = PetRepository()
        repo.handle_packet(event)
        repo.handle_packet(_named_event("s2c", [_named_pet_node(1, 100, b"synthetic", 2)]))
        self.assertEqual((repo.snapshot()[0].catch_way, repo.snapshot()[0].add_time), (2, 1700000000))

    def test_acquisition_recency_unknown_and_global_or(self):
        now = 1700000000
        base = _pet(1, name="synthetic", level=1)
        pets = (replace(base, catch_way=2, add_time=now - 86400),
                replace(base, gid=2, catch_way=3, add_time=now - 4 * 86400),
                replace(base, gid=3, catch_way=2, add_time=0))
        vm = PetViewModel(PetRepository())
        with patch("spritelens.view_models.pet_vm.time.time", return_value=now):
            self.assertEqual([p.gid for p in vm._apply_filters_with(pets, PetFilters(captured_days=1))], [1])
            self.assertEqual([p.gid for p in vm._apply_filters_with(pets, PetFilters(acquisition=3, captured_days=3))], [])
            self.assertEqual([p.gid for p in vm._apply_filters_with(pets, PetFilters(acquisition=3, captured_days=3, pool_mode="or"))], [1, 2])
        self.assertEqual(pet_ui_query({"acquisition": "2", "captured_days": "7"})["acquisition"], 2)
        for value in ("2", "-1", "invalid"):
            with self.assertRaises(ValueError):
                pet_ui_query({"captured_days": value})
