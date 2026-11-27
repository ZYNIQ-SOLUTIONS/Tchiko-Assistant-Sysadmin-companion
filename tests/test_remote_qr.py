"""Tests for the dependency-free QR encoder used by the Tchiko RC pairing window."""

import unittest

from tchiko.remote import qr


def _finder_ok(m, row0, col0):
    for r in range(7):
        for c in range(7):
            ring = r in (0, 6) or c in (0, 6)
            core = 2 <= r <= 4 and 2 <= c <= 4
            if m[row0 + r][col0 + c] != (ring or core):
                return False
    return True


def _read_format(m):
    """Read the 15 format bits from the copy around the top-left finder."""
    bits = 0
    coords = [(8, c) for c in (0, 1, 2, 3, 4, 5, 7, 8)] + [(r, 8) for r in (7, 5, 4, 3, 2, 1, 0)]
    for r, c in coords:
        bits = (bits << 1) | int(m[r][c])
    return bits


class TestQrEncoder(unittest.TestCase):
    def test_reed_solomon_known_vector(self) -> None:
        # ISO/IEC 18004 "HELLO WORLD", version 1-M data codewords and their 10 EC codewords.
        data = [32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17]
        self.assertEqual(qr.rs_ecc(data, 10), [196, 35, 39, 119, 235, 215, 231, 226, 93, 23])

    def test_format_and_version_bits(self) -> None:
        self.assertEqual(qr.format_bits("M", 0), 0b101010000010010)
        self.assertEqual(qr.format_bits("L", 4), 0b110011000101111)
        self.assertEqual(qr.version_bits(7), 0b000111110010010100)

    def test_url_symbol_structure(self) -> None:
        url = "https://192.168.1.20:8765"
        for mask in range(8):
            m = qr.encode(url, ec="M", mask=mask)
            n = len(m)
            self.assertEqual(n, 25)  # 25 bytes at level M -> version 2
            self.assertTrue(all(len(row) == n for row in m))
            self.assertTrue(_finder_ok(m, 0, 0) and _finder_ok(m, 0, n - 7) and _finder_ok(m, n - 7, 0))
            self.assertTrue(m[n - 8][8])  # dark module
            self.assertEqual([m[6][c] for c in range(8, n - 8)], [c % 2 == 0 for c in range(8, n - 8)])
            self.assertEqual(_read_format(m), qr.format_bits("M", mask))

    def test_version_selection_and_limits(self) -> None:
        self.assertEqual(len(qr.encode("a" * 14, ec="M")), 21)  # version 1-M holds 14 bytes
        self.assertEqual(len(qr.encode("a" * 15, ec="M")), 25)
        self.assertEqual(len(qr.encode("x" * 200, ec="L")), 4 * 9 + 17)  # v9-L holds 230 bytes
        self.assertEqual(len(qr.encode("x" * 240, ec="L")), 4 * 10 + 17)
        with self.assertRaises(ValueError):
            qr.encode("x" * 300, ec="M")
        with self.assertRaises(ValueError):
            qr.encode("x", ec="Z")

    def test_auto_mask_is_minimum_penalty(self) -> None:
        url = "https://tchiko.lan:8765"
        chosen = qr.encode(url)
        scores = [qr.penalty(qr.encode(url, mask=k)) for k in range(8)]
        self.assertEqual(qr.penalty(chosen), min(scores))

    def test_render_svg(self) -> None:
        m = qr.encode("https://127.0.0.1:8765")
        svg = qr.render_svg(m, module_px=4)
        side = (len(m) + 8) * 4
        self.assertIn(f'viewBox="0 0 {side} {side}"', svg)
        self.assertIn('shape-rendering="crispEdges"', svg)
        self.assertTrue(svg.startswith("<svg") and svg.endswith("</svg>"))

    def test_matches_reference_library_when_available(self) -> None:
        try:
            import qrcode
            from qrcode.util import MODE_8BIT_BYTE, QRData
        except ImportError:
            self.skipTest("optional cross-check: qrcode is not installed")
        levels = {
            "L": qrcode.constants.ERROR_CORRECT_L,
            "M": qrcode.constants.ERROR_CORRECT_M,
            "Q": qrcode.constants.ERROR_CORRECT_Q,
            "H": qrcode.constants.ERROR_CORRECT_H,
        }
        text = "https://192.168.1.20:8765/#pair=ECXbrdWFMUdIHbIl1MnAIA"
        for ec, level in levels.items():
            for mask in range(8):
                ref = qrcode.QRCode(error_correction=level, mask_pattern=mask, box_size=1, border=0)
                ref.add_data(QRData(text.encode(), mode=MODE_8BIT_BYTE))
                ref.make(fit=True)
                expected = [[bool(v) for v in row] for row in ref.modules]
                self.assertEqual(qr.encode(text, ec=ec, mask=mask), expected, f"ec={ec} mask={mask}")


if __name__ == "__main__":
    unittest.main()
