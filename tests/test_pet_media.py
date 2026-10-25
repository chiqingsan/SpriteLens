"""宠物头像/立绘映射：缺图不借用其它物种，登记过的同画别名除外。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import spritelens.web.pet_media as pet_media


class PetMediaTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name)
        (self.directory / "pet_media.json").write_text(
            json.dumps({
                "1001": {"normal": {"portrait": "/static/a.webp", "artwork": "/static/b.webp"}},
                "5006": {"normal": {"portrait": "/static/pet-media/5006-normal-portrait.webp"}},
            }),
            encoding="utf-8",
        )
        original = pet_media.static_dir
        pet_media.static_dir = lambda: self.directory
        self.addCleanup(setattr, pet_media, "static_dir", original)
        pet_media._index.cache_clear()
        self.addCleanup(pet_media._index.cache_clear)

    def test_own_entry_wins(self) -> None:
        self.assertEqual(pet_media.pet_images(1001)["portrait_url"], "/static/a.webp")
        self.assertEqual(pet_media.pet_images(1001)["artwork_url"], "/static/b.webp")

    def test_registered_alias_reuses_same_family_art(self) -> None:
        images = pet_media.pet_images(4012)
        self.assertEqual(images["portrait_url"], "/static/pet-media/5006-normal-portrait.webp")
        # 别名没有立绘条目时回落到别名 id 的默认路径，而不是伪造 4012 的资源。
        self.assertEqual(images["artwork_url"], "/static/pet-media/5006-normal-artwork.webp")

    def test_unregistered_missing_species_keeps_placeholder(self) -> None:
        # 4076 没有可复用的同画资源，必须保持自身路径，由前端显示首字占位。
        self.assertEqual(pet_media.pet_images(4076)["portrait_url"], "/static/pet-media/4076-normal-portrait.webp")


if __name__ == "__main__":
    unittest.main()
