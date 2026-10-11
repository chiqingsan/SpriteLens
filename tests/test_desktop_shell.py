"""桌面壳：窗口几何适配 + WebView2 预检测的可测部分。"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from spritelens.system import webview_guard, window_geometry


class WindowGeometryTests(unittest.TestCase):
    def test_default_on_1080p(self) -> None:
        # 100% 缩放：工作区减 32 边距，上限 1440x810
        self.assertEqual(window_geometry.fit_window(1920, 1040, 96), (1440, 810))

    def test_small_screen_keeps_workarea(self) -> None:
        # 小屏：工作区减边距后不足上限，取实际值
        width, height = window_geometry.fit_window(1366, 728, 96)
        self.assertEqual((width, height), (1334, 696))

    def test_dpi_converts_to_logical(self) -> None:
        # 150% 缩放：物理工作区转逻辑后仍受 1440x810 上限约束
        # （用户实测蛋神：逻辑 1440x810 = 物理 2160x1215，截图量到 2142x1206 含边框差）
        width, height = window_geometry.fit_window(2560, 1396, 144)
        self.assertEqual((width, height), (1440, 810))

    def test_tiny_screen_floors(self) -> None:
        # 极小工作区不低于下限语义（返回值供 min_size 使用）
        width, height = window_geometry.fit_window(700, 400, 96)
        self.assertEqual((width, height), (668, 368))


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
