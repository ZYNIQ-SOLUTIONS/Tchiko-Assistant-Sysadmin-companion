"""Unit and visual round-trip tests for the Tchiko Sigil pairing code."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tchiko.remote.sigil import (
    CODEWORD_BYTES,
    PAYLOAD_BYTES,
    RING_CELLS,
    SIGIL_VERSION,
    SigilPayload,
    codeword_bits,
    crc16_ccitt,
    render_svg,
    rs_encode,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestRemoteSigil(unittest.TestCase):
    """Verify SigilPayload encoding, GF(256) Reed-Solomon parity, SVG rendering, and JS decoder."""

    def test_payload_codeword_and_ring_layout(self) -> None:
        payload = SigilPayload.generate()
        pb = payload.payload_bytes()
        self.assertEqual(len(pb), PAYLOAD_BYTES)
        self.assertEqual(pb[0] >> 4, SIGIL_VERSION)
        self.assertEqual(pb[1:4], payload.session_bytes)
        self.assertEqual(pb[4:], payload.secret)

        cw = payload.codeword()
        self.assertEqual(len(cw), CODEWORD_BYTES)
        self.assertEqual(cw[:PAYLOAD_BYTES], pb)
        expected_crc = crc16_ccitt(pb).to_bytes(2, "big")
        self.assertEqual(cw[PAYLOAD_BYTES : PAYLOAD_BYTES + 2], expected_crc)
        self.assertEqual(cw, rs_encode(pb + expected_crc))

        rings = codeword_bits(cw)
        self.assertEqual(tuple(len(r) for r in rings), RING_CELLS)
        self.assertEqual(sum(len(r) for r in rings), CODEWORD_BYTES * 8)

    def test_render_svg_structure(self) -> None:
        payload = SigilPayload.generate()
        svg = render_svg(payload.codeword(), size=360, with_card=True)
        self.assertIn("<svg", svg)
        self.assertIn("viewBox=", svg)
        self.assertIn("</svg>", svg)
        self.assertGreater(svg.count("<path"), 20)

    def test_js_visual_decoder_and_reed_solomon_roundtrip(self) -> None:
        """Render warped/rotated/sheared/noisy sigil PNGs and verify rc/js/sigil.js decodes 100%."""
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        try:
            import cairo  # noqa: F401
            import gi

            gi.require_version("GdkPixbuf", "2.0")
            from gi.repository import GdkPixbuf  # noqa: F401
        except Exception:
            self.skipTest("GTK/Cairo/GdkPixbuf not available in this Python interpreter")

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            r1 = subprocess.run(
                ["/usr/bin/python3", str(PROJECT_ROOT / "tests" / "rc" / "render_sigils.py"), str(out_dir)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(r1.returncode, 0, msg=f"render_sigils failed:\n{r1.stdout}\n{r1.stderr}")

            r2 = subprocess.run(
                [node, str(PROJECT_ROOT / "tests" / "rc" / "sigil_decode.test.mjs"), str(out_dir)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(r2.returncode, 0, msg=f"sigil_decode.test.mjs failed:\n{r2.stdout}\n{r2.stderr}")
            self.assertIn("Sigil JS decode test OK", r2.stdout)


if __name__ == "__main__":
    unittest.main()
