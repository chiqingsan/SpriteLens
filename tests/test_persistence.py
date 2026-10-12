"""持久化功能测试：不依赖 UI / 真实流量，纯领域 + 仓库层验证。

覆盖三条产品级保证：
1. 身份识别正确（只认 self_info 路径，不误取 NPC 的 logic_id）；
2. 重启后数据还在（写库 → 关闭 → 重开 → 加载）；
3. 历史数据不覆盖新数据（本次会话收到的优先）。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from spritelens.domain.identity import extract_identity
from spritelens.domain.pets import Pet
from spritelens.domain.pet_locations import Backpack
from spritelens.capture.key_store import KeyStore
from spritelens.protocol.opcodes import OpcodeCatalog
from spritelens.repositories.database import Database
from spritelens.repositories.pet_store import PetStore
from spritelens.repositories.settings import SettingsRepository
from spritelens.events import PacketEvent
from spritelens.services.monitor_service import MonitorService
from spritelens.services.pet_repository import PetRepository
from spritelens.view_models import CaptureViewModel, PetViewModel

UID = 101384922
OTHER_UID = 999999999


def _make_tmp(test: unittest.TestCase) -> Path:
    """临时目录；Windows 上 WAL 句柄可能延迟释放，清理失败不视为测试失败。"""
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    test.addCleanup(tmp.cleanup)
    return Path(tmp.name)


# --- 事件构造（与真实 ZoneEnterSceneRsp 结构同形）--------------------


def _field(name: str, *, raw=None, children: list | None = None) -> dict:
    node: dict = {"no": 1, "name": name, "type": "", "value": "", "raw": raw}
    if children is not None:
        node["children"] = children
    return node


def identity_event(uid: int = UID, name: str = "话绵雨", level: int = 55, direction: str = "s2c") -> PacketEvent:
    """self_info → avatar → base → {logic_id, name, lv} 的身份包。"""
    base = _field("base", children=[
        _field("logic_id", raw=uid),
        _field("name", raw=name),
        _field("lv", raw=level),
    ])
    avatar = _field("avatar", children=[base])
    return PacketEvent(
        ts=0.0, session_id="s", direction=direction, opcode=0x0152,
        opcode_name="ZoneEnterSceneRsp", payload_len=0,
        decoded=[_field("self_info", children=[avatar])],
    )


def npc_event(uid: int = OTHER_UID) -> PacketEvent:
    """other_actors 下的 NPC 也带 logic_id——必须不被当成本人。"""
    base = _field("base", children=[_field("logic_id", raw=uid), _field("name", raw="护主犬")])
    npc = _field("npc", children=[base])
    return PacketEvent(
        ts=0.0, session_id="s", direction="s2c", opcode=0x0453,
        opcode_name="ZoneSceneClientEnterSceneFinishNtyAck", payload_len=0,
        decoded=[_field("other_actors", children=[npc])],
    )


def pet_event(pets: list[tuple[int, str, int]], direction: str = "s2c") -> PacketEvent:
    """ZoneGetPetInfoByPageRsp 形状的宠物包：nodes 为 (gid, name, level)。"""
    nodes = [
        _field("pet_data", children=[
            _field("gid", raw=gid),
            _field("conf_id", raw=20508),
            _field("name", raw=name.encode()),
            _field("level", raw=level),
        ])
        for gid, name, level in pets
    ]
    return PacketEvent(
        ts=0.0, session_id="s", direction=direction, opcode=0x1346,
        opcode_name="ZoneGetPetInfoByPageRsp", payload_len=0,
        decoded=[_field("pet_info", children=nodes)],
    )


# --- 1. 身份识别 ------------------------------------------------------


class IdentityExtractionTest(unittest.TestCase):
    def test_extract_from_self_info(self):
        identity = extract_identity(identity_event())
        self.assertIsNotNone(identity)
        self.assertEqual(identity.uid, UID)
        self.assertEqual(identity.name, "话绵雨")
        self.assertEqual(identity.level, 55)

    def test_npc_logic_id_not_mistaken(self):
        """实测坑：other_actors 下 NPC 也带 logic_id，不能当成本人。"""
        self.assertIsNone(extract_identity(npc_event()))

    def test_c2s_ignored(self):
        self.assertIsNone(extract_identity(identity_event(direction="c2s")))

    def test_missing_structure_returns_none(self):
        event = PacketEvent(ts=0.0, session_id="s", direction="s2c", opcode=1,
                            opcode_name="x", payload_len=0, decoded=[_field("self_info")])
        self.assertIsNone(extract_identity(event))

    def test_zero_uid_rejected(self):
        self.assertIsNone(extract_identity(identity_event(uid=0)))


# --- 2. 持久化往返（重启后数据还在）-----------------------------------


class PetStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp_path = _make_tmp(self)
        self.db_path = self.tmp_path / "test.sqlite"

    def _pets(self) -> list[Pet]:
        return [
            Pet(gid=1, conf_id=20508, name="魔力猫", level=41, exp=1, nature=11,
                gender=1, blood_id=4, talent_rank=4, is_first_catch=True),
            Pet(gid=2, conf_id=20510, name="岚鸟", level=39, exp=2, nature=3,
                gender=2, blood_id=0, talent_rank=2, is_first_catch=False),
        ]

    def test_write_then_reopen_keeps_data(self):
        """核心保证：写库 → 关闭 → 重开 → 数据仍在（模拟重启应用）。"""
        db1 = Database(self.db_path)
        store1 = PetStore(db1, flush_interval=0.05)
        store1.put_account(UID, "话绵雨", 55)
        store1.put(UID, self._pets())
        store1.close()
        db1.close()

        db2 = Database(self.db_path)
        store2 = PetStore(db2)
        loaded = store2.load(UID)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0].name, "魔力猫")
        self.assertEqual(loaded[0].level, 41)
        self.assertTrue(loaded[0].is_first_catch)
        self.assertEqual(loaded[1].gid, 2)
        # 账号表也持久化
        accounts = store2.list_accounts()
        self.assertEqual(accounts[0], (UID, "话绵雨"))
        store2.close()
        db2.close()

    def test_upsert_updates_existing_pet(self):
        db = Database(self.db_path)
        store = PetStore(db)
        store.put(UID, self._pets())
        store.flush()
        updated = [Pet(gid=1, conf_id=20508, name="魔力猫", level=60, exp=9, nature=11,
                       gender=1, blood_id=4, talent_rank=5, is_first_catch=True)]
        store.put(UID, updated)
        store.flush()
        loaded = store.load(UID)
        self.assertEqual(len(loaded), 2)  # 不重复插入
        self.assertEqual(loaded[0].level, 60)
        self.assertEqual(loaded[0].talent_rank, 5)
        store.close()
        db.close()

    def test_pending_coalesces_duplicates(self):
        """同一 (uid,gid) 多次写入在待写表合并，落盘只算一条。"""
        db = Database(self.db_path)
        store = PetStore(db, flush_interval=60.0)  # 不自动落盘，便于断言待写表
        pet = self._pets()[0]
        for level in (10, 20, 30):
            store.put(UID, [Pet(gid=pet.gid, conf_id=pet.conf_id, name=pet.name, level=level,
                                exp=0, nature=0, gender=0, blood_id=0, talent_rank=0,
                                is_first_catch=False)])
        self.assertEqual(store.pending_count, 1)
        self.assertEqual(store.flush(), 1)
        self.assertEqual(store.load(UID)[0].level, 30)
        store.close()
        db.close()

    def test_invalid_uid_and_gid_ignored(self):
        db = Database(self.db_path)
        store = PetStore(db)
        store.put(0, self._pets())
        store.put_account(0, "x", 1)
        bad = [Pet(gid=0, conf_id=1, name="", level=1, exp=0, nature=0, gender=0,
                   blood_id=0, talent_rank=0, is_first_catch=False)]
        store.put(UID, bad)
        store.flush()
        self.assertEqual(store.load(UID), ())
        self.assertEqual(store.list_accounts(), ())
        store.close()
        db.close()

    def test_account_separated_by_uid(self):
        """多账号数据互不串扰（按 uid 列隔离，而非按表名分表）。"""
        db = Database(self.db_path)
        store = PetStore(db)
        store.put(UID, self._pets())
        store.put(OTHER_UID, self._pets()[:1])
        store.flush()
        self.assertEqual(len(store.load(UID)), 2)
        self.assertEqual(len(store.load(OTHER_UID)), 1)
        store.close()
        db.close()

    def test_background_worker_flushes(self):
        """不手动 flush 也能落盘（write-behind 线程工作）。"""
        import time

        db = Database(self.db_path)
        store = PetStore(db, flush_interval=0.05)
        store.put(UID, self._pets())
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and store.written_count == 0:
            time.sleep(0.02)
        self.assertGreaterEqual(store.written_count, 2)
        self.assertEqual(len(store.load(UID)), 2)
        store.close()
        db.close()


# --- 3. 仓库集成（内存 + 持久化）--------------------------------------


class PetRepositoryPersistenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp_path = _make_tmp(self)
        self.db_path = self.tmp_path / "repo.sqlite"

    def test_identity_then_pets_written_to_store(self):
        db = Database(self.db_path)
        store = PetStore(db)
        repo = PetRepository(store=store)
        repo.handle_packet(identity_event())
        repo.handle_packet(pet_event([(1, "魔力猫", 41), (2, "岚鸟", 39)]))
        self.assertEqual(repo.identity.uid, UID)
        store.flush()
        self.assertEqual(len(store.load(UID)), 2)
        store.close()
        db.close()

    def test_pets_before_identity_not_written(self):
        """身份未到时收到的宠物不入库（不归错账号），内存快照仍保留。"""
        db = Database(self.db_path)
        store = PetStore(db)
        repo = PetRepository(store=store)
        repo.handle_packet(pet_event([(1, "魔力猫", 41)]))
        store.flush()
        self.assertEqual(store.load(UID), ())
        self.assertEqual(len(repo.snapshot()), 1)  # 界面仍可见
        store.close()
        db.close()

    def test_load_persisted_does_not_override_session_data(self):
        """历史数据只补缺，不覆盖本次会话已收到的新数据。"""
        db = Database(self.db_path)
        store = PetStore(db)
        store.put(UID, [Pet(gid=1, conf_id=1, name="旧名字", level=10, exp=0, nature=0,
                            gender=0, blood_id=0, talent_rank=0, is_first_catch=False)])
        store.flush()

        repo = PetRepository(store=store)
        repo.handle_packet(identity_event())
        repo.handle_packet(pet_event([(1, "新名字", 41)]))  # 会话内先收到新数据
        added = repo.load_persisted(UID)
        self.assertEqual(added, 0)
        self.assertEqual(repo.snapshot()[0].name, "新名字")
        store.close()
        db.close()

    def test_load_persisted_fills_missing(self):
        db = Database(self.db_path)
        store = PetStore(db)
        store.put(UID, [Pet(gid=1, conf_id=1, name="历史宠物", level=10, exp=0, nature=0,
                            gender=0, blood_id=0, talent_rank=0, is_first_catch=False)])
        store.flush()

        repo = PetRepository(store=store)
        added = repo.load_persisted(UID)
        self.assertEqual(added, 1)
        self.assertEqual(repo.snapshot()[0].name, "历史宠物")
        store.close()
        db.close()

    def test_load_last_account(self):
        db = Database(self.db_path)
        store = PetStore(db)
        store.put_account(UID, "话绵雨", 55)
        store.put(UID, [Pet(gid=7, conf_id=1, name="上次的宠物", level=20, exp=0, nature=0,
                            gender=0, blood_id=0, talent_rank=0, is_first_catch=False)])
        store.flush()

        repo = PetRepository(store=store)
        self.assertEqual(repo.load_last_account(), 1)
        self.assertEqual(repo.snapshot()[0].gid, 7)
        store.close()
        db.close()

    def test_without_store_behaviour_unchanged(self):
        """未注入 store：不落库、不补历史，但身份跟踪与切换清空照常生效。"""
        repo = PetRepository()
        repo.handle_packet(identity_event())
        repo.handle_packet(pet_event([(1, "魔力猫", 41)]))
        # 身份跟踪独立于持久化（切号清空内存快照是回放场景也需要的隔离）
        self.assertIsNotNone(repo.identity)
        self.assertEqual(repo.identity.uid, UID)
        self.assertEqual(repo.load_persisted(UID), 0)
        self.assertEqual(len(repo.snapshot()), 1)
        # 切换账号 → 旧快照作废
        repo.handle_packet(identity_event(uid=OTHER_UID, name="另一个账号"))
        self.assertEqual(repo.snapshot(), ())


# --- 4. 迁移与降级 ----------------------------------------------------


class DatabaseMigrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp_path = _make_tmp(self)
        self.db_path = self.tmp_path / "mig.sqlite"

    def test_schema_version_set(self):
        db = Database(self.db_path)
        self.assertGreaterEqual(db.schema_version, 1)
        db.close()

    def test_reopen_is_idempotent(self):
        """重复打开不重复执行迁移、不报错、数据保留。"""
        db1 = Database(self.db_path)
        store1 = PetStore(db1)
        store1.put(UID, [Pet(gid=1, conf_id=1, name="x", level=1, exp=0, nature=0,
                             gender=0, blood_id=0, talent_rank=0, is_first_catch=False)])
        store1.close()  # close 内含最终 flush
        db1.close()

        db2 = Database(self.db_path)
        self.assertGreaterEqual(db2.schema_version, 1)
        store2 = PetStore(db2)
        self.assertEqual(len(store2.load(UID)), 1)
        store2.close()
        db2.close()

    def test_in_memory_database(self):
        """:memory: 可直接用于测试，无需临时文件。"""
        db = Database(":memory:")
        store = PetStore(db)
        store.put(UID, [Pet(gid=1, conf_id=1, name="mem", level=1, exp=0, nature=0,
                            gender=0, blood_id=0, talent_rank=0, is_first_catch=False)])
        store.flush()
        self.assertEqual(store.load(UID)[0].name, "mem")
        store.close()
        db.close()

    def test_corrupt_database_recovered_not_fatal(self):
        """损坏库不阻断启动：自动备份原文件并重建空库（原数据留证）。"""
        bad = self.tmp_path / "bad.sqlite"
        bad.write_bytes(b"this is not a sqlite database" * 10)

        db = Database(bad)
        try:
            self.assertGreaterEqual(db.schema_version, 1)
            # 备份文件应存在（保留现场供排查）
            backups = list(self.tmp_path.glob("bad.corrupt-*.sqlite"))
            self.assertEqual(len(backups), 1, "损坏库应被备份")
            # 重建后的库可正常读写
            store = PetStore(db)
            store.put(UID, [Pet(gid=1, conf_id=1, name="re", level=1, exp=0, nature=0,
                                gender=0, blood_id=0, talent_rank=0, is_first_catch=False)])
            store.flush()
            self.assertEqual(len(store.load(UID)), 1)
            store.close()
        finally:
            db.close()

    def test_corrupt_backup_failure_keeps_original_file(self):
        """备份失败必须保留原文件：注入 Path.replace 抛 OSError，原字节不得消失。

        旧实现备份失败后 unlink 原文件再建空库，使「原数据留证」保证失效。
        """
        import sqlite3

        bad = self.tmp_path / "bad.sqlite"
        original_bytes = b"this is not a sqlite database" * 10
        bad.write_bytes(original_bytes)

        import spritelens.repositories.database as db_mod

        original_replace = Path.replace

        def failing_replace(self: Path, target):  # type: ignore[no-untyped-def]
            raise OSError("注入：备份目标不可写")

        Path.replace = failing_replace  # type: ignore[method-assign]
        try:
            with self.assertRaises(OSError):
                Database(bad)
        finally:
            Path.replace = original_replace  # type: ignore[method-assign]

        # 原文件字节不变（未被删除、未被空库覆盖）
        self.assertEqual(bad.read_bytes(), original_bytes)
        # 没有产生半个备份文件
        self.assertEqual(list(self.tmp_path.glob("bad.corrupt-*.sqlite")), [])
        # 备份问题解决后，同一个坏文件仍能走正常备份重建路径
        db = Database(bad)
        try:
            self.assertGreaterEqual(db.schema_version, 1)
            backups = list(self.tmp_path.glob("bad.corrupt-*.sqlite"))
            self.assertEqual(len(backups), 1)
        finally:
            db.close()

    def test_access_error_does_not_delete_database(self):
        """非损坏类错误（如访问/锁定失败）不得删除或覆盖原库文件。

        旧实现对任何 sqlite3.DatabaseError（含 OperationalError 子类）都走
        「备份重建」，备份再失败就把好库删了。恢复只应针对真正的损坏。
        """
        import sqlite3

        good = self.tmp_path / "locked.sqlite"
        original_bytes = good.read_bytes() if good.exists() else b""

        import spritelens.repositories.database as db_mod

        real_connect = sqlite3.connect

        def failing_first_read(*args, **kwargs):  # type: ignore[no-untyped-def]
            conn = real_connect(*args, **kwargs)

            class Guarded:
                def __getattr__(self, name):  # type: ignore[no-untyped-def]
                    return getattr(conn, name)

                def execute(self, sql, params=()):  # type: ignore[no-untyped-def]
                    if "user_version" in sql:
                        raise sqlite3.OperationalError("database is locked")
                    return conn.execute(sql, params)

            return Guarded()

        db_mod.sqlite3.connect = failing_first_read  # type: ignore[assignment]
        good.write_bytes(b"placeholder")  # 便于确认全程未被覆盖
        try:
            with self.assertRaises(sqlite3.OperationalError):
                Database(good)
        finally:
            db_mod.sqlite3.connect = real_connect  # type: ignore[assignment]

        self.assertEqual(good.read_bytes(), b"placeholder")
        self.assertEqual(original_bytes, b"")  # 前置自检：测试开始前文件不存在
        self.assertEqual(list(self.tmp_path.glob("locked.corrupt-*.sqlite")), [])

    def test_v1_database_upgrades_to_v2(self):
        """已发布的 v1 库（无六维/外观列）能直接升至 v2，历史数据保留。"""
        import sqlite3

        v1 = self.tmp_path / "v1.sqlite"
        conn = sqlite3.connect(v1)
        conn.executescript(
            """
            CREATE TABLE accounts (
                uid INTEGER PRIMARY KEY, name TEXT NOT NULL DEFAULT '',
                level INTEGER NOT NULL DEFAULT 0, first_seen REAL NOT NULL, last_seen REAL NOT NULL);
            CREATE TABLE pets (
                uid INTEGER NOT NULL, gid INTEGER NOT NULL, conf_id INTEGER NOT NULL DEFAULT 0,
                name TEXT NOT NULL DEFAULT '', level INTEGER NOT NULL DEFAULT 0,
                exp INTEGER NOT NULL DEFAULT 0, nature INTEGER NOT NULL DEFAULT 0,
                gender INTEGER NOT NULL DEFAULT 0, blood_id INTEGER NOT NULL DEFAULT 0,
                talent_rank INTEGER NOT NULL DEFAULT 0, is_first_catch INTEGER NOT NULL DEFAULT 0,
                first_seen REAL NOT NULL, updated_at REAL NOT NULL, PRIMARY KEY (uid, gid));
            PRAGMA user_version = 1;
            """
        )
        conn.execute("INSERT INTO accounts VALUES (?, ?, 60, 1.0, 2.0)", (UID, "老账号"))
        conn.execute(
            "INSERT INTO pets VALUES (?, 7, 2000671, ?, 30, 100, 11, 2, 4, 4, 1, 1.0, 2.0)",
            (UID, "波波拉"),
        )
        conn.commit()
        conn.close()

        db = Database(v1)
        try:
            self.assertGreaterEqual(db.schema_version, 2)
            cols = {row["name"] for row in db.query("PRAGMA table_info(pets)")}
            self.assertIn("attr_hp", cols)
            self.assertIn("skills_json", cols)
            # 历史行保留，新列取默认值（旧数据无六维，读取不崩）
            store = PetStore(db)
            loaded = store.load(UID)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].name, "波波拉")
            self.assertEqual(loaded[0].attributes, ())
            self.assertEqual(loaded[0].height, 0)
            store.close()
        finally:
            db.close()

    def test_extended_fields_round_trip(self):
        """六维/外观/技能写入后能完整读回（含负值声音）。"""
        from spritelens.domain.pets import PetAttribute, PetSkill

        db = Database(self.db_path)
        store = PetStore(db)
        pet = Pet(
            gid=99, conf_id=3004002, name="迪莫", level=50, exp=5, nature=1, gender=1,
            blood_id=2, talent_rank=5, is_first_catch=True,
            attributes=(
                PetAttribute(total_race=120, talent=10, base_value=200, effort_add=5, talent_add=8),
                PetAttribute(total_race=80, talent=8, base_value=120),
                PetAttribute(total_race=80, talent=8, base_value=118),
                PetAttribute(total_race=105, talent=9, base_value=160),
                PetAttribute(total_race=105, talent=9, base_value=158),
                PetAttribute(total_race=92, talent=7, base_value=140),
            ),
            height=120, weight=50000, voice=-50, mutation_type=1, classis=17,
            breakthrough_lv=10, speciality_id=7, ball_id=3,
            skills=(PetSkill(skill_id=7050210, conf_idx=13, is_learned=True,
                             is_equipped=True, pos=1, unlock_need_lv=48),),
        )
        store.put(UID, [pet])
        store.flush()

        loaded = store.load(UID)[0]
        self.assertEqual(len(loaded.attributes), 6)
        self.assertEqual(loaded.attribute("hp").total_race, 120)
        self.assertEqual(loaded.attribute("hp").final_value, 200 + 8 + 5)
        self.assertEqual(loaded.attribute("spe").total_race, 92)
        self.assertEqual(loaded.height, 120)
        self.assertEqual(loaded.weight, 50000)
        self.assertEqual(loaded.voice, -50)
        self.assertEqual(loaded.mutation_type, 1)
        self.assertEqual(loaded.classis, 17)
        self.assertEqual(loaded.breakthrough_lv, 10)
        self.assertEqual(loaded.speciality_id, 7)
        self.assertEqual(loaded.ball_id, 3)
        self.assertEqual(len(loaded.skills), 1)
        self.assertEqual(loaded.skills[0].skill_id, 7050210)
        self.assertEqual(loaded.skills[0].conf_idx, 13)
        self.assertTrue(loaded.skills[0].is_equipped)
        self.assertEqual(loaded.skills[0].unlock_need_lv, 48)
        store.close()
        db.close()

    def test_extended_fields_default_when_absent(self):
        """老数据/缺字段的宠物入库后，新列全零且读取不崩。"""
        db = Database(self.db_path)
        store = PetStore(db)
        store.put(UID, [Pet(gid=1, conf_id=1, name="x", level=1, exp=0, nature=0,
                            gender=0, blood_id=0, talent_rank=0, is_first_catch=False)])
        store.flush()
        loaded = store.load(UID)[0]
        self.assertEqual(loaded.attributes, ())
        self.assertEqual(loaded.skills, ())
        self.assertEqual((loaded.height, loaded.weight, loaded.voice), (0, 0, 0))
        self.assertEqual((loaded.colorful_conf_id, loaded.glass_type, loaded.glass_value), (0, 0, 0))
        store.close()
        db.close()

    def test_colorful_glass_fields_round_trip(self):
        """炫彩外观字段（colorful_conf_id/glass_type/glass_value）写入后完整读回。

        回归：这三个字段曾未落库，重启后色卡/花种离线展示全部清零。
        """
        db = Database(self.db_path)
        store = PetStore(db)
        store.put(UID, [Pet(gid=9, conf_id=100, name="菊花梨", level=40, exp=0, nature=1,
                            gender=1, blood_id=1, talent_rank=3, is_first_catch=False,
                            colorful_conf_id=130001, glass_type=2, glass_value=5)])
        store.flush()
        loaded = store.load(UID)[0]
        self.assertEqual(loaded.colorful_conf_id, 130001)
        self.assertEqual(loaded.glass_type, 2)
        self.assertEqual(loaded.glass_value, 5)
        store.close()
        db.close()

    def test_v3_database_upgrades_to_v4(self):
        """v3 库（无外观字段列）升级后读写正常，历史数据保留。"""
        import sqlite3

        v3 = self.tmp_path / "v3.sqlite"
        conn = sqlite3.connect(v3)
        conn.executescript(
            """
            CREATE TABLE accounts (
                uid INTEGER PRIMARY KEY, name TEXT NOT NULL DEFAULT '',
                level INTEGER NOT NULL DEFAULT 0, first_seen REAL NOT NULL, last_seen REAL NOT NULL);
            CREATE TABLE pets (
                uid INTEGER NOT NULL, gid INTEGER NOT NULL, conf_id INTEGER NOT NULL DEFAULT 0,
                name TEXT NOT NULL DEFAULT '', level INTEGER NOT NULL DEFAULT 0,
                exp INTEGER NOT NULL DEFAULT 0, nature INTEGER NOT NULL DEFAULT 0,
                gender INTEGER NOT NULL DEFAULT 0, blood_id INTEGER NOT NULL DEFAULT 0,
                talent_rank INTEGER NOT NULL DEFAULT 0, is_first_catch INTEGER NOT NULL DEFAULT 0,
                first_seen REAL NOT NULL, updated_at REAL NOT NULL,
                attr_hp INTEGER NOT NULL DEFAULT 0, attr_atk INTEGER NOT NULL DEFAULT 0,
                attr_spa INTEGER NOT NULL DEFAULT 0, attr_def INTEGER NOT NULL DEFAULT 0,
                attr_spd INTEGER NOT NULL DEFAULT 0, attr_spe INTEGER NOT NULL DEFAULT 0,
                height INTEGER NOT NULL DEFAULT 0, weight INTEGER NOT NULL DEFAULT 0,
                voice INTEGER NOT NULL DEFAULT 0, mutation_type INTEGER NOT NULL DEFAULT 0,
                classis INTEGER NOT NULL DEFAULT 0, breakthrough_lv INTEGER NOT NULL DEFAULT 0,
                speciality_id INTEGER NOT NULL DEFAULT 0, ball_id INTEGER NOT NULL DEFAULT 0,
                attributes_json TEXT NOT NULL DEFAULT '', skills_json TEXT NOT NULL DEFAULT '',
                base_conf_id INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (uid, gid));
            CREATE TABLE eggs (
                uid INTEGER NOT NULL, instance_id INTEGER NOT NULL,
                egg_conf_id INTEGER NOT NULL DEFAULT 0, pet_conf_id INTEGER NOT NULL DEFAULT 0,
                quantity INTEGER NOT NULL DEFAULT 0, obtained_at INTEGER NOT NULL DEFAULT 0,
                hatching INTEGER NOT NULL DEFAULT 0, detail_json TEXT NOT NULL DEFAULT '',
                updated_at REAL NOT NULL, PRIMARY KEY (uid, instance_id));
            PRAGMA user_version = 3;
            """
        )
        conn.execute("INSERT INTO accounts VALUES (?, ?, 60, 1.0, 2.0)", (UID, "老账号"))
        conn.commit()
        conn.close()

        db = Database(v3)
        try:
            self.assertGreaterEqual(db.schema_version, 4)
            cols = {row["name"] for row in db.query("PRAGMA table_info(pets)")}
            self.assertIn("colorful_conf_id", cols)
            self.assertIn("glass_type", cols)
            self.assertIn("glass_value", cols)
            # 旧库无 pets 行也不影响；写入新外观字段可读回
            store = PetStore(db)
            store.put(UID, [Pet(gid=5, conf_id=7, name="新宠", level=10, exp=0, nature=0,
                                gender=0, blood_id=0, talent_rank=0, is_first_catch=False,
                                colorful_conf_id=5400001, glass_type=1, glass_value=1048605)])
            store.flush()
            loaded = store.load(UID)[0]
            self.assertEqual(loaded.colorful_conf_id, 5400001)
            self.assertEqual(loaded.glass_value, 1048605)
            store.close()
        finally:
            db.close()

    def test_interrupted_migration_no_longer_blocks_startup(self):
        """历史半迁移库（列已在但版本号未推进）能自动修复、不再启动崩溃。

        回归：旧迁移逐句自动提交，中断后重跑报
        `duplicate column name: attr_hp`，应用彻底无法启动。
        """
        import sqlite3

        broken = self.tmp_path / "broken.sqlite"
        conn = sqlite3.connect(broken)
        conn.executescript(
            """
            CREATE TABLE accounts (
                uid INTEGER PRIMARY KEY, name TEXT NOT NULL DEFAULT '',
                level INTEGER NOT NULL DEFAULT 0, first_seen REAL NOT NULL, last_seen REAL NOT NULL);
            CREATE TABLE pets (
                uid INTEGER NOT NULL, gid INTEGER NOT NULL, conf_id INTEGER NOT NULL DEFAULT 0,
                name TEXT NOT NULL DEFAULT '', level INTEGER NOT NULL DEFAULT 0,
                exp INTEGER NOT NULL DEFAULT 0, nature INTEGER NOT NULL DEFAULT 0,
                gender INTEGER NOT NULL DEFAULT 0, blood_id INTEGER NOT NULL DEFAULT 0,
                talent_rank INTEGER NOT NULL DEFAULT 0, is_first_catch INTEGER NOT NULL DEFAULT 0,
                first_seen REAL NOT NULL, updated_at REAL NOT NULL, PRIMARY KEY (uid, gid));
            PRAGMA user_version = 1;
            """
        )
        # 模拟 v2 迁移中途被打断：第一条列已加上，版本号仍停在 1
        conn.execute("ALTER TABLE pets ADD COLUMN attr_hp INTEGER NOT NULL DEFAULT 0")
        conn.commit()
        conn.close()

        db = Database(broken)  # 旧实现会在此抛 duplicate column name
        try:
            self.assertGreaterEqual(db.schema_version, 4)
            cols = {row["name"] for row in db.query("PRAGMA table_info(pets)")}
            for name in ("attr_hp", "attr_atk", "colorful_conf_id", "glass_value"):
                self.assertIn(name, cols)
        finally:
            db.close()

    def test_migration_failure_rolls_back_atomically(self):
        """迁移中途失败整组回滚：不留下「版本未推进但半个迁移已提交」。"""
        import sqlite3

        bad = self.tmp_path / "bad_mig.sqlite"
        conn = sqlite3.connect(bad)
        conn.executescript(
            """
            CREATE TABLE accounts (
                uid INTEGER PRIMARY KEY, name TEXT NOT NULL DEFAULT '',
                level INTEGER NOT NULL DEFAULT 0, first_seen REAL NOT NULL, last_seen REAL NOT NULL);
            CREATE TABLE pets (
                uid INTEGER NOT NULL, gid INTEGER NOT NULL, conf_id INTEGER NOT NULL DEFAULT 0,
                name TEXT NOT NULL DEFAULT '', level INTEGER NOT NULL DEFAULT 0,
                exp INTEGER NOT NULL DEFAULT 0, nature INTEGER NOT NULL DEFAULT 0,
                gender INTEGER NOT NULL DEFAULT 0, blood_id INTEGER NOT NULL DEFAULT 0,
                talent_rank INTEGER NOT NULL DEFAULT 0, is_first_catch INTEGER NOT NULL DEFAULT 0,
                first_seen REAL NOT NULL, updated_at REAL NOT NULL, PRIMARY KEY (uid, gid));
            PRAGMA user_version = 1;
            """
        )
        conn.commit()
        conn.close()

        # 注入点：先执行一条有效 DDL，再执行必然失败的语句——
        # 验证有效 DDL 也随整组回滚（不是「跑了就算」）
        import spritelens.repositories.database as db_mod

        original = db_mod._MIGRATIONS
        broken = (
            original[0],
            (2, (
                "ALTER TABLE pets ADD COLUMN attr_test INTEGER NOT NULL DEFAULT 0",
                "SELECT * FROM not_a_table",
            )),
        )
        db_mod._MIGRATIONS = broken
        try:
            with self.assertRaises(sqlite3.Error):
                Database(bad)
        finally:
            db_mod._MIGRATIONS = original

        # 注入失败后：版本号未推进、v2 的列全部未留下（原子回滚）
        conn = sqlite3.connect(bad)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(pets)")}
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.close()
        self.assertEqual(version, 1)
        self.assertNotIn("attr_test", cols)
        self.assertNotIn("attr_hp", cols)
        # 恢复正常代码库：再次启动可完整升级
        db = Database(bad)
        self.assertGreaterEqual(db.schema_version, 4)
        db.close()

    def test_execute_many_failure_rolls_back(self):
        """批量写入中途失败整体回滚，残缺行不会被后续操作提交带出。"""
        import sqlite3

        db = Database(self.db_path)
        db.execute("CREATE TABLE t (a INTEGER PRIMARY KEY, b INTEGER NOT NULL CHECK (b > 0))")
        with self.assertRaises(sqlite3.Error):
            db.execute_many("INSERT INTO t (a, b) VALUES (?, ?)", [(1, 5), (2, -1)])
        # 失败批次整体不可见（旧实现：第一行留在事务里被后续 commit 带出）
        self.assertEqual(db.query("SELECT a FROM t"), [])
        db.execute("INSERT INTO t (a, b) VALUES (?, ?)", (3, 7))
        self.assertEqual([tuple(r) for r in db.query("SELECT a FROM t")], [(3,)])
        db.close()

    def test_concurrent_flush_keeps_newest_value(self):
        """并发 flush 批次按取出顺序提交：旧批次不得覆盖新值（R02）。

        用 Event 挡住旧批次（旧值）的写库，让新批次先完成提交；旧实现
        没有 flush 互斥，旧批次随后提交会把最终值拉回旧值。
        """
        import sqlite3
        import threading

        db = Database(self.db_path)
        store = PetStore(db, flush_interval=60.0)  # 关闭自动落盘，手动控制
        store.put(UID, [Pet(gid=1, conf_id=20508, name="旧值", level=10, exp=0, nature=0,
                            gender=0, blood_id=0, talent_rank=0, is_first_catch=False)])
        store.flush()
        self.assertEqual(store.load(UID)[0].name, "旧值")

        # 确定性屏障：旧批次写库时挂起，新批次先提交
        old_gate = threading.Event()
        old_batch_started = threading.Event()
        real_execute_many = db.execute_many

        def gated_execute_many(sql, seq_of_params):
            if "INSERT INTO pets" in sql:
                names = [row[3] for row in seq_of_params]
                if "旧值" in names:  # 旧批次：挡住直到新批次提交完成
                    old_batch_started.set()
                    old_gate.wait(timeout=5)
                elif "新值" not in names:
                    raise AssertionError(f"意外的批次: {names}")
            return real_execute_many(sql, seq_of_params)

        db.execute_many = gated_execute_many  # type: ignore[method-assign]
        try:
            # 旧批次被挡住期间 put 仍立即返回（写路径永不等待磁盘）
            store.put(UID, [Pet(gid=1, conf_id=20508, name="旧值", level=20, exp=0, nature=0,
                                gender=0, blood_id=0, talent_rank=0, is_first_catch=False)])
            old_flush = threading.Thread(target=store.flush)
            old_flush.start()
            self.assertTrue(old_batch_started.wait(timeout=5), "旧批次未开始写库")

            store.put(UID, [Pet(gid=1, conf_id=20508, name="新值", level=30, exp=0, nature=0,
                                gender=0, blood_id=0, talent_rank=0, is_first_catch=False)])
            new_flush = threading.Thread(target=store.flush)
            new_flush.start()
            # flush 批次串行化：新批次排在旧批次之后提交，等待旧批次释放
            old_gate.set()
            old_flush.join(timeout=5)
            new_flush.join(timeout=5)
            self.assertFalse(old_flush.is_alive(), "旧批次未完成")
            self.assertFalse(new_flush.is_alive(), "新批次被无限阻塞")
        finally:
            old_gate.set()
            old_flush.join(timeout=5)
            new_flush.join(timeout=5)
            db.execute_many = real_execute_many  # type: ignore[method-assign]

        # 最终落库值以新批次为准（旧实现：旧批次后提交，最终值回退为旧值）
        self.assertEqual(store.load(UID)[0].name, "新值")
        self.assertEqual(store.load(UID)[0].level, 30)
        store.close()
        db.close()

    def test_failed_flush_retry_keeps_newest_value(self):
        """写库失败回填不覆盖期间新写入：重试批次仍以最新值为准。"""
        import sqlite3

        db = Database(self.db_path)
        store = PetStore(db, flush_interval=60.0)
        store.put(UID, [Pet(gid=1, conf_id=20508, name="v1", level=10, exp=0, nature=0,
                            gender=0, blood_id=0, talent_rank=0, is_first_catch=False)])
        # 注入写库失败：本批回填待写表
        real_execute_many = db.execute_many

        def failing_execute_many(sql, seq_of_params):
            if "INSERT INTO pets" in sql:
                raise sqlite3.OperationalError("注入失败")
            return real_execute_many(sql, seq_of_params)

        db.execute_many = failing_execute_many  # type: ignore[method-assign]
        try:
            self.assertEqual(store.flush(), 0)
        finally:
            db.execute_many = real_execute_many  # type: ignore[method-assign]
        self.assertEqual(store.pending_count, 1)

        # 失败后写入更新的值：回填用 setdefault，不得把 v1 盖回 v2
        store.put(UID, [Pet(gid=1, conf_id=20508, name="v2", level=20, exp=0, nature=0,
                            gender=0, blood_id=0, talent_rank=0, is_first_catch=False)])
        self.assertEqual(store.flush(), 1)
        loaded = store.load(UID)[0]
        self.assertEqual(loaded.name, "v2")
        self.assertEqual(loaded.level, 20)
        store.close()
        db.close()

    def test_corrupt_row_isolated_not_fatal(self):
        """单条坏行不阻断整个账号恢复：合法行照常读出，坏行留日志（R04）。

        旧实现整表对象构造无隔离，一只宠物的 attributes_json 被改坏，
        load_last_account 抛 ValueError，应用恢复路径整体失败。
        """
        db = Database(self.db_path)
        store = PetStore(db)
        store.put(UID, [
            Pet(gid=1, conf_id=1, name="好猫", level=1, exp=0, nature=0,
                gender=0, blood_id=0, talent_rank=0, is_first_catch=False),
            Pet(gid=2, conf_id=2, name="好鸟", level=2, exp=0, nature=0,
                gender=0, blood_id=0, talent_rank=0, is_first_catch=False),
        ])
        store.flush()
        # 模拟外部改坏：合法 JSON 但字段类型错（int 列转换失败）
        db.execute(
            "UPDATE pets SET attributes_json = ? WHERE gid = 1",
            ('[{"talent":"bad"}]',),
        )
        loaded = store.load(UID)
        self.assertEqual([p.name for p in loaded], ["好鸟"], "坏行应被隔离，合法行照常恢复")
        store.close()
        db.close()

    def test_corrupt_row_not_silently_overwritten(self):
        """坏行保留在库中等待处置，不被静默删除或伪造数据覆盖。"""
        db = Database(self.db_path)
        store = PetStore(db)
        store.put(UID, [Pet(gid=1, conf_id=1, name="好猫", level=1, exp=0, nature=0,
                            gender=0, blood_id=0, talent_rank=0, is_first_catch=False)])
        store.flush()
        db.execute("UPDATE pets SET attributes_json = ? WHERE gid = 1", ('[{"talent":"bad"}]',))
        store.load(UID)  # 触发隔离读取
        rows = db.query("SELECT attributes_json FROM pets WHERE gid = 1")
        self.assertEqual(rows[0]["attributes_json"], '[{"talent":"bad"}]')
        store.close()
        db.close()

    def test_consistent_snapshot_same_version_across_reads(self):
        """consistent_snapshot 单次锁取齐：pets/backpack/version/uid 同版本（阶段1.5）。"""
        db = Database(self.db_path)
        store = PetStore(db, flush_interval=60.0)
        repo = PetRepository(store=store)

        repo.handle_packet(identity_event(uid=UID, name="账号A"))
        repo.handle_packet(pet_event([(1, "魔力猫", 41)]))
        first = repo.consistent_snapshot()
        self.assertEqual([p.gid for p in first.pets], [1])
        self.assertEqual(first.version, repo.version)
        self.assertEqual(first.uid, UID)
        self.assertIsNotNone(first.identity)

        # 新数据到达后新快照版本递增，且 pets 与 version 一起变化
        repo.handle_packet(pet_event([(1, "魔力猫", 42), (2, "岚鸟", 39)]))
        second = repo.consistent_snapshot()
        self.assertGreater(second.version, first.version)
        self.assertEqual([p.gid for p in second.pets], [1, 2])
        self.assertEqual(second.pets[0].level, 42)
        self.assertIsInstance(second.backpack, Backpack)
        store.close()
        db.close()

    def test_account_switch_clears_snapshot(self):
        """切号后内存快照不混合：B 登录后只应看到 B 的宠物，且入库分 uid 隔离。"""
        db = Database(self.db_path)
        store = PetStore(db, flush_interval=0.05)
        repo = PetRepository(store=store)

        repo.handle_packet(identity_event(uid=UID, name="账号A"))
        repo.handle_packet(pet_event([(1, "A的宠物", 30)]))
        store.flush()

        repo.handle_packet(identity_event(uid=OTHER_UID, name="账号B"))
        repo.handle_packet(pet_event([(2, "B的宠物", 20)]))
        store.flush()

        snap = repo.snapshot()
        self.assertEqual([p.gid for p in snap], [2])  # A 的数据已清出内存
        self.assertEqual(repo.identity.uid, OTHER_UID)
        # 落库各自隔离
        self.assertEqual([p.gid for p in store.load(UID)], [1])
        self.assertEqual([p.gid for p in store.load(OTHER_UID)], [2])
        store.close()
        db.close()

    def test_same_account_identity_refresh_keeps_snapshot(self):
        """同账号重发身份帧（进出场景）不清空快照。"""
        repo = PetRepository()
        repo.handle_packet(identity_event(uid=UID))
        repo.handle_packet(pet_event([(1, "魔力猫", 41)]))
        repo.handle_packet(identity_event(uid=UID, name="话绵雨", level=56))  # 同 uid 重发
        self.assertEqual(len(repo.snapshot()), 1)
        self.assertEqual(repo.identity.level, 56)

    def test_offline_history_same_account_not_treated_as_switch(self):
        """启动时载入的历史数据属于同一账号：其登录到达不得清空。"""
        db = Database(self.db_path)
        store = PetStore(db)
        store.put_account(UID, "账号A", 60)
        store.put(UID, [Pet(gid=7, conf_id=1, name="历史宠物", level=20, exp=0, nature=0,
                            gender=0, blood_id=0, talent_rank=0, is_first_catch=False)])
        store.flush()

        repo = PetRepository(store=store)
        self.assertEqual(repo.load_last_account(), 1)
        repo.handle_packet(identity_event(uid=UID))  # 上次账号登录
        self.assertEqual(len(repo.snapshot()), 1)  # 历史仍可见
        repo.handle_packet(identity_event(uid=OTHER_UID))  # 真切换
        self.assertEqual(repo.snapshot(), ())
        store.close()
        db.close()

    def test_load_persisted_restores_colorful_names(self):
        """回归（P2）：载入历史宠物时重建炫彩名字学习表。

        旧实现只恢复 colorful_conf_id 字段、不重建 id→名字映射，
        重启后花田/花种载荷引用该形态时退化成「#130001」。
        """
        db = Database(self.db_path)
        store = PetStore(db)
        store.put(UID, [Pet(gid=11, conf_id=100, name="菊花梨", level=40, exp=0, nature=0,
                            gender=0, blood_id=0, talent_rank=0, is_first_catch=False,
                            colorful_conf_id=130001, glass_type=1, glass_value=7)])
        store.flush()

        repo = PetRepository(store=store)
        self.assertIsNone(repo.colorful_name(130001))  # 载入前无学习结果
        repo.load_persisted(UID)
        self.assertEqual(repo.colorful_name(130001), "菊花梨")  # 载入即恢复映射
        store.close()
        db.close()


# --- 5. 组合根装配（含关闭落盘）----------------------------------------


class AppContextCloseTest(unittest.TestCase):
    """组合根资源所有权：Database 持有、逆序清理、单项失败不阻断其余（R09）。"""

    def setUp(self):
        self.tmp_path = _make_tmp(self)

    def _make_context(self):
        """最小装配：真实 Database + PetStore，事件日志用假对象观察调用。"""
        from spritelens.app_context import AppContext
        from spritelens.protocol.opcodes import OpcodeCatalog
        from spritelens.view_models import EventsViewModel

        db_path = self.tmp_path / "ctx.sqlite"
        database = Database(db_path)
        pet_store = PetStore(database)
        repo = PetRepository(store=pet_store)
        settings = SettingsRepository(self.tmp_path / "config.json")
        monitor = MonitorService(
            catalog=OpcodeCatalog({}), key_store=KeyStore(self.tmp_path / "keys")
        )

        class _FakeEventLog:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True
                raise RuntimeError("注入：事件日志关闭失败")

        capture_vm = CaptureViewModel(
            monitor=monitor,
            settings=settings,
            keys_dir=self.tmp_path / "keys",
            recordings_dir=self.tmp_path / "recordings",
            port=8195,
            probe_environment=False,
        )
        context = AppContext(
            settings=settings,
            static_data=None,
            monitor=monitor,
            pet_repository=repo,
            capture_vm=capture_vm,
            events_vm=EventsViewModel(monitor=monitor),
            pet_vm=PetViewModel(repo, static_data=None),
            pet_store=pet_store,
            event_log=_FakeEventLog(),
        )
        context.database = database  # 组合根应持有 Database 并负责关闭
        return context, database

    def test_close_closes_database_and_is_idempotent(self):
        context, database = self._make_context()
        # 事件日志注入了关闭失败：close 汇总后仍应抛出（调用方感知）
        with self.assertRaises(RuntimeError):
            context.close()
        # Database 已被组合根关闭（再次执行查询应报错）
        with self.assertRaises(Exception):
            database.query("SELECT 1")
        context.close()  # 幂等：重复关闭不再抛错（含首次失败项）

    def test_close_continues_after_component_failure(self):
        """某一项 close 抛错仍尝试其余清理（R09：旧实现提前置位后跳过）。"""
        context, database = self._make_context()
        with self.assertRaises(RuntimeError):
            context.close()
        # 事件日志失败后，PetStore/Database 仍应完成清理
        with self.assertRaises(Exception):
            database.query("SELECT 1")  # 已关闭
        self.assertEqual(context.pet_store.pending_count, 0)

    def test_database_survives_in_context_for_new_code(self):
        """AppContext 构造可直接携带 database 字段（dataclass 契约）。"""
        from dataclasses import fields

        from spritelens.app_context import AppContext

        names = {f.name for f in fields(AppContext)}
        self.assertIn("database", names)


class BuildRollbackTest(unittest.TestCase):
    """S02：装配失败回滚——任一节点失败，已建资源（DB/log worker）被清理。"""

    def setUp(self):
        self.tmp_path = _make_tmp(self)

    def _isolated_root(self):
        """隔离数据目录；返回恢复函数。"""
        import os

        old_root = os.environ.get("SPRITELENS_DATA_ROOT")

        def restore():
            if old_root is None:
                os.environ.pop("SPRITELENS_DATA_ROOT", None)
            else:
                os.environ["SPRITELENS_DATA_ROOT"] = old_root

        os.environ["SPRITELENS_DATA_ROOT"] = str(self.tmp_path / "data")
        return restore

    def _stub_environment_probe(self):
        """屏蔽 Npcap 探测（避免 PowerShell），返回 mock patcher 上下文。"""
        from unittest import mock

        import spritelens.view_models.capture_vm as vm_mod
        from spritelens.system.environment import NpcapReport

        return mock.patch.object(
            vm_mod,
            "check_npcap",
            lambda **kwargs: NpcapReport(installed=False, wpcap_path=None, message="(测试桩)"),
        )

    def test_successful_build_use_close_reclose(self):
        """D01 回归：正常装配→使用→关闭→重复关闭（此前成功路径必然 NameError）。"""
        from spritelens.app_context import build_app_context

        restore = self._isolated_root()
        try:
            with self._stub_environment_probe():
                context = build_app_context(autostart=False)
        finally:
            restore()
        try:
            # 使用：VM 与仓库可读
            self.assertFalse(context.capture_vm.is_running)
            self.assertEqual(context.pet_vm.total_count(), 0)
            self.assertIsNotNone(context.database)
        finally:
            context.close()
        context.close()  # 重复关闭幂等
        # Database 已关闭：查询报错而不是静默可用
        with self.assertRaises(Exception):
            context.database.query("SELECT 1")

    def test_autostart_failure_stops_capture_and_rolls_back(self):
        """D01：autostart 阶段抛异常也必须停源并回滚已建资源。"""
        from unittest import mock

        from spritelens.app_context import build_app_context
        from spritelens.services.capture_service import CaptureService
        from spritelens.view_models.capture_vm import CaptureViewModel

        restore = self._isolated_root()
        stopped: list[int] = []
        original_stop = CaptureService.stop

        def spy_stop(self):
            stopped.append(1)
            return original_stop(self)

        try:
            with self._stub_environment_probe(), \
                 mock.patch.object(CaptureService, "stop", spy_stop), \
                 mock.patch.object(
                     CaptureViewModel, "start_if_autostart",
                     side_effect=RuntimeError("注入：autostart 失败"),
                 ):
                with self.assertRaises(RuntimeError):
                    build_app_context(autostart=True)
        finally:
            restore()

        self.assertTrue(stopped, "autostart 失败后未停源（capture.stop 未调用）")

    def test_build_failure_rolls_back_created_resources(self):
        """EggStore 构造处注入失败：Database/PetStore/EventLog 已清理。"""
        import spritelens.repositories.egg_store as egg_store_mod
        from spritelens.app_context import build_app_context

        original_init = egg_store_mod.EggStore.__init__

        def failing_init(self, database, **kwargs):
            raise RuntimeError("注入：EggStore 构造失败")

        egg_store_mod.EggStore.__init__ = failing_init  # type: ignore[method-assign]
        # 隔离数据目录：不触碰真实用户库
        restore = self._isolated_root()
        try:
            with self._stub_environment_probe():
                with self.assertRaises(RuntimeError):
                    build_app_context(autostart=False)
        finally:
            egg_store_mod.EggStore.__init__ = original_init  # type: ignore[method-assign]
            restore()

        # Database 已被回滚关闭：对库目录的文件句柄应释放（进程内无活跃连接）
        # 通过再次打开验证一致性（Windows 上句柄未释放时重命名/删除会失败）
        db_file = self.tmp_path / "data" / "spritelens.sqlite"
        if db_file.exists():
            renamed = db_file.with_suffix(".renamed")
            db_file.rename(renamed)  # 句柄未释放会抛 PermissionError
            renamed.rename(db_file)

    def test_shutdown_continues_after_component_failure(self):
        """run._shutdown 单项失败不跳过其余清理，guard 总被释放。"""
        import sys
        from unittest.mock import MagicMock

        sys.path.insert(0, ".")
        from spritelens.web.run import _shutdown

        server, context, guard = MagicMock(), MagicMock(), MagicMock()
        server.stop.side_effect = RuntimeError("注入：server.stop 失败")

        _shutdown(server, context, guard)  # 不应抛出

        context.close.assert_called_once()
        guard.close.assert_called_once()  # server 失败仍执行


class WiringTest(unittest.TestCase):
    """验证组合根装配序列（ui/app.py 的接线逻辑），不启动窗口。

    用真实的装配顺序构造依赖，覆盖「启动 → 收数据 → 关闭 → 重启」全链路；
    这是"改组合根忘记 close 导致丢数据"这类问题的回归保障。
    """

    def setUp(self):
        self.tmp_path = _make_tmp(self)
        self.db_path = self.tmp_path / "wired.sqlite"

    @staticmethod
    def _build(db_path: Path, *, restore: bool) -> tuple[Database, PetStore, PetRepository]:
        """复刻 ui/app.py 的装配：Database → PetStore → PetRepository(store)。"""
        database = Database(db_path)
        store = PetStore(database)
        repo = PetRepository(store=store)
        if restore:
            repo.load_last_account()
        return database, store, repo

    def test_full_lifecycle_survives_restart(self):
        # 第一次运行：身份 → 宠物 → 关闭（close 内含最终 flush）
        db1, store1, repo1 = self._build(self.db_path, restore=False)
        repo1.handle_packet(identity_event())
        repo1.handle_packet(pet_event([(1, "魔力猫", 41), (2, "岚鸟", 39)]))
        store1.close()
        db1.close()

        # 第二次运行：装配时自动恢复上次账号的数据
        db2, store2, repo2 = self._build(self.db_path, restore=True)
        try:
            self.assertEqual(repo2.identity, None)  # 新会话尚未收身份包
            pets = repo2.snapshot()
            self.assertEqual(len(pets), 2)
            self.assertEqual(pets[0].name, "魔力猫")
            self.assertEqual(repo2.cached_accounts(), ((UID, "话绵雨"),))
        finally:
            store2.close()
            db2.close()

    def test_restart_merges_history_with_new_session(self):
        """重启后：历史可见；新会话收到同名 gid 时以新数据为准。"""
        db1, store1, repo1 = self._build(self.db_path, restore=False)
        repo1.handle_packet(identity_event())
        repo1.handle_packet(pet_event([(1, "旧名字", 10)]))
        store1.close()
        db1.close()

        db2, store2, repo2 = self._build(self.db_path, restore=True)
        try:
            self.assertEqual(len(repo2.snapshot()), 1)
            repo2.handle_packet(identity_event())
            repo2.handle_packet(pet_event([(1, "新名字", 55)]))
            snapped = repo2.snapshot()
            self.assertEqual(len(snapped), 1)
            self.assertEqual(snapped[0].name, "新名字")
            self.assertEqual(snapped[0].level, 55)
        finally:
            store2.close()
            db2.close()


if __name__ == "__main__":
    unittest.main()
