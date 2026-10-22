"""打包态资源定位测试：frozen / _MEIPASS 分支必须指向资源根。"""

import importlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import spritelens.paths as paths


class BundleRootTest(unittest.TestCase):
    """模拟打包环境验证 project_root() 的三条分支。

    直接操作 sys 属性后 reload 模块，用 addCleanup 保证还原，
    不影响同进程内其他测试使用 paths 模块。
    """

    def setUp(self):
        self._saved = {
            "frozen": getattr(sys, "frozen", None),
            "MEIPASS": getattr(sys, "_MEIPASS", None),
            "executable": sys.executable,
        }

        def _restore():
            for key, value in self._saved.items():
                attr = "_MEIPASS" if key == "MEIPASS" else key
                if value is None:
                    if hasattr(sys, attr):
                        delattr(sys, attr)
                else:
                    setattr(sys, attr, value)
            importlib.reload(paths)

        self.addCleanup(_restore)

    def _reload_with(self, **attrs) -> Path:
        for key, value in attrs.items():
            setattr(sys, key, value)
        importlib.reload(paths)
        return paths.project_root()

    def test_source_mode_returns_repo_root(self):
        root = paths.project_root()
        self.assertTrue((root / "data" / "static").is_dir(), f"{root} 下应有 data/static")
        self.assertTrue((root / "spritelens").is_dir(), f"{root} 下应有 spritelens/")

    def test_pyinstaller_meipass_wins(self):
        root = self._reload_with(_MEIPASS=r"C:\fake\meipass")
        self.assertEqual(Path(r"C:\fake\meipass"), root)

    def test_nuitka_frozen_uses_executable_dir(self):
        # MEIPASS 不存在时，frozen 走 exe 所在目录
        if hasattr(sys, "_MEIPASS"):
            delattr(sys, "_MEIPASS")
        root = self._reload_with(frozen=True, executable=r"C:\fake\dist\SpriteLens.exe")
        self.assertEqual(Path(r"C:\fake\dist"), root)

    def test_schema_and_static_follow_bundle_root(self):
        self._reload_with(_MEIPASS=r"C:\fake\meipass")
        self.assertEqual(Path(r"C:\fake\meipass\data\schemas"), paths.schema_dir())
        self.assertEqual(Path(r"C:\fake\meipass\data\static"), paths.static_dir())


class IntentionalHomeTest(unittest.TestCase):
    """data_root() 是用户数据目录，不受打包状态影响（必须仍是可写目录）。"""

    def test_data_root_is_not_bundle_root(self):
        self.assertNotEqual(paths.data_root(), paths.project_root())
        self.assertTrue(paths.data_root().is_dir())

    def test_unavailable_directory_never_switches_storage_location(self):
        target = r"C:\unavailable\SpriteLens"
        with patch.dict("os.environ", {"SPRITELENS_DATA_ROOT": target}), \
             patch.object(Path, "mkdir", side_effect=PermissionError("denied")) as mkdir:
            with self.assertRaisesRegex(OSError, "用户数据目录不可用") as caught:
                paths.data_root()
        self.assertIn(target, str(caught.exception))
        mkdir.assert_called_once()


if __name__ == "__main__":
    unittest.main()
