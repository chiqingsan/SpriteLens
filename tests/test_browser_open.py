"""浏览器调试入口：鉴权、当前服务 URL 与系统打开失败。"""

from __future__ import annotations

import tempfile
import unittest
import webbrowser
from pathlib import Path
from unittest.mock import patch

from spritelens.web.server import LocalServer
from tests.test_web_server import _http_post, _make_context


class BrowserOpenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.context = _make_context(Path(cls.tmp.name))
        cls.server = LocalServer(cls.context, token="browser-test-token", port=0)
        cls.server.start()
        cls.endpoint = f"http://{cls.server.host}:{cls.server.port}/api/ui/open-browser"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop()
        cls.context.close()
        cls.tmp.cleanup()

    def test_opens_current_authenticated_page(self) -> None:
        with patch("spritelens.web.server.webbrowser.open", return_value=True) as opener:
            status, payload = _http_post(self.endpoint, self.server.token, {})
        self.assertEqual((status, payload), (200, {"ok": True}))
        opener.assert_called_once_with(self.server.url, new=2)

    def test_unauthorized_request_does_not_open_browser(self) -> None:
        with patch("spritelens.web.server.webbrowser.open") as opener:
            for token in ("", "incorrect-token"):
                with self.subTest(token=token):
                    status, _ = _http_post(self.endpoint, token, {})
                    self.assertEqual(status, 401)
        opener.assert_not_called()

    def test_browser_failure_is_reported(self) -> None:
        for failure in (False, OSError("launch failed"), webbrowser.Error("no browser")):
            with self.subTest(failure=failure):
                options = {"side_effect": failure} if isinstance(failure, Exception) else {"return_value": failure}
                with patch("spritelens.web.server.webbrowser.open", **options):
                    status, payload = _http_post(self.endpoint, self.server.token, {})
                self.assertEqual(status, 503)
                self.assertIn("默认浏览器", payload["error"])


if __name__ == "__main__":
    unittest.main()
