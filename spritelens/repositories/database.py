"""SQLite 连接与基线结构：持久化底座（连接管理 / 串行化访问）。

设计要点：
- 单连接 + 互斥锁：sqlite3 连接对象非线程安全。写入发生在 PetStore 的
  worker 线程、读取发生在 UI 线程，统一由锁串行化；WAL 模式让读写在
  文件层面并发，锁只保护连接对象本身。
- 当前 schema 1 直接描述完整当前结构；对已知的向后兼容字段变更做原地迁移，
  未知结构仍先备份再重建，避免启动时无提示覆盖用户数据。
- 不依赖 UI 与网络：路径可指向临时目录或 :memory:，测试直接构造即可。
"""

from __future__ import annotations

import shutil
import sqlite3
import threading
import time
from pathlib import Path

from spritelens.logs import get_logger

logger = get_logger("db")

_SCHEMA_VERSION = 1


def _normalize_schema_sql(statement: str) -> str:
    """比较 SQLite DDL 时忽略空白和重命名产生的标识符引号。

    去掉引号这一步是承重条件：``_migrate_partner_mark_column_locked`` 用
    ``ALTER TABLE ... RENAME TO pets`` 重建表，SQLite 会把 DDL 改写成
    ``CREATE TABLE "pets" (...)``；不再迁移的库下次启动就靠这里把引号抹平
    才能与基线原文相等。改动本函数的归一化规则会直接让已迁移的本地库
    命不中基线（且库内已有数据，启动会被阻止）。
    """
    return " ".join(statement.split()).replace('"', "")


class DatabaseSchemaError(sqlite3.DatabaseError):
    """本地数据库不是当前破坏性开发基线。

    ``rebuild_allowed`` 为真时调用方可以备份原库后重建空基线（库内没有
    业务数据，重建不会丢东西）；为假时必须保留原文件并停止启动。
    """

    def __init__(self, message: str, *, rebuild_allowed: bool = True) -> None:
        super().__init__(message)
        self.rebuild_allowed = rebuild_allowed


