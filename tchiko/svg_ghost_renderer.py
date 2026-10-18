"""Fluffy, Squishy Tchiko (Dijiang / Hundun) Lovely Pet Renderer — White, Crimson Red & Black.

Combines:
- Ultra-fluffy, chubby, squishy mochi-like pet silhouette of Tchiko (the 6-legged,
  4-winged faceless Dijiang companion from *Shang-Chi*)
- Clean **Snowy White, Velvet Black, and Warm Crimson Red** color palette (zero pink,
  zero hearts!)
- Real **Spring Jelly Squash-and-Stretch Physics** (`squish_x`, `squish_y`):
  - Squishes down into a cozy, wide fluffball when petted or clicked ("booped")
  - Stretches and squishes dynamically when bouncing, hopping, or being dragged
  - 32 cloud-soft rounded fur puffs + double-layered chest fluff + soft feathery wings
  - 6 stubby, chubby little paws with crimson toe-beans that wiggle and tippy-tap!
"""

from __future__ import annotations

import io
import math
from typing import Any, Dict, List, Tuple

import cairo


THEMES: Dict[str, Dict[str, Tuple[float, float, float]]] = {
    "phantom_cyan": {
        # Default: Snowy White, Velvet Black & Warm Crimson Red ("Crimson Cloud Tchiko")
        "fur_light": (1.00, 1.00, 1.00),      # Pure Snowy White fluff highlight
        "fur_mid": (0.93, 0.95, 0.98),        # Soft Cloud White coat
        "fur_dark": (0.28, 0.33, 0.41),       # Plush Slate-Charcoal shading
        "fur_deep": (0.07, 0.09, 0.14),       # Velvet Obsidian Black paws & outline
        "wing_base": (1.00, 1.00, 1.00),      # Snowy White downy wing base
        "wing_mid": (0.14, 0.17, 0.23),       # Velvet Black middle feathers
        "wing_tip": (0.90, 0.14, 0.18),       # Warm Crimson Red rounded feather tips
        "aura": (0.94, 0.18, 0.20),           # Warm Crimson & White glow
    },
    "astral_violet": {
        # "Velvet Panda Hundun" (Dark Velvet Charcoal + Snowy Belly + Crimson Tips)
        "fur_light": (0.98, 0.99, 1.00),
        "fur_mid": (0.78, 0.82, 0.88),
        "fur_dark": (0.16, 0.19, 0.25),
        "fur_deep": (0.04, 0.05, 0.08),
        "wing_base": (0.98, 0.98, 1.00),
        "wing_mid": (0.08, 0.10, 0.14),
        "wing_tip": (0.88, 0.12, 0.16),
        "aura": (0.90, 0.14, 0.18),
    },
    "emerald_matrix": {
        # "Pure Marshmallow Mochi" (Extra Bright White Fluff + Scarlet Tips + Black Paws)
        "fur_light": (1.00, 1.00, 1.00),
        "fur_mid": (0.96, 0.97, 0.99),
        "fur_dark": (0.42, 0.47, 0.55),
        "fur_deep": (0.10, 0.12, 0.18),
        "wing_base": (1.00, 1.00, 1.00),
        "wing_mid": (0.18, 0.21, 0.28),
        "wing_tip": (0.96, 0.18, 0.18),
        "aura": (0.98, 0.24, 0.22),
    },
    "solar_gold": {
        # "Crimson Fox Hundun" (Warm Cream-White + Crimson Fur + Velvet Black Paws)
        "fur_light": (1.00, 0.99, 0.97),
        "fur_mid": (0.95, 0.89, 0.86),
        "fur_dark": (0.58, 0.16, 0.18),
        "fur_deep": (0.08, 0.06, 0.08),
        "wing_base": (1.00, 0.98, 0.96),
        "wing_mid": (0.12, 0.09, 0.12),
        "wing_tip": (0.96, 0.14, 0.14),
        "aura": (0.96, 0.20, 0.16),
    },
}

EMOTION_LIST: List[str] = [
    "idle",
    "love",        # Squishy Happy Petting (Musical Chirps & Sparkles — no hearts!)
    "happy",       # Bouncy Tippy-Tap Dance
    "roar",        # Big Fluffy Puff-Up Boop
    "wing_slash",  # Happy Roly-Poly Tumble Spin
    "excited",     # Zoomies & Fast Wing Flutter
    "thinking",    # Cute Curious Head-Tilt
    "executing",   # Spinning Red-White Ring Juggle
    "sleepy",      # Cozy Curled-Up Marshmallow Loaf
    "dizzy",       # Wobbly Jelly Spin
]

