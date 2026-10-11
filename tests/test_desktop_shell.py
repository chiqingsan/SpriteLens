"""桌面壳：窗口几何适配 + WebView2 预检测的可测部分。"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from spritelens.system import webview_guard, window_geometry


class WindowGeometryTests(unittest.TestCase):
    def test_default_on_1080p(self) -> None:
        # 1920x1040 工作区 + 100% 缩放 → 默认 1120x700
        self.assertEqual(window_geometry.fit_window(1920, 1040, 96), (1120, 700))

    def test_small_screen_clamps_to_workarea(self) -> None:
        # 1366x728 工作区 → 90% 上限
        width, height = window_geometry.fit_window(1366, 728, 96)
        self.assertLessEqual(width, int(1366 * 0.9))
        self.assertLessEqual(height, int(728 * 0.9))

    def test_dpi_scales_up(self) -> None:
        # 150% 缩放：1120*1.5=1680、700*1.5=1050 → 未触及工作区 90% 上限
        width, height = window_geometry.fit_window(2560, 1400, 144)
        self.assertEqual((width, height), (1680, 1050))

    def test_never_below_minimum(self) -> None:
        width, height = window_geometry.fit_window(700, 400, 96)
        self.assertGreaterEqual(width, 630)  # min(640, 700)
        self.assertGreaterEqual(height, 360)


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


class WebviewGuardTests(unittest.TestCase):
    def test_env_override_with_dll(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "webview2.dll").write_bytes(b"")
            old = os.environ.get("WEBVIEW2_RUNTIME_PATH")
            os.environ["WEBVIEW2_RUNTIME_PATH"] = tmp
            try:
                self.assertTrue(webview_guard.installed_runtime_version().startswith("custom:"))
            finally:
                if old is None:
                    os.environ.pop("WEBVIEW2_RUNTIME_PATH", None)
                else:
                    os.environ["WEBVIEW2_RUNTIME_PATH"] = old

    def test_env_override_without_dll_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:  # 目录存在但无 webview2.dll
            old = os.environ.get("WEBVIEW2_RUNTIME_PATH")
            os.environ["WEBVIEW2_RUNTIME_PATH"] = tmp
            try:
                result = webview_guard.installed_runtime_version()
                # 不应因空目录误判可用（本机若装了 WebView2 则走注册表返回版本）
                if result is not None:
                    self.assertFalse(result.startswith("custom:" + tmp))
            finally:
                if old is None:
                    os.environ.pop("WEBVIEW2_RUNTIME_PATH", None)
                else:
                    os.environ["WEBVIEW2_RUNTIME_PATH"] = old


if __name__ == "__main__":
    unittest.main()
