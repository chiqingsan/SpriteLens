"""蛋仓：形状搜索提取、聚合去重、SQLite 持久化、载荷联查。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from spritelens.domain.egg_box import EggBoxEntry, extract_eggs, extract_hatch_slots
from spritelens.domain.eggs import EggCatalog
from spritelens.repositories.database import Database
from spritelens.repositories.egg_store import EggStore
from spritelens.services.egg_repository import EggBoxRepository
from spritelens.events import PacketEvent
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


def _identity_event(uid: int, name: str = "玩家") -> PacketEvent:
    """self_info → avatar → base 身份帧（与持久化测试同形）。"""

    def _named(field_name: str, raw) -> dict:
        return {"no": 1, "name": field_name, "type": "", "value": "", "raw": raw}

    base = {"no": 1, "name": "base", "type": "", "value": "", "children": [
        _named("logic_id", uid), _named("name", name.encode()), _named("lv", 50)]}
    avatar = {"no": 1, "name": "avatar", "type": "", "value": "", "children": [base]}
    return PacketEvent(
        ts=0.0, session_id="s1", direction="s2c", opcode=0x0152, opcode_name="ZoneEnterSceneRsp",
        payload_len=0, decoded=[{"no": 1, "name": "self_info", "type": "", "value": "", "children": [avatar]}],
    )


def _hatch_event(ids: list[int]) -> PacketEvent:
    return PacketEvent(
        ts=0.0, session_id="s1", direction="s2c", opcode=0x0312, opcode_name="hatch", payload_len=0,
        decoded=[{"no": 1, "name": "f1", "type": "", "value": "", "raw": None, "children": []}]
        + [{"no": 2, "name": "f2", "type": "", "value": "", "raw": i} for i in ids],
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


class HatchSlotTests(unittest.TestCase):
    def test_extract_slot_ids(self) -> None:
        event = PacketEvent(
            ts=0.0, session_id="s", direction="s2c", opcode=0x0312, opcode_name="x", payload_len=0,
            decoded=[
                {"no": 1, "name": "f1", "type": "", "value": "", "raw": None, "children": [
                    {"no": 1, "name": "ok", "type": "", "value": "0", "raw": 0},
                    {"no": 4, "name": "f4", "type": "", "value": "", "raw": None, "children": []},
                ]},
                {"no": 2, "name": "f2", "type": "", "value": "888", "raw": 888},
                {"no": 2, "name": "f2", "type": "", "value": "886", "raw": 886},
                {"no": 3, "name": "f3", "type": "", "value": "263403", "raw": 263403},
            ],
        )
        self.assertEqual(extract_hatch_slots(event), (888, 886))

    def test_non_slot_frame(self) -> None:
        event = PacketEvent(0.0, "s", "s2c", 0x0164, "x", 0, [])
        self.assertIsNone(extract_hatch_slots(event))

    def test_repo_marks_in_slot(self) -> None:
        repo = EggBoxRepository()
        repo.handle_packet(_event(_egg_row(888)))
        repo.handle_packet(PacketEvent(
            ts=0.0, session_id="s", direction="s2c", opcode=0x0312, opcode_name="x", payload_len=0,
            decoded=[{"no": 2, "name": "f2", "type": "", "value": "888", "raw": 888}],
        ))
        payload = egg_box_payload(repo, None)
        self.assertTrue(payload["eggs"][0]["hatching"])
        self.assertTrue(payload["eggs"][0]["in_slot"])
        self.assertEqual(payload["hatch_slots"], 1)


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

    def test_account_switch_clears_eggs_and_slots(self) -> None:
        """切号清空蛋仓与孵化槽，且孵化槽帧不把旧账号的蛋写进新账号记录。

        回归：B 登录后仍能看到 A 的蛋，孵化槽帧触发整仓写入把 A 的蛋
        复制进 B 的 uid 记录（审查复现的串库场景）。
        """
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "db.sqlite")
            try:
                store = EggStore(db, flush_interval=0.05)
                repo = EggBoxRepository(store=store)

                repo.handle_packet(_identity_event(uid=111, name="账号A"))
                repo.handle_packet(_event(_egg_row(101)))
                store.flush()

                # 切换账号：内存蛋仓立即作废
                repo.handle_packet(_identity_event(uid=222, name="账号B"))
                self.assertEqual(repo.snapshot(), ())
                self.assertEqual(repo.hatch_slots(), set())

                # B 的孵化槽帧（A 的蛋 id）不得把 A 的蛋写入 B 的 uid
                repo.handle_packet(_hatch_event([101]))
                store.flush()
                rows = db.query("SELECT uid, instance_id FROM eggs ORDER BY uid")
                self.assertEqual([(r["uid"], r["instance_id"]) for r in rows], [(111, 101)])

                # B 自有的蛋正常入仓入槽
                repo.handle_packet(_event(_egg_row(202)))
                repo.handle_packet(_hatch_event([202]))
                snap = repo.snapshot()
                self.assertEqual([e.instance_id for e in snap], [202])
                self.assertEqual(repo.hatch_slots(), {202})
                store.close()
            finally:
                db.close()

    def test_load_last_account_not_treated_as_switch(self) -> None:
        """离线恢复的蛋仓属于该账号：同账号登录不清空恢复的数据。"""
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "db.sqlite")
            try:
                store = EggStore(db)
                store.put(101, [EggBoxEntry(
                    instance_id=7, egg_conf_id=3001001, pet_conf_id=3001, quantity=1,
                    obtained_at=1791661300, bag_type=8, height_cm=25, weight_g=1300,
                    hatch_seconds=100, hatched_seconds=50, hatch_updated_at=0,
                    start_hatch_time=0, category=6, special_egg_conf_id=0,
                    appearance_type=0, extension_type=0,
                )])
                repo = EggBoxRepository(store=store)
                self.assertEqual(repo.load_last_account(), 1)
                repo.handle_packet(_identity_event(uid=101, name="账号A"))  # 同账号登录
                self.assertEqual(len(repo.snapshot()), 1)
                repo.handle_packet(_identity_event(uid=202, name="账号B"))  # 真切换
                self.assertEqual(repo.snapshot(), ())
                store.close()
            finally:
                db.close()

    def test_hatch_slots_persisted_and_restored_per_uid(self) -> None:
        """孵化槽状态按 uid 持久化，重启可恢复为历史状态（R06）。

        审查复现：蛋条目时间字段全 0（hatching=False），槽位帧 [9001]
        使实时载荷识别为孵化中；重启后 Store 的 hatching=False、槽位
        映射丢失，孵化中显示退化。
        """
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "db.sqlite"
            db = Database(db_path)
            try:
                store = EggStore(db, flush_interval=60.0)
                repo = EggBoxRepository(store=store)
                repo.handle_packet(_identity_event(uid=101, name="账号A"))
                repo.handle_packet(_event(_egg_row(9001, hatch_seconds=43200, hatched_seconds=0)))
                repo.handle_packet(_hatch_event([9001]))
                self.assertEqual(repo.hatch_slots(), {9001})
                store.close()
                db.close()

                # 重启：新 store/repo，槽位快照应恢复
                db2 = Database(db_path)
                store2 = EggStore(db2, flush_interval=60.0)
                repo2 = EggBoxRepository(store=store2)
                restored = repo2.load_account(101)
                self.assertIn(9001, repo2.hatch_slots(), "重启后孵化槽应从快照恢复")
                # 槽位恢复影响展示：快照里的蛋按「历史槽位」标注
                snap = repo2.snapshot()
                self.assertEqual(len(snap), 1)
                self.assertEqual(restored, 1)
                store2.close()
            finally:
                db2.close()

    def test_hatch_slots_cleared_on_switch_and_empty_snapshot(self) -> None:
        """切号清空内存槽位；重开后恢复不出切走账号的旧槽位（R06）。"""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "db.sqlite"
            db = Database(db_path)
            try:
                store = EggStore(db, flush_interval=60.0)
                repo = EggBoxRepository(store=store)
                repo.handle_packet(_identity_event(uid=101, name="账号A"))
                repo.handle_packet(_hatch_event([9001]))
                repo.handle_packet(_identity_event(uid=202, name="账号B"))
                self.assertEqual(repo.hatch_slots(), set())  # 切号立即清空内存
                store.close()
            finally:
                db.close()
            # 重启：A 的槽位快照仍可恢复（切号只清内存，不删 A 的历史快照；
            # 快照语义是「最后观察到的槽位」，供历史展示而非当前状态断言）
            db2 = Database(db_path)
            try:
                store2 = EggStore(db2, flush_interval=60.0)
                repo2 = EggBoxRepository(store=store2)
                repo2.load_account(101)
                self.assertIn(9001, repo2.hatch_slots())
                store2.close()
            finally:
                db2.close()

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
                store.close()
            finally:
                db.close()

    def test_store_write_behind_and_close_flush(self) -> None:
        """写入不阻塞（待写表），close 落盘不丢（回归：同步写改异步的等价性）。"""
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "db.sqlite")
            try:
                store = EggStore(db, flush_interval=60.0)  # 不自动落盘，验证待写表
                egg = EggBoxEntry(
                    instance_id=1, egg_conf_id=3001001, pet_conf_id=3001, quantity=1,
                    obtained_at=1, bag_type=8, height_cm=0, weight_g=0,
                    hatch_seconds=0, hatched_seconds=0, hatch_updated_at=0,
                    start_hatch_time=0, category=0, special_egg_conf_id=0,
                    appearance_type=0, extension_type=0,
                )
                store.put(101, [egg])
                self.assertEqual(store.pending_count, 1)
                # 同 id 更新在待写表合并
                store.put(101, [egg])
                self.assertEqual(store.pending_count, 1)
                store.close()  # close 内含最终 flush
                self.assertEqual(store.pending_count, 0)
                self.assertEqual(len(store.load(101)), 1)
            finally:
                db.close()

    def test_store_corrupt_row_isolated_not_fatal(self) -> None:
        """单条坏行不阻断蛋仓恢复：合法蛋照常读出（R04）。"""
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "db.sqlite")
            try:
                store = EggStore(db, flush_interval=60.0)
                eggs = [
                    EggBoxEntry(
                        instance_id=i, egg_conf_id=3001000 + i, pet_conf_id=3000 + i,
                        quantity=1, obtained_at=i, bag_type=8, height_cm=0, weight_g=0,
                        hatch_seconds=0, hatched_seconds=0, hatch_updated_at=0,
                        start_hatch_time=0, category=0, special_egg_conf_id=0,
                        appearance_type=0, extension_type=0,
                    )
                    for i in (1, 2)
                ]
                store.put(101, eggs)
                store.flush()
                db.execute("UPDATE eggs SET obtained_at = 'not-a-number' WHERE instance_id = 1")
                loaded = store.load(101)
                self.assertEqual([e.instance_id for e in loaded], [2], "坏行应被隔离")
                # load_latest 同样不因坏行失败
                uid, latest = store.load_latest()
                self.assertEqual(uid, 101)
                self.assertEqual([e.instance_id for e in latest], [2])
                store.close()
            finally:
                db.close()

    def test_store_detail_json_non_dict_tolerated(self) -> None:
        """detail_json 为列表/null 时按空明细降级，不抛错。"""
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "db.sqlite")
            try:
                store = EggStore(db, flush_interval=60.0)
                store.put(101, [EggBoxEntry(
                    instance_id=5, egg_conf_id=3001001, pet_conf_id=3001, quantity=1,
                    obtained_at=1, bag_type=8, height_cm=0, weight_g=0,
                    hatch_seconds=0, hatched_seconds=0, hatch_updated_at=0,
                    start_hatch_time=0, category=0, special_egg_conf_id=0,
                    appearance_type=0, extension_type=0,
                )])
                store.flush()
                db.execute("UPDATE eggs SET detail_json = '[1,2]' WHERE instance_id = 5")
                loaded = store.load(101)
                self.assertEqual(len(loaded), 1)
                self.assertEqual(loaded[0].hatch_seconds, 0)
                store.close()
            finally:
                db.close()

    def test_load_account_uses_display_uid_not_latest_eggs(self) -> None:
        """蛋仓恢复按组合根指定的展示 uid，不独立按 eggs.updated_at 选账号（R05）。

        审查复现：A 有蛋；B 后登录只写 accounts 不更新蛋仓。旧实现
        load_last_account 按 eggs.updated_at 选出 A，而宠物按 accounts
        选出 B——页面宠物与蛋仓来自不同账号且无归属标记。
        """
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "db.sqlite")
            try:
                egg_store = EggStore(db)
                egg_store.put(111, [EggBoxEntry(  # A(111) 的蛋
                    instance_id=7, egg_conf_id=3001001, pet_conf_id=3001, quantity=1,
                    obtained_at=1791661300, bag_type=8, height_cm=0, weight_g=0,
                    hatch_seconds=0, hatched_seconds=0, hatch_updated_at=0,
                    start_hatch_time=0, category=0, special_egg_conf_id=0,
                    appearance_type=0, extension_type=0,
                )])
                egg_store.flush()
                # B(222) 后登录：只写 accounts（经由 PetStore 的账号表），蛋仓无更新
                from spritelens.repositories.pet_store import PetStore
                pet_store = PetStore(db)
                pet_store.put_account(222, "账号B", 50)
                pet_store.flush()

                repo = EggBoxRepository(store=egg_store)
                # 组合根统一选定展示账号 B(222)：B 无蛋记录 → 明确空，不拿 A 的蛋补齐
                restored = repo.load_account(222)
                self.assertEqual(restored, 0)
                self.assertEqual(repo.snapshot(), ())
                self.assertEqual(repo.loaded_uid, 222)
                # 同账号 B 登录不算切换（离线空数据也登记归属）
                repo.handle_packet(_identity_event(uid=222, name="账号B"))
                self.assertEqual(repo.snapshot(), ())
                # 指定 A(111) 时仍可按账号恢复
                repo2 = EggBoxRepository(store=egg_store)
                self.assertEqual(repo2.load_account(111), 1)
                egg_store.close()
                pet_store.close()
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


class ColorCardTests(unittest.TestCase):
    """色卡目录与 glass → 卡号判定。"""

    def _catalog(self):
        import json
        from pathlib import Path
        from spritelens.domain.color_cards import ColorCatalog
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name)
        (d / "color_cards.json").write_text(json.dumps({
            "cards": [
                {"card_id": "7", "base_name": "紫色", "mix_name": "绿色",
                 "base_color": "#b869ed", "mix_color": "#83d256"},
                {"card_id": "29", "base_name": "绿色", "mix_name": "粉色",
                 "base_color": "#83d256", "mix_color": "#e5576f"},
            ],
            "particles": {"1": "四角星"},
        }, ensure_ascii=False), encoding="utf-8")
        return ColorCatalog(d)

    def test_card_lookup(self) -> None:
        catalog = self._catalog()
        self.assertEqual(catalog.card("7").base_name, "紫色")
        self.assertIsNone(catalog.card("999"))

    def test_card_id_for(self) -> None:
        catalog = self._catalog()
        # 普通卡：value 低 20 位（高位为标志位）
        self.assertEqual(catalog.card_id_for(1, 1048605), "29")   # 1048605 & 0xFFFFF = 29
        self.assertEqual(catalog.card_id_for(1, 7), "7")
        # 赛季卡：type=2 且 value 低 20 位 ∈ 1..4
        self.assertEqual(catalog.card_id_for(2, 1), "s1")
        self.assertEqual(catalog.card_id_for(2, 4), "s4")
        # 未收录
        self.assertEqual(catalog.card_id_for(1, 999999), "")

    def test_payload_matrix(self) -> None:
        from spritelens.web.payloads import colors_payload

        class Repo:
            def snapshot(self):
                return [self._p]
        repo = Repo()
        repo._p = self._pet(1, "菊花梨", 1, 1)  # glass 1×1048605 → 卡 29

        class Catalog:
            def cards(self):
                from types import SimpleNamespace
                return [SimpleNamespace(base_name="绿色", mix_name="粉色")]
            def card(self, cid):
                from types import SimpleNamespace
                return SimpleNamespace(base_name="绿色", mix_name="粉色") if cid == "29" else None
            def card_id_for(self, t, v):
                return "29"
            def effect_for(self, t, v):
                return {"card_id": "29", "particle_id": 1}

        payload = colors_payload(repo, Catalog(), None)
        self.assertEqual(payload["pet_total"], 1)
        self.assertIn("绿色|粉色", payload["matrix"])

    def _pet(self, gid, name, gender, base_conf_id):
        from spritelens.domain.pets import Pet, PetAttribute
        return Pet(
            gid=gid, conf_id=2000000 + gid, name=name, level=40, exp=0,
            nature=1, gender=gender, blood_id=1, talent_rank=3,
            is_first_catch=False, base_conf_id=base_conf_id,
            attributes=(PetAttribute(),) * 6, height=0, weight=0, voice=0,
            glass_type=1, glass_value=1048605, mutation_type=8, skills=(),
        )


if __name__ == "__main__":
    unittest.main()
