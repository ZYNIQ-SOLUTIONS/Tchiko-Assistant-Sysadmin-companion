"""Tchiko design system (`tchiko/ui_theme.py`).

One source of truth for every Tchiko surface (floating companion, chat window, settings):

- Colour, type and radius tokens, mirrored in Python (for Pango markup / Cairo) and CSS.
- A single application stylesheet, installed once per process by `apply_theme()`.
- Small widget helpers (`icon`, `icon_button`, `RingGauge`) and the shared
  Markdown -> Pango renderer used by the chat feed and the speech bubble.

Palette: graphite surfaces with one crimson accent taken from the mascot's coat.
Semantic green / amber are reserved for status, never decoration.
"""

from __future__ import annotations

import html
import math
import re
from typing import List, Optional, Tuple

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk

# ── Tokens ───────────────────────────────────────────────────────────────────
BG = "#0d0e11"
SURFACE = "#14161a"
SURFACE_RAISED = "#1a1d23"
SURFACE_HOVER = "#22262e"
BORDER = "#262a32"
BORDER_STRONG = "#353a45"

TEXT = "#eceef2"
TEXT_SECONDARY = "#a3a9b5"
TEXT_MUTED = "#6b7280"

ACCENT = "#e5484d"
ACCENT_HOVER = "#f2555a"
ACCENT_TEXT = "#ff8589"
SUCCESS = "#3ecf8e"
WARNING = "#f5a524"
CODE_TEXT = "#d7dae0"

FONT_UI = '"Ubuntu Sans", "Inter", "Cantarell", "Noto Sans", sans-serif'
FONT_MONO = '"JetBrains Mono", "Ubuntu Sans Mono", "Ubuntu Mono", monospace'
PANGO_MONO = "Ubuntu Sans Mono, JetBrains Mono, monospace"

# Display names for the BoopFace material coats (keys are the renderer's theme ids).
COAT_NAMES: List[Tuple[str, str]] = [
    ("phantom_cyan", "Obsidian Metal"),
    ("astral_violet", "Velvet Slate"),
    ("emerald_matrix", "Porcelain Glaze"),
    ("solar_gold", "Crimson Carbon"),
]

MOOD_NAMES: List[Tuple[str, str]] = [
    ("idle", "Hover"),
    ("happy", "Tippy-tap dance"),
    ("excited", "Zoomies"),
    ("thinking", "Curious head-tilt"),
    ("executing", "Ring juggle"),
    ("roar", "Puff up"),
    ("wing_slash", "Tumble spin"),
    ("dizzy", "Wobbly spin"),
    ("sleepy", "Nap"),
]

