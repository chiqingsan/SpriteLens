"""记录数据保留策略：eventlog / recordings / backups 的年龄与总量上限。

背景：`%LOCALAPPDATA%\\SpriteLens` 下的记录数据原先只增不减（实测 eventlog
2.0GB/10 天、recordings 290MB）。本模块负责在启动时与跨天时做保守清理，
只依赖标准库与 `spritelens.logs`，全部函数可注入目录，便于单测。

策略（保守、可解释、失败不致命）：
- `eventlog_YYYYMMDD.jsonl`：先删 mtime 超过 `eventlog_max_age_days` 的整天
  分片，再对剩余非 keep 分片按 mtime 从旧到新删到总量 ≤ `eventlog_max_mb`；
  keep（当天正在写的文件，跨天回调传入新文件）永不删。最新一个已关闭分片
  也受保护（`keep_newest`）：单日分片本身超过总量上限时，宁可略超上限，
  也不把最近一天整份删掉——上限约束的是长期增长，不是最新数据。
- `capture_YYYYMMDD_HHMMSS.jsonl`：同样的年龄 + 总量策略；正在录制的文件
  （keep）永不删。录制文件是整段会话，不做行级截断，只按文件粒度清理。
- `backups/*.sqlite|*.json`：只按年龄（`backups_max_age_days`）删过期备份，
  keep_dirs（如刚生成的数据库迁移备份）整目录跳过；备份是恢复手段，不做
  总量上限，宁可多留。
- 根目录孤儿 sidecar（`spritelens.*.sqlite-shm/-wal`，对应 `.sqlite` 仍在）：
  只清理主库之外的旧备份库 sidecar（读取备份时 SQLite 产生的垃圾）；主库
  `spritelens.sqlite` 的 `-wal/-shm` 永不删，没有对应库的孤 sidecar 也不动。
- 单文件删除失败（PermissionError/OSError，例如文件仍被运行中的进程占用）
  只记 warning 并继续处理其它文件，绝不向上抛出；启动清理的整体异常由
  `app_context` 兜底（只 warning，不阻断启动）。
- 只删目标目录内的普通文件：路径先 `resolve()` 再与目标目录做
  `is_relative_to` 校验，符号链接一律跳过，防目录穿越。
- `max_age_days <= 0` 或 `max_total_bytes <= 0` 关闭对应维度（只按另一维度）。

配置键（config.json，经 `SettingsRepository.get_int` 读取并 clamp）：
- `storage.eventlog_max_age_days`  默认 7，[1, 365]
- `storage.eventlog_max_mb`        默认 1024（1 GB），[64, 102400]
- `storage.recordings_max_age_days` 默认 14，[1, 365]
- `storage.recordings_max_mb`      默认 1024（1 GB），[64, 102400]
- `storage.backups_max_age_days`   默认 30，[3, 3650]
MB 换算按 1024*1024，保留 MB 单位便于用户手改 config.json。

手工清理（一次性排查/回收）：`python tools/cleanup_data_root.py [--root DIR] [--apply]`，
默认 dry-run，`--apply` 才真正移动/删除。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Sequence

from spritelens.logs import get_logger

logger = get_logger("retention")

MB = 1024 * 1024
EVENTLOG_PATTERN = "eventlog_*.jsonl"
RECORDING_PATTERN = "capture_*.jsonl"
SIDECAR_SUFFIXES = ("-shm", "-wal")
MAIN_DATABASE_NAME = "spritelens.sqlite"

# 默认上限（也是 config.json 缺键时的回退值，见模块 docstring 的键表）
EVENTLOG_MAX_AGE_DAYS = 7
EVENTLOG_MAX_MB = 1024
RECORDINGS_MAX_AGE_DAYS = 14
RECORDINGS_MAX_MB = 1024
BACKUPS_MAX_AGE_DAYS = 30

_SECONDS_PER_DAY = 86400.0


# -- 配置 ---------------------------------------------------------------
@dataclass(frozen=True)
class StorageLimits:
    """一次启动读取到的保留上限；字节数由配置的 MB 换算而来。"""

    eventlog_max_age_days: int = EVENTLOG_MAX_AGE_DAYS
    eventlog_max_bytes: int = EVENTLOG_MAX_MB * MB
    recordings_max_age_days: int = RECORDINGS_MAX_AGE_DAYS
    recordings_max_bytes: int = RECORDINGS_MAX_MB * MB
    backups_max_age_days: int = BACKUPS_MAX_AGE_DAYS

    @classmethod
    def from_settings(cls, settings) -> "StorageLimits":
        """从 SettingsRepository 读取（缺键/非法值走默认值 + clamp，不抛）。"""
        return cls(
            eventlog_max_age_days=settings.get_int(
                "storage.eventlog_max_age_days", EVENTLOG_MAX_AGE_DAYS, lo=1, hi=365
            ),
            eventlog_max_bytes=settings.get_int(
                "storage.eventlog_max_mb", EVENTLOG_MAX_MB, lo=64, hi=102400
            ) * MB,
            recordings_max_age_days=settings.get_int(
                "storage.recordings_max_age_days", RECORDINGS_MAX_AGE_DAYS, lo=1, hi=365
            ),
            recordings_max_bytes=settings.get_int(
                "storage.recordings_max_mb", RECORDINGS_MAX_MB, lo=64, hi=102400
            ) * MB,
            backups_max_age_days=settings.get_int(
                "storage.backups_max_age_days", BACKUPS_MAX_AGE_DAYS, lo=3, hi=3650
            ),
        )


@dataclass(frozen=True)
class RetentionReport:
    """一次保留策略执行的删除明细（供启动日志/测试断言使用）。"""

    sidecars: tuple[Path, ...] = ()
    eventlog: tuple[Path, ...] = ()
    recordings: tuple[Path, ...] = ()
    backups: tuple[Path, ...] = ()

    @property
    def total_files(self) -> int:
        return len(self.sidecars) + len(self.eventlog) + len(self.recordings) + len(self.backups)


# -- 底层安全删除 ---------------------------------------------------------
def _safe_resolve(path: Path) -> Path | None:
    try:
        return Path(path).resolve()
    except OSError:
        return None


def _is_inside(path: Path, directory: Path) -> bool:
    """path 解析后是否仍在 directory 内（防 ../ 目录穿越）。"""
    resolved = _safe_resolve(path)
    base = _safe_resolve(directory)
    if resolved is None or base is None:
        return False
    try:
        return resolved == base or resolved.is_relative_to(base)
    except (OSError, ValueError):
        return False


def _iter_regular_files(
    directory: Path, pattern: str, *, recursive: bool = False
) -> Iterator[Path]:
    """枚举目标目录内匹配的普通文件；目录不可读/条目异常只跳过，不抛出。

    符号链接一律跳过：链接可能指向目录之外，删链接本身也容易误伤。
    """
    try:
        entries = directory.rglob(pattern) if recursive else directory.glob(pattern)
        for entry in entries:
            try:
                if entry.is_symlink() or not entry.is_file():
                    continue
            except OSError:
                continue
            yield entry
    except OSError as exc:
        logger.warning("读取目录失败，跳过清理 %s: %s", directory, exc)


def _try_delete_file(
    path: Path, directory: Path, *, dry_run: bool, label: str
) -> int | None:
    """删除 directory 内的普通文件；返回释放字节数，被拒绝/失败返回 None。

    单文件失败（占用、权限、目录穿越）只记 warning，绝不抛出——清理是
    尽力而为，不能让一个坏文件挡住其它文件或启动。
    """
    try:
        if path.is_symlink():
            logger.warning("%s：跳过符号链接 %s", label, path.name)
            return None
        if not _is_inside(path, directory):
            logger.warning("%s：拒绝删除目标目录外的路径 %s", label, path)
            return None
        if not path.is_file():
            return None
        size = path.stat().st_size
    except OSError as exc:
        logger.warning("%s：读取文件状态失败 %s（%s），跳过", label, path.name, exc)
        return None
    if dry_run:
        return size
    try:
        path.unlink()
    except OSError as exc:
        logger.warning("%s：删除失败 %s（%s），继续处理其它文件", label, path.name, exc)
        return None
    logger.debug("%s：已删除 %s（%d 字节）", label, path.name, size)
    return size


def _same_keep(entry: Path, keep: Path | None, keep_resolved: Path | None) -> bool:
    """keep（正在写的文件）判定：解析路径相同，或文件名相同（保守多留）。"""
    if keep is None:
        return False
    if keep_resolved is not None and _safe_resolve(entry) == keep_resolved:
        return True
    return entry.name.casefold() == keep.name.casefold()


# -- 通用策略：年龄 + 总量 --------------------------------------------------
def _prune_by_age_and_size(
    directory: Path,
    pattern: str,
    *,
    max_age_days: float,
    max_total_bytes: int,
    keep: Path | None,
    label: str,
    dry_run: bool,
    keep_newest: int = 0,
) -> list[Path]:
    directory = Path(directory)
    if not directory.is_dir():
        logger.info("%s：目录不存在，跳过清理（%s）", label, directory)
        return []

    keep_resolved = _safe_resolve(keep) if keep is not None else None
    candidates: list[tuple[Path, float, int]] = []
    for entry in _iter_regular_files(directory, pattern):
        if _same_keep(entry, keep, keep_resolved):
            continue
        try:
            stat = entry.stat()
        except OSError as exc:
            logger.warning("%s：读取文件状态失败 %s（%s），跳过", label, entry.name, exc)
            continue
        candidates.append((entry, stat.st_mtime, stat.st_size))

    deleted: list[Path] = []
    freed = 0
    now = time.time()

    # 第一遍：按 mtime 删过旧分片；删除失败的仍计入占用，但不再重复尝试。
    remaining: list[tuple[Path, float, int]] = []
    failed: set[Path] = set()
    if max_age_days > 0:
        cutoff = now - float(max_age_days) * _SECONDS_PER_DAY
        for entry, mtime, size in candidates:
            if mtime < cutoff:
                freed_size = _try_delete_file(entry, directory, dry_run=dry_run, label=label)
                if freed_size is not None:
                    deleted.append(entry)
                    freed += freed_size
                    continue
                failed.add(entry)
            remaining.append((entry, mtime, size))
    else:
        remaining = list(candidates)

    # 第二遍：剩余非 keep 按 mtime 从旧到新删，直到总量 ≤ 上限。
    # keep_newest：最新的若干分片不计入可删集合。单日分片可能单独超过总量
    # 上限（例如大版本更新后的长会话），此时宁可总量略超，也不整份删除最近
    # 一天的数据。
    protected: set[Path] = set()
    if keep_newest > 0 and remaining:
        newest = sorted(remaining, key=lambda item: item[1], reverse=True)[:keep_newest]
        protected = {entry for entry, _mtime, _size in newest}
    if max_total_bytes > 0 and remaining:
        total = sum(size for _entry, _mtime, size in remaining)
        for entry, _mtime, _size in sorted(remaining, key=lambda item: item[1]):
            if total <= max_total_bytes:
                break
            if entry in failed or entry in protected:
                continue
            freed_size = _try_delete_file(entry, directory, dry_run=dry_run, label=label)
            if freed_size is None:
                failed.add(entry)
                continue
            deleted.append(entry)
            freed += freed_size
            total -= freed_size

    logger.info(
        "%s：%s %d 个文件，%s %.2f MB（上限：%s）",
        label,
        "预计清理" if dry_run else "清理",
        len(deleted),
        "预计释放" if dry_run else "释放",
        freed / MB,
        _policy_text(max_age_days, max_total_bytes),
    )
    return deleted


def _policy_text(max_age_days: float, max_total_bytes: int) -> str:
    parts = []
    if max_age_days > 0:
        parts.append(f"年龄>{max_age_days:g}天")
    if max_total_bytes > 0:
        parts.append(f"总量>{max_total_bytes / MB:.0f}MB")
    return " / ".join(parts) if parts else "两维上限均关闭"


# -- 公共 API ------------------------------------------------------------
def prune_event_log(
    log_dir: Path,
    *,
    max_age_days: float,
    max_total_bytes: int,
    keep: Path | None = None,
    dry_run: bool = False,
    keep_newest: int = 0,
) -> list[Path]:
    """清理 `eventlog_*.jsonl`（按年龄再按总量）；`keep`（当天文件）永不删。

    `keep_newest` 保护最新的若干已关闭分片，见 `_prune_by_age_and_size`。
    """
    return _prune_by_age_and_size(
        log_dir,
        EVENTLOG_PATTERN,
        max_age_days=max_age_days,
        max_total_bytes=max_total_bytes,
        keep=keep,
        label="事件日志",
        dry_run=dry_run,
        keep_newest=keep_newest,
    )


def prune_recordings(
    rec_dir: Path,
    *,
    max_age_days: float,
    max_total_bytes: int,
    keep: Path | None = None,
    dry_run: bool = False,
    keep_newest: int = 0,
) -> list[Path]:
    """清理 `capture_*.jsonl`（按年龄再按总量）；`keep`（录制中文件）永不删。

    `keep_newest` 保护最新的若干已关闭录制，避免最近一次会话被整份删掉。
    """
    return _prune_by_age_and_size(
        rec_dir,
        RECORDING_PATTERN,
        max_age_days=max_age_days,
        max_total_bytes=max_total_bytes,
        keep=keep,
        label="录制文件",
        dry_run=dry_run,
        keep_newest=keep_newest,
    )


def prune_backups(
    backups_dir: Path,
    *,
    max_age_days: float,
    keep_dirs: Sequence[Path] = (),
    dry_run: bool = False,
) -> list[Path]:
    """只按年龄删过期备份文件（`.sqlite`/`.json`，含子目录）；keep_dirs 内跳过。

    备份是恢复手段，不做总量上限；keep_dirs 用于保护刚生成、尚在被使用的
    备份目录（如数据库迁移备份）。
    """
    directory = Path(backups_dir)
    if not directory.is_dir():
        logger.info("备份：目录不存在，跳过清理（%s）", directory)
        return []

    keep_resolved = [p for p in (_safe_resolve(item) for item in keep_dirs) if p is not None]
    candidates: list[tuple[Path, float, int]] = []
    for entry in _iter_regular_files(directory, "*", recursive=True):
        if entry.suffix not in (".sqlite", ".json"):
            continue
        resolved = _safe_resolve(entry)
        if resolved is None:
            continue
        if any(resolved.is_relative_to(base) for base in keep_resolved):
            continue
        try:
            stat = entry.stat()
        except OSError as exc:
            logger.warning("备份：读取文件状态失败 %s（%s），跳过", entry.name, exc)
            continue
        candidates.append((entry, stat.st_mtime, stat.st_size))

    deleted: list[Path] = []
    freed = 0
    if max_age_days > 0:
        cutoff = time.time() - float(max_age_days) * _SECONDS_PER_DAY
        for entry, mtime, _size in sorted(candidates, key=lambda item: item[1]):
            if mtime >= cutoff:
                continue
            freed_size = _try_delete_file(entry, directory, dry_run=dry_run, label="备份")
            if freed_size is None:
                continue
            deleted.append(entry)
            freed += freed_size

    logger.info(
        "备份：%s %d 个文件，%s %.2f MB（上限：年龄>%g天）",
        "预计清理" if dry_run else "清理",
        len(deleted),
        "预计释放" if dry_run else "释放",
        freed / MB,
        max_age_days if max_age_days > 0 else 0,
    )
    return deleted


def prune_stale_sidecars(
    root: Path, *, older_than_days: float = 1.0, dry_run: bool = False
) -> list[Path]:
    """清理根目录旧备份库的 `-shm/-wal` 垃圾（读取备份时 SQLite 产生）。

    只删满足全部条件的文件：名字形如 `spritelens.*.sqlite-shm/-wal`、
    对应 `.sqlite` 仍存在、sidecar mtime 早于阈值。主库
    `spritelens.sqlite-shm/-wal` 永不删，没有对应库的孤 sidecar 也不动。
    """
    directory = Path(root)
    if not directory.is_dir():
        logger.info("孤儿 sidecar：目录不存在，跳过清理（%s）", directory)
        return []

    now = time.time()
    cutoff = now - float(older_than_days) * _SECONDS_PER_DAY
    candidates: list[tuple[Path, float, int]] = []
    for pattern in ("spritelens.*.sqlite-shm", "spritelens.*.sqlite-wal"):
        for entry in _iter_regular_files(directory, pattern):
            if not entry.name.endswith(SIDECAR_SUFFIXES):
                continue
            # 去掉 -shm/-wal 还原库文件名（Path.suffix 是 .sqlite-shm，不能用它）
            if entry.name.endswith("-shm"):
                base_name = entry.name[: -len("-shm")]
            else:
                base_name = entry.name[: -len("-wal")]
            if not base_name.endswith(".sqlite"):
                continue
            if base_name == MAIN_DATABASE_NAME:
                continue  # 主库 sidecar 永不删
            database = directory / base_name
            try:
                if not database.is_file():
                    continue  # 没有对应库：不碰（不是本策略的清理对象）
                stat = entry.stat()
            except OSError as exc:
                logger.warning("孤儿 sidecar：读取文件状态失败 %s（%s），跳过", entry.name, exc)
                continue
            if stat.st_mtime >= cutoff:
                continue
            candidates.append((entry, stat.st_mtime, stat.st_size))

    deleted: list[Path] = []
    freed = 0
    for entry, _mtime, _size in sorted(candidates, key=lambda item: item[1]):
        freed_size = _try_delete_file(entry, directory, dry_run=dry_run, label="孤儿 sidecar")
        if freed_size is None:
            continue
        deleted.append(entry)
        freed += freed_size

    logger.info(
        "孤儿 sidecar：%s %d 个文件，%s %.2f MB（阈值：%g 天）",
        "预计清理" if dry_run else "清理",
        len(deleted),
        "预计释放" if dry_run else "释放",
        freed / MB,
        older_than_days,
    )
    return deleted


def eventlog_rollover_pruner(settings, log_dir: Path) -> Callable[[Path], None]:
    """构造跨天回调：在 worker 线程按当前配置清理旧分片，keep=新文件。

    回调异常由 EventLogWriter 兜底（warning），清理失败不影响日志写入；
    上限在跨天时重新读配置，用户改 config.json 后无需重启即可生效。
    """

    def _on_rollover(new_path: Path) -> None:
        limits = StorageLimits.from_settings(settings)
        prune_event_log(
            log_dir,
            max_age_days=limits.eventlog_max_age_days,
            max_total_bytes=limits.eventlog_max_bytes,
            keep=new_path,
            keep_newest=1,
        )

    return _on_rollover


def apply_storage_retention(
    settings,
    root: Path,
    *,
    recording_active: Path | Callable[[], Path | None] | None = None,
) -> RetentionReport:
    """启动门面：按配置清理一轮，返回删除明细。

    调用方负责兜底异常（app_context 只 warning，不阻断启动）；单文件删除
    失败已在底层消化。`recording_active` 可以是路径或返回路径的 callable，
    用于保护启动时仍被占用的录制文件。
    """
    limits = StorageLimits.from_settings(settings)
    root = Path(root)
    active = recording_active() if callable(recording_active) else recording_active

    sidecars = prune_stale_sidecars(root)
    eventlog_dir = root / "eventlog"
    today = eventlog_dir / f"eventlog_{time.strftime('%Y%m%d')}.jsonl"
    eventlog = prune_event_log(
        eventlog_dir,
        max_age_days=limits.eventlog_max_age_days,
        max_total_bytes=limits.eventlog_max_bytes,
        keep=today,
        keep_newest=1,
    )
    recordings = prune_recordings(
        root / "recordings",
        max_age_days=limits.recordings_max_age_days,
        max_total_bytes=limits.recordings_max_bytes,
        keep=active,
        keep_newest=1,
    )
    backups = prune_backups(root / "backups", max_age_days=limits.backups_max_age_days)
    report = RetentionReport(
        sidecars=tuple(sidecars),
        eventlog=tuple(eventlog),
        recordings=tuple(recordings),
        backups=tuple(backups),
    )
    logger.info("存储保留策略执行完成：共清理 %d 个文件", report.total_files)
    return report


__all__ = [
    "BACKUPS_MAX_AGE_DAYS",
    "EVENTLOG_MAX_AGE_DAYS",
    "EVENTLOG_MAX_MB",
    "EVENTLOG_PATTERN",
    "MB",
    "RECORDINGS_MAX_AGE_DAYS",
    "RECORDINGS_MAX_MB",
    "RECORDING_PATTERN",
    "RetentionReport",
    "StorageLimits",
    "apply_storage_retention",
    "eventlog_rollover_pruner",
    "prune_backups",
    "prune_event_log",
    "prune_recordings",
    "prune_stale_sidecars",
]
