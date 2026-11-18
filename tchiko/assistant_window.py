"""Tchiko chat & system window (`tchiko/assistant_window.py`).

Three views behind a segmented switcher in the header bar:

- **Chat** — a centred conversation column. Your messages sit right in soft bubbles; Tchiko's
  replies are unboxed, with a live activity chip while it works, rendered Markdown, code cards
  with one-click copy, and a footer showing how many tools ran and how long it took.
- **System** — host summary, live CPU / memory / disk ring gauges, the full-access switch and
  one-click sysadmin actions.
- **Activity** — a timeline of every thought and tool call the agent made.

All styling comes from `tchiko/ui_theme.py`.
"""

from __future__ import annotations

from datetime import datetime
import html
import os
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango

from . import ui_theme as ui
from .agent_engine import TchikoAgentEngine
from .config_manager import ConfigManager
from .svg_ghost_renderer import SvgGhostRenderer
from .system_tools import LinuxSystemToolkit

SSH_KEY_PROMPT = "create an ssh key for my remote hetzner server in OpenSSH format"

# (icon, title, description, prompt)
STARTERS: List[Tuple[str, str, str, str]] = [
    ("utilities-system-monitor-symbolic", "Run a health check", "CPU, memory, disk, services and ports", "/doctor"),
    ("network-wired-symbolic", "See what's listening", "Open ports and the processes behind them", "check listening ports"),
    ("dialog-password-symbolic", "Create an SSH key", "Ed25519 keypair, public key copied for you", SSH_KEY_PROMPT),
    ("document-open-recent-symbolic", "What do you remember?", "Working directory, notes and last results", "/memory"),
]

QUICK_ACTIONS: List[Tuple[str, str, str, str]] = [
    ("utilities-system-monitor-symbolic", "System doctor", "Full health audit", "/doctor"),
    ("view-list-symbolic", "Top processes", "By CPU and memory", "/procs"),
    ("network-wired-symbolic", "Listening ports", "Sockets and owners", "check listening ports"),
    ("package-x-generic-symbolic", "Docker containers", "Running and stopped", "check docker containers"),
    ("applications-engineering-symbolic", "Dev tool versions", "python, node, git and more", "check installed tools versions"),
    ("dialog-password-symbolic", "New SSH key", "Ed25519, OpenSSH format", SSH_KEY_PROMPT),
]

SLASH_MENU: List[Tuple[str, str]] = [
    ("System doctor", "/doctor"),
    ("System report", "/sysinfo"),
    ("Top processes", "/procs"),
    ("Listening ports", "check listening ports"),
    ("Desktop files", "/files ~/Desktop"),
    ("Memory and notes", "/memory"),
    ("Permission policy", "/permissions"),
    ("Help", "/help"),
]

MAX_TIMELINE_ROWS = 400


