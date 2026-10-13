"""窗口图标的 Win32 边界：大小图标消息、64 位句柄与加载失败。"""

from __future__ import annotations

import unittest
from unittest.mock import Mock, call, patch

from spritelens.web.run import _apply_window_icons


class AppIconsTest(unittest.TestCase):
    def test_sets_small_and_large_icons_with_pointer_sized_handles(self):
        user32 = Mock()
        handles = (0x123456789, 0x23456789A)
        hwnd = 0x3456789AB
        user32.LoadImageW.side_effect = handles

        with patch("ctypes.WinDLL", return_value=user32, create=True):
            _apply_window_icons(hwnd, "app.ico")

        self.assertEqual(user32.SendMessageW.call_args_list, [
            call(hwnd, 0x80, 1, handles[0]),
            call(hwnd, 0x80, 0, handles[1]),
        ])
        import ctypes
        from ctypes import wintypes

        self.assertEqual(user32.LoadImageW.restype, wintypes.HANDLE)
        self.assertEqual(user32.SendMessageW.restype, ctypes.c_ssize_t)
        self.assertEqual(user32.SendMessageW.argtypes, [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        ])

    def test_icon_load_failure_is_reported(self):
        user32 = Mock()
        user32.LoadImageW.return_value = None
        error = OSError("图标加载失败")
        with patch("ctypes.WinDLL", return_value=user32, create=True), \
                patch("ctypes.WinError", return_value=error, create=True):
            with self.assertRaises(OSError):
                _apply_window_icons(1, "missing.ico")
        user32.SendMessageW.assert_not_called()


if __name__ == "__main__":
    unittest.main()
