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
        """模拟 worker：手动把队列里的 chunk 投递给回调。"""
        while True:
            try:
                chunk = self.src._queue.get_nowait()
            except queue.Empty:
                return
            if chunk is None:
                return
            self.src._on_chunk(chunk)

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
        self.assertEqual(self.events, [("flow_closed", "10.0.0.9:40002")])

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


if __name__ == "__main__":
    unittest.main()
