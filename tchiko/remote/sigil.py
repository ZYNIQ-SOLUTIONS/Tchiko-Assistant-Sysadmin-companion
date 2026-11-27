"""The Tchiko Sigil (`tchiko/remote/sigil.py`) — the circular pairing pattern.

A sigil is a 192-bit code drawn as arcs around the Tchiko face:

    payload (16 B) = version/flags (1) | session id (3) | pairing secret (12)
    message (18 B) = payload | CRC-16/CCITT (2)
    codeword (24 B) = message | Reed-Solomon parity over GF(256) (6)  -> fixes 3 bad bytes

Bits are laid MSB-first, byte after byte, around three data rings (72 / 64 / 56 cells, outer to
inner), clockwise from 12 o'clock. A solid locator ring surrounds the data so a camera can find
the sigil, measure its tilt and read it at any rotation. `rc/js/sigil.js` holds the decoder and
mirrors every constant here.
"""

from __future__ import annotations

import math
import secrets
from dataclasses import dataclass
from typing import List, Tuple

SIGIL_VERSION = 1
SECRET_BYTES = 12
PAYLOAD_BYTES = 16
RS_PARITY = 6
CODEWORD_BYTES = PAYLOAD_BYTES + 2 + RS_PARITY  # 24 bytes = 192 bits

# Geometry in units of the locator ring's outer radius.
RING_CELLS: Tuple[int, ...] = (72, 64, 56)
RING_RADII: Tuple[float, ...] = (0.765, 0.645, 0.525)
RING_WIDTH = 0.07
LOCATOR_OUTER = 1.0
LOCATOR_INNER = 0.88
FACE_RADIUS = 0.40
CARD_HALF = 1.22  # quiet zone around the locator

# Palette (Tchiko design tokens, see tchiko/ui_theme.py).
INK = "#eceef2"
CARD = "#0d0e11"
CARD_EDGE = "#262a32"
ACCENT = "#e5484d"
ACCENT_DEEP = "#b4343a"


# ── GF(256) & Reed-Solomon (primitive polynomial 0x11D, generator 2, fcr = 0) ─
_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _rs_generator(nsym: int) -> List[int]:
    g = [1]
    for i in range(nsym):
        nxt = [0] * (len(g) + 1)
        for j, coef in enumerate(g):
            nxt[j] ^= coef
            nxt[j + 1] ^= _gf_mul(coef, _EXP[i])
        g = nxt
    return g


def rs_encode(msg: bytes, nsym: int = RS_PARITY) -> bytes:
    """Systematic Reed-Solomon: returns `msg` followed by `nsym` parity bytes."""
    gen = _rs_generator(nsym)
    buf = list(msg) + [0] * nsym
    for i in range(len(msg)):
        coef = buf[i]
        if coef:
            for j in range(1, len(gen)):
                buf[i + j] ^= _gf_mul(gen[j], coef)
    return bytes(msg) + bytes(buf[len(msg):])


