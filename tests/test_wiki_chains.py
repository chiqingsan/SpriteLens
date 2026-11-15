"""按 Wiki 进化表补链的解析与写入口径。只使用合成数据。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.sync_wiki_chains import ChainIndex, load, sync, write


def _species(name: str, **extra: object) -> dict:
    return {"name": name, **extra}


class WikiChainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.static = Path(self.tmp.name)

    def _dump(self, species: dict, eggs: dict, wiki: dict) -> None:
        write(self.static / "species.json", species)
        write(self.static / "eggs.json", eggs)
        write(self.static / "wiki_reference.json", wiki)

    def _wiki(self, evolution_id: str, branches: list[dict], catalog: dict) -> dict:
        return {"catalog": catalog, "evolutions": {evolution_id: branches}}

    def test_sync_fills_missing_chain_and_keeps_format(self) -> None:
        species = {"1": _species("甲"), "2": _species("乙"), "3": _species("丙")}
        eggs = {"eggs": []}
        catalog = {key: {"evolution_id": "e1"} for key in species}
        wiki = self._wiki("e1", [{"chain": [{"name": "甲"}, {"name": "乙"}, {"name": "丙"}],
                                  "lord_branches": []}], catalog)
        self._dump(species, eggs, wiki)

        self.assertEqual(sync(self.static, check=True), 1)
        self.assertEqual(sync(self.static, check=False), 0)
        filled = load(self.static / "species.json")
        self.assertEqual(filled["1"]["chain_members"], [1, 2, 3])
        self.assertEqual(filled["2"]["chain_members"], [1, 2, 3])
        self.assertEqual(filled["2"]["evolutions"], [3])
        self.assertEqual(filled["3"]["chain_members"], [1, 2, 3])
        self.assertEqual(filled["3"]["evolutions"], [])
        text = (self.static / "species.json").read_text(encoding="utf-8")
        self.assertTrue(text.endswith("\n"))
        self.assertNotIn("\r", text)
        self.assertEqual(sync(self.static, check=True), 0)

    def test_lord_branch_members_join_the_line(self) -> None:
        species = {"1": _species("甲"), "2": _species("乙"), "9": _species("首领")}
        catalog = {key: {"evolution_id": "e1"} for key in species}
        wiki = self._wiki("e1", [{"chain": [{"name": "甲"}, {"name": "乙"}],
                                  "lord_branches": [{"name": "首领", "stage": 4, "form": "首领形态"}]}], catalog)
        self._dump(species, {"eggs": []}, wiki)
        index = ChainIndex(load(self.static / "species.json"), load(self.static / "wiki_reference.json"))

        self.assertEqual(index.chain_of("9"), ([1, 2, 9], []))
        self.assertEqual(index.chain_of("2"), ([1, 2, 9], [9]))
        self.assertEqual(index.chain_of("1"), ([1, 2, 9], [2]))

    def test_name_ambiguity_uses_evolution_id(self) -> None:
        species = {"10": _species("同名"), "20": _species("同名"), "11": _species("后阶")}
        catalog = {"10": {"evolution_id": "e1"}, "11": {"evolution_id": "e1"},
                   "20": {"evolution_id": "e2"}}
        wiki = self._wiki("e1", [{"chain": [{"name": "同名"}, {"name": "后阶"}], "lord_branches": []}], catalog)
        index = ChainIndex(species, wiki)

        self.assertEqual(index.chain_of("10"), ([10, 11], [11]))
        self.assertIsNone(index.chain_of("20"))

    def test_unresolved_member_skips_the_branch(self) -> None:
        species = {"1": _species("甲")}
        catalog = {"1": {"evolution_id": "e1"}}
        wiki = self._wiki("e1", [{"chain": [{"name": "甲"}, {"name": "未收录"}], "lord_branches": []}], catalog)
        index = ChainIndex(species, wiki)

        self.assertIsNone(index.chain_of("1"))
        self.assertEqual(index.skipped, ["1"])
        self.assertIn("未收录", index.unresolved)

    def test_existing_value_extends_to_wiki_superset(self) -> None:
        species = {"1": _species("甲", chain_members=[1, 2], evolutions=[2]),
                   "2": _species("乙", chain_members=[1, 2]), "3": _species("丙")}
        catalog = {key: {"evolution_id": "e1"} for key in species}
        wiki = self._wiki("e1", [{"chain": [{"name": "甲"}, {"name": "乙"}, {"name": "丙"}], "lord_branches": []}], catalog)
        self._dump(species, {"eggs": []}, wiki)

        self.assertEqual(sync(self.static, check=False), 0)
        after = load(self.static / "species.json")
        self.assertEqual(after["1"]["chain_members"], [1, 2, 3])
        self.assertEqual(after["1"]["evolutions"], [2])
        self.assertEqual(after["2"]["chain_members"], [1, 2, 3])
        self.assertEqual(after["2"]["evolutions"], [3])

    def test_local_only_member_is_kept_and_reported(self) -> None:
        species = {"1": _species("甲", chain_members=[1, 2, 9]),
                   "2": _species("乙", chain_members=[1, 2, 9])}
        catalog = {key: {"evolution_id": "e1"} for key in species}
        wiki = self._wiki("e1", [{"chain": [{"name": "甲"}, {"name": "乙"}], "lord_branches": []}], catalog)
        self._dump(species, {"eggs": []}, wiki)
        before = (self.static / "species.json").read_text(encoding="utf-8")

        self.assertEqual(sync(self.static, check=False), 0)
        self.assertEqual(load(self.static / "species.json")["1"]["chain_members"], [1, 2, 9])
        self.assertEqual(before, (self.static / "species.json").read_text(encoding="utf-8"))

    def test_egg_chain_filled_from_species_line(self) -> None:
        species = {"1": _species("甲"), "2": _species("乙")}
        catalog = {key: {"evolution_id": "e1"} for key in species}
        wiki = self._wiki("e1", [{"chain": [{"name": "甲"}, {"name": "乙"}], "lord_branches": []}], catalog)
        self._dump(species, {"eggs": [{"egg_key": "egg-1", "egg_name": "甲蛋", "base_id": 1}]}, wiki)

        self.assertEqual(sync(self.static, check=False), 0)
        eggs = load(self.static / "eggs.json")
        self.assertEqual(eggs["eggs"][0]["chain_members"], [1, 2])


if __name__ == "__main__":
    unittest.main()
