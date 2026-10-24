"""伙伴标记资源映射：真实流量确认的标记 ID 都必须有可加载素材。"""
from pathlib import Path
import unittest

from spritelens.web.payloads import _PARTNER_MARK_ASSETS, partner_mark_payload

ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "spritelens" / "web" / "static" / "partner-marks"

# 2026-10-24 真实事件日志（%LOCALAPPDATA%/SpriteLens/eventlog）里出现过的
# PetData.partner_mark 取值；8 在该账号的历史流量里未出现，映射保留。
OBSERVED_MARK_IDS = (1, 3, 4, 5, 6, 7, 14, 15)


class PartnerMarkAssetsTest(unittest.TestCase):
    def test_observed_mark_ids_resolve_to_existing_assets(self):
        for mark_id in OBSERVED_MARK_IDS:
            with self.subTest(mark_id=mark_id):
                payload = partner_mark_payload(mark_id)
                self.assertIsNotNone(payload)
                self.assertEqual(payload["id"], mark_id)
                self.assertEqual(payload["name"], "伙伴标记")
                icon = ASSET_DIR / Path(payload["icon_url"]).name
                self.assertTrue(icon.is_file(), f"缺少素材 {payload['icon_url']}")

    def test_unknown_mark_ids_do_not_fabricate_icons(self):
        for mark_id in (0, -1, 2, 9, 999):
            with self.subTest(mark_id=mark_id):
                self.assertIsNone(partner_mark_payload(mark_id))

    def test_every_mapped_asset_exists_and_frame_loads(self):
        for mark_id, asset in _PARTNER_MARK_ASSETS.items():
            with self.subTest(mark_id=mark_id):
                self.assertTrue((ASSET_DIR / asset).is_file(), asset)
        self.assertTrue((ASSET_DIR / "frame.webp").is_file())


if __name__ == "__main__":
    unittest.main()