def crc16_ccitt(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


# ── Payload ──────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class SigilPayload:
    session_id: int  # 24 bits
    secret: bytes  # 12 bytes, one-time pairing secret

    @staticmethod
    def generate() -> "SigilPayload":
        return SigilPayload(secrets.randbits(24), secrets.token_bytes(SECRET_BYTES))

    @property
    def session_bytes(self) -> bytes:
        return self.session_id.to_bytes(3, "big")

    def payload_bytes(self) -> bytes:
        return bytes([(SIGIL_VERSION << 4) | 0x0]) + self.session_bytes + self.secret

    def codeword(self) -> bytes:
        msg = self.payload_bytes()
        msg += crc16_ccitt(msg).to_bytes(2, "big")
        return rs_encode(msg)


def codeword_bits(codeword: bytes) -> List[List[int]]:
    """Split the codeword into per-ring bit lists (outer ring first)."""
    bits = [(byte >> (7 - j)) & 1 for byte in codeword for j in range(8)]
    rings: List[List[int]] = []
    pos = 0
    for cells in RING_CELLS:
        rings.append(bits[pos : pos + cells])
        pos += cells
    return rings


# ── Drawing ──────────────────────────────────────────────────────────────────
def _polar(cx: float, cy: float, r: float, angle: float) -> Tuple[float, float]:
    """Angle in radians, clockwise from 12 o'clock (screen coordinates)."""
    return cx + r * math.sin(angle), cy - r * math.cos(angle)


def _runs(bits: List[int]) -> List[Tuple[int, int]]:
    """Runs of consecutive 1-cells as (start, length), merging across the 12 o'clock seam."""
    n = len(bits)
    if all(bits):
        return [(0, n)]
    start = next(i for i in range(n) if not bits[i])  # begin scanning just after a gap
    runs: List[Tuple[int, int]] = []
    i = 0
    while i < n:
        idx = (start + i) % n
        if bits[idx]:
            length = 0
            while length < n and bits[(idx + length) % n]:
                length += 1
            runs.append((idx, length))
            i += length
        else:
            i += 1
    return runs


def _f(v: float) -> str:
    return f"{v:.3f}".rstrip("0").rstrip(".")


def render_svg(codeword: bytes, size: int = 360, with_card: bool = True) -> str:
    """Render the sigil as a standalone SVG document."""
    scale = size / (2 * CARD_HALF)
    c = size / 2.0
    parts: List[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">',
        "<defs>"
        f'<linearGradient id="tchikoHead" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{ACCENT}"/><stop offset="1" stop-color="{ACCENT_DEEP}"/></linearGradient>'
        "</defs>",
    ]
    if with_card:
        parts.append(
            f'<rect x="0.5" y="0.5" width="{size - 1}" height="{size - 1}" rx="{_f(size * 0.12)}" '
            f'fill="{CARD}" stroke="{CARD_EDGE}" stroke-width="1"/>'
        )

    # Locator ring.
    r_mid = (LOCATOR_OUTER + LOCATOR_INNER) / 2 * scale
    parts.append(
        f'<circle cx="{_f(c)}" cy="{_f(c)}" r="{_f(r_mid)}" fill="none" stroke="{INK}" '
        f'stroke-width="{_f((LOCATOR_OUTER - LOCATOR_INNER) * scale)}"/>'
    )

    # Data rings.
    width = RING_WIDTH * scale
    for bits, radius, cells in zip(codeword_bits(codeword), RING_RADII, RING_CELLS, strict=False):
        r = radius * scale
        cell = 2 * math.pi / cells
        cell_len = cell * r
        gap = 0.10 * cell
        for start, length in _runs(bits):
            if length == cells:
                parts.append(
                    f'<circle cx="{_f(c)}" cy="{_f(c)}" r="{_f(r)}" fill="none" stroke="{INK}" stroke-width="{_f(width)}"/>'
                )
                continue
            visual = length * cell_len - 2 * gap * r
            if visual <= width:
                # Short run: a round dot centred on the run.
                mid = (start + length / 2) * cell
                x, y = _polar(c, c, r, mid)
                parts.append(f'<circle cx="{_f(x)}" cy="{_f(y)}" r="{_f(min(width, visual) / 2)}" fill="{INK}"/>')
                continue
            cap = (width / 2) / r  # round caps add half the stroke width at both ends
            a0 = start * cell + gap + cap
            a1 = (start + length) * cell - gap - cap
            x0, y0 = _polar(c, c, r, a0)
            x1, y1 = _polar(c, c, r, a1)
            large = 1 if (a1 - a0) > math.pi else 0
            parts.append(
                f'<path d="M{_f(x0)} {_f(y0)} A{_f(r)} {_f(r)} 0 {large} 1 {_f(x1)} {_f(y1)}" fill="none" '
                f'stroke="{INK}" stroke-width="{_f(width)}" stroke-linecap="round"/>'
            )

    # Tchiko face (decorative; the decoder never samples inside FACE_RADIUS).
    hw = 0.29 * scale
    hh = 0.24 * scale
    hy = c + 0.05 * scale
    parts.append(
        f'<line x1="{_f(c)}" y1="{_f(hy - hh)}" x2="{_f(c)}" y2="{_f(c - 0.34 * scale)}" '
        f'stroke="{INK}" stroke-width="{_f(0.025 * scale)}" stroke-linecap="round"/>'
    )
    parts.append(f'<circle cx="{_f(c)}" cy="{_f(c - 0.355 * scale)}" r="{_f(0.04 * scale)}" fill="{ACCENT}"/>')
    parts.append(
        f'<rect x="{_f(c - hw)}" y="{_f(hy - hh)}" width="{_f(2 * hw)}" height="{_f(2 * hh)}" '
        f'rx="{_f(hh * 0.62)}" fill="url(#tchikoHead)"/>'
    )
    for dx in (-0.115, 0.115):
        parts.append(
            f'<rect x="{_f(c + dx * scale - 0.04 * scale)}" y="{_f(hy - 0.085 * scale)}" '
            f'width="{_f(0.08 * scale)}" height="{_f(0.15 * scale)}" rx="{_f(0.04 * scale)}" fill="{INK}"/>'
        )
    parts.append("</svg>")
    return "".join(parts)
