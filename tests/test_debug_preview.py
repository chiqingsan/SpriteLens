from __future__ import annotations

import json
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from unittest.mock import patch

from spritelens.web.debug_preview import PreviewManager


class DebugPreviewTests(unittest.TestCase):
    def test_isolated_preview_and_shutdown(self) -> None:
        manager = PreviewManager()
        try:
            url = manager.start()
            parts = urlsplit(url)
            token = parts.fragment.removeprefix("token=")
            origin = f"{parts.scheme}://{parts.netloc}"
            def request(path: str, method: str = "GET"):
                req = Request(origin + path, headers={"X-Local-Token": token}, method=method)
                with urlopen(req, timeout=10) as response:
                    return json.load(response)
            bootstrap = request("/api/bootstrap")
            self.assertTrue(bootstrap["ui_preferences"]["onboarding_pending"])
            self.assertEqual(bootstrap["state"]["uid"], 0)
            with self.assertRaises(RuntimeError):
                manager.start()
            with self.assertRaises(HTTPError) as blocked:
                request("/api/capture/start", "POST")
            self.assertEqual(blocked.exception.code, 403)
            directory = Path(manager._directory.name)
        finally:
            manager.stop()
        self.assertFalse(directory.exists())
        manager.stop()

    def test_launch_failure_releases_temporary_directory(self) -> None:
        manager = PreviewManager()
        with patch("spritelens.web.debug_preview.subprocess.Popen", side_effect=OSError("failed")):
            with self.assertRaises(OSError):
                manager.start()
        self.assertIsNone(manager._process)
        self.assertIsNone(manager._directory)


if __name__ == "__main__":
    unittest.main()
