from __future__ import annotations

import asyncio
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from PIL import Image

from spritelens.web.account_avatar_cache import AccountAvatarCache


class _Response:
    def __init__(self, raw: bytes, url: str) -> None:
        self.status = 200
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


def _png() -> bytes:
    output = BytesIO()
    Image.new("RGBA", (2, 2), (95, 125, 72, 255)).save(output, "PNG")
    return output.getvalue()


class AccountAvatarCacheTest(unittest.TestCase):
    def test_downloads_once_then_uses_user_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mapping_dir = root / "static" / "account-avatars"
            mapping_dir.mkdir(parents=True)
            source = "https://wegame.shallow.ink/api/v1/resources/wiki/assets/profile/avatar/1001017.png"
            (mapping_dir / "manifest.json").write_text(
                json.dumps({"assets": [{"id": 1001017, "source_url": source}]}),
                encoding="utf-8",
            )
            cache = AccountAvatarCache(root / "static", root / "data-cache")
            response = _Response(_png(), source)
            with mock.patch(
                "spritelens.web.account_avatar_cache.urlopen", return_value=response
            ) as download:
                first = asyncio.run(cache.resolve("1001017.png"))
                second = asyncio.run(cache.resolve("1001017.png"))

            self.assertIsNotNone(first)
            self.assertEqual(first, second)
            self.assertEqual(download.call_count, 1)
            self.assertEqual(first.read_bytes(), _png())

    def test_unknown_or_invalid_asset_does_not_request_cloud_resource(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mapping_dir = root / "static" / "account-avatars"
            mapping_dir.mkdir(parents=True)
            (mapping_dir / "manifest.json").write_text(
                json.dumps({"assets": [{"id": 1001017, "source_url": "https://wegame.shallow.ink/api/v1/resources/wiki/assets/profile/avatar/1001017.png"}]}),
                encoding="utf-8",
            )
            cache = AccountAvatarCache(root / "static", root / "data-cache")
            with mock.patch("spritelens.web.account_avatar_cache.urlopen") as download:
                self.assertIsNone(asyncio.run(cache.resolve("9999999.png")))
                self.assertIsNone(asyncio.run(cache.resolve("not-an-avatar.png")))
            download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
