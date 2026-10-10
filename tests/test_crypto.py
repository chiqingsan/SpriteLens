"""解密与 key 提取测试。"""

import unittest

from Crypto.Cipher import AES

from spritelens.protocol.crypto import (
    FIXED_IV,
    decrypt_data_body,
    decrypt_data_body_with_embedded_iv,
    encrypt_data_body,
    extract_ack_key,
    iter_decrypt_variants,
)
from tests._synth import SYNTH_KEY


class CryptoTest(unittest.TestCase):
    def test_roundtrip(self):
        plain = bytes(range(16)) * 2
        cipher = encrypt_data_body(SYNTH_KEY, plain)
        self.assertNotEqual(cipher, plain)
        self.assertEqual(decrypt_data_body(SYNTH_KEY, cipher), plain)

    def test_fixed_iv_used(self):
        self.assertEqual(FIXED_IV, bytes(range(16)))

    def test_reject_bad_length_body(self):
        with self.assertRaises(ValueError):
            decrypt_data_body(SYNTH_KEY, b"\x00" * 15)
        with self.assertRaises(ValueError):
            decrypt_data_body(SYNTH_KEY, b"\x00" * 17)

    def test_reject_bad_key_length(self):
        with self.assertRaises(ValueError):
            decrypt_data_body(b"short", b"\x00" * 16)

    def test_extract_ack_key_offset(self):
        key = extract_ack_key(b"\x00\x00" + SYNTH_KEY)
        self.assertEqual(key, SYNTH_KEY)
        self.assertIsNone(extract_ack_key(b"\x00\x00\x00\x00"))
        self.assertIsNone(extract_ack_key(b""))


class EmbeddedIvVariantTest(unittest.TestCase):
    """自带 IV 变体（body = IV(16) + 密文）：实测见于 c2s 短心跳帧。"""

    def test_roundtrip(self):
        iv = bytes(range(16, 32))
        plain = bytes(range(32))
        body = iv + AES.new(SYNTH_KEY, AES.MODE_CBC, iv).encrypt(plain)
        self.assertEqual(decrypt_data_body_with_embedded_iv(SYNTH_KEY, body), plain)

    def test_reject_bad_length_body(self):
        with self.assertRaises(ValueError):
            decrypt_data_body_with_embedded_iv(SYNTH_KEY, b"\x00" * 16)  # 只有 IV 无密文
        with self.assertRaises(ValueError):
            decrypt_data_body_with_embedded_iv(SYNTH_KEY, b"\x00" * 31)

    def test_reject_bad_key_length(self):
        with self.assertRaises(ValueError):
            decrypt_data_body_with_embedded_iv(b"short", b"\x00" * 32)

    def test_iter_variants_covers_fixed_iv_body(self):
        plain = bytes(range(16)) * 2
        body = encrypt_data_body(SYNTH_KEY, plain)  # 32B：两变体长度均合法
        self.assertIn(plain, list(iter_decrypt_variants(SYNTH_KEY, body)))

    def test_iter_variants_skips_invalid_lengths(self):
        plain = bytes(range(16))
        body = encrypt_data_body(SYNTH_KEY, plain)  # 16B：IV+ct 变体长度非法被跳过
        self.assertEqual(list(iter_decrypt_variants(SYNTH_KEY, body)), [plain])

    def test_iter_variants_all_invalid_yields_nothing(self):
        self.assertEqual(list(iter_decrypt_variants(SYNTH_KEY, b"\x00" * 15)), [])


if __name__ == "__main__":
    unittest.main()
