"""离线 Wiki 的身份匹配、学习来源与按需载荷契约。只使用合成数据。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from spritelens.domain.static_data import StaticData
from spritelens.domain.wiki_reference import WikiReference
from spritelens.web.payloads_catalog import handbook_payload
from tools.import_wiki_reference import LuaTableReader


class WikiReferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        directory = Path(self.tmp.name)
        reference = {"retrieved_at": "2026-10-19T00:00:00Z", "sources": [],
            "catalog": {"100": {"name": "测试兽", "title": "测试兽", "source_url": "https://example.invalid/test",
                "feature_skill_id": "feature", "learnset_id": "learnset", "evolution_id": "evolution",
                "class": "合成类别", "can_double_ride": True, "ecology": {"areas": ["合成地点"]}}},
            "skills": {"feature": {"name": "合成特性", "desc": "合成描述", "category": "特性"},
                "skill": {"name": "合成技能", "desc": "合成效果", "category": "攻击", "energy": 0, "power": 35}},
            "learnsets": {"learnset": {"native_skills": [{"skill": "skill", "level": 1}],
                "skill_stones": ["skill"], "blood_skills": [{"skill": "skill", "blood": "草", "level": 15}]}},
            "evolutions": {}}
        (directory / "wiki_reference.json").write_text(json.dumps(reference), encoding="utf-8")
        (directory / "species.json").write_text(json.dumps({"100": {"name": "测试兽", "handbook_no": "001"}}), encoding="utf-8")
        for name in ("skills", "natures", "types", "type_chart"):
            (directory / f"{name}.json").write_text("{}", encoding="utf-8")
        self.static = StaticData(directory)

    def test_id_and_name_must_match(self) -> None:
        wiki = self.static.wiki_reference
        self.assertIsNotNone(wiki.species(100, "测试兽"))
        self.assertIsNone(wiki.species(100, "另一形态"))
        self.assertIsNone(wiki.species(200, "测试兽"))
        self.assertTrue(wiki.can_double_ride(100, "测试兽"))
        self.assertIsNone(wiki.can_double_ride(100, "另一形态"))

    def test_learning_sources_and_zero_energy(self) -> None:
        entry = self.static.wiki_reference.species(100, "测试兽")
        self.assertEqual([row["source"] for row in entry["skills"]], ["自学", "技能石", "血脉"])
        self.assertEqual(entry["skills"][0]["energy"], 0)
        self.assertIsNone(entry["skills"][1]["level"])
        self.assertEqual(entry["skills"][2]["blood"], "草")

    def test_supplement_is_only_in_detail_response(self) -> None:
        self.assertIsNone(handbook_payload(self.static)["species"][0]["wiki"])
        entry = handbook_payload(self.static, search="100", details=True)["species"][0]
        self.assertEqual(entry["wiki"]["feature"]["name"], "合成特性")
        self.assertEqual(entry["wiki"]["areas"], ["合成地点"])
        self.assertIsNone(WikiReference(None).species(100, "测试兽"))

    def test_import_accepts_data_and_rejects_lua_code(self) -> None:
        self.assertEqual(LuaTableReader('return {test={name="合成",energy=0,values={1,2},enabled=true}}').read(),
                         {"test": {"name": "合成", "energy": 0, "values": [1, 2], "enabled": True}})
        with self.assertRaises(ValueError):
            LuaTableReader('return {test=os.execute("command")}').read()
