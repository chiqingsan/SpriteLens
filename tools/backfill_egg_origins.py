"""从事件日志补录蛋仓的历史收蛋来源（小窝类型 / 关联母本 / 候选父本）。

用法:
    python tools/backfill_egg_origins.py                  # 只读预览（默认 dry-run）
    python tools/backfill_egg_origins.py --apply          # 写入蛋仓
    python tools/backfill_egg_origins.py --uid 134509467  # 只看/只补某个账号
    python tools/backfill_egg_origins.py --since 20261028 # 只扫该日期起的日志分片

背景：实时采集只在收蛋当场记来源（请求帧 → 奖励帧关联）。功能上线前
收取的蛋在蛋仓里没有来源，这里用同样的逻辑回放 eventlog 补上。

请在 SpriteLens 退出后运行 `--apply`：应用在线时会把内存里的蛋仓整仓
写回（孵化槽/背包帧），补录的 pickup 会被覆盖；补录完成后重启应用才能
从库里读到。本工具只补 detail_json.pickup，已有来源的蛋不覆盖，其它
字段与 updated_at、home_egg 一律不动。

日志里没有收蛋请求帧的蛋（请求没被采集到、或奖励超出 3 秒窗口）无法
补录，末尾会单独统计。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spritelens.domain.egg_box import EggPickupOrigin
from spritelens.paths import data_root
from spritelens.repositories.database import Database
from spritelens.repositories.egg_store import EggStore
from spritelens.services.egg_origin_backfill import EggOriginScanner, PickupRecord, iter_event_stream
from spritelens.system.single_instance import instance_running

RECENT_WRITE_SECONDS = 60.0
NEST_KIND_LABELS = {"ordinary": "普通窝", "academy": "学院绿窝"}


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="从事件日志补录蛋仓的历史收蛋来源")
    parser.add_argument("--root", default=None, help="用户数据目录（默认 %%LOCALAPPDATA%%\\SpriteLens）")
    parser.add_argument("--apply", action="store_true", help="实际写入蛋仓；默认只预览")
    parser.add_argument("--uid", type=int, default=0, help="只处理该账号（默认全部账号）")
    parser.add_argument("--since", default=None, help="只扫文件名日期 >= 该值（如 20261028）的分片")
    parser.add_argument("--force", action="store_true", help="跳过「应用可能仍在运行」的写入保护")
    return parser.parse_args(argv)


def _eventlog_files(root: Path, since: str | None) -> list[Path]:
    directory = root / "eventlog"
    if not directory.is_dir():
        return []
    files = sorted(directory.glob("eventlog_*.jsonl"))
    if since:
        files = [path for path in files if path.name >= f"eventlog_{since}"]
    return files


def _seconds_since_write(files: list[Path]) -> float:
    newest = max((path.stat().st_mtime for path in files), default=0.0)
    return max(0.0, time.time() - newest)


def _format_time(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def _describe(record: PickupRecord) -> list[str]:
    origin = record.origin
    nest = NEST_KIND_LABELS.get(origin.nest_kind, origin.nest_kind or "未知")
    lines = [f"  蛋 {record.instance_id}  {_format_time(origin.observed_at)}  "
             f"{nest}（配置 {origin.nest_config_id}，小窝 {origin.nest_guid}）"]
    mother = origin.mother
    lines.append(f"    关联母本：{mother.name} #{mother.instance_id}" if mother else "    关联母本：未确认")
    if origin.fathers:
        names = "、".join(f"{father.name} #{father.instance_id}" for father in origin.fathers)
        lines.append(f"    候选父本：{names}" + ("（配对数据可能过期）" if origin.pairing_stale else ""))
    else:
        lines.append("    候选父本：日志里没有可用的配对名单")
    lines.append(f"    日志来源：{record.source or '未知分片'}")
    return lines


def _load_db_state(store: EggStore, uids: list[int]) -> dict[int, dict[int, bool]]:
    """每个账号下 {蛋 instance_id: 是否已有来源}。"""
    state: dict[int, dict[int, bool]] = {}
    for uid in uids:
        state[uid] = {egg.instance_id: egg.pickup is not None for egg in store.load(uid)}
    return state


def _write_guard(files: list[Path]) -> str | None:
    """返回拒绝原因；None 表示可以安全写库。"""
    if instance_running():
        return "检测到 SpriteLens 仍在运行。"
    age = _seconds_since_write(files)
    if age < RECENT_WRITE_SECONDS:
        return f"事件日志 {age:.0f} 秒前仍在写入，可能仍有采集进程。"
    return None


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    root = Path(args.root) if args.root else data_root()
    if not root.is_dir():
        print(f"数据目录不存在：{root}")
        return 2
    files = _eventlog_files(root, args.since)
    if not files:
        print(f"没有可扫描的事件日志分片：{root / 'eventlog'}")
        return 2
    db_file = root / "spritelens.sqlite"
    if not db_file.exists():
        print(f"蛋仓数据库不存在：{db_file}")
        return 2
    if args.apply and not args.force:
        reason = _write_guard(files)
        if reason is not None:
            print(reason)
            print("请退出 SpriteLens 后再运行 --apply：在线应用会把内存蛋仓整仓写回，"
                  "覆盖补录结果。确认已退出可加 --force。")
            return 3

    print(f"扫描 {len(files)} 个事件日志分片（{root / 'eventlog'}）…")
    scanner = EggOriginScanner()
    events = 0
    for source, event in iter_event_stream(files):
        scanner.feed(event, source)
        events += 1
    records = [record for record in scanner.records if not args.uid or record.uid == args.uid]
    print(f"回放 {events} 条事件，得到 {len(records)} 条收蛋关联"
          f"（其中 {scanner.unmatched_rewards} 次收蛋奖励没有匹配到请求帧，只能留空来源）")
    if not records:
        return 0

    db = Database(db_file)
    store = EggStore(db)
    try:
        uids = sorted({record.uid for record in records})
        state = _load_db_state(store, uids)
        pending: dict[int, dict[int, EggPickupOrigin]] = {}
        applied = kept = missing = 0
        for record in records:
            lines = _describe(record)
            uid_state = state.get(record.uid, {})
            if record.instance_id not in uid_state:
                print("\n".join(lines + ["    库内状态：蛋仓里没有这枚蛋，跳过"]))
                missing += 1
                continue
            if uid_state[record.instance_id]:
                print("\n".join(lines + ["    库内状态：已有来源，保留（不覆盖）"]))
                kept += 1
                continue
            print("\n".join(lines + ["    库内状态：待补录"]))
            pending.setdefault(record.uid, {})[record.instance_id] = record.origin
            applied += 1

        print(f"\n汇总：待补录 {applied}，已有来源 {kept}，库中无蛋 {missing}"
              f"，账号 {', '.join(str(uid) for uid in uids)}")
        if not args.apply:
            print("预览模式：未写库。确认无误后加 --apply 执行（请先退出 SpriteLens）。")
            return 0
        if not pending:
            print("没有需要写入的来源。")
            return 0
        for uid, origins in pending.items():
            result = store.put_pickups(uid, origins)
            print(f"已写入 uid={uid}：补上 {result.applied} 条，保留 {result.kept} 条，"
                  f"库中无蛋 {len(result.missing)} 条")
        state = _load_db_state(store, uids)
        done = sum(1 for record in records
                   if state.get(record.uid, {}).get(record.instance_id))
        print(f"复核：{done}/{len(records)} 条关联已能在蛋仓读到。重启 SpriteLens 后蛋仓页面即可显示。")
        return 0
    finally:
        store.close()
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
