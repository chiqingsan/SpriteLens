"""配置失败不能丢失草稿，也不能把未落盘的值当成已保存。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from spritelens.repositories.settings import SettingsRepository


class SettingsFailureTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "config.json"
        self.original = '{"planner.draft": {"revision": 7}}'
        self.path.write_text(self.original, encoding="utf-8")
        self.settings = SettingsRepository(self.path)

    def test_read_failure_prevents_geometry_overwrite_and_can_be_retried(self):
        with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                self.settings.get_value("planner.draft")
            with self.assertRaises(PermissionError):
                self.settings.set_window_geometry(width=800, height=600, maximized=False)
        self.assertEqual(self.path.read_text(encoding="utf-8"), self.original)
        self.settings.set_window_geometry(width=800, height=600, maximized=False)
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["planner.draft"], {"revision": 7})
        self.assertEqual(saved["window.width"], 800)

    def test_invalid_json_or_non_object_cannot_be_overwritten(self):
        for raw in ("{broken", "[]", "null"):
            with self.subTest(raw=raw):
                self.path.write_text(raw, encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.settings.set("key", "new")
                self.assertEqual(self.path.read_text(encoding="utf-8"), raw)

    def test_failed_atomic_replace_preserves_disk_and_cache(self):
        self.assertEqual(self.settings.get_value("planner.draft"), {"revision": 7})
        with patch.object(Path, "replace", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                self.settings.set("planner.draft", {"revision": 8})
        self.assertEqual(self.path.read_text(encoding="utf-8"), self.original)
        self.assertEqual(self.settings.get_value("planner.draft"), {"revision": 7})
        self.settings.set("planner.draft", {"revision": 8})
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["planner.draft"], {"revision": 8})
