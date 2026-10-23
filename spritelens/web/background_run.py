"""无主界面的按需后台采集入口。"""

from __future__ import annotations

import os
import threading

from spritelens.app_context import build_app_context
from spritelens.logs import get_logger
from spritelens.system.game_process import (
    current_app_command,
    is_process_running,
    normalize_process_name,
)
from spritelens.system.runtime_session import RuntimeSession, clear_runtime, write_runtime
from spritelens.system.single_instance import SingleInstanceGuard
from spritelens.system.tray import TrayIcon
from spritelens.web.server import LocalServer

logger = get_logger("background_run")


def run_background(process_name: str) -> int:
    """游戏事件触发后启动采集，游戏结束后释放后台资源。"""
    try:
        process_name = normalize_process_name(process_name)
    except ValueError as exc:
        logger.error("后台监听未启动：%s", exc)
        return 2
    if not is_process_running(process_name):
        logger.info("后台任务触发时游戏进程已退出：%s", process_name)
        return 0

    guard = SingleInstanceGuard()
    if not guard.acquire():
        logger.info("后台采集已有实例运行，本次任务退出")
        return 0

    context = None
    server: LocalServer | None = None
    tray: TrayIcon | None = None
    activation_handle = guard.create_activation_event()
    open_ui = threading.Event()
    exit_requested = threading.Event()
    try:
        context = build_app_context(autostart=True)
        tray = TrayIcon(
            icon_path=str(_icon_path()),
            on_open=open_ui.set,
            on_exit=exit_requested.set,
        )
        tray.start()
        logger.info("后台采集已启动，目标进程：%s", process_name)

        while is_process_running(process_name) and not exit_requested.is_set():
            if activation_handle and guard.consume_activation(activation_handle):
                open_ui.set()
            if open_ui.wait(0.25):
                open_ui.clear()
                if server is None:
                    server = LocalServer(context)
                    server.start()
                    write_runtime(RuntimeSession(pid=os.getpid(), url=server.url))
                    logger.info("按需启动本地 UI 服务：%s", server.url)
                _launch_ui()
        logger.info("游戏进程退出，后台采集准备停止：%s", process_name)
        return 0
    except Exception:
        logger.exception("后台采集运行失败")
        return 1
    finally:
        clear_runtime(os.getpid())
        if tray is not None:
            tray.stop()
        if server is not None:
            try:
                server.stop()
            except Exception:
                logger.exception("后台本地服务关闭失败")
        if context is not None:
            try:
                context.close()
            except Exception:
                logger.exception("后台采集资源关闭失败")
        guard.close()


def _launch_ui() -> None:
    import subprocess

    executable, arguments = current_app_command("--ui")
    subprocess.Popen(
        [executable, *arguments],
        cwd=str(_project_root()),
        close_fds=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _project_root():
    from spritelens.paths import project_root

    return project_root()


def _icon_path():
    return _project_root() / "resources" / "app.ico"


__all__ = ["run_background"]
