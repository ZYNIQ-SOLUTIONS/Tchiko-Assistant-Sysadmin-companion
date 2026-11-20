"""Render sigil test images for `tests/rc/sigil_decode.test.mjs`.

Writes PNGs plus a manifest with the expected payloads into the directory given as argv[1].
Run by `tests/test_remote_sigil.py` (needs PyGObject + librsvg, like the desktop app).
"""

from __future__ import annotations

import io
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import cairo  # noqa: E402
import gi  # noqa: E402

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf  # noqa: E402

from tchiko.remote.sigil import SigilPayload, render_svg  # noqa: E402


def svg_pixbuf(svg: str) -> GdkPixbuf.Pixbuf:
    loader = GdkPixbuf.PixbufLoader.new_with_type("svg")
    loader.write(svg.encode("utf-8"))
    loader.close()
    return loader.get_pixbuf()


def pixbuf_to_surface(pix: GdkPixbuf.Pixbuf) -> cairo.ImageSurface:
    ok, buf = pix.save_to_bufferv("png", [], [])
    assert ok
    return cairo.ImageSurface.create_from_png(io.BytesIO(buf))


def main(out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(7)
    cases = []
    for idx in range(14):
        payload = SigilPayload.generate()
        size = rng.choice([260, 340, 420])
        src_surf = pixbuf_to_surface(svg_pixbuf(render_svg(payload.codeword(), size)))
        surf = cairo.ImageSurface(cairo.FORMAT_RGB24, 640, 480)
        cr = cairo.Context(surf)
        grad = cairo.LinearGradient(0, 0, 640, 480)
        grad.add_color_stop_rgb(0, rng.uniform(0.2, 0.9), 0.5, 0.45)
        grad.add_color_stop_rgb(1, 0.15, rng.uniform(0.1, 0.8), 0.3)
        cr.set_source(grad)
        cr.paint()
        cr.translate(320 + rng.uniform(-50, 50), 240 + rng.uniform(-30, 30))
        cr.rotate(rng.uniform(0, 2 * math.pi))
        sx = rng.uniform(0.75, 1.1)
        cr.transform(cairo.Matrix(sx, 0, rng.uniform(-0.15, 0.15), rng.uniform(0.75, 1.1), 0, 0))
        cr.translate(-size / 2, -size / 2)
        cr.set_source_surface(src_surf, 0, 0)
        cr.paint()
        name = f"case{idx:02d}.png"
        surf.write_to_png(str(out / name))
        cases.append({"file": name, "payload": payload.payload_bytes().hex()})
    # One canonical straight-on render used for the perspective-warp tests.
    canon = SigilPayload.generate()
    svg_pixbuf(render_svg(canon.codeword(), 480)).savev(str(out / "canonical.png"), "png", [], [])
    (out / "manifest.json").write_text(
        json.dumps({"cases": cases, "canonical": {"file": "canonical.png", "payload": canon.payload_bytes().hex()}})
    )


if __name__ == "__main__":
    main(sys.argv[1])
