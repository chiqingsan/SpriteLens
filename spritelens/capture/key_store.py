"""会话密钥持久化：latest.key 供工具重启后从流中段续解。

密钥文件格式（文本）：
    key_hex=<32位hex>
    key_ascii=<可打印时>
    flow=<会话标识>
    captured_at=<本地时间>
"""

from __future__ import annotations

from pathlib import Path

from spritelens.logs import get_logger

logger = get_logger("key_store")

KEY_LEN = 16
_HEX_CHARS = set("0123456789abcdefABCDEF")


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
    """按文件持久化最近一次会话密钥；失败只告警不阻断监听。"""

    def __init__(self, keys_dir: Path) -> None:
        self._dir = keys_dir
        self._latest = keys_dir / "latest.key"

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

    def load_latest(self) -> bytes | None:
        try:
            if not self._latest.is_file():
                return None
            first_line = self._latest.read_text(encoding="utf-8").splitlines()[0]
            if not first_line.startswith("key_hex="):
                return None
            return bytes.fromhex(first_line.split("=", 1)[1].strip())
        except (OSError, ValueError) as exc:
            logger.warning("key 读取失败: %s", exc)
            return None
