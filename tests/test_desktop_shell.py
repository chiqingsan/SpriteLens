"""桌面窗口位置、DPI、已保存尺寸的适配与恢复。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from spritelens.system import window_geometry


class WindowGeometryTests(unittest.TestCase):
    def test_position_keeps_secondary_screen_and_recovers_offscreen(self) -> None:
        fit = window_geometry.fit_window_position
        self.assertEqual(fit(-1400, 100, 1180, 730, (-1920, 0, 0, 1040)), (-1400, 100))
        self.assertEqual(fit(-1400, 100, 1180, 730, (0, 0, 1920, 1040)), (0, 100))
        self.assertEqual(fit(1800, 1000, 1180, 730, (0, 40, 1920, 1040)), (740, 310))
    def test_small_screen_keeps_workarea(self) -> None:
        # 小屏由高度限制等比缩小，不能只截断高度。
        width, height = window_geometry.fit_window(1366, 728, 96)
        self.assertEqual((width, height), (1237, 696))

    def test_dpi_converts_to_logical(self) -> None:
        # 150% 缩放：物理工作区转逻辑后仍受 1440x810 上限约束
        # （用户实测蛋神：逻辑 1440x810 = 物理 2160x1215，截图量到 2142x1206 含边框差）
        width, height = window_geometry.fit_window(2560, 1396, 144)
        self.assertEqual((width, height), (1440, 810))

    def test_saved_dimensions_preserve_ratio_and_fit_a_smaller_screen(self) -> None:
        self.assertEqual(window_geometry.fit_window(2560, 1528, 144, width=1443, height=718), (1443, 718))
        width, height = window_geometry.fit_window(1366, 728, 96, width=1900, height=950)
        self.assertEqual((width, height), (1334, 667))
        self.assertEqual(width / height, 2)

class WindowGeometryStoreTests(unittest.TestCase):
    def test_roundtrip_and_default(self) -> None:
        import tempfile
        from spritelens.repositories.settings import SettingsRepository
        with tempfile.TemporaryDirectory() as tmp:
            settings = SettingsRepository(Path(tmp) / "config.json")
            self.assertIsNone(settings.window_geometry())  # 未记录过
            settings.set_window_geometry(width=1180, height=730, maximized=False)
            geometry = settings.window_geometry()
            self.assertEqual((geometry["width"], geometry["height"]), (1180, 730))
            self.assertFalse(geometry["maximized"])
            self.assertEqual((geometry["x"], geometry["y"]), (None, None))
            settings.set_window_geometry(width=1180, height=730, maximized=False, x=-1400, y=100)
            restored = SettingsRepository(Path(tmp) / "config.json").window_geometry()
            self.assertEqual((restored["x"], restored["y"]), (-1400, 100))


if __name__ == "__main__":
    unittest.main()
