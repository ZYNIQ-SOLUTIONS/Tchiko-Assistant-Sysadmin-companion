"""BoopFace-Powered Procedural Cairo & SVG Renderer for Tchiko Assistant.

Replaces the legacy winged-bird mascot with the **BoopFace** visual design
(inspired by `CX-ArtLab/BoopFace`):
- Smooth superellipse ("squircle") robot head with subtle specular rim & material finish
- Spring-coupled top antenna bobble that sways with movement & bounces on boop
- Expressive dual eyes with independent top/bottom eyelid clipping, natural blinking,
  pointer-following gaze, heart-eyes (`love`), scanning (`thinking`), spinning/wave
  (`executing`), crescent smile (`happy`), slit (`sleepy`), and wide (`roar`/`excited`)
- Real **Spring Jelly Squash-and-Stretch Physics** (`squish_x`, `squish_y`)
- Dual-surface `pycairo` pipeline: identical rendering to `GdkPixbuf` (28 FPS GTK3 overlay)
  and lossless `.svg` files (`assets/tchiko-*.svg`, `landing/assets/tchiko-*.svg`).
"""

from __future__ import annotations

import io
import math
from typing import Any, Dict, List, Tuple

import cairo


THEMES: Dict[str, Dict[str, Tuple[float, float, float]]] = {
    "phantom_cyan": {
        # BoopFace Obsidian Metal (Default: dark obsidian head, pure white eyes, crimson antenna)
        "head_top": (0.11, 0.13, 0.18),
        "head_mid": (0.05, 0.06, 0.08),
        "head_bottom": (0.02, 0.03, 0.04),
        "rim": (0.28, 0.32, 0.42),
        "eye": (1.00, 1.00, 1.00),
        "accent": (0.90, 0.28, 0.30),
        "aura": (0.90, 0.28, 0.30),
    },
    "astral_violet": {
        # BoopFace Velvet Slate (Deep slate-indigo head, ice-white eyes, crimson-violet glow)
        "head_top": (0.15, 0.17, 0.25),
        "head_mid": (0.08, 0.09, 0.14),
        "head_bottom": (0.04, 0.04, 0.08),
        "rim": (0.36, 0.40, 0.56),
        "eye": (0.97, 0.98, 1.00),
        "accent": (0.88, 0.22, 0.36),
        "aura": (0.72, 0.32, 0.92),
    },
    "emerald_matrix": {
        # BoopFace Porcelain Glaze (Crisp white ceramic head, obsidian eyes, scarlet antenna)
        "head_top": (1.00, 1.00, 1.00),
        "head_mid": (0.93, 0.95, 0.98),
        "head_bottom": (0.82, 0.85, 0.90),
        "rim": (0.72, 0.76, 0.84),
        "eye": (0.06, 0.07, 0.10),
        "accent": (0.92, 0.24, 0.26),
        "aura": (0.24, 0.81, 0.56),
    },
    "solar_gold": {
        # BoopFace Crimson Carbon (Deep crimson-charcoal head, warm white eyes, amber-gold antenna)
        "head_top": (0.24, 0.08, 0.10),
        "head_mid": (0.12, 0.04, 0.06),
        "head_bottom": (0.06, 0.02, 0.03),
        "rim": (0.55, 0.20, 0.24),
        "eye": (1.00, 0.98, 0.94),
        "accent": (0.96, 0.65, 0.14),
        "aura": (0.96, 0.65, 0.14),
    },
}

EMOTION_LIST: List[str] = [
    "idle",
    "happy",       # Smiling crescent eyes + bouncy hop
    "roar",        # Wide surprised eyes + shockwave puff
    "wing_slash",  # Playful tumble spin
    "excited",     # Wide bright eyes + energetic bounce
    "thinking",    # Narrowed scanning inspect eyes + head tilt
    "executing",   # Alternating wave eyes + active ring indicator
    "sleepy",      # Thin sleep slits + floating Zs
    "dizzy",       # Wobbly spin eyes
]