_BASELINE_SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE accounts (
        uid        INTEGER PRIMARY KEY,
        name       TEXT    NOT NULL DEFAULT '',
        level      INTEGER NOT NULL DEFAULT 0,
        first_seen REAL    NOT NULL,
        last_seen  REAL    NOT NULL,
        avatar_url TEXT    NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE pets (
        uid            INTEGER NOT NULL,
        gid            INTEGER NOT NULL,
        conf_id        INTEGER NOT NULL DEFAULT 0,
        name           TEXT    NOT NULL DEFAULT '',
        level          INTEGER NOT NULL DEFAULT 0,
        exp            INTEGER NOT NULL DEFAULT 0,
        nature         INTEGER NOT NULL DEFAULT 0,
        gender         INTEGER NOT NULL DEFAULT 0,
        blood_id       INTEGER NOT NULL DEFAULT 0,
        talent_rank    INTEGER NOT NULL DEFAULT 0,
        is_first_catch INTEGER NOT NULL DEFAULT 0,
        first_seen     REAL    NOT NULL,
        updated_at     REAL    NOT NULL,
        attr_hp        INTEGER NOT NULL DEFAULT 0,
        attr_atk       INTEGER NOT NULL DEFAULT 0,
        attr_spa       INTEGER NOT NULL DEFAULT 0,
        attr_def       INTEGER NOT NULL DEFAULT 0,
        attr_spd       INTEGER NOT NULL DEFAULT 0,
        attr_spe       INTEGER NOT NULL DEFAULT 0,
        height         INTEGER NOT NULL DEFAULT 0,
        weight         INTEGER NOT NULL DEFAULT 0,
        voice         INTEGER NOT NULL DEFAULT 0,
        mutation_type  INTEGER NOT NULL DEFAULT 0,
        classis        INTEGER NOT NULL DEFAULT 0,
        breakthrough_lv INTEGER NOT NULL DEFAULT 0,
        speciality_id  INTEGER NOT NULL DEFAULT 0,
        ball_id        INTEGER NOT NULL DEFAULT 0,
        attributes_json TEXT NOT NULL DEFAULT '',
        skills_json    TEXT NOT NULL DEFAULT '',
        base_conf_id   INTEGER NOT NULL DEFAULT 0,
        colorful_conf_id INTEGER NOT NULL DEFAULT 0,
        glass_type     INTEGER NOT NULL DEFAULT 0,
        glass_value    INTEGER NOT NULL DEFAULT 0,
        worn_medal_id  INTEGER NOT NULL DEFAULT 0,
        is_trial_pet   INTEGER NOT NULL DEFAULT 0,
        is_mirror_pet  INTEGER NOT NULL DEFAULT 0,
        catch_way      INTEGER NOT NULL DEFAULT 0,
        add_time       INTEGER NOT NULL DEFAULT 0,
        awarded_medals_json TEXT DEFAULT NULL,
        partner_mark   INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (uid, gid)
    )
    """,
    "CREATE INDEX idx_pets_conf ON pets(uid, conf_id)",
    "CREATE INDEX idx_pets_level ON pets(uid, level)",
    """
    CREATE TABLE eggs (
        uid            INTEGER NOT NULL,
        instance_id    INTEGER NOT NULL,
        egg_conf_id    INTEGER NOT NULL DEFAULT 0,
        pet_conf_id    INTEGER NOT NULL DEFAULT 0,
        quantity       INTEGER NOT NULL DEFAULT 0,
        obtained_at    INTEGER NOT NULL DEFAULT 0,
        hatching       INTEGER NOT NULL DEFAULT 0,
        detail_json    TEXT    NOT NULL DEFAULT '',
        updated_at     REAL    NOT NULL,
        home_egg       INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (uid, instance_id)
    )
    """,
    "CREATE INDEX idx_eggs_uid ON eggs(uid, updated_at)",
    "CREATE TABLE pet_locations (uid INTEGER PRIMARY KEY, snapshot_json TEXT NOT NULL)",
    """
    CREATE TABLE egg_hatch_slots (
        uid          INTEGER PRIMARY KEY,
        slots_json   TEXT NOT NULL,
        collected_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE egg_annotations (
        uid           INTEGER NOT NULL,
        instance_id   INTEGER NOT NULL,
        nature_id     INTEGER NOT NULL DEFAULT 0,
        nest_override TEXT    NOT NULL DEFAULT '',
        note          TEXT    NOT NULL DEFAULT '',
        voice_tag     TEXT    NOT NULL DEFAULT '',
        voice_db      INTEGER DEFAULT NULL,
        is_favorite   INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (uid, instance_id)
    )
    """,
    """
    CREATE TABLE home_snapshots (
        uid           INTEGER PRIMARY KEY,
        snapshot_json TEXT    NOT NULL,
        updated_at    REAL    NOT NULL
    )
    """,
)



class Database:
    """SQLite 连接包装：基线初始化、串行化执行、只读查询。"""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = self._open_or_recover()
        try:
            self._configure_connection()
        except DatabaseSchemaError as exc:
            self._conn.close()
            if not exc.rebuild_allowed:
                logger.error(
                    "数据库结构不兼容且库内已有数据，已停止启动并保留原库: %s", exc
                )
                raise
            self._rebuild_unsupported_schema(exc)
            try:
                self._configure_connection()
            except Exception:
                self._conn.close()
                raise
        except Exception:
            self._conn.close()
            raise

    def _configure_connection(self) -> None:
        with self._lock:
            self._initialize_schema_locked()
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")

    def _open_or_recover(self) -> sqlite3.Connection:
        """打开库；文件损坏时备份原文件并重建（不阻断启动，原数据留证）。

        只有真正的损坏（NOTADB / CORRUPT）才走恢复；锁定、磁盘 IO 等
        其他数据库错误原样抛出——把好库误判损坏会改名重建成空库。
        备份失败保留原文件并明确失败，绝不删除原文换来空库。
        """
        preserved_sidecars: list[tuple[Path, Path]] = []
        if str(self.path) != ":memory:" and self.path.exists():
            for suffix in ("-wal", "-shm"):
                source = Path(str(self.path) + suffix)
                if not source.exists():
                    continue
                temporary = source.with_name(source.name + ".corrupt-preserve.tmp")
                try:
                    temporary.unlink(missing_ok=True)
                    shutil.copy2(source, temporary)
                except OSError:
                    temporary.unlink(missing_ok=True)
                    for _source, pending in preserved_sidecars:
                        pending.unlink(missing_ok=True)
                    raise
                preserved_sidecars.append((source, temporary))
        try:
            conn = sqlite3.connect(str(self.path), check_same_thread=False)
            conn.execute("PRAGMA user_version").fetchone()  # 触发一次真实读取
        except sqlite3.DatabaseError as exc:
            if not self._is_corruption(exc):
                for _source, temporary in preserved_sidecars:
                    temporary.unlink(missing_ok=True)
                raise
            logger.warning("数据库文件损坏（%s），备份后重建: %s", exc, self.path)
            try:
                conn.close()
            except Exception:  # noqa: BLE001 - 关闭失败不影响重建
                pass
            if str(self.path) != ":memory:" and self.path.exists():
                backup = self._next_backup_path("corrupt")
                try:
                    for source, temporary in preserved_sidecars:
                        if not source.exists() and temporary.exists():
                            temporary.replace(source)
                    self._backup_database_group(backup)
                    logger.warning("原库已备份到: %s", backup)
                finally:
                    for _source, temporary in preserved_sidecars:
                        temporary.unlink(missing_ok=True)
                conn = sqlite3.connect(str(self.path), check_same_thread=False)
        else:
            for _source, temporary in preserved_sidecars:
                temporary.unlink(missing_ok=True)
        conn.row_factory = sqlite3.Row
        return conn

    def _rebuild_unsupported_schema(self, error: DatabaseSchemaError) -> None:
        """备份不兼容的本地库并创建当前基线，不尝试迁移历史结构。"""
        if str(self.path) == ":memory:":
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            logger.warning("内存数据库结构不兼容，已重建当前基线: %s", error)
            return

        backup = self._next_backup_path("incompatible")
        self._backup_database_group(backup)
        self._conn = self._open_or_recover()
        logger.warning("数据库结构不兼容，原库已备份到 %s，已重建当前基线: %s", backup, error)

    def _next_backup_path(self, label: str) -> Path:
        """返回不会覆盖已有主库或 sidecar 备份的路径。"""
        stamp = int(time.time())
        candidate = self.path.with_suffix(f".{label}-{stamp}.sqlite")
        index = 1
        while any(
            path.exists()
            for path in (candidate, Path(str(candidate) + "-wal"), Path(str(candidate) + "-shm"))
        ):
            candidate = self.path.with_suffix(f".{label}-{stamp}-{index}.sqlite")
            index += 1
        return candidate

    def _backup_database_group(self, backup: Path) -> None:
        """完整备份主库及 sidecar，失败时恢复原路径后再抛错。

        SQLite 的 WAL/SHM 必须与主库一起保留。逐个移动会在中途失败时
        留下「主库已移走、sidecar 仍在原处」的不可恢复状态，因此先把每个
        成员复制到临时备份并逐一固化，再清理原组；清理失败也从备份组恢复。
        """
        members = [
            (Path(str(self.path) + suffix), Path(str(backup) + suffix))
            for suffix in ("", "-wal", "-shm")
        ]
        existing = [(source, target) for source, target in members if source.exists()]
        if not existing:
            return
        staged: list[tuple[Path, Path]] = []
        try:
            for source, target in existing:
                temporary = target.with_name(target.name + ".tmp")
                if temporary.exists():
                    temporary.unlink()
                shutil.copy2(source, temporary)
                temporary.replace(target)
                staged.append((source, target))
            removed: list[Path] = []
            try:
                for source, _target in existing:
                    source.unlink()
                    removed.append(source)
            except OSError:
                for source, target in existing:
                    if source not in removed:
                        continue
                    shutil.copy2(target, source)
                raise
        except OSError as exc:
            # A failed staged copy leaves the original group untouched. If the
            # cleanup phase already removed a member, restore every removed file.
            for source, target in staged:
                if not source.exists() and target.exists():
                    try:
                        shutil.copy2(target, source)
                    except OSError:
                        logger.exception("损坏库恢复原路径失败: %s", source)
            if len(staged) < len(existing):
                for _source, target in staged:
                    try:
                        target.unlink(missing_ok=True)
                    except OSError:
                        logger.exception("不完整损坏库备份清理失败: %s", target)
            for _source, target in existing:
                temporary = target.with_name(target.name + ".tmp")
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    logger.exception("损坏库临时备份清理失败: %s", temporary)
            logger.error("备份失败，保留原文件不重建: %s", exc)
            raise

    @staticmethod
    def _is_corruption(exc: sqlite3.DatabaseError) -> bool:
        """区分真正损坏与锁定/访问等其他数据库错误。

        Python 3.11+ 提供 sqlite_errorcode；取不到时按消息兜底。
        """
        code = getattr(exc, "sqlite_errorcode", None)
        if code is not None:
            return code in (sqlite3.SQLITE_NOTADB, sqlite3.SQLITE_CORRUPT)
        message = str(exc).lower()
        return "file is not a database" in message or "malformed" in message

    # -- 基线结构 ------------------------------------------------------
    def _has_user_data_locked(self) -> bool:
        """库内是否已有业务数据。

        结构不可信时不能假设表名/列名，只做 `SELECT 1 ... LIMIT 1`；
        任何读取失败都按「有数据」处理，宁可阻止重建也不覆盖本地数据。
        """
        names = [
            row[0]
            for row in self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        for name in names:
            quoted = str(name).replace('"', '""')
            try:
                if self._conn.execute(f'SELECT 1 FROM "{quoted}" LIMIT 1').fetchone() is not None:
                    return True
            except sqlite3.Error:
                return True
        return False

    def _schema_error(self, reason: str) -> DatabaseSchemaError:
        """构造结构不兼容错误；库内已有数据时禁止备份重建。"""
        if self._has_user_data_locked():
            return DatabaseSchemaError(
                f"数据库 {self.path} {reason}；"
                "库内已有数据，为避免覆盖本地数据已停止启动，原文件保持不变。"
                "请先备份该文件（同目录 -wal/-shm 一并保留），再确认迁移方式后重试",
                rebuild_allowed=False,
            )
        return DatabaseSchemaError(
            f"数据库 {self.path} {reason}；库内没有数据，将备份原文件后重建",
            rebuild_allowed=True,
        )

    def _initialize_schema_locked(self) -> None:
        current = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
        if current == 0:
            tables = {
                row[0]
                for row in self._conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            if tables:
                raise self._schema_error("没有当前基线版本，但已经包含旧表")
            try:
                self._conn.execute("BEGIN")
                for statement in _BASELINE_SCHEMA:
                    self._conn.execute(statement)
                self._conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
                self._conn.commit()
            except sqlite3.Error:
                self._conn.rollback()
                raise
            logger.info("数据库初始化为 schema %d: %s", _SCHEMA_VERSION, self.path)
            return
        if current != _SCHEMA_VERSION:
            raise self._schema_error(f"使用不支持的 schema {current}")
        # SQLite 保存建表时的 DDL，直接与唯一基线比较，包含主键、默认值和索引。
        expected = {_normalize_schema_sql(statement) for statement in _BASELINE_SCHEMA}
        actual = {
            _normalize_schema_sql(row[0])
            for row in self._conn.execute(
                "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"
            )
        }
        if self._migrate_partner_mark_column_locked(actual, expected):
            actual = {
                _normalize_schema_sql(row[0])
                for row in self._conn.execute(
                    "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"
                )
            }
        if not expected.issubset(actual):
            raise self._schema_error("的结构与当前基线不一致")

    def _migrate_partner_mark_column_locked(
        self, actual: set[str], expected: set[str]
    ) -> bool:
        """将搭档标记字段加入上一版 schema 1，保留已有宠物数据。

        这里只接受已知的单字段追加：其余基线对象必须已经存在，额外旧表保留，
        不把未知结构误判为可迁移结构。
        """
        pets_statement = next(
            statement for statement in _BASELINE_SCHEMA
            if statement.lstrip().startswith("CREATE TABLE pets")
        )
        legacy_statement = pets_statement.replace(
            ",\n        partner_mark   INTEGER NOT NULL DEFAULT 0", "", 1
        )
        normalized_legacy = _normalize_schema_sql(legacy_statement)
        normalized_current = _normalize_schema_sql(pets_statement)
        if normalized_legacy not in actual or normalized_current in actual:
            return False
        if not (expected - {normalized_current}).issubset(actual):
            return False

        old_columns = [row[1] for row in self._conn.execute("PRAGMA table_info(pets)")]
        if "partner_mark" in old_columns:
            return False
        migration_table = "pets_partner_mark_migration"
        quoted_columns = ", ".join(f'"{column}"' for column in old_columns)
        new_statement = pets_statement.replace(
            "CREATE TABLE pets", f"CREATE TABLE {migration_table}", 1
        )
        try:
            self._conn.execute("BEGIN")
            self._conn.execute(new_statement)
            self._conn.execute(
                f"INSERT INTO {migration_table} ({quoted_columns}, partner_mark) "
                f"SELECT {quoted_columns}, 0 FROM pets"
            )
            self._conn.execute("DROP TABLE pets")
            self._conn.execute(f"ALTER TABLE {migration_table} RENAME TO pets")
            for statement in _BASELINE_SCHEMA:
                if statement.lstrip().startswith("CREATE INDEX") and "pets" in statement:
                    self._conn.execute(statement)
            self._conn.commit()
        except sqlite3.Error:
            self._conn.rollback()
            raise
        logger.info("数据库已原地迁移 pets.partner_mark，保留已有数据: %s", self.path)
        return True

    @property
    def schema_version(self) -> int:
        with self._lock:
            return int(self._conn.execute("PRAGMA user_version").fetchone()[0])

    # -- 执行 ----------------------------------------------------------
    def execute(self, sql: str, params: tuple = ()) -> None:
        with self._lock:
            try:
                self._conn.execute(sql, params)
                self._conn.commit()
            except sqlite3.Error:
                self._conn.rollback()
                raise

    def execute_many(self, sql: str, seq_of_params: list[tuple]) -> int:
        """批量执行（单事务、一次提交）；失败整体回滚后抛出。"""
        return self.execute_batches([(sql, seq_of_params)])

    def execute_batches(self, batches: list[tuple[str, list[tuple]]]) -> int:
        """同一业务批次可写多张关联表；全部成功才提交。"""
        with self._lock:
            try:
                self._conn.execute("BEGIN")
                count = 0
                for sql, rows in batches:
                    if rows:
                        count += self._conn.executemany(sql, rows).rowcount
                self._conn.commit()
                return count
            except BaseException:
                self._conn.rollback()
                raise

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


__all__ = ["Database", "DatabaseSchemaError"]
