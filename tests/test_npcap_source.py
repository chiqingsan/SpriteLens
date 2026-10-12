"""NpcapCaptureSource 的抓包线程逻辑测试（不依赖真实网卡）：

- _handle_packet 的分类/重组/入队；
- 队列满时丢新块并计数（保嗅探不阻塞）；
- 工作线程按序投递 chunk、哨兵退出。
"""

import queue
import threading
import time
import unittest

from spritelens.capture.npcap_source import CHUNK_QUEUE_MAX, NpcapCaptureSource


def make_tcp_packet(sport: int, dport: int, seq: int, payload: bytes):
    """构造 scapy TCP/IP 包（延迟导入 scapy，环境缺失则跳过该测试）。"""
    from scapy.all import IP, TCP

    return IP(src="10.0.0.9", dst="1.2.3.4") / TCP(sport=sport, dport=dport, seq=seq, flags="PA") / payload


def make_login_flow_packets():
    """一段合法 GCP 流（0x1001 SYN + ACK + DATA），拆成 TCP 包。"""
    from spritelens.protocol.crypto import encrypt_data_body
    from spritelens.protocol.frames import CMD_ACK, CMD_DATA, CMD_SYN
    from tests._synth import encode_frame

    key = b"0123456789abcdef"
    syn = encode_frame(CMD_SYN, flag=0, sequence=1, header_extra=b"\x00" * 8, body=b"")
    ack = encode_frame(CMD_ACK, flag=1, sequence=1, header_extra=b"\x00\x00" + key, body=b"")
    body = encrypt_data_body(key, bytes(range(16)))
    data = encode_frame(CMD_DATA, flag=1, sequence=2, header_extra=b"\x00\x00\x00\x00", body=body)
    packets = []
    seq = 1000
    for seg in (syn, ack, data):
        packets.append(make_tcp_packet(40000, 8195, seq, seg))
        seq += len(seg)
    return packets


class _FakeSniffer:
    """替代 AsyncSniffer：手工驱动 _handle_packet。"""

    def __init__(self, source, packets):
        self._source = source
        self._packets = packets
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        for pkt in self._packets:
            self._source._handle_packet(pkt)

    def stop(self):
        if self._thread:
            self._thread.join(timeout=5)

    exception = None


