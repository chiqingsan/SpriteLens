"""目录增量更新扩展点（services/catalog_update.py）的回归测试。

覆盖：版本快照的原子切换与回滚、sha256/结构校验失败时保留旧版本、
更新源不可用时不落半成品，以及「没有配置更新源」时的默认行为。
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from spritelens.domain.eggs import EggCatalog
from spritelens.services.catalog_update import (
    CatalogRelease,
    CatalogRejected,
    CatalogStore,
    CatalogUnavailable,
    CatalogUpdater,
    DisabledCatalogSource,
)


def _eggs_payload(name: str) -> dict:
    return {
        "groups": {},
        "eggs": [
            {
                "egg_key": f"{name}#3001001",
                "egg_conf_id": 3001001,
                "egg_name": f"{name}蛋",
                "name": name,
                "base_id": 3001,
                "egg_item_id": 107001,
                "egg_type_name": "普通",
                "hatch_label": "12小时",
                "egg_group_names": [],
            }
        ],
        "egg_conf_index": {},
    }


def _archive(files: dict[str, dict]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, payload in files.items():
            bundle.writestr(name, json.dumps(payload))
    return buffer.getvalue()


class _FakeSource:
    name = "fake"

    def __init__(self, release: CatalogRelease | None, archive: bytes = b"", error=None) -> None:
        self.release = release
        self.archive = archive
        self.error = error
        self.seen: list[str | None] = []
        self.fetched: list[str] = []

    async def check(self, current_version: str | None) -> CatalogRelease | None:
        self.seen.append(current_version)
        if self.error is not None:
            raise self.error
        return self.release

    async def fetch(self, release: CatalogRelease) -> bytes:
        self.fetched.append(release.version)
        if self.error is not None:
            raise self.error
        return self.archive


def _release(archive: bytes, version: str = "2026.10.28") -> CatalogRelease:
    return CatalogRelease(version=version, sha256=hashlib.sha256(archive).hexdigest(),
                          entries=1, source="test://catalog")


class CatalogStoreTests(unittest.TestCase):
    def test_resolve_falls_back_to_bundled_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundled = Path(tmp) / "static"
            bundled.mkdir()
            (bundled / "eggs.json").write_text("{}", encoding="utf-8")
            store = CatalogStore(Path(tmp) / "egg-catalog")
            self.assertIsNone(store.active_dir())
            self.assertIsNone(store.current_version())
            self.assertEqual(store.resolve(bundled), bundled)

    def test_install_switches_pointer_and_reads_new_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "egg-catalog"
            bundled = Path(tmp) / "static"
            bundled.mkdir()
            (bundled / "eggs.json").write_text("{}", encoding="utf-8")
            store = CatalogStore(root)

            archive = _archive({"eggs.json": _eggs_payload("云梦豚")})
            release = _release(archive)
            installed = store.install(archive, release)

            self.assertTrue((installed / "eggs.json").is_file())
            manifest = json.loads((installed / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["version"], "2026.10.28")
            self.assertEqual(manifest["sha256"], release.sha256)
            self.assertEqual(store.current_version(), "2026.10.28")
            self.assertEqual(EggCatalog(store.resolve(bundled)).egg(3001001).egg_name, "云梦豚蛋")
            pointer = json.loads((root / "active.json").read_text(encoding="utf-8"))
            self.assertEqual(pointer["current"]["version"], "2026.10.28")

    def test_sha_mismatch_keeps_previous_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "egg-catalog"
            store = CatalogStore(root)
            good = _archive({"eggs.json": _eggs_payload("甲")})
            store.install(good, _release(good, "v1"))

            bad = CatalogRelease(version="v2", sha256="0" * 64)
            with self.assertRaises(CatalogRejected):
                store.install(_archive({"eggs.json": _eggs_payload("乙")}), bad)
            self.assertEqual(store.current_version(), "v1")
            self.assertEqual(len(list((root / "versions").glob("v2-*"))), 0)

    def test_rejects_archive_without_eggs_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = CatalogStore(Path(tmp) / "egg-catalog")
            archive = _archive({"egg_inventory.json": {"items": {}}})
            with self.assertRaises(CatalogRejected):
                store.install(archive, _release(archive))
            self.assertIsNone(store.current_version())

    def test_rejects_unknown_or_nested_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = CatalogStore(Path(tmp) / "egg-catalog")
            for name in ("../evil.json", "sub/eggs.json", "note.txt"):
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w") as bundle:
                    bundle.writestr("eggs.json", json.dumps(_eggs_payload("甲")))
                    bundle.writestr(name, "{}")
                with self.assertRaises(CatalogRejected, msg=name):
                    store.install(buffer.getvalue(), _release(buffer.getvalue()))

    def test_rejects_broken_json_and_bad_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = CatalogStore(Path(tmp) / "egg-catalog")
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as bundle:
                bundle.writestr("eggs.json", "{not json")
            with self.assertRaises(CatalogRejected):
                store.install(buffer.getvalue(), _release(buffer.getvalue()))
            with self.assertRaises(CatalogRejected):
                store.install(b"not a zip", CatalogRelease(version="v1", sha256=hashlib.sha256(b"not a zip").hexdigest()))

    def test_rollback_returns_to_previous_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundled = Path(tmp) / "static"
            bundled.mkdir()
            (bundled / "eggs.json").write_text("{}", encoding="utf-8")
            store = CatalogStore(Path(tmp) / "egg-catalog")
            first = _archive({"eggs.json": _eggs_payload("甲")})
            store.install(first, _release(first, "v1"))
            second = _archive({"eggs.json": _eggs_payload("乙")})
            store.install(second, _release(second, "v2"))
            self.assertEqual(store.current_version(), "v2")

            self.assertTrue(store.rollback())
            self.assertEqual(store.current_version(), "v1")
            self.assertEqual(EggCatalog(store.resolve(bundled)).egg(3001001).egg_name, "甲蛋")
            self.assertFalse(store.rollback())  # 已回到最早版本，没有更早的可退

    def test_broken_pointer_falls_back_to_bundled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "egg-catalog"
            root.mkdir()
            (root / "active.json").write_text(json.dumps({"current": {"version": "v1", "dir": "versions/missing"}}), encoding="utf-8")
            store = CatalogStore(root)
            self.assertIsNone(store.active_dir())
            self.assertIsNone(store.current_version())
            bundled = Path(tmp) / "static"
            self.assertEqual(store.resolve(bundled), bundled)


class CatalogUpdaterTests(unittest.TestCase):
    def _updater(self, tmp: str, source) -> tuple[CatalogUpdater, CatalogStore]:
        store = CatalogStore(Path(tmp) / "egg-catalog")
        return CatalogUpdater(store, source), store

    def test_disabled_source_reports_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            updater, store = self._updater(tmp, DisabledCatalogSource())
            result = asyncio.run(updater.update())
            self.assertEqual(result.status, "disabled")
            self.assertEqual(result.version, None)
            self.assertIsNone(store.active_dir())

    def test_installs_then_reports_up_to_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = _archive({"eggs.json": _eggs_payload("云梦豚")})
            source = _FakeSource(_release(archive), archive)
            updater, store = self._updater(tmp, source)

            first = asyncio.run(updater.update())
            self.assertEqual(first.status, "installed")
            self.assertEqual(first.version, "2026.10.28")
            self.assertEqual(store.current_version(), "2026.10.28")
            self.assertEqual(source.seen, [None])

            second = asyncio.run(updater.update())
            self.assertEqual(second.status, "up_to_date")
            self.assertEqual(source.seen, [None, "2026.10.28"])
            self.assertEqual(source.fetched, ["2026.10.28"])

    def test_unavailable_source_keeps_current_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = _FakeSource(None, error=CatalogUnavailable("连接失败"))
            updater, store = self._updater(tmp, source)
            result = asyncio.run(updater.update())
            self.assertEqual(result.status, "unavailable")
            self.assertIn("连接失败", result.message)
            self.assertIsNone(store.active_dir())

    def test_rejected_archive_keeps_current_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = _archive({"eggs.json": _eggs_payload("甲")})
            updater, store = self._updater(tmp, _FakeSource(_release(archive), archive))
            self.assertEqual(asyncio.run(updater.update()).status, "installed")

            tampered = _archive({"eggs.json": _eggs_payload("乙")})
            bad = CatalogRelease(version="v2", sha256="f" * 64)
            updater, _ = self._updater(tmp, _FakeSource(bad, tampered))
            result = asyncio.run(updater.update())
            self.assertEqual(result.status, "rejected")
            self.assertEqual(store.current_version(), "2026.10.28")

    def test_same_version_does_not_download(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = _archive({"eggs.json": _eggs_payload("甲")})
            source = _FakeSource(_release(archive, "v1"), archive)
            updater, store = self._updater(tmp, source)
            store.install(archive, _release(archive, "v1"))
            result = asyncio.run(updater.update())
            self.assertEqual(result.status, "up_to_date")
            self.assertEqual(source.fetched, [])


if __name__ == "__main__":
    unittest.main()