_CSS = f"""
@define-color t_bg {BG};
@define-color t_surface {SURFACE};
@define-color t_raised {SURFACE_RAISED};
@define-color t_hover {SURFACE_HOVER};
@define-color t_border {BORDER};
@define-color t_border_strong {BORDER_STRONG};
@define-color t_text {TEXT};
@define-color t_text2 {TEXT_SECONDARY};
@define-color t_muted {TEXT_MUTED};
@define-color t_accent {ACCENT};
@define-color t_accent_hover {ACCENT_HOVER};
@define-color t_success {SUCCESS};
@define-color t_warning {WARNING};

/* ── Base ─────────────────────────────────────────────────────────────── */
.tchiko-root, .tchiko-root * {{
    font-family: {FONT_UI};
}}
window.tchiko-window, .tchiko-root {{
    background-color: @t_bg;
    color: @t_text;
    font-size: 10.5pt;
}}
.tchiko-root label {{ color: @t_text; }}
.tchiko-root label.dim, .tchiko-dim {{ color: @t_text2; }}
.tchiko-root label.muted, .tchiko-muted {{ color: @t_muted; }}
.tchiko-root label.caption {{ font-size: 8.5pt; color: @t_muted; letter-spacing: 0.6px; font-weight: 600; }}
.tchiko-root label.title {{ font-size: 12pt; font-weight: 700; }}
.tchiko-root label.display {{ font-size: 19pt; font-weight: 700; letter-spacing: -0.3px; }}
.tchiko-root label selection, .tchiko-root entry selection, .tchiko-bubble label selection {{
    background-color: alpha(@t_accent, 0.45);
    color: #ffffff;
}}
.tchiko-root label link, .tchiko-bubble label link {{ color: {ACCENT_TEXT}; }}

scrolledwindow.tchiko-scroll, .tchiko-scroll viewport {{ background-color: transparent; border: none; }}
.tchiko-root scrollbar, .tchiko-bubble scrollbar {{ background-color: transparent; border: none; }}
.tchiko-root scrollbar slider, .tchiko-bubble scrollbar slider {{
    background-color: alpha(@t_text, 0.16);
    border-radius: 8px;
    min-width: 5px;
    min-height: 5px;
    border: 2px solid transparent;
}}
.tchiko-root scrollbar slider:hover, .tchiko-bubble scrollbar slider:hover {{ background-color: alpha(@t_text, 0.32); }}
.tchiko-root separator {{ background-color: @t_border; min-height: 1px; min-width: 1px; }}

/* ── Header bar ───────────────────────────────────────────────────────── */
headerbar.tchiko-titlebar {{
    background-image: none;
    background-color: @t_bg;
    border: none;
    border-bottom: 1px solid @t_border;
    box-shadow: none;
    padding: 6px 10px;
    min-height: 44px;
    color: @t_text;
    font-family: {FONT_UI};
}}
headerbar.tchiko-titlebar:backdrop {{ background-color: @t_bg; }}
headerbar.tchiko-titlebar .title {{ font-weight: 700; font-size: 10.5pt; color: @t_text; }}
headerbar.tchiko-titlebar button.titlebutton {{
    background-image: none;
    background-color: transparent;
    border: none;
    box-shadow: none;
    color: @t_text2;
    min-width: 26px;
    min-height: 26px;
    border-radius: 8px;
}}
headerbar.tchiko-titlebar button.titlebutton:hover {{ background-color: @t_hover; color: @t_text; }}

/* ── Segmented switcher ───────────────────────────────────────────────── */
.tchiko-segmented {{
    background-color: @t_surface;
    border: 1px solid @t_border;
    border-radius: 10px;
    padding: 3px;
}}
.tchiko-segmented button {{
    background-image: none;
    background-color: transparent;
    border: none;
    box-shadow: none;
    border-radius: 7px;
    padding: 4px 16px;
    min-height: 22px;
    color: @t_text2;
    font-weight: 600;
    font-size: 9.5pt;
    transition: background-color 140ms ease, color 140ms ease;
}}
.tchiko-segmented button:hover {{ color: @t_text; }}
.tchiko-segmented button:checked {{
    background-color: @t_hover;
    color: @t_text;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.35);
}}

/* ── Buttons ──────────────────────────────────────────────────────────── */
button.tchiko-btn, button.tchiko-icon-btn, button.tchiko-primary, button.tchiko-ghost-btn {{
    background-image: none;
    box-shadow: none;
    text-shadow: none;
    -gtk-icon-shadow: none;
    font-family: {FONT_UI};
    transition: background-color 140ms ease, border-color 140ms ease, color 140ms ease;
}}
button.tchiko-btn {{
    background-color: @t_raised;
    color: @t_text;
    border: 1px solid @t_border;
    border-radius: 9px;
    padding: 6px 14px;
    font-weight: 600;
    font-size: 9.5pt;
}}
button.tchiko-btn:hover {{ background-color: @t_hover; border-color: @t_border_strong; }}
button.tchiko-primary {{
    background-color: @t_accent;
    color: #ffffff;
    border: 1px solid @t_accent;
    border-radius: 9px;
    padding: 6px 16px;
    font-weight: 700;
    font-size: 9.5pt;
}}
button.tchiko-primary:hover {{ background-color: @t_accent_hover; border-color: @t_accent_hover; }}
button.tchiko-primary:disabled {{ background-color: @t_hover; border-color: @t_hover; color: @t_muted; }}
button.tchiko-primary label {{ color: #ffffff; }}
button.tchiko-icon-btn {{
    background-color: transparent;
    color: @t_text2;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 5px;
    min-width: 20px;
    min-height: 20px;
}}
button.tchiko-icon-btn:hover {{ background-color: @t_hover; color: @t_text; }}
button.tchiko-icon-btn:active {{ background-color: @t_border_strong; }}
button.tchiko-ghost-btn {{
    background-color: transparent;
    color: @t_text2;
    border: none;
    border-radius: 7px;
    padding: 3px 8px;
    font-size: 8.5pt;
    font-weight: 600;
}}
button.tchiko-ghost-btn:hover {{ background-color: @t_hover; color: @t_text; }}
button.tchiko-send {{
    background-image: none;
    background-color: @t_accent;
    color: #ffffff;
    border: none;
    box-shadow: none;
    border-radius: 999px;
    padding: 0;
    min-width: 32px;
    min-height: 32px;
    transition: background-color 140ms ease;
}}
button.tchiko-send:hover {{ background-color: @t_accent_hover; }}
button.tchiko-send:disabled {{ background-color: @t_hover; color: @t_muted; }}

/* ── Status pill ──────────────────────────────────────────────────────── */
button.tchiko-pill {{
    background-image: none;
    box-shadow: none;
    border-radius: 999px;
    padding: 3px 11px 3px 9px;
    font-size: 8.8pt;
    font-weight: 600;
    border: 1px solid @t_border;
    background-color: @t_surface;
    color: @t_text2;
}}
button.tchiko-pill:hover {{ background-color: @t_hover; }}
button.tchiko-pill.ok {{ color: @t_success; border-color: alpha(@t_success, 0.32); background-color: alpha(@t_success, 0.08); }}
button.tchiko-pill.review {{ color: @t_warning; border-color: alpha(@t_warning, 0.35); background-color: alpha(@t_warning, 0.08); }}

/* ── Cards & tiles ────────────────────────────────────────────────────── */
.tchiko-card {{
    background-color: @t_surface;
    border: 1px solid @t_border;
    border-radius: 14px;
}}
.tchiko-card-pad {{ padding: 16px 18px; }}
button.tchiko-tile {{
    background-image: none;
    box-shadow: none;
    background-color: @t_surface;
    border: 1px solid @t_border;
    border-radius: 12px;
    padding: 12px 14px;
    color: @t_text;
    transition: background-color 140ms ease, border-color 140ms ease;
}}
button.tchiko-tile:hover {{ background-color: @t_raised; border-color: @t_border_strong; }}
button.tchiko-tile:active {{ background-color: @t_hover; }}
.tchiko-tile-icon {{
    background-color: alpha(@t_accent, 0.12);
    color: {ACCENT_TEXT};
    border-radius: 9px;
    padding: 7px;
}}

/* ── Chat feed ────────────────────────────────────────────────────────── */
.tchiko-user-bubble {{
    background-color: @t_raised;
    border: 1px solid @t_border;
    border-radius: 16px 16px 5px 16px;
    padding: 9px 14px;
}}
.tchiko-activity-chip {{
    background-color: @t_surface;
    border: 1px solid @t_border;
    border-radius: 999px;
    padding: 4px 12px 4px 9px;
}}
.tchiko-activity-chip label {{ color: @t_text2; font-size: 9pt; }}
.tchiko-code-card {{
    background-color: #0a0b0d;
    border: 1px solid @t_border;
    border-radius: 10px;
}}
.tchiko-code-head {{
    border-bottom: 1px solid @t_border;
    padding: 3px 6px 3px 12px;
}}
.tchiko-code-body {{ padding: 10px 12px; }}
.tchiko-code-text, .tchiko-root .tchiko-code-text {{
    font-family: {FONT_MONO};
    font-size: 9.3pt;
    color: {CODE_TEXT};
}}

/* ── Composer ─────────────────────────────────────────────────────────── */
.tchiko-composer {{
    background-color: @t_surface;
    border: 1px solid @t_border_strong;
    border-radius: 16px;
    padding: 5px 6px 5px 8px;
    transition: border-color 160ms ease, box-shadow 160ms ease;
}}
.tchiko-composer.focused {{
    border-color: alpha(@t_accent, 0.75);
    box-shadow: 0 0 0 3px alpha(@t_accent, 0.14);
}}
entry.tchiko-entry {{
    background-image: none;
    background-color: transparent;
    border: none;
    box-shadow: none;
    outline-style: none;
    color: @t_text;
    caret-color: @t_accent;
    padding: 6px 6px;
    font-size: 10.5pt;
    font-family: {FONT_UI};
    min-height: 24px;
}}
entry.tchiko-entry placeholder, entry.tchiko-entry .placeholder {{ color: @t_muted; }}

.tchiko-banner {{
    background-color: alpha(@t_warning, 0.08);
    border: 1px solid alpha(@t_warning, 0.38);
    border-radius: 12px;
    padding: 10px 12px 10px 14px;
}}

/* ── Activity timeline ────────────────────────────────────────────────── */
list.tchiko-timeline {{ background-color: transparent; }}
list.tchiko-timeline row {{
    background-color: transparent;
    padding: 7px 14px;
    border-bottom: 1px solid alpha(@t_border, 0.7);
}}
list.tchiko-timeline row:hover {{ background-color: alpha(@t_text, 0.025); }}
.tchiko-badge {{
    border-radius: 6px;
    padding: 1px 7px;
    font-size: 7.8pt;
    font-weight: 700;
    letter-spacing: 0.5px;
    background-color: @t_hover;
    color: @t_text2;
}}
.tchiko-badge.tool {{ background-color: alpha(@t_accent, 0.14); color: {ACCENT_TEXT}; }}

/* ── Settings ─────────────────────────────────────────────────────────── */
.tchiko-sidebar {{
    background-color: @t_surface;
    border-right: 1px solid @t_border;
    padding: 10px 8px;
}}
.tchiko-sidebar button {{
    background-image: none;
    background-color: transparent;
    border: none;
    box-shadow: none;
    border-radius: 9px;
    padding: 8px 12px;
    color: @t_text2;
    font-weight: 600;
    font-size: 10pt;
}}
.tchiko-sidebar button:hover {{ background-color: @t_hover; color: @t_text; }}
.tchiko-sidebar button:checked {{ background-color: alpha(@t_accent, 0.13); color: @t_text; }}
.tchiko-sidebar button:checked image {{ color: {ACCENT_TEXT}; }}
.tchiko-row {{ padding: 12px 16px; }}
.tchiko-row-title {{ font-weight: 600; }}
.tchiko-hero-ok {{ background-color: alpha(@t_success, 0.06); border-color: alpha(@t_success, 0.30); }}
.tchiko-hero-review {{ background-color: alpha(@t_warning, 0.06); border-color: alpha(@t_warning, 0.32); }}
button.tchiko-coat {{
    background-image: none;
    box-shadow: none;
    background-color: @t_raised;
    border: 1.5px solid @t_border;
    border-radius: 12px;
    padding: 8px 10px 6px 10px;
}}
button.tchiko-coat:hover {{ border-color: @t_border_strong; background-color: @t_hover; }}
button.tchiko-coat:checked {{ border-color: @t_accent; background-color: alpha(@t_accent, 0.10); }}
button.tchiko-coat label {{ font-size: 8.5pt; font-weight: 600; color: @t_text2; }}
button.tchiko-coat:checked label {{ color: @t_text; }}

/* ── Controls ─────────────────────────────────────────────────────────── */
.tchiko-root switch {{
    background-image: none;
    background-color: @t_border_strong;
    border: none;
    box-shadow: none;
    border-radius: 999px;
    min-width: 42px;
    min-height: 22px;
    font-size: 0;
    transition: background-color 160ms ease;
}}
.tchiko-root switch:checked {{ background-color: @t_accent; }}
.tchiko-root switch slider {{
    background-image: none;
    background-color: #ffffff;
    border: none;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.4);
    border-radius: 999px;
    min-width: 18px;
    min-height: 18px;
    margin: 2px;
}}
.tchiko-root switch image {{ color: transparent; }}
.tchiko-root combobox button, .tchiko-root combobox button.combo {{
    background-image: none;
    box-shadow: none;
    background-color: @t_raised;
    color: @t_text;
    border: 1px solid @t_border;
    border-radius: 9px;
    padding: 5px 10px;
    font-size: 9.5pt;
    min-height: 22px;
}}
.tchiko-root combobox button:hover {{ border-color: @t_border_strong; background-color: @t_hover; }}
.tchiko-root scale trough {{
    background-color: @t_border_strong;
    border: none;
    border-radius: 999px;
    min-height: 4px;
}}
.tchiko-root scale highlight {{ background-color: @t_accent; border: none; border-radius: 999px; }}
.tchiko-root scale slider {{
    background-image: none;
    background-color: #ffffff;
    border: none;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.45);
    border-radius: 999px;
    min-width: 16px;
    min-height: 16px;
    margin: -6px;
}}
.tchiko-root spinner, .tchiko-bubble spinner {{ color: @t_accent; }}

/* ── Menus & tooltips (process-wide: these are all Tchiko's) ──────────── */
menu, .menu, .context-menu {{
    background-color: {SURFACE_RAISED};
    border: 1px solid {BORDER_STRONG};
    border-radius: 12px;
    padding: 6px;
    font-family: {FONT_UI};
    font-size: 9.8pt;
}}
menu menuitem {{
    color: {TEXT};
    border-radius: 7px;
    padding: 6px 12px;
    min-height: 20px;
}}
menu menuitem:hover {{ background-color: {SURFACE_HOVER}; color: #ffffff; }}
menu menuitem:disabled {{ color: {TEXT_MUTED}; }}
menu menuitem check {{ min-width: 14px; min-height: 14px; }}
menu menuitem accelerator {{ color: {TEXT_MUTED}; }}
menu separator {{ background-color: {BORDER}; margin: 5px 4px; min-height: 1px; }}
menu menuitem arrow {{ color: {TEXT_MUTED}; }}
tooltip, tooltip.background {{
    background-color: #000000;
    border: 1px solid {BORDER_STRONG};
    border-radius: 7px;
    padding: 2px 4px;
}}
tooltip label {{ color: {TEXT}; font-family: {FONT_UI}; font-size: 8.8pt; }}

/* ── Floating companion ───────────────────────────────────────────────── */
window.tchiko-ghost-win, .tchiko-ghost-transparent, .tchiko-ghost-box {{
    background-color: rgba(0, 0, 0, 0);
    background-image: none;
    border: none;
    box-shadow: none;
}}
.tchiko-bubble, .tchiko-bubble * {{ font-family: {FONT_UI}; }}
.tchiko-bubble {{
    background-color: rgba(20, 22, 26, 0.97);
    border: 1px solid {BORDER_STRONG};
    border-radius: 16px;
    padding: 8px 8px 11px 12px;
    margin: 4px 14px 2px 14px;
    box-shadow: 0 10px 26px rgba(0, 0, 0, 0.50);
    color: {TEXT};
}}
.tchiko-bubble label {{ color: {TEXT}; }}
.tchiko-bubble .bubble-name {{ font-weight: 700; font-size: 9pt; }}
.tchiko-bubble .bubble-body {{ font-size: 9.6pt; }}
.tchiko-bubble button.tchiko-icon-btn {{ padding: 3px; min-width: 18px; min-height: 18px; color: {TEXT_MUTED}; }}
.tchiko-bubble button.tchiko-icon-btn:hover {{ color: {TEXT}; background-color: {SURFACE_HOVER}; }}
.tchiko-status-dot {{
    background-color: {ACCENT};
    border-radius: 999px;
    min-width: 7px;
    min-height: 7px;
}}
.tchiko-quick-pill {{
    background-color: rgba(20, 22, 26, 0.97);
    border: 1px solid alpha({ACCENT}, 0.60);
    border-radius: 999px;
    padding: 3px 4px 3px 12px;
    margin: 2px 14px 12px 14px;
    box-shadow: 0 8px 22px rgba(0, 0, 0, 0.45), 0 0 0 3px alpha({ACCENT}, 0.12);
}}
.tchiko-quick-pill button.tchiko-icon-btn {{ color: {TEXT_MUTED}; padding: 4px; }}
.tchiko-quick-pill button.tchiko-icon-btn:hover {{ color: {TEXT}; background-color: {SURFACE_HOVER}; }}
.tchiko-quick-pill button.tchiko-send {{ min-width: 26px; min-height: 26px; }}
.tchiko-quick-pill entry.tchiko-entry {{ font-size: 9.8pt; padding: 3px 4px; min-height: 22px; }}
"""

