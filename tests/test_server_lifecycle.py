"""本地服务生命周期与入口清理回归（D06/D07）。

覆盖：
- start 超时的确定性回收（loop 未建 / 启动中 / 绑定后 三条路径）；
- 超时后重复 stop 安全、不留下晚到的 HTTP 服务；
- run_web 入口的 guard/部分资源清理（装配失败、LocalServer 构造失败）。

不依赖真实网卡与浏览器；HTTP 探测用回环连接失败判定。
"""

from __future__ import annotations

import asyncio
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from spritelens.web.server import LocalServer


def _make_context(tmp: Path):
    from tests.test_web_server import _make_context as make
    return make(tmp)


def _port_serving(port: int) -> bool:
    """port 上是否有可连接的 HTTP 服务（用于验证没有晚到的服务）。"""
    if not port:
        return False
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


class StartTimeoutReclaimTest(unittest.TestCase):
    """D06：start 超时后三种到达时机都被确定性回收。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)

    def _server(self, cls=LocalServer):
        return cls(_make_context(self.tmp_path), token="t-lifecycle", port=0)

    def test_timeout_before_loop_creation(self):
        """超时发生在 loop 创建前：线程入口检查 _stopped 直接退出。"""
        entered = threading.Event()
        release = threading.Event()

        class _PausedEntry(LocalServer):
            def _run_loop(self):
                entered.set()
                release.wait(timeout=10)
                super()._run_loop()

        server = self._server(_PausedEntry)
        # 让线程停在入口，再让 start 超时；随后释放入口——_stopped 已置位，
        # 真 _run_loop 必须立即退出而不是补启动一个服务
        threading.Timer(0.6, release.set).start()
        with self.assertRaises(TimeoutError):
            server.start(timeout=0.15)
        self.assertTrue(entered.wait(timeout=5), "线程未进入暂停入口")
        time.sleep(0.9)  # 等待释放后真 _run_loop 走完
        self.assertFalse(server.running)
        self.assertFalse(_port_serving(server.port))
        server.stop()  # 重复 stop 安全
        self.assertFalse(_port_serving(server.port))

    def test_timeout_during_startup(self):
        """超时发生在 _start_async 执行中：loop 被停、半成品清理、不晚到。"""
        release = threading.Event()

        class _SlowStart(LocalServer):
            async def _start_async(self):
                await asyncio.sleep(0.5)  # 模拟慢启动（loop 已运行）
                await super()._start_async()

        server = self._server(_SlowStart)
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            server.start(timeout=0.15)
        self.assertLess(time.monotonic() - started, 5, "超时回收不应超过预算")
        time.sleep(0.8)  # 给慢启动协程收尾时间
        self.assertFalse(server.running)
        self.assertFalse(server._thread is not None and server._thread.is_alive())
        self.assertFalse(_port_serving(server.port), "超时后不得留下可连接服务")
        server.stop()

    def test_timeout_after_bind(self):
        """超时发生在绑定完成后：清理 runner 并退出，不进入 run_forever。"""
        bound = threading.Event()

        class _SlowAfterBind(LocalServer):
            async def _start_async(self):
                await super()._start_async()
                self._bound_seen = True
                bound.set()
                await asyncio.sleep(0.6)  # 绑定后拖延：ready 尚未置位

        server = self._server(_SlowAfterBind)
        with self.assertRaises(TimeoutError):
            server.start(timeout=0.2)
        self.assertTrue(bound.wait(timeout=5), "未观察到绑定完成")
        time.sleep(1.0)  # 等取消路径收尾
        self.assertFalse(server.running)
        self.assertFalse(_port_serving(server.port), "绑定后超时必须回收 socket")
        server.stop()  # 幂等

    def test_normal_start_stop_unchanged(self):
        """正常启停行为不受回收逻辑影响（对照）。"""
        server = self._server()
        server.start(timeout=10)
        try:
            self.assertTrue(server.running)
            self.assertTrue(_port_serving(server.port))
        finally:
            server.stop()
        self.assertFalse(_port_serving(server.port))
        server.stop()  # 重复 stop


class RunWebEntryGuardTest(unittest.TestCase):
    """D07：run_web 入口的 guard 与部分资源清理。"""

    def _patch_common(self, run_mod):
        return [
            mock.patch.object(run_mod, "setup_logger"),
            mock.patch.object(run_mod, "_enable_dpi_awareness"),
            mock.patch.object(run_mod, "_set_app_user_model_id"),
            mock.patch("spritelens.system.webview_guard.ensure_webview2", return_value=True),
            mock.patch.object(run_mod, "_fatal"),
        ]

    def test_explicit_abandon_exits_without_entering_cleanup(self):
        import spritelens.web.run as run_mod

        context, server, guard = mock.Mock(), mock.Mock(), mock.Mock()
        force_exit = mock.Mock()
        patches = [
            *self._patch_common(run_mod),
            mock.patch.object(run_mod, "SingleInstanceGuard", return_value=guard),
            mock.patch.object(run_mod, "build_app_context", return_value=context),
            mock.patch.object(run_mod, "LocalServer", return_value=server),
            mock.patch.object(run_mod, "_run_window", return_value=False),
            mock.patch.object(run_mod.os, "_exit", force_exit),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.assertEqual(run_mod.run_web(), 1)
        force_exit.assert_called_once_with(1)
        context.close.assert_not_called()
        server.stop.assert_not_called()
        guard.close.assert_not_called()

    def test_successful_window_close_keeps_normal_cleanup(self):
        import spritelens.web.run as run_mod

        context, server, guard, force_exit = mock.Mock(), mock.Mock(), mock.Mock(), mock.Mock()
        patches = [
            *self._patch_common(run_mod),
            mock.patch.object(run_mod, "SingleInstanceGuard", return_value=guard),
            mock.patch.object(run_mod, "build_app_context", return_value=context),
            mock.patch.object(run_mod, "LocalServer", return_value=server),
            mock.patch.object(run_mod, "_run_window", return_value=True),
            mock.patch.object(run_mod.os, "_exit", force_exit),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.assertEqual(run_mod.run_web(), 0)
        force_exit.assert_not_called()
        server.stop.assert_called_once()
        context.close.assert_called_once()
        guard.close.assert_called_once()

    def test_explicit_abandon_terminates_process_with_blocked_request_worker(self):
        """使用真实 to_thread 工作线程；不能用 Mock(_exit) 验证进程退出。"""
        import subprocess
        import sys
        import textwrap
        from pathlib import Path

        script = textwrap.dedent('''
            import asyncio
            import threading
            from unittest.mock import Mock, patch
            import spritelens.web.run as run
            from spritelens.web.server import LocalServer

            blocked = threading.Event()
            def request():
                blocked.set()
                threading.Event().wait()

            def worker():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                server = object.__new__(LocalServer)
                server._blocking_tasks = set()
                loop.create_task(server._run_blocking(request))
                loop.run_forever()

            threading.Thread(target=worker, daemon=True).start()
            assert blocked.wait(2)
            print("request blocked", flush=True)
            context, server, guard = Mock(), Mock(), Mock()
            def forbidden(*args, **kwargs):
                print("unexpected cleanup", flush=True)
                threading.Event().wait()
            server.stop.side_effect = forbidden
            context.close.side_effect = forbidden
            with patch.object(run, "setup_logger"), \\
                 patch.object(run, "logs_dir", return_value="unused"), \\
                 patch.object(run, "_enable_dpi_awareness"), \\
                 patch.object(run, "_set_app_user_model_id"), \\
                 patch("spritelens.system.webview_guard.ensure_webview2", return_value=True), \\
                 patch.object(run, "SingleInstanceGuard", return_value=guard), \\
                 patch.object(run, "build_app_context", return_value=context), \\
                 patch.object(run, "LocalServer", return_value=server), \\
                 patch.object(run, "_run_window", return_value=False):
                run.run_web()
            print("unexpected normal return", flush=True)
        ''')
        child = subprocess.run([sys.executable, "-c", script],
                               cwd=Path(__file__).resolve().parents[1],
                               capture_output=True, text=True, timeout=8)
        self.assertEqual(child.returncode, 1, child.stderr)
        self.assertEqual(child.stdout.strip(), "request blocked", child.stderr)

    def test_unavailable_data_directory_is_reported_before_startup(self):
        import spritelens.web.run as run_mod

        with mock.patch.object(run_mod, "logs_dir", side_effect=PermissionError("denied")), \
             mock.patch.object(run_mod, "_fatal") as fatal, \
             mock.patch.object(run_mod, "SingleInstanceGuard") as guard:
            self.assertEqual(run_mod.run_web(), 1)
        fatal.assert_called_once_with("用户数据目录初始化失败", "denied")
        guard.assert_not_called()

    def test_main_reports_directory_failure_before_logger_is_available(self):
        import spritelens.main as main_mod

        with mock.patch.object(main_mod, "logs_dir", side_effect=PermissionError("denied")), \
             mock.patch("spritelens.web.run._fatal") as fatal, \
             mock.patch.object(main_mod, "setup_logger") as setup:
            self.assertEqual(main_mod.main([]), 1)
        fatal.assert_called_once_with("用户数据目录初始化失败", "denied")
        setup.assert_not_called()

    def test_guard_released_when_build_fails(self):
        """装配抛异常：guard 被释放、弹出可读失败提示、返回码 1。"""
        import spritelens.web.run as run_mod

        guard_calls: list[str] = []

        class _FakeGuard:
            def acquire(self):
                return True

            def close(self):
                guard_calls.append("close")

        patches = [
            mock.patch.object(run_mod, "SingleInstanceGuard", _FakeGuard),
            mock.patch.object(run_mod, "build_app_context", side_effect=RuntimeError("注入：装配失败")),
            *self._patch_common(run_mod),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        code = run_mod.run_web()
        self.assertEqual(code, 1)
        self.assertEqual(guard_calls, ["close"], "装配失败后 guard 未释放")

    def test_context_closed_when_server_construction_fails(self):
        """LocalServer 构造失败：已建 context 被关闭，guard 释放。"""
        import spritelens.web.run as run_mod

        closed: list[str] = []
        guard_calls: list[str] = []

        class _FakeGuard:
            def acquire(self):
                return True

            def close(self):
                guard_calls.append("close")

        class _FakeContext:
            def close(self):
                closed.append("context")

        patches = [
            mock.patch.object(run_mod, "SingleInstanceGuard", _FakeGuard),
            mock.patch.object(run_mod, "build_app_context", return_value=_FakeContext()),
            mock.patch.object(run_mod, "LocalServer", side_effect=RuntimeError("注入：构造失败")),
            *self._patch_common(run_mod),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        with self.assertRaises(RuntimeError):
            run_mod.run_web()
        self.assertEqual(closed, ["context"], "部分资源未清理")
        self.assertEqual(guard_calls, ["close"])


if __name__ == "__main__":
    unittest.main()
