"""筛选配对：候选正确性、未知值、分页与账号边界。"""
from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from spritelens.domain.breeder_library import BreederFilters
from spritelens.domain.identity import PlayerIdentity
from spritelens.domain.pets import Pet
from spritelens.domain.static_data import NatureInfo, SpeciesInfo, StaticData
from spritelens.services.pet_repository import PetRepository
from spritelens.view_models.breeder_library_vm import BreederLibraryViewModel
from spritelens.web.breeder_library import breeder_payload, parse_filters


class BreederLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.static = StaticData(None)
        species = SpeciesInfo("合成精灵", (), (), {}, 1, 1, 0, (), dex_no=1,
                              egg_groups=("动物", "精灵"), height_range=(100, 200),
                              weight_range=(1000, 2000), chain_members=(1, 2))
        self.static._species = {"1": species, "2": replace(species, stage=2),
                                "3": replace(species, dex_no=3, chain_members=(3,), egg_groups=("动物",)),
                                "4": replace(species, egg_groups=("未发现",)),
                                "5": replace(species, egg_groups=("龙",))}
        self.static._natures = {2: NatureInfo("固执", "atk", "spa"), 11: NatureInfo("聪明", "spa", "atk")}
        self.repo = PetRepository()
        self.repo._account.observe(PlayerIdentity(101, "合成账号", 60))
        self.vm = BreederLibraryViewModel(self.repo, self.static)

    def pet(self, gid: int, gender: int = 1, base: int = 1, **changes) -> Pet:
        return replace(Pet(gid, base, "合成", 30, 0, 2, gender, 0, 0, False,
                           base_conf_id=base, height=150, weight=2000, voice=100), **changes)

    def result(self, pets: tuple[Pet, ...], **filters):
        self.repo._pets = {pet.gid: pet for pet in pets}
        return self.vm.snapshot(BreederFilters(**filters))

    def test_complete_deduplicated_pools_and_bounded_pagination(self) -> None:
        pets = tuple(self.pet(i) for i in range(1, 60))
        view = self.result(pets, male_page=3)
        self.assertEqual(view.male_total, 59)
        self.assertEqual(len(view.males), 11)
        self.assertEqual(len({row.pet.gid for row in view.males}), 11)
        self.assertEqual(self.result(pets, male_page=99).male_page, 3)

    def test_both_directions_share_groups_and_nature_without_same_species_requirement(self) -> None:
        pets = (self.pet(1), self.pet(2, 2, 3), self.pet(3, 2, 3, nature=11), self.pet(4, 2, 5), self.pet(5, 2, 4), self.pet(6, 0))
        view = self.result(pets, male=1, anchor=1)
        self.assertEqual([row.pet.gid for row in view.females], [2])
        self.assertEqual([row.pet.gid for row in self.result(pets, male=1, anchor=1, same_nature=False).females], [2, 3])
        view = self.result(pets, female=2, anchor=2)
        self.assertEqual([row.pet.gid for row in view.males], [1])
        self.assertNotIn(5, [row.pet.gid for row in view.females])

    def test_same_chain_alternatives_and_incompatible_selection_reconciliation(self) -> None:
        pets = (self.pet(1), self.pet(2, base=2), self.pet(3, base=3), self.pet(4, 2, 5))
        view = self.result(pets, male=1, female=4, anchor=1)
        self.assertEqual([row.pet.gid for row in view.males], [1, 2])
        self.assertIsNone(view.selected_female)
        self.assertTrue(view.selection_changed)
        self.assertIsNone(view.prediction)

    def test_filters_apply_to_both_sides_and_do_not_drop_selected_anchor(self) -> None:
        pets = (self.pet(1), self.pet(2, 2, 3), self.pet(3, voice=0), self.pet(4, height=200, weight=1890))
        view = self.result(pets, marks=frozenset(("双奖牌",)), groups=frozenset(("动物",)))
        self.assertEqual([row.pet.gid for row in view.males], [1])
        self.assertEqual([row.pet.gid for row in view.females], [2])
        view = self.result(pets, male=1, anchor=1, search="不存在")
        self.assertEqual(view.selected_male.pet.gid, 1)
        self.assertEqual(view.males, ())
        self.assertEqual(self.result(pets, height_min=.9).male_total, 1)

    def test_unknown_voice_and_out_of_range_body_are_not_fabricated(self) -> None:
        pets = (self.pet(1, voice=0, height=999), self.pet(2, 2, voice=-99))
        view = self.result(pets, male=1, female=2, anchor=1)
        self.assertIsNone(view.prediction["voice"])
        self.assertIsNone(view.prediction["height_ratio"])
        self.assertIsNone(self.result(pets, male=1, female=2, anchor=1).prediction["voice"])
        self.assertEqual(self.result(pets, height_max=1).male_total, 0)

    def test_unknown_natures_do_not_match_and_large_ids_remain_strings(self) -> None:
        pets = (self.pet(2**63 + 1, nature=999), self.pet(2, 2, nature=999))
        self.assertEqual(self.result(pets, male=pets[0].gid, anchor=1).female_total, 0)
        view = self.result(pets, male=pets[0].gid, female=2, same_nature=False)
        payload = breeder_payload(view, SimpleNamespace(egg_catalog=None))
        self.assertEqual(payload["selected_male"]["gid"], str(2**63 + 1))
        self.assertEqual(payload["prediction"]["unknown_percent"], 60)

    def test_current_account_snapshot_does_not_retain_previous_selection(self) -> None:
        self.result((self.pet(1), self.pet(2, 2)), male=1, female=2)
        self.repo._account.observe(PlayerIdentity(202, "另一账号", 60))
        view = self.result((), male=1, female=2)
        self.assertEqual(view.inventory.uid, 202)
        self.assertIsNone(view.prediction)
        self.assertIsNone(view.selected_male)

    def test_invalid_network_inputs_fail_explicitly(self) -> None:
        for query in ({"voice_min": "NaN"}, {"height_max": "2"}, {"weight_min": ".8", "weight_max": ".2"},
                      {"marks": "虚构奖牌"}, {"male_page": "0"}, {"male": "oops"}, {"anchor": "3"}, {"same_nature": "yes"}):
            with self.subTest(query=query), self.assertRaises(ValueError):
                parse_filters(query)

    def test_route_requires_token_and_rejects_invalid_filters(self) -> None:
        from tests.test_web_server import _make_context, _http_get
        from spritelens.web.server import LocalServer
        with TemporaryDirectory() as directory:
            context = _make_context(Path(directory))
            server = LocalServer(context)
            server.start()
            url = f"http://127.0.0.1:{server.port}/api/breeder-library"
            try:
                self.assertEqual(_http_get(url)[0], 401)
                status, payload = _http_get(url, server.token)
                self.assertEqual(status, 200)
                self.assertEqual(payload["male_total"], 0)
                self.assertEqual(_http_get(url + '?voice_min=NaN', server.token)[0], 400)
            finally:
                server.stop()
                context.close()


if __name__ == "__main__":
    unittest.main()
