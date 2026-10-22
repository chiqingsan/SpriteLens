"""按头像 ID 懒加载游戏头像，并缓存到用户数据目录。"""
from __future__ import annotations

import asyncio
from io import BytesIO
import json
import logging
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from PIL import Image, UnidentifiedImageError

logger = logging.getLogger("spritelens.account_avatar")

_AVATAR_NAME = re.compile(r"(?P<icon_id>\d{1,10})\.png\Z")
_RESOURCE_HOST = "wegame.shallow.ink"
_MAX_DOWNLOAD_BYTES = 8 * 1024 * 1024
_DOWNLOAD_TIMEOUT = 10
_NOT_FOUND_COOLDOWN = 6 * 60 * 60
_NETWORK_COOLDOWN = 60


class AccountAvatarCache:
    """仅从映射清单解析来源，首次访问时下载并缓存原始 PNG。"""

    def __init__(self, static_dir: Path, cache_dir: Path) -> None:
        self._manifest_path = static_dir / "account-avatars" / "manifest.json"
        self._cache_dir = cache_dir
        self._sources = self._load_sources()
        self._downloads = asyncio.Semaphore(2)
        self._inflight: dict[str, asyncio.Task[tuple[Path | None, float]]] = {}
        self._misses: dict[str, float] = {}
        self._network_retry_after = 0.0
        self._closed = False

    async def resolve(self, asset_name: str) -> Path | None:
        if self._closed:
            return None
        match = _AVATAR_NAME.fullmatch(asset_name)
        if match is None:
            return None
        icon_id = match.group("icon_id")
        local = self._local_asset(icon_id)
        if local is not None:
            return local
        now = time.monotonic()
        if self._misses.get(icon_id, 0) > now or self._network_retry_after > now:
            return None
        if icon_id not in self._sources:
            return None

        async with self._downloads:
            local = self._local_asset(icon_id)
            if local is not None:
                return local
            now = time.monotonic()
            if self._misses.get(icon_id, 0) > now or self._network_retry_after > now:
                return None
            task = self._inflight.get(icon_id)
            if task is None:
                task = asyncio.create_task(self._download_and_remember(icon_id))
                self._inflight[icon_id] = task
                task.add_done_callback(
                    lambda completed, key=icon_id: self._clear_inflight(key, completed)
                )
            cached, retry_after = await asyncio.shield(task)
        if cached is not None:
            return cached
        retry_at = time.monotonic() + retry_after
        self._misses[icon_id] = retry_at
        if retry_after == _NETWORK_COOLDOWN:
            self._network_retry_after = retry_at
        return None

    async def close(self) -> None:
        """停止接收新请求，并等待已启动的下载线程完成。"""
        self._closed = True
        tasks = tuple(self._inflight.values())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._inflight.clear()

    def _load_sources(self) -> dict[str, str]:
        try:
            manifest = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.error("读取游戏头像映射失败：%s", exc)
            return {}
        sources: dict[str, str] = {}
        for entry in manifest.get("assets", []):
            icon_id = str(entry.get("id", ""))
            source_url = str(entry.get("source_url", ""))
            parsed = urlsplit(source_url)
            expected_path = f"/api/v1/resources/wiki/assets/profile/avatar/{icon_id}.png"
            if (icon_id.isdigit() and parsed.scheme == "https"
                    and parsed.hostname == _RESOURCE_HOST and parsed.path == expected_path):
                sources[icon_id] = source_url
        return sources

    def _local_asset(self, icon_id: str) -> Path | None:
        path = self._cache_dir / f"{icon_id}.png"
        return path if path.is_file() else None

    async def _download_and_remember(self, icon_id: str) -> tuple[Path | None, float]:
        return await asyncio.to_thread(self._download, icon_id)

    def _download(self, icon_id: str) -> tuple[Path | None, float]:
        url = self._sources[icon_id]
        request = Request(url, headers={"User-Agent": "SpriteLens account avatar cache"})
        try:
            with urlopen(request, timeout=_DOWNLOAD_TIMEOUT) as response:
                if response.status != 200 or urlsplit(response.geturl()).hostname != _RESOURCE_HOST:
                    return None, _NETWORK_COOLDOWN
                raw = response.read(_MAX_DOWNLOAD_BYTES + 1)
            if len(raw) > _MAX_DOWNLOAD_BYTES:
                return None, _NOT_FOUND_COOLDOWN
            with Image.open(BytesIO(raw)) as image:
                if image.format != "PNG":
                    return None, _NOT_FOUND_COOLDOWN
                image.verify()
        except HTTPError as exc:
            return (None, _NOT_FOUND_COOLDOWN if exc.code in (400, 404) else _NETWORK_COOLDOWN)
        except (URLError, TimeoutError, OSError, UnidentifiedImageError):
            logger.warning("游戏头像下载失败：%s", icon_id)
            return None, _NETWORK_COOLDOWN

        temporary_path: Path | None = None
        target = self._cache_dir / f"{icon_id}.png"
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                dir=self._cache_dir, prefix=f".{icon_id}-", suffix=".tmp", delete=False
            ) as stream:
                temporary_path = Path(stream.name)
                stream.write(raw)
            os.replace(temporary_path, target)
        except OSError:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            logger.warning("保存游戏头像缓存失败：%s", icon_id)
            return None, _NETWORK_COOLDOWN
        return target, 0

    def _clear_inflight(
        self, icon_id: str, task: asyncio.Task[tuple[Path | None, float]]
    ) -> None:
        if self._inflight.get(icon_id) is task:
            self._inflight.pop(icon_id, None)
