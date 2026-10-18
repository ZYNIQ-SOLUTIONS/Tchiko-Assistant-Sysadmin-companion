"""Floating Always-on-Top Interactive Tchiko (Dijiang) Desktop Companion for Ubuntu Linux.

Features:
- Fluffy, squishy White, Crimson Red, and Velvet Black Tchiko pet visual
- **Quick Input Bar directly below the Tchiko SVG**:
  - Type any question or Linux command and press `Enter` (`↵`) to send automatically!
- **Talking Speech Bubble directly above Tchiko**:
  - Streams Tchiko's response live above the pet like Tchiko is talking back to you!
  - Includes 1-click `📋 Copy`, `💬 Full Chat`, and `✖` dismiss buttons.
- **Full Chat Window Option Preserved**:
  - Click the pet (or click the `💬` button next to the quick input) anytime to open/toggle
    the full Chat & System Studio window!
"""

from __future__ import annotations

import html
import math
import re
from typing import Any, Callable, Dict, Optional

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango

from .config_manager import ConfigManager
from .svg_ghost_renderer import EMOTION_LIST, SvgGhostRenderer, THEMES


GHOST_WIDGET_CSS = b"""
window.tchiko-ghost-win,
.tchiko-ghost-transparent,
.tchiko-ghost-box {
    background-color: rgba(0, 0, 0, 0);
    background-image: none;
    border: none;
    box-shadow: none;
}

.tchiko-talk-bubble {
    background-color: rgba(13, 18, 28, 0.95);
    border: 1.5px solid #ef4444;
    border-radius: 14px;
    padding: 10px 12px;
    color: #f8fafc;
}

.tchiko-bubble-btn {
    background-image: none;
    background-color: rgba(30, 41, 59, 0.85);
    color: #cbd5e1;
    border: 1px solid #334155;
    border-radius: 7px;
    padding: 2px 7px;
    font-size: 8pt;
}
.tchiko-bubble-btn:hover {
    background-color: #ef4444;
    color: #ffffff;
    border-color: #f87171;
}

.tchiko-quick-pill {
    background-color: rgba(13, 18, 28, 0.92);
    border: 1.5px solid rgba(239, 68, 68, 0.65);
    border-radius: 18px;
    padding: 4px 8px;
}

entry.tchiko-quick-entry {
    background-color: transparent;
    background-image: none;
    color: #f8fafc;
    border: none;
    box-shadow: none;
    padding: 3px 6px;
    font-size: 9.5pt;
    min-height: 22px;
}

.tchiko-mini-chat-btn {
    background-image: none;
    background-color: rgba(239, 68, 68, 0.18);
    color: #f8fafc;
    border: 1px solid rgba(239, 68, 68, 0.45);
    border-radius: 12px;
    padding: 2px 8px;
    font-size: 9pt;
}
.tchiko-mini-chat-btn:hover {
    background-color: #ef4444;
    color: #ffffff;
}
"""


