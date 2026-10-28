from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.parse import urlsplit

from PIL import Image

from spritelens.web.egg_icon_cache import EggIconCache

_SOURCE = "https://wegame.shallow.ink/api/v1/resources/wiki/assets/items/bag/{id}.png"


class _Response:
    def __init__(self, raw: bytes, url: str, status: int = 200) -> None:
        self.status = status
        self._raw = raw
        self._url = url

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args) -> None:
        return None

    def geturl(self) -> str:
        return self._url

    def read(self, _limit: int) -> bytes:
        return self._raw


def _png(size: int = 256) -> bytes:
    output = BytesIO()
    Image.new("RGBA", (size, size), (120, 170, 220, 255)).save(output, "PNG")
    return output.getvalue()


class EggIconCacheTest(unittest.TestCase):
    def test_downloads_once_then_serves_user_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            static_dir = root / "static"
            (static_dir / "egg-icons").mkdir(parents=True)
            cache = EggIconCache(static_dir, root / "egg-icon-cache")
            response = _Response(_png(), _SOURCE.format(id=150006))
            with mock.patch(
                "spritelens.web.egg_icon_cache.urlopen", return_value=response
            ) as download:
                first = asyncio.run(cache.resolve("150006.webp"))
                second = asyncio.run(cache.resolve("150006"))

            self.assertIsNotNone(first)
            self.assertEqual(first, second)
            self.assertEqual(download.call_count, 1)
            request_url = download.call_args[0][0].full_url
            self.assertEqual(urlsplit(request_url).hostname, "wegame.shallow.ink")
            self.assertTrue(request_url.endswith("/items/bag/150006.png"))
            with Image.open(first) as image:
                self.assertEqual(image.format, "WEBP")
                self.assertEqual(image.size, (128, 128))
            self.assertEqual(first.parent, cache._cache_dir)

    def test_packaged_icon_wins_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            static_dir = root / "static"
            (static_dir / "egg-icons").mkdir(parents=True)
            packaged = static_dir / "egg-icons" / "107249.webp"
            packaged.write_bytes(b"packaged")
            cache = EggIconCache(static_dir, root / "cache")
            with mock.patch("spritelens.web.egg_icon_cache.urlopen") as download:
                self.assertEqual(asyncio.run(cache.resolve("107249.webp")), packaged)
                self.assertEqual(asyncio.run(cache.resolve("_fallback.webp")), None)
            download.assert_not_called()

    def test_unknown_or_invalid_name_never_requests_cloud(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = EggIconCache(Path(directory) / "static", Path(directory) / "cache")
            with mock.patch("spritelens.web.egg_icon_cache.urlopen") as download:
                self.assertIsNone(asyncio.run(cache.resolve("not-an-icon.webp")))
                self.assertIsNone(asyncio.run(cache.resolve("../../etc/passwd")))
            download.assert_not_called()

    def test_missing_icon_is_negatively_cached(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = EggIconCache(Path(directory) / "static", Path(directory) / "cache")
            failure = HTTPError(_SOURCE.format(id=999999), 404, "Not Found", None, None)
            with mock.patch(
                "spritelens.web.egg_icon_cache.urlopen", side_effect=failure
            ) as download:
                self.assertIsNone(asyncio.run(cache.resolve("999999.webp")))
                self.assertIsNone(asyncio.run(cache.resolve("999999.webp")))
            self.assertEqual(download.call_count, 1)

    def test_unexpected_host_is_not_written_to_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = EggIconCache(root / "static", root / "cache")
            response = _Response(_png(), "https://evil.example.com/items/bag/150006.png")
            with mock.patch("spritelens.web.egg_icon_cache.urlopen", return_value=response):
                self.assertIsNone(asyncio.run(cache.resolve("150006.webp")))
            self.assertFalse((root / "cache" / "150006.webp").exists())


if __name__ == "__main__":
    unittest.main()
