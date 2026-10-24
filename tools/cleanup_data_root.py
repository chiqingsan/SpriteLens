"""一次性清理用户数据根目录（默认 dry-run，`--apply` 才实际执行）。

用法:
    python tools/cleanup_data_root.py [--root DIR] [--apply]

步骤（顺序固定：先清垃圾，再按保留上限滚动，最后统计）:
1. 根目录孤儿 sidecar：`spritelens.*.sqlite-shm/-wal`（对应 `.sqlite` 仍存在、
   mtime 超过 1 天）。主库 `spritelens.sqlite` 的 `-wal/-shm` 永不删。
2. 根目录过期数据库文件：`spritelens.incompatible-*.sqlite` 与
   `spritelens.empty-before-recovery-*.sqlite`（含其 `-shm/-wal`）**移动**到
   `backups/database-recovery-YYYYMMDD/`，不删除，保留可回溯。
3. 按默认保留上限清理 `eventlog/`、`recordings/`、`backups/`（与启动清理
   复用 `spritelens/services/retention.py` 同一套函数与默认值）。
4. 打印 Before/After 目录总量与每类释放量。

保护名单（任何模式都不动）：`spritelens.sqlite`、`spritelens.sqlite-wal`、
`spritelens.sqlite-shm`、`config.json`、`keys/` 目录及其内容。桌面应用正在
运行、文件被进程占用时，个别删除/移动失败只打印警告并继续。

处置侧注意：本工具不会停止进程，也不碰主库；`--apply` 会对
`spritelens.incompatible-*.sqlite` 做移动而非删除，误操作可原路移回。
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spritelens.paths import data_root
from spritelens.services.retention import (
    MB,
    StorageLimits,
    prune_backups,
    prune_event_log,
    prune_recordings,
    prune_stale_sidecars,
)

SIDECARS = ("-shm", "-wal")
PROTECTED_NAMES = frozenset(
    {"spritelens.sqlite", "spritelens.sqlite-wal", "spritelens.sqlite-shm", "config.json"}
)
RECOVERY_PATTERNS = (
    "spritelens.incompatible-*.sqlite",
    "spritelens.empty-before-recovery-*.sqlite",
)
_MAX_LIST_LINES = 12


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _sum_size(paths) -> int:
    return sum(_file_size(path) for path in paths)


def _dir_stats(root: Path) -> tuple[int, int]:
    """目录总量与文件数（元数据遍历，不读内容；坏条目跳过）。"""
    total = 0
    files = 0
    for entry in root.rglob("*"):
        try:
            if entry.is_symlink() or not entry.is_file():
                continue
            total += entry.stat().st_size
            files += 1
        except OSError:
            continue
    return total, files


def _print_changes(changes) -> None:
    for path in changes[: _MAX_LIST_LINES]:
        print(f"     - {path.name}")
    if len(changes) > _MAX_LIST_LINES:
        print(f"     ... 其余 {len(changes) - _MAX_LIST_LINES} 个省略")


def plan_database_recovery_moves(
    root: Path, *, skip: frozenset[Path] | set[Path] = frozenset()
) -> list[tuple[Path, Path]]:
    """规划把根目录过期数据库（含 sidecar）移入 backups 的路径对。"""
    root = Path(root)
    destination = root / "backups" / f"database-recovery-{time.strftime('%Y%m%d')}"
    planned: list[tuple[Path, Path]] = []
    seen: set[Path] = set()
    for pattern in RECOVERY_PATTERNS:
        for database in sorted(root.glob(pattern)):
            try:
                if database.is_symlink() or not database.is_file():
                    continue
            except OSError:
                continue
            if database.name in PROTECTED_NAMES:
                continue
            candidates = [database, *(database.with_name(database.name + suffix) for suffix in SIDECARS)]
            for candidate in candidates:
                if candidate in seen or candidate in skip:
                    continue
                try:
                    if candidate.is_symlink() or not candidate.is_file():
                        continue
                except OSError:
                    continue
                seen.add(candidate)
                planned.append((candidate, destination / candidate.name))
    return planned


def apply_moves(moves) -> list[Path]:
    """执行移动；单个失败打印警告并继续，返回已移动的源路径。"""
    moved: list[Path] = []
    for source, destination in moves:
        if source.name in PROTECTED_NAMES:
            print(f"     [跳过] 保护名单文件：{source}")
            continue
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                print(f"     [跳过] 目标已存在：{destination}")
                continue
            shutil.move(str(source), str(destination))
        except OSError as exc:
            print(f"     [失败] 移动 {source.name} -> {destination}: {exc}")
            continue
        moved.append(source)
    return moved


def _run_category(
    title: str,
    *,
    plan,
    execute,
    apply: bool,
    verb: str = "清理",
) -> tuple[list[Path], int]:
    """打印一类的计划/结果，返回（实际操作对象，释放字节数）。"""
    print(title)
    targets = plan()
    sizes = {path: _file_size(path) for path in targets}
    estimated = sum(sizes.values())
    if not targets:
        print("     无")
        return [], 0
    _print_changes(targets)
    if not apply:
        print(f"     预计{verb} {len(targets)} 个 / {estimated / MB:.2f} MB")
        return targets, estimated
    executed = execute()
    freed = sum(sizes.get(path, 0) for path in executed if not path.exists())
    print(f"     已{verb} {len(executed)} 个 / {freed / MB:.2f} MB")
    return executed, freed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="一次性清理 SpriteLens 用户数据根目录（默认 dry-run）"
    )
    parser.add_argument("--root", default=None, help="数据根目录，默认 %%LOCALAPPDATA%%\\SpriteLens")
    parser.add_argument("--apply", action="store_true", help="实际执行移动/删除（默认只打印）")
    args = parser.parse_args(argv)

    root = Path(args.root).expanduser().resolve() if args.root else data_root().resolve()
    if not root.is_dir():
        print(f"数据根目录不存在：{root}")
        return 2

    print(f"SpriteLens 数据根目录：{root}")
    print("模式：" + ("APPLY（实际执行）" if args.apply else "DRY-RUN（只打印，不改文件）"))
    print("保护名单（永不动）：spritelens.sqlite[.sqlite-wal/-shm]、config.json、keys/")
    print()

    limits = StorageLimits()  # 与启动清理同一套默认值
    before_bytes, before_files = _dir_stats(root)
    print(f"Before：{before_bytes / MB:.2f} MB / {before_files} 个文件")
    print()

    # 1) 孤儿 sidecar（先规划，步骤 2 据此跳过将被删除的 sidecar）
    sidecar_targets, sidecar_freed = _run_category(
        "1) 根目录旧备份库孤儿 sidecar（spritelens.*.sqlite-shm/-wal，>1 天）",
        plan=lambda: prune_stale_sidecars(root, dry_run=True),
        execute=lambda: prune_stale_sidecars(root, dry_run=False),
        apply=args.apply,
    )

    # 2) 过期数据库文件 -> backups/database-recovery-YYYYMMDD/
    destination = root / "backups" / f"database-recovery-{time.strftime('%Y%m%d')}"
    moves = plan_database_recovery_moves(root, skip=set(sidecar_targets))
    move_bytes = _sum_size(source for source, _destination in moves)
    print(f"2) 过期数据库文件 -> {destination.relative_to(root)}（移动，不删除）")
    if not moves:
        print("     无")
        move_freed = 0
    else:
        _print_changes([source for source, _destination in moves])
        if args.apply:
            moved = apply_moves(moves)
            move_freed = _sum_size(moved)
            print(f"     已移动 {len(moved)} 个 / {move_freed / MB:.2f} MB（保留在 backups/，总量不减）")
        else:
            move_freed = move_bytes
            print(f"     预计移动 {len(moves)} 个 / {move_bytes / MB:.2f} MB（保留在 backups/，总量不减）")
    print()

    # 3) 按保留上限清理记录数据（与启动清理同一套函数）
    eventlog_dir = root / "eventlog"
    today_file = eventlog_dir / f"eventlog_{time.strftime('%Y%m%d')}.jsonl"
    _, eventlog_freed = _run_category(
        f"3a) eventlog/ 超过 {limits.eventlog_max_age_days} 天或总量 > "
        f"{limits.eventlog_max_bytes / MB:.0f}MB 的旧分片（当天文件保留）",
        plan=lambda: prune_event_log(
            eventlog_dir,
            max_age_days=limits.eventlog_max_age_days,
            max_total_bytes=limits.eventlog_max_bytes,
            keep=today_file,
            keep_newest=1,
            dry_run=True,
        ),
        execute=lambda: prune_event_log(
            eventlog_dir,
            max_age_days=limits.eventlog_max_age_days,
            max_total_bytes=limits.eventlog_max_bytes,
            keep=today_file,
            keep_newest=1,
            dry_run=False,
        ),
        apply=args.apply,
    )
    _, recordings_freed = _run_category(
        f"3b) recordings/ 超过 {limits.recordings_max_age_days} 天或总量 > "
        f"{limits.recordings_max_bytes / MB:.0f}MB 的旧录制",
        plan=lambda: prune_recordings(
            root / "recordings",
            max_age_days=limits.recordings_max_age_days,
            max_total_bytes=limits.recordings_max_bytes,
            keep_newest=1,
            dry_run=True,
        ),
        execute=lambda: prune_recordings(
            root / "recordings",
            max_age_days=limits.recordings_max_age_days,
            max_total_bytes=limits.recordings_max_bytes,
            keep_newest=1,
            dry_run=False,
        ),
        apply=args.apply,
    )
    _, backups_freed = _run_category(
        f"3c) backups/ 超过 {limits.backups_max_age_days} 天的旧备份",
        plan=lambda: prune_backups(
            root / "backups", max_age_days=limits.backups_max_age_days, dry_run=True
        ),
        execute=lambda: prune_backups(
            root / "backups", max_age_days=limits.backups_max_age_days, dry_run=False
        ),
        apply=args.apply,
    )
    print()

    # 4) 汇总
    after_bytes, after_files = _dir_stats(root)
    freed_total = sidecar_freed + eventlog_freed + recordings_freed + backups_freed
    print("汇总")
    print(f"  Before：{before_bytes / MB:.2f} MB / {before_files} 个文件")
    if args.apply:
        print(f"  After ：{after_bytes / MB:.2f} MB / {after_files} 个文件")
    else:
        estimated_after = max(0, before_bytes - freed_total)
        print(f"  After ：约 {estimated_after / MB:.2f} MB（dry-run 预计值，未改文件）")
    print(f"  孤儿 sidecar：{sidecar_freed / MB:.2f} MB")
    print(f"  eventlog    ：{eventlog_freed / MB:.2f} MB")
    print(f"  recordings  ：{recordings_freed / MB:.2f} MB")
    print(f"  backups     ：{backups_freed / MB:.2f} MB")
    print(f"  释放合计    ：{freed_total / MB:.2f} MB")
    if moves:
        print(
            f"  过期数据库  ：{len(moves)} 个 / {move_bytes / MB:.2f} MB"
            + ("（已移入 backups，可回溯）" if args.apply else "（预计移入 backups，可回溯）")
        )
    if not args.apply:
        print("  提示：以上为 dry-run 预计结果，确认后加 --apply 执行。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