EMOTION_COLORS: Dict[str, Tuple[float, float, float]] = {
    "idle": (0.90, 0.28, 0.30),
    "happy": (0.24, 0.81, 0.56),
    "roar": (0.96, 0.65, 0.14),
    "wing_slash": (0.90, 0.28, 0.30),
    "excited": (0.22, 0.74, 0.97),
    "thinking": (0.96, 0.65, 0.14),
    "executing": (0.90, 0.28, 0.30),
    "surprised": (1.00, 1.00, 1.00),
    "dizzy": (0.88, 0.22, 0.34),
    "sleepy": (0.45, 0.50, 0.62),
    "alert": (0.98, 0.20, 0.20),
}


def _squircle_points(cx: float, cy: float, rx: float, ry: float, power: float = 4.0, steps: int = 96) -> List[Tuple[float, float]]:
    """Generate smooth BoopFace superellipse perimeter points."""
    pts: List[Tuple[float, float]] = []
    exp = 2.0 / power
    for i in range(steps):
        theta = (i / steps) * 2.0 * math.pi
        ct = math.cos(theta)
        st = math.sin(theta)
        x = cx + rx * math.copysign(abs(ct) ** exp, ct)
        y = cy + ry * math.copysign(abs(st) ** exp, st)
        pts.append((x, y))
    return pts


