"""蛋仓：形状搜索提取、聚合去重、SQLite 持久化、载荷联查。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from spritelens.domain.egg_box import EggBoxEntry, extract_eggs
from spritelens.domain.eggs import EggCatalog
from spritelens.repositories.database import Database
from spritelens.repositories.egg_store import EggStore
from spritelens.services.egg_repository import EggBoxRepository
from spritelens.services.monitor_service import PacketEvent
from spritelens.web.payloads import egg_box_payload, male_matrix_payload


def _field(no: int, raw: object, children: list[dict] | None = None) -> dict:
    node = {"no": no, "name": f"field_{no}", "type": "", "value": "", "raw": raw}
    if children is not None:
        node["children"] = children
    return node


def _egg_row(
    instance_id: int = 9001,
    item_conf_id: int = 3001001,
    quantity: int = 1,
    *,
    hatch_seconds: int = 43200,
    hatched_seconds: int = 0,
    bag_type: int = 8,
    with_detail: bool = True,
) -> dict:
    detail = (
        _field(
            15,
            None,
            [
                _field(1, 3001),
                _field(2, 25),
                _field(3, 1300),
                _field(6, hatch_seconds),
                _field(4, hatched_seconds),
                _field(10, 6),
            ],
        )
        if with_detail
        else None
    )
    rows = [
        _field(1, instance_id),
        _field(2, item_conf_id),
        _field(3, quantity),
        _field(4, 1791661300),
        _field(14, bag_type),
    ]
    if detail is not None:
        rows.append(detail)
    return _field(1, None, rows)


def _event(*rows: dict, opcode: int = 0x1344) -> PacketEvent:
    return PacketEvent(
        ts=0.0,
        session_id="s1",
        direction="s2c",
        opcode=opcode,
        opcode_name="test",
        payload_len=0,
        decoded=[_field(4, None, list(rows))],
    )


class ExtractEggsTests(unittest.TestCase):
    def test_extract_valid_row(self) -> None:
        eggs = extract_eggs(_event(_egg_row()))
        self.assertEqual(len(eggs), 1)
        egg = eggs[0]
        self.assertEqual(egg.instance_id, 9001)
        self.assertEqual(egg.egg_conf_id, 3001001)
        self.assertEqual(egg.pet_conf_id, 3001)
        self.assertEqual(egg.hatch_seconds, 43200)
        self.assertEqual(egg.category, 6)
        self.assertFalse(egg.hatching)
        self.assertEqual(egg.hatch_progress, 0.0)

    def test_rejects_wrong_bag_type(self) -> None:
        self.assertEqual(extract_eggs(_event(_egg_row(bag_type=1))), [])

    def test_rejects_missing_detail(self) -> None:
        self.assertEqual(extract_eggs(_event(_egg_row(with_detail=False))), [])

    def test_hatching_progress(self) -> None:
        eggs = extract_eggs(_event(_egg_row(hatched_seconds=21600)))
        self.assertTrue(eggs[0].hatching)
        self.assertAlmostEqual(eggs[0].hatch_progress, 0.5, places=3)

    def test_no_events_without_tree(self) -> None:
        event = PacketEvent(0.0, "s", "c2s", 0x1344, "x", 0, [])
        self.assertEqual(extract_eggs(event), [])


class EggBoxRepositoryTests(unittest.TestCase):
    def test_merge_dedup_and_version(self) -> None:
        repo = EggBoxRepository()
        repo.handle_packet(_event(_egg_row(1), _egg_row(2)))
        repo.handle_packet(_event(_egg_row(2, 3002001), _egg_row(3)))
        snap = repo.snapshot()
        self.assertEqual([e.instance_id for e in snap], [1, 2, 3])
        self.assertEqual(repo.version(), 2)
        # instance 2 被第二帧覆盖为新 itemConfId
        self.assertEqual(snap[1].egg_conf_id, 3002001)

    def test_store_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "db.sqlite")
            try:
                store = EggStore(db)
                egg = EggBoxEntry(
                    instance_id=7, egg_conf_id=3001001, pet_conf_id=3001, quantity=1,
                    obtained_at=1791661300, bag_type=8, height_cm=25, weight_g=1300,
                    hatch_seconds=100, hatched_seconds=50, hatch_updated_at=0,
                    start_hatch_time=0, category=6, special_egg_conf_id=0,
                    appearance_type=0, extension_type=0,
                )
                self.assertEqual(store.put(101, [egg]), 1)
                uid, loaded = store.load_latest()
                self.assertEqual(uid, 101)
                self.assertEqual(len(loaded), 1)
                got = loaded[0]
                self.assertEqual(got.instance_id, 7)
                self.assertEqual(got.hatch_seconds, 100)
                self.assertTrue(got.hatching)
            finally:
                db.close()


class EggBoxPayloadTests(unittest.TestCase):
    def test_payload_joins_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            catalog_dir = Path(tmp)
            (catalog_dir / "eggs.json").write_text(
                """{"groups": {}, "eggs": [{
                    "egg_key": "喵喵#3001001", "egg_conf_id": 3001001, "egg_name": "喵喵蛋",
                    "name": "喵喵", "base_id": 3001, "egg_item_id": 107001,
                    "egg_type_name": "普通", "hatch_label": "12小时", "egg_group_names": []
                }], "egg_conf_index": {}}""",
                encoding="utf-8",
            )
            catalog = EggCatalog(catalog_dir)
            repo = EggBoxRepository()
            repo.handle_packet(_event(_egg_row(9)))
            payload = egg_box_payload(repo, catalog)
            self.assertEqual(payload["total"], 1)
            row = payload["eggs"][0]
            self.assertEqual(row["egg_name"], "喵喵蛋")
            self.assertEqual(row["icon_url"], "/static/egg-icons/107001.png")
            self.assertEqual(row["fallback_icon_url"], "/static/pets/3001.webp")
            self.assertEqual(payload["total_quantity"], 1)

    def test_payload_empty_when_no_repo(self) -> None:
        payload = egg_box_payload(None, None)
        self.assertEqual(payload["total"], 0)
        self.assertEqual(payload["version"], 0)


class MaleMatrixPayloadTests(unittest.TestCase):
    def _pet(self, gid, name, nature, gender, base_conf_id):
        from spritelens.domain.pets import Pet, PetAttribute
        return Pet(
            gid=gid, conf_id=2000000 + gid, name=name, level=40, exp=0,
            nature=nature, gender=gender, blood_id=1, talent_rank=3,
            is_first_catch=False, base_conf_id=base_conf_id,
            attributes=(PetAttribute(),) * 6, height=0, weight=0, voice=0, skills=(),
        )

    def test_matrix_cells(self) -> None:
        class Repo:
            def snapshot(self):
                return [
                    self._p1, self._p2, self._p3,
                ]
        repo = Repo()
        repo._p1 = self._pet(1, "喵喵A", 1, 1, 3001)   # 动物组/拟人组
        repo._p2 = self._pet(2, "喵喵B", 1, 2, 3001)   # 同性格雌性
        repo._p3 = self._pet(3, "火花", 2, 1, 3003)    # 另一性格，魔力组/巨灵组

        class Static:
            def species(self, base_id):
                info = {3001: ("喵喵A-cat", ["动物组", "拟人组"]), 3003: ("火花-cat", ["魔力组", "巨灵组"])}[base_id]
                from types import SimpleNamespace
                return SimpleNamespace(egg_groups=info[1])
            def nature_name(self, nid):
                return {1: "勤奋", 2: "固执"}[nid]
            def nature(self, nid):
                from types import SimpleNamespace
                return SimpleNamespace(positive_stat="atk", negative_stat="spa" if nid == 2 else None)

        payload = male_matrix_payload(repo, Static())
        # 每只宠物带 2 个蛋组 → 3 只 × 2 = 6 个格子计数
        self.assertEqual(payload["matched"], 6)
        self.assertIn("勤奋", {n["name"] for n in payload["natures"]})
        cell = payload["cells"]["勤奋|动物组"]
        self.assertEqual(len(cell), 2)  # 公母各一只（all 模式）
        self.assertEqual(cell[0]["gid"], 1)  # 同级按 gid 升序

    def test_gender_filter(self) -> None:
        class Repo:
            def snapshot(self):
                return [self._p1, self._p2]
        repo = Repo()
        repo._p1 = self._pet(1, "A", 1, 1, 3001)
        repo._p2 = self._pet(2, "B", 1, 2, 3001)

        class Static:
            def species(self, base_id):
                from types import SimpleNamespace
                return SimpleNamespace(egg_groups=["动物组"])
            def nature_name(self, nid):
                return "勤奋"
            def nature(self, nid):
                return None

        males = male_matrix_payload(repo, Static(), gender="male")
        self.assertEqual(males["matched"], 1)
        females = male_matrix_payload(repo, Static(), gender="female")
        self.assertEqual(females["matched"], 1)


if __name__ == "__main__":
    unittest.main()
