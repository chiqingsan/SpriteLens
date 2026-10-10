"""0x4013 DATA 帧体的 AES-128-CBC 解密。

关键协议事实：会话密钥由服务器在 0x1002 ACK 的 HEAD.extend[2:18]
明文下发（16 字节 AES-128 key）。0x4013 body 存在两种实测加密变体：

- 固定 IV：整个 body 即密文，CBC 固定 IV 解密（业务帧主流布局）；
- 自带 IV：body 前 16 字节为本次加密的 IV，其余为密文（实测见于
  c2s 短心跳帧，与社区实现 rocom-helper 的解法一致）。

两变体按内容自适应（见 monitor_service 的双尝试），每包独立解密、
无跨包状态——因此工具重启或中途接入都可续解。
"""

from __future__ import annotations

from collections.abc import Iterator

from Crypto.Cipher import AES

FIXED_IV = bytes(range(16))
KEY_LEN = 16


def decrypt_data_body(key: bytes, body: bytes) -> bytes:
    """解密 0x4013 的 body（固定 IV 变体）；长度非法时抛 ValueError。"""
    if len(key) != KEY_LEN:
        raise ValueError(f"AES-128 密钥必须为 {KEY_LEN} 字节，实际 {len(key)}")
    if len(body) < KEY_LEN:
        raise ValueError("body 长度不足 16 字节")
    if len(body) % 16 != 0:
        raise ValueError(f"body 非 16 字节对齐: {len(body)}")
    return AES.new(key, AES.MODE_CBC, FIXED_IV).decrypt(body)


def decrypt_data_body_with_embedded_iv(key: bytes, body: bytes) -> bytes:
    """解密 0x4013 的 body（自带 IV 变体：body = IV(16) + 密文）。"""
    if len(key) != KEY_LEN:
        raise ValueError(f"AES-128 密钥必须为 {KEY_LEN} 字节，实际 {len(key)}")
    if len(body) < 2 * KEY_LEN:
        raise ValueError("自带 IV 变体 body 长度不足 32 字节")
    iv, ct = body[:KEY_LEN], body[KEY_LEN:]
    if len(ct) % 16 != 0:
        raise ValueError(f"密文区非 16 字节对齐: {len(ct)}")
    return AES.new(key, AES.MODE_CBC, iv).decrypt(ct)


def iter_decrypt_variants(key: bytes, body: bytes) -> Iterator[bytes]:
    """依次产出两种加密变体的明文；单变体长度非法时跳过。"""
    for decrypt in (decrypt_data_body, decrypt_data_body_with_embedded_iv):
        try:
            yield decrypt(key, body)
        except ValueError:
            continue


def encrypt_data_body(key: bytes, plaintext: bytes) -> bytes:
    """加密（对称工具：测试合成帧与未来写入型接入层使用）。"""
    if len(key) != KEY_LEN:
        raise ValueError(f"AES-128 密钥必须为 {KEY_LEN} 字节，实际 {len(key)}")
    if len(plaintext) < KEY_LEN or len(plaintext) % 16 != 0:
        raise ValueError("明文须 16 字节对齐且非空")
    return AES.new(key, AES.MODE_CBC, FIXED_IV).encrypt(plaintext)


def extract_ack_key(header_extra: bytes) -> bytes | None:
    """从 0x1002 ACK 的 HEAD.extend 提取会话密钥；格式不符返回 None。"""
    if len(header_extra) < 18:
        return None
    return header_extra[2:18]
