"""崩溃日志（excepthook 兜底）测试：pythonw 启动下未捕获异常必须落盘。"""

import contextlib
import io
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from spritelens.logs.local_logger import install_excepthook


def _fire_excepthook() -> None:
    """触发钩子；吞掉转发给 stderr 的 traceback，保持测试输出干净。"""
    with contextlib.redirect_stderr(io.StringIO()):
        sys.excepthook(*sys.exc_info())


class ExcepthookTest(unittest.TestCase):
    def setUp(self):
        # 保存并还原全局钩子，避免影响其他测试与测试进程自身
        self._saved = (sys.excepthook, threading.excepthook)

        def _restore():
            sys.excepthook, threading.excepthook = self._saved

        self.addCleanup(_restore)

    def test_main_thread_exception_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            crash = install_excepthook(Path(tmp))
            try:
                raise ValueError("主线程炸了")
            except ValueError:
                _fire_excepthook()

            text = crash.read_text(encoding="utf-8")
        self.assertIn("主线程", text)
        self.assertIn("主线程炸了", text)
        self.assertIn("ValueError", text)

    def test_background_thread_exception_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            crash = install_excepthook(Path(tmp))

            def boom() -> None:
                raise RuntimeError("后台线程炸了")

            thread = threading.Thread(target=boom, name="sl-crash-test")
            thread.start()
            thread.join()

            text = crash.read_text(encoding="utf-8")
        self.assertIn("sl-crash-test", text)
        self.assertIn("后台线程炸了", text)

if __name__ == "__main__":
    unittest.main()
