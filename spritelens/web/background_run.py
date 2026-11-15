"""无主界面的后台采集入口。

登录后常驻一个监听进程：用窗口事件等游戏启动，游戏运行期间进入采集会话，
游戏退出后释放单实例锁回到等待。空闲时不轮询、不持锁，也不会触发系统光标
变成「启动中」沙漏。
"""

from __future__ import annotations

import os
import threading

from spritelens.app_context import build_app_context
from spritelens.logs import get_logger
from spritelens.paths import data_root, project_root
from spritelens.system.game_process import (
    current_app_command,
    is_process_running,
    normalize_process_name,
    wait_for_process_exit,
)
from spritelens.system.process_watch import ProcessWindowWatcher
from spritelens.system.runtime_session import RuntimeSession, clear_runtime, write_runtime
from spritelens.system.single_instance import SingleInstanceGuard
from spritelens.system.tray import TrayIcon
from spritelens.web.server import LocalServer

logger = get_logger("background_run")

_SESSION_IDLE = "idle"
_SESSION_USER_EXIT = "exit"
_SESSION_FAILED = "failed"
_WAIT_FALLBACK_SECONDS = 30.0


def run_background(process_name: str) -> int:
    """常驻等待游戏窗口，出现后开始采集，退出后回到等待。"""
    try:
        process_name = normalize_process_name(process_name)
    except ValueError as exc:
        logger.error("后台监听未启动：%s", exc)
        return 2
    if os.name != "nt":
        logger.error("后台监听仅支持 Windows")
        return 1

    watcher = ProcessWindowWatcher(process_name)
    watcher.start()
    guard = SingleInstanceGuard()
    try:
        while True:
            if not is_process_running(process_name):
                logger.info("等待游戏进程启动：%s", process_name)
                _wait_for_game(watcher, process_name)
            if not guard.acquire():
                logger.info("已有实例在运行，等待本轮游戏结束：%s", process_name)
                wait_for_process_exit(process_name)
                watcher.reset()
                continue
            try:
                outcome = _run_capture_session(process_name, guard)
            finally:
                guard.close()
            if outcome != _SESSION_IDLE:
                return 0 if outcome == _SESSION_USER_EXIT else 1
            watcher.reset()
    finally:
        watcher.stop()


def _wait_for_game(watcher: ProcessWindowWatcher, process_name: str) -> None:
    """由窗口事件唤醒；超时只做一次轻量快照，兜住事件丢失或注册失败。"""
    while True:
        if watcher.wait(_WAIT_FALLBACK_SECONDS):
            return
        if is_process_running(process_name):
            return


def _run_capture_session(process_name: str, guard: SingleInstanceGuard) -> str:
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
                    server = LocalServer(
                        context, ext_runtime_path=data_root() / "ext-runtime.json"
                    )
                    server.start()
                    write_runtime(RuntimeSession(pid=os.getpid(), url=server.url))
                    logger.info("按需启动本地 UI 服务：%s", server.url)
                _launch_ui()
        if exit_requested.is_set():
            logger.info("后台监听已按要求退出")
            return _SESSION_USER_EXIT
        logger.info("游戏进程退出，后台采集准备停止：%s", process_name)
        return _SESSION_IDLE
    except Exception:
        logger.exception("后台采集运行失败")
        return _SESSION_FAILED
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


def _launch_ui() -> None:
    import subprocess

    executable, arguments = current_app_command("--ui")
    subprocess.Popen(
        [executable, *arguments],
        cwd=str(project_root()),
        close_fds=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _icon_path():
    return project_root() / "resources" / "app.ico"


__all__ = ["run_background"]