class NpcapSourceLogicTest(unittest.TestCase):
    def setUp(self):
        self.chunks = []
        self.events = []
        self.src = NpcapCaptureSource(
            port=8195,
            on_chunk=self.chunks.append,
            on_event=lambda kind, detail: self.events.append((kind, detail)),
        )

    def _drain(self):
        """模拟 worker：手动把队列里的 chunk/关闭事件投递给回调。"""
        from spritelens.capture.npcap_source import FlowClosed

        while True:
            try:
                item = self.src._queue.get_nowait()
            except queue.Empty:
                return
            if item is None:
                return
            if isinstance(item, FlowClosed):
                self.src._on_event("flow_closed", item.flow_id)
            else:
                self.src._on_chunk(item)

    def test_handle_packet_classifies_and_queues(self):
        for pkt in make_login_flow_packets():
            self.src._handle_packet(pkt)
        self.assertEqual(self.src._queue.qsize(), 3)
        self._drain()
        self.assertEqual(len(self.chunks), 3)
        self.assertEqual(self.chunks[0].session_id, "10.0.0.9:40000")
        self.assertEqual(str(self.chunks[0].direction), "c2s")
        self.assertEqual(self.src._flow_count, 1)
        self.assertEqual(self.events, [])  # 无 FIN/RST

    def test_s2c_direction_by_sport(self):
        self.src._handle_packet(make_tcp_packet(8195, 40001, 5000, b"\x33\x66" + b"\x00" * 30))
        self._drain()
        self.assertEqual(len(self.chunks), 1)
        self.assertEqual(str(self.chunks[0].direction), "s2c")
        self.assertEqual(self.chunks[0].session_id, "1.2.3.4:40001")

    def test_fin_emits_flow_closed(self):
        from scapy.all import IP, TCP

        pkt = IP(src="10.0.0.9", dst="1.2.3.4") / TCP(sport=40002, dport=8195, seq=1, flags="FA") / b"bye"
        self.src._handle_packet(pkt)
        self.assertEqual(self.chunks, [])
        self.assertEqual(self.events, [])  # 关闭事件先入队，不直接回调
        self._drain()
        self.assertEqual(self.events, [("flow_closed", "10.0.0.9:40002")])

    def test_flow_closed_ordered_after_pending_data(self):
        """回归（P1）：FIN 到达时，队列里此前的 DATA 必须先于关闭事件投递。

        旧实现嗅探线程直接回调 close_session，越过排队中的 DATA——协议层
        先清密钥、后处理残余数据（key_miss + 已关闭会话被重新建出）。
        """
        from scapy.all import IP, TCP

        for pkt in make_login_flow_packets():
            self.src._handle_packet(pkt)  # SYN + ACK + DATA 入队
        fin = IP(src="10.0.0.9", dst="1.2.3.4") / TCP(sport=40000, dport=8195, seq=99999, flags="FA") / b""
        self.src._handle_packet(fin)

        # 队列顺序：3 个数据块 + 1 个关闭事件（关闭在最后）
        from spritelens.capture.npcap_source import FlowClosed

        kinds = []
        while not self.src._queue.empty():
            item = self.src._queue.get_nowait()
            kinds.append("closed" if isinstance(item, FlowClosed) else "data")
        self.assertEqual(kinds, ["data", "data", "data", "closed"])
        # 关闭事件到达前，嗅探线程没有回调过任何事件
        self.assertEqual(self.events, [])

    def test_fin_releases_reassembler(self):
        """回归：FIN 后流表与重组器被移除（旧实现只记录事件，长期运行泄漏）。"""
        for pkt in make_login_flow_packets():
            self.src._handle_packet(pkt)
        self.assertEqual(self.src.flow_count, 1)
        self.assertIn("10.0.0.9:40000", self.src._flows)

        from scapy.all import IP, TCP

        fin = IP(src="10.0.0.9", dst="1.2.3.4") / TCP(sport=40000, dport=8195, seq=99999, flags="FA")
        self.src._handle_packet(fin)
        self.assertEqual(self.src.flow_count, 0)
        self.assertNotIn("10.0.0.9:40000", self.src._flows)
        self.assertNotIn("10.0.0.9:40000", self.src._flow_seen)

    def test_idle_sweep_releases_flows(self):
        """异常断连（收不到 FIN）时按空闲时间淘汰流与重组器。"""
        import spritelens.capture.npcap_source as mod

        original_idle = mod.FLOW_IDLE_SECONDS
        mod.FLOW_IDLE_SECONDS = 0.0  # 任何流量都视为已空闲
        try:
            for pkt in make_login_flow_packets():
                self.src._handle_packet(pkt)
            # 下一次带负载的包触发清扫（间隔条件基于单调时钟，直接改 _last_flow_sweep）
            self.src._last_flow_sweep = 0.0
            self.src._flow_seen["10.0.0.9:40000"] = 0.0
            self.src._sweep_flows(10_000.0)
            self.assertEqual(self.src.flow_count, 0)
            self.assertNotIn("10.0.0.9:40000", self.src._flows)
        finally:
            mod.FLOW_IDLE_SECONDS = original_idle

    def test_stop_releases_all_flows(self):
        for pkt in make_login_flow_packets():
            self.src._handle_packet(pkt)
        self.assertEqual(self.src.flow_count, 1)
        self.src._running = True  # 模拟运行中
        self.src.stop()
        self.assertEqual(self.src.flow_count, 0)
        self.assertEqual(self.src._flows, {})

    def test_dropped_segments_exposed(self):
        """重组层丢弃计数可从抓包源读出（含已关闭流的历史累计）。"""
        self.assertEqual(self.src.dropped_segments, 0)
        for pkt in make_login_flow_packets():
            self.src._handle_packet(pkt)
        reassembler = next(iter(self.src._flows["10.0.0.9:40000"].values()))
        reassembler.dropped_segments = 3
        self.assertEqual(self.src.dropped_segments, 3)
        # 关闭该流后计数仍保留（历史累计不因释放而丢失）
        self.src._drop_flow("10.0.0.9:40000")
        self.assertEqual(self.src.dropped_segments, 3)

    def test_worker_dispatches_chunks_in_order(self):
        fake = _FakeSniffer(self.src, make_login_flow_packets())
        self.src._worker = threading.Thread(target=self.src._drain_queue, daemon=True)
        self.src._worker.start()
        fake.start()
        fake.stop()
        deadline = time.time() + 2
        while len(self.chunks) < 3 and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual([str(c.direction) for c in self.chunks], ["c2s", "c2s", "c2s"])
        self.src._queue.put(None)  # 哨兵退出
        self.src._worker.join(timeout=2)
        self.assertFalse(self.src._worker.is_alive())

    def test_queue_full_drops_and_counts(self):
        for _ in range(CHUNK_QUEUE_MAX):
            self.src._queue.put(None)
        self.src._handle_packet(make_tcp_packet(40003, 8195, 7000, b"\x33\x66" + b"\x00" * 24))
        self.assertEqual(self.src.dropped_chunks, 1)
        while not self.src._queue.empty():
            self.src._queue.get()

    def _patch_scapy_sniffer(self, sniffer_cls) -> None:
        """用假 scapy.all 替换 sys.modules 里的条目（AsyncSniffer 在 start() 内延迟导入）。"""
        import sys
        import types

        fake = types.ModuleType("scapy.all")
        fake.AsyncSniffer = sniffer_cls
        self._original_scapy_all = sys.modules.get("scapy.all")
        sys.modules["scapy.all"] = fake
        self.addCleanup(self._restore_scapy_sniffer)

    def _restore_scapy_sniffer(self) -> None:
        import sys

        if getattr(self, "_original_scapy_all", None) is not None:
            sys.modules["scapy.all"] = self._original_scapy_all
        else:
            sys.modules.pop("scapy.all", None)

    def test_start_failure_rolls_back_worker(self):
        """启动失败（sniffer 抛错）必须回收已创建的 worker 线程（R03）。

        旧实现 worker 在嗅探器启动前创建，AsyncSniffer.start 抛 SourceError
        后无回滚；stop 因 _running == False 直接返回，反复点开始会累积
        等待 queue.get 的守护线程。
        """
        from spritelens.capture.base import SourceError

        class _Boom:
            def __init__(self, *args, **kwargs):
                pass

            def start(self):
                raise RuntimeError("缺 Npcap")

            def stop(self):  # pragma: no cover - 失败路径不会走到
                pass

        self._patch_scapy_sniffer(_Boom)
        with self.assertRaises(SourceError):
            self.src.start()

        # worker 已被回滚：无遗留投递线程
        self.assertIsNone(self.src._worker)
        self.assertFalse(self.src.is_running)
        # 失败后 stop 仍可安全调用且能清理资源（重复启停不积累状态）
        self.src.stop()
        self.assertEqual(self.src._flows, {})
        self.assertIsNone(self.src._sniffer)

    def test_repeated_start_stop_no_worker_leak(self):
        """失败启动后再次成功启停：无线程与流表累积。"""

        class _FakeOk:
            exception = None

            def __init__(self, *args, **kwargs):
                pass

            def start(self):
                pass

            def stop(self):
                pass

        class _Boom(_FakeOk):
            def start(self):
                raise RuntimeError("缺 Npcap")

        from spritelens.capture.base import SourceError

        self._patch_scapy_sniffer(_Boom)
        with self.assertRaises(SourceError):
            self.src.start()

        self._restore_scapy_sniffer()
        self._patch_scapy_sniffer(_FakeOk)
        self.src.start()
        self.assertTrue(self.src.is_running)
        self.src.stop()
        self.assertFalse(self.src.is_running)
        self.assertIsNone(self.src._worker)
        self.assertEqual(self.src._flows, {})

    def test_stop_bounded_when_queue_full_and_worker_busy(self):
        """满队列+投递线程忙碌时 stop 仍有界返回（R03 回归）。

        旧实现 stop 的 `queue.put(None)` 在满队列时无限阻塞（已实测挂死）；
        新实现哨兵有界入队（满时丢最旧腾位），join 限时。
        """
        for _ in range(CHUNK_QUEUE_MAX):
            self.src._queue.put(b"stub")
        self.src._running = True
        gate = threading.Event()

        def busy_worker():
            while True:
                item = self.src._queue.get()
                if item is None:
                    return
                gate.wait(timeout=3)  # 模拟下游处理阻塞

        self.src._worker = threading.Thread(target=busy_worker, daemon=True)
        self.src._worker.start()
        # 稍后恢复下游，避免测试吃满 join 上限
        threading.Timer(0.3, gate.set).start()
        started = time.monotonic()
        self.src.stop()
        self.assertLess(time.monotonic() - started, 5, "stop 超出 join 上限")
        self.assertFalse(self.src.is_running)
        self.assertIsNone(self.src._worker)


if __name__ == "__main__":
    unittest.main()
