"""pets.partner_mark 原地迁移的对抗性复核。

四个问题（对应四个测试类）：
1. ``MigrationRollbackTest``   迁移事务中途失败能否完整回滚，失败后能否再次正常打开；
2. ``MigrationIdempotencyTest`` 重复打开是否幂等（不再迁移、不再备份、结构与数据不变）；
3. ``WalSidecarTest``          旧库带 -wal/-shm 时迁移、切 WAL 后关闭重开、备份组成功与失败行为；
4. ``UnknownSchemaTest``       未知结构在「库内已有数据 / 没有数据」两种情况下分别是阻止启动还是备份重建。

测试自包含：不读取 %LOCALAPPDATA% 运行数据；真实旧库样本仅在环境变量
``SPRITELENS_LEGACY_DB`` 指向它、或本机存在历史 .incompatible-* 备份时以只读方式
复制一份做比对，否则整类跳过。所有写入都发生在测试自己的临时目录内。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

from spritelens.repositories.database import (
    _BASELINE_SCHEMA,
    Database,
    DatabaseSchemaError,
)

_REAL_SAMPLE_ENV = "SPRITELENS_LEGACY_DB"
_REAL_SAMPLE_DEFAULT = (
    Path(os.environ.get("LOCALAPPDATA", ""))
    / "SpriteLens"
    / "spritelens.incompatible-1792836638.sqlite"
)


def _make_tmp(test: unittest.TestCase) -> Path:
    """可写临时目录；受限沙箱里 mkdtemp 的 0700 目录不可写，退回默认 mode。

    正常环境下第一次 mkdtemp 就能用，不会走到兜底分支。
    """
    root = Path(tempfile.mkdtemp(prefix="partner-mark-"))
    try:
        probe = root / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError:
        shutil.rmtree(root, ignore_errors=True)
        root = Path(tempfile.gettempdir()) / f"partner-mark-{uuid.uuid4().hex[:12]}"
        root.mkdir(parents=True)
    test.addCleanup(shutil.rmtree, root, ignore_errors=True)
    return root


def _pets_statement() -> str:
    return next(
        statement for statement in _BASELINE_SCHEMA
        if statement.lstrip().startswith("CREATE TABLE pets")
    )


def _legacy_pets_statement() -> str:
    """上一版 schema 1 的 pets：只比当前基线少 partner_mark 一行。"""
    current = _pets_statement()
    legacy = current.replace(",\n        partner_mark   INTEGER NOT NULL DEFAULT 0", "", 1)
    if legacy == current:
        raise AssertionError("基线 pets DDL 已变化，旧结构夹具需要同步更新")
    return legacy


def _normalize(statement: str) -> str:
    """与 database.py 相同的 DDL 归一化：迁移经 ALTER ... RENAME 后表名会带引号。"""
    return " ".join(statement.split()).replace('"', "")


def _create_database(
    path: Path,
    *,
    partner_mark: bool = True,
    pets: int = 2,
    eggs: int = 1,
    accounts: int = 1,
    user_version: int = 1,
    extra_tables: tuple[str, ...] = (),
    extra_rows: tuple[str, ...] = (),
) -> sqlite3.Connection:
    """用基线 DDL 直接建库并写入可数数据；返回仍打开的连接，由调用方关闭。"""
    connection = sqlite3.connect(path)
    legacy = None if partner_mark else _legacy_pets_statement()
    for statement in _BASELINE_SCHEMA:
        if legacy is not None and statement.lstrip().startswith("CREATE TABLE pets"):
            statement = legacy
        connection.execute(statement)
    connection.execute(f"PRAGMA user_version = {user_version}")
    for ddl in extra_tables:
        connection.execute(ddl)
    if accounts:
        connection.execute(
            "INSERT INTO accounts (uid, name, first_seen, last_seen) VALUES (1, 'account', 1.0, 1.0)"
        )
    for gid in range(pets):
        connection.execute(
            "INSERT INTO pets (uid, gid, conf_id, name, level, first_seen, updated_at) "
            "VALUES (1, ?, 3001, 'pet', 10, 1.0, 2.0)",
            (gid,),
        )
    for index in range(eggs):
        connection.execute(
            "INSERT INTO eggs (uid, instance_id, updated_at) VALUES (1, ?, 1.0)",
            (100 + index,),
        )
    for sql in extra_rows:
        connection.execute(sql)
    connection.commit()
    return connection


def _snapshot(path: Path) -> dict:
    """结构 + 行数 + 版本 + 日志模式 + 完整性，用于前后逐项比较。"""
    connection = sqlite3.connect(path)
    try:
        master = sorted(
            (row[0], row[1], row[2])
            for row in connection.execute(
                "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            )
        )
        counts = {
            name: connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            for kind, name, _sql in master
            if kind == "table"
        }
        return {
            "master": master,
            "counts": counts,
            "indexes": sorted(name for kind, name, _sql in master if kind == "index"),
            "user_version": connection.execute("PRAGMA user_version").fetchone()[0],
            "journal_mode": connection.execute("PRAGMA journal_mode").fetchone()[0],
            "integrity": connection.execute("PRAGMA integrity_check").fetchone()[0],
            "pets_columns": [
                row[1] for row in connection.execute("PRAGMA table_info(pets)")
            ],
        }
    finally:
        connection.close()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _backup_files(directory: Path, label: str) -> list[Path]:
    """目录下某一类备份的主文件（-wal/-shm 成员以原主文件名为前缀，不在此列）。"""
    return sorted(directory.glob(f"*.{label}-*.sqlite"))


def _copy_group(source: Path, target: Path) -> list[str]:
    """复制主库及 sidecar，模拟进程崩溃后遗留的 WAL 组。"""
    copied = []
    for suffix in ("", "-wal", "-shm"):
        origin = Path(str(source) + suffix)
        if origin.exists():
            shutil.copy2(origin, Path(str(target) + suffix))
            copied.append(suffix or "main")
    return copied


def _real_sample_path() -> Path | None:
    override = os.environ.get(_REAL_SAMPLE_ENV)
    candidates = [Path(override)] if override else [_REAL_SAMPLE_DEFAULT]
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


class _DeniedDatabase(Database):
    """在迁移的指定语句上注入 SQLITE_DENY，模拟事务中途失败（无需磁盘故障）。"""

    def __init__(self, path: Path | str, deny) -> None:  # type: ignore[no-untyped-def]
        self._deny = deny
        super().__init__(path)

    def _open_or_recover(self) -> sqlite3.Connection:
        connection = super()._open_or_recover()
        connection.set_authorizer(self._authorize)
        return connection

    def _authorize(self, action, arg1, arg2, dbname, trigger):  # type: ignore[no-untyped-def]
        return sqlite3.SQLITE_DENY if self._deny(action, arg1) else sqlite3.SQLITE_OK


class MigrationRollbackTest(unittest.TestCase):
    """问题 1：迁移事务中途失败必须完整回滚，且之后仍能正常打开。"""

    def setUp(self) -> None:
        self.tmp_path = _make_tmp(self)
        self.db_path = self.tmp_path / "mig.sqlite"
        _create_database(self.db_path, partner_mark=False, pets=3).close()

    def _assert_untouched(self, before: dict) -> None:
        after = _snapshot(self.db_path)
        self.assertEqual(after["master"], before["master"], "sqlite_master 必须与失败前逐条一致")
        self.assertEqual(after["counts"], before["counts"])
        self.assertEqual(after["user_version"], before["user_version"])
        self.assertEqual(after["integrity"], "ok")
        self.assertNotIn("pets_partner_mark_migration", after["counts"], "不得残留迁移表")
        self.assertIn("idx_pets_conf", after["indexes"])
        self.assertIn("idx_pets_level", after["indexes"])
        self.assertEqual(_backup_files(self.tmp_path, "incompatible"), [])
        self.assertEqual(_backup_files(self.tmp_path, "corrupt"), [])
        self.assertEqual(_backup_files(self.tmp_path, "empty"), [])

    def test_denied_statement_midway_rolls_back_completely(self):
        injections = [
            (
                "INSERT 迁移表",
                lambda action, name: action == sqlite3.SQLITE_INSERT
                and name == "pets_partner_mark_migration",
            ),
            (
                "DROP TABLE pets",
                lambda action, name: action == sqlite3.SQLITE_DROP_TABLE and name == "pets",
            ),
            (
                "CREATE INDEX idx_pets_conf",
                lambda action, name: action == sqlite3.SQLITE_CREATE_INDEX
                and name == "idx_pets_conf",
            ),
            (
                "CREATE INDEX idx_pets_level",
                lambda action, name: action == sqlite3.SQLITE_CREATE_INDEX
                and name == "idx_pets_level",
            ),
        ]
        for label, deny in injections:
            with self.subTest(injection=label):
                before = _snapshot(self.db_path)
                with self.assertRaises(sqlite3.DatabaseError) as raised:
                    _DeniedDatabase(self.db_path, deny)
                self.assertIn("not authorized", str(raised.exception))
                self._assert_untouched(before)

    def test_denied_commit_rolls_back_after_all_statements(self):
        before = _snapshot(self.db_path)
        with self.assertRaises(sqlite3.DatabaseError) as raised:
            _DeniedDatabase(
                self.db_path,
                lambda action, name: action == sqlite3.SQLITE_TRANSACTION and name == "COMMIT",
            )
        self.assertIn("not authorized", str(raised.exception))
        self._assert_untouched(before)

    def test_failed_migration_can_retry_and_keeps_every_pet(self):
        with self.assertRaises(sqlite3.DatabaseError):
            _DeniedDatabase(
                self.db_path,
                lambda action, name: action == sqlite3.SQLITE_DROP_TABLE and name == "pets",
            )
        database = Database(self.db_path)
        try:
            rows = database.query("SELECT gid, partner_mark FROM pets ORDER BY gid")
            self.assertEqual([row[0] for row in rows], [0, 1, 2])
            self.assertEqual([row[1] for row in rows], [0, 0, 0])
            self.assertIn(
                "partner_mark",
                [row[1] for row in database.query("PRAGMA table_info(pets)")],
            )
        finally:
            database.close()
        self.assertEqual(_snapshot(self.db_path)["counts"]["pets"], 3)
        self.assertEqual(_backup_files(self.tmp_path, "incompatible"), [])

    def test_write_lock_busy_keeps_original_and_recovers(self):
        before = _snapshot(self.db_path)
        holder = sqlite3.connect(self.db_path)
        holder.execute("BEGIN IMMEDIATE")
        try:
            with self.assertRaises(sqlite3.OperationalError):
                Database(self.db_path)
        finally:
            holder.rollback()
            holder.close()
        self._assert_untouched(before)

        database = Database(self.db_path)
        try:
            self.assertEqual(database.query("SELECT COUNT(*) FROM pets")[0][0], 3)
            self.assertIn(
                "partner_mark",
                [row[1] for row in database.query("PRAGMA table_info(pets)")],
            )
        finally:
            database.close()


class MigrationIdempotencyTest(unittest.TestCase):
    """问题 2：迁移幂等——第二次打开不再迁移、不再备份，数据与结构保持。"""

    def setUp(self) -> None:
        self.tmp_path = _make_tmp(self)
        self.db_path = self.tmp_path / "mig.sqlite"
        _create_database(
            self.db_path,
            partner_mark=False,
            pets=3,
            extra_tables=("CREATE TABLE legacy_notes (uid INTEGER, note TEXT)",),
            extra_rows=("INSERT INTO legacy_notes VALUES (1, 'keep')",),
        ).close()

    def test_second_open_keeps_schema_and_rows_and_creates_no_backup(self):
        first = Database(self.db_path)
        try:
            self.assertEqual(first.query("SELECT COUNT(*) FROM pets")[0][0], 3)
            self.assertEqual(first.query("SELECT COUNT(*) FROM legacy_notes")[0][0], 1)
        finally:
            first.close()

        after_first = _snapshot(self.db_path)
        self.assertEqual(after_first["journal_mode"], "wal")
        self.assertIn("partner_mark", after_first["pets_columns"])
        self.assertEqual(_backup_files(self.tmp_path, "incompatible"), [])

        second = Database(self.db_path)
        second.close()

        after_second = _snapshot(self.db_path)
        self.assertEqual(after_second, after_first, "第二次打开不得改变结构、数据、版本或日志模式")
        self.assertEqual(_backup_files(self.tmp_path, "incompatible"), [], "不得产生第二份备份")
        self.assertEqual(_backup_files(self.tmp_path, "corrupt"), [])
        self.assertEqual(list(self.tmp_path.glob("*.tmp")), [])
        self.assertEqual(list(self.tmp_path.glob("*.corrupt-preserve.tmp")), [])

    def test_migrated_pets_ddl_and_indexes_match_current_baseline(self):
        Database(self.db_path).close()
        connection = sqlite3.connect(self.db_path)
        try:
            statements = dict(
                connection.execute(
                    "SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL"
                ).fetchall()
            )
            columns = {
                row[1]: row for row in connection.execute("PRAGMA table_info(pets)")
            }
        finally:
            connection.close()

        # 迁移用 CREATE ... ALTER ... RENAME 重建表，sqlite_master 里表名会变成
        # "pets"（带引号）；这里按产品自身的归一化口径比较，引号差异不算结构差异。
        self.assertEqual(_normalize(statements["pets"]), _normalize(_pets_statement()))
        self.assertEqual(columns["partner_mark"][3], 1, "partner_mark 必须 NOT NULL")
        self.assertEqual(columns["partner_mark"][4], "0", "partner_mark 默认值必须为 0")
        for statement in _BASELINE_SCHEMA:
            if statement.lstrip().startswith("CREATE INDEX") and "pets" in statement:
                index_name = statement.split()[2]
                self.assertEqual(_normalize(statements[index_name]), _normalize(statement))
        self.assertEqual(_snapshot(self.db_path)["counts"]["pets"], 3)
        self.assertEqual(_backup_files(self.tmp_path, "incompatible"), [])


class WalSidecarTest(unittest.TestCase):
    """问题 3：-wal/-shm 存在时迁移、切 WAL 后重开、备份组行为。"""

    def setUp(self) -> None:
        self.tmp_path = _make_tmp(self)
        self.db_path = self.tmp_path / "mig.sqlite"
        _create_database(self.db_path, partner_mark=False, pets=2).close()

    def test_rows_committed_in_wal_are_migrated(self):
        source = self.tmp_path / "source.sqlite"
        connection = _create_database(source, partner_mark=False, pets=2)
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(
            "INSERT INTO pets (uid, gid, conf_id, name, level, first_seen, updated_at) "
            "VALUES (1, 77, 3001, 'wal-pet', 30, 3.0, 4.0)"
        )
        connection.commit()  # 只落在 -wal，尚未 checkpoint
        wal = Path(str(source) + "-wal")
        self.assertTrue(wal.exists() and wal.stat().st_size > 0, "夹具必须留下未 checkpoint 的 WAL")

        target = self.tmp_path / "crash.sqlite"
        self.assertEqual(_copy_group(source, target), ["main", "-wal", "-shm"])
        connection.close()

        database = Database(target)
        try:
            self.assertEqual(
                [row[0] for row in database.query("SELECT gid FROM pets ORDER BY gid")],
                [0, 1, 77],
            )
            self.assertEqual(database.query("SELECT name FROM pets WHERE gid = 77")[0][0], "wal-pet")
            self.assertIn(
                "partner_mark",
                [row[1] for row in database.query("PRAGMA table_info(pets)")],
            )
        finally:
            database.close()

        self.assertFalse(Path(str(target) + "-wal").exists(), "迁移关闭后 WAL 应被 checkpoint 并清理")
        self.assertFalse(Path(str(target) + "-shm").exists())
        self.assertEqual(_backup_files(self.tmp_path, "incompatible"), [])
        self.assertEqual(list(self.tmp_path.glob("*.corrupt-preserve.tmp")), [])
        after = _snapshot(target)
        self.assertEqual(after["counts"]["pets"], 3)
        self.assertEqual(after["integrity"], "ok")

    def test_journal_mode_switches_to_wal_and_reopen_is_stable(self):
        Database(self.db_path).close()
        connection = sqlite3.connect(self.db_path)
        try:
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        finally:
            connection.close()
        self.assertFalse(Path(str(self.db_path) + "-wal").exists())
        self.assertFalse(Path(str(self.db_path) + "-shm").exists())

        before = _snapshot(self.db_path)
        Database(self.db_path).close()
        after = _snapshot(self.db_path)
        self.assertEqual(after["master"], before["master"])
        self.assertEqual(after["counts"], before["counts"])
        self.assertEqual(after["journal_mode"], "wal")
        self.assertEqual(_backup_files(self.tmp_path, "incompatible"), [])

    def test_corrupt_group_backup_keeps_all_members(self):
        bad = self.tmp_path / "bad.sqlite"
        originals = {
            bad: b"broken-main" * 10,
            Path(str(bad) + "-wal"): b"broken-wal" * 4,
            Path(str(bad) + "-shm"): b"broken-shm" * 2,
        }
        for path, payload in originals.items():
            path.write_bytes(payload)

        database = Database(bad)
        try:
            self.assertEqual(database.schema_version, 1)
        finally:
            database.close()

        backups = [
            path for path in self.tmp_path.glob("bad.corrupt-*")
            if path.name.endswith(".sqlite")
        ]
        self.assertEqual(len(backups), 1, "损坏库应产生一份备份")
        backup = backups[0]
        self.assertEqual(backup.read_bytes(), originals[bad])
        for suffix in ("-wal", "-shm"):
            self.assertEqual(
                Path(str(backup) + suffix).read_bytes(),
                originals[Path(str(bad) + suffix)],
                f"备份必须保留 {suffix} 成员",
            )
            self.assertFalse(Path(str(bad) + suffix).exists(), "原 sidecar 应随组移走")
        rebuilt = _snapshot(bad)
        self.assertEqual(rebuilt["user_version"], 1)
        self.assertEqual(len(rebuilt["counts"]), 7)
        self.assertTrue(all(count == 0 for count in rebuilt["counts"].values()))

    def test_backup_cleanup_failure_restores_original_group(self):
        # 清理阶段（已复制、正删原组）失败：已删成员必须从备份恢复，原组字节不变。
        # 覆盖两个阶段：第一个成员就失败（还没删过任何文件）、第二个成员失败（主库已删）。
        for label, failing_name in (("first-member", "group.sqlite"), ("later-member", "group.sqlite-wal")):
            with self.subTest(stage=label):
                directory = self.tmp_path / label
                directory.mkdir()
                bad = directory / "group.sqlite"
                originals = {
                    bad: b"broken-main" * 10,
                    Path(str(bad) + "-wal"): b"broken-wal" * 4,
                    Path(str(bad) + "-shm"): b"broken-shm" * 2,
                }
                for path, payload in originals.items():
                    path.write_bytes(payload)

                original_unlink = Path.unlink

                def failing_unlink(self: Path, missing_ok: bool = False):  # type: ignore[no-untyped-def]
                    if self.name == failing_name:
                        raise OSError("注入：清理阶段删除原库失败")
                    return original_unlink(self, missing_ok)

                Path.unlink = failing_unlink  # type: ignore[method-assign]
                try:
                    with self.assertRaises(OSError):
                        Database(bad)
                finally:
                    Path.unlink = original_unlink  # type: ignore[method-assign]

                for path, payload in originals.items():
                    self.assertTrue(path.exists(), f"{path.name} 必须留在原位置")
                    self.assertEqual(path.read_bytes(), payload, f"{path.name} 字节必须不变")

                backups = [
                    path for path in directory.glob("group.corrupt-*")
                    if path.name.endswith(".sqlite")
                ]
                self.assertEqual(len(backups), 1)
                # 留下的是完整备份组（三份成员齐全），不是半个备份
                for suffix in ("", "-wal", "-shm"):
                    member = Path(str(backups[0]) + suffix)
                    self.assertTrue(member.exists(), f"备份成员 {member.name} 必须存在")
                    self.assertEqual(member.read_bytes(), originals[Path(str(bad) + suffix)])

                database = Database(bad)
                try:
                    self.assertEqual(database.schema_version, 1)
                finally:
                    database.close()


class UnknownSchemaTest(unittest.TestCase):
    """问题 4：未知结构必须区分「库内已有数据」与「空库」两种处理。"""

    def setUp(self) -> None:
        self.tmp_path = _make_tmp(self)

    def _assert_blocked(self, path: Path, before_digest: str) -> DatabaseSchemaError:
        with self.assertRaises(DatabaseSchemaError) as raised:
            Database(path)
        self.assertFalse(raised.exception.rebuild_allowed, "有数据时不允许备份后重建")
        self.assertEqual(_sha256(path), before_digest, "阻止启动时原库必须逐字节保持不变")
        self.assertEqual(_backup_files(self.tmp_path, "incompatible"), [], "不得产生备份")
        self.assertEqual(_backup_files(self.tmp_path, "corrupt"), [])
        return raised.exception

    def test_extra_unknown_column_with_data_blocks_startup(self):
        path = self.tmp_path / "extra-column.sqlite"
        _create_database(path, partner_mark=True, pets=2).close()
        connection = sqlite3.connect(path)
        connection.execute(
            "ALTER TABLE pets ADD COLUMN future_flag INTEGER NOT NULL DEFAULT 0"
        )
        connection.commit()
        connection.close()

        self._assert_blocked(path, _sha256(path))

        connection = sqlite3.connect(path)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM pets").fetchone()[0], 2)
            self.assertIn(
                "future_flag",
                [row[1] for row in connection.execute("PRAGMA table_info(pets)")],
            )
        finally:
            connection.close()

    def test_newer_user_version_with_data_blocks_startup(self):
        path = self.tmp_path / "newer.sqlite"
        connection = _create_database(path, partner_mark=True, pets=2, user_version=2)
        connection.close()

        self._assert_blocked(path, _sha256(path))

        connection = sqlite3.connect(path)
        try:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM pets").fetchone()[0], 2)
        finally:
            connection.close()

    def test_old_tables_without_version_and_data_blocks_startup(self):
        path = self.tmp_path / "unversioned.sqlite"
        _create_database(path, partner_mark=False, pets=2, user_version=0).close()

        self._assert_blocked(path, _sha256(path))

        connection = sqlite3.connect(path)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM pets").fetchone()[0], 2)
        finally:
            connection.close()

    def test_user_data_decides_between_blocking_and_rebuilding(self):
        for label, rows, blocked in (("empty", 0, False), ("with-data", 2, True)):
            with self.subTest(case=label):
                directory = self.tmp_path / label
                directory.mkdir()
                path = directory / "unknown.sqlite"
                connection = sqlite3.connect(path)
                connection.execute("CREATE TABLE legacy (value TEXT)")
                for index in range(rows):
                    connection.execute("INSERT INTO legacy VALUES (?)", (f"row-{index}",))
                connection.execute("PRAGMA user_version = 18")
                connection.commit()
                connection.close()

                if blocked:
                    self._assert_blocked(path, _sha256(path))
                    connection = sqlite3.connect(path)
                    try:
                        self.assertEqual(
                            connection.execute("SELECT COUNT(*) FROM legacy").fetchone()[0], rows
                        )
                    finally:
                        connection.close()
                else:
                    database = Database(path)
                    try:
                        self.assertEqual(database.schema_version, 1)
                    finally:
                        database.close()
                    self.assertEqual(len(_backup_files(directory, "incompatible")), 1)
                    rebuilt = _snapshot(path)
                    self.assertEqual(rebuilt["user_version"], 1)
                    self.assertEqual(len(rebuilt["counts"]), 7)
                    self.assertTrue(all(count == 0 for count in rebuilt["counts"].values()))

    def test_extra_unknown_table_with_data_is_tolerated(self):
        path = self.tmp_path / "extra-table.sqlite"
        database = Database(path)
        try:
            database.execute(
                "INSERT INTO accounts (uid, name, first_seen, last_seen) VALUES (1, 'a', 1.0, 1.0)"
            )
            database.execute("CREATE TABLE legacy_notes (uid INTEGER, note TEXT)")
            database.execute("INSERT INTO legacy_notes VALUES (1, 'keep')")
        finally:
            database.close()

        reopened = Database(path)
        try:
            self.assertEqual(reopened.query("SELECT COUNT(*) FROM legacy_notes")[0][0], 1)
            self.assertEqual(reopened.query("SELECT COUNT(*) FROM accounts")[0][0], 1)
        finally:
            reopened.close()
        self.assertEqual(_backup_files(self.tmp_path, "incompatible"), [])

    def test_blocked_startup_keeps_rows_that_live_in_wal(self):
        path = self.tmp_path / "wal-unknown.sqlite"
        connection = _create_database(path, partner_mark=False, pets=1)
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("ALTER TABLE pets ADD COLUMN future_flag INTEGER")
        connection.commit()  # 结构变更只在 -wal 中
        try:
            with self.assertRaises(DatabaseSchemaError) as raised:
                Database(path)
            self.assertFalse(raised.exception.rebuild_allowed)
        finally:
            connection.close()

        self.assertEqual(_backup_files(self.tmp_path, "incompatible"), [])
        reopened = sqlite3.connect(path)
        try:
            self.assertEqual(reopened.execute("SELECT COUNT(*) FROM pets").fetchone()[0], 1)
            self.assertIn(
                "future_flag",
                [row[1] for row in reopened.execute("PRAGMA table_info(pets)")],
            )
            self.assertEqual(reopened.execute("PRAGMA user_version").fetchone()[0], 1)
        finally:
            reopened.close()


@unittest.skipUnless(
    _real_sample_path(),
    "无真实旧库样本：设置 SPRITELENS_LEGACY_DB 指向历史 .incompatible-* 备份后重跑",
)
class RealLegacySampleTest(unittest.TestCase):
    """真实旧库样本（只读复制后）迁移前后必须无损、可重复打开。"""

    def setUp(self) -> None:
        self.tmp_path = _make_tmp(self)
        self.source = _real_sample_path()
        self.db_path = self.tmp_path / "spritelens.sqlite"
        try:
            shutil.copy2(self.source, self.db_path)
        except OSError as exc:
            self.skipTest(f"无法复制真实样本（只读或权限不足）: {exc}")

    def test_real_legacy_sample_migrates_losslessly(self):
        before = _snapshot(self.db_path)
        if "partner_mark" in before["pets_columns"]:
            self.skipTest("真实样本已是当前结构，无法验证旧结构迁移")

        Database(self.db_path).close()

        after = _snapshot(self.db_path)
        self.assertEqual(after["counts"], before["counts"], "迁移前后每张表行数必须一致")
        self.assertIn("partner_mark", after["pets_columns"])
        self.assertNotIn("partner_mark", before["pets_columns"])
        self.assertEqual(after["user_version"], 1)
        self.assertEqual(after["integrity"], "ok")
        self.assertEqual(after["journal_mode"], "wal")
        self.assertEqual(_backup_files(self.tmp_path, "incompatible"), [])

    def test_second_open_of_real_sample_is_stable(self):
        Database(self.db_path).close()
        first = _snapshot(self.db_path)
        Database(self.db_path).close()
        self.assertEqual(_snapshot(self.db_path), first)
        self.assertEqual(_backup_files(self.tmp_path, "incompatible"), [])


if __name__ == "__main__":
    unittest.main()
