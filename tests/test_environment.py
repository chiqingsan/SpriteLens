"""Npcap 环境检测与安装引导的单元测试（网络与提权不真实触发）。"""

import tempfile
import unittest
from unittest import mock
from pathlib import Path

import spritelens.system.environment as environment
from spritelens.system.environment import check_npcap, parse_dist_page

_SAMPLE_HTML = """
<html><body>
<a href="npcap-1.10.exe">npcap-1.10.exe</a>
<a href="npcap-1.79.exe">npcap-1.79.exe</a>
<a href="npcap-1.9.2.exe">npcap-1.9.2.exe</a>
</body></html>
"""


class CheckNpcapTest(unittest.TestCase):
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


class NpcapInstallerTransferTest(unittest.TestCase):
    def test_powershell_download_validates_and_atomically_promotes(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest_dir = Path(tmp)
            expected_tmp = dest_dir / "npcap-1.0.exe.part"

            def fake_run(command, **kwargs):
                self.assertEqual(command[0], "powershell.exe")
                expected_tmp.write_bytes(b"MZ" + b"installer")
                return mock.Mock(stdout="", returncode=0)

            progress: list[float] = []
            with mock.patch.object(environment.subprocess, "run", side_effect=fake_run):
                result = environment.download_installer(
                    "https://npcap.com/dist/npcap-1.0.exe",
                    dest_dir,
                    progress_cb=progress.append,
                )

            self.assertEqual(result.read_bytes(), b"MZinstaller")
            self.assertFalse(expected_tmp.exists())
            self.assertEqual(progress, [0.0, 1.0])

    def test_powershell_script_uses_invoke_web_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest_dir = Path(tmp)
            expected_tmp = dest_dir / "npcap-1.0.exe.part"

            def fake_run(command, **kwargs):
                script = command[-1]
                self.assertIn("Invoke-WebRequest", script)
                self.assertIn("-OutFile", script)
                expected_tmp.write_bytes(b"MZinstaller")
                return mock.Mock(stdout="", returncode=0)

            with mock.patch.object(environment.subprocess, "run", side_effect=fake_run):
                environment.download_installer(
                    "https://npcap.com/dist/npcap-1.0.exe", dest_dir
                )

    def test_unavailable_powershell_falls_back_to_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest_dir = Path(tmp)
            result_path = dest_dir / "npcap-1.0.exe"

            def python_download(url, dest, part, **kwargs):
                part.write_bytes(b"MZpython")
                part.replace(dest)
                return dest

            with (
                mock.patch.object(environment, "_download_with_powershell", side_effect=FileNotFoundError()),
                mock.patch.object(environment, "_download_with_python", side_effect=python_download) as fallback,
            ):
                result = environment.download_installer(
                    "https://npcap.com/dist/npcap-1.0.exe", dest_dir
                )

            fallback.assert_called_once()
            self.assertEqual(result, result_path)
            self.assertEqual(result.read_bytes(), b"MZpython")

    def test_powershell_network_failure_falls_back_to_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest_dir = Path(tmp)

            def python_download(url, dest, part, **kwargs):
                part.write_bytes(b"MZpython")
                part.replace(dest)
                return dest

            with (
                mock.patch.object(
                    environment,
                    "_download_with_powershell",
                    side_effect=RuntimeError("网络失败"),
                ),
                mock.patch.object(environment, "_download_with_python", side_effect=python_download),
            ):
                result = environment.download_installer(
                    "https://npcap.com/dist/npcap-1.0.exe", dest_dir
                )

            self.assertTrue(result.is_file())
            self.assertEqual(result.read_bytes(), b"MZpython")

    def test_both_download_paths_fail_without_leaving_installer(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest_dir = Path(tmp)
            with (
                mock.patch.object(
                    environment,
                    "_download_with_powershell",
                    side_effect=RuntimeError("PowerShell 失败"),
                ),
                mock.patch.object(
                    environment,
                    "_download_with_python",
                    side_effect=RuntimeError("Python 失败"),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "npcap.com/#download"):
                    environment.download_installer(
                        "https://npcap.com/dist/npcap-1.0.exe", dest_dir
                    )

            self.assertFalse((dest_dir / "npcap-1.0.exe").exists())
            self.assertFalse((dest_dir / "npcap-1.0.exe.part").exists())

    def test_invalid_download_is_rejected_before_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            installer = Path(tmp) / "npcap.exe"
            installer.write_bytes(b"not-pe")
            with mock.patch.object(environment.subprocess, "run") as run:
                with self.assertRaisesRegex(RuntimeError, "PE"):
                    environment.launch_installer(installer)
            run.assert_not_called()

    def test_empty_download_is_rejected_before_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            installer = Path(tmp) / "npcap.exe"
            installer.write_bytes(b"")
            with mock.patch.object(environment.subprocess, "run") as run:
                with self.assertRaisesRegex(RuntimeError, "为空"):
                    environment.launch_installer(installer)
            run.assert_not_called()

    def test_powershell_launch_waits_and_returns_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            installer = Path(tmp) / "npcap.exe"
            installer.write_bytes(b"MZinstaller")
            completed = mock.Mock(stdout="SPRITELENS_EXIT:0\n", returncode=0)
            with mock.patch.object(environment.subprocess, "run", return_value=completed) as run:
                self.assertEqual(environment.launch_installer(installer), 0)
            self.assertEqual(run.call_args.args[0][0], "powershell.exe")

    def test_powershell_launch_failure_falls_back_to_native_wait(self):
        with tempfile.TemporaryDirectory() as tmp:
            installer = Path(tmp) / "npcap.exe"
            installer.write_bytes(b"MZinstaller")
            ps_error = environment.subprocess.CalledProcessError(1, "powershell.exe")
            native = mock.Mock(returncode=0)
            with mock.patch.object(
                environment.subprocess,
                "run",
                side_effect=[ps_error, native],
            ) as run:
                self.assertEqual(environment.launch_installer(installer), 0)
            self.assertEqual(run.call_count, 2)

if __name__ == "__main__":
    unittest.main()
