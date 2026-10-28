from __future__ import annotations

import asyncio
import json
from pathlib import Path
import tempfile
import threading
import unittest

from spritelens.web.account_avatar_cache import AccountAvatarCache
from spritelens.web.egg_icon_cache import EggIconCache
from spritelens.web.pet_media_cache import PetMediaCache


class AssetCacheLifecycleTest(unittest.TestCase):
    def test_cancelled_requests_keep_download_limit_and_cancel_waiters(self) -> None:
        async def run(cache_type, root):
            (root / "account-avatars").mkdir(exist_ok=True)
            (root / "account-avatars" / "manifest.json").write_text('{"assets": []}', encoding="utf-8")
            cache = cache_type(root, root / "cache")
            limit = 3 if cache_type is PetMediaCache else 2
            if cache_type is AccountAvatarCache:
                cache._sources = {str(i): "unused" for i in range(1, 2 * limit + 2)}
            started, release = threading.Event(), threading.Event()
            lock = threading.Lock()
            counts = {"active": 0, "peak": 0, "started": 0}

            def download(*args):
                with lock:
                    counts["active"] += 1
                    counts["started"] += 1
                    counts["peak"] = max(counts["peak"], counts["active"])
                    if counts["started"] == limit:
                        started.set()
                release.wait(3)
                with lock:
                    counts["active"] -= 1
                return None, 0

            cache._download = download
            def name(i):
                if cache_type is AccountAvatarCache:
                    return f"{i}.png"
                return f"{i}-normal-portrait.webp" if cache_type is PetMediaCache else f"{i}.webp"
            first = [asyncio.create_task(cache.resolve(name(i))) for i in range(1, limit + 1)]
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 2))
                for task in first:
                    task.cancel()
                await asyncio.gather(*first, return_exceptions=True)
                waiting = [asyncio.create_task(cache.resolve(name(i))) for i in range(limit + 1, 2 * limit + 1)]
                await asyncio.sleep(0.05)
                self.assertEqual(counts["started"], limit)
                for task in waiting:
                    task.cancel()
                await asyncio.gather(*waiting, return_exceptions=True)
                release.set()
                await cache.close()
                self.assertEqual(counts["started"], limit)
                self.assertEqual(counts["peak"], limit)
            finally:
                release.set()
                await cache.close()

        for cache_type in (AccountAvatarCache, PetMediaCache, EggIconCache):
            with self.subTest(cache=cache_type.__name__), tempfile.TemporaryDirectory() as directory:
                asyncio.run(run(cache_type, Path(directory)))

    def test_cache_manifest_records_resource_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resource_manifest = root / "pet_media_manifest.json"
            resource_manifest.write_text(
                json.dumps({"schema_version": 1, "resource_version": "test-2026-10"}),
                encoding="utf-8",
            )
            cache = PetMediaCache(root, root / "cache", resource_manifest)
            cache._cache_dir.mkdir()
            cache._record_source(
                "1-normal-portrait.webp",
                "https://game.gtimg.cn/example.png",
                b"source",
                b"output",
                (1, 1),
                (256, 256),
            )

            manifest = json.loads(
                (root / "cache" / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["schema_version"], 2)
            self.assertEqual(manifest["resource_version"], "test-2026-10")

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