_theme_installed = False


def apply_theme() -> None:
    """Install the Tchiko stylesheet for this process (idempotent)."""
    global _theme_installed
    if _theme_installed:
        return
    screen = Gdk.Screen.get_default()
    if screen is None:
        return
    provider = Gtk.CssProvider()
    provider.load_from_data(_CSS.encode("utf-8"))
    Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
    settings = Gtk.Settings.get_default()
    if settings is not None:
        settings.set_property("gtk-application-prefer-dark-theme", True)
    _theme_installed = True


# ── Widget helpers ───────────────────────────────────────────────────────────
def icon(name: str, pixel_size: int = 16) -> Gtk.Image:
    """Symbolic icon that inherits the surrounding CSS text colour."""
    img = Gtk.Image.new_from_icon_name(name, Gtk.IconSize.MENU)
    img.set_pixel_size(pixel_size)
    return img


def icon_button(icon_name: str, tooltip: str, css_class: str = "tchiko-icon-btn", pixel_size: int = 16) -> Gtk.Button:
    btn = Gtk.Button()
    btn.set_image(icon(icon_name, pixel_size))
    btn.set_always_show_image(True)
    btn.set_tooltip_text(tooltip)
    btn.set_relief(Gtk.ReliefStyle.NONE)
    btn.set_valign(Gtk.Align.CENTER)
    btn.get_style_context().add_class(css_class)
    return btn


