"""Unit tests for Tchiko RC cryptography (`tchiko.remote.crypto`)."""

from __future__ import annotations

import os
import re
import unittest

from tchiko.remote import crypto


class TestRemoteCrypto(unittest.TestCase):
    """Verify ECDH P-256, HKDF-SHA256, AES-256-GCM, and counter-checked SecureChannel."""

    def test_pure_python_and_native_ecdh_match(self) -> None:
        native_a = crypto.EcdhKeyPair(force_pure=False)
        pure_b = crypto.EcdhKeyPair(force_pure=True)
        pure_c = crypto.EcdhKeyPair(force_pure=True)

        self.assertEqual(len(native_a.public_raw), 65)
        self.assertEqual(native_a.public_raw[0], 0x04)
        self.assertEqual(len(pure_b.public_raw), 65)
        self.assertEqual(pure_b.public_raw[0], 0x04)

        # Native peer and pure-Python peer must derive identical 32-byte shared secrets
        shared_ab = native_a.shared_secret(pure_b.public_raw)
        shared_ba = pure_b.shared_secret(native_a.public_raw)
        self.assertEqual(len(shared_ab), 32)
        self.assertEqual(shared_ab, shared_ba)

        # Pure-Python <-> pure-Python symmetry
        self.assertEqual(
            pure_b.shared_secret(pure_c.public_raw),
            pure_c.shared_secret(pure_b.public_raw),
        )

    def test_invalid_curve_points_rejected(self) -> None:
        native_kp = crypto.EcdhKeyPair(force_pure=False)
        pure_kp = crypto.EcdhKeyPair(force_pure=True)
        bad_keys = [
            b"",
            b"\x04" + b"\x00" * 64,  # (0, 0) not on P-256
            b"\x02" + b"\x01" * 64,  # wrong uncompressed prefix
            b"\x04" + b"\xff" * 64,  # coordinates >= p
            b"\x04" + b"\x01" * 63,  # wrong length
        ]
        for bad in bad_keys:
            with self.assertRaises(crypto.CryptoError):
                native_kp.shared_secret(bad)
            with self.assertRaises(crypto.CryptoError):
                pure_kp.shared_secret(bad)

    def test_pure_python_and_native_aes_gcm_parity(self) -> None:
        key = os.urandom(32)
        nonce = os.urandom(12)
        aad = b"tchiko-rc-aad-test"

        native = crypto.make_aead(key, force_pure=False)
        pure = crypto.make_aead(key, force_pure=True)

        for plaintext in (b"", b"hello", os.urandom(16), os.urandom(100), os.urandom(1024)):
            ct_native = native.encrypt(nonce, plaintext, aad)
            ct_pure = pure.encrypt(nonce, plaintext, aad)
            self.assertEqual(ct_native, ct_pure)
            self.assertEqual(native.decrypt(nonce, ct_pure, aad), plaintext)
            self.assertEqual(pure.decrypt(nonce, ct_native, aad), plaintext)

        # Tampering with ciphertext, tag, or AAD must fail on both paths
        ct = native.encrypt(nonce, b"secret payload", aad)
        flipped = bytearray(ct)
        flipped[0] ^= 0x01
        with self.assertRaises(crypto.CryptoError):
            native.decrypt(nonce, bytes(flipped), aad)
        with self.assertRaises(crypto.CryptoError):
            pure.decrypt(nonce, bytes(flipped), aad)
        with self.assertRaises(crypto.CryptoError):
            native.decrypt(nonce, ct, b"wrong-aad")
        with self.assertRaises(crypto.CryptoError):
            pure.decrypt(nonce, ct, b"wrong-aad")

    def test_transcript_hkdf_and_safety_code(self) -> None:
        c = crypto.EcdhKeyPair()
        s = crypto.EcdhKeyPair()
        shared = c.shared_secret(s.public_raw)
        secret = os.urandom(12)
        cn = os.urandom(16)
        sn = os.urandom(16)
        th1 = crypto.transcript_hash(b"pair:abc", c.public_raw, s.public_raw, cn, sn)
        th2 = crypto.transcript_hash(b"pair:abc", c.public_raw, s.public_raw, cn, sn)
        self.assertEqual(th1, th2)
        self.assertEqual(len(th1), 32)

        c2s, s2c, conf = crypto.derive_session_keys(shared, secret, th1)
        self.assertEqual(len(c2s), 32)
        self.assertEqual(len(s2c), 32)
        self.assertEqual(len(conf), 32)
        self.assertEqual(len({c2s, s2c, conf}), 3)

        p_client = crypto.proof(conf, b"client", th1)
        p_server = crypto.proof(conf, b"server", th1)
        self.assertNotEqual(p_client, p_server)
        self.assertEqual(len(p_client), 32)

        code = crypto.safety_code(th1)
        self.assertRegex(code, re.compile(r"^\d{3} \d{3}$"))

    def test_secure_channel_monotonic_counters_and_tamper_rejection(self) -> None:
        c2s = os.urandom(32)
        s2c = os.urandom(32)
        client = crypto.SecureChannel(c2s, s2c, crypto.DIR_CLIENT_TO_SERVER, crypto.DIR_SERVER_TO_CLIENT)
        server = crypto.SecureChannel(s2c, c2s, crypto.DIR_SERVER_TO_CLIENT, crypto.DIR_CLIENT_TO_SERVER, force_pure=True)

        f0 = client.seal(b"msg-0")
        f1 = client.seal(b"msg-1")
        f2 = client.seal(b"msg-2")

        # Out-of-order frame rejected before accepting f0
        with self.assertRaises(crypto.CryptoError):
            server.open(f1)

        # Correct sequence succeeds
        self.assertEqual(server.open(f0), b"msg-0")
        self.assertEqual(server.open(f1), b"msg-1")

        # Replay of f0 rejected
        with self.assertRaises(crypto.CryptoError):
            server.open(f0)

        # Cross-direction reflection rejected
        with self.assertRaises(crypto.CryptoError):
            client.open(f2)

        # Tampered frame rejected without advancing counter
        tampered = bytearray(f2)
        tampered[-1] ^= 0x80
        with self.assertRaises(crypto.CryptoError):
            server.open(bytes(tampered))

        # Valid f2 still opens cleanly after rejected tamper
        self.assertEqual(server.open(f2), b"msg-2")


if __name__ == "__main__":
    unittest.main()
