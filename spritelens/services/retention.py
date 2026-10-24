"""记录数据保留策略：只保留最近 3 天、总量不超过 300MB 的 eventlog/recordings。

背景：`%LOCALAPPDATA%\\SpriteLens` 下的记录数据原先只增不减（实测 eventlog
单日 1.1GB、累计 2.0GB）。本模块负责在启动时、跨天时、以及当天分片滚动时
清理旧记录；只依赖标准库与 `spritelens.logs`，全部函数可注入目录，便于单测。

策略（用户口径：近 3 天、最大 300MB）：
- `eventlog/*.jsonl`（`eventlog_YYYYMMDD.jsonl` 与滚动分片
  `eventlog_YYYYMMDD_pNN.jsonl`）与 `recordings/capture_*.jsonl` 视为同一池
  的「记录数据」：先删 mtime 超过 `records_max_age_days`（默认 3 天）的文件，
  再按 mtime 从旧到新删到合计 ≤ `records_max_mb`（默认 300MB）。单个文件本身
  就超过上限时（升级前留下的大分片）从头部截断保留尾部，不整份删除。
  这样「超过上限立刻清旧的」在启动（重启即收敛到上限）与当天分片滚动（见
  event_logger 的 `max_part_bytes`）时都会触发，不必等到跨天。
- 正在写的文件（当天 eventlog 当前分片、正在录制的 capture 文件）永不删除，
  但计入总量：只有它们自身占满上限时才会超（单分片 64MB，正常不会发生）。
  启动清理默认不把当天分片当 keep——写入器还没打开它，超限可安全截断；若
  调用方已持有写入器（或另一实例在写），通过 `apply_storage_retention` 的
  `eventlog_active` 传入当前分片路径，该文件就只计入总量、不会被改动。
- `backups/*.sqlite|*.json`：只按年龄（`backups_max_age_days` 默认 30 天）删
  过期备份，`keep_dirs`（如刚生成的数据库迁移备份）整目录跳过；备份是恢复
  手段，不参与 300MB 记录池上限，宁可多留。
- 根目录孤儿 sidecar（`spritelens.*.sqlite-shm/-wal`，对应 `.sqlite` 仍在）：
  只清理主库之外的旧备份库 sidecar；主库 `spritelens.sqlite` 的 `-wal/-shm`
  永不删，没有对应库的孤 sidecar 也不动。
- 单文件删除失败（PermissionError/OSError，例如文件仍被运行中的进程占用）
  只记 warning 并继续处理其它文件，绝不向上抛出；启动清理的整体异常由
  `app_context` 兜底（只 warning，不阻断启动）。
- 只删目标目录内的普通文件：路径先 `resolve()` 再与目标目录做
  `is_relative_to` 校验，符号链接一律跳过，防目录穿越。
- `max_age_days <= 0` 或 `max_total_bytes <= 0` 关闭对应维度（只按另一维度）。

配置键（config.json，经 `SettingsRepository.get_int` 读取并 clamp；默认值
即用户口径，不需要手工配置）：
- `storage.records_max_age_days` 默认 3，[1, 365]
- `storage.records_max_mb`      默认 300，[16, 102400]
- `storage.backups_max_age_days` 默认 30，[3, 3650]
MB 换算按 1024*1024。

手工清理（一次性排查/回收）：`python tools/cleanup_data_root.py [--root DIR] [--apply]`，
默认 dry-run，`--apply` 才真正移动/删除。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Sequence

from spritelens.logs import get_logger

logger = get_logger("retention")

MB = 1024 * 1024
# 记录池：目录名 → 文件名模式；两者共享同一套年龄与总量上限
RECORD_DIRS: tuple[tuple[str, str], ...] = (
    ("eventlog", "eventlog_*.jsonl"),
    ("recordings", "capture_*.jsonl"),
)
SIDECAR_SUFFIXES = ("-shm", "-wal")
MAIN_DATABASE_NAME = "spritelens.sqlite"

# 默认上限（也是 config.json 缺键时的回退值，见模块 docstring 的键表）
RECORDS_MAX_AGE_DAYS = 3
RECORDS_MAX_MB = 300
BACKUPS_MAX_AGE_DAYS = 30

_SECONDS_PER_DAY = 86400.0


# -- 配置 ---------------------------------------------------------------
@dataclass(frozen=True)
class StorageLimits:
    """一次启动读取到的保留上限；字节数由配置的 MB 换算而来。"""

    records_max_age_days: int = RECORDS_MAX_AGE_DAYS
    records_max_bytes: int = RECORDS_MAX_MB * MB
    backups_max_age_days: int = BACKUPS_MAX_AGE_DAYS

    @classmethod
    def from_settings(cls, settings) -> "StorageLimits":
        """从 SettingsRepository 读取（缺键/非法值走默认值 + clamp，不抛）。"""
        return cls(
            records_max_age_days=settings.get_int(
                "storage.records_max_age_days", RECORDS_MAX_AGE_DAYS, lo=1, hi=365
            ),
            records_max_bytes=settings.get_int(
                "storage.records_max_mb", RECORDS_MAX_MB, lo=16, hi=102400
            )
            * MB,
            backups_max_age_days=settings.get_int(
                "storage.backups_max_age_days", BACKUPS_MAX_AGE_DAYS, lo=3, hi=3650
            ),
        )


@dataclass(frozen=True)
class RetentionReport:
    """一次保留策略执行的删除明细（供启动日志/测试断言使用）。"""

    sidecars: tuple[Path, ...] = ()
    records: tuple[Path, ...] = ()
    backups: tuple[Path, ...] = ()

    @property
    def total_files(self) -> int:
        return len(self.sidecars) + len(self.records) + len(self.backups)


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


def _is_keep(entry: Path, keep_resolved: Sequence[Path]) -> bool:
    """entry 是否是正在写的文件（解析后路径相同）。"""
    if not keep_resolved:
        return False
    resolved = _safe_resolve(entry)
    return resolved is not None and resolved in keep_resolved


def _trim_front(path: Path, keep_bytes: int, directory: Path) -> int | None:
    """把记录文件从头部截断到只剩最后 keep_bytes 字节（按行边界）。

    只在「单个文件本身就超过上限」时使用：整份删除会丢掉最近的数据，截断
    则保留文件尾部最近的记录。JSONL 每行独立，从头截断不会破坏剩余行。
    调用方必须保证该文件不是正在写的文件（写入方已切换走、句柄已关闭）。
    返回释放字节数；失败只 warning 并返回 None（原文件保持不变）。
    """
    try:
        size = path.stat().st_size
    except OSError as exc:
        logger.warning("记录数据：读取文件状态失败 %s（%s），跳过", path.name, exc)
        return None
    if keep_bytes >= size:
        return 0
    if keep_bytes <= 0:
        return _try_delete_file(path, directory, dry_run=False, label="记录数据")
    start = size - keep_bytes
    staging = path.with_name(path.name + ".trim-tmp")
    try:
        with path.open("rb") as source, staging.open("wb") as target:
            # 起点落在行中间时丢弃半行，保证剩余内容仍是完整 JSONL
            if start > 0:
                source.seek(start - 1)
                previous = source.read(1)
                source.seek(start)
                if previous != b"\n":
                    source.readline()
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                target.write(chunk)
        os.replace(staging, path)
    except OSError as exc:
        try:
            staging.unlink()
        except OSError:
            pass
        logger.warning("记录数据：截断失败 %s（%s），跳过", path.name, exc)
        return None
    try:
        remaining = path.stat().st_size
    except OSError:
        return None
    logger.info(
        "记录数据：%s 单文件超过上限，已从头部截断并保留最近 %.2f MB",
        path.name,
        remaining / MB,
    )
    return max(0, size - remaining)


def _note_freed(sink: list[int] | None, freed: int) -> None:
    """把单个文件的实际/预计释放字节记入 sink（供调用方汇总 dry-run 预计值）。"""
    if sink is not None:
        sink.append(freed)


# -- 记录池：年龄 + 总量 ---------------------------------------------------
def prune_records(
    root: Path,
    *,
    max_age_days: float,
    max_total_bytes: int,
    keep: Sequence[Path] = (),
    dry_run: bool = False,
    freed_sink: list[int] | None = None,
) -> list[Path]:
    """清理 eventlog 与 recordings 组成的记录池（先年龄、再合计总量）。

    keep 里的文件（正在写的分片/录制）永不删除，但计入总量，保证上限口径
    是「磁盘上的记录数据总量」；总量超限时按 mtime 从旧到新删。单个文件
    本身就超过上限时（例如升级前留下的大分片），从头部截断保留尾部，避免
    整份删除丢掉最近记录。

    返回被删除或截断的文件（keep 中从未被改动）；传入 `freed_sink` 时逐个
    追加释放字节数（截断时是「原大小 - 保留大小」，dry-run 为估计值），供
    调用方汇总，避免把被截断的文件按整份大小重复计入释放量。
    """
    root = Path(root)
    keep_resolved = [
        resolved for resolved in (_safe_resolve(item) for item in keep if item) if resolved
    ]
    candidates: list[tuple[Path, Path, float, int]] = []
    for sub, pattern in RECORD_DIRS:
        directory = root / sub
        if not directory.is_dir():
            logger.info("记录数据：目录不存在，跳过清理（%s）", directory)
            continue
        for entry in _iter_regular_files(directory, pattern):
            try:
                stat = entry.stat()
            except OSError as exc:
                logger.warning("记录数据：读取文件状态失败 %s（%s），跳过", entry.name, exc)
                continue
            candidates.append((entry, directory, stat.st_mtime, stat.st_size))

    deleted: list[Path] = []
    freed = 0
    now = time.time()
    failed: set[Path] = set()
    remaining: list[tuple[Path, Path, float, int]] = []

    # 第一遍：按 mtime 删过期分片；删除失败的仍计入占用，但不再重复尝试。
    if max_age_days > 0:
        cutoff = now - float(max_age_days) * _SECONDS_PER_DAY
        for entry, directory, mtime, size in candidates:
            if _is_keep(entry, keep_resolved):
                remaining.append((entry, directory, mtime, size))
                continue
            if mtime < cutoff:
                freed_size = _try_delete_file(
                    entry, directory, dry_run=dry_run, label="记录数据"
                )
                if freed_size is not None:
                    deleted.append(entry)
                    freed += freed_size
                    _note_freed(freed_sink, freed_size)
                    continue
                failed.add(entry)
            remaining.append((entry, directory, mtime, size))
    else:
        remaining = list(candidates)

    # 第二遍：先按 mtime 从旧到新整份删除，但留下最大的那个文件——它多半是
    # 升级前的大分片，整份删会丢最近记录，改为从头部截断保留尾部。
    if max_total_bytes > 0 and remaining:
        total = sum(size for _entry, _directory, _mtime, size in remaining)
        prunable = [
            item
            for item in sorted(remaining, key=lambda item: item[2])
            if item[0] not in failed and not _is_keep(item[0], keep_resolved)
        ]
        kept_for_trim: tuple[Path, Path, float, int] | None = None
        if prunable:
            largest = max(prunable, key=lambda item: item[3])
            # 只有「单个文件本身就超过上限」时才截断：能整份纳入上限的文件
            # 直接按 mtime 删除即可，不必改写文件内容。
            if largest[3] > max_total_bytes:
                kept_for_trim = largest
                prunable = [item for item in prunable if item is not kept_for_trim]
        for entry, directory, _mtime, _size in prunable:
            if total <= max_total_bytes:
                break
            freed_size = _try_delete_file(entry, directory, dry_run=dry_run, label="记录数据")
            if freed_size is None:
                failed.add(entry)
                continue
            deleted.append(entry)
            freed += freed_size
            _note_freed(freed_sink, freed_size)
            total -= freed_size
        if total > max_total_bytes and kept_for_trim is not None:
            entry, directory, _mtime, size = kept_for_trim
            allowance = max(0, max_total_bytes - (total - size))
            freed_size = (
                size - allowance if dry_run else _trim_front(entry, allowance, directory)
            )
            if freed_size is not None:
                deleted.append(entry)
                freed += freed_size
                _note_freed(freed_sink, freed_size)
                total -= freed_size
        if total > max_total_bytes:
            logger.info(
                "记录数据：清理后仍有 %.2f MB（上限 %.2f MB），超出部分来自正在写的"
                "文件或无法修改的文件，等分片滚动/应用退出后继续收敛",
                total / MB,
                max_total_bytes / MB,
            )

    logger.info(
        "记录数据：%s %d 个文件，%s %.2f MB（上限：%s）",
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


# -- 备份：只按年龄 -------------------------------------------------------
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


# -- 组合入口 ------------------------------------------------------------
def eventlog_rollover_pruner(settings, root: Path) -> Callable[[Path], None]:
    """构造分片切换回调：在 worker 线程按当前配置清理旧记录，keep=新分片。

    当天 eventlog 每写满一个分片、以及跨天切文件时都会调用；回调异常由
    EventLogWriter 兜底（warning），清理失败不影响日志写入。上限在每次
    切换时重读配置，用户改 config.json 后无需重启即可生效。
    """

    def _on_rollover(new_path: Path) -> None:
        limits = StorageLimits.from_settings(settings)
        prune_records(
            root,
            max_age_days=limits.records_max_age_days,
            max_total_bytes=limits.records_max_bytes,
            keep=(new_path,),
        )

    return _on_rollover


def _resolve_active(value) -> Path | None:
    """eventlog_active/recording_active 允许传路径或返回路径的 callable。"""
    resolved = value() if callable(value) else value
    return Path(resolved) if resolved is not None else None


def apply_storage_retention(
    settings,
    root: Path,
    *,
    recording_active: Path | Callable[[], Path | None] | None = None,
    eventlog_active: Path | Callable[[], Path | None] | None = None,
) -> RetentionReport:
    """启动门面：按配置清理一轮，返回删除明细。

    调用方负责兜底异常（app_context 只 warning，不阻断启动）；单文件删除
    失败已在底层消化。`recording_active`/`eventlog_active` 可以是路径或返回
    路径的 callable，用于保护启动时仍被占用的文件。

    默认不保护当天 eventlog 分片：正常启动顺序下（保留策略早于任何写入）
    写入器还没打开文件，超限时按总量截断，重启即收敛到上限；若调用方已
    持有写入器或另一实例正在写，应传 `eventlog_active=writer.current_path`，
    此时该文件按 keep 处理（截断/删除都会被跳过）。
    """
    limits = StorageLimits.from_settings(settings)
    root = Path(root)
    active_eventlog = _resolve_active(eventlog_active)
    active_recording = _resolve_active(recording_active)
    keep = [path for path in (active_eventlog, active_recording) if path is not None]

    sidecars = prune_stale_sidecars(root)
    records = prune_records(
        root,
        max_age_days=limits.records_max_age_days,
        max_total_bytes=limits.records_max_bytes,
        keep=keep,
    )
    backups = prune_backups(root / "backups", max_age_days=limits.backups_max_age_days)
    report = RetentionReport(
        sidecars=tuple(sidecars),
        records=tuple(records),
        backups=tuple(backups),
    )
    logger.info("存储保留策略执行完成：共清理 %d 个文件", report.total_files)
    return report


__all__ = [
    "BACKUPS_MAX_AGE_DAYS",
    "MB",
    "RECORDS_MAX_AGE_DAYS",
    "RECORDS_MAX_MB",
    "RECORD_DIRS",
    "RetentionReport",
    "StorageLimits",
    "apply_storage_retention",
    "eventlog_rollover_pruner",
    "prune_backups",
    "prune_records",
    "prune_stale_sidecars",
]
