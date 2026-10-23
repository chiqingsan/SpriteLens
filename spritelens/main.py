"""包主入口：CLI 参数解析与启动编排。

子命令：
- 无参       启动界面（pywebview 窗口 + 本地服务；原生 PyQt 界面已退役）
- --web-browser  仅起本地服务并用系统浏览器打开（调试用，便于 DevTools）
- --smoke-test  组件导入与管线自检，不打开窗口（CI/构建前检查）
- --list-ifaces 列出可用网卡
- --replay <file.jsonl>  离线回放录制帧
- --background          游戏启动后运行无界面的后台采集
- --ui                  从后台采集实例打开主界面
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import spritelens
from spritelens.logs import install_excepthook, setup_logger
from spritelens.paths import logs_dir


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=spritelens.APP_NAME,
        description=f"{spritelens.APP_DISPLAY_NAME}（{spritelens.APP_NAME}）—《洛克王国：世界》数据观测工具",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {spritelens.__version__}")
    parser.add_argument("--smoke-test", action="store_true", help="组件自检，不打开窗口")
    parser.add_argument(
        "--web-browser",
        action="store_true",
        help="仅起本地服务并用系统浏览器打开（调试用）",
    )
    parser.add_argument("--list-ifaces", action="store_true", help="列出可用抓包网卡")
    parser.add_argument("--replay", metavar="FILE", help="离线回放录制帧文件")
    parser.add_argument("--background", action="store_true", help="运行无界面的后台采集")
    parser.add_argument("--process-name", default="", help="后台采集匹配的游戏 exe 文件名")
    parser.add_argument("--ui", action="store_true", help="连接后台采集实例并打开主界面")
    parser.add_argument("--diagnose-net", nargs="?", type=float, const=20.0, default=None, metavar="SECONDS",
                        help="宽抓 TCP 统计会话分布，定位游戏多连接的数据端口（默认 20 秒）")
    parser.add_argument("--debug", action="store_true", help="控制台同步输出 debug 日志")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        log_directory = logs_dir()
        logger = setup_logger(log_directory, debug=args.debug)
        crash_log = install_excepthook(log_directory)
    except OSError as exc:
        from spritelens.web.run import _fatal

        _fatal("用户数据目录初始化失败", str(exc))
        return 1
    logger.debug("崩溃日志: %s", crash_log)

    if args.smoke_test:
        return _run_smoke_test()
    if args.list_ifaces:
        return _run_list_ifaces()
    if args.diagnose_net is not None:
        from spritelens.system.net_diagnose import run_diagnose

        return run_diagnose(args.diagnose_net)
    if args.replay:
        return _run_replay(args.replay, logger)
    if args.background:
        from spritelens.system.game_process import DEFAULT_GAME_PROCESS_NAME

        from spritelens.web.background_run import run_background

        return run_background(args.process_name or DEFAULT_GAME_PROCESS_NAME)

    # 唯一界面：Web（pywebview 窗口 + 本地服务）
    from spritelens.web.run import run_web

    return run_web(open_browser=args.web_browser, ui_only=args.ui)


def _run_smoke_test() -> int:
    """逐组件导入 + 协议管线自检；环境缺 Npcap/scapy 时不视为失败。"""
    from spritelens.recording import replay as replay_mod
    from spritelens.repositories.settings import SettingsRepository
    from spritelens.services.monitor_service import MonitorService
    from spritelens.capture import key_store
    from spritelens.protocol import crypto, frames, records, schema, wire

    print(f"[smoke] spritelens {spritelens.__version__}")
    print(f"[smoke] 协议层模块: frames/crypto/records/wire/schema 导入正常")
    print(f"[smoke] 服务层: MonitorService 导入正常")
    print(f"[smoke] 录制回放: {replay_mod.__name__} 导入正常")

    settings = SettingsRepository(spritelens.paths.config_path())
    settings.get_str("capture.iface")
    print("[smoke] 配置仓库读写正常")

    # 抓包源探测：装了 scapy 才尝试枚举网卡，失败仅提示（smoke 不要求抓包环境）
    try:
        from spritelens.capture.npcap_source import NpcapCaptureSource

        count = len(NpcapCaptureSource.list_ifaces())
        print(f"[smoke] scapy 可用，枚举到 {count} 个网卡")
    except Exception as exc:  # noqa: BLE001 - smoke 只报告环境状态
        print(f"[smoke] 抓包源不可用（不影响协议层测试）: {exc}")

    # 界面资源必须齐（打包最常见的漏带项）：缺了前端目录服务起不来，
    # 缺了静态表则宠物名/系别全退化成 ID。这里直接失败，不静默通过。
    return _smoke_check_assets()


def _smoke_check_assets() -> int:
    """检查界面与静态资源是否随包分发（打包后自检的关键一步）。"""
    from spritelens.web.server import STATIC_DIR

    failures: list[str] = []
    required_dirs = {
        "前端静态目录": STATIC_DIR,
        "静态映射表": spritelens.paths.static_dir(),
        "schema 目录": spritelens.paths.schema_dir(),
    }
    for label, path in required_dirs.items():
        if path.is_dir():
            print(f"[smoke] {label}: {path} [ok]")
        else:
            failures.append(f"{label}缺失: {path}")

    from spritelens.web.frontend_assets import check_frontend_assets
    failures.extend(check_frontend_assets(STATIC_DIR / "vue"))
    if not (STATIC_DIR / "account-requests.js").is_file():
        failures.append("前端文件缺失: account-requests.js")
    for name in ("index.html", "boot.js", "desktop-shell.js", "desktop-shell.css", "ui.js", "app.js", "app.css", "ui.css", "themes.css", "appearance.js", "icons.js", "icons/sprite.svg", "vue/entry.js"):
        if not (STATIC_DIR / name).is_file():
            failures.append(f"前端文件缺失: {STATIC_DIR / name}")

    if not (spritelens.paths.static_dir() / "pet_media.json").is_file():
        failures.append("精灵图片映射缺失: pet_media.json")

    if spritelens.paths.project_root() != Path(__file__).resolve().parent.parent:
        print(f"[smoke] 冻结态资源根: {spritelens.paths.project_root()}")

    if failures:
        print("[smoke] 资源检查失败：")
        for item in failures:
            print(f"  - {item}")
        return 1

    print("[smoke] 通过")
    return 0


def _run_list_ifaces() -> int:
    from spritelens.capture.npcap_source import NpcapCaptureSource

    for name, description in NpcapCaptureSource.list_ifaces():
        print(f"{name}\t{description}")
    return 0


def _run_replay(path: str, logger) -> int:
    from spritelens.recording.replay import run_replay

    return run_replay(path, logger=logger)


if __name__ == "__main__":
    sys.exit(main())