class TchikoAssistantWindow(Gtk.Window):
    """Chat, system overview and agent activity for Tchiko."""

    def __init__(
        self,
        config: ConfigManager,
        toolkit: LinuxSystemToolkit,
        engine: TchikoAgentEngine,
        on_open_settings: Callable[[], None],
        on_ghost_state: Callable[[str, Optional[str]], None],
    ) -> None:
        super().__init__(title="Tchiko")
        self.config = config
        self.toolkit = toolkit
        self.engine = engine
        self.on_open_settings = on_open_settings
        self.on_ghost_state = on_ghost_state

        self._mini_renderer = SvgGhostRenderer()
        self._bubble_listener: Optional[Callable[[str], None]] = None
        self._approve_cb: Optional[Callable[[], None]] = None
        self._deny_cb: Optional[Callable[[], None]] = None

        # State of the reply currently being streamed.
        self._busy = False
        self._stream_tokens: List[str] = []
        self._stream_label: Optional[Gtk.Label] = None
        self._stream_content: Optional[Gtk.Box] = None
        self._stream_chip: Optional[Gtk.Box] = None
        self._stream_chip_label: Optional[Gtk.Label] = None
        self._stream_footer: Optional[Gtk.Box] = None
        self._stream_meta: Optional[Gtk.Label] = None
        self._stream_flush_id: Optional[int] = None
        self._stream_started = 0.0
        self._stream_tools = 0
        self._welcome: Optional[Gtk.Widget] = None
        self._welcome_avatar: Optional[Gtk.Image] = None
        self._side_margin = -1

        ui.apply_theme()
        self.get_style_context().add_class("tchiko-window")
        self.set_default_size(960, 720)
        self.set_keep_above(True)
        self.connect("delete-event", self._on_delete_event)

        self._build_body()
        self._build_headerbar()

        self.config.subscribe(self._on_config_changed)
        self._on_config_changed(self.config.data)

        GLib.timeout_add(80, self._tick_avatars)
        GLib.timeout_add_seconds(3, self._refresh_telemetry)
        self._refresh_telemetry()

    # ── Window chrome ────────────────────────────────────────────────────────
    def _on_delete_event(self, _widget: Gtk.Widget, _event: Any) -> bool:
        self.hide()
        return True

    def _build_headerbar(self) -> None:
        hbar = Gtk.HeaderBar()
        hbar.set_show_close_button(True)
        hbar.get_style_context().add_class("tchiko-titlebar")

        brand = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=9)
        self.mini_avatar_img = Gtk.Image()
        brand.pack_start(self.mini_avatar_img, False, False, 0)
        name_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        name_box.set_valign(Gtk.Align.CENTER)
        name_lbl = Gtk.Label(xalign=0.0)
        name_lbl.set_markup(f"<span weight='bold' foreground='{ui.TEXT}'>Tchiko</span>")
        self.status_lbl = Gtk.Label(xalign=0.0)
        self.status_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        self.status_lbl.set_width_chars(18)
        self.status_lbl.set_max_width_chars(18)
        name_box.pack_start(name_lbl, False, False, 0)
        name_box.pack_start(self.status_lbl, False, False, 0)
        brand.pack_start(name_box, False, False, 0)
        hbar.pack_start(brand)
        self._set_status("idle", "Ready")

        switcher = Gtk.StackSwitcher()
        switcher.set_stack(self.stack)
        switcher.get_style_context().add_class("tchiko-segmented")
        hbar.set_custom_title(switcher)

        settings_btn = ui.icon_button("emblem-system-symbolic", "Settings")
        settings_btn.connect("clicked", lambda *_: self.on_open_settings())
        hbar.pack_end(settings_btn)

        new_btn = ui.icon_button("document-new-symbolic", "New chat")
        new_btn.connect("clicked", self._on_new_chat)
        hbar.pack_end(new_btn)

        self.perm_pill = Gtk.Button(label="Full access")
        self.perm_pill.set_valign(Gtk.Align.CENTER)
        self.perm_pill.get_style_context().add_class("tchiko-pill")
        self.perm_pill.connect("clicked", lambda *_: self.on_open_settings())
        hbar.pack_end(self.perm_pill)

        self.set_titlebar(hbar)
        self._update_avatars()

    def _build_body(self) -> None:
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.get_style_context().add_class("tchiko-root")

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(160)
        self.stack.add_titled(self._build_chat_page(), "chat", "Chat")
        self.stack.add_titled(self._build_system_page(), "system", "System")
        self.stack.add_titled(self._build_activity_page(), "activity", "Activity")
        self.stack.connect("size-allocate", self._on_stack_allocate)

        root.pack_start(self.stack, True, True, 0)
        self.add(root)

    def _on_stack_allocate(self, _widget: Gtk.Widget, alloc: Gdk.Rectangle) -> None:
        """Keep chat content in a readable centred column however wide the window is."""
        margin = max(22, (alloc.width - 780) // 2)
        if margin == self._side_margin:
            return
        self._side_margin = margin

        def _apply() -> bool:
            for widget in (self.feed_box, self.composer_wrap, self.approval_bar):
                widget.set_margin_start(margin)
                widget.set_margin_end(margin)
            return False

        GLib.idle_add(_apply)

    # ── Chat page ────────────────────────────────────────────────────────────
    def _build_chat_page(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.chat_scroll = Gtk.ScrolledWindow()
        self.chat_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.chat_scroll.get_style_context().add_class("tchiko-scroll")
        self.feed_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=22)
        self.feed_box.set_margin_top(22)
        self.feed_box.set_margin_bottom(14)
        self.chat_scroll.add(self.feed_box)
        page.pack_start(self.chat_scroll, True, True, 0)
        self._show_welcome()

        # Approval banner (review mode only).
        self.approval_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.approval_bar.get_style_context().add_class("tchiko-banner")
        self.approval_bar.set_margin_bottom(10)
        warn = ui.icon("dialog-warning-symbolic", 18)
        warn.get_style_context().add_class("tchiko-warn-icon")
        self.approval_bar.pack_start(warn, False, False, 0)
        ap_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        ap_title = ui.label("Tchiko wants to run a command", "tchiko-row-title")
        self.approval_cmd_lbl = ui.label("", "tchiko-code-text")
        self.approval_cmd_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        ap_text.pack_start(ap_title, False, False, 0)
        ap_text.pack_start(self.approval_cmd_lbl, False, False, 0)
        self.approval_bar.pack_start(ap_text, True, True, 0)
        for text, css, handler in (
            ("Run", "tchiko-primary", self._on_approve_clicked),
            ("Always allow", "tchiko-btn", self._on_approve_all_clicked),
            ("Deny", "tchiko-btn", self._on_deny_clicked),
        ):
            btn = Gtk.Button(label=text)
            btn.set_valign(Gtk.Align.CENTER)
            btn.get_style_context().add_class(css)
            btn.connect("clicked", handler)
            self.approval_bar.pack_end(btn, False, False, 0)
        self.approval_bar.set_no_show_all(True)
        page.pack_start(self.approval_bar, False, False, 0)

        # Composer.
        self.composer_wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.composer_wrap.set_margin_bottom(12)

        self.composer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        self.composer.get_style_context().add_class("tchiko-composer")

        slash_btn = ui.icon_button("view-more-symbolic", "Quick commands")
        slash_btn.connect("clicked", self._on_slash_menu_clicked)
        self.composer.pack_start(slash_btn, False, False, 0)

        self.prompt_entry = Gtk.Entry()
        self.prompt_entry.set_has_frame(False)
        self.prompt_entry.get_style_context().add_class("tchiko-entry")
        self.prompt_entry.set_placeholder_text("Ask Tchiko to check, fix or set up anything on this machine")
        self.prompt_entry.connect("activate", self._on_send_clicked)
        self.prompt_entry.connect("changed", lambda *_: self._sync_send_state())
        self.prompt_entry.connect("focus-in-event", self._on_entry_focus, True)
        self.prompt_entry.connect("focus-out-event", self._on_entry_focus, False)
        self.composer.pack_start(self.prompt_entry, True, True, 0)

        mood_btn = ui.icon_button("face-smile-symbolic", "Make Tchiko do a trick")
        mood_btn.connect("clicked", self._on_mood_menu_clicked)
        self.composer.pack_start(mood_btn, False, False, 0)

        self.send_btn = Gtk.Button()
        self.send_btn.set_image(ui.icon("go-up-symbolic", 16))
        self.send_btn.set_always_show_image(True)
        self.send_btn.set_tooltip_text("Send (Enter)")
        self.send_btn.set_valign(Gtk.Align.CENTER)
        self.send_btn.set_margin_start(4)
        self.send_btn.get_style_context().add_class("tchiko-send")
        self.send_btn.connect("clicked", self._on_send_clicked)
        self.composer.pack_start(self.send_btn, False, False, 0)
        self.composer_wrap.pack_start(self.composer, False, False, 0)

        hints = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        hints.set_margin_start(6)
        hints.set_margin_end(6)
        hint_lbl = Gtk.Label(xalign=0.0)
        hint_lbl.set_markup(
            f"<span size='small' foreground='{ui.TEXT_MUTED}'>"
            f"<b>Enter</b> to send   ·   <b>$</b> runs a shell command   ·   <b>/help</b> lists commands</span>"
        )
        self.cwd_lbl = Gtk.Label(xalign=1.0)
        self.cwd_lbl.set_ellipsize(Pango.EllipsizeMode.START)
        self.cwd_lbl.set_tooltip_text("Tchiko's working directory (change it with: cd <path>)")
        hints.pack_start(hint_lbl, False, False, 0)
        hints.pack_end(self.cwd_lbl, True, True, 0)
        self.composer_wrap.pack_start(hints, False, False, 0)
        page.pack_start(self.composer_wrap, False, False, 0)

        self._sync_send_state()
        self._refresh_cwd()
        return page

    def _on_entry_focus(self, _w: Gtk.Widget, _e: Any, focused: bool) -> bool:
        ctx = self.composer.get_style_context()
        if focused:
            ctx.add_class("focused")
        else:
            ctx.remove_class("focused")
        return False

    def _sync_send_state(self) -> None:
        self.send_btn.set_sensitive(not self._busy and bool(self.prompt_entry.get_text().strip()))

    def _refresh_cwd(self) -> None:
        cwd = str(self.engine.memory.get("cwd", "~"))
        home = os.path.expanduser("~")
        shown = "~" + cwd[len(home):] if cwd.startswith(home) else cwd
        self.cwd_lbl.set_markup(
            f"<span size='small' font_family='{ui.PANGO_MONO}' foreground='{ui.TEXT_MUTED}'>{html.escape(shown)}</span>"
        )

    def _tile(self, icon_name: str, title: str, desc: str, prompt: str) -> Gtk.Button:
        btn = Gtk.Button()
        btn.get_style_context().add_class("tchiko-tile")
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        chip = Gtk.Box()
        chip.set_valign(Gtk.Align.CENTER)
        chip.get_style_context().add_class("tchiko-tile-icon")
        chip.add(ui.icon(icon_name, 16))
        row.pack_start(chip, False, False, 0)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        text.set_valign(Gtk.Align.CENTER)
        t_lbl = ui.label(title, "tchiko-row-title")
        d_lbl = Gtk.Label(xalign=0.0)
        d_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        d_lbl.set_markup(f"<span size='small' foreground='{ui.TEXT_SECONDARY}'>{html.escape(desc)}</span>")
        text.pack_start(t_lbl, False, False, 0)
        text.pack_start(d_lbl, False, False, 0)
        row.pack_start(text, True, True, 0)
        btn.add(row)
        btn.connect("clicked", lambda *_: self.submit_external_command(prompt))
        return btn

    def _show_welcome(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(34)

        self._welcome_avatar = Gtk.Image()
        self._welcome_avatar.set_halign(Gtk.Align.CENTER)
        box.pack_start(self._welcome_avatar, False, False, 0)

        title = ui.label("What needs doing?", "display", xalign=0.5)
        title.set_margin_top(6)
        sub = Gtk.Label(xalign=0.5)
        sub.set_justify(Gtk.Justification.CENTER)
        sub.set_line_wrap(True)
        sub.set_markup(
            f"<span foreground='{ui.TEXT_SECONDARY}'>I'm Tchiko. Tell me in plain words and I'll do it on this "
            f"machine — install, configure, diagnose, fix.</span>"
        )
        box.pack_start(title, False, False, 0)
        box.pack_start(sub, False, False, 0)

        grid = Gtk.Grid(column_spacing=10, row_spacing=10, column_homogeneous=True)
        grid.set_margin_top(22)
        for idx, (icon_name, s_title, s_desc, s_prompt) in enumerate(STARTERS):
            grid.attach(self._tile(icon_name, s_title, s_desc, s_prompt), idx % 2, idx // 2, 1, 1)
        box.pack_start(grid, False, False, 0)

        self._welcome = box
        self.feed_box.pack_start(box, False, False, 0)
        box.show_all()
        self._update_avatars()

    def _hide_welcome(self) -> None:
        if self._welcome is not None:
            self.feed_box.remove(self._welcome)
            self._welcome = None
            self._welcome_avatar = None

    # ── System page ──────────────────────────────────────────────────────────
    def _build_system_page(self) -> Gtk.Widget:
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.get_style_context().add_class("tchiko-scroll")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        for setter in (box.set_margin_start, box.set_margin_end):
            setter(28)
        box.set_margin_top(24)
        box.set_margin_bottom(24)

        self.host_title_lbl = ui.label("", "display")
        self.host_sub_lbl = ui.label("", "dim")
        box.pack_start(self.host_title_lbl, False, False, 0)
        box.pack_start(self.host_sub_lbl, False, False, 0)

        gauges = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, homogeneous=True)
        gauges.set_margin_top(8)
        self._gauges: Dict[str, Tuple[ui.RingGauge, Gtk.Label, Gtk.Label]] = {}
        for key, caption in (("cpu", "CPU LOAD"), ("ram", "MEMORY"), ("disk", "DISK  ·  HOME")):
            card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
            card.get_style_context().add_class("tchiko-card")
            card.get_style_context().add_class("tchiko-card-pad")
            ring = ui.RingGauge(74)
            card.pack_start(ring, False, False, 0)
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            text.set_valign(Gtk.Align.CENTER)
            value_lbl = ui.label("—", "title")
            detail_lbl = ui.label("", "dim")
            text.pack_start(ui.label(caption, "caption"), False, False, 0)
            text.pack_start(value_lbl, False, False, 0)
            text.pack_start(detail_lbl, False, False, 0)
            card.pack_start(text, True, True, 0)
            gauges.pack_start(card, True, True, 0)
            self._gauges[key] = (ring, value_lbl, detail_lbl)
        box.pack_start(gauges, False, False, 0)

        access = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        access.get_style_context().add_class("tchiko-card")
        access.get_style_context().add_class("tchiko-card-pad")
        chip = Gtk.Box()
        chip.set_valign(Gtk.Align.CENTER)
        chip.get_style_context().add_class("tchiko-tile-icon")
        chip.add(ui.icon("security-high-symbolic", 18))
        access.pack_start(chip, False, False, 0)
        a_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        a_text.pack_start(ui.label("Full system access", "tchiko-row-title"), False, False, 0)
        a_text.pack_start(
            ui.label("Run commands, edit files and manage services without asking each time.", "dim", wrap=True),
            False, False, 0,
        )
        access.pack_start(a_text, True, True, 0)
        self.access_switch = Gtk.Switch()
        self.access_switch.set_valign(Gtk.Align.CENTER)
        self.access_switch.connect("notify::active", self._on_access_switch_toggled)
        access.pack_end(self.access_switch, False, False, 0)
        box.pack_start(access, False, False, 0)

        qa_caption = ui.label("QUICK ACTIONS", "caption")
        qa_caption.set_margin_top(10)
        box.pack_start(qa_caption, False, False, 0)
        grid = Gtk.Grid(column_spacing=10, row_spacing=10, column_homogeneous=True)
        for idx, (icon_name, a_title, a_desc, a_prompt) in enumerate(QUICK_ACTIONS):
            grid.attach(self._tile(icon_name, a_title, a_desc, a_prompt), idx % 3, idx // 3, 1, 1)
        box.pack_start(grid, False, False, 0)

        scroll.add(box)
        return scroll

    def _refresh_telemetry(self) -> bool:
        t = self.toolkit.get_system_telemetry()
        self.host_title_lbl.set_text(str(t["hostname"]))
        self.host_sub_lbl.set_text(f"{t['distro']}   ·   up {t['uptime_str']}")

        cores = max(1, int(t["cpu_cores"]))
        values = {
            "cpu": (float(t["cpu_load_1m"]) / cores, f"{t['cpu_load_1m']}", f"1-min load · {cores} cores"),
            "ram": (float(t["ram_percent"]) / 100.0, f"{t['ram_used_gb']} GB", f"of {t['ram_total_gb']} GB"),
            "disk": (float(t["disk_percent"]) / 100.0, f"{t['disk_used_gb']} GB", f"of {t['disk_total_gb']} GB"),
        }
        for key, (fraction, value, detail) in values.items():
            ring, value_lbl, detail_lbl = self._gauges[key]
            ring.set_fraction(fraction)
            value_lbl.set_text(value)
            detail_lbl.set_text(detail)
        return True

    # ── Activity page ────────────────────────────────────────────────────────
    def _build_activity_page(self) -> Gtk.Widget:
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for setter in (vbox.set_margin_start, vbox.set_margin_end):
            setter(28)
        vbox.set_margin_top(24)
        vbox.set_margin_bottom(24)

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        titles.pack_start(ui.label("Activity", "display"), False, False, 0)
        titles.pack_start(ui.label("Every step the agent takes, as it happens.", "dim"), False, False, 0)
        head.pack_start(titles, True, True, 0)
        clear_btn = Gtk.Button(label="Clear")
        clear_btn.set_valign(Gtk.Align.END)
        clear_btn.get_style_context().add_class("tchiko-btn")
        clear_btn.connect("clicked", lambda *_: [self.timeline.remove(r) for r in self.timeline.get_children()])
        head.pack_end(clear_btn, False, False, 0)
        vbox.pack_start(head, False, False, 0)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        card.get_style_context().add_class("tchiko-card")
        self.timeline_scroll = Gtk.ScrolledWindow()
        self.timeline_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.timeline_scroll.get_style_context().add_class("tchiko-scroll")
        self.timeline = Gtk.ListBox()
        self.timeline.set_selection_mode(Gtk.SelectionMode.NONE)
        self.timeline.get_style_context().add_class("tchiko-timeline")
        empty = ui.label("Nothing yet. Ask Tchiko something and its steps will show up here.", "muted", xalign=0.5)
        empty.set_margin_top(48)
        empty.show()
        self.timeline.set_placeholder(empty)
        self.timeline_scroll.add(self.timeline)
        card.pack_start(self.timeline_scroll, True, True, 0)
        vbox.pack_start(card, True, True, 0)
        return vbox

    def _append_activity(self, kind: str, text: str) -> None:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        ts = Gtk.Label(xalign=0.0)
        ts.set_valign(Gtk.Align.START)
        ts.set_markup(
            f"<span font_family='{ui.PANGO_MONO}' size='small' foreground='{ui.TEXT_MUTED}'>"
            f"{datetime.now().strftime('%H:%M:%S')}</span>"
        )
        badge = Gtk.Label(label="TOOL" if kind == "tool" else "THINK")
        badge.set_valign(Gtk.Align.START)
        badge.set_size_request(46, -1)
        badge.get_style_context().add_class("tchiko-badge")
        if kind == "tool":
            badge.get_style_context().add_class("tool")
        body = ui.label(text, "tchiko-code-text" if kind == "tool" else "dim", wrap=True, selectable=True)
        row.pack_start(ts, False, False, 0)
        row.pack_start(badge, False, False, 0)
        row.pack_start(body, True, True, 0)
        self.timeline.add(row)
        row.show_all()
        rows = self.timeline.get_children()
        if len(rows) > MAX_TIMELINE_ROWS:
            self.timeline.remove(rows[0])

        def _scroll() -> bool:
            adj = self.timeline_scroll.get_vadjustment()
            adj.set_value(max(0.0, adj.get_upper() - adj.get_page_size()))
            return False

        GLib.idle_add(_scroll)

    # ── Avatars, status, config ──────────────────────────────────────────────
    def _tick_avatars(self) -> bool:
        if self.get_visible():
            self._mini_renderer.step(0.08)
            self._update_avatars()
        return True

    def _update_avatars(self) -> None:
        theme = self.config.data.get("ghost_widget", {}).get("theme", "phantom_cyan")
        scale = max(1, self.get_scale_factor())
        targets = [(getattr(self, "mini_avatar_img", None), 34)]
        if self.stack.get_visible_child_name() == "chat":
            targets.append((self._welcome_avatar, 120))
        for image, size in targets:
            if image is not None:
                px = size * scale
                ui.set_hidpi_pixbuf(
                    image, self._mini_renderer.render_to_pixbuf(px, px, theme_name=theme, opacity=1.0), size
                )

    def _set_status(self, state: str, text: str) -> None:
        color = {
            "idle": ui.SUCCESS, "happy": ui.SUCCESS,
            "thinking": ui.ACCENT_TEXT, "executing": ui.ACCENT_TEXT,
            "alert": ui.WARNING,
        }.get(state, ui.TEXT_SECONDARY)
        self.status_lbl.set_markup(
            f"<span size='small'><span foreground='{color}'>●</span> "
            f"<span foreground='{ui.TEXT_SECONDARY}'>{html.escape(text)}</span></span>"
        )

    def _on_config_changed(self, _data: Dict[str, Any]) -> None:
        all_ok = self.config.is_all_permissions_approved()
        ctx = self.perm_pill.get_style_context()
        ctx.remove_class("ok")
        ctx.remove_class("review")
        ctx.add_class("ok" if all_ok else "review")
        self.perm_pill.set_label("●  Full access" if all_ok else "●  Review mode")
        self.perm_pill.set_tooltip_text(
            "Tchiko acts without asking. Click to change."
            if all_ok else "Tchiko asks before running commands. Click to change."
        )
        if self.access_switch.get_active() != all_ok:
            self.access_switch.set_active(all_ok)

    def _on_access_switch_toggled(self, switch: Gtk.Switch, _gparam: Any) -> None:
        if switch.get_active() != self.config.is_all_permissions_approved():
            self.config.set_all_permissions(switch.get_active())

    # ── Menus ────────────────────────────────────────────────────────────────
    def _on_slash_menu_clicked(self, widget: Gtk.Widget) -> None:
        menu = Gtk.Menu()
        for text, cmd in SLASH_MENU:
            item = Gtk.MenuItem(label=text)
            item.connect("activate", lambda _w, c=cmd: self.submit_external_command(c))
            menu.append(item)
        menu.show_all()
        menu.popup_at_widget(widget, Gdk.Gravity.NORTH_WEST, Gdk.Gravity.SOUTH_WEST, None)

    def _on_mood_menu_clicked(self, widget: Gtk.Widget) -> None:
        menu = Gtk.Menu()
        for mood_key, mood_label in ui.MOOD_NAMES:
            item = Gtk.MenuItem(label=mood_label)
            item.connect("activate", lambda _w, mk=mood_key: self._trigger_emotion(mk))
            menu.append(item)
        menu.show_all()
        menu.popup_at_widget(widget, Gdk.Gravity.NORTH_EAST, Gdk.Gravity.SOUTH_EAST, None)

    def _trigger_emotion(self, emotion: str) -> None:
        self._mini_renderer.set_emotion(emotion, duration=6.0)
        self.on_ghost_state(emotion, None)

    # ── Public API used by the floating companion ────────────────────────────
    def set_bubble_listener(self, callback: Callable[[str], None]) -> None:
        """Register the callback that mirrors replies into the companion's speech bubble."""
        self._bubble_listener = callback

    def submit_inline_prompt(self, prompt: str) -> None:
        """Run a prompt typed into the companion's quick-input bar."""
        cmd = prompt.strip()
        if cmd:
            self._dispatch_prompt(cmd)

    def submit_external_command(self, cmd: str) -> None:
        """Bring the chat forward and run a command."""
        self.show_all()
        self.present()
        self.stack.set_visible_child_name("chat")
        self._dispatch_prompt(cmd)

    def _on_new_chat(self, *_args: Any) -> None:
        if self._busy:
            return
        for child in list(self.feed_box.get_children()):
            self.feed_box.remove(child)
        self._welcome = None
        self.engine.reset_conversation()
        self._show_welcome()
        self.stack.set_visible_child_name("chat")
        self.prompt_entry.grab_focus()

    # ── Sending & streaming ──────────────────────────────────────────────────
    def _on_send_clicked(self, *_args: Any) -> None:
        prompt = self.prompt_entry.get_text().strip()
        if not prompt or self._busy:
            return
        self.prompt_entry.set_text("")
        self._dispatch_prompt(prompt)

    def _mirror_to_bubble(self, text: str) -> None:
        if self._bubble_listener is not None:
            self._bubble_listener(text)

    def _dispatch_prompt(self, prompt: str) -> None:
        if self._busy:
            self._mirror_to_bubble("Still working on the last request — I'll take this one right after.")
            self.prompt_entry.set_text(prompt)
            return
        self._busy = True
        self._sync_send_state()
        self._hide_welcome()

        ts = datetime.now().strftime("%H:%M")
        self._append_user_bubble(prompt)
        self._create_reply(ts)
        self._scroll_feed_to_bottom(force=True)
        self._set_status("thinking", "Thinking…")

        self.engine.process_prompt_async(
            prompt=prompt,
            on_thought=lambda th: GLib.idle_add(self._on_thought_update, th),
            on_tool_call=lambda name, args: GLib.idle_add(self._on_tool_update, name, args),
            on_token=lambda tok: GLib.idle_add(self._append_token, tok),
            on_complete=lambda _full: GLib.idle_add(self._on_response_complete),
            on_state_change=lambda st: GLib.idle_add(self._on_engine_state, st),
            on_approval_needed=lambda cmd, yes, no: GLib.idle_add(self._prompt_inline_approval, cmd, yes, no),
        )

    def _append_user_bubble(self, text: str) -> None:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        bubble = Gtk.Box()
        bubble.get_style_context().add_class("tchiko-user-bubble")
        bubble.set_margin_start(110)
        msg = ui.label(text, wrap=True, selectable=True)
        msg.set_max_width_chars(64)
        bubble.add(msg)
        row.pack_end(bubble, False, True, 0)
        self.feed_box.pack_start(row, False, False, 0)
        row.show_all()

    def _create_reply(self, ts: str) -> None:
        reply = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=9)

        head = Gtk.Label(xalign=0.0)
        head.set_markup(
            f"<span foreground='{ui.ACCENT}'>●</span>  <b>Tchiko</b>"
            f"<span size='small' foreground='{ui.TEXT_MUTED}'>   {ts}</span>"
        )
        reply.pack_start(head, False, False, 0)

        chip_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        chip = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        chip.get_style_context().add_class("tchiko-activity-chip")
        spinner = Gtk.Spinner()
        spinner.start()
        chip_lbl = Gtk.Label(label="Thinking…", xalign=0.0)
        chip_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        chip_lbl.set_max_width_chars(70)
        chip.pack_start(spinner, False, False, 0)
        chip.pack_start(chip_lbl, False, False, 0)
        chip_row.pack_start(chip, False, False, 0)
        reply.pack_start(chip_row, False, False, 0)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        stream_lbl = ui.label("", wrap=True, selectable=True)
        stream_lbl.set_no_show_all(True)
        content.pack_start(stream_lbl, False, False, 0)
        reply.pack_start(content, False, False, 0)

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        meta = ui.label("", "muted")
        copy_btn = ui.icon_button("edit-copy-symbolic", "Copy reply", pixel_size=14)
        footer.pack_start(copy_btn, False, False, 0)
        footer.pack_start(meta, False, False, 0)
        footer.set_no_show_all(True)
        reply.pack_start(footer, False, False, 0)
        copy_btn.connect("clicked", lambda b: self._copy_to_clipboard(getattr(content, "_raw_text", ""), b))

        self._stream_tokens = []
        self._stream_label = stream_lbl
        self._stream_content = content
        self._stream_chip = chip_row
        self._stream_chip_label = chip_lbl
        self._stream_footer = footer
        self._stream_meta = meta
        self._stream_started = time.monotonic()
        self._stream_tools = 0

        self.feed_box.pack_start(reply, False, False, 0)
        reply.show_all()

    def _set_chip(self, text: str) -> None:
        if self._stream_chip_label is not None:
            self._stream_chip_label.set_text(" ".join(text.split())[:160])

    def _on_thought_update(self, thought_text: str) -> bool:
        self._append_activity("think", thought_text)
        self._set_chip(thought_text)
        if not self._stream_tokens:
            self._mirror_to_bubble(f"*{thought_text}*")
        return False

    def _on_tool_update(self, name: str, args: str) -> bool:
        self._stream_tools += 1
        self._append_activity("tool", f"{name}  {args}")
        self._set_chip(f"Running {name}…")
        self._set_status("executing", f"Running {name}…")
        if not self._stream_tokens:
            self._mirror_to_bubble(f"*Running `{name}`…*")
        return False

    def _on_engine_state(self, state: str) -> bool:
        if self._busy and state in ("idle", "happy"):
            # Final states are applied by _on_response_complete once the reply is rendered.
            self.on_ghost_state(state, None)
            return False
        texts = {"idle": "Ready", "happy": "Ready", "thinking": "Thinking…", "executing": "Working…", "alert": "Needs attention"}
        self._mini_renderer.set_emotion(state, duration=4.0)
        self._set_status(state, texts.get(state, state.capitalize()))
        self.on_ghost_state(state, None)
        return False

    def _append_token(self, token: str) -> bool:
        self._stream_tokens.append(token)
        if self._stream_flush_id is None:
            # Coalesce bursts of tokens into one repaint.
            self._stream_flush_id = GLib.timeout_add(45, self._flush_stream)
        return False

    def _flush_stream(self) -> bool:
        self._stream_flush_id = None
        current = "".join(self._stream_tokens)
        if self._stream_label is not None and current.strip():
            self._stream_label.set_markup(ui.streaming_markup(current))
            self._stream_label.show()
            self._scroll_feed_to_bottom()
        self._mirror_to_bubble(current)
        return False

    def _on_response_complete(self) -> bool:
        if self._stream_flush_id is not None:
            GLib.source_remove(self._stream_flush_id)
            self._stream_flush_id = None
        full_raw = "".join(self._stream_tokens).strip()
        if self._stream_content is not None:
            self._stream_content._raw_text = full_raw
            self._render_reply(self._stream_content, full_raw or "*(no reply)*")
        if self._stream_chip is not None:
            # Destroy rather than hide: the window is re-shown with show_all() on every toggle.
            self._stream_chip.destroy()
        if self._stream_footer is not None and self._stream_meta is not None:
            elapsed = time.monotonic() - self._stream_started
            took = f"{elapsed:.1f}s" if elapsed < 60 else f"{int(elapsed // 60)}m {int(elapsed % 60)}s"
            tools = self._stream_tools
            parts = ([f"{tools} tool call{'s' if tools != 1 else ''}"] if tools else []) + [took]
            self._stream_meta.set_markup(f"<span size='small'>{'  ·  '.join(parts)}</span>")
            self._stream_footer.set_no_show_all(False)
            self._stream_footer.show_all()
        self._stream_label = None
        self._stream_chip = None
        self._stream_chip_label = None

        if full_raw:
            self._mirror_to_bubble(full_raw)
        self._busy = False
        self._sync_send_state()
        self._refresh_cwd()
        self._mini_renderer.set_emotion("happy", duration=4.0)
        self._set_status("idle", "Ready")
        self._scroll_feed_to_bottom()
        return False

    def _render_reply(self, container: Gtk.Box, markdown_text: str) -> None:
        """Replace the streaming label with rendered prose and code cards."""
        for child in list(container.get_children()):
            container.remove(child)

        for kind, content, lang in ui.split_markdown_blocks(markdown_text):
            if kind == "code":
                card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                card.get_style_context().add_class("tchiko-code-card")

                head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                head.get_style_context().add_class("tchiko-code-head")
                shown_lang = "output" if lang in ("", "text") else lang
                head.pack_start(ui.label(shown_lang.upper(), "caption"), True, True, 0)
                c_btn = ui.icon_button("edit-copy-symbolic", "Copy", pixel_size=14)
                c_btn.connect("clicked", lambda b, t=content: self._copy_to_clipboard(t, b))
                head.pack_end(c_btn, False, False, 0)
                card.pack_start(head, False, False, 0)

                body = Gtk.Box()
                body.get_style_context().add_class("tchiko-code-body")
                code_lbl = ui.label(content, "tchiko-code-text", wrap=True, selectable=True)
                body.pack_start(code_lbl, True, True, 0)
                card.pack_start(body, False, False, 0)
                container.pack_start(card, False, False, 0)
            else:
                lbl = ui.label("", wrap=True, selectable=True)
                lbl.set_markup(ui.markdown_to_pango(content))
                container.pack_start(lbl, False, False, 0)
        container.show_all()

    @staticmethod
    def _copy_to_clipboard(text: str, btn: Gtk.Button) -> None:
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(text, -1)
        ui.flash_button_icon(btn)

    # ── Approval flow ────────────────────────────────────────────────────────
    def _prompt_inline_approval(
        self, cmd: str, approve_cb: Callable[[], None], deny_cb: Callable[[], None]
    ) -> bool:
        self._approve_cb = approve_cb
        self._deny_cb = deny_cb
        self.approval_cmd_lbl.set_text(cmd)
        self.approval_cmd_lbl.set_tooltip_text(cmd)
        self._set_chip("Waiting for your approval…")
        self._set_status("alert", "Waiting for approval")
        self.approval_bar.set_no_show_all(False)
        self.approval_bar.show_all()
        self.approval_bar.set_no_show_all(True)
        return False

    def _resolve_approval(self, approved: bool) -> None:
        self.approval_bar.hide()
        cb = self._approve_cb if approved else self._deny_cb
        self._approve_cb = None
        self._deny_cb = None
        if cb:
            cb()

    def _on_approve_clicked(self, *_args: Any) -> None:
        self._resolve_approval(True)

    def _on_approve_all_clicked(self, *_args: Any) -> None:
        self.config.set_all_permissions(True)
        self._resolve_approval(True)

    def _on_deny_clicked(self, *_args: Any) -> None:
        self._resolve_approval(False)

    def _scroll_feed_to_bottom(self, force: bool = False) -> None:
        """Follow new content, unless the user has scrolled up to read something."""
        adj = self.chat_scroll.get_vadjustment()
        if adj is None:
            return
        near_bottom = adj.get_upper() - adj.get_page_size() - adj.get_value() < 90
        if not (force or near_bottom):
            return

        def _do_scroll() -> bool:
            adj.set_value(max(0.0, adj.get_upper() - adj.get_page_size()))
            return False

        GLib.idle_add(_do_scroll)
