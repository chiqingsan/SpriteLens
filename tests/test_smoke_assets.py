"""打包自检（--smoke-test）的资源检查测试。

背景：静态目录 spritelens/web/static 是包内资源，Nuitka 只编译 .py
不会自动带上它。曾因此打出「smoke 通过却启动即崩」的 exe（服务报
`web/static does not exist`），所以资源检查必须进 smoke-test。

这里不 mock 全局路径，而是直接核对真实资源——它同时是「仓库自包含」
的守护测试：任何随包分发的资源被误删/误忽略都会在此变红。
"""

from __future__ import annotations

import unittest

import spritelens.paths as paths
from spritelens.web.server import STATIC_DIR


class PackagedAssetsTest(unittest.TestCase):
    """随包分发的资源必须真实存在（打包漏带/被 gitignore 误伤都会红灯）。"""

    def test_frontend_static_dir_exists(self):
        self.assertTrue(STATIC_DIR.is_dir(), f"前端静态目录缺失: {STATIC_DIR}")

    def test_frontend_entry_files_exist(self):
        for name in ("index.html", "boot.js", "ui.js", "app.js", "app.css", "ui.css", "themes.css", "appearance.js", "pet-presentation.js", "pet-filters.js", "backpack-controls.js", "icons.js", "icons/sprite.svg"):
            with self.subTest(file=name):
                self.assertTrue((STATIC_DIR / name).is_file(), f"前端文件缺失: {name}")

    def test_static_tables_exist(self):
        static_dir = paths.static_dir()
        self.assertTrue(static_dir.is_dir(), f"静态映射表目录缺失: {static_dir}")
        for name in ("species.json", "natures.json", "types.json", "skills.json", "pet_media.json"):
            with self.subTest(file=name):
                self.assertTrue((static_dir / name).is_file(), f"静态表缺失: {name}")

    def test_schema_dir_exists(self):
        schema_dir = paths.schema_dir()
        self.assertTrue(schema_dir.is_dir(), f"schema 目录缺失: {schema_dir}")
        self.assertTrue((schema_dir / "opcodes.json").is_file(), "opcode 目录缺失")

    def test_smoke_asset_check_passes_in_source_tree(self):
        """源码态资源齐全时，smoke 的资源检查应返回 0。"""
        from spritelens.main import _smoke_check_assets

        self.assertEqual(0, _smoke_check_assets())


if __name__ == "__main__":
    unittest.main()
