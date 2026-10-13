"""F00/V01：JSON→JS ID 精度与构建失败门禁（仅合成数据）。"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from spritelens.domain.home import HomeResident, HomeSnapshot
from spritelens.services.home_repository import HomeRepoSnapshot
from spritelens.web.payloads_catalog import home_payload
from spritelens.web.frontend_assets import check_frontend_assets
from tools import frontend


class IdContractTest(unittest.TestCase):
    def test_adjacent_uint64_survive_json_to_js(self) -> None:
        ids = (9518406239959121930, 9518406239959121931)
        repo = Mock()
        repo.consistent_snapshot.return_value = HomeRepoSnapshot(HomeSnapshot(1, tuple(
            HomeResident(actor_id, "合成居民", 1, 40, (0, 0, 0)) for actor_id in ids), ()), 0, 1, 0)
        payload = home_payload(repo, None)
        self.assertEqual([r["actor_id"] for r in payload["residents"]], list(map(str, ids)))
        node = shutil.which("node")
        self.assertIsNotNone(node, "F00 端到端验证需要 Node")
        result = subprocess.run([node, "-e", "let s='';process.stdin.on('data',c=>s+=c);"
            "process.stdin.on('end',()=>{const r=JSON.parse(s).residents;"
            "if(typeof r[0].actor_id!=='string'||r[0].actor_id===r[1].actor_id||"
            "BigInt(r[1].actor_id)-BigInt(r[0].actor_id)!==1n)process.exit(1)});"],
            input=json.dumps(payload), text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class FrontendBuildTest(unittest.TestCase):
    def test_missing_changed_and_stale_outputs_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            static = Path(tmp)
            directory = static / "vue"
            (directory / ".vite").mkdir(parents=True)
            (directory / "entry.js").write_text("export {};", encoding="utf-8")
            (directory / ".vite/manifest.json").write_text(json.dumps({"src/main.ts":
                {"file": "entry.js", "isEntry": True}}), encoding="utf-8")
            outputs = {p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in directory.rglob("*") if p.is_file()}
            (directory / "build.json").write_text(json.dumps({"outputs": outputs, "source_hash": "old"}), encoding="utf-8")
            self.assertEqual(check_frontend_assets(directory), [])
            with patch.object(frontend, "STATIC", static):
                self.assertIn("过期", frontend.check()[0])
            manifest_path = directory / ".vite/manifest.json"
            manifest_path.write_text(json.dumps({"src/main.ts": {"file": "entry.js", "isEntry": True,
                "css": ["missing.css"], "dynamicImports": ["missing-chunk"]}}), encoding="utf-8")
            failures = check_frontend_assets(directory)
            self.assertTrue(any("引用未登记" in failure for failure in failures))
            self.assertTrue(any("chunk 引用缺失" in failure for failure in failures))
            (directory / "entry.js").write_text("changed", encoding="utf-8")
            self.assertIn("改变", check_frontend_assets(directory)[0])
            (directory / "entry.js").unlink()
            self.assertIn("缺失", check_frontend_assets(directory)[0])

    def test_missing_manifest_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(check_frontend_assets(Path(tmp)))
