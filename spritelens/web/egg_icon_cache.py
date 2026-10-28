"""蛋图标按需补图：本地安装包优先，缺失时从游戏素材站下载并缓存到用户数据目录。

游戏按版本增量更新，新蛋的道具图标不会立刻进安装包。这里只在页面确实要显示
某个图标时才发一次请求，成功后写进用户缓存，之后完全离线；失败静默降级为
中性占位图，不做批量预取、不重试循环、不把失败暴露成错误提示。
"""
from __future__ import annotations

import asyncio
from io import BytesIO
import logging
import os
from pathlib import Path
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from PIL import Image, UnidentifiedImageError

logger = logging.getLogger("spritelens.egg_icon")

_RESOURCE_HOST = "wegame.shallow.ink"
_RESOURCE_PATH = "/api/v1/resources/wiki/assets/items/bag/{item_id}.png"
_MAX_DOWNLOAD_BYTES = 4 * 1024 * 1024
_DOWNLOAD_TIMEOUT = 8
_NOT_FOUND_COOLDOWN = 6 * 60 * 60
_NETWORK_COOLDOWN = 60
_ICON_SIZE = 128


class EggIconCache:
    """按道具 ID 解析蛋图标：安装包 → 用户缓存 → 云端补图（每个 ID 只试一次）。"""

    def __init__(self, static_dir: Path, cache_dir: Path) -> None:
        self._packaged_dir = static_dir / "egg-icons"
        self._cache_dir = cache_dir
        self._downloads = asyncio.Semaphore(2)
        self._inflight: dict[str, asyncio.Task[tuple[Path | None, float]]] = {}
        self._misses: dict[str, float] = {}
        self._network_retry_after = 0.0
        self._closed = False

    async def resolve(self, asset: str) -> Path | None:
        """asset 允许带扩展名（路由参数是文件名），非数字只查安装包。"""
        if self._closed:
            return None
        name = asset if asset.endswith(".webp") else f"{asset}.webp"
        packaged = self._packaged_dir / name
        if packaged.is_file():
            return packaged
        item_id = name[: -len(".webp")]
        if not item_id.isdigit():
            return None
        cached = self._cache_dir / name
        if cached.is_file():
            return cached
        now = time.monotonic()
        if self._misses.get(item_id, 0) > now or self._network_retry_after > now:
            return None

        task = self._inflight.get(item_id)
        if task is None:
            await self._downloads.acquire()
            cached = self._cache_dir / name
            now = time.monotonic()
            task = self._inflight.get(item_id)
            if cached.is_file() or self._misses.get(item_id, 0) > now or self._network_retry_after > now:
                self._downloads.release()
                return cached if cached.is_file() else None
            if task is None:
                task = asyncio.create_task(self._download_and_remember(item_id))
                self._inflight[item_id] = task
                task.add_done_callback(
                    lambda completed, key=item_id: self._clear_inflight(key, completed)
                )
                # 请求取消后下载线程仍运行，许可必须等实际任务结束。
                task.add_done_callback(lambda _: self._downloads.release())
            else:
                self._downloads.release()
        cached, _ = await asyncio.shield(task)
        return cached

    async def close(self) -> None:
        self._closed = True
        tasks = tuple(self._inflight.values())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._inflight.clear()

    async def _download_and_remember(self, item_id: str) -> tuple[Path | None, float]:
        result = await asyncio.to_thread(self._download, item_id)
        cached, retry_after = result
        if cached is None:
            retry_at = time.monotonic() + retry_after
            self._misses[item_id] = retry_at
            if retry_after == _NETWORK_COOLDOWN:
                self._network_retry_after = retry_at
        return result

    def _download(self, item_id: str) -> tuple[Path | None, float]:
        # URL 只由白名单主机与纯数字 ID 拼成，不跟随任意来源
        url = f"https://{_RESOURCE_HOST}{_RESOURCE_PATH.format(item_id=item_id)}"
        request = Request(url, headers={"User-Agent": "SpriteLens egg icon cache"})
        try:
            with urlopen(request, timeout=_DOWNLOAD_TIMEOUT) as response:
                if response.status != 200 or urlsplit(response.geturl()).hostname != _RESOURCE_HOST:
                    return None, _NETWORK_COOLDOWN
                raw = response.read(_MAX_DOWNLOAD_BYTES + 1)
            if len(raw) > _MAX_DOWNLOAD_BYTES:
                return None, _NOT_FOUND_COOLDOWN
            with Image.open(BytesIO(raw)) as source:
                if source.width * source.height > 1_048_576:
                    return None, _NOT_FOUND_COOLDOWN
                source.load()
                image = source.convert("RGBA")
                image.thumbnail((_ICON_SIZE, _ICON_SIZE), Image.Resampling.LANCZOS)
                canvas = Image.new("RGBA", (_ICON_SIZE, _ICON_SIZE))
                canvas.alpha_composite(
                    image, ((_ICON_SIZE - image.width) // 2, (_ICON_SIZE - image.height) // 2)
                )
                output = BytesIO()
                canvas.save(output, "WEBP", lossless=True)
        except HTTPError as exc:
            return (None, _NOT_FOUND_COOLDOWN if exc.code in (400, 404) else _NETWORK_COOLDOWN)
        except (URLError, TimeoutError, OSError, UnidentifiedImageError):
            logger.warning("蛋图标补图失败：%s", item_id)
            return None, _NETWORK_COOLDOWN

        temporary_path: Path | None = None
        target = self._cache_dir / f"{item_id}.webp"
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                dir=self._cache_dir, prefix=f".{item_id}-", suffix=".tmp", delete=False
            ) as stream:
                temporary_path = Path(stream.name)
                stream.write(output.getvalue())
            os.replace(temporary_path, target)
        except OSError:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            logger.warning("保存蛋图标缓存失败：%s", item_id)
            return None, _NETWORK_COOLDOWN
        return target, 0

    def _clear_inflight(
        self, item_id: str, task: asyncio.Task[tuple[Path | None, float]]
    ) -> None:
        if self._inflight.get(item_id) is task:
            self._inflight.pop(item_id, None)
