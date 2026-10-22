from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
import threading
import unittest

from spritelens.web.account_avatar_cache import AccountAvatarCache
from spritelens.web.pet_media_cache import PetMediaCache


class AssetCacheLifecycleTest(unittest.TestCase):
    def test_close_waits_for_actual_download_threads(self) -> None:
        async def run(cache_type, root):
            (root / "account-avatars").mkdir(exist_ok=True)
            (root / "account-avatars" / "manifest.json").write_text('{"assets": []}', encoding="utf-8")
            cache = cache_type(root, root / "cache")
            started, release, finished = threading.Event(), threading.Event(), threading.Event()

            def download(*args):
                started.set()
                release.wait(3)
                finished.set()
                return None, 0

            cache._download = download
            args = ("1",) if cache_type is AccountAvatarCache else ("1-normal-portrait.webp", "1", "normal", "portrait")
            task = asyncio.create_task(cache._download_and_remember(*args))
            cache._inflight["1"] = task
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 2))
                closing = asyncio.create_task(cache.close())
                await asyncio.sleep(0)
                self.assertFalse(closing.done())
                self.assertFalse(finished.is_set())
                release.set()
                await closing
                self.assertTrue(finished.is_set())
                self.assertFalse(task.cancelled())
                self.assertFalse(cache._inflight)
                self.assertIsNone(await cache.resolve("1.png"))
            finally:
                release.set()
                await task

        for cache_type in (AccountAvatarCache, PetMediaCache):
            with self.subTest(cache=cache_type.__name__), tempfile.TemporaryDirectory() as directory:
                asyncio.run(run(cache_type, Path(directory)))
