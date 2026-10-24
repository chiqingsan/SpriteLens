"""发布配置的关键命令行回归。"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import build


class BuildConfigTest(unittest.TestCase):
    def test_release_command_requests_uac_admin(self):
        config = build.load_config(build.DEFAULT_CONFIG)
        command = build.build_command(config, version="0.0.0")
        self.assertIn("--windows-uac-admin", command)

    def test_release_name_includes_build_timestamp(self):
        config = build.load_config(build.DEFAULT_CONFIG)
        timestamp = build.build_timestamp(now_seconds=1234567890)
        self.assertEqual(timestamp, "7890")
        self.assertEqual(build.build_timestamp(now_seconds=1203), "1203")
        self.assertEqual(build.build_timestamp(now_seconds=7), "0007")
        self.assertEqual(
            build.build_output_name(config, "0.0.0", timestamp=timestamp),
            "小洛探探_SpriteLens_0.0.0_7890",
        )

    def test_existing_release_name_gets_sequence_suffix(self):
        config = build.load_config(build.DEFAULT_CONFIG)
        with TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "小洛探探_SpriteLens_0.0.0_7890.exe").touch()
            self.assertEqual(
                build.available_output_name(
                    config,
                    "0.0.0",
                    timestamp="7890",
                    output_dir=output_dir,
                    suffix=".exe",
                ),
                "小洛探探_SpriteLens_0.0.0_7890-2",
            )


if __name__ == "__main__":
    unittest.main()
