"""后台采集实例向按需 UI 进程发布的本地运行信息。"""

from __future__ import annotations

import json
from dataclasses import dataclass

from spritelens.paths import data_root

RUNTIME_FILE_NAME = "background-runtime.json"


@dataclass(frozen=True)
class RuntimeSession:
    pid: int
    url: str


def runtime_path():
    return data_root() / RUNTIME_FILE_NAME


def write_runtime(session: RuntimeSession) -> None:
    path = runtime_path()
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps({"pid": session.pid, "url": session.url}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def read_runtime() -> RuntimeSession | None:
    try:
        raw = json.loads(runtime_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    if (
        not isinstance(raw, dict)
        or type(raw.get("pid")) is not int
        or raw["pid"] <= 0
        or not isinstance(raw.get("url"), str)
        or not raw["url"].startswith("http://127.0.0.1:")
    ):
        return None
    return RuntimeSession(pid=raw["pid"], url=raw["url"])


def clear_runtime(pid: int | None = None) -> None:
    path = runtime_path()
    if pid is not None:
        current = read_runtime()
        if current is not None and current.pid != pid:
            return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


__all__ = ["RUNTIME_FILE_NAME", "RuntimeSession", "clear_runtime", "read_runtime", "runtime_path", "write_runtime"]
