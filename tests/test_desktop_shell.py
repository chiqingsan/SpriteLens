"""桌面壳：窗口几何适配 + WebView2 预检测的可测部分。"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from spritelens.system import webview_guard, window_geometry


class WindowGeometryTests(unittest.TestCase):
    def test_default_on_1080p(self) -> None:
        # 1920x1040 工作区 + 100% 缩放 → 默认 1280x720
        self.assertEqual(window_geometry.fit_window(1920, 1040, 96), (1280, 720))

    def test_small_screen_clamps_to_workarea(self) -> None:
        # 1366x728 工作区 → 90% 上限
        width, height = window_geometry.fit_window(1366, 728, 96)
        self.assertLessEqual(width, int(1366 * 0.9))
        self.assertLessEqual(height, int(728 * 0.9))

    def test_dpi_scales_up(self) -> None:
        # 150% 缩放：1280*1.5=1920 超出上限 → 受工作区 90% 约束
        width, height = window_geometry.fit_window(2560, 1400, 144)
        self.assertEqual((width, height), (1920, 1080))

    def test_never_below_minimum(self) -> None:
        width, height = window_geometry.fit_window(700, 400, 96)
        self.assertGreaterEqual(width, 630)  # min(640, 700)
        self.assertGreaterEqual(height, 360)


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
