"""发布配置的关键命令行回归。"""

import unittest

import build


class BuildConfigTest(unittest.TestCase):
    def test_release_command_requests_uac_admin(self):
        config = build.load_config(build.DEFAULT_CONFIG)
        command = build.build_command(config, version="0.0.0")
        self.assertIn("--windows-uac-admin", command)


if __name__ == "__main__":
    unittest.main()
