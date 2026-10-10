"""本地日志：标准 logging + RotatingFileHandler 双文件。

与 meow toolkit 同款策略：app.log 只放用户可理解的结论，debug.log 存放
协议细节（帧 hex、原始字节等），避免敏感细节泄漏到 UI 或常规日志。

另提供崩溃兜底：start.bat 用 pythonw 启动（无控制台），未捕获异常默认
静默消失，用户只看到窗口没开。`install_excepthook()` 把主线程异常写入
crash.log，并提供错误提示给界面降级使用。
"""

from __future__ import annotations

import logging
import sys
import threading
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

import spritelens

_APP_LOG_NAME = "spritelens.log"
_DEBUG_LOG_NAME = "spritelens.debug.log"
_CRASH_LOG_NAME = "spritelens.crash.log"
_APP_MAX_BYTES = 256 * 1024
_DEBUG_MAX_BYTES = 2 * 1024 * 1024
_CRASH_MAX_BYTES = 512 * 1024


class CompactFormatter(logging.Formatter):
    """超长消息截断，防止帧 dump 撑爆日志文件。"""

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        if len(text) > 2000:
            text = text[:2000] + f"...<截断，全长 {len(text)}>"
        return text


def setup_logger(logs_dir: Path, *, debug: bool = False) -> logging.Logger:
    """初始化根 logger，返回 spritelens 根 logger。重复调用直接复用。"""
    logger = logging.getLogger(spritelens.APP_NAME.lower())
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    fmt = CompactFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    app_handler = RotatingFileHandler(
        logs_dir / _APP_LOG_NAME, maxBytes=_APP_MAX_BYTES, backupCount=2, encoding="utf-8"
    )
    app_handler.setLevel(logging.INFO)
    app_handler.setFormatter(fmt)
    logger.addHandler(app_handler)

    debug_handler = RotatingFileHandler(
        logs_dir / _DEBUG_LOG_NAME, maxBytes=_DEBUG_MAX_BYTES, backupCount=2, encoding="utf-8"
    )
    debug_handler.setLevel(logging.DEBUG)
    debug_handler.setFormatter(fmt)
    logger.addHandler(debug_handler)

    if debug:
        console = logging.StreamHandler()
        console.setLevel(logging.DEBUG)
        console.setFormatter(fmt)
        logger.addHandler(console)
    return logger


def get_logger(name: str) -> logging.Logger:
    """子模块统一入口：spritelens.<name>，未 setup 前也安全（走默认 handler）。"""
    return logging.getLogger(f"{spritelens.APP_NAME.lower()}.{name}")


def install_excepthook(logs_dir: Path) -> Path:
    """把未捕获异常写入独立 crash.log，返回该文件路径。

    为什么单独一个文件：app.log 会被压缩轮转，崩溃现场需要长期保留；
    crash.log 只追加不轮转成多份，用户反馈问题时报这一个路径即可。
    主线程与后台线程异常都记录（pythonw 下两者都不可见）。
    """
    crash_path = logs_dir / _CRASH_LOG_NAME

    def _write(kind: str, exc: BaseException) -> None:
        try:
            logs_dir.mkdir(parents=True, exist_ok=True)
            with crash_path.open("a", encoding="utf-8") as handle:
                handle.write(f"\n===== {kind} 未捕获异常 =====\n")
                traceback.print_exception(type(exc), exc, exc.__traceback__, file=handle)
        except OSError:
            pass  # 崩溃现场写入失败不能让进程再崩一次

    def _hook(exc_type, exc_value, exc_tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        _write("主线程", exc_value)
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook

    def _thread_hook(args: threading.ExceptHookArgs) -> None:
        if issubclass(args.exc_type, SystemExit):
            return
        _write(f"线程 {args.thread.name if args.thread else '?'}", args.exc_value)

    threading.excepthook = _thread_hook
    return crash_path
