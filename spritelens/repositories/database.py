"""SQLite 连接与迁移：持久化底座（连接管理 / 版本迁移 / 串行化访问）。

设计要点：
- 单连接 + 互斥锁：sqlite3 连接对象非线程安全。写入发生在 PetStore 的
  worker 线程、读取发生在 UI 线程，统一由锁串行化；WAL 模式让读写在
  文件层面并发，锁只保护连接对象本身。
- 迁移用 PRAGMA user_version：老库重开自动补齐；迁移只追加、不修改旧条目，
  任何历史库都能升到最新结构（未来加背包/图鉴表即追加一条）。
- 不依赖 UI 与网络：路径可指向临时目录或 :memory:，测试直接构造即可。
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

from spritelens.logs import get_logger

logger = get_logger("db")

# 结构版本：新增表/列时追加 (版本号, SQL 语句组)，不得修改已发布的条目
_MIGRATIONS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (
        1,
        (
            """
            CREATE TABLE IF NOT EXISTS accounts (
                uid        INTEGER PRIMARY KEY,
                name       TEXT    NOT NULL DEFAULT '',
                level      INTEGER NOT NULL DEFAULT 0,
                first_seen REAL    NOT NULL,
                last_seen  REAL    NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS pets (
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
                PRIMARY KEY (uid, gid)
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_pets_conf  ON pets(uid, conf_id)",
            "CREATE INDEX IF NOT EXISTS idx_pets_level ON pets(uid, level)",
        ),
    ),
    (
        2,
        (
            # 六维最终面板值（可排序/筛选；种族值等明细见 attributes_json）
            "ALTER TABLE pets ADD COLUMN attr_hp  INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE pets ADD COLUMN attr_atk INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE pets ADD COLUMN attr_spa INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE pets ADD COLUMN attr_def INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE pets ADD COLUMN attr_spd INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE pets ADD COLUMN attr_spe INTEGER NOT NULL DEFAULT 0",
            # 外观与培养标量（roco_helper 式筛选维度所需）
            "ALTER TABLE pets ADD COLUMN height          INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE pets ADD COLUMN weight          INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE pets ADD COLUMN voice           INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE pets ADD COLUMN mutation_type   INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE pets ADD COLUMN classis         INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE pets ADD COLUMN breakthrough_lv INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE pets ADD COLUMN speciality_id   INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE pets ADD COLUMN ball_id         INTEGER NOT NULL DEFAULT 0",
            # 明细 JSON：不同步建列，避免登录突发时写入放大（百只级 × 数十字段）
            "ALTER TABLE pets ADD COLUMN attributes_json TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE pets ADD COLUMN skills_json     TEXT NOT NULL DEFAULT ''",
            # 物种关联键：协议字段 15，静态物种表（系别/种族值）一律按它查
            "ALTER TABLE pets ADD COLUMN base_conf_id    INTEGER NOT NULL DEFAULT 0",
        ),
    ),
)


class Database:
    """SQLite 连接包装：迁移、串行化执行、只读查询。"""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = self._open_or_recover()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._apply_migrations_locked()

    def _open_or_recover(self) -> sqlite3.Connection:
        """打开库；文件损坏时备份原文件并重建（不阻断启动，原数据留证）。"""
        try:
            conn = sqlite3.connect(str(self.path), check_same_thread=False)
            conn.execute("PRAGMA user_version").fetchone()  # 触发一次真实读取
        except sqlite3.DatabaseError as exc:
            logger.warning("数据库文件不可用（%s），备份后重建: %s", exc, self.path)
            try:
                conn.close()
            except Exception:  # noqa: BLE001 - 关闭失败不影响重建
                pass
            if str(self.path) != ":memory:" and self.path.exists():
                backup = self.path.with_suffix(f".corrupt-{int(time.time())}.sqlite")
                try:
                    self.path.replace(backup)
                    logger.warning("原库已备份到: %s", backup)
                except OSError as move_exc:
                    logger.warning("备份失败，将覆盖原文件: %s", move_exc)
                    self.path.unlink(missing_ok=True)
            conn = sqlite3.connect(str(self.path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    # -- 迁移 ----------------------------------------------------------
    def _apply_migrations_locked(self) -> None:
        current = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
        for version, statements in _MIGRATIONS:
            if version <= current:
                continue
            for statement in statements:
                self._conn.execute(statement)
            self._conn.execute(f"PRAGMA user_version = {version}")
            self._conn.commit()
            logger.info("数据库迁移: v%d → v%d (%s)", current, version, self.path)
            current = version

    @property
    def schema_version(self) -> int:
        with self._lock:
            return int(self._conn.execute("PRAGMA user_version").fetchone()[0])

    # -- 执行 ----------------------------------------------------------
    def execute(self, sql: str, params: tuple = ()) -> None:
        with self._lock:
            self._conn.execute(sql, params)
            self._conn.commit()

    def execute_many(self, sql: str, seq_of_params: list[tuple]) -> int:
        """批量执行（单事务、一次提交）；返回受影响行数。"""
        if not seq_of_params:
            return 0
        with self._lock:
            cursor = self._conn.executemany(sql, seq_of_params)
            self._conn.commit()
            return cursor.rowcount

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


__all__ = ["Database"]
