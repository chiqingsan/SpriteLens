"""F01：请求读取后切号，单响应的宠物/统计/身份/选项仍来自同一快照。"""
from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from spritelens.domain.identity import PlayerIdentity
from spritelens.domain.pet_locations import Backpack, PetBox
from spritelens.domain.static_data import NatureInfo, SpeciesInfo, StaticData
from spritelens.view_models.pet_vm import PetFilters, PetViewModel
from spritelens.web.payloads import overview_payload, pets_payload
from spritelens.web.server import LocalServer
from tests.test_web_server import _make_context, _pet


class PetSnapshotContractTest(unittest.TestCase):
    def test_type_options_exclude_placeholder_names_and_keep_normal(self) -> None:
        static = StaticData(Path(__file__).resolve().parents[1] / "data" / "static")
        vm = PetViewModel(self.repo, static)
        options = vm.type_options()
        self.assertNotIn("", options)
        self.assertIn("普通", options)
        self.assertEqual(len(options), 18)

    def test_speciality_catalog_names_and_filter_ids(self) -> None:
        static = StaticData(Path(__file__).resolve().parents[1] / "data" / "static")
        self.assertEqual(static.speciality_name(101), "奇袭")
        self.assertEqual(static.speciality_name(402), "同乘")
        self.assertEqual(static.speciality_name(1001), "爱分享")
        self.assertEqual(static.speciality_name(99999), "特性 #99999")
        with self.repo._lock:
            self.repo._pets = {1: replace(_pet(1, name="合成同乘", level=1), speciality_id=402),
                               2: replace(_pet(2, name="合成未知", level=1), speciality_id=99999)}
        vm = PetViewModel(self.repo, static)
        payload = pets_payload(vm.view_with(PetFilters(speciality=402)), static)
        self.assertEqual([pet["gid"] for pet in payload["pets"]], [1])
        choices = {item["id"]: item["name"] for item in payload["options"]["specialities"]}
        self.assertEqual(choices[1001], "爱分享")  # 未在背包出现也可选择。
        self.assertEqual(choices[99999], "特性 #99999")

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        pets = (replace(_pet(1, name="A", level=60, base_conf=100), nature=1, talent_rank=2),
                replace(_pet(2, name="A2", level=10, base_conf=100), nature=1, talent_rank=3))
        self.context = _make_context(Path(self.tmp.name), pets)
        self.addCleanup(self.context.close)
        self.repo = self.context.pet_repository
        self.repo._account.observe(PlayerIdentity(101, "账号 A", 60))
        self.repo._cached_identity = self.repo.identity
        self.repo._backpack = Backpack({1: PetBox(1, (1, 2) + (0,) * 28)})
        self.repo._locations = self.repo._backpack.locations()
        self.repo._version = 10
        static = StaticData(None)
        static._species = {
            "100": SpeciesInfo("A 物种", ("火",), (1,), {}, 1, 1, 0, (), egg_groups=("动物组",)),
            "200": SpeciesInfo("B 物种", ("水",), (2,), {}, 1, 1, 0, (), egg_groups=("海洋组",)),
        }
        static._natures = {1: NatureInfo("性格 A", None, None), 2: NatureInfo("性格 B", None, None)}
        self.context.static_data = static
        self.context.pet_vm = PetViewModel(self.repo, static)
        self.server = LocalServer(self.context, port=0)

    def switch_to_b(self) -> None:
        with self.repo._lock:
            self.repo._account.observe(PlayerIdentity(202, "账号 B", 20))
            self.repo._cached_identity = self.repo._account.identity
            self.repo._pets = {9: replace(_pet(9, name="B", level=20, base_conf=200), nature=2, talent_rank=8)}
            self.repo._backpack = Backpack({2: PetBox(2, (9,) + (0,) * 29)})
            self.repo._locations = self.repo._backpack.locations()
            self.repo._version = 11

    def test_pets_payload_never_reloads_live_options(self) -> None:
        view = self.context.pet_vm.view_with(PetFilters(search="a"))
        self.switch_to_b()
        with patch.object(self.repo, "snapshot", side_effect=AssertionError("禁止重新读 live pets")):
            payload = pets_payload(view, self.context.static_data)
            overview = overview_payload(view, self.context.static_data)
        self.assertEqual((payload["uid"], payload["version"], payload["total"]), (101, 10, 2))
        self.assertEqual([pet["gid"] for pet in payload["pets"]], [1, 2])
        self.assertEqual(payload["pets"][0]["location"]["box_id"], 1)
        self.assertEqual(payload["backpack"]["boxes"][0]["slots"][0]["state"], "matched")
        # 目录选项跨账号共享；常用性格排序和宠物条目仍来自账号A的单次快照。
        self.assertEqual(payload["options"]["natures"], [{"id": 1, "name": "性格 A"}, {"id": 2, "name": "性格 B"}])
        self.assertEqual(payload["options"]["types"], ["水", "火"])
        self.assertEqual(payload["options"]["egg_groups"], ["动物组", "海洋组"])
        self.assertEqual(payload["options"]["talent_max"], 3)
        self.assertEqual(payload["options"]["measurement_limits"], view.measurement_limits())
        self.assertEqual((overview["uid"], overview["version"], overview["stats"]["total"]), (101, 10, 2))

    def test_bootstrap_reuses_one_snapshot_after_switch(self) -> None:
        original = self.repo.consistent_snapshot

        def snapshot_then_switch():
            snapshot = original()
            self.switch_to_b()
            return snapshot

        self.context.pet_vm.set_search("does not match")
        with patch.object(self.repo, "consistent_snapshot", side_effect=snapshot_then_switch) as take:
            response = asyncio.run(self.server._api_bootstrap(None))
        payload = json.loads(response.text)
        self.assertEqual(take.call_count, 1)
        self.assertEqual([pet["gid"] for pet in payload["pets"]["pets"]], [1, 2])
        self.assertEqual(payload["overview"]["uid"], 101)
        self.assertEqual(payload["overview"]["version"], 10)
        self.assertEqual(payload["overview"]["identity"]["uid"], 101)
        self.assertEqual(payload["overview"]["cached_identity"]["uid"], 101)
        self.assertEqual(payload["overview"]["stats"]["maxed"], 1)
        self.assertEqual(payload["overview"]["stats"]["max_level"], 60)
        self.assertEqual(payload["overview"]["stats"]["types"][0]["name"], "火")
        state = payload["state"]
        self.assertEqual((state["uid"], state["pets_version"], state["pets_total"]), (101, 10, 2))
        self.assertEqual(state["stats"], payload["overview"]["stats"])
        self.assertEqual(state["identity"], payload["overview"]["identity"])

    def test_state_uses_one_snapshot_for_ws_and_rest(self) -> None:
        original = self.repo.consistent_snapshot

        def snapshot_then_switch():
            snapshot = original()
            self.switch_to_b()
            return snapshot

        with patch.object(self.repo, "consistent_snapshot", side_effect=snapshot_then_switch) as take:
            state = self.server._state_payload()
        self.assertEqual(take.call_count, 1)
        self.assertEqual((state["uid"], state["pets_version"], state["pets_total"]), (101, 10, 2))
        self.assertEqual(state["identity"]["uid"], 101)
        self.assertEqual(state["cached_identity"]["uid"], 101)
        self.assertEqual(state["stats"]["max_level"], 60)
        next_state = self.server._state_payload()
        self.assertEqual((next_state["uid"], next_state["pets_version"], next_state["pets_total"]), (202, 11, 1))

    def test_mutable_vm_payload_is_snapshotted_once(self) -> None:
        original = self.repo.consistent_snapshot

        def snapshot_then_switch():
            snapshot = original()
            self.switch_to_b()
            return snapshot

        with patch.object(self.repo, "consistent_snapshot", side_effect=snapshot_then_switch) as take:
            payload = pets_payload(self.context.pet_vm, self.context.static_data)
        self.assertEqual(take.call_count, 1)
        self.assertEqual((payload["uid"], payload["version"], payload["total"]), (101, 10, 2))

    def test_offline_uid_is_data_owner_without_live_identity(self) -> None:
        from spritelens.services.account_tracker import AccountTracker
        self.repo._account = AccountTracker()
        self.repo._account.note_loaded(101)
        self.repo._cached_identity = PlayerIdentity(101, "离线 A", 60)
        payload = asyncio.run(self.server._api_bootstrap(None))
        data = json.loads(payload.text)
        self.assertEqual(data["pets"]["uid"], 101)
        self.assertEqual(data["overview"]["uid"], 101)
        self.assertEqual(data["state"]["uid"], 101)
        self.assertIsNone(data["overview"]["identity"])
        self.assertEqual(data["overview"]["cached_identity"]["uid"], 101)
        self.repo._cached_identity = None
        data = json.loads(asyncio.run(self.server._api_bootstrap(None)).text)
        self.assertEqual(data["pets"]["uid"], 101)
        self.assertIsNone(data["overview"]["cached_identity"])

    def test_snapshot_reuse_keeps_request_filters_independent(self) -> None:
        vm = self.context.pet_vm
        one = vm.view_with(PetFilters(search="a2"))
        all_pets = vm.view_with(PetFilters())
        self.switch_to_b()
        self.assertEqual([pet.gid for pet in one.filtered_pets()], [2])
        self.assertEqual([pet.gid for pet in all_pets.filtered_pets()], [1, 2])
        self.assertEqual(vm.filters.search, "")
