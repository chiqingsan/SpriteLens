"""SQLite 连接与基线结构：持久化底座（连接管理 / 串行化访问）。

设计要点：
- 单连接 + 互斥锁：sqlite3 连接对象非线程安全。写入发生在 PetStore 的
  worker 线程、读取发生在 UI 线程，统一由锁串行化；WAL 模式让读写在
  文件层面并发，锁只保护连接对象本身。
- 当前处于破坏性开发阶段，schema 1 直接描述完整当前结构；旧结构不会被
  隐式迁移，避免把开发期历史负债带进发布基线。
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


class DatabaseSchemaError(sqlite3.DatabaseError):
    """本地数据库不是当前破坏性开发基线，需要备份后重建。"""


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
            with self._lock:
                self._initialize_schema_locked()
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            self._conn.close()
            raise

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
                backup = self.path.with_suffix(f".corrupt-{int(time.time())}.sqlite")
                try:
                    for source, temporary in preserved_sidecars:
                        if not source.exists() and temporary.exists():
                            temporary.replace(source)
                    self._backup_corrupt_group(backup)
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

    def _backup_corrupt_group(self, backup: Path) -> None:
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
                raise DatabaseSchemaError(
                    f"数据库 {self.path} 没有当前基线版本，但已经包含旧表；"
                    "请先备份并删除本地数据库后重启"
                )
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
            raise DatabaseSchemaError(
                f"数据库 {self.path} 使用不支持的 schema {current}；"
                "当前开发不兼容旧数据库，请先备份并重建"
            )
        # SQLite 保存建表时的 DDL，直接与唯一基线比较，包含主键、默认值和索引。
        expected = {" ".join(statement.split()) for statement in _BASELINE_SCHEMA}
        actual = {
            " ".join(row[0].split())
            for row in self._conn.execute(
                "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"
            )
        }
        if actual != expected:
            raise DatabaseSchemaError(
                f"数据库 {self.path} 的结构与当前基线不一致；请先备份并重建"
            )

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
