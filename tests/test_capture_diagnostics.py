"""C01 的诊断语义、刷新失败及互斥回归。"""
from __future__ import annotations

import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from spritelens.capture.base import SourceError
from spritelens.system.environment import NpcapReport
from spritelens.view_models.capture_diagnostics import capture_diagnostics
from spritelens.view_models.capture_vm import CaptureSnapshot, EnvironmentBusyError
from spritelens.services.session_tracker import Totals
from tests.test_web_server import _make_context, _http_get, _http_post
from spritelens.web.server import LocalServer


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.report = NpcapReport(True, None, "驱动就绪")
        self.snapshot = CaptureSnapshot(False, "", 0, (), Totals(0, 0, 0, 0, 0), False, 0, "", False)

    def checks(self, **changes):
        return {row["id"]: row for row in capture_diagnostics(replace(self.snapshot, **changes), self.report,
            port=8195, extra_ports=(8196,), environment_error="")}

    def test_observations_do_not_claim_current_health(self):
        self.assertEqual(self.checks()["capture"]["status"], "idle")
        self.assertEqual(self.checks(running=True)["capture"]["status"], "waiting")
        self.assertIn("重新登录", self.checks(running=True)["decrypt"]["message"])
        self.assertIn("已有密钥", self.checks(any_key=True)["decrypt"]["message"])
        rows = self.checks(running=True, totals=Totals(5, 2, 3, 4, 1, 8, 100),
            dropped_chunks=1, dropped_segments=2, event_log_dropped=3, event_log_error="磁盘满")
        self.assertIn("不代表当前连接", rows["decrypt"]["message"])
        for text in ("解密失败 2", "解析失败 4", "缺密钥 3", "采集队列丢弃 1", "重组丢弃 2", "日志丢弃 3", "磁盘满"):
            self.assertIn(text, rows["warnings"]["message"])
        self.assertIn("8195、8196", rows["network"]["message"])
        self.assertEqual(self.checks(last_error="启动失败")["capture"]["status"], "error")

    def test_environment_actions_and_stale_report(self):
        for report, action in ((NpcapReport(False, None, "缺驱动"), "install"),
                               (NpcapReport(True, None, "RSC", True, "网卡"), "rsc")):
            row = capture_diagnostics(self.snapshot, report, port=8195, extra_ports=(), environment_error="探测失败")[0]
            self.assertIn(action, row["actions"])
            self.assertIn("上次检测结果", row["message"])
            self.assertEqual(row["status"], "error")

    def test_refresh_is_exclusive_and_preserves_report_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _make_context(Path(tmp)); vm = ctx.capture_vm
            old = vm.environment_report()
            entered, release = threading.Event(), threading.Event()
            def probe():
                entered.set()
                if not release.wait(3): raise TimeoutError("测试超时")
                return self.report
            with mock.patch.object(vm, "_environment_probe", side_effect=probe):
                worker = threading.Thread(target=vm.refresh_environment)
                worker.start()
                try:
                    self.assertTrue(entered.wait(2))
                    with self.assertRaises(EnvironmentBusyError): vm.refresh_environment()
                    self.assertIs(vm.environment_report(), old)
                    self.assertTrue(vm.environment_checking)
                    checking = capture_diagnostics(self.snapshot, self.report, port=8195,
                        extra_ports=(), environment_error="", environment_checking=True)[0]
                    self.assertEqual(checking["status"], "waiting")
                finally:
                    release.set(); worker.join(3)
            with mock.patch.object(vm, "_environment_probe", side_effect=OSError("探测失败")):
                with self.assertRaises(OSError): vm.refresh_environment()
            self.assertIs(vm.environment_report(), self.report)
            self.assertEqual(vm.environment_error, "探测失败")
            with mock.patch.object(vm, "_environment_probe", return_value=self.report): vm.refresh_environment()
            self.assertEqual(vm.environment_error, "")
            ctx.close()

    def test_http_contract_and_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _make_context(Path(tmp)); server = LocalServer(ctx, port=0)
            server.start(); base = f"http://127.0.0.1:{server.port}"
            try:
                url = base + "/api/capture/environment"
                with mock.patch.object(ctx.capture_vm, "_environment_probe", return_value=self.report) as probe:
                    self.assertEqual(_http_post(url, "invalid", {})[0], 401)
                    probe.assert_not_called()
                    status, payload = _http_post(url, server.token, {})
                    self.assertEqual(status, 200); probe.assert_called_once()
                    self.assertEqual(payload["port"], 8195)
                    _, state = _http_get(base + "/api/state", server.token)
                    self.assertEqual(payload["diagnostics"], state["capture"]["diagnostics"])
                    self.assertIn("decrypt_ok", state["capture"])
                with mock.patch.object(ctx.capture_vm, "_environment_probe", side_effect=OSError("检测失败")):
                    self.assertEqual(_http_post(url, server.token, {})[0], 500)
                    _, payload = _http_get(base + "/api/capture", server.token)
                    self.assertTrue(payload["environment"]["installed"])
                    self.assertIn("检测失败", payload["diagnostics"][0]["message"])
                with mock.patch.object(ctx.capture_vm, "refresh_environment", side_effect=EnvironmentBusyError("进行中")):
                    self.assertEqual(_http_post(url, server.token, {})[0], 409)
                with mock.patch.object(ctx.capture_vm, "refresh_ifaces", side_effect=SourceError("枚举失败")):
                    self.assertEqual(_http_get(base + "/api/capture/ifaces", server.token)[0], 500)
            finally:
                server.stop(); ctx.close()
