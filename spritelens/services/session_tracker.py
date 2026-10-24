"""会话与统计跟踪：UI 视图数据从这里取（只读快照）。

有界设计：会话表 LRU 限量，防止长时间挂机内存增长。
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

MAX_SESSIONS = 256


@dataclass(frozen=True)
class SessionStats:
    """单个会话的只读视图数据。"""

    session_id: str
    has_key: bool
    key_captured_at: float | None
    last_activity: float
    data_frames: int
    decrypt_ok: int = 0
    parse_fail: int = 0
    decrypt_fail: int = 0
    key_miss: int = 0
    uid: int = 0
    name: str = ""
    last_result: str = ""


@dataclass(frozen=True)
class Totals:
    """全局计数快照。raw_* 为接入层原始流计数（区分"没抓到包"与"没密钥"）。"""

    decrypt_ok: int
    decrypt_fail: int
    key_miss: int
    parse_fail: int
    sessions: int
    raw_chunks: int = 0
    raw_bytes: int = 0


class SessionTracker:
    """线程安全的会话状态与计数；所有方法可在抓包线程与 UI 线程调用。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: OrderedDict[str, _Session] = OrderedDict()
        self._decrypt_ok = 0
        self._decrypt_fail = 0
        self._key_miss = 0
        self._parse_fail = 0
        self._raw_chunks = 0
        self._raw_bytes = 0

    def count_raw(self, nbytes: int) -> None:
        """接入层每交付一段连续流调用一次（诊断"是否抓到包"的依据）。"""
        with self._lock:
            self._raw_chunks += 1
            self._raw_bytes += nbytes

    def mark_key(self, session_id: str) -> None:
        with self._lock:
            # preset key 路径可能在会话首次 count 之前到来，须确保登记
            session = self._sessions.get(session_id)
            if session is None:
                session = _Session(session_id=session_id)
                self._sessions[session_id] = session
                self._evict_locked()
            session.has_key = True
            session.key_captured_at = time.time()

    def mark_identity(self, session_id: str, identity: tuple[int, str, int] | None) -> None:
        with self._lock:
            session = self._sessions[session_id]
            session.uid = identity[0] if identity else 0
            session.name = identity[1] if identity else ""

    def drop(self, session_id: str) -> None:
        """移除会话行（连接关闭/超时淘汰时与管线会话同步）。"""
        with self._lock:
            self._sessions.pop(session_id, None)

    def count(self, session_id: str, kind: str) -> None:
        """kind ∈ data_frame / decrypt_ok / decrypt_fail / key_miss / parse_fail。"""
        with self._lock:
            if kind == "decrypt_ok":
                self._decrypt_ok += 1
            elif kind == "decrypt_fail":
                self._decrypt_fail += 1
            elif kind == "key_miss":
                self._key_miss += 1
            elif kind == "parse_fail":
                self._parse_fail += 1
            session = self._sessions.get(session_id)
            if session is None:
                session = _Session(session_id=session_id)
                self._sessions[session_id] = session
                self._evict_locked()
            session.last_activity = time.time()
            if kind == "data_frame":
                session.data_frames += 1
            else:
                setattr(session, kind, getattr(session, kind) + 1)
                session.last_result = kind

    def snapshot(self) -> tuple[list[SessionStats], Totals]:
        with self._lock:
            sessions = [
                SessionStats(
                    session_id=s.session_id,
                    has_key=s.has_key,
                    key_captured_at=s.key_captured_at,
                    last_activity=s.last_activity,
                    data_frames=s.data_frames,
                    decrypt_ok=s.decrypt_ok, parse_fail=s.parse_fail, decrypt_fail=s.decrypt_fail,
                    key_miss=s.key_miss, uid=s.uid, name=s.name, last_result=s.last_result,
                )
                for s in self._sessions.values()
            ]
            totals = Totals(
                decrypt_ok=self._decrypt_ok,
                decrypt_fail=self._decrypt_fail,
                key_miss=self._key_miss,
                parse_fail=self._parse_fail,
                sessions=len(self._sessions),
                raw_chunks=self._raw_chunks,
                raw_bytes=self._raw_bytes,
            )
        return sessions, totals

    def _evict_locked(self) -> None:
        while len(self._sessions) > MAX_SESSIONS:
            self._sessions.popitem(last=False)


class _Session:
    """内部可变会话状态（非线程安全，由 Tracker 锁保护）。"""

    __slots__ = ("session_id", "has_key", "key_captured_at", "last_activity", "data_frames",
                 "decrypt_ok", "parse_fail", "decrypt_fail", "key_miss", "uid", "name", "last_result")

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.has_key = False
        self.key_captured_at: float | None = None
        self.last_activity = time.time()
        self.data_frames = 0
        self.decrypt_ok = self.parse_fail = self.decrypt_fail = self.key_miss = self.uid = 0
        self.name = ""
        self.last_result = ""
