"""会话密钥持久化：session.json 按连接恢复密钥、身份和服务端序号。

latest.key 仅保留最近捕获的密钥供手动诊断，不再自动应用到所有连接。
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from spritelens.logs import get_logger

logger = get_logger("key_store")

KEY_LEN = 16
_HEX_CHARS = set("0123456789abcdefABCDEF")


@dataclass(frozen=True)
class SessionCheckpoint:
    flow_id: str
    key: bytes
    identity: tuple[int, str, int] | None = None
    server_sequence: int = 0
    closed: bool = False



def parse_key_text(text: str) -> bytes:
    """16 字节 ASCII 或 32 位 hex；其余格式抛 ValueError。"""
    raw = text.strip()
    if len(raw) == KEY_LEN:
        try:
            return raw.encode("ascii")
        except UnicodeEncodeError as exc:
            raise ValueError("key 必须是 16 字节 ASCII 或 32 位 hex") from exc
    hex_cand = "".join(c for c in raw if c in _HEX_CHARS)
    if len(hex_cand) == 2 * KEY_LEN:
        return bytes.fromhex(hex_cand)
    raise ValueError("key 必须是 16 字节 ASCII 或 32 位 hex")


def _ascii_or_placeholder(key: bytes) -> str:
    if all(32 <= b < 127 for b in key):
        return key.decode("ascii")
    return "<non-ascii>"


class KeyStore:
    """逐连接保存密钥；checkpoint 集合由单写者异步合并并原子替换。"""

    def __init__(self, keys_dir: Path) -> None:
        self._dir = keys_dir
        self._latest = keys_dir / "latest.key"
        self._session = keys_dir / "session.json"
        self._condition = threading.Condition()
        self._checkpoints = {item.flow_id: item for item in self.load_sessions()}
        self._revision = 0
        self._written_revision = 0
        self._pending_session: tuple[int, SessionCheckpoint] | None = None
        self._writer: threading.Thread | None = None
        self._closing = False
        self._closed = False

    def save_session(self, checkpoint: SessionCheckpoint) -> None:
        """原子保存会话关联；密钥仅写本地文件，不进入日志或界面。"""
        with self._condition:
            if self._closing or self._closed:
                raise RuntimeError("KeyStore 已进入关闭状态")
            self._checkpoints[checkpoint.flow_id] = checkpoint
            if len(self._checkpoints) > 256:
                del self._checkpoints[next(iter(self._checkpoints))]
            self._revision += 1
            self._pending_session = (self._revision, checkpoint)
            self._ensure_writer_locked()
            self._condition.notify()

    def _write_session(self, revision: int, checkpoint: SessionCheckpoint) -> None:
        record = {"version": 1, "flow_id": checkpoint.flow_id, "key_hex": checkpoint.key.hex(),
                  "identity": list(checkpoint.identity) if checkpoint.identity else None,
                  "server_sequence": checkpoint.server_sequence, "closed": checkpoint.closed, "updated_at": time.time()}
        # 每次原子替换包含全部连接，异步合并不能让另一条连接的更新丢失。
        with self._condition:
            record["sessions"] = [
                {"flow_id": item.flow_id, "key_hex": item.key.hex(),
                 "identity": list(item.identity) if item.identity else None,
                 "server_sequence": item.server_sequence, "closed": item.closed}
                for item in self._checkpoints.values()
            ]
        self._session.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._session.with_suffix(f".{revision}.json.tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self._session)

    @staticmethod
    def _parse_checkpoint(record: dict) -> SessionCheckpoint:
        key = bytes.fromhex(record["key_hex"])
        flow = record["flow_id"]
        sequence = record["server_sequence"]
        identity = record.get("identity")
        if (len(key) != KEY_LEN or not isinstance(flow, str) or not flow
                or type(sequence) is not int or not 0 <= sequence <= 0xFFFFFFFF):
            raise ValueError("会话记录格式错误")
        if identity is not None:
            if (not isinstance(identity, list) or len(identity) != 3
                    or type(identity[0]) is not int or identity[0] <= 0
                    or not isinstance(identity[1], str)
                    or type(identity[2]) is not int or identity[2] < 0):
                raise ValueError("会话身份格式错误")
            identity = tuple(identity)
        return SessionCheckpoint(flow, key, identity, sequence, record.get("closed") is True)

    def load_session(self) -> SessionCheckpoint | None:
        """读取最近一次记录；保留现有单会话调用入口。"""
        try:
            record = json.loads(self._session.read_text(encoding="utf-8"))
            if not isinstance(record, dict) or record.get("version") != 1:
                return None
            return self._parse_checkpoint(record)
        except (OSError, ValueError, TypeError, KeyError):
            return None

    def load_sessions(self) -> tuple[SessionCheckpoint, ...]:
        """恢复逐连接记录；旧的单连接记录只用于它原本的连接。"""
        try:
            record = json.loads(self._session.read_text(encoding="utf-8"))
            if not isinstance(record, dict) or record.get("version") != 1:
                return ()
            records = record.get("sessions", [record])
            if not isinstance(records, list):
                return ()
            return tuple(self._parse_checkpoint(item) for item in records[-256:])
        except (OSError, ValueError, TypeError, KeyError):
            return ()

    def save_latest(self, key: bytes, flow_id: str) -> None:
        text = (
            f"key_hex={key.hex()}\nkey_ascii={_ascii_or_placeholder(key)}\n"
            f"flow={flow_id}\n"
        )
        try:
            self._latest.parent.mkdir(parents=True, exist_ok=True)
            self._latest.write_text(text, encoding="utf-8")
        except OSError as exc:
            logger.warning("key 持久化失败: %s", exc)

    def _ensure_writer_locked(self) -> None:
        if self._writer is None:
            self._writer = threading.Thread(target=self._run_writer, name="spritelens-key-store", daemon=True)
            self._writer.start()

    def _run_writer(self) -> None:
        while True:
            with self._condition:
                while self._pending_session is None and not self._closing:
                    self._condition.wait()
                if self._pending_session is None and self._closing:
                    return
                revision, checkpoint = self._pending_session
                self._pending_session = None
            try:
                self._write_session(revision, checkpoint)
                with self._condition:
                    self._written_revision = max(self._written_revision, revision)
                    self._condition.notify_all()
            except OSError as exc:
                logger.warning("会话密钥信息保存失败，稍后重试: %s", exc)
                with self._condition:
                    if self._pending_session is None or self._pending_session[0] < revision:
                        self._pending_session = (revision, checkpoint)
                    self._condition.wait(timeout=0.5)

    def flush(self, *, timeout: float = 5) -> None:
        """等待调用前已受理的 checkpoint 原子写入完成。"""
        deadline = time.monotonic() + timeout
        with self._condition:
            revision = self._revision
            while self._written_revision < revision:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("KeyStore checkpoint 未在等待期限内写入")
                self._condition.wait(timeout=remaining)

    def close(self, *, timeout: float = 5) -> None:
        """排空最后的 checkpoint；超时保留唯一 writer，允许稍后重试。"""
        with self._condition:
            if self._closed:
                return
            self._closing = True
            writer = self._writer
            self._condition.notify_all()
        if writer is not None:
            writer.join(timeout=timeout)
            if writer.is_alive():
                raise TimeoutError("KeyStore writer 未在关闭预算内完成")
        with self._condition:
            if self._written_revision < self._revision:
                raise OSError("KeyStore 仍有未写入的 checkpoint")
            self._closed = True

    def load_latest(self) -> bytes | None:
        try:
            if not self._latest.is_file():
                return None
            first_line = self._latest.read_text(encoding="utf-8").splitlines()[0]
            if not first_line.startswith("key_hex="):
                return None
            key = bytes.fromhex(first_line.split("=", 1)[1].strip())
            return key if len(key) == KEY_LEN else None
        except (OSError, ValueError, IndexError) as exc:
            logger.warning("key 读取失败: %s", exc)
            return None
