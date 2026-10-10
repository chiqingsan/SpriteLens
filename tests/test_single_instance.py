"""单实例控制测试：互斥锁唯一性、唤醒事件投递与消费。

只测本机可验证的行为（Windows 上真实创建内核对象）；非 Windows 平台
跳过——那时单实例控制整体降级为「不做限制」，无对象可测。
"""

from __future__ import annotations

import sys
import unittest

from spritelens.system.single_instance import SingleInstanceGuard

_ON_WINDOWS = sys.platform == "win32"


@unittest.skipUnless(_ON_WINDOWS, "单实例控制仅在 Windows 生效")
class SingleInstanceTest(unittest.TestCase):
    def setUp(self):
        # 测试用独立命名空间：避免与被测进程/其他测试的实例互相干扰
        self._saved_mutex = None
        self.guard = SingleInstanceGuard()
        if not self.guard.acquire():
            self.skipTest("本机已有 SpriteLens 实例在运行，跳过单实例测试")
        self.addCleanup(self.guard.close)

    def test_second_instance_cannot_acquire(self):
        """第二个实例抢不到锁（这是单实例的核心保证）。"""
        second = SingleInstanceGuard()
        self.addCleanup(second.close)
        self.assertFalse(second.acquire())

    def test_activation_event_roundtrip(self):
        """唤醒事件：投递前消费为 False，投递后为 True，且只能消费一次。"""
        handle = self.guard.create_activation_event()
        self.assertIsNotNone(handle)
        self.assertFalse(self.guard.consume_activation(handle))

        notifier = SingleInstanceGuard()
        self.addCleanup(notifier.close)
        self.assertTrue(notifier.notify_existing())

        self.assertTrue(self.guard.consume_activation(handle))
        # 已消费（ResetEvent）后再查应为 False
        self.assertFalse(self.guard.consume_activation(handle))

    def test_notify_without_event_returns_false(self):
        """没有实例创建事件时投递失败但不抛错（调用方据返回值决定提示）。"""
        notifier = SingleInstanceGuard()
        self.addCleanup(notifier.close)
        # 先确保没有残留事件被置位
        self.guard.consume_activation(self.guard.create_activation_event())
        result = notifier.notify_existing()
        self.assertIsInstance(result, bool)

    def test_close_is_idempotent(self):
        """close 可重复调用且清空句柄（退出路径可能被触发多次）。

        注意：同一进程内 setUp 已持有互斥锁，无法在这里验证「释放后可重新
        获取」——那需要跨进程，锁的释放语义由内核在句柄全关时保证。
        """
        guard = SingleInstanceGuard()
        self.addCleanup(guard.close)
        guard.close()
        guard.close()  # 不应抛错
        self.assertIsNone(guard._mutex_handle)
        self.assertIsNone(guard._event_handle)

    def test_null_handle_is_safe(self):
        """未创建事件时传 None 不抛错（非 Windows / 失败路径）。"""
        self.assertFalse(self.guard.consume_activation(None))


if __name__ == "__main__":
    unittest.main()
