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

    def test_keyboard_interrupt_is_not_logged(self):
        """Ctrl+C 属正常退出路径，不应污染崩溃日志。"""
        with tempfile.TemporaryDirectory() as tmp:
            crash = install_excepthook(Path(tmp))
            try:
                raise KeyboardInterrupt
            except KeyboardInterrupt:
                _fire_excepthook()

            exists = crash.exists()
        self.assertFalse(exists, "KeyboardInterrupt 不应写入 crash.log")

    def test_write_failure_does_not_raise(self):
        """日志目录不可写时钩子不得二次抛出（崩溃现场写入失败要静默）。"""
        missing = Path("Z:/definitely-not-exist/logs")
        crash = install_excepthook(missing)
        try:
            raise RuntimeError("目录不可写")
        except RuntimeError:
            _fire_excepthook()  # 不应抛出
        self.assertEqual(missing / crash.name, crash)

    def test_successive_crashes_append(self):
        """多次崩溃追加到同一文件，不互相覆盖。"""
        with tempfile.TemporaryDirectory() as tmp:
            crash = install_excepthook(Path(tmp))
            for message in ("第一次", "第二次"):
                try:
                    raise ValueError(message)
                except ValueError:
                    _fire_excepthook()
            text = crash.read_text(encoding="utf-8")
        self.assertIn("第一次", text)
        self.assertIn("第二次", text)


if __name__ == "__main__":
    unittest.main()
