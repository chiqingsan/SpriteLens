"""产线关键规则：链计数、父母条件、精确量值与账号隔离。"""
from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from spritelens.domain.collection_lines import CollectionGoal, build_catalog
from spritelens.domain.eggs import EggCatalog
from spritelens.domain.identity import PlayerIdentity
from spritelens.domain.pets import Pet
from spritelens.domain.static_data import SpeciesInfo, StaticData
from spritelens.services.collection_lines_service import CollectionLinesService
from spritelens.services.pet_repository import PetRepository
from spritelens.view_models.collection_lines_vm import CollectionLinesViewModel
from spritelens.web.collection_lines import collection_payload


def catalogs() -> tuple[StaticData, EggCatalog]:
    static = StaticData(None)
    species = SpeciesInfo("种母", (), (), {}, 1, 1, 0, (), dex_no=1,
                          egg_groups=("动物",), height_range=(100, 200), weight_range=(1000, 2000),
                          chain_members=(1, 2))
    static._species = {"1": species, "2": replace(species, name="进化型", stage=2),
                       "3": replace(species, name="种公", chain_members=(3,))}
    from spritelens.domain.static_data import NatureInfo
    static._natures = {2: NatureInfo("固执", "atk", "spa"), 11: NatureInfo("聪明", "spa", "atk")}
    eggs = EggCatalog(None)
    eggs._by_base_id = {key: SimpleNamespace(egg_key=f"egg:{1 if key in (1, 2) else 3}") for key in (1, 2, 3)}
    return static, eggs


def pet(gid: int, gender: int = 2, base: int = 1, **changes) -> Pet:
    return replace(Pet(gid, gid, "测试", 30, 0, 2, gender, 0, 0, False,
                       base_conf_id=base, height=150, weight=2000, voice=100), **changes)


class CollectionRulesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.static, self.eggs = catalogs()
        self.repo = PetRepository()
        self.repo._account.observe(PlayerIdentity(101, "合成账号", 60))
        self.vm = CollectionLinesViewModel(CollectionLinesService(self.repo, self.static, self.eggs))

    def result(self, pets: tuple[Pet, ...], goal: CollectionGoal = CollectionGoal()) -> dict:
        self.repo._pets = {parent.gid: parent for parent in pets}
        return collection_payload(self.vm.snapshot(goal), goal, SimpleNamespace(static_data=self.static))

    def test_evolved_mothers_count_once_and_cross_species_male_can_pair(self) -> None:
        result = self.result((pet(2**63 + 1), pet(2, base=2), pet(3, 1, 3)))
        self.assertEqual(result["totals"]["eligible"], 2)
        self.assertEqual(result["totals"]["collected"], 1)
        line = result["lines"][0]
        self.assertEqual(len(line["mothers"]), 2)
        self.assertEqual(line["pairs"][0], {"mother_gid": str(2**63 + 1), "father_gids": ["3"]})

    def test_all_parent_conditions_apply_to_both_sides(self) -> None:
        mother, father = pet(1), pet(2, 1, 3)
        for bad in (replace(father, nature=11), replace(father, gender=2), replace(father, voice=-100),
                    replace(father, weight=1500), replace(father, is_trial_pet=True)):
            with self.subTest(bad=bad):
                self.assertEqual(self.result((mother, bad))["lines"][0]["status"], "missingMale")
        self.static._species["3"] = replace(self.static._species["3"], egg_groups=("飞行",))
        self.assertEqual(self.result((mother, father))["lines"][0]["status"], "missingMale")

    def test_exact_sound_and_weight_are_not_rounded(self) -> None:
        for weight in (1999, 2001):
            result = self.result((pet(1, weight=weight), pet(2, 1, 3)), CollectionGoal(full_weight=True))
            self.assertEqual(result["totals"]["complete"], 0)
        self.assertEqual(self.result((pet(1, voice=99), pet(2, 1, 3)), CollectionGoal(sound=100))["totals"]["complete"], 0)

    def test_four_goals_require_size_and_voice_marks(self) -> None:
        for key, weight, voice in (("big-soft", 2000, 100), ("big-loud", 2000, -100),
                                   ("small-soft", 1000, 100), ("small-loud", 1000, -100)):
            result = self.result((pet(1, weight=weight, voice=voice), pet(2, 1, 3, weight=weight, voice=voice)), CollectionGoal(key))
            self.assertEqual(result["totals"]["collected"], 1)
        result = self.result((pet(1, height=200, weight=1500), pet(2, 1, 3)))
        self.assertEqual(result["totals"]["collected"], 0)
        self.assertEqual(self.result((pet(1, weight=2100), pet(2, 1, 3)))["totals"]["collected"], 0)

    def test_full_height_weight_89_percent_is_not_double_marked(self) -> None:
        from spritelens.domain.collection_lines import breeder
        single = pet(1, height=200, weight=1890, worn_medal_id=1026)
        self.assertIsNone(breeder(single, self.static, CollectionGoal()))
        self.assertIsNone(breeder(replace(single, height=100), self.static, CollectionGoal('small-soft')))
        result = self.result((pet(2), replace(single, gid=3, gender=1, base_conf_id=3)))
        self.assertEqual(result['lines'][0]['status'], 'missingMale')
        self.assertEqual(result['fathers'], [])

    def test_all_known_natures_and_structured_mark_sources(self) -> None:
        from spritelens.domain.static_data import NatureInfo
        self.static._natures[1] = NatureInfo('大胆', 'atk', 'def')
        result = self.result((pet(1, nature=1), pet(2, 1, 3, nature=1)))
        self.assertEqual(result['totals']['collected'], 1)
        self.assertIn('大胆', result['natures'])
        mother = result['lines'][0]['mothers'][0]
        self.assertEqual(mother['marks'], [{'name': '大块头', 'source': 'reference'}, {'name': '婉转声', 'source': 'reference'}])
        self.assertEqual(mother['weight_ratio'], 1)

    def test_ignore_male_changes_progress_without_relabelling_missing_male(self) -> None:
        result = self.result((pet(1),), CollectionGoal(ignore_missing_male=True))
        self.assertEqual(result["totals"]["complete"], 1)
        self.assertEqual(result["lines"][0]["status"], "missingMale")

    def test_colorful_requires_explicit_mutation_bit_on_both_parents(self) -> None:
        for mutation in (0, 1, 8):
            result = self.result((pet(1, mutation_type=8), pet(2, 1, 3, mutation_type=mutation)), CollectionGoal(colorful=True))
            self.assertEqual(result["totals"]["complete"], int(mutation == 8))

    def test_conflicting_catalog_is_unknown_and_excluded_from_denominator(self) -> None:
        self.static._species["2"] = replace(self.static._species["2"], chain_members=(2, 3))
        chains = build_catalog(self.static, self.eggs)
        self.assertTrue(all(chain.gaps for chain in chains))
        vm = CollectionLinesViewModel(CollectionLinesService(self.repo, self.static, self.eggs))
        result = vm.snapshot(CollectionGoal())
        self.assertEqual(result.totals["eligible"], 0)
        self.assertEqual(result.totals["unknown"], len(chains))

    def test_single_snapshot_does_not_reuse_previous_account_candidates(self) -> None:
        self.result((pet(1), pet(2, 1, 3)))
        self.repo._account.observe(PlayerIdentity(202, "另一账号", 60))
        self.repo._pets.clear()
        result = collection_payload(self.vm.snapshot(CollectionGoal()), CollectionGoal(), SimpleNamespace(static_data=self.static))
        self.assertEqual(result["uid"], 202)
        self.assertEqual(result["totals"]["complete"], 0)
        self.assertFalse(result["fathers"])


class CollectionRouteTest(unittest.TestCase):
    def test_authenticated_route_and_invalid_boundary_inputs(self) -> None:
        from tests.test_web_server import _make_context, _http_get
        from spritelens.web.server import LocalServer
        with TemporaryDirectory() as directory:
            context = _make_context(Path(directory))
            server = LocalServer(context)
            server.start()
            url = f"http://127.0.0.1:{server.port}/api/collection-lines"
            try:
                status, _ = _http_get(url)
                self.assertEqual(status, 401)
                status, payload = _http_get(url, server.token)
                self.assertEqual(status, 200)
                self.assertEqual(payload["totals"]["eligible"], 0)
                for query in ('goal=bad', 'sound=99', 'colorful=maybe'):
                    status, _ = _http_get(url + '?' + query, server.token)
                    self.assertEqual(status, 400)
            finally:
                server.stop()
                context.close()
