"""隔离的临时新用户预览，子进程独占数据根目录。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


class PreviewManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._directory: tempfile.TemporaryDirectory | None = None
        self._url: str | None = None

    def start(self) -> str:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                raise RuntimeError("已有调试预览正在运行，请先退出")
            self._stop_locked()
            directory = tempfile.TemporaryDirectory(prefix="spritelens-preview-")
            ready = Path(directory.name) / "ready.json"
            env = os.environ.copy()
            env.update(SPRITELENS_DATA_ROOT=directory.name, SPRITELENS_DEBUG_PREVIEW="1", SPRITELENS_PREVIEW_READY=str(ready))
            frozen = getattr(sys, "frozen", False) or "__compiled__" in globals()
            command = [sys.executable, "--debug-preview-worker"] if frozen else [sys.executable, "-m", "spritelens", "--debug-preview-worker"]
            try:
                process = subprocess.Popen(command, env=env, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL, cwd=None if frozen else Path(__file__).resolve().parents[2],
                                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except OSError:
                directory.cleanup()
                raise
            self._process, self._directory = process, directory
            try:
                deadline = time.monotonic() + 30
                while not ready.exists():
                    if process.poll() is not None:
                        raise RuntimeError("预览服务提前退出")
                    if time.monotonic() >= deadline:
                        raise TimeoutError("预览服务启动超时")
                    time.sleep(0.05)
                result = json.loads(ready.read_text(encoding="utf-8"))
                if "error" in result:
                    raise RuntimeError(result["error"])
                self._url = result["url"]
                return self._url
            except Exception:
                self._stop_locked()
                raise

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        process = self._process
        if process is not None:
            if process.stdin is not None:
                process.stdin.close()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired as exc:
                raise TimeoutError("预览服务关闭超时，请重试") from exc
            self._process = None
        if self._directory is not None:
            self._directory.cleanup()
            self._directory = None
        self._url = None


def run_worker() -> int:
    """只由主服务启动；父进程关闭管道后停止预览并释放资源。"""
    from spritelens.app_context import build_app_context
    from spritelens.web.server import LocalServer

    ready = Path(os.environ["SPRITELENS_PREVIEW_READY"])
    context = None
    server = None
    try:
        context = build_app_context(autostart=False)
        server = LocalServer(context)
        server.start()
        temporary = ready.with_suffix(".tmp")
        temporary.write_text(json.dumps({"url": server.url}), encoding="utf-8")
        temporary.replace(ready)
        sys.stdin.buffer.read()
        return 0
    except Exception as exc:
        temporary = ready.with_suffix(".tmp")
        temporary.write_text(json.dumps({"error": str(exc)}), encoding="utf-8")
        temporary.replace(ready)
        return 1
    finally:
        if server is not None:
            server.stop()
        if context is not None:
            context.close()
