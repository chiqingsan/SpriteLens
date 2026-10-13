"""将原生迁移桥接的切号/乱序回归纳入工程门禁。"""
from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path


class AccountRequestsTest(unittest.TestCase):
    def test_account_generation_sequence_owner_and_domain_version(self) -> None:
        root = Path(__file__).resolve().parents[1]
        node = shutil.which("node")
        self.assertIsNotNone(node, "F02 请求时序验收需要 Node")
        result = subprocess.run([node, str(root / "tests/account_requests_cases.js"),
            str(root / "spritelens/web/static/account-requests.js")],
            capture_output=True, text=True, encoding="utf-8", timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