def label(text: str = "", *classes: str, xalign: float = 0.0, wrap: bool = False, selectable: bool = False) -> Gtk.Label:
    lbl = Gtk.Label(label=text, xalign=xalign)
    for cls in classes:
        lbl.get_style_context().add_class(cls)
    if wrap:
        lbl.set_line_wrap(True)
        lbl.set_line_wrap_mode(2)  # Pango.WrapMode.WORD_CHAR
    lbl.set_selectable(selectable)
    return lbl


def flash_button_icon(btn: Gtk.Button, done_icon: str = "object-select-symbolic", ms: int = 1400) -> None:
    """Swap a button's icon briefly to confirm an action (e.g. copied)."""
    from gi.repository import GLib

    original = btn.get_image()
    size = original.get_pixel_size() if isinstance(original, Gtk.Image) else 16
    btn.set_image(icon(done_icon, size))

    def _restore() -> bool:
        if original is not None:
            btn.set_image(original)
        return False

    GLib.timeout_add(ms, _restore)


def _hex_rgb(value: str) -> Tuple[float, float, float]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def level_color(fraction: float) -> str:
    """Status colour for a utilisation level: calm until it matters."""
    if fraction >= 0.90:
        return ACCENT
    if fraction >= 0.75:
        return WARNING
    return SUCCESS


