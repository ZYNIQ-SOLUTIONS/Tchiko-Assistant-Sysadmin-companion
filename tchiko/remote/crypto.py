"""Cryptography for Tchiko RC (`tchiko/remote/crypto.py`).

Everything the secure channel needs, matching what browsers expose through WebCrypto:

- ECDH on NIST P-256 (raw 65-byte uncompressed public keys, 32-byte shared X coordinate)
- HKDF-SHA256 (RFC 5869) and HMAC-SHA256
- AES-256-GCM with a 96-bit nonce and 128-bit tag

The `cryptography` package is used when it is installed (it is on stock Ubuntu). Otherwise a
pure-Python implementation takes over so Tchiko keeps its zero-dependency promise. Both paths
are checked against each other in `tests/test_remote_crypto.py`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
from typing import List, Optional, Tuple

try:  # Fast, constant-time native implementation when available.
    from cryptography.hazmat.primitives.asymmetric import ec as _ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM as _AESGCM
    from cryptography.hazmat.primitives.serialization import Encoding as _Enc
    from cryptography.hazmat.primitives.serialization import PublicFormat as _PubFmt

    HAS_NATIVE = True
except Exception:  # pragma: no cover - exercised when `cryptography` is absent
    HAS_NATIVE = False


class CryptoError(Exception):
    """Raised for any authentication, decoding or protocol failure."""


# ── Encoding helpers ─────────────────────────────────────────────────────────
def b64u_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64u_decode(text: str) -> bytes:
    if not isinstance(text, str) or len(text) > 4096:
        raise CryptoError("bad base64 field")
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except Exception as exc:
        raise CryptoError("bad base64 field") from exc


# ── HMAC / HKDF ──────────────────────────────────────────────────────────────
def hmac_sha256(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()


def hkdf_sha256(ikm: bytes, salt: bytes, info: bytes, length: int) -> bytes:
    """RFC 5869 HKDF with SHA-256 (identical to WebCrypto `HKDF` deriveBits)."""
    if length > 255 * 32:
        raise ValueError("HKDF output too long")
    prk = hmac_sha256(salt or b"\x00" * 32, ikm)
    out = b""
    block = b""
    counter = 1
    while len(out) < length:
        block = hmac_sha256(prk, block + info + bytes([counter]))
        out += block
        counter += 1
    return out[:length]


# ── P-256 (pure Python fallback) ─────────────────────────────────────────────
_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
_GX = 0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296
_GY = 0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5

_Jac = Tuple[int, int, int]  # Jacobian (X, Y, Z); Z == 0 is the point at infinity
_INF: _Jac = (1, 1, 0)


def _jac_double(pt: _Jac) -> _Jac:
    x, y, z = pt
    if z == 0 or y == 0:
        return _INF
    delta = z * z % _P
    gamma = y * y % _P
    beta = x * gamma % _P
    alpha = 3 * (x - delta) * (x + delta) % _P
    x3 = (alpha * alpha - 8 * beta) % _P
    z3 = ((y + z) * (y + z) - gamma - delta) % _P
    y3 = (alpha * (4 * beta - x3) - 8 * gamma * gamma) % _P
    return (x3, y3, z3)


def _jac_add(p1: _Jac, p2: _Jac) -> _Jac:
    x1, y1, z1 = p1
    x2, y2, z2 = p2
    if z1 == 0:
        return p2
    if z2 == 0:
        return p1
    z1z1 = z1 * z1 % _P
    z2z2 = z2 * z2 % _P
    u1 = x1 * z2z2 % _P
    u2 = x2 * z1z1 % _P
    s1 = y1 * z2 * z2z2 % _P
    s2 = y2 * z1 * z1z1 % _P
    if u1 == u2:
        return _jac_double(p1) if s1 == s2 else _INF
    h = (u2 - u1) % _P
    r = (s2 - s1) % _P
    hh = h * h % _P
    hhh = h * hh % _P
    v = u1 * hh % _P
    x3 = (r * r - hhh - 2 * v) % _P
    y3 = (r * (v - x3) - s1 * hhh) % _P
    z3 = h * z1 * z2 % _P
    return (x3, y3, z3)


def _scalar_mult(k: int, x: int, y: int) -> Tuple[int, int]:
    """Montgomery ladder: same sequence of group operations for every scalar bit."""
    r0: _Jac = _INF
    r1: _Jac = (x, y, 1)
    for i in reversed(range(256)):
        if (k >> i) & 1:
            r0, r1 = _jac_add(r0, r1), _jac_double(r1)
        else:
            r1, r0 = _jac_add(r0, r1), _jac_double(r0)
    xr, yr, zr = r0
    if zr == 0:
        raise CryptoError("ECDH produced the point at infinity")
    zinv = pow(zr, -1, _P)
    zinv2 = zinv * zinv % _P
    return xr * zinv2 % _P, yr * zinv2 * zinv % _P


def _decode_point(raw: bytes) -> Tuple[int, int]:
    """Parse and fully validate an uncompressed P-256 point (rejects invalid-curve attacks)."""
    if len(raw) != 65 or raw[0] != 4:
        raise CryptoError("public key must be a 65-byte uncompressed P-256 point")
    x = int.from_bytes(raw[1:33], "big")
    y = int.from_bytes(raw[33:], "big")
    if not (0 < x < _P and 0 < y < _P):
        raise CryptoError("public key coordinates out of range")
    if (y * y - (x * x * x - 3 * x + _B)) % _P != 0:
        raise CryptoError("public key is not on the P-256 curve")
    return x, y


class EcdhKeyPair:
    """Ephemeral P-256 key pair; one per handshake, discarded afterwards."""

    def __init__(self, force_pure: bool = False) -> None:
        self._native = None
        self._d = 0
        if HAS_NATIVE and not force_pure:
            self._native = _ec.generate_private_key(_ec.SECP256R1())
            self.public_raw = self._native.public_key().public_bytes(_Enc.X962, _PubFmt.UncompressedPoint)
        else:
            self._d = secrets.randbelow(_N - 1) + 1
            qx, qy = _scalar_mult(self._d, _GX, _GY)
            self.public_raw = b"\x04" + qx.to_bytes(32, "big") + qy.to_bytes(32, "big")

    def shared_secret(self, peer_public_raw: bytes) -> bytes:
        px, py = _decode_point(peer_public_raw)  # validate on both paths
        if self._native is not None:
            peer = _ec.EllipticCurvePublicKey.from_encoded_point(_ec.SECP256R1(), peer_public_raw)
            return self._native.exchange(_ec.ECDH(), peer)
        sx, _ = _scalar_mult(self._d, px, py)
        return sx.to_bytes(32, "big")


# ── AES (pure Python fallback, encryption direction only — all GCM needs) ────
def _build_aes_tables() -> Tuple[List[int], List[List[int]]]:
    sbox = [0] * 256
    p = q = 1
    while True:  # generate the S-box from the multiplicative inverse + affine map
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09
        rot = lambda v, s: ((v << s) | (v >> (8 - s))) & 0xFF  # noqa: E731
        sbox[p] = q ^ rot(q, 1) ^ rot(q, 2) ^ rot(q, 3) ^ rot(q, 4) ^ 0x63
        if p == 1:
            break
    sbox[0] = 0x63
    te0 = []
    for s in sbox:
        s2 = ((s << 1) ^ (0x1B if s & 0x80 else 0)) & 0xFF
        te0.append((s2 << 24) | (s << 16) | (s << 8) | (s2 ^ s))
    ror = lambda w, n: ((w >> n) | (w << (32 - n))) & 0xFFFFFFFF  # noqa: E731
    tables = [te0, [ror(w, 8) for w in te0], [ror(w, 16) for w in te0], [ror(w, 24) for w in te0]]
    return sbox, tables


_SBOX, _TE = _build_aes_tables()


class _PureAES:
    def __init__(self, key: bytes) -> None:
        if len(key) not in (16, 24, 32):
            raise ValueError("AES key must be 128, 192 or 256 bits")
        nk = len(key) // 4
        self.rounds = nk + 6
        w = list(struct.unpack(f">{nk}I", key))
        rcon = 1
        sb = _SBOX
        for i in range(nk, 4 * (self.rounds + 1)):
            t = w[i - 1]
            if i % nk == 0:
                t = ((t << 8) | (t >> 24)) & 0xFFFFFFFF
                t = (sb[t >> 24] << 24) | (sb[(t >> 16) & 255] << 16) | (sb[(t >> 8) & 255] << 8) | sb[t & 255]
                t ^= rcon << 24
                rcon = ((rcon << 1) ^ (0x1B if rcon & 0x80 else 0)) & 0xFF
            elif nk > 6 and i % nk == 4:
                t = (sb[t >> 24] << 24) | (sb[(t >> 16) & 255] << 16) | (sb[(t >> 8) & 255] << 8) | sb[t & 255]
            w.append(w[i - nk] ^ t)
        self.rk = w

    def encrypt_block(self, block: bytes) -> bytes:
        t0, t1, t2, t3 = _TE
        sb = _SBOX
        rk = self.rk
        s0, s1, s2, s3 = struct.unpack(">4I", block)
        s0 ^= rk[0]
        s1 ^= rk[1]
        s2 ^= rk[2]
        s3 ^= rk[3]
        k = 4
        for _ in range(self.rounds - 1):
            n0 = t0[s0 >> 24] ^ t1[(s1 >> 16) & 255] ^ t2[(s2 >> 8) & 255] ^ t3[s3 & 255] ^ rk[k]
            n1 = t0[s1 >> 24] ^ t1[(s2 >> 16) & 255] ^ t2[(s3 >> 8) & 255] ^ t3[s0 & 255] ^ rk[k + 1]
            n2 = t0[s2 >> 24] ^ t1[(s3 >> 16) & 255] ^ t2[(s0 >> 8) & 255] ^ t3[s1 & 255] ^ rk[k + 2]
            n3 = t0[s3 >> 24] ^ t1[(s0 >> 16) & 255] ^ t2[(s1 >> 8) & 255] ^ t3[s2 & 255] ^ rk[k + 3]
            s0, s1, s2, s3 = n0, n1, n2, n3
            k += 4

        def _last(a: int, b: int, c: int, d: int, key: int) -> int:
            return ((sb[a >> 24] << 24) | (sb[(b >> 16) & 255] << 16) | (sb[(c >> 8) & 255] << 8) | sb[d & 255]) ^ key

        return struct.pack(
            ">4I",
            _last(s0, s1, s2, s3, rk[k]),
            _last(s1, s2, s3, s0, rk[k + 1]),
            _last(s2, s3, s0, s1, rk[k + 2]),
            _last(s3, s0, s1, s2, rk[k + 3]),
        )


_GCM_R = 0xE1 << 120


def _gf_mult_slow(x: int, y: int) -> int:
    z = 0
    v = y
    for i in range(127, -1, -1):
        if (x >> i) & 1:
            z ^= v
        v = (v >> 1) ^ _GCM_R if v & 1 else v >> 1
    return z


class _PureAESGCM:
    """AES-GCM (NIST SP 800-38D) with 96-bit IVs and a byte-table GHASH."""

    def __init__(self, key: bytes) -> None:
        self._aes = _PureAES(key)
        h = int.from_bytes(self._aes.encrypt_block(b"\x00" * 16), "big")
        self._tables: List[List[int]] = []
        for pos in range(16):
            shift = 8 * (15 - pos)
            base = [_gf_mult_slow(1 << (bit + shift), h) for bit in range(8)]
            table = [0] * 256
            for b in range(1, 256):
                low = b & -b
                table[b] = table[b ^ low] ^ base[low.bit_length() - 1]
            self._tables.append(table)

    def _ghash(self, aad: bytes, ct: bytes) -> int:
        tables = self._tables
        y = 0

        def _absorb(y_val: int, data: bytes) -> int:
            for off in range(0, len(data), 16):
                chunk = data[off : off + 16]
                if len(chunk) < 16:
                    chunk = chunk + b"\x00" * (16 - len(chunk))
                xb = (y_val ^ int.from_bytes(chunk, "big")).to_bytes(16, "big")
                acc = 0
                for pos in range(16):
                    acc ^= tables[pos][xb[pos]]
                y_val = acc
            return y_val

        y = _absorb(y, aad)
        y = _absorb(y, ct)
        return _absorb(y, struct.pack(">QQ", len(aad) * 8, len(ct) * 8))

    def _ctr(self, nonce: bytes, data: bytes) -> bytes:
        out = bytearray()
        counter = 2
        enc = self._aes.encrypt_block
        for off in range(0, len(data), 16):
            ks = enc(nonce + counter.to_bytes(4, "big"))
            chunk = data[off : off + 16]
            out += bytes(a ^ b for a, b in zip(chunk, ks, strict=False))
            counter = (counter + 1) & 0xFFFFFFFF
        return bytes(out)

    def _tag(self, nonce: bytes, aad: bytes, ct: bytes) -> bytes:
        s = self._ghash(aad, ct)
        ek = int.from_bytes(self._aes.encrypt_block(nonce + b"\x00\x00\x00\x01"), "big")
        return (s ^ ek).to_bytes(16, "big")

    def encrypt(self, nonce: bytes, data: bytes, aad: Optional[bytes]) -> bytes:
        if len(nonce) != 12:
            raise ValueError("nonce must be 96 bits")
        ct = self._ctr(nonce, data)
        return ct + self._tag(nonce, aad or b"", ct)

    def decrypt(self, nonce: bytes, data: bytes, aad: Optional[bytes]) -> bytes:
        if len(nonce) != 12 or len(data) < 16:
            raise CryptoError("ciphertext too short")
        ct, tag = data[:-16], data[-16:]
        if not hmac.compare_digest(tag, self._tag(nonce, aad or b"", ct)):
            raise CryptoError("authentication tag mismatch")
        return self._ctr(nonce, ct)


def make_aead(key: bytes, force_pure: bool = False):
    """AES-256-GCM object with `encrypt(nonce, data, aad)` / `decrypt(nonce, data, aad)`."""
    if HAS_NATIVE and not force_pure:
        native = _AESGCM(key)

        class _Native:
            def encrypt(self, nonce: bytes, data: bytes, aad: Optional[bytes]) -> bytes:
                return native.encrypt(nonce, data, aad)

            def decrypt(self, nonce: bytes, data: bytes, aad: Optional[bytes]) -> bytes:
                try:
                    return native.decrypt(nonce, data, aad)
                except Exception as exc:
                    raise CryptoError("authentication tag mismatch") from exc

        return _Native()
    return _PureAESGCM(key)


# ── Handshake key schedule & secure channel ──────────────────────────────────
DIR_CLIENT_TO_SERVER = 1
DIR_SERVER_TO_CLIENT = 2
MAX_FRAME_PLAINTEXT = 4 * 1024 * 1024


def transcript_hash(context: bytes, client_pub: bytes, server_pub: bytes, client_nonce: bytes, server_nonce: bytes) -> bytes:
    """Binds the handshake: mode + session/device id, both public keys and both nonces."""
    h = hashlib.sha256()
    h.update(b"TCHIKO-RC/1")
    for part in (context, client_pub, server_pub, client_nonce, server_nonce):
        h.update(struct.pack(">H", len(part)))
        h.update(part)
    return h.digest()


def derive_session_keys(shared: bytes, secret: bytes, th: bytes) -> Tuple[bytes, bytes, bytes]:
    """-> (client->server key, server->client key, confirmation key)."""
    okm = hkdf_sha256(shared, secret, b"tchiko-rc v1 keys" + th, 96)
    return okm[:32], okm[32:64], okm[64:]


def proof(confirm_key: bytes, role: bytes, th: bytes) -> bytes:
    return hmac_sha256(confirm_key, role + th)


def safety_code(th: bytes) -> str:
    """Six digits both screens show, so a person can eyeball that the channel is theirs."""
    value = int.from_bytes(hashlib.sha256(b"safety" + th).digest()[:4], "big") % 1_000_000
    digits = f"{value:06d}"
    return f"{digits[:3]} {digits[3:]}"


class SecureChannel:
    """AES-256-GCM framing with strict per-direction counters.

    Frame = 8-byte big-endian counter || ciphertext || 16-byte tag.
    Nonce = 4-byte direction || counter. A frame is accepted only if its counter is exactly the
    next expected one, so replayed, dropped or reordered frames kill the session.
    """

    def __init__(self, send_key: bytes, recv_key: bytes, send_dir: int, recv_dir: int, force_pure: bool = False) -> None:
        self._send = make_aead(send_key, force_pure)
        self._recv = make_aead(recv_key, force_pure)
        self._send_dir = send_dir
        self._recv_dir = recv_dir
        self._send_ctr = 0
        self._recv_ctr = 0

    @staticmethod
    def _aad(direction: int) -> bytes:
        return b"tchiko-rc" + bytes([direction])

    def seal(self, plaintext: bytes) -> bytes:
        if len(plaintext) > MAX_FRAME_PLAINTEXT:
            raise CryptoError("frame too large")
        ctr = self._send_ctr
        self._send_ctr += 1
        nonce = struct.pack(">IQ", self._send_dir, ctr)
        return struct.pack(">Q", ctr) + self._send.encrypt(nonce, plaintext, self._aad(self._send_dir))

    def open(self, frame: bytes) -> bytes:
        if len(frame) < 8 + 16:
            raise CryptoError("frame too short")
        (ctr,) = struct.unpack(">Q", frame[:8])
        if ctr != self._recv_ctr:
            raise CryptoError("unexpected frame counter (replay or reordering)")
        nonce = struct.pack(">IQ", self._recv_dir, ctr)
        plaintext = self._recv.decrypt(nonce, frame[8:], self._aad(self._recv_dir))
        self._recv_ctr += 1
        return plaintext
