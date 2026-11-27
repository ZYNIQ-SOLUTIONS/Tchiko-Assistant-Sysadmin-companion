"""Minimal, dependency-free QR Code encoder (`tchiko/remote/qr.py`).

Encodes short UTF-8 strings (URLs) as ISO/IEC 18004 QR symbols in byte mode, versions 1-10,
error-correction level L/M/Q/H, choosing the mask with the lowest standard penalty score.
Used by the Tchiko RC pairing window to show the web app address as a scannable code.

    matrix = encode("https://192.168.1.20:8765")   # List[List[bool]], True = dark module
    svg = render_svg(matrix, module_px=4)          # crisp SVG with a 4-module quiet zone
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Sequence, Tuple

Matrix = List[List[bool]]

# Error-correction level -> 2-bit format indicator.
_EC_FORMAT_BITS: Dict[str, int] = {"L": 0b01, "M": 0b00, "Q": 0b11, "H": 0b10}

# (ec_codewords_per_block, [(block_count, data_codewords_per_block), ...]) per version and level.
_RS_BLOCKS: Dict[Tuple[int, str], Tuple[int, List[Tuple[int, int]]]] = {
    (1, "L"): (7, [(1, 19)]), (1, "M"): (10, [(1, 16)]), (1, "Q"): (13, [(1, 13)]), (1, "H"): (17, [(1, 9)]),
    (2, "L"): (10, [(1, 34)]), (2, "M"): (16, [(1, 28)]), (2, "Q"): (22, [(1, 22)]), (2, "H"): (28, [(1, 16)]),
    (3, "L"): (15, [(1, 55)]), (3, "M"): (26, [(1, 44)]), (3, "Q"): (18, [(2, 17)]), (3, "H"): (22, [(2, 13)]),
    (4, "L"): (20, [(1, 80)]), (4, "M"): (18, [(2, 32)]), (4, "Q"): (26, [(2, 24)]), (4, "H"): (16, [(4, 9)]),
    (5, "L"): (26, [(1, 108)]), (5, "M"): (24, [(2, 43)]),
    (5, "Q"): (18, [(2, 15), (2, 16)]), (5, "H"): (22, [(2, 11), (2, 12)]),
    (6, "L"): (18, [(2, 68)]), (6, "M"): (16, [(4, 27)]), (6, "Q"): (24, [(4, 19)]), (6, "H"): (28, [(4, 15)]),
    (7, "L"): (20, [(2, 78)]), (7, "M"): (18, [(4, 31)]),
    (7, "Q"): (18, [(2, 14), (4, 15)]), (7, "H"): (26, [(4, 13), (1, 14)]),
    (8, "L"): (24, [(2, 97)]), (8, "M"): (22, [(2, 38), (2, 39)]),
    (8, "Q"): (22, [(4, 18), (2, 19)]), (8, "H"): (26, [(4, 14), (2, 15)]),
    (9, "L"): (30, [(2, 116)]), (9, "M"): (22, [(3, 36), (2, 37)]),
    (9, "Q"): (20, [(4, 16), (4, 17)]), (9, "H"): (24, [(4, 12), (4, 13)]),
    (10, "L"): (18, [(2, 68), (2, 69)]), (10, "M"): (26, [(4, 43), (1, 44)]),
    (10, "Q"): (24, [(6, 19), (2, 20)]), (10, "H"): (28, [(6, 15), (2, 16)]),
}

_ALIGNMENT_CENTERS: Dict[int, List[int]] = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30],
    6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
}

MAX_VERSION = 10

_MASKS: List[Callable[[int, int], bool]] = [
    lambda r, c: (r + c) % 2 == 0,
    lambda r, c: r % 2 == 0,
    lambda r, c: c % 3 == 0,
    lambda r, c: (r + c) % 3 == 0,
    lambda r, c: (r // 2 + c // 3) % 2 == 0,
    lambda r, c: (r * c) % 2 + (r * c) % 3 == 0,
    lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
    lambda r, c: ((r * c) % 3 + (r + c) % 2) % 2 == 0,
]


# ── GF(256) Reed-Solomon (primitive polynomial 0x11D, generator roots α^0..α^(n-1)) ───────────
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


def _rs_generator(degree: int) -> List[int]:
    poly = [1]
    for i in range(degree):
        nxt = [0] * (len(poly) + 1)
        for j, coef in enumerate(poly):
            nxt[j] ^= coef
            nxt[j + 1] ^= _gf_mul(coef, _EXP[i])
        poly = nxt
    return poly


def rs_ecc(data: Sequence[int], ec_len: int) -> List[int]:
    """Reed-Solomon error-correction codewords for `data` (QR convention)."""
    gen = _rs_generator(ec_len)
    rem = list(data) + [0] * ec_len
    for i in range(len(data)):
        coef = rem[i]
        if coef:
            for j in range(1, len(gen)):
                rem[i + j] ^= _gf_mul(gen[j], coef)
    return rem[len(data):]


# ── Data encoding ─────────────────────────────────────────────────────────────────────────────
def _data_capacity(version: int, ec: str) -> int:
    _, groups = _RS_BLOCKS[(version, ec)]
    return sum(count * size for count, size in groups)


def _choose_version(n_bytes: int, ec: str, min_version: int = 1) -> int:
    for version in range(max(1, min_version), MAX_VERSION + 1):
        count_bits = 8 if version < 10 else 16
        if 4 + count_bits + 8 * n_bytes <= 8 * _data_capacity(version, ec):
            return version
    raise ValueError(f"data too long for a version {MAX_VERSION} QR code ({n_bytes} bytes, level {ec})")


def _data_codewords(payload: bytes, version: int, ec: str) -> List[int]:
    capacity = _data_capacity(version, ec)
    bits: List[int] = []

    def put(value: int, length: int) -> None:
        bits.extend((value >> (length - 1 - i)) & 1 for i in range(length))

    put(0b0100, 4)  # byte mode
    put(len(payload), 8 if version < 10 else 16)
    for byte in payload:
        put(byte, 8)
    put(0, min(4, capacity * 8 - len(bits)))  # terminator
    if len(bits) % 8:
        put(0, 8 - len(bits) % 8)
    words = [int("".join(map(str, bits[i : i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = (0xEC, 0x11)
    while len(words) < capacity:
        words.append(pad[(len(words) - len(bits) // 8) % 2])
    return words


def _interleave(data: List[int], version: int, ec: str) -> List[int]:
    ec_len, groups = _RS_BLOCKS[(version, ec)]
    blocks: List[List[int]] = []
    pos = 0
    for count, size in groups:
        for _ in range(count):
            blocks.append(data[pos : pos + size])
            pos += size
    ecc = [rs_ecc(block, ec_len) for block in blocks]
    out: List[int] = []
    for i in range(max(len(b) for b in blocks)):
        out.extend(b[i] for b in blocks if i < len(b))
    for i in range(ec_len):
        out.extend(e[i] for e in ecc)
    return out


# ── Matrix construction ───────────────────────────────────────────────────────────────────────
def _bch(value: int, poly: int, shift: int) -> int:
    rem = value << shift
    top = poly.bit_length()
    while rem.bit_length() >= top:
        rem ^= poly << (rem.bit_length() - top)
    return (value << shift) | rem


def format_bits(ec: str, mask: int) -> int:
    """15-bit format information (BCH(15,5) with the 0x5412 XOR mask)."""
    return _bch((_EC_FORMAT_BITS[ec] << 3) | mask, 0x537, 10) ^ 0x5412


def version_bits(version: int) -> int:
    """18-bit version information (BCH(18,6)), used for versions >= 7."""
    return _bch(version, 0x1F25, 12)


def _function_patterns(version: int) -> List[List[Optional[bool]]]:
    n = version * 4 + 17
    m: List[List[Optional[bool]]] = [[None] * n for _ in range(n)]

    for row0, col0 in ((0, 0), (n - 7, 0), (0, n - 7)):  # finders + separators
        for r in range(-1, 8):
            for c in range(-1, 8):
                rr, cc = row0 + r, col0 + c
                if 0 <= rr < n and 0 <= cc < n:
                    m[rr][cc] = (
                        (0 <= r <= 6 and c in (0, 6))
                        or (0 <= c <= 6 and r in (0, 6))
                        or (2 <= r <= 4 and 2 <= c <= 4)
                    )

    centers = _ALIGNMENT_CENTERS[version]
    for r0 in centers:
        for c0 in centers:
            if m[r0][c0] is not None:  # overlaps a finder pattern
                continue
            for r in range(-2, 3):
                for c in range(-2, 3):
                    m[r0 + r][c0 + c] = max(abs(r), abs(c)) != 1

    for i in range(8, n - 8):  # timing patterns
        if m[i][6] is None:
            m[i][6] = i % 2 == 0
        if m[6][i] is None:
            m[6][i] = i % 2 == 0

    _place_format(m, 0)  # reserve format areas (overwritten after masking)
    if version >= 7:
        _place_version(m, version)
    return m


def _place_format(m: List[List[Optional[bool]]], bits: int) -> None:
    n = len(m)
    for i in range(15):
        bit = (bits >> i) & 1 == 1
        if i < 6:
            m[i][8] = bit
        elif i < 8:
            m[i + 1][8] = bit
        else:
            m[n - 15 + i][8] = bit
        if i < 8:
            m[8][n - i - 1] = bit
        elif i < 9:
            m[8][15 - i] = bit
        else:
            m[8][15 - i - 1] = bit
    m[n - 8][8] = True  # dark module


def _place_version(m: List[List[Optional[bool]]], version: int) -> None:
    n = len(m)
    bits = version_bits(version)
    for i in range(18):
        bit = (bits >> i) & 1 == 1
        m[i // 3][i % 3 + n - 11] = bit
        m[i % 3 + n - 11][i // 3] = bit


def _place_data(base: List[List[Optional[bool]]], codewords: List[int], mask: int) -> Matrix:
    n = len(base)
    m = [row[:] for row in base]
    mask_fn = _MASKS[mask]
    bit_index = 7
    byte_index = 0
    row = n - 1
    step = -1
    col = n - 1
    while col > 0:
        if col == 6:  # skip the vertical timing pattern
            col -= 1
        while True:
            for c in (col, col - 1):
                if m[row][c] is None:
                    dark = False
                    if byte_index < len(codewords):
                        dark = (codewords[byte_index] >> bit_index) & 1 == 1
                    if mask_fn(row, c):
                        dark = not dark
                    m[row][c] = dark
                    bit_index -= 1
                    if bit_index < 0:
                        byte_index += 1
                        bit_index = 7
            row += step
            if row < 0 or row >= n:
                row -= step
                step = -step
                break
        col -= 2
    return [[bool(v) for v in r] for r in m]


def penalty(m: Matrix) -> int:
    """Standard QR mask penalty (rules N1-N4)."""
    n = len(m)
    score = 0
    lines = m + [list(col) for col in zip(*m, strict=True)]
    for line in lines:  # N1: runs of 5+ same-colour modules
        run = 1
        for i in range(1, n):
            if line[i] == line[i - 1]:
                run += 1
            else:
                if run >= 5:
                    score += run - 2
                run = 1
        if run >= 5:
            score += run - 2
    for r in range(n - 1):  # N2: 2x2 blocks
        for c in range(n - 1):
            v = m[r][c]
            if v == m[r][c + 1] == m[r + 1][c] == m[r + 1][c + 1]:
                score += 3
    pat_a = [True, False, True, True, True, False, True, False, False, False, False]
    pat_b = pat_a[::-1]
    for line in lines:  # N3: finder-like 1:1:3:1:1 patterns
        for i in range(n - 10):
            window = line[i : i + 11]
            if window == pat_a or window == pat_b:
                score += 40
    dark = sum(v for row in m for v in row)  # N4: dark/light balance
    score += 10 * (abs(dark * 20 - n * n * 10) // (n * n))
    return score


def encode(text: str, ec: str = "M", mask: Optional[int] = None, min_version: int = 1) -> Matrix:
    """Encode `text` (UTF-8, byte mode) as a QR matrix; True = dark module."""
    ec = ec.upper()
    if ec not in _EC_FORMAT_BITS:
        raise ValueError(f"unknown error-correction level {ec!r}")
    payload = text.encode("utf-8")
    version = _choose_version(len(payload), ec, min_version)
    codewords = _interleave(_data_codewords(payload, version, ec), version, ec)
    base = _function_patterns(version)

    best: Optional[Matrix] = None
    best_score = -1
    for candidate in ([mask] if mask is not None else range(8)):
        matrix = _place_data(base, codewords, candidate)
        fmt: List[List[Optional[bool]]] = [list(row) for row in matrix]
        _place_format(fmt, format_bits(ec, candidate))
        final = [[bool(v) for v in row] for row in fmt]
        score = penalty(final)
        if best is None or score < best_score:
            best, best_score = final, score
    assert best is not None
    return best


def render_svg(matrix: Matrix, module_px: int = 4, quiet: int = 4, dark: str = "#000000",
               light: str = "#ffffff") -> str:
    """Render a QR matrix as a crisp SVG (one path, integer module size, quiet zone)."""
    n = len(matrix)
    size = (n + 2 * quiet) * module_px
    segments: List[str] = []
    for r, row in enumerate(matrix):
        c = 0
        while c < n:
            if row[c]:
                start = c
                while c < n and row[c]:
                    c += 1
                x = (start + quiet) * module_px
                y = (r + quiet) * module_px
                segments.append(f"M{x} {y}h{(c - start) * module_px}v{module_px}h-{(c - start) * module_px}z")
            else:
                c += 1
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 {size} {size}" shape-rendering="crispEdges">'
        f'<rect width="{size}" height="{size}" fill="{light}"/>'
        f'<path d="{"".join(segments)}" fill="{dark}"/></svg>'
    )

