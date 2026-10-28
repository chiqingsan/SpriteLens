"""目录增量更新的扩展点（游戏增量更新的层 2 接缝）。

游戏每版都在加蛋/加精灵：本地随包分发的目录（`data/static/eggs.json`）会落后，
表现为「有图无名」「区间缺失」。运行期补图（`web/egg_icon_cache.py`）只解决图标，
名称、尺寸/体重区间、蛋组这些必须靠目录数据本身更新。

真正的更新服务端还没做。这里先把接缝定下来，接服务端时只新增一个
`CatalogSource` 实现，落盘、校验、回滚都不用改：

- `CatalogStore`：用户数据目录里的版本化快照 + 指针文件。当前版本可用时优先于
  随包目录；不可用（文件缺失/损坏）自动退回随包目录，不会让页面变空。
- `CatalogSource`：更新源协议（`check` 比版本，`fetch` 取归档）。默认
  `DisabledCatalogSource`，不联网。
- `CatalogUpdater`：编排 check → fetch → 校验 → 安装，返回结构化结果。

服务端需要提供的约定（接服务端时按这个实现 source 即可）：

- manifest 字段：`version`（字符串，单调递增）、`sha256`（归档字节的 sha256）、
  `entries`（条目数，仅展示）、`published_at`（unix 秒）、`source`（归档地址）；
- 归档是 zip：里面只允许 `eggs.json`（必需）、`egg_inventory.json`、
  `egg_descriptions.json` 三个文件，格式与 `data/static/` 同名文件一致；
- 客户端只在用户点「检查更新」时调用，不做启动预取，失败静默保留旧版本；
- 请求只带版本号，不带账号、UID 或任何业务数据。

未接入时的行为（当前默认）：`DisabledCatalogSource` 恒返回「没有更新」，
所有页面照旧读随包目录，不产生任何网络请求。
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

CATALOG_FILES = ("eggs.json", "egg_inventory.json", "egg_descriptions.json")
REQUIRED_CATALOG_FILES = ("eggs.json",)
MANIFEST_FILE = "manifest.json"
POINTER_FILE = "active.json"
_HISTORY_DEPTH = 3
_MAX_ARCHIVE_BYTES = 32 * 1024 * 1024


class CatalogUnavailable(RuntimeError):
    """更新源不可用（未配置、网络失败、服务端 5xx）。保留当前版本。"""


class CatalogRejected(RuntimeError):
    """归档校验失败（sha256 不符、缺必需文件、JSON 损坏、越界路径）。保留当前版本。"""


@dataclass(frozen=True)
class CatalogRelease:
    """更新源报告的一个目录版本。"""

    version: str
    sha256: str
    entries: int = 0
    published_at: int = 0
    source: str = ""


@dataclass(frozen=True)
class UpdateResult:
    """更新结果；status 取值见 `CatalogUpdater.update`。"""

    status: str
    version: str | None = None
    installed_dir: Path | None = None
    message: str = ""

    @property
    def installed(self) -> bool:
        return self.status == "installed"


class CatalogSource(Protocol):
    """更新源协议。接服务端时实现这一个接口即可。

    `check` 返回 None 表示「已是最新」；`fetch` 返回 zip 归档字节。
    网络失败抛 `CatalogUnavailable`，不要抛其他异常。
    """

    name: str

    async def check(self, current_version: str | None) -> CatalogRelease | None: ...

    async def fetch(self, release: CatalogRelease) -> bytes: ...


class DisabledCatalogSource:
    """默认实现：未配置更新源，永不上报更新。"""

    name = "disabled"

    async def check(self, current_version: str | None) -> CatalogRelease | None:
        return None

    async def fetch(self, release: CatalogRelease) -> bytes:
        raise CatalogUnavailable("未配置目录更新源")


class CatalogStore:
    """用户数据目录里的目录快照：版本目录 + 指针文件，支持回滚。

    布局::

        <root>/active.json                     {"current": {...}, "history": [{...}, ...]}
        <root>/versions/<version>-<sha8>/      eggs.json / egg_inventory.json / manifest.json

    指针先写临时文件再 `os.replace`，因此切换是原子的：进程在任意时刻崩溃，
    要么指向旧版本、要么指向新版本，不存在只写一半的当前目录。
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._versions = self._root / "versions"

    @property
    def root(self) -> Path:
        return self._root

    # -- 读取 ----------------------------------------------------------

    def _pointer(self) -> dict:
        path = self._root / POINTER_FILE
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _entry_dir(self, entry: object) -> Path | None:
        if not isinstance(entry, dict):
            return None
        relative = entry.get("dir")
        if not isinstance(relative, str) or not relative:
            return None
        path = self._root / relative
        if ".." in Path(relative).parts:
            return None
        return path if (path / REQUIRED_CATALOG_FILES[0]).is_file() else None

    def active_dir(self) -> Path | None:
        """当前生效的快照目录；缺失或损坏时返回 None（调用方退回随包目录）。"""
        return self._entry_dir(self._pointer().get("current"))

    def current_version(self) -> str | None:
        if self.active_dir() is None:
            return None
        entry = self._pointer().get("current")
        version = entry.get("version") if isinstance(entry, dict) else None
        return version if isinstance(version, str) and version else None

    def resolve(self, fallback: Path) -> Path:
        """有可用快照就用快照，否则用随包目录；保证返回值里一定有 eggs.json。"""
        return self.active_dir() or Path(fallback)

    # -- 写入 ----------------------------------------------------------

    def install(self, archive: bytes, release: CatalogRelease) -> Path:
        """校验并安装一个目录归档，成功后指针指向它。失败抛 `CatalogRejected`。"""
        digest = hashlib.sha256(archive).hexdigest()
        if release.sha256 and digest.lower() != release.sha256.lower():
            raise CatalogRejected(f"sha256 不符：期望 {release.sha256}，实际 {digest}")
        if len(archive) > _MAX_ARCHIVE_BYTES:
            raise CatalogRejected("归档过大")
        if not release.version.strip():
            raise CatalogRejected("版本号为空")

        self._versions.mkdir(parents=True, exist_ok=True)
        staging = self._versions / f".staging-{uuid.uuid4().hex}"
        staging.mkdir()
        try:
            self._extract(archive, staging)
            if not (staging / REQUIRED_CATALOG_FILES[0]).is_file():
                raise CatalogRejected("归档缺少 eggs.json")
            (staging / MANIFEST_FILE).write_text(
                json.dumps(
                    {
                        "version": release.version,
                        "sha256": digest,
                        "entries": release.entries,
                        "published_at": release.published_at,
                        "source": release.source,
                    },
                    ensure_ascii=False,
                    indent=2,
                ) + "\n",
                encoding="utf-8",
            )
            target = self._versions / f"{_safe_component(release.version)}-{digest[:8]}"
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            os.replace(staging, target)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise

        pointer = self._pointer()
        entry = {"version": release.version, "sha256": digest,
                 "dir": str(target.relative_to(self._root))}
        history = [pointer.get("current")] + list(_history(pointer))
        history = [item for item in history if isinstance(item, dict)][:_HISTORY_DEPTH]
        self._write_pointer({"current": entry, "history": history})
        self._prune([entry, *history])
        return target

    def rollback(self) -> bool:
        """退回上一个可用版本；没有更早的版本时返回 False（不删任何文件）。"""
        pointer = self._pointer()
        history = list(_history(pointer))
        while history:
            candidate = history.pop(0)
            if self._entry_dir(candidate) is None:
                continue
            self._write_pointer({"current": candidate, "history": history})
            return True
        return False

    # -- 内部 ----------------------------------------------------------

    def _extract(self, archive: bytes, target: Path) -> None:
        try:
            with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
                for info in bundle.infolist():
                    if info.is_dir():
                        continue
                    name = info.filename.replace("\\", "/")
                    if "/" in name or name not in CATALOG_FILES:
                        raise CatalogRejected(f"归档包含不允许的条目：{name}")
                    raw = bundle.read(info)
                    try:
                        json.loads(raw.decode("utf-8"))
                    except (UnicodeDecodeError, ValueError) as exc:
                        raise CatalogRejected(f"{name} 不是合法的 UTF-8 JSON") from exc
                    (target / name).write_bytes(raw)
        except zipfile.BadZipFile as exc:
            raise CatalogRejected("归档不是合法的 zip") from exc

    def _write_pointer(self, data: dict) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=".active-", suffix=".json", dir=self._root)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._root / POINTER_FILE)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def _prune(self, keep: list) -> None:
        if not self._versions.is_dir():
            return
        kept = {str(entry.get("dir")) for entry in keep if isinstance(entry, dict)}
        for child in self._versions.iterdir():
            if child.is_dir() and str(child.relative_to(self._root)) not in kept:
                shutil.rmtree(child, ignore_errors=True)