EMOTION_COLORS: Dict[str, Tuple[float, float, float]] = {
    "idle": (0.92, 0.18, 0.20),        # Warm Crimson
    "happy": (0.98, 0.22, 0.22),       # Joyful Scarlet
    "love": (1.00, 0.20, 0.20),        # Warm Crimson Glow (NO pink!)
    "roar": (1.00, 0.98, 0.98),        # Fluffy White Puff
    "wing_slash": (0.98, 0.22, 0.22),  # Playful Crimson Spin
    "excited": (1.00, 0.26, 0.20),     # Bright Red-White
    "thinking": (0.94, 0.96, 1.00),    # Curious Cloud White
    "executing": (0.95, 0.16, 0.18),   # Ten-Rings Crimson
    "surprised": (1.00, 1.00, 1.00),   # Puff White
    "dizzy": (0.88, 0.16, 0.18),       # Wobbly Red
    "sleepy": (0.65, 0.16, 0.18),      # Cozy Ember Red
    "alert": (1.00, 0.12, 0.12),       # Alert Red
}


class SvgGhostRenderer:
    """Renders Tchiko (Dijiang) as a super fluffy, squishy, lovable pet in White/Red/Black."""

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
        # Spring-damped jelly squish state
        self.squish_boost: float = 0.0
        self.hovered: bool = False
        self.state: str = "idle"
        self.emotion_ttl: float = 0.0
        self.idle_seconds: float = 0.0
        self.pet_accumulator: float = 0.0

    def set_emotion(self, emotion: str, duration: float = 4.0) -> None:
        """Trigger an interactive pet mood and give a cute jelly squish bounce!"""
        self.state = emotion
        self.emotion_ttl = duration
        self.squish_boost = 0.22 if emotion in ("roar", "love", "happy", "surprised") else 0.12
        if emotion == "roar":
            self.shockwave_prog = 0.01
        elif emotion == "wing_slash":
            self.spin_angle = 0.01
        if emotion != "sleepy":
            self.idle_seconds = 0.0

    def trigger_boop_squish(self) -> None:
        """Give Tchiko an instant squishy marshmallow boop when clicked/poked!"""
        self.squish_boost = 0.28

    def apply_drag_velocity(self, dx: float, dy: float) -> None:
        """Feed mouse drag velocity so Tchiko squishes and his stubby legs dangle."""
        self.vel_x = max(-30.0, min(30.0, self.vel_x * 0.6 + dx * 0.4))
        self.vel_y = max(-24.0, min(24.0, self.vel_y * 0.6 + dy * 0.4))
        self.idle_seconds = 0.0

    def register_petting(self, motion_delta: float) -> None:
        """Rubbing cursor over Tchiko squishes his fluffy coat & triggers happy chirps!"""
        self.idle_seconds = 0.0
        self.squish_boost = min(0.24, self.squish_boost + abs(motion_delta) * 0.004)
        self.pet_accumulator = min(100.0, self.pet_accumulator + abs(motion_delta) * 0.52)
        if self.pet_accumulator > 34.0 and self.state not in ("love", "roar", "wing_slash", "executing"):
            self.set_emotion("love", duration=4.0)
            self.pet_accumulator = 0.0
        elif self.pet_accumulator > 15.0 and self.state == "idle":
            self.set_emotion("happy", duration=2.6)

    def step(self, dt: float, speed: float = 1.0) -> None:
        """Advance jelly squish physics, wing flutters, and pet mood timers."""
        speed_mult = (
            0.45
            if self.state == "sleepy"
            else (1.70 if self.state in ("excited", "happy", "love", "executing", "roar", "wing_slash") else 1.0)
        )
        self.phase += dt * 3.8 * speed * speed_mult

        self.look_x += (self.target_look_x - self.look_x) * min(1.0, dt * 10.0)
        self.look_y += (self.target_look_y - self.look_y) * min(1.0, dt * 10.0)

        self.vel_x *= 0.82
        self.vel_y *= 0.82
        self.squish_boost *= 0.86
        self.pet_accumulator = max(0.0, self.pet_accumulator - dt * 8.0)

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
        opacity: float = 1.0,
    ) -> None:
        """Export the exact desktop Tchiko Cairo rendering directly to a vector .svg file."""
        surface = cairo.SVGSurface(svg_path, width, height)
        cr = cairo.Context(surface)
        self.draw(cr, width=width, height=height, theme_name=theme_name, opacity=opacity)
        surface.finish()

    def draw(
        self,
        cr: cairo.Context,
        width: int,
        height: int,
        theme_name: str = "phantom_cyan",
        opacity: float = 0.98,
        **_kwargs: Any,
    ) -> None:
        """Render Tchiko as an ultra-fluffy, squishy, chubby pet in White, Red & Black."""
        cr.save()
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)

        theme = THEMES.get(theme_name, THEMES["phantom_cyan"])
        emo_r, emo_g, emo_b = EMOTION_COLORS.get(self.state, EMOTION_COLORS["idle"])

        scale = min(width / 230.0, height / 215.0)

        # Jelly Squash-and-Stretch Physics!
        jelly_wave = math.sin(self.phase * 2.6) * self.squish_boost
        if self.state == "love":
            # Happy petted mochi squish!
            bob_y = 3.0 + math.sin(self.phase * 2.2) * 3.5
            squish_x = 1.13 + math.sin(self.phase * 2.2) * 0.05 + jelly_wave
            squish_y = 0.88 - math.sin(self.phase * 2.2) * 0.04 - jelly_wave * 0.7
        elif self.state in ("happy", "excited"):
            # Bouncy jump with stretch at peak & squish at bottom!
            jump_sin = math.sin(self.phase * 1.4)
            bob_y = -abs(jump_sin) * 11.0 + 4.0
            squish_x = 1.04 - abs(jump_sin) * 0.08 + jelly_wave
            squish_y = 0.96 + abs(jump_sin) * 0.08 - jelly_wave * 0.7
        elif self.state == "roar":
            # Big fluffy marshmallow puff-up!
            bob_y = -6.0 + math.sin(self.phase * 3.5) * 2.5
            squish_x = 1.12 + math.sin(self.phase * 4.0) * 0.04
            squish_y = 1.10 - math.sin(self.phase * 4.0) * 0.04
        elif self.state == "sleepy":
            # Cozy flat loaf
            bob_y = 7.0 + math.sin(self.phase * 0.7) * 2.0
            squish_x = 1.10 + math.sin(self.phase * 0.7) * 0.03
            squish_y = 0.89 - math.sin(self.phase * 0.7) * 0.02
        else:
            bob_y = math.sin(self.phase) * 5.5
            squish_x = 1.0 + math.sin(self.phase * 1.1) * 0.028 + jelly_wave
            squish_y = 1.0 - math.sin(self.phase * 1.1) * 0.028 - jelly_wave * 0.7

        sway_x = math.cos(self.phase * 0.5) * 2.5

        # Cute Tchiko curious head-tilt!
        tilt_rad = max(-0.28, min(0.28, self.vel_x * 0.011))
        if self.state == "thinking":
            tilt_rad += 0.25 + math.sin(self.phase * 0.9) * 0.05
        elif self.state == "dizzy":
            tilt_rad += math.sin(self.phase * 2.5) * 0.25
        elif self.hovered:
            tilt_rad += self.look_x * 0.12

        cr.save()
        cr.translate(width / 2.0 + sway_x, height / 2.0 + bob_y)
        cr.scale(scale, scale)

        # 1. Soft Cozy Ground Shadow
        shadow_scale = max(0.55, 1.0 - (-bob_y / 45.0)) * squish_x
        cr.save()
        cr.translate(0, 74 - bob_y * 0.65)
        cr.scale(50 * shadow_scale, 8.5 * shadow_scale)
        cr.arc(0, 0, 1.0, 0, 2 * math.pi)
        cr.set_source_rgba(0.02, 0.03, 0.06, 0.30 * opacity)
        cr.fill()
        cr.restore()

        # 2. Soft Warm Crimson & Snowy White Aura
        aura_r = 92.0 + (8.0 if self.hovered else 0.0) + math.sin(self.phase * 1.4) * 4.0
        aura = cairo.RadialGradient(0, -2, 14, 0, -2, aura_r)
        aura.add_color_stop_rgba(0.0, emo_r, emo_g, emo_b, 0.32 * opacity)
        aura.add_color_stop_rgba(0.55, 0.98, 0.98, 1.0, 0.12 * opacity)
        aura.add_color_stop_rgba(1.0, 0.0, 0.0, 0.0, 0.0)
        cr.set_source(aura)
        cr.arc(0, -2, aura_r, 0, 2 * math.pi)
        cr.fill()

        # Apply roly-poly spin + tilt + jelly squash-and-stretch
        cr.rotate(tilt_rad + self.spin_angle)
        cr.scale(squish_x, squish_y)

        # 3. FOUR SOFT, PLUMP, FEATHERY WINGS (Snowy White, Velvet Black & Crimson Tips)
        self._draw_plush_feathered_wings(cr, theme, opacity)

        # 4. HIND & MIDDLE CHUBBY PET PAWS (Legs 3, 4, 5, 6)
        self._draw_chubby_pet_legs(cr, theme, opacity, layer="back")

        # 5. ULTRA-FLUFFY, SQUISHY, CLOUD-PUFF MORRIS BODY
        self._draw_fluffy_squishy_body(cr, theme, opacity)

        # 6. FRONT CHUBBY PET PAWS (Legs 1 & 2 with Crimson Toe-Beans)
        self._draw_chubby_pet_legs(cr, theme, opacity, layer="front")

        # 7. PLAYFUL PET EFFECTS (Musical Chirps ♪ ♫, White/Red Sparkles, Puff Rings — NO Hearts!)
        self._draw_pet_particles(cr, opacity, emo_r, emo_g, emo_b)

        cr.restore()
        cr.restore()

    def _draw_plush_feathered_wings(
        self,
        cr: cairo.Context,
        theme: Dict[str, Tuple[float, float, float]],
        opacity: float,
    ) -> None:
        """Draw 4 soft, rounded, pillowy feathered wings in White, Black & Crimson."""
        wb = theme["wing_base"]
        wm = theme["wing_mid"]
        wt = theme["wing_tip"]
        fdeep = theme["fur_deep"]

        if self.state == "sleepy":
            u_ang_l, u_ang_r = -0.48, 0.48
            l_ang_l, l_ang_r = -0.58, 0.58
            spread = 0.80
        elif self.state in ("happy", "excited", "executing"):
            flap = math.sin(self.phase * 2.8) * 0.42
            u_ang_l, u_ang_r = 0.24 + flap, -0.24 - flap
            l_ang_l = 0.05 + math.sin(self.phase * 2.8 - 0.6) * 0.36
            l_ang_r = -0.05 - math.sin(self.phase * 2.8 - 0.6) * 0.36
            spread = 1.12
        elif self.state == "love":
            # Soft, happy wing-hug flutter when petted!
            flap = math.sin(self.phase * 2.4) * 0.28
            u_ang_l, u_ang_r = 0.16 + flap, -0.16 - flap
            l_ang_l, l_ang_r = -0.08 + flap * 0.8, 0.08 - flap * 0.8
            spread = 1.06
        elif self.state == "thinking":
            flap = math.sin(self.phase * 1.1) * 0.12
            u_ang_l, u_ang_r = -0.14 + flap, -0.54 - flap
            l_ang_l, l_ang_r = -0.24 + flap, 0.20 - flap
            spread = 1.02
        elif self.state in ("roar", "surprised"):
            u_ang_l, u_ang_r = 0.36, -0.36
            l_ang_l, l_ang_r = 0.12, -0.12
            spread = 1.20
        else:
            flap_u = math.sin(self.phase * 1.6) * 0.28
            flap_l = math.sin(self.phase * 1.6 - 0.7) * 0.24
            u_ang_l, u_ang_r = 0.08 + flap_u, -0.08 - flap_u
            l_ang_l, l_ang_r = -0.14 + flap_l, 0.14 - flap_l
            spread = 1.02

        # Lower Cute Wings
        self._draw_single_plush_wing(cr, -44, 6, -1.0, l_ang_l, 0.80 * spread, wb, wm, wt, fdeep, opacity)
        self._draw_single_plush_wing(cr, 44, 6, 1.0, l_ang_r, 0.80 * spread, wb, wm, wt, fdeep, opacity)

        # Upper Fluffy Wings
        self._draw_single_plush_wing(cr, -46, -18, -1.0, u_ang_l, 1.06 * spread, wb, wm, wt, fdeep, opacity)
        self._draw_single_plush_wing(cr, 46, -18, 1.0, u_ang_r, 1.06 * spread, wb, wm, wt, fdeep, opacity)

    def _draw_single_plush_wing(
        self,
        cr: cairo.Context,
        anchor_x: float,
        anchor_y: float,
        side: float,
        angle: float,
        scale_factor: float,
        wb: Tuple[float, float, float],
        wm: Tuple[float, float, float],
        wt: Tuple[float, float, float],
        fdeep: Tuple[float, float, float],
        opacity: float,
    ) -> None:
        """Render a soft, rounded, pillowy 3-scallop feathered wing."""
        cr.save()
        cr.translate(anchor_x, anchor_y)
        cr.rotate(angle)
        cr.scale(side * scale_factor, scale_factor)

        grad = cairo.LinearGradient(0, -12, 58, 20)
        grad.add_color_stop_rgba(0.0, wb[0], wb[1], wb[2], 0.99 * opacity)
        grad.add_color_stop_rgba(0.52, wm[0], wm[1], wm[2], 0.97 * opacity)
        grad.add_color_stop_rgba(1.0, wt[0], wt[1], wt[2], 0.98 * opacity)

        # Plump, rounded 3-puff feather contour
        cr.new_path()
        cr.move_to(0, -14)
        cr.curve_to(24, -34, 52, -26, 58, -8)
        cr.curve_to(62, 2, 50, 10, 40, 7)
        cr.curve_to(50, 15, 38, 25, 25, 19)
        cr.curve_to(30, 28, 16, 32, 4, 19)
        cr.close_path()

        cr.set_source(grad)
        cr.fill_preserve()
        cr.set_source_rgba(fdeep[0], fdeep[1], fdeep[2], 0.85 * opacity)
        cr.set_line_width(2.0)
        cr.stroke()

        # Soft white downy shoulder puff inside wing
        cr.arc(12, -4, 9.0, -math.pi * 0.4, math.pi * 0.5)
        cr.set_source_rgba(wb[0], wb[1], wb[2], 0.75 * opacity)
        cr.set_line_width(2.2)
        cr.stroke()

        cr.restore()

    def _draw_fluffy_squishy_body(
        self,
        cr: cairo.Context,
        theme: Dict[str, Tuple[float, float, float]],
        opacity: float,
    ) -> None:
        """Render Tchiko's ultra-fluffy, chubby, squishy mochi-like body with cloud puffs."""
        fl = theme["fur_light"]
        fm = theme["fur_mid"]
        fd = theme["fur_dark"]
        fdeep = theme["fur_deep"]
        wt = theme["wing_tip"]

        shift_x = max(-10.0, min(10.0, self.look_x * 10.0))
        shift_y = max(-7.0, min(7.0, self.look_y * 7.0))

        body_grad = cairo.RadialGradient(
            -12 + shift_x * 0.6,
            -20 + shift_y * 0.6,
            10,
            shift_x * 0.3,
            5,
            68,
        )
        body_grad.add_color_stop_rgba(0.0, fl[0], fl[1], fl[2], 1.00 * opacity)
        body_grad.add_color_stop_rgba(0.55, fm[0], fm[1], fm[2], 0.99 * opacity)
        body_grad.add_color_stop_rgba(0.86, fd[0], fd[1], fd[2], 0.98 * opacity)
        body_grad.add_color_stop_rgba(1.0, fdeep[0], fdeep[1], fdeep[2], 0.96 * opacity)

        # Wide, chubby pear/mochi silhouette with 32 round, pillowy cloud-puffs!
        rx, ry = 60.0, 50.0
        num_puffs = 32
        cr.new_path()
        for i in range(num_puffs):
            t1 = (i / num_puffs) * 2.0 * math.pi
            t_mid = ((i + 0.5) / num_puffs) * 2.0 * math.pi
            t2 = ((i + 1.0) / num_puffs) * 2.0 * math.pi

            # Extra chubby lower cheeks & crown fluff!
            cheek_factor = 1.12 if math.sin(t_mid) > 0.1 else 1.0
            puff_amp = 4.6 if (0.15 < abs(math.cos(t_mid)) < 0.88) else 3.2
            if self.state in ("roar", "love", "happy"):
                puff_amp *= 1.28

            x1 = math.cos(t1) * rx * (1.12 if math.sin(t1) > 0.1 else 1.0)
            y1 = math.sin(t1) * ry
            xm = math.cos(t_mid) * (rx * cheek_factor + puff_amp)
            ym = math.sin(t_mid) * (ry + puff_amp)
            x2 = math.cos(t2) * rx * (1.12 if math.sin(t2) > 0.1 else 1.0)
            y2 = math.sin(t2) * ry

            if i == 0:
                cr.move_to(x1, y1)
            cr.curve_to(xm, ym, xm, ym, x2, y2)
        cr.close_path()

        cr.set_source(body_grad)
        cr.fill_preserve()
        cr.set_source_rgba(fdeep[0], fdeep[1], fdeep[2], 0.85 * opacity)
        cr.set_line_width(2.2)
        cr.stroke()

        # Plush Snowy-White Belly Cushion Patch
        cr.save()
        cr.translate(shift_x * 0.55, 10 + shift_y * 0.45)
        cr.scale(42.0, 33.0)
        cr.arc(0, 0, 1.0, 0, 2 * math.pi)
        belly_grad = cairo.RadialGradient(0, -0.2, 0.1, 0, 0, 1.0)
        belly_grad.add_color_stop_rgba(0.0, 1.0, 1.0, 1.0, 0.85 * opacity)
        belly_grad.add_color_stop_rgba(1.0, fm[0], fm[1], fm[2], 0.0)
        cr.set_source(belly_grad)
        cr.fill()
        cr.restore()

        # Soft Warm Crimson Cheek Glow (NOT pink — pure warm crimson-scarlet ember glow!)
        if self.state in ("love", "happy", "excited") or self.hovered:
            glow_a = 0.36 if self.state in ("love", "happy") else 0.18
            for gx in (-28.0 + shift_x * 0.7, 28.0 + shift_x * 0.7):
                cr.save()
                cr.translate(gx, 4.0 + shift_y * 0.6)
                cr.scale(11.5, 6.5)
                cr.arc(0, 0, 1.0, 0, 2 * math.pi)
                cr.set_source_rgba(wt[0], wt[1], wt[2], glow_a * opacity)
                cr.fill()
                cr.restore()

        # FACELESS FLUFFY TCHIKO FUR-SWIRLS & CUTE SQUISHY DIMPLES
        fx = shift_x * 0.95
        fy = shift_y * 0.85
        cr.set_line_cap(cairo.LINE_CAP_ROUND)

        # Fluffy Crown Tuft Swirl at top of forehead
        cr.move_to(fx - 10, -36 + fy * 0.4)
        cr.curve_to(fx - 2, -46 + fy * 0.4, fx + 8, -44 + fy * 0.4, fx + 12, -35 + fy * 0.4)
        cr.set_source_rgba(wt[0], wt[1], wt[2], 0.75 * opacity)
        cr.set_line_width(2.5)
        cr.stroke()

        # Upper Soft Fur Arch
        arch_lift = -4.5 if self.state in ("happy", "love", "roar", "excited") else (3.0 if self.state == "sleepy" else 0.0)
        cr.move_to(fx - 22, fy - 16 + arch_lift * 0.5)
        cr.curve_to(fx - 8, fy - 26 + arch_lift, fx + 8, fy - 26 + arch_lift, fx + 22, fy - 16 + arch_lift * 0.5)
        cr.set_source_rgba(wt[0], wt[1], wt[2], 0.72 * opacity)
        cr.set_line_width(2.4)
        cr.stroke()

        # Central Cozy Squish-Dimple (curves happily like a plush smile crease!)
        dimple_curve = 10.0 if self.state in ("happy", "love", "excited") else 6.0
        cr.move_to(fx - 26, fy - 2)
        cr.curve_to(fx - 10, fy + dimple_curve, fx + 10, fy + dimple_curve, fx + 26, fy - 2)
        cr.set_source_rgba(fdeep[0], fdeep[1], fdeep[2], 0.65 * opacity)
        cr.set_line_width(2.6)
        cr.stroke()

        # Lower Fluffy Chest Ruff Scallops (3 soft cloud-curls on his chest!)
        for ruff_x, ruff_y, ruff_w in ((fx - 14, fy + 15, 11.0), (fx, fy + 18, 13.0), (fx + 14, fy + 15, 11.0)):
            cr.move_to(ruff_x - ruff_w * 0.5, ruff_y)
            cr.curve_to(ruff_x - ruff_w * 0.25, ruff_y + 6.5, ruff_x + ruff_w * 0.25, ruff_y + 6.5, ruff_x + ruff_w * 0.5, ruff_y)
            cr.set_source_rgba(fd[0], fd[1], fd[2], 0.58 * opacity)
            cr.set_line_width(2.2)
            cr.stroke()

    def _draw_chubby_pet_legs(
        self,
        cr: cairo.Context,
        theme: Dict[str, Tuple[float, float, float]],
        opacity: float,
        layer: str,
    ) -> None:
        """Render Tchiko's 6 short, plump, squishy little paws with Crimson toe-beans."""
        fl = theme["fur_light"]
        fd = theme["fur_dark"]
        fdeep = theme["fur_deep"]
        wt = theme["wing_tip"]

        tuck_y = -11.0 if self.state == "sleepy" else 0.0
        wiggle_amp = 9.5 if self.state in ("happy", "excited", "love", "roar") else (2.0 if self.state == "sleepy" else 5.0)
        drag_swing = -self.vel_x * 0.018

        if layer == "back":
            legs = [
                (-50.0, 34.0 + tuck_y, 11.5, 17.5, 0.42 + drag_swing, 2.1, False),
                (50.0, 34.0 + tuck_y, 11.5, 17.5, -0.42 + drag_swing, 5.2, False),
                (-36.0, 44.0 + tuck_y, 12.5, 19.0, 0.24 + drag_swing, 1.0, False),
                (36.0, 44.0 + tuck_y, 12.5, 19.0, -0.24 + drag_swing, 4.1, False),
            ]
        else:
            legs = [
                (-19.0, 47.0 + tuck_y, 13.5, 20.0, 0.08 + drag_swing, 0.0, True),
                (19.0, 47.0 + tuck_y, 13.5, 20.0, -0.08 + drag_swing, 3.14, True),
            ]

        for lx, ly, rx, ry, base_ang, p_off, is_front in legs:
            step_lift = math.sin(self.phase * 2.3 + p_off) * wiggle_amp
            step_rot = math.cos(self.phase * 2.3 + p_off) * 0.15

            cr.save()
            cr.translate(lx, ly + step_lift * 0.5)
            cr.rotate(base_ang + step_rot)

            leg_grad = cairo.LinearGradient(0, -ry, 0, ry)
            leg_grad.add_color_stop_rgba(0.0, fl[0], fl[1], fl[2], 0.99 * opacity)
            leg_grad.add_color_stop_rgba(0.45, fd[0], fd[1], fd[2], 0.98 * opacity)
            leg_grad.add_color_stop_rgba(1.0, fdeep[0], fdeep[1], fdeep[2], 0.99 * opacity)

            cr.save()
            cr.scale(rx, ry)
            cr.arc(0, 0, 1.0, 0, 2 * math.pi)
            cr.set_source(leg_grad)
            cr.fill_preserve()
            cr.restore()

            cr.set_source_rgba(fdeep[0], fdeep[1], fdeep[2], 0.90 * opacity)
            cr.set_line_width(1.9)
            cr.stroke()

            # Cute Crimson Red Toe-Beans on the front chubby paws!
            if is_front:
                for toe_dx, toe_dy in ((-4.5, ry - 4.8), (0.0, ry - 3.4), (4.5, ry - 4.8)):
                    cr.arc(toe_dx, toe_dy, 2.2, 0, 2 * math.pi)
                    cr.set_source_rgba(wt[0], wt[1], wt[2], 0.92 * opacity)
                    cr.fill()

            cr.restore()

    def _draw_pet_particles(
        self,
        cr: cairo.Context,
        opacity: float,
        er: float,
        eg: float,
        eb: float,
    ) -> None:
        """Render Tchiko's musical chirps (♪ ♫), White/Crimson sparkles, and soft puff rings (zero hearts!)."""
        # 1. Soft Fluffy Puff Ring when Booped ('roar') or Petted ('love')
        if self.shockwave_prog > 0.0 or self.state == "roar":
            p = self.shockwave_prog if self.shockwave_prog > 0.0 else ((self.phase * 0.6) % 1.0)
            rad = 34.0 + p * 66.0
            alpha = max(0.0, (1.0 - p) * 0.85 * opacity)
            cr.arc(0, 0, rad, 0, 2 * math.pi)
            cr.set_source_rgba(1.0, 1.0, 1.0, alpha)
            cr.set_line_width(2.8)
            cr.stroke()

        # 2. Happy Musical Chirp Notes ('♪') & White/Crimson Sparkle Stars ('✦') when Petted or Happy!
        if self.state in ("love", "happy", "excited"):
            spots = ((-70, -28), (70, -32), (-52, -58), (54, -56), (0, -68))
            for i, (sx, sy) in enumerate(spots):
                drift = (self.phase * 11.0 + i * 14.0) % 24.0
                alpha = max(0.0, 1.0 - drift / 24.0) * opacity
                if i % 2 == 0:
                    self._draw_musical_note(
                        cr,
                        sx + math.sin(self.phase + i) * 4.0,
                        sy - drift * 0.7,
                        (0.96, 0.16, 0.18) if i == 0 else (1.0, 1.0, 1.0),
                        alpha,
                    )
                else:
                    twinkle = (0.55 + 0.45 * math.sin(self.phase * 3.2 + i)) * 8.0
                    self._draw_sparkle(
                        cr,
                        sx,
                        sy - drift * 0.4,
                        twinkle,
                        (0.96, 0.16, 0.18) if i == 1 else (1.0, 1.0, 1.0),
                        opacity,
                    )
        elif self.state == "executing":
            # Playful Orbiting Crimson & White Rings
            for r_idx in range(4):
                ang = self.phase * 2.2 + r_idx * (math.pi / 2.0)
                rx = math.cos(ang) * 66.0
                ry = math.sin(ang) * 38.0
                cr.arc(rx, ry, 9.5, 0, 2 * math.pi)
                cr.set_source_rgba(0.95, 0.16, 0.18, 0.92 * opacity)
                cr.set_line_width(2.4)
                cr.stroke()
        elif self.state == "thinking":
            # Curious floating White & Crimson thought puffs
            for i in range(3):
                ang = self.phase * 1.6 + i * (2.0 * math.pi / 3.0)
                ox = math.cos(ang) * 34.0
                oy = -62.0 + math.sin(ang) * 7.0
                cr.arc(ox, oy, 4.5, 0, 2 * math.pi)
                cr.set_source_rgba(1.0 if i % 2 == 0 else 0.94, 1.0 if i % 2 == 0 else 0.16, 1.0 if i % 2 == 0 else 0.18, 0.92 * opacity)
                cr.fill()
        elif self.state == "sleepy":
            # Cozy 'Zzz' sleep letters in White & Crimson
            cr.select_font_face("Sans", cairo.FONT_SLANT_ITALIC, cairo.FONT_WEIGHT_BOLD)
            for i in range(3):
                prog = (self.phase * 0.40 + i * 0.33) % 1.0
                zx = 36.0 + prog * 28.0 + math.sin(prog * 6.0) * 4.0
                zy = -36.0 - prog * 38.0
                alpha = math.sin(prog * math.pi) * 0.92 * opacity
                cr.set_font_size(10.0 + prog * 8.0)
                cr.move_to(zx, zy)
                cr.set_source_rgba(1.0 if i % 2 == 0 else 0.94, 1.0 if i % 2 == 0 else 0.18, 1.0 if i % 2 == 0 else 0.20, alpha)
                cr.show_text("Z")
        elif self.state == "dizzy":
            for i in range(4):
                ang = self.phase * 2.6 + i * (math.pi / 2.0)
                sx = math.cos(ang) * 42.0
                sy = -58.0 + math.sin(ang) * 10.0
                self._draw_sparkle(cr, sx, sy, 6.8, (1.0, 1.0, 1.0) if i % 2 == 0 else (0.95, 0.16, 0.18), opacity)
        else:
            # Soft floating White & Crimson fireflies
            for i in range(4):
                ang = self.phase * (0.75 + i * 0.15) + i * (math.pi / 2.0)
                px = math.cos(ang) * (72.0 + (i % 2) * 6.0)
                py = math.sin(ang * 1.3) * 44.0
                r_dot = 2.8 + math.sin(self.phase * 2.0 + i) * 0.9
                cr.set_source_rgba(1.0 if i % 2 == 0 else 0.94, 1.0 if i % 2 == 0 else 0.16, 1.0 if i % 2 == 0 else 0.18, 0.80 * opacity)
                cr.arc(px, py, r_dot, 0, 2 * math.pi)
                cr.fill()

    @staticmethod
    def _draw_musical_note(
        cr: cairo.Context, x: float, y: float, color: Tuple[float, float, float], alpha: float
    ) -> None:
        """Draw Tchiko's happy musical chirp/whistle note ('♪')."""
        cr.save()
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(15.5)
        cr.move_to(x, y)
        cr.set_source_rgba(color[0], color[1], color[2], alpha)
        cr.show_text("♪")
        cr.restore()

    @staticmethod
    def _draw_sparkle(
        cr: cairo.Context, cx: float, cy: float, size: float, color: Tuple[float, float, float], opacity: float
    ) -> None:
        if size <= 0.5:
            return
        cr.save()
        cr.translate(cx, cy)
        cr.move_to(0, -size)
        cr.curve_to(size * 0.18, -size * 0.18, size * 0.18, -size * 0.18, size, 0)
        cr.curve_to(size * 0.18, size * 0.18, size * 0.18, size * 0.18, 0, size)
        cr.curve_to(-size * 0.18, size * 0.18, -size * 0.18, size * 0.18, -size, 0)
        cr.curve_to(-size * 0.18, -size * 0.18, -size * 0.18, -size * 0.18, 0, -size)
        cr.close_path()
        cr.set_source_rgba(color[0], color[1], color[2], 0.92 * opacity)
        cr.fill()
        cr.restore()
