"""活跃网卡排序：纯函数行为。"""

from __future__ import annotations

import unittest

from spritelens.capture.nic_rank import _name_matches, rank_ifaces


class NicRankTests(unittest.TestCase):
    IFACES = [
        ("\\Device\\NPF_{A1}", "以太网 2"),
        ("\\Device\\NPF_{B2}", "WLAN"),
        ("\\Device\\NPF_{C3}", "Bluetooth Device (个人区域网)"),
        ("\\Device\\NPF_{D4}", "WAN Miniport (IP)"),
    ]

    def test_active_adapters_sorted_first(self) -> None:
        ranked = rank_ifaces(self.IFACES, ["WLAN", "以太网"])
        # 活跃的（WLAN / 以太网）在前，其余保持相对顺序
        self.assertEqual([desc for _, desc in ranked[:2]], ["以太网 2", "WLAN"])
        self.assertEqual([desc for _, desc in ranked[2:]], ["Bluetooth Device (个人区域网)", "WAN Miniport (IP)"])

    def test_no_active_keeps_order(self) -> None:
        self.assertEqual(rank_ifaces(self.IFACES, []), self.IFACES)

    def test_name_matching_is_loose(self) -> None:
        self.assertTrue(_name_matches("以太网 2", ["以太网"]))
        self.assertTrue(_name_matches("WLAN", ["Wlan"]))
        self.assertFalse(_name_matches("WAN Miniport (IP)", ["以太网"]))


if __name__ == "__main__":
    unittest.main()