class FloatingGhostWidget(Gtk.Window):
    """Frameless, transparent, draggable interactive Tchiko companion with quick input & speech bubble."""

    def __init__(
        self,
        config: ConfigManager,
        on_toggle_chat: Callable[[], None],
        on_open_settings: Callable[[], None],
        on_quick_command: Callable[[str], None],
        on_inline_prompt: Callable[[str], None],
        on_quit: Callable[[], None],
    ) -> None:
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.config = config
        self.on_toggle_chat = on_toggle_chat
        self.on_open_settings = on_open_settings
        self.on_quick_command = on_quick_command
        self.on_inline_prompt = on_inline_prompt
        self.on_quit = on_quit

        self.renderer = SvgGhostRenderer()
        self._dragging = False
        self._drag_moved = False
        self._press_root_x = 0.0
        self._press_root_y = 0.0
        self._last_root_x = 0.0
        self._last_root_y = 0.0
        self._last_local_x = 0.0
        self._last_local_y = 0.0
        self._shake_energy = 0.0
        self._win_start_x = 0
        self._win_start_y = 0
        self._width = 190
        self._height = 190
        self._emotion_idx = 0
        self._last_bubble_raw = ""
        self._bubble_hide_timer: Optional[int] = None
        self._bubble_hovered = False

        self._apply_transparent_css()
        self._setup_window_properties()
        self._build_composite_widget()
        self.config.subscribe(self._on_config_updated)

        self._render_frame()
        self._anim_source_id = GLib.timeout_add(36, self._on_tick)

    def _apply_transparent_css(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(GHOST_WIDGET_CSS)
        screen = Gdk.Screen.get_default()
        if screen is not None:
            Gtk.StyleContext.add_provider_for_screen(
                screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_USER
            )
        self.get_style_context().add_class("tchiko-ghost-win")

    def _setup_window_properties(self) -> None:
        ghost_cfg = self.config.data.get("ghost_widget", {})
        size = int(ghost_cfg.get("size", 150))
        self._width = size + 36
        self._height = size + 36

        self.set_title("Tchiko Companion")
        self.set_decorated(False)
        self.set_resizable(False)

        self.set_keep_above(bool(ghost_cfg.get("always_on_top", True)))
        if ghost_cfg.get("stick_all_workspaces", True):
            self.stick()
        self.set_type_hint(Gdk.WindowTypeHint.NORMAL)

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual is not None:
            self.set_visual(visual)

        pos_x = int(ghost_cfg.get("position_x", 960))
        pos_y = int(ghost_cfg.get("position_y", 140))
        if screen is not None:
            sw = screen.get_width()
            sh = screen.get_height()
            if sw > 200 and sh > 200:
                pos_x = max(20, min(pos_x, sw - 260))
                pos_y = max(40, min(pos_y, sh - 280))
        self.move(pos_x, pos_y)

    def _build_composite_widget(self) -> None:
        """Build: [Top Talking Speech Bubble] + [Middle Tchiko SVG Pet] + [Bottom Quick Input Pill]."""
        self.main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.main_vbox.get_style_context().add_class("tchiko-ghost-transparent")
        self.main_vbox.set_halign(Gtk.Align.CENTER)

        # ── 1. TOP TALKING SPEECH BUBBLE (Hidden until Tchiko speaks) ─────────
        self.bubble_eb = Gtk.EventBox()
        self.bubble_eb.set_visible_window(False)
        self.bubble_eb.connect("enter-notify-event", self._on_bubble_enter)
        self.bubble_eb.connect("leave-notify-event", self._on_bubble_leave)

        self.bubble_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.bubble_card.get_style_context().add_class("tchiko-talk-bubble")
        self.bubble_card.set_size_request(255, -1)

        # Header inside talking bubble
        b_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        b_title = Gtk.Label(xalign=0.0)
        b_title.set_markup("<span size='small' weight='bold' foreground='#ef4444'>🐾 Tchiko</span>")
        b_hdr.pack_start(b_title, True, True, 0)

        self.bubble_copy_btn = Gtk.Button(label="📋 Copy")
        self.bubble_copy_btn.get_style_context().add_class("tchiko-bubble-btn")
        self.bubble_copy_btn.connect("clicked", self._on_copy_bubble)
        b_hdr.pack_end(self.bubble_copy_btn, False, False, 0)

        b_chat_btn = Gtk.Button(label="💬 Chat")
        b_chat_btn.set_tooltip_text("Open Full Chat Window")
        b_chat_btn.get_style_context().add_class("tchiko-bubble-btn")
        b_chat_btn.connect("clicked", lambda *_: self.on_toggle_chat())
        b_hdr.pack_end(b_chat_btn, False, False, 0)

        b_close_btn = Gtk.Button(label="✖")
        b_close_btn.get_style_context().add_class("tchiko-bubble-btn")
        b_close_btn.connect("clicked", lambda *_: self.hide_speech_bubble())
        b_hdr.pack_end(b_close_btn, False, False, 0)

        self.bubble_card.pack_start(b_hdr, False, False, 0)

        # Scrollable reply label inside bubble (handles short answers & multi-line SSH keys)
        self.bubble_scroll = Gtk.ScrolledWindow()
        self.bubble_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.bubble_scroll.set_max_content_height(150)
        self.bubble_scroll.set_propagate_natural_height(True)

        self.bubble_label = Gtk.Label(xalign=0.0)
        self.bubble_label.set_line_wrap(True)
        self.bubble_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.bubble_label.set_max_width_chars(34)
        self.bubble_label.set_selectable(True)
        self.bubble_scroll.add(self.bubble_label)
        self.bubble_card.pack_start(self.bubble_scroll, False, False, 0)

        self.bubble_eb.add(self.bubble_card)
        self.bubble_card.show_all()
        self.bubble_eb.set_no_show_all(True)
        self.bubble_eb.hide()
        self.main_vbox.pack_start(self.bubble_eb, False, False, 0)

        # ── 2. MIDDLE: FLUFFY SQUISHY TCHIKO PET SVG ──────────────────────────
        self.event_box = Gtk.EventBox()
        self.event_box.set_visible_window(False)
        self.event_box.set_halign(Gtk.Align.CENTER)
        self.event_box.get_style_context().add_class("tchiko-ghost-box")
        self.event_box.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
            | Gdk.EventMask.ENTER_NOTIFY_MASK
            | Gdk.EventMask.LEAVE_NOTIFY_MASK
            | Gdk.EventMask.SCROLL_MASK
        )

        self.image = Gtk.Image()
        self.event_box.add(self.image)

        self.event_box.connect("button-press-event", self._on_button_press)
        self.event_box.connect("button-release-event", self._on_button_release)
        self.event_box.connect("motion-notify-event", self._on_motion_notify)
        self.event_box.connect("enter-notify-event", self._on_enter_notify)
        self.event_box.connect("leave-notify-event", self._on_leave_notify)
        self.event_box.connect("scroll-event", self._on_scroll_event)
        self.main_vbox.pack_start(self.event_box, False, False, 0)

        # ── 3. BOTTOM: FAST INTERACTION QUICK-INPUT BAR (Hidden until Middle-Click) ─
        self.quick_pill = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.quick_pill.get_style_context().add_class("tchiko-quick-pill")
        self.quick_pill.set_halign(Gtk.Align.CENTER)

        self.quick_entry = Gtk.Entry()
        self.quick_entry.get_style_context().add_class("tchiko-quick-entry")
        self.quick_entry.set_width_chars(20)
        self.quick_entry.set_placeholder_text("Ask Tchiko... ↵")
        self.quick_entry.connect("activate", self._on_quick_entry_activate)
        self.quick_entry.connect("key-press-event", self._on_quick_entry_key_press)
        self.quick_pill.pack_start(self.quick_entry, True, True, 0)

        open_chat_btn = Gtk.Button(label="💬")
        open_chat_btn.set_tooltip_text("Open / Toggle Full Tchiko Chat Window")
        open_chat_btn.get_style_context().add_class("tchiko-mini-chat-btn")
        open_chat_btn.connect("clicked", lambda *_: self.on_toggle_chat())
        self.quick_pill.pack_start(open_chat_btn, False, False, 0)

        close_quick_btn = Gtk.Button(label="✖")
        close_quick_btn.set_tooltip_text("Hide Quick Input (or Middle-Click Tchiko / press Esc)")
        close_quick_btn.get_style_context().add_class("tchiko-bubble-btn")
        close_quick_btn.connect("clicked", lambda *_: self.hide_quick_input())
        self.quick_pill.pack_end(close_quick_btn, False, False, 0)

        self.quick_entry.show()
        open_chat_btn.show()
        close_quick_btn.show()
        self.quick_pill.set_no_show_all(True)
        self.quick_pill.hide()
        self.main_vbox.pack_start(self.quick_pill, False, False, 0)
        self.add(self.main_vbox)

    def toggle_quick_input(self) -> None:
        """Toggle the quick-input bar below Tchiko (triggered by middle-click / scroll-wheel click)."""
        if self.quick_pill.get_visible():
            self.hide_quick_input()
        else:
            self.show_quick_input()

    def show_quick_input(self) -> None:
        """Show and focus the quick-input bar below Tchiko."""
        self.quick_pill.set_no_show_all(False)
        self.quick_pill.show_all()
        self.quick_pill.set_no_show_all(True)
        self.set_accept_focus(True)
        self.present_with_time(Gdk.CURRENT_TIME)
        self.quick_entry.grab_focus()

    def hide_quick_input(self) -> None:
        """Hide the quick-input bar below Tchiko and shrink window bounds."""
        self.quick_pill.hide()
        self.resize(1, 1)

    def _on_quick_entry_key_press(self, _widget: Gtk.Widget, event: Gdk.EventKey) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            self.hide_quick_input()
            return True
        return False

    def _on_quick_entry_activate(self, entry: Gtk.Entry) -> None:
        """Called when the user presses Enter in the quick input below Tchiko."""
        text = entry.get_text().strip()
        if not text:
            return
        entry.set_text("")
        self.hide_quick_input()
        self.renderer.trigger_boop_squish()
        self.renderer.set_emotion("thinking", duration=6.0)
        self.show_speech_bubble("<i>Thinking...</i>", is_markup=True, auto_hide_sec=0)
        self.on_inline_prompt(text)

    def show_speech_bubble(
        self, text: str, is_markup: bool = False, auto_hide_sec: int = 22
    ) -> None:
        """Show or update the talking speech bubble above Tchiko."""
        GLib.idle_add(self._apply_speech_bubble, text, is_markup, auto_hide_sec)

    def _apply_speech_bubble(self, text: str, is_markup: bool, auto_hide_sec: int) -> bool:
        self._last_bubble_raw = text
        if is_markup:
            self.bubble_label.set_markup(text)
        else:
            self.bubble_label.set_markup(self._format_bubble_pango(text))

        self.bubble_eb.set_no_show_all(False)
        self.bubble_eb.show_all()
        self.bubble_eb.set_no_show_all(True)

        if self._bubble_hide_timer is not None:
            GLib.source_remove(self._bubble_hide_timer)
            self._bubble_hide_timer = None

        if auto_hide_sec > 0:
            self._bubble_hide_timer = GLib.timeout_add_seconds(
                auto_hide_sec, self._on_bubble_timeout
            )
        return False

    def hide_speech_bubble(self) -> None:
        if self._bubble_hide_timer is not None:
            GLib.source_remove(self._bubble_hide_timer)
            self._bubble_hide_timer = None
        self.bubble_eb.hide()
        self.resize(1, 1)

    def _on_bubble_timeout(self) -> bool:
        if self._bubble_hovered:
            # Keep open while the user's cursor is hovering over the bubble
            return True
        self._bubble_hide_timer = None
        self.bubble_eb.hide()
        self.resize(1, 1)
        return False

    def _on_bubble_enter(self, *_args: Any) -> bool:
        self._bubble_hovered = True
        return False

    def _on_bubble_leave(self, *_args: Any) -> bool:
        self._bubble_hovered = False
        return False

    def _on_copy_bubble(self, btn: Gtk.Button) -> None:
        clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        # If there is a fenced code block inside the reply (e.g., an SSH key), copy the code block content!
        m_code = re.search(r"```(?:[a-zA-Z0-9_-]*\n)?(.*?)```", self._last_bubble_raw, re.DOTALL)
        to_copy = m_code.group(1).strip() if m_code else self._last_bubble_raw.strip()
        clip.set_text(to_copy, -1)
        self.bubble_copy_btn.set_label("✓ Copied")
        GLib.timeout_add(1500, lambda: (self.bubble_copy_btn.set_label("📋 Copy"), False)[1])

    @staticmethod
    def _format_bubble_pango(raw_text: str) -> str:
        """Convert markdown response into compact, readable Pango markup for the talking bubble."""
        cleaned = re.sub(r"```[a-zA-Z0-9_-]*\n?", "", raw_text)
        lines = []
        for raw_line in cleaned.strip().splitlines():
            line = html.escape(raw_line)
            if line.startswith("### "):
                line = f"<b><span foreground='#f87171'>{line[4:].strip()}</span></b>"
            elif line.startswith("- "):
                line = "• " + line[2:]
            line = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", line)
            line = re.sub(
                r"`([^`]+)`",
                r"<span font_family='monospace' foreground='#fca5a5'>\1</span>",
                line,
            )
            lines.append(line)
        return "<span size='small'>" + "\n".join(lines) + "</span>"

    def _render_frame(self) -> None:
        ghost_cfg = self.config.data.get("ghost_widget", {})
        pixbuf = self.renderer.render_to_pixbuf(
            width=self._width,
            height=self._height,
            theme_name=ghost_cfg.get("theme", "phantom_cyan"),
            opacity=float(ghost_cfg.get("opacity", 0.98)),
        )
        self.image.set_from_pixbuf(pixbuf)

    def set_agent_state(self, state: str, _speech: Optional[str] = None) -> None:
        """Update Tchiko pet animation state."""
        GLib.idle_add(self._apply_state, state)

    def _apply_state(self, state: str) -> bool:
        duration = 0.0 if state in ("idle", "thinking", "executing") else 4.2
        self.renderer.set_emotion(state, duration=duration)
        self._render_frame()
        return False

    def _on_config_updated(self, new_data: Dict[str, Any]) -> None:
        ghost_cfg = new_data.get("ghost_widget", {})
        size = int(ghost_cfg.get("size", 150))
        self._width = size + 36
        self._height = size + 36
        self.set_keep_above(bool(ghost_cfg.get("always_on_top", True)))
        if ghost_cfg.get("stick_all_workspaces", True):
            self.stick()
        else:
            self.unstick()
        self._render_frame()

    def _on_tick(self) -> bool:
        speed = float(self.config.data.get("ghost_widget", {}).get("animation_speed", 1.0))
        self._shake_energy = max(0.0, self._shake_energy - 1.5)
        self.renderer.step(0.036, speed=speed)
        self._render_frame()
        return True

    def _on_enter_notify(self, _widget: Gtk.Widget, event: Gdk.EventCrossing) -> bool:
        self.renderer.hovered = True
        self._last_local_x = event.x
        self._last_local_y = event.y
        if self.renderer.state == "sleepy":
            self.renderer.set_emotion("roar", duration=1.8)
        return False

    def _on_leave_notify(self, _widget: Gtk.Widget, _event: Gdk.EventCrossing) -> bool:
        self.renderer.hovered = False
        self.renderer.target_look_x = 0.0
        self.renderer.target_look_y = 0.0
        return False

    def _on_scroll_event(self, _widget: Gtk.Widget, event: Gdk.EventScroll) -> bool:
        """Scroll wheel on Tchiko cycles through all 10 pet moods."""
        if event.direction in (Gdk.ScrollDirection.UP, Gdk.ScrollDirection.RIGHT):
            self._emotion_idx = (self._emotion_idx + 1) % len(EMOTION_LIST)
        else:
            self._emotion_idx = (self._emotion_idx - 1) % len(EMOTION_LIST)
        chosen = EMOTION_LIST[self._emotion_idx]
        self.renderer.set_emotion(chosen, duration=6.0)
        return True

    def _on_motion_notify(self, widget: Gtk.Widget, event: Gdk.EventMotion) -> bool:
        alloc = widget.get_allocation()
        if alloc.width > 0 and alloc.height > 0:
            self.renderer.target_look_x = (event.x - alloc.width / 2.0) / (alloc.width / 2.0)
            self.renderer.target_look_y = (event.y - alloc.height / 2.0) / (alloc.height / 2.0)

        if self._dragging:
            step_dx = event.x_root - self._last_root_x
            step_dy = event.y_root - self._last_root_y
            self._last_root_x = event.x_root
            self._last_root_y = event.y_root

            self.renderer.apply_drag_velocity(step_dx, step_dy)
            speed_mag = math.hypot(step_dx, step_dy)
            if speed_mag > 26.0:
                self._shake_energy += speed_mag * 0.32
                if self._shake_energy > 85.0:
                    self.renderer.set_emotion("wing_slash", duration=2.5)
                    self._shake_energy = 0.0

            dx = int(event.x_root - self._press_root_x)
            dy = int(event.y_root - self._press_root_y)
            if abs(dx) > 4 or abs(dy) > 4:
                self._drag_moved = True
                new_x = max(0, self._win_start_x + dx)
                new_y = max(0, self._win_start_y + dy)
                self.move(new_x, new_y)
        else:
            pet_dist = math.hypot(event.x - self._last_local_x, event.y - self._last_local_y)
            self._last_local_x = event.x
            self._last_local_y = event.y
            if 2.0 < pet_dist < 45.0:
                self.renderer.register_petting(pet_dist)
        return True

    def _on_button_press(self, _widget: Gtk.Widget, event: Gdk.EventButton) -> bool:
        self.renderer.trigger_boop_squish()
        if event.button == 1:
            if event.type == Gdk.EventType._2BUTTON_PRESS:
                self._dragging = False
                self.renderer.set_emotion("excited", duration=3.0)
                self.on_open_settings()
                return True
            self._dragging = True
            self._drag_moved = False
            self._press_root_x = event.x_root
            self._press_root_y = event.y_root
            self._last_root_x = event.x_root
            self._last_root_y = event.y_root
            win_x, win_y = self.get_position()
            self._win_start_x = win_x
            self._win_start_y = win_y
            return True
        elif event.button == 2:
            # Middle-click (scroll-wheel click) toggles the quick input bar below Tchiko
            if event.type == Gdk.EventType.BUTTON_PRESS:
                self.renderer.set_emotion("happy", duration=2.5)
                self.toggle_quick_input()
            return True
        elif event.button == 3:
            self._show_context_menu(event)
            return True
        return False

    def _on_button_release(self, _widget: Gtk.Widget, event: Gdk.EventButton) -> bool:
        if event.button == 1 and self._dragging:
            self._dragging = False
            if self._drag_moved:
                win_x, win_y = self.get_position()
                ghost_cfg = self.config.data.setdefault("ghost_widget", {})
                ghost_cfg["position_x"] = int(win_x)
                ghost_cfg["position_y"] = int(win_y)
                self.config.save(notify=False)
                if self.renderer.state not in ("wing_slash", "roar"):
                    self.renderer.set_emotion("happy", duration=2.0)
            else:
                self.renderer.set_emotion("happy", duration=2.2)
                self.on_toggle_chat()
            return True
        return False

    def _show_context_menu(self, event: Gdk.EventButton) -> None:
        menu = Gtk.Menu()

        quick_item = Gtk.MenuItem(label="⌨️ Toggle Quick Input Bar (Middle-Click)")
        quick_item.connect("activate", lambda *_: self.toggle_quick_input())
        menu.append(quick_item)

        chat_item = Gtk.MenuItem(label="💬 Open / Toggle Full Tchiko Chat Window")
        chat_item.connect("activate", lambda *_: self.on_toggle_chat())
        menu.append(chat_item)

        settings_item = Gtk.MenuItem(label="⚙️ Open Tchiko Settings & Permissions...")
        settings_item.connect("activate", lambda *_: self.on_open_settings())
        menu.append(settings_item)

        menu.append(Gtk.SeparatorMenuItem())

        emo_menu_item = Gtk.MenuItem(label="🐾 Tchiko Pet Moods & Tricks")
        emo_sub = Gtk.Menu()
        for emo_key, emo_label in (
            ("love", "🎶 Squishy Happy Petting (Chirps & Sparkles)"),
            ("happy", "🐾 Bouncy 6-Leg Tippy-Tap Dance"),
            ("roar", "☁️ Big Fluffy Marshmallow Puff-Up"),
            ("wing_slash", "🌀 Playful Roly-Poly Tumble Spin (Fast Flick)"),
            ("excited", "✨ Happy Zoomies & Wing Flutter"),
            ("thinking", "🤔 Cute Curious Head-Tilt"),
            ("executing", "⭕ Red & White Ring Juggle"),
            ("idle", "🐾 Fluffy Hover (Default)"),
            ("sleepy", "😴 Cozy Curled-Up Mochi Loaf (Zzz)"),
            ("dizzy", "💫 Wobbly Jelly Spin"),
        ):
            e_item = Gtk.MenuItem(label=emo_label)
            e_item.connect(
                "activate",
                lambda _w, ek=emo_key: self.renderer.set_emotion(ek, duration=7.0),
            )
            emo_sub.append(e_item)
        emo_menu_item.set_submenu(emo_sub)
        menu.append(emo_menu_item)

        theme_menu_item = Gtk.MenuItem(label="🎨 Tchiko White / Red / Black Coats")
        theme_sub = Gtk.Menu()
        for theme_key, display_name in (
            ("phantom_cyan", "Crimson Cloud Tchiko (Snowy White, Velvet Black & Crimson)"),
            ("astral_violet", "Velvet Panda Hundun (Charcoal, Snowy Belly & Red Tips)"),
            ("emerald_matrix", "Pure Marshmallow Mochi (Bright White & Scarlet)"),
            ("solar_gold", "Crimson Fox Hundun (Warm Cream-White & Deep Crimson)"),
        ):
            t_item = Gtk.MenuItem(label=display_name)
            t_item.connect("activate", lambda _w, tk=theme_key: self._set_theme(tk))
            theme_sub.append(t_item)
        theme_menu_item.set_submenu(theme_sub)
        menu.append(theme_menu_item)

        menu.append(Gtk.SeparatorMenuItem())

        perm_item = Gtk.CheckMenuItem(label="🛡️ Approve All Linux System Permissions")
        perm_item.set_active(self.config.is_all_permissions_approved())
        perm_item.connect(
            "toggled",
            lambda item: self.config.set_all_permissions(item.get_active()),
        )
        menu.append(perm_item)

        sys_menu_item = Gtk.MenuItem(label="⚡ Quick Ubuntu System Actions")
        sys_sub = Gtk.Menu()
        for label, cmd in (
            ("🩺 Run 5-Point System Doctor (/doctor)", "/doctor"),
            ("🧠 Inspect Agent Memory & Notes (/memory)", "/memory"),
            ("🔑 Create OpenSSH Key for Hetzner", "tchiko create an ssh key for my remote hetzner server in OpenSSH format"),
            ("🖥️ System Telemetry Report (/sysinfo)", "/sysinfo"),
            ("⚙️ Top Running Processes (/procs)", "/procs"),
            ("📂 List Desktop Files (/files ~/Desktop)", "/files ~/Desktop"),
            ("🌐 Check Listening Ports", "check listening ports"),
        ):
            sub_item = Gtk.MenuItem(label=label)
            sub_item.connect("activate", lambda _w, c=cmd: self.on_quick_command(c))
            sys_sub.append(sub_item)
        sys_menu_item.set_submenu(sys_sub)
        menu.append(sys_menu_item)

        menu.append(Gtk.SeparatorMenuItem())

        quit_item = Gtk.MenuItem(label="❌ Quit Tchiko Assistant")
        quit_item.connect("activate", lambda *_: self.on_quit())
        menu.append(quit_item)

        menu.show_all()
        menu.popup_at_pointer(event)

    def _set_theme(self, theme_key: str) -> None:
        if theme_key in THEMES:
            self.config.data.setdefault("ghost_widget", {})["theme"] = theme_key
            self.config.save(notify=True)
            self.renderer.set_emotion("roar", duration=2.5)
