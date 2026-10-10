"""Npcap 环境检测与安装引导的单元测试（网络与提权不真实触发）。"""

import tempfile
import unittest
from pathlib import Path

from spritelens.system.environment import check_npcap, parse_dist_page

_SAMPLE_HTML = """
<html><body>
<a href="npcap-1.10.exe">npcap-1.10.exe</a>
<a href="npcap-1.79.exe">npcap-1.79.exe</a>
<a href="npcap-1.9.2.exe">npcap-1.9.2.exe</a>
</body></html>
"""


class CheckNpcapTest(unittest.TestCase):
    def test_installed_when_wpcap_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "wpcap.dll"
            fake.write_bytes(b"MZ")
            report = check_npcap(search_paths=(str(fake),), check_rsc=lambda: (False, ""))
        self.assertTrue(report.installed)
        self.assertEqual(report.wpcap_path, str(fake))

    def test_not_installed_when_missing(self):
        report = check_npcap(search_paths=("Z:/nope/wpcap.dll",))
        self.assertFalse(report.installed)
        self.assertIsNone(report.wpcap_path)
        self.assertIn("npcap.com", report.message)

    def test_rsc_enabled_reported(self):
        """RSC 开启时报告应包含警告与网卡名（一键禁用的入口）。"""
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "wpcap.dll"
            fake.write_bytes(b"MZ")
            report = check_npcap(
                search_paths=(str(fake),), check_rsc=lambda: (True, "WLAN")
            )
        self.assertTrue(report.installed)
        self.assertTrue(report.rsc_enabled)
        self.assertEqual(report.rsc_adapter, "WLAN")
        self.assertIn("RSC", report.message)

    def test_first_candidate_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "a.dll"
            second = Path(tmp) / "b.dll"
            for p in (first, second):
                p.write_bytes(b"MZ")
            report = check_npcap(search_paths=(str(first), str(second)), check_rsc=lambda: (False, ""))
        self.assertEqual(report.wpcap_path, str(first))

    def test_quick_check_skips_rsc_probe(self):
        """quick 模式只查驱动文件（毫秒级），绝不触发 RSC 的 PowerShell 探活。

        这是启动路径的契约：探测线程据此异步补 RSC，检查自身不能阻塞。
        """
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "wpcap.dll"
            fake.write_bytes(b"MZ")
            calls: list[int] = []

            def _forbidden() -> tuple[bool, str]:
                calls.append(1)
                return (True, "WLAN")

            report = check_npcap(search_paths=(str(fake),), check_rsc=_forbidden, quick=True)
        self.assertTrue(report.installed)
        self.assertFalse(report.rsc_enabled)  # 未探测，占位默认
        self.assertIn("RSC", report.message)  # 文案告知检查进行中
        self.assertEqual(calls, [], "quick 模式不得调用 RSC 探测")


class ParseDistPageTest(unittest.TestCase):
    def test_latest_version_selected(self):
        # 1.79 > 1.9.2（逐段数值比较，不是字符串比较）
        self.assertEqual(parse_dist_page(_SAMPLE_HTML), "1.79")

    def test_empty_page_returns_none(self):
        self.assertIsNone(parse_dist_page("<html></html>"))


if __name__ == "__main__":
    unittest.main()