def set_hidpi_pixbuf(image: Gtk.Image, pixbuf, logical_size: int) -> None:
    """Show `pixbuf` at `logical_size` px, using all of its pixels on HiDPI screens.

    A plain `set_from_pixbuf` maps pixbuf pixels 1:1 to logical pixels, which looks soft at 2x
    scaling. Going through the icon path lets GTK map a (size x scale) pixbuf to device pixels.
    """
    image.set_from_gicon(pixbuf, Gtk.IconSize.DIALOG)
    image.set_pixel_size(logical_size)


class RingGauge(Gtk.Image):
    """Circular utilisation gauge with the percentage in the centre."""

    def __init__(self, size: int = 76) -> None:
        super().__init__()
        self._size = size
        self.set_valign(Gtk.Align.CENTER)
        self.set_fraction(0.0)

    def set_fraction(self, fraction: float) -> None:
        import io

        import cairo
        from gi.repository import GdkPixbuf

        shown = max(0.0, min(1.0, fraction))
        px = self._size * max(1, self.get_scale_factor())
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, px, px)
        cr = cairo.Context(surface)
        stroke = px * 0.085
        radius = px / 2.0 - stroke
        cx = cy = px / 2.0
        cr.set_line_width(stroke)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)

        cr.set_source_rgb(*_hex_rgb(BORDER))
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.stroke()

        if shown > 0.004:
            cr.set_source_rgb(*_hex_rgb(level_color(shown)))
            start = -math.pi / 2.0
            cr.arc(cx, cy, radius, start, start + 2 * math.pi * shown)
            cr.stroke()

        text = f"{int(round(shown * 100))}%"
        cr.select_font_face("Ubuntu Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(radius * 0.56)
        ext = cr.text_extents(text)
        cr.set_source_rgb(*_hex_rgb(TEXT))
        cr.move_to(cx - ext.width / 2.0 - ext.x_bearing, cy - ext.height / 2.0 - ext.y_bearing)
        cr.show_text(text)

        buf = io.BytesIO()
        surface.write_to_png(buf)
        loader = GdkPixbuf.PixbufLoader.new_with_type("png")
        loader.write(buf.getvalue())
        loader.close()
        set_hidpi_pixbuf(self, loader.get_pixbuf(), self._size)


# ── Markdown ─────────────────────────────────────────────────────────────────
_HIDDEN_BLOCKS = re.compile(r"<(?:think|output|channel\|)>.*?(?:</(?:think|output)>|$)", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"```([a-zA-Z0-9_+-]*)[ \t]*\n?(.*?)(?:```|$)", re.DOTALL)


def strip_hidden_blocks(text: str) -> str:
    """Drop model reasoning / fabricated-output tags that must never reach the user."""
    return _HIDDEN_BLOCKS.sub("", text)


def split_markdown_blocks(text: str) -> List[Tuple[str, str, str]]:
    """Split a reply into ("text" | "code", content, language) blocks at fenced code."""
    cleaned = strip_hidden_blocks(text)
    blocks: List[Tuple[str, str, str]] = []
    pos = 0
    for match in _FENCE.finditer(cleaned):
        before = cleaned[pos : match.start()].strip()
        if before:
            blocks.append(("text", before, ""))
        code = match.group(2).strip("\n")
        if code.strip():
            blocks.append(("code", code, match.group(1) or ""))
        pos = match.end()
    tail = cleaned[pos:].strip()
    if tail:
        blocks.append(("text", tail, ""))
    return blocks


def _inline(line: str) -> str:
    """Inline Markdown (code, bold, italic, links) on an already-escaped line."""
    stash: List[str] = []

    def _keep(match: "re.Match[str]") -> str:
        stash.append(
            f"<span font_family='{PANGO_MONO}' size='smaller' background='{SURFACE_HOVER}' "
            f"foreground='{TEXT}'> {match.group(1)} </span>"
        )
        return f"\x00{len(stash) - 1}\x00"

    line = re.sub(r"`([^`]+)`", _keep, line)
    line = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", line)
    line = re.sub(r"(?<![\w*])\*([^*\s][^*]*?)\*(?![\w*])", r"<i>\1</i>", line)
    line = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', line)
    return re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], line)