def _history(pointer: dict) -> tuple:
    history = pointer.get("history")
    return tuple(history) if isinstance(history, list) else ()


def _safe_component(value: str) -> str:
    keep = [char if char.isalnum() or char in "-._" else "_" for char in value.strip()]
    return "".join(keep)[:64] or "catalog"


class CatalogUpdater:
    """按更新源把目录快照装到用户数据目录；失败保留当前版本，不产生半成品。"""

    def __init__(self, store: CatalogStore, source: CatalogSource | None = None) -> None:
        self._store = store
        self._source: CatalogSource = source or DisabledCatalogSource()

    async def update(self) -> UpdateResult:
        current = self._store.current_version()
        source_name = getattr(self._source, "name", "")
        try:
            release = await self._source.check(current)
        except CatalogUnavailable as exc:
            return UpdateResult("unavailable", current, None, str(exc))
        if release is None:
            if source_name == "disabled":
                return UpdateResult("disabled", current, None, "未配置目录更新源")
            return UpdateResult("up_to_date", current, None, "已是最新目录")
        if current is not None and release.version == current:
            return UpdateResult("up_to_date", current, None, "已是最新目录")
        try:
            archive = await self._source.fetch(release)
        except CatalogUnavailable as exc:
            return UpdateResult("unavailable", current, None, str(exc))
        try:
            installed = self._store.install(archive, release)
        except CatalogRejected as exc:
            return UpdateResult("rejected", current, None, str(exc))
        return UpdateResult("installed", release.version, installed, "")


__all__ = [
    "CATALOG_FILES",
    "CatalogRelease",
    "CatalogRejected",
    "CatalogSource",
    "CatalogStore",
    "CatalogUnavailable",
    "CatalogUpdater",
    "DisabledCatalogSource",
    "UpdateResult",
]
