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

import re
import sqlite3
import threading
import time
from pathlib import Path

from spritelens.logs import get_logger

logger = get_logger("db")

# 迁移语句里的 ALTER ADD COLUMN（用于幂等跳过历史半迁移库的已存在列）
_ADD_COLUMN_RE = re.compile(
    r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(\w+)", re.IGNORECASE
)

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
    (
        3,
        (
            # 蛋仓快照（bagType==8）：一行一枚蛋实例，明细 JSON 冗余全字段
            """
            CREATE TABLE IF NOT EXISTS eggs (
                uid            INTEGER NOT NULL,
                instance_id    INTEGER NOT NULL,
                egg_conf_id    INTEGER NOT NULL DEFAULT 0,
                pet_conf_id    INTEGER NOT NULL DEFAULT 0,
                quantity       INTEGER NOT NULL DEFAULT 0,
                obtained_at    INTEGER NOT NULL DEFAULT 0,
                hatching       INTEGER NOT NULL DEFAULT 0,
                detail_json    TEXT    NOT NULL DEFAULT '',
                updated_at     REAL    NOT NULL,
                PRIMARY KEY (uid, instance_id)
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_eggs_uid ON eggs (uid, updated_at)",
        ),
    ),
    (
        4,
        (
            # 炫彩外观字段（色卡/花种离线展示依赖；此前未落库，重启清零）
            "ALTER TABLE pets ADD COLUMN colorful_conf_id INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE pets ADD COLUMN glass_type       INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE pets ADD COLUMN glass_value      INTEGER NOT NULL DEFAULT 0",
        ),
    ),
    (
        5,
        (
            "ALTER TABLE pets ADD COLUMN worn_medal_id INTEGER NOT NULL DEFAULT 0",
            "CREATE TABLE IF NOT EXISTS pet_locations (uid INTEGER PRIMARY KEY, snapshot_json TEXT NOT NULL)",
        ),
    ),
    (
        6,
        (
            "ALTER TABLE pets ADD COLUMN is_trial_pet INTEGER NOT NULL DEFAULT 0",
        ),
    ),
    (
        7,
        (
            "ALTER TABLE pets ADD COLUMN is_mirror_pet INTEGER NOT NULL DEFAULT 0",
        ),
    ),
    (
        8,
        (
            # 孵化槽快照（R06）：slots 帧驱动的「槽中蛋 id」与采集时间独立
            # 落库，重启恢复为历史状态——蛋条目自身的时间字段不可靠（实测
            # 全 0 时槽位帧是唯一在孵证据）
            """
            CREATE TABLE IF NOT EXISTS egg_hatch_slots (
                uid          INTEGER PRIMARY KEY,
                slots_json   TEXT NOT NULL,
                collected_at REAL NOT NULL
            )
            """,
        ),
    ),
    (9, (
        "ALTER TABLE pets ADD COLUMN catch_way INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE pets ADD COLUMN add_time INTEGER NOT NULL DEFAULT 0",
    )),
    (10, ("ALTER TABLE pets ADD COLUMN awarded_medals_json TEXT DEFAULT NULL",)),
    (11, (
        "ALTER TABLE eggs ADD COLUMN home_egg INTEGER NOT NULL DEFAULT 0",
        """
        CREATE TABLE IF NOT EXISTS egg_annotations (
            uid            INTEGER NOT NULL,
            instance_id    INTEGER NOT NULL,
            nature_id      INTEGER NOT NULL DEFAULT 0,
            nest_override  TEXT    NOT NULL DEFAULT '',
            pet_gid        INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (uid, instance_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS pet_voice_overrides (
            uid        INTEGER NOT NULL,
            gid        INTEGER NOT NULL,
            voice      INTEGER NOT NULL,
            updated_at REAL    NOT NULL,
            PRIMARY KEY (uid, gid)
        )
        """,
    )),
    (12, (
        "ALTER TABLE egg_annotations ADD COLUMN note TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE egg_annotations ADD COLUMN voice_extreme TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE egg_annotations ADD COLUMN voice_medal TEXT NOT NULL DEFAULT ''",
    )),
    (13, (
        "ALTER TABLE egg_annotations ADD COLUMN voice_tag TEXT NOT NULL DEFAULT ''",
        "UPDATE egg_annotations SET voice_tag = CASE WHEN voice_extreme != '' THEN voice_extreme "
        "ELSE voice_medal END",
    )),
    (14, ("ALTER TABLE egg_annotations ADD COLUMN is_favorite INTEGER NOT NULL DEFAULT 0",)),
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
        """打开库；文件损坏时备份原文件并重建（不阻断启动，原数据留证）。

        只有真正的损坏（NOTADB / CORRUPT）才走恢复；锁定、磁盘 IO 等
        其他数据库错误原样抛出——把好库误判损坏会改名重建成空库。
        备份失败保留原文件并明确失败，绝不删除原文换来空库。
        """
        try:
            conn = sqlite3.connect(str(self.path), check_same_thread=False)
            conn.execute("PRAGMA user_version").fetchone()  # 触发一次真实读取
        except sqlite3.DatabaseError as exc:
            if not self._is_corruption(exc):
                raise
            logger.warning("数据库文件损坏（%s），备份后重建: %s", exc, self.path)
            try:
                conn.close()
            except Exception:  # noqa: BLE001 - 关闭失败不影响重建
                pass
            if str(self.path) != ":memory:" and self.path.exists():
                backup = self.path.with_suffix(f".corrupt-{int(time.time())}.sqlite")
                try:
                    # WAL/SHM 与主库一起移走，避免残件干扰新库恢复
                    for suffix in ("", "-wal", "-shm"):
                        source = Path(str(self.path) + suffix)
                        if suffix and not source.exists():
                            continue
                        source.replace(Path(str(backup) + suffix))
                    logger.warning("原库已备份到: %s", backup)
                except OSError as move_exc:
                    logger.error("备份失败，保留原文件不重建: %s", move_exc)
                    raise
            conn = sqlite3.connect(str(self.path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

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

    # -- 迁移 ----------------------------------------------------------
    def _apply_migrations_locked(self) -> None:
        current = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
        for version, statements in _MIGRATIONS:
            if version <= current:
                continue
            try:
                # 整组 DDL 单事务：中途失败整体回滚，绝不留下「版本号未推进
                # 但半个迁移已提交」的死局（旧实现逐句自动提交，重启必崩
                # duplicate column name）
                self._conn.execute("BEGIN")
                for statement in statements:
                    self._execute_migration_statement_locked(statement)
                self._conn.execute(f"PRAGMA user_version = {version}")
                self._conn.commit()
            except sqlite3.Error as exc:
                self._conn.rollback()
                logger.error("数据库迁移 v%d 失败，已回滚: %s", version, exc)
                raise
            logger.info("数据库迁移: v%d → v%d (%s)", current, version, self.path)
            current = version

    def _execute_migration_statement_locked(self, statement: str) -> None:
        """执行单条迁移语句；ALTER ADD COLUMN 幂等，修复历史半迁移库。

        旧版逐句自动提交，中途中断会留下「列已存在但版本号没推进」的库：
        重启重跑该句报 duplicate column name，启动被彻底卡死。这里对
        ADD COLUMN 先查表结构，列已在则跳过——库自动修复到目标结构。
        """
        match = _ADD_COLUMN_RE.match(statement)
        if match:
            table, column = match.group(1), match.group(2)
            existing = {row[1] for row in self._conn.execute(f"PRAGMA table_info({table})")}
            if column in existing:
                logger.warning("迁移跳过已存在列（历史半迁移库）: %s.%s", table, column)
                return
        self._conn.execute(statement)

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
        if not seq_of_params:
            return 0
        with self._lock:
            try:
                cursor = self._conn.executemany(sql, seq_of_params)
                self._conn.commit()
                return cursor.rowcount
            except sqlite3.Error:
                # 不回滚会留下半批残缺行，并被后续任何 commit 一起带入磁盘
                self._conn.rollback()
                raise

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


__all__ = ["Database"]
