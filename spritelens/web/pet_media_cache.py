"""按需获取缺失的官方精灵图片，并缓存到用户数据目录。"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from hashlib import sha256
from http.client import HTTPException
from io import BytesIO
import json
import logging
import os
from pathlib import Path
import re
import tempfile
from threading import Lock
import time
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image, UnidentifiedImageError

logger = logging.getLogger("spritelens.pet_media")
_ASSET_NAME = re.compile(r"(?P<id>\d{1,10})-(?P<variant>normal|shiny)-(?P<use>portrait|artwork)\.webp\Z")
_MAX_DOWNLOAD_BYTES = 8 * 1024 * 1024
_DOWNLOAD_TIMEOUT = 3
_NOT_FOUND_COOLDOWN = 6 * 60 * 60
_NETWORK_COOLDOWN = 60


class PetMediaCache:
    """从内置资源开始服务，缺失时尝试腾讯 CDN 并持久化到用户缓存。"""

    def __init__(self, static_dir: Path, cache_dir: Path) -> None:
        self._static_dir = static_dir
        self._cache_dir = cache_dir
        self._downloads = asyncio.Semaphore(3)
        self._misses: dict[str, float] = {}
        self._inflight: dict[str, asyncio.Task[tuple[Path | None, float]]] = {}
        self._network_retry_after = 0.0
        self._manifest_lock = Lock()

    async def resolve(self, asset_name: str) -> Path | None:
        match = _ASSET_NAME.fullmatch(asset_name)
        if match is None:
            return None
        species_id = match.group("id")
        variant = match.group("variant")
        use = match.group("use")
        variants = (variant, "normal") if variant == "shiny" else (variant,)

        for candidate in variants:
            name = f"{species_id}-{candidate}-{use}.webp"
            local = self._local_asset(name)
            if local is not None:
                return local
            now = time.monotonic()
            if self._misses.get(name, 0) > now or self._network_retry_after > now:
                continue
            async with self._downloads:
                # 同一种图片等待并发请求完成后再检查，避免重复下载。
                local = self._local_asset(name)
                if local is not None:
                    return local
                now = time.monotonic()
                if self._misses.get(name, 0) > now or self._network_retry_after > now:
                    continue
                task = self._inflight.get(name)
                if task is None:
                    task = asyncio.create_task(self._download_and_remember(name, species_id, candidate, use))
                    self._inflight[name] = task
                    task.add_done_callback(lambda completed, key=name: self._clear_inflight(key, completed))
                cached, retry_after = await asyncio.shield(task)
            if cached is not None:
                return cached
        return None

    async def _download_and_remember(
        self, name: str, species_id: str, variant: str, use: str,
    ) -> tuple[Path | None, float]:
        result = await asyncio.to_thread(self._download, species_id, variant, use)
        cached, retry_after = result
        if cached is None:
            retry_at = time.monotonic() + retry_after
            self._misses[name] = retry_at
            if retry_after == _NETWORK_COOLDOWN:
                self._network_retry_after = retry_at
        return result

    def _clear_inflight(self, name: str, task: asyncio.Task[tuple[Path | None, float]]) -> None:
        if self._inflight.get(name) is task:
            self._inflight.pop(name, None)

    def _local_asset(self, name: str) -> Path | None:
        packaged = self._static_dir / "pet-media" / name
        if packaged.is_file():
            return packaged
        cached = self._cache_dir / name
        return cached if cached.is_file() else None

    def _download(self, species_id: str, variant: str, use: str) -> tuple[Path | None, float]:
        image_name = {("normal", "portrait"): "icon.png", ("normal", "artwork"): "image.png",
                      ("shiny", "portrait"): "icon_yise.png", ("shiny", "artwork"): "image_yise.png"}[(variant, use)]
        url = f"https://game.gtimg.cn/images/rocom/rocodata/jingling/{species_id}/{image_name}"
        request = Request(url, headers={"User-Agent": "SpriteLens resource cache"})
        try:
            with urlopen(request, timeout=_DOWNLOAD_TIMEOUT) as response:
                if response.status != 200 or urlsplit(response.geturl()).hostname != "game.gtimg.cn":
                    return None, _NETWORK_COOLDOWN
                raw = response.read(_MAX_DOWNLOAD_BYTES + 1)
            if len(raw) > _MAX_DOWNLOAD_BYTES:
                return None, _NOT_FOUND_COOLDOWN
            with Image.open(BytesIO(raw)) as source:
                if source.format != "PNG" or source.width * source.height > 16_777_216:
                    return None, _NOT_FOUND_COOLDOWN
                source_size = source.size
                image = source.convert("RGBA")
                canvas_size = (256, 256) if use == "portrait" else (512, 512)
                image.thumbnail(canvas_size, Image.Resampling.LANCZOS)
                canvas = Image.new("RGBA", canvas_size)
                canvas.alpha_composite(image, ((canvas_size[0] - image.width) // 2,
                                               (canvas_size[1] - image.height) // 2))
                output = BytesIO()
                canvas.save(output, "WEBP", quality=90)
        except HTTPError as exc:
            return None, _NOT_FOUND_COOLDOWN if exc.code == 404 else _NETWORK_COOLDOWN
        except (URLError, TimeoutError, OSError, HTTPException, UnidentifiedImageError,
                Image.DecompressionBombError):
            return None, _NETWORK_COOLDOWN

        name = f"{species_id}-{variant}-{use}.webp"
        target = self._cache_dir / name
        temporary_path: Path | None = None
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self._cache_dir, prefix=".pet-media-", suffix=".tmp", delete=False) as stream:
                temporary_path = Path(stream.name)
                stream.write(output.getvalue())
            os.replace(temporary_path, target)
        except OSError:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            return None, _NETWORK_COOLDOWN

        try:
            self._record_source(name, url, raw, output.getvalue(), source_size, canvas_size)
        except OSError as exc:
            logger.warning("写入精灵图片缓存清单失败：%s", exc)
        return target, 0

    def _record_source(self, name: str, url: str, source: bytes, output: bytes,
                       source_size: tuple[int, int], output_size: tuple[int, int]) -> None:
        path = self._cache_dir / "manifest.json"
        with self._manifest_lock:
            try:
                manifest = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"schema_version": 1, "assets": {}}
            except (OSError, ValueError) as exc:
                logger.warning("读取精灵图片缓存清单失败，将重新生成：%s", exc)
                manifest = {"schema_version": 1, "assets": {}}
            manifest["assets"][name] = {
                "source_url": url,
                "sha256_source": sha256(source).hexdigest(),
                "sha256_output": sha256(output).hexdigest(),
                "source_dimensions": list(source_size),
                "output_dimensions": list(output_size),
                "cached_at": datetime.now(timezone.utc).isoformat(),
            }
            temporary = path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(temporary, path)