class SvgGhostRenderer:
    """Renders Tchiko using the BoopFace squircle robot avatar in pure Cairo + SVG."""

    def __init__(self) -> None:
        self.phase: float = 0.0
        self.look_x: float = 0.0
        self.look_y: float = 0.0
        self.target_look_x: float = 0.0
        self.target_look_y: float = 0.0
        self.vel_x: float = 0.0
        self.vel_y: float = 0.0
        self.spin_angle: float = 0.0
        self.shockwave_prog: float = 0.0
        self.squish_boost: float = 0.0
        self.hovered: bool = False
        self.state: str = "idle"
        self.emotion_ttl: float = 0.0
        self.idle_seconds: float = 0.0
        self.pet_accumulator: float = 0.0
        # BoopFace-specific blink & antenna spring state
        self._blink_timer: float = 2.4
        self._blink_amount: float = 0.0
        self._antenna_x: float = 0.0
        self._antenna_vx: float = 0.0

    def set_emotion(self, emotion: str, duration: float = 4.0) -> None:
        """Trigger an expressive BoopFace mood and spring bounce."""
        self.state = emotion
        self.emotion_ttl = duration
        self.squish_boost = 0.22 if emotion in ("roar", "excited", "happy", "surprised") else 0.12
        if emotion == "roar":
            self.shockwave_prog = 0.01
        elif emotion == "wing_slash":
            self.spin_angle = 0.01
        if emotion != "sleepy":
            self.idle_seconds = 0.0

    def trigger_boop_squish(self) -> None:
        """Apply an instant elastic squeeze impulse when clicked/booped."""
        self.squish_boost = 0.28
        self._antenna_vx += 18.0

    def apply_drag_velocity(self, dx: float, dy: float) -> None:
        """Feed drag velocity so the head tilts and the antenna sways."""
        self.vel_x = max(-30.0, min(30.0, self.vel_x * 0.6 + dx * 0.4))
        self.vel_y = max(-24.0, min(24.0, self.vel_y * 0.6 + dy * 0.4))
        self.idle_seconds = 0.0

    def register_petting(self, motion_delta: float) -> None:
        """Hover-rubbing squishes the BoopFace head & triggers happy/excited expressions."""
        self.idle_seconds = 0.0
        self.squish_boost = min(0.24, self.squish_boost + abs(motion_delta) * 0.004)
        self.pet_accumulator = min(100.0, self.pet_accumulator + abs(motion_delta) * 0.52)
        if self.pet_accumulator > 34.0 and self.state not in ("excited", "roar", "wing_slash", "executing"):
            self.set_emotion("excited", duration=4.0)
            self.pet_accumulator = 0.0
        elif self.pet_accumulator > 15.0 and self.state == "idle":
            self.set_emotion("happy", duration=2.6)

    def step(self, dt: float, speed: float = 1.0) -> None:
        """Advance spring-jelly physics, blinking, antenna sway, and mood timers."""
        speed_mult = (
            0.45
            if self.state == "sleepy"
            else (1.65 if self.state in ("excited", "happy", "executing", "roar", "wing_slash") else 1.0)
        )
        self.phase += dt * 3.8 * speed * speed_mult

        self.look_x += (self.target_look_x - self.look_x) * min(1.0, dt * 10.0)
        self.look_y += (self.target_look_y - self.look_y) * min(1.0, dt * 10.0)

        self.vel_x *= 0.82
        self.vel_y *= 0.82
        self.squish_boost *= 0.86
        self.pet_accumulator = max(0.0, self.pet_accumulator - dt * 8.0)

        # Antenna spring oscillator coupled to horizontal drag velocity
        target_ant = max(-22.0, min(22.0, -self.vel_x * 0.85))
        force_ant = (target_ant - self._antenna_x) * 140.0
        self._antenna_vx = (self._antenna_vx + force_ant * dt) * 0.86
        self._antenna_x += self._antenna_vx * dt

        # Natural periodic blinking when awake
        if self.state in ("idle", "thinking"):
            self._blink_timer -= dt
            if self._blink_timer <= 0.0:
                self._blink_amount = min(1.0, self._blink_amount + dt * 12.0)
                if self._blink_amount >= 1.0:
                    self._blink_timer = 3.1
            elif self._blink_amount > 0.0:
                self._blink_amount = max(0.0, self._blink_amount - dt * 10.0)
        else:
            self._blink_amount = 0.0

        if self.shockwave_prog > 0.0:
            self.shockwave_prog += dt * 1.4
            if self.shockwave_prog >= 1.0:
                self.shockwave_prog = 0.0 if self.state != "roar" else 0.01

        if self.spin_angle > 0.0 or self.state == "wing_slash":
            self.spin_angle += dt * 7.8
            if self.spin_angle >= 2.0 * math.pi:
                self.spin_angle = 0.0
                if self.state == "wing_slash":
                    self.state = "happy"
                    self.emotion_ttl = 2.0

        if self.emotion_ttl > 0:
            self.emotion_ttl = max(0.0, self.emotion_ttl - dt)
            if self.emotion_ttl == 0.0 and self.state not in ("executing", "thinking"):
                self.state = "idle"
                self.shockwave_prog = 0.0
        else:
            if not self.hovered and self.state == "idle":
                self.idle_seconds += dt
                if self.idle_seconds > 38.0:
                    self.state = "sleepy"

    def render_to_pixbuf(
        self,
        width: int,
        height: int,
        theme_name: str = "phantom_cyan",
        opacity: float = 0.98,
        **_kwargs: Any,
    ) -> Any:
        """Render frame in pure Python Cairo and return a transparent GdkPixbuf.Pixbuf."""
        import gi

        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf

        w = max(64, int(width))
        h = max(64, int(height))
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(surface)
        self.draw(cr, width=w, height=h, theme_name=theme_name, opacity=opacity)
        buf = io.BytesIO()
        surface.write_to_png(buf)
        loader = GdkPixbuf.PixbufLoader.new_with_type("png")
        loader.write(buf.getvalue())
        loader.close()
        return loader.get_pixbuf()

    def export_to_svg(
        self,
        svg_path: str,
        width: int = 360,
        height: int = 340,
        theme_name: str = "phantom_cyan",
    ) -> str:
        """Export the exact BoopFace Cairo vector directly into a standalone .svg file."""
        surface = cairo.SVGSurface(svg_path, float(width), float(height))
        cr = cairo.Context(surface)
        self.draw(cr, width=width, height=height, theme_name=theme_name, opacity=1.0)
        surface.finish()
        return svg_path

    def draw(
        self,
        cr: cairo.Context,
        width: int = 220,
        height: int = 220,
        theme_name: str = "phantom_cyan",
        opacity: float = 0.98,
    ) -> None:
        """Draw the complete BoopFace robot avatar centered in (width, height)."""
        theme = THEMES.get(theme_name, THEMES["phantom_cyan"])
        emo_rgb = EMOTION_COLORS.get(self.state, EMOTION_COLORS["idle"])

        cr.save()
        cr.set_operator(cairo.OPERATOR_CLEAR)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)

        scale = min(width / 240.0, height / 240.0)
        jelly_wave = math.sin(self.phase * 2.6) * self.squish_boost

        if self.state in ("happy", "excited"):
            jump_sin = math.sin(self.phase * 1.4)
            bob_y = -abs(jump_sin) * 10.0 + 3.0
            squish_x = 1.03 - abs(jump_sin) * 0.06 + jelly_wave
            squish_y = 0.97 + abs(jump_sin) * 0.06 - jelly_wave * 0.65
        elif self.state == "roar":
            bob_y = -4.0 + math.sin(self.phase * 3.5) * 2.0
            squish_x = 1.10 + math.sin(self.phase * 4.0) * 0.03
            squish_y = 1.08 - math.sin(self.phase * 4.0) * 0.03
        elif self.state == "sleepy":
            bob_y = 6.0 + math.sin(self.phase * 0.7) * 1.5
            squish_x = 1.06 + math.sin(self.phase * 0.7) * 0.02
            squish_y = 0.94 - math.sin(self.phase * 0.7) * 0.02
        else:
            bob_y = math.sin(self.phase) * 4.0
            squish_x = 1.0 + math.sin(self.phase * 1.1) * 0.02 + jelly_wave
            squish_y = 1.0 - math.sin(self.phase * 1.1) * 0.02 - jelly_wave * 0.65

        sway_x = math.cos(self.phase * 0.5) * 1.8
        tilt_rad = (self.look_x * 0.09 if self.hovered else 0.0) + max(-0.18, min(0.18, self.vel_x * 0.005))

        cr.translate(width / 2.0 + sway_x, height / 2.0 + bob_y + 8.0 * scale)
        cr.scale(scale, scale)

        # 1. Soft Ground Shadow
        shadow_scale = max(0.6, 1.0 - (-bob_y / 45.0)) * squish_x
        cr.save()
        cr.translate(0, 98 - bob_y * 0.6)
        cr.scale(62 * shadow_scale, 9.0 * shadow_scale)
        cr.arc(0, 0, 1.0, 0, 2.0 * math.pi)
        cr.set_source_rgba(0.02, 0.03, 0.06, 0.34 * opacity)
        cr.fill()
        cr.restore()

        # 2. Ambient Glow Aura
        aura_r = 104.0 + (6.0 if self.hovered else 0.0) + math.sin(self.phase * 1.4) * 3.5
        aura = cairo.RadialGradient(0, 0, 16, 0, 0, aura_r)
        aura.add_color_stop_rgba(0.0, emo_rgb[0], emo_rgb[1], emo_rgb[2], 0.28 * opacity)
        aura.add_color_stop_rgba(0.65, theme["aura"][0], theme["aura"][1], theme["aura"][2], 0.08 * opacity)
        aura.add_color_stop_rgba(1.0, 0.0, 0.0, 0.0, 0.0)
        cr.arc(0, 0, aura_r, 0, 2.0 * math.pi)
        cr.set_source(aura)
        cr.fill()

        # 3. Apply Spin + Tilt + Jelly Squish
        cr.rotate(tilt_rad + self.spin_angle)
        cr.scale(squish_x, squish_y)

        # 4. Spring Antenna
        self._draw_antenna(cr, theme, emo_rgb, opacity)

        # 5. BoopFace Squircle Head
        self._draw_squircle_head(cr, theme, opacity)

        # 6. Expressive BoopFace Eyes
        self._draw_eyes(cr, theme, emo_rgb, opacity)

        # 7. Emotion FX (executing rings, sleepy Zs, shockwave)
        self._draw_emotion_fx(cr, emo_rgb, opacity)

        cr.restore()

    def _draw_antenna(
        self,
        cr: cairo.Context,
        theme: Dict[str, Tuple[float, float, float]],
        emo_rgb: Tuple[float, float, float],
        opacity: float,
    ) -> None:
        tip_x = self._antenna_x + math.sin(self.phase * 1.3) * 2.2
        tip_y = -98.0

        # Curved spring stem from top of squircle (-78) to bobble (-98)
        cr.move_to(0.0, -76.0)
        cr.curve_to(tip_x * 0.2, -86.0, tip_x * 0.7, -92.0, tip_x, tip_y)
        cr.set_source_rgba(theme["rim"][0], theme["rim"][1], theme["rim"][2], 0.95 * opacity)
        cr.set_line_width(4.5)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.stroke()

        # Glowing antenna bobble
        bob_r = 11.5
        grad = cairo.RadialGradient(tip_x - 3, tip_y - 3, 1.5, tip_x, tip_y, bob_r)
        ac = emo_rgb if self.state in ("executing", "roar", "excited", "happy") else theme["accent"]
        grad.add_color_stop_rgba(0.0, 1.0, 1.0, 1.0, 0.98 * opacity)
        grad.add_color_stop_rgba(0.35, ac[0], ac[1], ac[2], 0.98 * opacity)
        grad.add_color_stop_rgba(1.0, ac[0] * 0.55, ac[1] * 0.55, ac[2] * 0.55, 0.98 * opacity)
        cr.arc(tip_x, tip_y, bob_r, 0, 2.0 * math.pi)
        cr.set_source(grad)
        cr.fill()

        cr.arc(tip_x, tip_y, bob_r, 0, 2.0 * math.pi)
        cr.set_source_rgba(theme["head_bottom"][0], theme["head_bottom"][1], theme["head_bottom"][2], 0.65 * opacity)
        cr.set_line_width(1.6)
        cr.stroke()

    def _draw_squircle_head(
        self,
        cr: cairo.Context,
        theme: Dict[str, Tuple[float, float, float]],
        opacity: float,
    ) -> None:
        pts = _squircle_points(0.0, 4.0, 84.0, 78.0, power=4.0, steps=96)

        def trace_head() -> None:
            cr.move_to(pts[0][0], pts[0][1])
            for px, py in pts[1:]:
                cr.line_to(px, py)
            cr.close_path()

        # Main vertical metallic/ceramic body gradient
        grad = cairo.LinearGradient(0, -78, 0, 86)
        grad.add_color_stop_rgba(0.0, theme["head_top"][0], theme["head_top"][1], theme["head_top"][2], opacity)
        grad.add_color_stop_rgba(0.55, theme["head_mid"][0], theme["head_mid"][1], theme["head_mid"][2], opacity)
        grad.add_color_stop_rgba(1.0, theme["head_bottom"][0], theme["head_bottom"][1], theme["head_bottom"][2], opacity)

        trace_head()
        cr.set_source(grad)
        cr.fill()

        # Subtle pointer-following specular sheen
        sheen_x = -24.0 + self.look_x * 16.0
        sheen_y = -32.0 + self.look_y * 12.0
        sheen = cairo.RadialGradient(sheen_x, sheen_y, 4, sheen_x, sheen_y, 92)
        sheen.add_color_stop_rgba(0.0, 1.0, 1.0, 1.0, 0.12 * opacity)
        sheen.add_color_stop_rgba(1.0, 1.0, 1.0, 1.0, 0.0)
        trace_head()
        cr.set_source(sheen)
        cr.fill()

        # Crisp 1.8px rim border
        trace_head()
        cr.set_source_rgba(theme["rim"][0], theme["rim"][1], theme["rim"][2], 0.85 * opacity)
        cr.set_line_width(2.0)
        cr.stroke()

    def _draw_eyes(
        self,
        cr: cairo.Context,
        theme: Dict[str, Tuple[float, float, float]],
        emo_rgb: Tuple[float, float, float],
        opacity: float,
    ) -> None:
        gx = max(-11.0, min(11.0, self.look_x * 11.0))
        gy = max(-8.0, min(8.0, self.look_y * 8.0))
        eye_rgb = theme["eye"]

        # Standard dual eyes at (-30, 8) and (+30, 8)
        for idx, side in enumerate((-1.0, 1.0)):
            ex = side * 30.0 + gx
            ey = 8.0 + gy
            rx, ry = 21.0, 23.0

            if self.state in ("roar", "excited"):
                rx, ry = 24.5, 25.5
            elif self.state == "executing":
                wave_y = math.sin(self.phase * 2.4 - idx * 1.1) * 6.5
                ey += wave_y
                rx, ry = 20.0, 21.0

            cr.save()
            cr.translate(ex, ey)

            # Dizzy spiral/angled eye offset
            if self.state == "dizzy":
                cr.rotate(self.phase * 2.0 * side)
                rx, ry = 21.0, 14.0

            # Clip to eye ellipse
            cr.save()
            cr.scale(rx, ry)
            cr.arc(0, 0, 1.0, 0, 2.0 * math.pi)
            cr.restore()
            cr.clip()

            # Paint eye base
            cr.set_source_rgba(eye_rgb[0], eye_rgb[1], eye_rgb[2], opacity)
            cr.paint()

            # Eyelid masking (BoopFace style)
            lid_rgb = theme["head_mid"]
            cr.set_source_rgba(lid_rgb[0], lid_rgb[1], lid_rgb[2], opacity)

            if self.state == "sleepy":
                # Thin horizontal slit
                cr.rectangle(-36, -36, 72, 32)
                cr.rectangle(-36, 6, 72, 32)
                cr.fill()
            elif self.state == "happy":
                # Bottom eyelid rises to create happy crescent eyes
                cr.arc(0, 28, 30, 0, 2.0 * math.pi)
                cr.fill()
            elif self.state == "thinking":
                # Narrowed inspect scan
                scan = math.sin(self.phase * 1.8) * 3.0
                cr.rectangle(-36, -36, 72, 26 + scan)
                cr.rectangle(-36, 12 + scan, 72, 28)
                cr.fill()
            elif self._blink_amount > 0.01:
                lid_drop = self._blink_amount * 24.0
                cr.rectangle(-36, -36, 72, 13.0 + lid_drop)
                cr.rectangle(-36, 23.0 - lid_drop, 72, 24.0)
                cr.fill()

            cr.restore()

    def _draw_emotion_fx(
        self,
        cr: cairo.Context,
        emo_rgb: Tuple[float, float, float],
        opacity: float,
    ) -> None:
        p = self.phase
        if self.shockwave_prog > 0.0 or self.state == "roar":
            prog = self.shockwave_prog if self.shockwave_prog > 0.0 else ((p * 0.6) % 1.0)
            rad = 78.0 + prog * 34.0
            cr.arc(0, 4, rad, 0, 2.0 * math.pi)
            cr.set_source_rgba(1.0, 1.0, 1.0, max(0.0, (1.0 - prog) * 0.75 * opacity))
            cr.set_line_width(2.4)
            cr.stroke()

        if self.state == "executing":
            for r in range(4):
                ang = p * 2.2 + r * (math.pi / 2.0)
                ox = math.cos(ang) * 96.0
                oy = math.sin(ang) * 56.0
                cr.arc(ox, oy, 5.5, 0, 2.0 * math.pi)
                cr.set_source_rgba(emo_rgb[0], emo_rgb[1], emo_rgb[2], 0.9 * opacity)
                cr.fill()
        elif self.state == "sleepy":
            cr.select_font_face("Sans", cairo.FONT_SLANT_ITALIC, cairo.FONT_WEIGHT_BOLD)
            cr.set_font_size(14.0)
            for i in range(3):
                prog = (p * 0.4 + i * 0.33) % 1.0
                zx = 54.0 + prog * 24.0
                zy = -48.0 - prog * 32.0
                alpha = math.sin(prog * math.pi) * 0.9 * opacity
                cr.set_source_rgba(0.9, 0.92, 1.0, alpha)
                cr.move_to(zx, zy)
                cr.show_text("Z")
