"""蛋仓：形状搜索提取、聚合去重、SQLite 持久化、载荷联查。"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from spritelens.domain.egg_box import EggBoxEntry, extract_eggs, extract_hatch_slots
from spritelens.domain.eggs import EggCatalog
from spritelens.repositories.database import Database
from spritelens.repositories.egg_store import EggStore
from spritelens.services.egg_repository import EggBoxRepository
from spritelens.events import PacketEvent
from spritelens.web.payloads_catalog import egg_box_payload


def _field(no: int, raw: object, children: list[dict] | None = None) -> dict:
    node = {"no": no, "name": f"field_{no}", "type": "", "value": "", "raw": raw}
    if children is not None:
        node["children"] = children
    return node


def _egg_row(
    instance_id: int = 9001,
    item_conf_id: int = 107001,
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
                _field(1, 3001001),
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
        self.assertEqual(egg.egg_conf_id, 107001)
        self.assertEqual(egg.pet_conf_id, 3001001)
        self.assertEqual(egg.hatch_seconds, 43200)
        self.assertEqual(egg.category, 6)
        self.assertEqual((egg.from_player_name, egg.from_pet_name, egg.from_player_uin, egg.from_pet_gid),
                         ("", "", 0, 0))
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

    def test_rejects_trial_appearance_as_egg(self) -> None:
        # 试炼条目也会碰巧含 field14=8，但 field15 只有外观 type/value。
        row = _field(3, None, [
            _field(1, 1700000000), _field(2, 3501), _field(3, 60),
            _field(4, 5), _field(14, 8),
            _field(15, None, [_field(1, 1), _field(2, 2097161)]),
        ])
        self.assertEqual(extract_eggs(_event(row, opcode=0x1959)), [])

    def test_rejects_repeated_bag_scalars(self) -> None:
        row = _egg_row()
        row["children"].append(_field(2, 107002))
        self.assertEqual(extract_eggs(_event(row)), [])

    def test_collects_precious_and_glass_fields(self) -> None:
        row = _egg_row()
        row["children"][-1]["children"].extend([
            _field(11, 1), _field(18, 8), _field(21, 6),
            _field(19, None, [_field(1, 1), _field(2, 1048605)]),
        ])
        egg = extract_eggs(_event(row))[0]
        self.assertTrue(egg.is_precious)
        self.assertEqual((egg.appearance_type, egg.extension_type, egg.glass_type, egg.glass_value), (8, 6, 1, 1048605))

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

class EggBoxRepositoryTests(unittest.TestCase):
    def test_origin_fields_survive_failed_flush_and_restart(self) -> None:
        row = _egg_row()
        row["children"][-1]["children"].extend([
            _field(13, "测试来源玩家".encode("utf-8")), _field(14, "来源精灵昵称"),
            _field(15, 4294967295), _field(16, 4294967294),
        ])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "db.sqlite"
            db = Database(path)
            store = EggStore(db, flush_interval=60.0)
            try:
                repo = EggBoxRepository(store=store)
                repo.handle_packet(_identity_event(101))
                pickup_event = _event(row, opcode=0x0243)
                pickup_event.decoded.extend([_field(2, 13), _field(3, 223)])
                repo.handle_packet(pickup_event)
                with patch.object(db, "execute_batches", side_effect=sqlite3.OperationalError("synthetic failure")):
                    with self.assertRaises(sqlite3.OperationalError):
                        store.flush()
                self.assertEqual(store.pending_count, 1)
            finally:
                store.close()
                db.close()
            db = Database(path)
            store = EggStore(db)
            try:
                repo = EggBoxRepository(store=store)
                repo.load_account(101)
                payload = egg_box_payload(repo, None)
                got = payload["eggs"][0]
                self.assertTrue(got["historical"])
                self.assertTrue(got["home_egg"])
                self.assertEqual(got["category"], 6)
                self.assertEqual(got["from_player_name"], "测试来源玩家")
                self.assertEqual(got["from_pet_name"], "来源精灵昵称")
                self.assertEqual(got["from_player_uin"], 4294967295)
                self.assertEqual(got["from_pet_gid"], 4294967294)
                repo.load_account(202)
                self.assertEqual(egg_box_payload(repo, None)["eggs"], [])
                # 旧明细未保存来源字段时仍可读取，不把缺失值补成别的账号或精灵。
                db.execute("UPDATE eggs SET detail_json = ? WHERE uid = 101", ('{"category":6}',))
                legacy = store.load(101)[0]
                self.assertEqual((legacy.from_player_name, legacy.from_pet_name,
                                  legacy.from_player_uin, legacy.from_pet_gid), ("", "", 0, 0))
            finally:
                store.close()
                db.close()

    def test_annotation_and_favorite_changes_invalidate_page_version(self) -> None:
        store = Mock()
        repo = EggBoxRepository(store=store)
        before = repo.version()
        repo.save_annotations(42, 1, 7, "green", "note", "", -20)
        self.assertEqual(repo.version(), before + 1)
        repo.save_favorite(42, 1, True)
        self.assertEqual(repo.version(), before + 2)
        store.save_annotations.side_effect = OSError("synthetic disk failure")
        store.save_favorite.side_effect = OSError("synthetic disk failure")
        with self.assertRaises(OSError):
            repo.save_annotations(42, 1, 0, "", "", "", None)
        with self.assertRaises(OSError):
            repo.save_favorite(42, 1, False)
        self.assertEqual(repo.version(), before + 2)

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
                    appearance_type=8, extension_type=6, is_precious=True,
                    glass_type=1, glass_value=1048605,
                )
                self.assertEqual(store.put(101, [egg]), 1)
                uid, loaded = store.load_latest()
                self.assertEqual(uid, 101)
                self.assertEqual(len(loaded), 1)
                got = loaded[0]
                self.assertEqual(got.instance_id, 7)
                self.assertEqual(got.hatch_seconds, 100)
                self.assertTrue(got.hatching)
                self.assertEqual((got.is_precious, got.glass_type, got.glass_value), (True, 1, 1048605))
                store.save_annotations(101, 7, 0, "", "", "", -20)
                self.assertEqual(store.annotations(101)[7]["voice_db"], -20)
                store.save_annotations(101, 7, 0, "", "", "", None)
                self.assertNotIn(7, store.annotations(101))
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
            self.assertEqual(row["icon_url"], "/static/egg-icons/107001.webp")
            self.assertEqual(row["fallback_icon_url"], "/static/egg-icons/_fallback.webp")
            self.assertEqual(row["egg_kind"], "regular")
            self.assertEqual(payload["total_quantity"], 1)

    def test_payload_labels_unresolved_egg_neutrally(self) -> None:
        """目录里解不出这枚蛋时给中性文案，不把内部配置号当名字摆在卡片上。"""
        repo = EggBoxRepository()
        repo.handle_packet(_event(_egg_row(9)))
        row = egg_box_payload(repo, EggCatalog(None))["eggs"][0]
        self.assertEqual(row["egg_name"], "精灵蛋 · 数据待补")
        self.assertEqual(row["fallback_icon_url"], "/static/egg-icons/_fallback.webp")

    def test_inventory_variant_uses_exact_ranges_and_item_texture(self) -> None:
        import json
        from dataclasses import replace
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "eggs.json").write_text(json.dumps({"eggs": [{
                "egg_key": "synthetic", "egg_conf_id": 4001001, "base_id": 4001,
                "dex_no": 77,
                "name": "测试精灵", "egg_name": "测试精灵蛋", "egg_item_id": 108001,
                "egg_group_names": ["动物组"], "height_low": 10, "height_high": 20,
                "chain_members": [4001, 4002, 4003],
            }]}), encoding="utf-8")
            (directory / "egg_inventory.json").write_text(json.dumps({
                "configs": {"4001002": {"name": "测试精灵", "base_id": 4001, "precious_type": 2,
                    "height_low": 30, "height_high": 40, "weight_low": 500, "weight_high": 900}},
                "items": {"150999": {"name": "测试精灵的异色蛋", "icon_item_id": 108001, "egg_conf_id": 4001002}},
                "random": {"1": {"precious_type": 0, "mutation_type": 0}},
            }), encoding="utf-8")
            catalog = EggCatalog(directory)
            egg = extract_eggs(_event(_egg_row(12, 150999)))[0]
            egg = replace(egg, pet_conf_id=4001002)
            repo = SimpleNamespace(consistent_snapshot=lambda: SimpleNamespace(
                entries=(egg,), slots=frozenset(), slots_source="unknown", historical_ids=frozenset(),
                source="observed", uid=101, version=1))
            class Static:
                def species(self, base_id):
                    name = {4001: "测试精灵", 4002: "罗隐"}.get(base_id)
                    return SimpleNamespace(name=name) if name else None

            row = egg_box_payload(repo, catalog, static=Static())["eggs"][0]
            self.assertEqual(row["species_name"], "测试精灵")
            self.assertEqual(row["dex_no"], 77)
            self.assertEqual(row["chain_names"], ["测试精灵", "罗隐"])
            self.assertEqual(row["egg_kind"], "shiny")
            self.assertEqual(row["icon_url"], "/static/egg-icons/108001.webp")
            self.assertEqual(row["egg_group_names"], ["动物组"])
            self.assertEqual(row["measurement_ranges"]["height_cm"], {"min": 30, "max": 40})
            # 活动蛋等变体配置没有蛋记录：按物种基础 ID 回退，名称/图标/物种/范围不再整块缺失
            (directory / "eggs.json").write_text(json.dumps({"eggs": [{
                "egg_key": "云梦豚#3784001", "egg_conf_id": 3784001, "base_id": 3784,
                "name": "云梦豚的蛋", "egg_name": "云梦豚的蛋", "egg_item_id": 107249,
                "egg_type_name": "普通蛋", "hatch_seconds": 57600,
                "egg_group_names": ["海洋组"], "height_low": 14, "height_high": 21,
                "weight_low": 4900, "weight_high": 11200,
            }]}), encoding="utf-8")
            variant_catalog = EggCatalog(directory)
            variant_egg = replace(extract_eggs(_event(_egg_row(13, 150006)))[0], pet_conf_id=3784002)
            variant_repo = SimpleNamespace(consistent_snapshot=lambda: SimpleNamespace(
                entries=(variant_egg,), slots=frozenset(), slots_source="unknown",
                historical_ids=frozenset(), source="observed", uid=101, version=1))

            class VariantStatic:
                def species(self, base_id):
                    return SimpleNamespace(name="云梦豚") if base_id == 3784 else None

            variant_row = egg_box_payload(variant_repo, variant_catalog, static=VariantStatic())["eggs"][0]
            self.assertEqual(variant_row["egg_name"], "云梦豚的蛋")
            self.assertEqual(variant_row["species_name"], "云梦豚")
            self.assertEqual(variant_row["icon_url"], "/static/egg-icons/107249.webp")
            self.assertEqual(variant_row["egg_group_names"], ["海洋组"])
            self.assertEqual(variant_row["egg_kind"], "regular")
            self.assertEqual(variant_row["measurement_ranges"]["height_cm"], {"min": 14, "max": 21})
            extreme_weights = tuple(
                replace(egg, instance_id=index, weight_g=weight)
                for index, weight in enumerate((500, 501, 508, 892, 899, 900), start=20)
            )
            extreme_repo = SimpleNamespace(consistent_snapshot=lambda: SimpleNamespace(
                entries=extreme_weights, slots=frozenset(), slots_source="unknown", historical_ids=frozenset(),
                source="observed", uid=101, version=1))
            extreme_rows = egg_box_payload(extreme_repo, catalog)["eggs"]
            self.assertEqual([row["tags"]["weight"] for row in extreme_rows],
                             ["底重", None, None, None, None, "满重"])
            self.assertEqual([row["tags"]["medals"] for row in extreme_rows],
                             [[], ["小不点"], [], [], ["大块头"], []])

            voice_annotations = {
                20: {"voice_tag": "满分", "voice_db": -20}, 21: {"voice_tag": "婉转声", "voice_db": None},
                22: {"voice_tag": "底分", "voice_db": 20}, 23: {"voice_tag": "粗嗓门", "voice_db": None},
            }
            voice_entries = tuple(replace(egg, instance_id=index, weight_g=700)
                                  for index in range(20, 24))
            voice_repo = SimpleNamespace(consistent_snapshot=lambda: SimpleNamespace(
                entries=voice_entries, slots=frozenset(), slots_source="unknown", historical_ids=frozenset(),
                source="observed", uid=101, version=1))
            voice_rows = egg_box_payload(voice_repo, catalog, annotations=voice_annotations)["eggs"]
            self.assertEqual([row["tags"]["voice"] for row in voice_rows], ["满分", None, "底分", None])
            self.assertEqual([row["tags"]["medals"] for row in voice_rows],
                             [[], ["婉转声"], [], ["粗嗓门"]])
            self.assertEqual([row["annotations"]["voice_db"] for row in voice_rows], [-20, None, 20, None])
            # 随机配置本身不等于特殊蛋；未知新配置保持未知，不借普通蛋范围。
            random_info = catalog.inventory_egg(310049, 0, 1)
            self.assertEqual(random_info.dex_no, 0)
            from spritelens.domain.egg_box import egg_kind
            self.assertEqual(egg_kind(replace(egg, appearance_type=0), random_info.precious_type, 0, True), "mystery")
            unknown = catalog.inventory_egg(999999, 9999999)
            self.assertEqual(unknown.dex_no, 0)
            self.assertEqual(unknown.height_high, 0)
            self.assertEqual(egg_kind(egg, unknown.precious_type, 0, False), "unknown")

    def test_kind_uses_precious_enum_and_mutation_bits(self) -> None:
        from dataclasses import replace
        from spritelens.domain.egg_box import egg_kind
        egg = extract_eggs(_event(_egg_row()))[0]
        for precious, expected in ((0, "regular"), (1, "special"), (2, "shiny"),
                                   (3, "colorful"), (4, "special"), (5, "special"),
                                   (6, "colorful"), (7, "colorful")):
            with self.subTest(precious=precious):
                self.assertEqual(egg_kind(egg, precious, 0, False), expected)
        self.assertEqual(egg_kind(replace(egg, appearance_type=8), 0, 0, True), "colorful")
        self.assertEqual(egg_kind(replace(egg, appearance_type=1), 0, 0, False), "shiny")
        self.assertEqual(egg_kind(replace(egg, is_precious=True), None, 0, False), "special")

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
        from spritelens.web.payloads_catalog import colors_payload

        class Repo:
            def consistent_snapshot(self):
                return SimpleNamespace(pets=(self._p,), uid=0, version=0)
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
