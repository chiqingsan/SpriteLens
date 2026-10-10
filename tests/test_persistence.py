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
from spritelens.repositories.database import Database
from spritelens.repositories.pet_store import PetStore
from spritelens.services.monitor_service import PacketEvent
from spritelens.services.pet_repository import PetRepository

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
        """未注入 store 时保持纯内存语义（回放 / 单测场景）。"""
        repo = PetRepository()
        repo.handle_packet(identity_event())
        repo.handle_packet(pet_event([(1, "魔力猫", 41)]))
        self.assertIsNone(repo.identity)  # 无 store 不追踪身份
        self.assertEqual(repo.load_persisted(UID), 0)
        self.assertEqual(len(repo.snapshot()), 1)


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
        store.close()
        db.close()


# --- 5. 组合根装配（含关闭落盘）----------------------------------------


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
