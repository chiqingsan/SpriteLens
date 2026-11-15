from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from spritelens.repositories.settings import SettingsRepository
from spritelens.view_models.ui_preferences import UIPreferencesViewModel


class OnboardingTests(unittest.TestCase):
    def test_new_install_persists_until_completed(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            config, database = Path(root) / "config.json", Path(root) / "spritelens.sqlite"
            settings = SettingsRepository.for_application(config, database)
            self.assertTrue(UIPreferencesViewModel(settings).snapshot()["onboarding_pending"])
            restarted = SettingsRepository.for_application(config, database)
            self.assertTrue(UIPreferencesViewModel(restarted).snapshot()["onboarding_pending"])
            UIPreferencesViewModel(restarted).update({"onboarding_pending": False})
            self.assertFalse(UIPreferencesViewModel(SettingsRepository.for_application(config, database)).snapshot()["onboarding_pending"])

    def test_existing_install_is_not_prompted(self) -> None:
        for existing in ("config.json", "spritelens.sqlite"):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as root:
                config, database = Path(root) / "config.json", Path(root) / "spritelens.sqlite"
                (Path(root) / existing).write_text("{}", encoding="utf-8")
                settings = SettingsRepository.for_application(config, database)
                self.assertFalse(UIPreferencesViewModel(settings).snapshot()["onboarding_pending"])

    def test_save_failure_keeps_pending(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            settings = SettingsRepository.for_application(Path(root) / "config.json", Path(root) / "db")
            with patch.object(settings, "_save_locked", side_effect=OSError("disk")):
                with self.assertRaises(OSError):
                    UIPreferencesViewModel(settings).update({"onboarding_pending": False})
            self.assertTrue(UIPreferencesViewModel(settings).snapshot()["onboarding_pending"])

    def test_new_install_write_failure_is_not_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as root, patch.object(SettingsRepository, "_save_locked", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                SettingsRepository.for_application(Path(root) / "config.json", Path(root) / "db")

    def test_bad_config_is_not_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            config = Path(root) / "config.json"
            config.write_text("bad", encoding="utf-8")
            settings = SettingsRepository.for_application(config, Path(root) / "db")
            with self.assertRaises(ValueError):
                UIPreferencesViewModel(settings).snapshot()
            self.assertEqual(config.read_text(encoding="utf-8"), "bad")


if __name__ == "__main__":
    unittest.main()
