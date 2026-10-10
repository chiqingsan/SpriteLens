"""TCP 流重组：把乱序/重传的段拼回连续字节流（纯逻辑，无 IO）。

自研实现，策略与业界通行做法一致：
- 首个有负载的段定基准 seq；
- 顺序段追加、乱序段进有界 pending 缓存，空洞补齐后按序吐出；
- 全零短段（突发前实测出现的 6 字节探测形态）暂缓下发：若随后同 seq 的
  真实段与之冲突，回滚重收（零丢失）；其余重叠冲突保留既有字节、接纳
  新段尾部（下游按内容自同步）；
- pending 总量超限丢弃最远段，防止内存无限增长。

历史教训：旧版对冲突一律丢弃新段，而服务器在大批下行突发前会插入同 seq
的 6 字节全零段——真实首段被丢弃后空洞永久无法补齐，后续段全部卡在
pending，整批下行静默丢失（登录推送收不到的根因，日志中「重传冲突」即此）。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

MAX_PENDING_BYTES = 8 * 1024 * 1024
# 全零且不超过此长度的段视为可疑探测段，暂缓下发以待可能的回滚
_TENTATIVE_MAX = 16


class TcpStreamReassembler:
    """单方向重组器：feed 返回「新变为连续」的字节（可空）。"""

    def __init__(self, *, name: str = "stream") -> None:
        self.name = name
        self._base_seq: int | None = None
        self._next_seq = 0
        self._buffer = bytearray()
        self._pending: dict[int, bytes] = {}
        self._pending_bytes = 0
        self.conflicts = 0
        self.retractions = 0
        self.dropped_segments = 0
        self._emitted = 0  # _buffer 中已下发的字节数（回滚边界）
        self._tentative_len = 0  # 末尾暂缓下发的可疑字节数（0=无）

    def feed(self, seq: int, payload: bytes) -> bytes:
        if not payload:
            return b""
        if self._base_seq is None:
            self._base_seq = seq
            self._next_seq = seq
        out = bytearray()
        self._ingest(seq, payload, out)
        return bytes(out)

    def _ingest(self, seq: int, payload: bytes, out: bytearray) -> None:
        if seq < self._base_seq:
            # 早于基准的历史段（中段接入的残留重传）丢弃：帧不完整且多为
            # 重复数据，保留反而引入负偏移与错乱拼接的风险
            return
        if seq + len(payload) <= self._next_seq:
            return  # 完全重复的旧段（含已确认区间内的重复）
        if seq < self._next_seq:
            overlap = self._next_seq - seq
            existing = bytes(self._buffer[seq - self._base_seq : seq - self._base_seq + overlap])
            incoming = payload[:overlap]
            if existing != incoming:
                self.conflicts += 1
                idx = seq - self._base_seq
                held_from = len(self._buffer) - self._tentative_len
                if self._tentative_len and idx >= held_from:
                    # 冲突区完全落在「暂缓下发」区：撤销可疑字节，整段按真实数据重收
                    self.retractions += 1
                    logger.debug(
                        "reassembler[%s] 冲突回滚 seq=%d overlap=%d（撤销暂缓的 %d 字节）",
                        self.name, seq, overlap, self._tentative_len,
                    )
                    del self._buffer[idx:]
                    self._next_seq = seq
                    self._tentative_len = 0
                    # 落到按序追加分支，payload 不做裁剪
                else:
                    # 既有字节已下发、无法回退：保留既有前缀，接纳新段尾部。
                    # （旧版此处直接丢弃整段，会造成永久空洞 → 整批下行卡死）
                    logger.debug(
                        "reassembler[%s] 重传冲突 seq=%d overlap=%d existing=%s incoming=%s，接纳新段尾部",
                        self.name, seq, overlap, existing[:16].hex(), incoming[:16].hex(),
                    )
                    payload = payload[overlap:]
                    seq = self._next_seq
            else:
                payload = payload[overlap:]
                seq = self._next_seq
            if not payload:
                return
        if seq == self._next_seq:
            suspicious = len(payload) <= _TENTATIVE_MAX and not any(payload)
            self._buffer.extend(payload)
            self._next_seq += len(payload)
            if suspicious:
                self._tentative_len += len(payload)
            elif self._tentative_len:
                self._tentative_len = 0  # 新内容到达：暂缓的探测段确认有效
            self._emit_ready(out)
            self._drain_pending(out)
            return
        self._store_pending(seq, payload)

    def _emit_ready(self, out: bytearray) -> None:
        """下发 _buffer 中排除暂缓区后的全部新字节。"""
        safe_end = len(self._buffer) - self._tentative_len
        if safe_end > self._emitted:
            out.extend(self._buffer[self._emitted:safe_end])
            self._emitted = safe_end

    def _store_pending(self, seq: int, payload: bytes) -> None:
        # 覆盖/去重：已有段包含新段则跳过，反之替换
        new_end = seq + len(payload)
        for old_seq in list(self._pending):
            old = self._pending[old_seq]
            old_end = old_seq + len(old)
            if old_seq <= seq and old_end >= new_end:
                return
            if seq <= old_seq and new_end >= old_end:
                self._pending_bytes -= len(old)
                del self._pending[old_seq]
        if seq in self._pending:
            return
        self._pending[seq] = payload
        self._pending_bytes += len(payload)
        while self._pending_bytes > MAX_PENDING_BYTES and self._pending:
            farthest = max(self._pending)
            dropped = self._pending.pop(farthest)
            self._pending_bytes -= len(dropped)
            self.dropped_segments += 1
            logger.warning("reassembler[%s] pending 超限，丢弃最远段 seq=%d", self.name, farthest)

    def _drain_pending(self, out: bytearray) -> None:
        while self._pending:
            nxt = min(self._pending)
            if nxt > self._next_seq:
                return
            payload = self._pending.pop(nxt)
            self._pending_bytes -= len(payload)
            overlap = self._next_seq - nxt
            if overlap >= len(payload):
                continue
            tail = payload[overlap:]
            self._buffer.extend(tail)
            self._next_seq += len(tail)
        self._emit_ready(out)
