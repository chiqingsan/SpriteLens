"""记录数据保留策略测试：3 天/300MB 记录池、分片滚动、上限清理、失败隔离、清理工具。

不联网、不依赖真实用户目录：全部目录由 tempfile 创建，mtime 用 os.utime 造旧。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from spritelens.repositories.settings import SettingsRepository
from spritelens.services import retention
from spritelens.services.event_logger import EventLogWriter
from spritelens.services.retention import (
    StorageLimits,
    apply_storage_retention,
    prune_backups,
    prune_records,
    prune_stale_sidecars,
)
from spritelens.events import PacketEvent

_TOOL = Path(__file__).resolve().parent.parent / "tools" / "cleanup_data_root.py"


def _write(path: Path, *, size: int = 16, age_days: float = 0.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    if age_days:
        stamp = time.time() - age_days * 86400.0
        os.utime(path, (stamp, stamp))
    return path


def _event() -> PacketEvent:
    return PacketEvent(
        ts=1700000000.0,
        session_id="10.0.0.1:1000",
        direction="s2c",
        opcode=0x134A,
        opcode_name="op_0x134A",
        payload_len=8,
        decoded=[{"no": 1, "name": "gid", "type": "uint32", "value": "1", "raw": 1}],
    )


class _RootTestCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)


class RecordsRetentionTest(_RootTestCase):
    """eventlog 与 recordings 共享同一套年龄 + 总量上限。"""

    def setUp(self) -> None:
        super().setUp()
        self.eventlog = self.root / "eventlog"
        self.recordings = self.root / "recordings"
        self.eventlog.mkdir()
        self.recordings.mkdir()

    def test_prune_by_age_removes_only_expired(self):
        old = _write(self.eventlog / "eventlog_20200101.jsonl", age_days=10)
        fresh = _write(self.eventlog / "eventlog_20200102.jsonl", age_days=1)
        deleted = prune_records(self.root, max_age_days=3, max_total_bytes=0)
        self.assertEqual(deleted, [old])
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())

    def test_old_recording_is_pruned_by_age_too(self):
        old = _write(self.recordings / "capture_20200101_000000.jsonl", age_days=10)
        fresh = _write(self.recordings / "capture_20200102_000000.jsonl", age_days=1)
        deleted = prune_records(self.root, max_age_days=3, max_total_bytes=0)
        self.assertEqual(deleted, [old])
        self.assertTrue(fresh.exists())

    def test_total_cap_deletes_oldest_across_both_directories(self):
        oldest_log = _write(self.eventlog / "eventlog_20200101.jsonl", size=100, age_days=2)
        middle_recording = _write(
            self.recordings / "capture_20200102_000000.jsonl", size=100, age_days=1
        )
        newest_log = _write(self.eventlog / "eventlog_20200103.jsonl", size=100, age_days=0)
        deleted = prune_records(self.root, max_age_days=0, max_total_bytes=150)
        self.assertEqual(deleted, [oldest_log, middle_recording])
        self.assertFalse(oldest_log.exists())
        self.assertFalse(middle_recording.exists())
        self.assertTrue(newest_log.exists())

    def test_keep_file_counts_toward_total_but_is_never_removed(self):
        keep = _write(self.eventlog / "eventlog_20200101.jsonl", size=100, age_days=30)
        other = _write(self.eventlog / "eventlog_20200102.jsonl", size=100, age_days=1)
        deleted = prune_records(
            self.root, max_age_days=3, max_total_bytes=150, keep=(keep,)
        )
        self.assertEqual(deleted, [other])
        self.assertTrue(keep.exists(), "keep（正在写的文件）永不被删")
        self.assertFalse(other.exists(), "keep 计入总量后仍需把其它文件清到上限内")
        self.assertLessEqual(keep.stat().st_size, 150)

    def test_keep_only_file_over_cap_is_reported_but_kept(self):
        keep = _write(self.eventlog / "eventlog_20200101.jsonl", size=400)
        deleted = prune_records(self.root, max_age_days=0, max_total_bytes=300, keep=(keep,))
        self.assertEqual(deleted, [])
        self.assertTrue(keep.exists(), "只剩正在写的文件时不能为了上限删它")

    def test_zero_limits_disable_both_dimensions(self):
        old = _write(self.eventlog / "eventlog_20200101.jsonl", age_days=100)
        self.assertEqual(prune_records(self.root, max_age_days=0, max_total_bytes=0), [])
        self.assertTrue(old.exists())

    def test_missing_directories_are_noop(self):
        self.assertEqual(
            prune_records(self.root / "nope", max_age_days=3, max_total_bytes=0), []
        )

    def test_only_matching_files_are_touched(self):
        match = _write(self.eventlog / "eventlog_20200101.jsonl", age_days=10)
        other_jsonl = _write(self.eventlog / "capture_20200101.jsonl", age_days=10)
        other_txt = _write(self.eventlog / "eventlog_20200101.txt", age_days=10)
        deleted = prune_records(self.root, max_age_days=3, max_total_bytes=0)
        self.assertEqual(deleted, [match])
        self.assertTrue(other_jsonl.exists())
        self.assertTrue(other_txt.exists())

    def test_directory_named_like_shard_is_skipped(self):
        fake = self.eventlog / "eventlog_20200102.jsonl"
        fake.mkdir()
        old = _write(self.eventlog / "eventlog_20200101.jsonl", age_days=10)
        deleted = prune_records(self.root, max_age_days=3, max_total_bytes=0)
        self.assertEqual(deleted, [old])
        self.assertTrue(fake.is_dir())

    def test_delete_failure_is_isolated_and_does_not_raise(self):
        locked = _write(self.eventlog / "eventlog_20200101.jsonl", age_days=10)
        other = _write(self.eventlog / "eventlog_20200102.jsonl", age_days=10)
        real_unlink = Path.unlink

        def flaky(path, *args, **kwargs):
            if path.name == locked.name:
                raise PermissionError("locked by running app")
            return real_unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", flaky):
            with self.assertLogs("spritelens.retention", level="WARNING"):
                deleted = prune_records(self.root, max_age_days=3, max_total_bytes=0)
        self.assertEqual(deleted, [other])
        self.assertTrue(locked.exists(), "删除失败的文件不能被报告为已删除")
        self.assertFalse(other.exists(), "单文件失败不能挡住其它文件")

    def test_dry_run_reports_targets_without_deleting(self):
        old = _write(self.eventlog / "eventlog_20200101.jsonl", age_days=10)
        deleted = prune_records(
            self.root, max_age_days=3, max_total_bytes=0, dry_run=True
        )
        self.assertEqual(deleted, [old])
        self.assertTrue(old.exists(), "dry-run 不得改文件")

    def _lines(self, path: Path, count: int = 100) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"".join(f"line{i:04d}\n".encode() for i in range(count)))
        return path

    def test_single_oversized_file_is_trimmed_to_keep_recent_tail(self):
        """升级前留下的大分片超过上限时，整份删除会丢最近记录，应截断保留尾部。"""
        shard = self._lines(self.eventlog / "eventlog_20200101.jsonl")  # 900 字节
        deleted = prune_records(self.root, max_age_days=0, max_total_bytes=450)
        self.assertEqual(deleted, [shard])
        self.assertTrue(shard.exists())
        self.assertEqual(shard.stat().st_size, 450)
        self.assertEqual(
            shard.read_bytes().splitlines()[0], b"line0050", "保留的是最近的完整行"
        )

    def test_freed_sink_counts_trimmed_bytes_not_full_size(self):
        """截断释放量是「原大小 - 保留大小」，不能按整份文件大小重复计入。"""
        shard = self._lines(self.eventlog / "eventlog_20200101.jsonl")  # 900 字节
        sink: list[int] = []
        deleted = prune_records(
            self.root,
            max_age_days=0,
            max_total_bytes=450,
            dry_run=True,
            freed_sink=sink,
        )
        self.assertEqual(deleted, [shard])
        self.assertEqual(sink, [450])

    def test_trim_dry_run_keeps_file_untouched(self):
        shard = self._lines(self.eventlog / "eventlog_20200101.jsonl")
        deleted = prune_records(
            self.root, max_age_days=0, max_total_bytes=450, dry_run=True
        )
        self.assertEqual(deleted, [shard])
        self.assertEqual(shard.stat().st_size, 900, "dry-run 不得截断文件")

    def test_trim_failure_keeps_original_file(self):
        shard = self._lines(self.eventlog / "eventlog_20200101.jsonl")
        with patch.object(retention.os, "replace", side_effect=OSError("locked")):
            with self.assertLogs("spritelens.retention", level="WARNING"):
                deleted = prune_records(self.root, max_age_days=0, max_total_bytes=450)
        self.assertEqual(deleted, [])
        self.assertEqual(shard.stat().st_size, 900, "截断失败不得损坏原文件")
        self.assertFalse(shard.with_name(shard.name + ".trim-tmp").exists())

    def test_old_files_are_deleted_before_trimming_the_big_one(self):
        old = _write(self.eventlog / "eventlog_20200101.jsonl", size=200, age_days=2)
        shard = self._lines(self.eventlog / "eventlog_20200102.jsonl", 100)  # 900 字节
        deleted = prune_records(self.root, max_age_days=0, max_total_bytes=603)
        self.assertEqual(deleted, [old, shard])
        self.assertFalse(old.exists())
        self.assertEqual(shard.stat().st_size, 603, "预算按「上限 - 其它文件」计算")
        self.assertTrue(shard.read_bytes().startswith(b"line0033"))


class BackupsRetentionTest(_RootTestCase):
    def test_prune_backups_only_expired_and_skip_keep_dirs(self):
        backups = self.root / "backups"
        old_sqlite = _write(backups / "egg-fix-20200101-000000.sqlite", age_days=40)
        old_json = _write(backups / "manifest-20200101.json", age_days=40)
        fresh = _write(backups / "recent.sqlite", age_days=5)
        note = _write(backups / "readme.txt", age_days=400)
        keep_dir = backups / "partner-mark-backfill-20200101"
        kept = _write(keep_dir / "db.sqlite", age_days=400)
        nested_old = _write(backups / "nested" / "old.sqlite", age_days=40)

        deleted = prune_backups(backups, max_age_days=30, keep_dirs=(keep_dir,))
        self.assertEqual(set(deleted), {old_sqlite, old_json, nested_old})
        self.assertFalse(old_sqlite.exists())
        self.assertFalse(old_json.exists())
        self.assertFalse(nested_old.exists())
        self.assertTrue(fresh.exists())
        self.assertTrue(note.exists(), "非 .sqlite/.json 备份文件不处理")
        self.assertTrue(kept.exists(), "keep_dirs 内文件必须跳过")

    def test_missing_backups_directory_is_noop(self):
        self.assertEqual(prune_backups(self.root / "nope", max_age_days=30), [])


class SidecarRetentionTest(_RootTestCase):
    def test_only_stale_orphan_sidecars_are_removed(self):
        main_db = _write(self.root / "spritelens.sqlite", age_days=0)
        main_wal = _write(self.root / "spritelens.sqlite-wal", age_days=2)
        main_shm = _write(self.root / "spritelens.sqlite-shm", age_days=2)

        old_db = _write(self.root / "spritelens.incompatible-1782.sqlite", age_days=2)
        old_shm = _write(self.root / "spritelens.incompatible-1782.sqlite-shm", age_days=2)
        old_wal = _write(self.root / "spritelens.incompatible-1782.sqlite-wal", age_days=2)

        orphan = _write(self.root / "spritelens.orphan.sqlite-shm", age_days=2)

        fresh_db = _write(self.root / "spritelens.incompatible-1783.sqlite", age_days=0)
        fresh_shm = _write(self.root / "spritelens.incompatible-1783.sqlite-shm", age_days=0)

        nested = _write(
            self.root / "backups" / "spritelens.incompatible-9.sqlite-shm", age_days=2
        )

        deleted = prune_stale_sidecars(self.root)
        self.assertEqual(set(deleted), {old_shm, old_wal})
        self.assertTrue(main_db.exists())
        self.assertTrue(main_wal.exists(), "主库 -wal 永不删")
        self.assertTrue(main_shm.exists(), "主库 -shm 永不删")
        self.assertTrue(old_db.exists(), "只删 sidecar，不动对应备份库")
        self.assertTrue(orphan.exists(), "没有对应 .sqlite 的孤儿 sidecar 不动")
        self.assertTrue(fresh_db.exists())
        self.assertTrue(fresh_shm.exists(), "未过阈值的新 sidecar 不动")
        self.assertTrue(nested.exists(), "只处理根目录，不递归 backups/")


class TraversalGuardTest(_RootTestCase):
    def test_refuses_to_delete_file_outside_target_directory(self):
        inside = self.root / "eventlog"
        inside.mkdir()
        outside = _write(self.root / "outside.jsonl")
        with self.assertLogs("spritelens.retention", level="WARNING"):
            self.assertFalse(
                retention._try_delete_file(outside, inside, dry_run=False, label="测试")
            )
        self.assertTrue(outside.exists())

    def test_refuses_parent_relative_path_escape(self):
        inside = self.root / "eventlog"
        inside.mkdir()
        outside = _write(self.root / "outside.jsonl")
        escaped = inside / ".." / "outside.jsonl"
        with self.assertLogs("spritelens.retention", level="WARNING"):
            self.assertFalse(
                retention._try_delete_file(escaped, inside, dry_run=False, label="测试")
            )
        self.assertTrue(outside.exists(), "构造 ../ 路径不得删到目标目录外")

    def test_symlinks_are_not_followed(self):
        inside = self.root / "eventlog"
        inside.mkdir()
        target = _write(inside / "eventlog_20200101.jsonl", size=64, age_days=30)
        real_is_symlink = Path.is_symlink

        def fake_is_symlink(self):
            return self == target or real_is_symlink(self)

        # 直接构造符号链接需要 Windows 开发者模式/管理员权限；用 patch 断言
        # “枚举到符号链接即跳过、不跟随删除”这条防线本身。
        with patch.object(Path, "is_symlink", fake_is_symlink):
            deleted = prune_records(self.root, max_age_days=3, max_total_bytes=0)
        self.assertEqual(deleted, [])
        self.assertTrue(target.exists(), "符号链接不得被跟随删除")


class StorageLimitsTest(_RootTestCase):
    def _settings(self, payload: dict | None = None) -> SettingsRepository:
        path = self.root / "config.json"
        path.write_text(json.dumps(payload or {}), encoding="utf-8")
        return SettingsRepository(path)

    def test_defaults_are_three_days_and_300mb(self):
        limits = StorageLimits.from_settings(self._settings())
        self.assertEqual(limits.records_max_age_days, 3)
        self.assertEqual(limits.records_max_bytes, 300 * retention.MB)
        self.assertEqual(limits.backups_max_age_days, 30)

    def test_clamp(self):
        clamped = StorageLimits.from_settings(
            self._settings(
                {
                    "storage.records_max_age_days": 0,
                    "storage.records_max_mb": 1,
                    "storage.backups_max_age_days": 99999,
                }
            )
        )
        self.assertEqual(clamped.records_max_age_days, 1, "低于下限要 clamp 到 1")
        self.assertEqual(clamped.records_max_bytes, 16 * retention.MB)
        self.assertEqual(clamped.backups_max_age_days, 3650, "高于上限 clamp 到 3650")

    def test_apply_storage_retention_uses_defaults(self):
        settings = self._settings()
        old_eventlog = _write(
            self.root / "eventlog" / "eventlog_20200101.jsonl", age_days=10
        )
        today_file = self.root / "eventlog" / f"eventlog_{time.strftime('%Y%m%d')}.jsonl"
        _write(today_file, age_days=0)
        old_recording = _write(
            self.root / "recordings" / "capture_20200101_000000.jsonl", age_days=10
        )
        fresh_recording = _write(
            self.root / "recordings" / "capture_20200102_000000.jsonl", age_days=2
        )
        old_backup = _write(self.root / "backups" / "old.sqlite", age_days=40)
        fresh_backup = _write(self.root / "backups" / "fresh.sqlite", age_days=5)
        incompatible = _write(
            self.root / "spritelens.incompatible-1782.sqlite", age_days=2
        )
        stale_sidecar = _write(
            self.root / "spritelens.incompatible-1782.sqlite-shm", age_days=2
        )
        main_db = _write(self.root / "spritelens.sqlite")
        main_wal = _write(self.root / "spritelens.sqlite-wal", age_days=2)

        report = apply_storage_retention(settings, self.root)

        self.assertEqual(report.records, (old_eventlog, old_recording))
        self.assertEqual(report.backups, (old_backup,))
        self.assertEqual(report.sidecars, (stale_sidecar,))
        self.assertEqual(report.total_files, 4)
        self.assertFalse(old_eventlog.exists())
        self.assertTrue(today_file.exists(), "当天 eventlog 文件保留")
        self.assertFalse(old_recording.exists())
        self.assertTrue(fresh_recording.exists(), "未过期录制保留")
        self.assertFalse(old_backup.exists())
        self.assertTrue(fresh_backup.exists(), "未过期备份保留")
        self.assertFalse(stale_sidecar.exists())
        self.assertTrue(incompatible.exists(), "清理只删 sidecar，不动备份库")
        self.assertTrue(main_db.exists())
        self.assertTrue(main_wal.exists())

    def test_settings_override_and_active_recording_keep(self):
        old_eventlog = _write(
            self.root / "eventlog" / "eventlog_20200101.jsonl", age_days=10
        )
        active = _write(
            self.root / "recordings" / "capture_20200101_000000.jsonl", age_days=40
        )
        settings = self._settings({"storage.records_max_age_days": 30})
        report = apply_storage_retention(settings, self.root, recording_active=active)
        self.assertEqual(report.records, (), "配置放宽到 30 天后 10 天分片保留")
        self.assertTrue(old_eventlog.exists())
        self.assertTrue(active.exists(), "正在录制文件不删")

        clamped = self._settings({"storage.records_max_age_days": 0})
        report = apply_storage_retention(clamped, self.root)
        self.assertIn(old_eventlog, report.records, "0 clamp 到 1 天后可删")
        self.assertFalse(old_eventlog.exists())

    def test_startup_trims_oversized_today_file(self):
        """重启后当天分片超限也要收敛：启动清理不默认保护当天文件。"""
        day = time.strftime("%Y%m%d")
        today = self.root / "eventlog" / f"eventlog_{day}.jsonl"
        line = b'{"opcode": "0x0000"}\n'
        today.parent.mkdir(parents=True, exist_ok=True)
        today.write_bytes(line * (17 * retention.MB // len(line) + 1))

        report = apply_storage_retention(
            self._settings({"storage.records_max_mb": 16}), self.root
        )

        self.assertEqual(report.records, (today,))
        size = today.stat().st_size
        self.assertLessEqual(size, 16 * retention.MB, "超限当天分片应截断到上限")
        self.assertGreater(size, 16 * retention.MB - 2 * len(line))


class EventLogRolloverTest(_RootTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.dir = self.root / "eventlog"

    def test_day_rollover_callback_receives_new_day_file(self):
        calls: list[Path] = []
        writer = EventLogWriter(self.dir, on_rollover=calls.append, max_part_bytes=0)
        self.addCleanup(writer.close)
        writer.handle_packet(_event())
        writer.flush()
        # 模拟“昨天写的文件仍在，今天已跨天”：改 _day 让下一次写触发切换
        writer._day = "19990101"
        writer.handle_packet(_event())
        writer.flush()

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].name, f"eventlog_{time.strftime('%Y%m%d')}.jsonl")
        self.assertEqual(writer.count, 2)

    def test_part_rotation_switches_file_and_notifies(self):
        calls: list[Path] = []
        writer = EventLogWriter(self.dir, on_rollover=calls.append, max_part_bytes=1)
        self.addCleanup(writer.close)
        writer.handle_packet(_event())
        writer.flush()

        day = time.strftime("%Y%m%d")
        self.assertEqual(len(calls), 1, "写满分片后必须触发一次保留回调")
        self.assertEqual(calls[0].name, f"eventlog_{day}_p02.jsonl")
        self.assertEqual(writer.current_path, calls[0])
        self.assertTrue((self.dir / f"eventlog_{day}.jsonl").exists(), "第一个分片保留")

        writer.handle_packet(_event())
        writer.flush()
        self.assertEqual(len(calls), 2, "第二个分片写满后继续切换")
        self.assertEqual(calls[1].name, f"eventlog_{day}_p03.jsonl")

    def test_oversized_existing_part_is_not_appended(self):
        day = time.strftime("%Y%m%d")
        legacy = _write(self.dir / f"eventlog_{day}.jsonl", size=4096)
        writer = EventLogWriter(self.dir, max_part_bytes=1024)
        self.addCleanup(writer.close)
        writer.handle_packet(_event())
        writer.flush()
        self.assertEqual(
            writer.current_path, self.dir / f"eventlog_{day}_p02.jsonl",
            "上次运行留下的大分片不应继续追加",
        )
        self.assertEqual(legacy.stat().st_size, 4096, "旧分片内容不被改写")

    def test_rollover_callback_failure_does_not_break_writing(self):
        def boom(_path: Path) -> None:
            raise RuntimeError("prune failed")

        writer = EventLogWriter(self.dir, on_rollover=boom, max_part_bytes=1)
        self.addCleanup(writer.close)
        writer.handle_packet(_event())
        writer.flush()
        with self.assertLogs("spritelens.event_log", level="WARNING"):
            writer.handle_packet(_event())
            writer.flush()
        self.assertEqual(writer.count, 2)
        self.assertEqual(writer.error, "")
        self.assertTrue(writer._worker.is_alive())


class CleanupToolTest(_RootTestCase):
    def _build_root(self) -> dict[str, Path]:
        files = {
            "main_db": _write(self.root / "spritelens.sqlite", size=64),
            "main_wal": _write(self.root / "spritelens.sqlite-wal", size=8, age_days=2),
            "main_shm": _write(self.root / "spritelens.sqlite-shm", size=8, age_days=2),
            "config": self.root / "config.json",
            "key": _write(self.root / "keys" / "latest.key", size=32),
            "incompatible": _write(
                self.root / "spritelens.incompatible-1782.sqlite", size=128, age_days=2
            ),
            "incompatible_shm": _write(
                self.root / "spritelens.incompatible-1782.sqlite-shm",
                size=16,
                age_days=2,
            ),
            "recovery_db": _write(
                self.root / "spritelens.empty-before-recovery-20200101-000000.sqlite",
                size=32,
            ),
            "old_eventlog": _write(
                self.root / "eventlog" / "eventlog_20200101.jsonl", size=256, age_days=10
            ),
            "today_eventlog": _write(
                self.root
                / "eventlog"
                / f"eventlog_{time.strftime('%Y%m%d')}.jsonl",
                size=32,
            ),
            "old_recording": _write(
                self.root / "recordings" / "capture_20200101_000000.jsonl",
                size=128,
                age_days=20,
            ),
            "fresh_recording": _write(
                self.root / "recordings" / "capture_20200102_000000.jsonl",
                size=128,
                age_days=1,
            ),
            "old_backup": _write(self.root / "backups" / "old.sqlite", size=64, age_days=40),
            "fresh_backup": _write(
                self.root / "backups" / "fresh.sqlite", size=64, age_days=2
            ),
        }
        files["config"].write_text('{"capture.port": 8195}', encoding="utf-8")
        return files

    def _run_tool(self, *args: str) -> str:
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run(
            [sys.executable, str(_TOOL), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=180,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_dry_run_changes_nothing(self):
        files = self._build_root()
        output = self._run_tool("--root", str(self.root))
        self.assertIn("DRY-RUN", output)
        self.assertIn("预计", output)
        for name, path in files.items():
            self.assertTrue(path.exists(), f"dry-run 不得改动 {name}")
        self.assertFalse((self.root / "backups" / "database-recovery").exists())

    def test_apply_moves_recovery_dbs_and_prunes_records(self):
        files = self._build_root()
        output = self._run_tool("--root", str(self.root), "--apply")
        self.assertIn("APPLY", output)
        self.assertIn("汇总", output)

        recovery_dir = self.root / "backups" / f"database-recovery-{time.strftime('%Y%m%d')}"
        # 过期数据库移动到 backups（不删除，可回溯），旧 sidecar 先被清理
        self.assertTrue((recovery_dir / "spritelens.incompatible-1782.sqlite").exists())
        self.assertTrue(
            (recovery_dir / "spritelens.empty-before-recovery-20200101-000000.sqlite").exists()
        )
        self.assertFalse(files["incompatible"].exists())
        self.assertFalse(files["incompatible_shm"].exists())
        self.assertFalse((recovery_dir / "spritelens.incompatible-1782.sqlite-shm").exists())

        # 记录数据按 3 天/300MB 默认上限清理
        self.assertFalse(files["old_eventlog"].exists())
        self.assertTrue(files["today_eventlog"].exists())
        self.assertFalse(files["old_recording"].exists())
        self.assertTrue(files["fresh_recording"].exists())
        self.assertFalse(files["old_backup"].exists())
        self.assertTrue(files["fresh_backup"].exists())

        # 保护名单一个都不能少
        self.assertTrue(files["main_db"].exists())
        self.assertTrue(files["main_wal"].exists())
        self.assertTrue(files["main_shm"].exists())
        self.assertTrue(files["config"].exists())
        self.assertTrue(files["key"].exists())
        self.assertEqual(
            files["config"].read_text(encoding="utf-8"), '{"capture.port": 8195}'
        )


if __name__ == "__main__":
    unittest.main()