def markdown_to_pango(text: str, compact: bool = False) -> str:
    """Render prose Markdown (no fenced code) as Pango markup. Always returns valid markup."""
    out: List[str] = []
    for raw in strip_hidden_blocks(text).splitlines():
        stripped = raw.strip()
        line = html.escape(stripped, quote=False)
        if not stripped:
            out.append("")
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            level = len(heading.group(1))
            body = _inline(heading.group(2))
            if compact or level >= 3:
                out.append(f"<b>{body}</b>")
            else:
                out.append(f"<span size='large' weight='bold'>{body}</span>")
            continue
        if re.fullmatch(r"[-*_]{3,}", stripped):
            out.append(f"<span foreground='{BORDER_STRONG}'>────────────</span>")
            continue
        indent = "    " * (min(len(raw) - len(raw.lstrip()), 8) // 2)
        bullet = re.match(r"^[-*•]\s+(.*)$", line)
        if bullet:
            out.append(f"{indent}<span foreground='{TEXT_MUTED}'>•</span>  {_inline(bullet.group(1))}")
            continue
        numbered = re.match(r"^(\d+)[.)]\s+(.*)$", line)
        if numbered:
            out.append(
                f"{indent}<span foreground='{TEXT_MUTED}'>{numbered.group(1)}.</span>  {_inline(numbered.group(2))}"
            )
            continue
        if line.startswith("&gt;"):
            out.append(f"<span foreground='{TEXT_SECONDARY}'><i>{_inline(line[4:].strip())}</i></span>")
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            if re.fullmatch(r"[|\s:-]+", stripped):
                continue
            out.append(f"<span font_family='{PANGO_MONO}' size='smaller'>{line}</span>")
            continue
        out.append(_inline(line))
    # Collapse runs of blank lines so spacing stays even.
    collapsed: List[str] = []
    for item in out:
        if item == "" and (not collapsed or collapsed[-1] == ""):
            continue
        collapsed.append(item)
    return "\n".join(collapsed).strip("\n")


def streaming_markup(text: str, compact: bool = False) -> str:
    """Markup for a reply that is still arriving: prose rendered, fenced code shown monospace."""
    parts: List[str] = []
    for kind, content, _lang in split_markdown_blocks(text):
        if kind == "code":
            parts.append(
                f"<span font_family='{PANGO_MONO}' size='smaller' foreground='{CODE_TEXT}'>"
                f"{html.escape(content, quote=False)}</span>"
            )
        else:
            parts.append(markdown_to_pango(content, compact=compact))
    return "\n\n".join(p for p in parts if p)


def first_code_block(text: str) -> Optional[str]:
    for kind, content, _lang in split_markdown_blocks(text):
        if kind == "code":
            return content
    return None
