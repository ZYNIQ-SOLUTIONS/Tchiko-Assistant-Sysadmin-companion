"""World-Class Antigravity 2.0 Chat & System Studio UI (`tchiko/assistant_window.py`).

Features:
- Custom Modern HeaderBar with Live Animated Ghost Mini-Avatar, Status Pill,
  Segmented View Switcher (💬 Chat | ⚡ System Studio | 🧠 Activity), and
  one-click Permission & Settings controls.
- Card-Based Chat Feed (instead of plain text dumps):
  - Interactive Welcome Hero Card with a 2x2 grid of 1-click Suggestion Cards
  - Right-aligned User Message Bubbles with clean typography
  - Left-aligned Tchiko Response Cards with formatted Markdown headings, bold
    bullet points, distinct Terminal/Code Output Cards, and 1-click Clipboard Copy (`📋 Copy`)
- Interactive Bottom Composer with Slash Command Menu (`/`), Ghost Mood Picker (`🎭`),
  and instant streaming indicator.
- Visual System Studio Tab with live graphical CPU/RAM/Disk progress meters and
  1-click Ubuntu diagnostic & automation cards.
"""

from __future__ import annotations

from datetime import datetime
import html
import re
from typing import Any, Callable, Dict, List, Optional

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango

from .agent_engine import TchikoAgentEngine
from .config_manager import ConfigManager
from .svg_ghost_renderer import SvgGhostRenderer
from .system_tools import LinuxSystemToolkit


WORLDCLASS_CSS = b"""
window, .tchiko-root {
    background-color: #0b0f17;
    color: #f0f6fc;
    font-family: "Inter", "Ubuntu", "Cantarell", sans-serif;
}

headerbar.tchiko-titlebar {
    background-image: linear-gradient(to right, #0f1623, #131c2e);
    border-bottom: 1px solid #1f2a3d;
    padding: 6px 12px;
    min-height: 52px;
}

.tchiko-nav-btn {
    background-image: none;
    background-color: transparent;
    color: #8b949e;
    border: 1px solid transparent;
    border-radius: 9px;
    padding: 6px 14px;
    font-weight: 600;
}
.tchiko-nav-btn:hover {
    background-color: #161f30;
    color: #f0f6fc;
}
.tchiko-nav-btn-active {
    background-image: linear-gradient(135deg, #1d4ed8, #3b82f6);
    color: #ffffff;
    border: 1px solid #60a5fa;
    border-radius: 9px;
    padding: 6px 14px;
    font-weight: 700;
}

.tchiko-perm-on {
    background-image: none;
    background-color: rgba(16, 185, 129, 0.14);
    color: #34d399;
    border: 1px solid rgba(52, 211, 153, 0.45);
    border-radius: 20px;
    padding: 5px 12px;
    font-weight: 600;
}
.tchiko-perm-on:hover {
    background-color: rgba(16, 185, 129, 0.25);
}

.tchiko-perm-review {
    background-image: none;
    background-color: rgba(245, 158, 11, 0.15);
    color: #fbbf24;
    border: 1px solid rgba(251, 191, 36, 0.45);
    border-radius: 20px;
    padding: 5px 12px;
    font-weight: 600;
}

.tchiko-hero-card {
    background-image: linear-gradient(145deg, #111827, #161f33);
    border: 1px solid #26344d;
    border-radius: 16px;
    padding: 18px;
}

.tchiko-suggest-btn {
    background-image: none;
    background-color: #131b2c;
    border: 1px solid #23304a;
    border-radius: 12px;
    padding: 12px 14px;
    color: #e2e8f0;
}
.tchiko-suggest-btn:hover {
    background-color: #1b2740;
    border-color: #38bdf8;
}

.tchiko-user-bubble {
    background-image: linear-gradient(135deg, #1e3a8a, #1d4ed8);
    border: 1px solid #3b82f6;
    border-radius: 16px 16px 4px 16px;
    padding: 12px 16px;
    color: #ffffff;
}

.tchiko-bot-card {
    background-color: #121826;
    border: 1px solid #222e45;
    border-radius: 16px 16px 16px 4px;
    padding: 14px 16px;
    color: #e6edf3;
}

.tchiko-code-card {
    background-color: #070a0f;
    border: 1px solid #1e293b;
    border-radius: 10px;
    padding: 10px 12px;
}

.tchiko-code-text {
    font-family: "JetBrains Mono", "Ubuntu Mono", monospace;
    font-size: 9.8pt;
    color: #a5f3fc;
}

.tchiko-copy-btn {
    background-image: none;
    background-color: #1b2436;
    color: #94a3b8;
    border: 1px solid #2d3b55;
    border-radius: 7px;
    padding: 3px 9px;
    font-size: 8.5pt;
}
.tchiko-copy-btn:hover {
    background-color: #26344d;
    color: #f8fafc;
    border-color: #38bdf8;
}

.tchiko-composer-bar {
    background-color: #101726;
    border-top: 1px solid #1f2a3d;
    padding: 12px 16px;
}

entry.tchiko-prompt-entry {
    background-color: #0b0f17;
    color: #f8fafc;
    border: 1px solid #283652;
    border-radius: 12px;
    padding: 10px 14px;
    font-size: 10.5pt;
}
entry.tchiko-prompt-entry:focus {
    border-color: #38bdf8;
}

.tchiko-send-btn {
    background-image: linear-gradient(135deg, #2563eb, #7c3aed);
    color: #ffffff;
    border: none;
    border-radius: 12px;
    padding: 8px 18px;
    font-weight: 700;
}
.tchiko-send-btn:hover {
    background-image: linear-gradient(135deg, #3b82f6, #8b5cf6);
}

.tchiko-icon-btn {
    background-image: none;
    background-color: #161f30;
    color: #cbd5e1;
    border: 1px solid #26344d;
    border-radius: 10px;
    padding: 6px 11px;
}
.tchiko-icon-btn:hover {
    background-color: #1f2c44;
    border-color: #38bdf8;
    color: #ffffff;
}

.tchiko-studio-card {
    background-color: #121826;
    border: 1px solid #222e45;
    border-radius: 14px;
    padding: 16px;
}

.tchiko-approve-banner {
    background-color: #291d0a;
    border: 1px solid #f59e0b;
    border-radius: 12px;
    padding: 10px 14px;
}

progressbar trough {
    background-color: #0b0f17;
    border-radius: 6px;
    min-height: 10px;
}
progressbar progress {
    background-image: linear-gradient(to right, #38bdf8, #818cf8);
    border-radius: 6px;
    min-height: 10px;
}
"""


class TchikoAssistantWindow(Gtk.Window):
    """World-Class Antigravity 2.0 Chat & System Studio Window."""

    def __init__(
        self,
        config: ConfigManager,
        toolkit: LinuxSystemToolkit,
        engine: TchikoAgentEngine,
        on_open_settings: Callable[[], None],
        on_ghost_state: Callable[[str, Optional[str]], None],
    ) -> None:
        super().__init__(title="Tchiko Assistant")
        self.config = config
        self.toolkit = toolkit
        self.engine = engine
        self.on_open_settings = on_open_settings
        self.on_ghost_state = on_ghost_state

        self._mini_renderer = SvgGhostRenderer()
        self._approve_cb: Optional[Callable[[], None]] = None
        self._deny_cb: Optional[Callable[[], None]] = None
        self._active_stream_label: Optional[Gtk.Label] = None
        self._active_stream_card: Optional[Gtk.Box] = None
        self._active_stream_text: List[str] = []
        self._nav_buttons: Dict[str, Gtk.Button] = {}

        self.set_default_size(860, 650)
        self.set_keep_above(True)
        self.connect("delete-event", self._on_delete_event)

        self._apply_css()
        self._build_headerbar()
        self._build_body()

        self.config.subscribe(self._on_config_changed)
        self._on_config_changed(self.config.data)

        # Start timers for mini-avatar and live telemetry
        GLib.timeout_add(80, self._tick_mini_avatar)
        GLib.timeout_add_seconds(3, self._refresh_telemetry)
        self._refresh_telemetry()

    def _apply_css(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(WORLDCLASS_CSS)
        screen = Gdk.Screen.get_default()
        if screen is not None:
            Gtk.StyleContext.add_provider_for_screen(
                screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

    def _on_delete_event(self, _widget: Gtk.Widget, _event: Any) -> bool:
        self.hide()
        return True

    def _build_headerbar(self) -> None:
        hbar = Gtk.HeaderBar()
        hbar.set_show_close_button(True)
        hbar.get_style_context().add_class("tchiko-titlebar")

        # Left: Animated Mini-Ghost Avatar + Title + Live Mood Subtitle
        brand_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.mini_avatar_img = Gtk.Image()
        self._update_mini_avatar_pixbuf()
        brand_box.pack_start(self.mini_avatar_img, False, False, 0)

        title_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        title_lbl = Gtk.Label(xalign=0.0)
        title_lbl.set_markup(
            "<span weight='bold' size='medium' foreground='#f8fafc'>Tchiko Assistant</span>"
        )
        self.status_sub_lbl = Gtk.Label(xalign=0.0)
        self.status_sub_lbl.set_markup(
            "<span size='x-small' foreground='#38bdf8'>● Ready • Antigravity SDK</span>"
        )
        title_vbox.pack_start(title_lbl, False, False, 0)
        title_vbox.pack_start(self.status_sub_lbl, False, False, 0)
        brand_box.pack_start(title_vbox, False, False, 0)
        hbar.pack_start(brand_box)

        # Center: Segmented View Switcher Tabs
        nav_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for tab_id, tab_label in (
            ("chat", "💬 Chat"),
            ("studio", "⚡ System Studio"),
            ("activity", "🧠 Activity"),
        ):
            btn = Gtk.Button(label=tab_label)
            btn.connect("clicked", lambda _w, tid=tab_id: self._switch_tab(tid))
            self._nav_buttons[tab_id] = btn
            nav_box.pack_start(btn, False, False, 0)
        hbar.set_custom_title(nav_box)

        # Right: Permission Pill + Settings Button
        settings_btn = Gtk.Button(label="⚙️")
        settings_btn.set_tooltip_text("Open Tchiko Settings & Permissions")
        settings_btn.get_style_context().add_class("tchiko-icon-btn")
        settings_btn.connect("clicked", lambda *_: self.on_open_settings())
        hbar.pack_end(settings_btn)

        self.perm_pill_btn = Gtk.Button(label="🟢 Full Access")
        self.perm_pill_btn.set_tooltip_text("Click to configure Linux System Permissions")
        self.perm_pill_btn.connect("clicked", lambda *_: self.on_open_settings())
        hbar.pack_end(self.perm_pill_btn)

        self.set_titlebar(hbar)

    def _build_body(self) -> None:
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.get_style_context().add_class("tchiko-root")

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(180)

        # Page 1: Chat View
        self.stack.add_named(self._build_chat_page(), "chat")
        # Page 2: System Studio View
        self.stack.add_named(self._build_studio_page(), "studio")
        # Page 3: Activity & Logs View
        self.stack.add_named(self._build_activity_page(), "activity")

        root.pack_start(self.stack, True, True, 0)
        self.add(root)
        self._switch_tab("chat")

    def _build_chat_page(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Scrollable Message Card Feed
        self.chat_scroll = Gtk.ScrolledWindow()
        self.chat_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self.feed_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.feed_box.set_margin_start(20)
        self.feed_box.set_margin_end(20)
        self.feed_box.set_margin_top(18)
        self.feed_box.set_margin_bottom(18)

        self.chat_scroll.add(self.feed_box)
        page.pack_start(self.chat_scroll, True, True, 0)

        # Add Welcome Hero Card with 2x2 Suggestion Grid
        self._add_welcome_hero_card()

        # Inline Manual Approval Banner (hidden unless review mode is active)
        self.approval_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.approval_bar.get_style_context().add_class("tchiko-approve-banner")
        self.approval_bar.set_margin_start(20)
        self.approval_bar.set_margin_end(20)
        self.approval_bar.set_margin_bottom(8)

        self.approval_lbl = Gtk.Label(label="🔒 Approval needed", xalign=0.0)
        self.approval_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        approve_yes_btn = Gtk.Button(label="✅ Run Command")
        approve_yes_btn.get_style_context().add_class("tchiko-send-btn")
        approve_yes_btn.connect("clicked", self._on_approve_clicked)

        approve_all_btn = Gtk.Button(label="🛡️ Always Allow All")
        approve_all_btn.get_style_context().add_class("tchiko-icon-btn")
        approve_all_btn.connect("clicked", self._on_approve_all_clicked)

        approve_no_btn = Gtk.Button(label="✖ Cancel")
        approve_no_btn.get_style_context().add_class("tchiko-icon-btn")
        approve_no_btn.connect("clicked", self._on_deny_clicked)

        self.approval_bar.pack_start(self.approval_lbl, True, True, 4)
        self.approval_bar.pack_end(approve_no_btn, False, False, 0)
        self.approval_bar.pack_end(approve_all_btn, False, False, 0)
        self.approval_bar.pack_end(approve_yes_btn, False, False, 0)
        self.approval_bar.set_no_show_all(True)
        self.approval_bar.hide()
        page.pack_start(self.approval_bar, False, False, 0)

        # Bottom Composer Bar
        composer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        composer.get_style_context().add_class("tchiko-composer-bar")

        # Slash Command Quick Menu Button
        slash_btn = Gtk.Button(label="⚡ /")
        slash_btn.set_tooltip_text("Quick Commands & Actions")
        slash_btn.get_style_context().add_class("tchiko-icon-btn")
        slash_btn.connect("clicked", self._on_slash_menu_clicked)
        composer.pack_start(slash_btn, False, False, 0)

        # Interactive Ghost Mood Picker Button
        mood_btn = Gtk.Button(label="🎭")
        mood_btn.set_tooltip_text("Trigger Ghost Emotion")
        mood_btn.get_style_context().add_class("tchiko-icon-btn")
        mood_btn.connect("clicked", self._on_mood_menu_clicked)
        composer.pack_start(mood_btn, False, False, 0)

        # Prompt Input Entry
        self.prompt_entry = Gtk.Entry()
        self.prompt_entry.get_style_context().add_class("tchiko-prompt-entry")
        self.prompt_entry.set_placeholder_text(
            "Ask Tchiko anything, or run a command (e.g. '$ ls -la', 'check disk space', '/sysinfo')..."
        )
        self.prompt_entry.connect("activate", self._on_send_clicked)
        composer.pack_start(self.prompt_entry, True, True, 0)

        # Clear Feed Button
        clear_btn = Gtk.Button(label="🧹")
        clear_btn.set_tooltip_text("Clear Conversation")
        clear_btn.get_style_context().add_class("tchiko-icon-btn")
        clear_btn.connect("clicked", self._on_clear_chat)
        composer.pack_end(clear_btn, False, False, 0)

        # Send Button
        send_btn = Gtk.Button(label="Send ➤")
        send_btn.get_style_context().add_class("tchiko-send-btn")
        send_btn.connect("clicked", self._on_send_clicked)
        composer.pack_end(send_btn, False, False, 0)

        page.pack_start(composer, False, False, 0)
        return page

    def _add_welcome_hero_card(self) -> None:
        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        hero.get_style_context().add_class("tchiko-hero-card")

        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        h_title = Gtk.Label(xalign=0.0)
        h_title.set_markup(
            "<span size='large' weight='bold' foreground='#f8fafc'>"
            "👋 Hi! I'm Tchiko, your Ubuntu Desktop Ghost Companion</span>"
        )
        h_sub = Gtk.Label(xalign=0.0)
        h_sub.set_line_wrap(True)
        h_sub.set_markup(
            "<span size='small' foreground='#94a3b8'>"
            "Powered by the Google Antigravity SDK. Pet me with your cursor, scroll on me to change my mood, "
            "or pick a quick action below to interact with your Linux system.</span>"
        )
        title_box.pack_start(h_title, False, False, 0)
        title_box.pack_start(h_sub, False, False, 0)
        top_row.pack_start(title_box, True, True, 0)
        hero.pack_start(top_row, False, False, 0)

        # 2x2 Grid of Interactive Starter Cards
        grid = Gtk.Grid(column_spacing=10, row_spacing=10, column_homogeneous=True)
        suggestions = [
            (
                "🔑  Create OpenSSH Server Key",
                "Generate an Ed25519 OpenSSH keypair & auto-copy to clipboard",
                "tchiko create an ssh key for my remote hetzner server in OpenSSH format",
            ),
            (
                "🩺  Run System Doctor (/doctor)",
                "5-point Ubuntu audit: CPU, RAM, Disk, Services & Ports",
                "/doctor",
            ),
            (
                "🧠  Agent Memory & Context (/memory)",
                "Inspect active working dir, saved notes & recent artifacts",
                "/memory",
            ),
            (
                "🌐  Network & Open Ports",
                "View active network interfaces and listening ports",
                "check listening ports",
            ),
        ]
        for idx, (stitle, sdesc, scmd) in enumerate(suggestions):
            btn = Gtk.Button()
            btn.get_style_context().add_class("tchiko-suggest-btn")
            b_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            l1 = Gtk.Label(xalign=0.0)
            l1.set_markup(f"<span weight='bold' size='small' foreground='#38bdf8'>{html.escape(stitle)}</span>")
            l2 = Gtk.Label(xalign=0.0)
            l2.set_markup(f"<span size='x-small' foreground='#94a3b8'>{html.escape(sdesc)}</span>")
            b_vbox.pack_start(l1, False, False, 0)
            b_vbox.pack_start(l2, False, False, 0)
            btn.add(b_vbox)
            btn.connect("clicked", lambda _w, c=scmd: self.submit_external_command(c))
            grid.attach(btn, idx % 2, idx // 2, 1, 1)

        hero.pack_start(grid, False, False, 0)
        self.feed_box.pack_start(hero, False, False, 0)
        hero.show_all()

    def _build_studio_page(self) -> Gtk.Widget:
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_margin_start(22)
        box.set_margin_end(22)
        box.set_margin_top(18)
        box.set_margin_bottom(18)

        # 1. Live Resource Telemetry Card with Graphical Progress Bars
        telem_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        telem_card.get_style_context().add_class("tchiko-studio-card")

        hdr_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        hdr_lbl = Gtk.Label(xalign=0.0)
        hdr_lbl.set_markup(
            "<span size='medium' weight='bold' foreground='#38bdf8'>📊 Live Ubuntu Resource Telemetry</span>"
        )
        self.studio_host_lbl = Gtk.Label(xalign=1.0)
        hdr_row.pack_start(hdr_lbl, True, True, 0)
        hdr_row.pack_end(self.studio_host_lbl, False, False, 0)
        telem_card.pack_start(hdr_row, False, False, 0)

        # CPU Bar
        self.cpu_val_lbl = Gtk.Label(xalign=0.0)
        self.cpu_bar = Gtk.ProgressBar()
        telem_card.pack_start(self.cpu_val_lbl, False, False, 0)
        telem_card.pack_start(self.cpu_bar, False, False, 0)

        # RAM Bar
        self.ram_val_lbl = Gtk.Label(xalign=0.0)
        self.ram_bar = Gtk.ProgressBar()
        telem_card.pack_start(self.ram_val_lbl, False, False, 0)
        telem_card.pack_start(self.ram_bar, False, False, 0)

        # Disk Bar
        self.disk_val_lbl = Gtk.Label(xalign=0.0)
        self.disk_bar = Gtk.ProgressBar()
        telem_card.pack_start(self.disk_val_lbl, False, False, 0)
        telem_card.pack_start(self.disk_bar, False, False, 0)

        box.pack_start(telem_card, False, False, 0)

        # 2. Master Permission Control Card
        perm_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        perm_card.get_style_context().add_class("tchiko-studio-card")
        p_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        p_title = Gtk.Label(xalign=0.0)
        p_title.set_markup(
            "<span weight='bold' foreground='#34d399'>🛡️ Full Linux System Permissions (Autonomous Mode)</span>"
        )
        p_desc = Gtk.Label(xalign=0.0)
        p_desc.set_markup(
            "<span size='small' foreground='#94a3b8'>"
            "Allow Tchiko to execute terminal commands, manage files, and control Ubuntu without prompts.</span>"
        )
        p_vbox.pack_start(p_title, False, False, 0)
        p_vbox.pack_start(p_desc, False, False, 0)

        self.studio_perm_switch = Gtk.Switch()
        self.studio_perm_switch.set_valign(Gtk.Align.CENTER)
        self.studio_perm_switch.connect("notify::active", self._on_studio_switch_toggled)

        perm_card.pack_start(p_vbox, True, True, 0)
        perm_card.pack_end(self.studio_perm_switch, False, False, 0)
        box.pack_start(perm_card, False, False, 0)

        # 3. One-Click Ubuntu System Toolkit Grid
        actions_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        actions_card.get_style_context().add_class("tchiko-studio-card")
        act_lbl = Gtk.Label(xalign=0.0)
        act_lbl.set_markup(
            "<span size='medium' weight='bold' foreground='#a855f7'>⚡ One-Click Ubuntu System Actions</span>"
        )
        actions_card.pack_start(act_lbl, False, False, 0)

        act_grid = Gtk.Grid(column_spacing=10, row_spacing=10, column_homogeneous=True)
        studio_actions = [
            ("🩺 Run System Doctor (/doctor)", "/doctor"),
            ("🧠 View Agent Memory (/memory)", "/memory"),
            ("🔑 Create Hetzner OpenSSH Key", "tchiko create an ssh key for my remote hetzner server in OpenSSH format"),
            ("🔌 Open Network Ports (ss)", "check listening ports"),
            ("🐳 Docker Containers", "check docker containers"),
            ("🔧 Check Installed Dev Tools", "check installed tools versions"),
        ]
        for idx, (alabel, acmd) in enumerate(studio_actions):
            btn = Gtk.Button(label=alabel)
            btn.get_style_context().add_class("tchiko-suggest-btn")
            btn.connect("clicked", lambda _w, c=acmd: self.submit_external_command(c))
            act_grid.attach(btn, idx % 2, idx // 2, 1, 1)

        actions_card.pack_start(act_grid, False, False, 0)
        box.pack_start(actions_card, False, False, 0)

        scroll.add(box)
        return scroll

    def _build_activity_page(self) -> Gtk.Widget:
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_start(20)
        vbox.set_margin_end(20)
        vbox.set_margin_top(16)
        vbox.set_margin_bottom(16)

        hdr = Gtk.Label(xalign=0.0)
        hdr.set_markup(
            "<span size='medium' weight='bold' foreground='#38bdf8'>"
            "🧠 Antigravity SDK — Live Thoughts &amp; Tool Execution Stream</span>"
        )
        vbox.pack_start(hdr, False, False, 0)

        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        frame.get_style_context().add_class("tchiko-code-card")
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        self.activity_view = Gtk.TextView()
        self.activity_view.set_editable(False)
        self.activity_view.set_cursor_visible(False)
        self.activity_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.activity_view.get_style_context().add_class("tchiko-code-text")
        self.activity_buffer = self.activity_view.get_buffer()
        scroll.add(self.activity_view)
        frame.pack_start(scroll, True, True, 0)
        vbox.pack_start(frame, True, True, 0)
        return vbox

    def _switch_tab(self, tab_id: str) -> None:
        self.stack.set_visible_child_name(tab_id)
        for tid, btn in self._nav_buttons.items():
            ctx = btn.get_style_context()
            ctx.remove_class("tchiko-nav-btn")
            ctx.remove_class("tchiko-nav-btn-active")
            ctx.add_class("tchiko-nav-btn-active" if tid == tab_id else "tchiko-nav-btn")

    def _tick_mini_avatar(self) -> bool:
        if self.get_visible():
            self._mini_renderer.step(0.08)
            self._update_mini_avatar_pixbuf()
        return True

    def _update_mini_avatar_pixbuf(self) -> None:
        theme = self.config.data.get("ghost_widget", {}).get("theme", "phantom_cyan")
        pb = self._mini_renderer.render_to_pixbuf(42, 42, theme_name=theme, opacity=1.0)
        self.mini_avatar_img.set_from_pixbuf(pb)

    def _on_config_changed(self, _data: Dict[str, Any]) -> None:
        all_ok = self.config.is_all_permissions_approved()
        ctx = self.perm_pill_btn.get_style_context()
        ctx.remove_class("tchiko-perm-on")
        ctx.remove_class("tchiko-perm-review")
        if all_ok:
            self.perm_pill_btn.set_label("🟢 Full Access")
            ctx.add_class("tchiko-perm-on")
        else:
            self.perm_pill_btn.set_label("🟡 Review Mode")
            ctx.add_class("tchiko-perm-review")

        if self.studio_perm_switch.get_active() != all_ok:
            self.studio_perm_switch.set_active(all_ok)

    def _on_studio_switch_toggled(self, switch: Gtk.Switch, _gparam: Any) -> None:
        if switch.get_active() != self.config.is_all_permissions_approved():
            self.config.set_all_permissions(switch.get_active())

    def _refresh_telemetry(self) -> bool:
        t = self.toolkit.get_system_telemetry()
        self.studio_host_lbl.set_markup(
            f"<span size='small' foreground='#94a3b8'>{html.escape(t['hostname'])} • {html.escape(t['distro'])} • Uptime {html.escape(t['uptime_str'])}</span>"
        )
        cpu_frac = min(1.0, float(t["cpu_load_1m"]) / max(1, int(t["cpu_cores"])))
        self.cpu_val_lbl.set_markup(
            f"<span size='small' weight='bold' foreground='#e2e8f0'>CPU Load (1m):</span> "
            f"<span size='small' foreground='#38bdf8'>{t['cpu_load_1m']} ({t['cpu_cores']} cores)</span>"
        )
        self.cpu_bar.set_fraction(cpu_frac)

        ram_frac = min(1.0, float(t["ram_percent"]) / 100.0)
        self.ram_val_lbl.set_markup(
            f"<span size='small' weight='bold' foreground='#e2e8f0'>Memory (RAM):</span> "
            f"<span size='small' foreground='#a855f7'>{t['ram_used_gb']} GB / {t['ram_total_gb']} GB ({t['ram_percent']}%)</span>"
        )
        self.ram_bar.set_fraction(ram_frac)

        disk_frac = min(1.0, float(t["disk_percent"]) / 100.0)
        self.disk_val_lbl.set_markup(
            f"<span size='small' weight='bold' foreground='#e2e8f0'>Disk (/home):</span> "
            f"<span size='small' foreground='#34d399'>{t['disk_used_gb']} GB / {t['disk_total_gb']} GB ({t['disk_percent']}%)</span>"
        )
        self.disk_bar.set_fraction(disk_frac)
        return True

    def _on_slash_menu_clicked(self, widget: Gtk.Widget) -> None:
        menu = Gtk.Menu()
        for label, cmd in (
            ("🩺 System Doctor Audit (/doctor)", "/doctor"),
            ("🧠 Agent Memory & Notes (/memory)", "/memory"),
            ("🔑 Create Hetzner OpenSSH Key", "tchiko create an ssh key for my remote hetzner server in OpenSSH format"),
            ("🖥️ System Health Report (/sysinfo)", "/sysinfo"),
            ("⚙️ Top Running Processes (/procs)", "/procs"),
            ("📂 List Desktop Files (/files ~/Desktop)", "/files ~/Desktop"),
            ("🌐 Network & Open Ports", "check listening ports"),
            ("🛡️ View Permission Policy (/permissions)", "/permissions"),
            ("❓ Help & Commands (/help)", "/help"),
        ):
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda _w, c=cmd: self.submit_external_command(c))
            menu.append(item)
        menu.show_all()
        menu.popup_at_widget(widget, Gdk.Gravity.NORTH_WEST, Gdk.Gravity.SOUTH_WEST, None)

    def _on_mood_menu_clicked(self, widget: Gtk.Widget) -> None:
        menu = Gtk.Menu()
        for emo_key, emo_label in (
            ("roar", "🔥 Chaos Sonic Shockwave"),
            ("wing_slash", "⚔️ 360° Razor Wing Slash"),
            ("love", "⚡ Crimson Lightning Surge"),
            ("executing", "⭕ Ten-Rings Overdrive"),
            ("happy", "🦅 Apex Strike Hover"),
            ("thinking", "🎯 Tactical Chaos Scan"),
            ("idle", "🛡️ Guardian Hover (Default)"),
            ("sleepy", "🌑 Obsidian Gargoyle Rest"),
            ("dizzy", "🌀 Chaos Vortex"),
        ):
            item = Gtk.MenuItem(label=emo_label)
            item.connect("activate", lambda _w, ek=emo_key: self._trigger_emotion(ek))
            menu.append(item)
        menu.show_all()
        menu.popup_at_widget(widget, Gdk.Gravity.NORTH_WEST, Gdk.Gravity.SOUTH_WEST, None)

    def _trigger_emotion(self, emotion: str) -> None:
        self._mini_renderer.set_emotion(emotion, duration=6.0)
        self.on_ghost_state(emotion, None)

    def set_bubble_listener(self, callback: Callable[[str], None]) -> None:
        """Register callback to update the talking speech bubble above the floating Tchiko pet."""
        self._bubble_listener = callback

    def submit_inline_prompt(self, prompt: str) -> None:
        """Execute a prompt submitted from the quick-input bar below Tchiko and reply in the talking bubble."""
        cmd = prompt.strip()
        if not cmd:
            return
        self._dispatch_prompt(cmd)

    def submit_external_command(self, cmd: str) -> None:
        """Switch to Chat tab, show window, and execute command."""
        self.show_all()
        self.present()
        self._switch_tab("chat")
        self.prompt_entry.set_text(cmd)
        self._on_send_clicked()

    def _on_clear_chat(self, *_args: Any) -> None:
        for child in list(self.feed_box.get_children()):
            self.feed_box.remove(child)
        self._add_welcome_hero_card()
        self._scroll_feed_to_bottom()

    def _append_user_bubble(self, text: str, ts: str) -> None:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        bubble = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        bubble.get_style_context().add_class("tchiko-user-bubble")
        bubble.set_margin_start(90)

        hdr = Gtk.Label(xalign=1.0)
        hdr.set_markup(f"<span size='x-small' foreground='#bfdbfe'>You • {ts}</span>")

        msg_lbl = Gtk.Label(xalign=0.0)
        msg_lbl.set_line_wrap(True)
        msg_lbl.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        msg_lbl.set_selectable(True)
        msg_lbl.set_text(text)

        bubble.pack_start(hdr, False, False, 0)
        bubble.pack_start(msg_lbl, False, False, 0)
        row.pack_end(bubble, False, True, 0)
        self.feed_box.pack_start(row, False, False, 0)
        row.show_all()

    def _create_bot_streaming_card(self, ts: str) -> None:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.get_style_context().add_class("tchiko-bot-card")
        card.set_margin_end(50)

        # Card Header with Tchiko name + Copy button
        hdr_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        name_lbl = Gtk.Label(xalign=0.0)
        name_lbl.set_markup(
            f"<span weight='bold' size='small' foreground='#38bdf8'>🐾 Tchiko</span> "
            f"<span size='x-small' foreground='#64748b'>• {ts}</span>"
        )
        copy_btn = Gtk.Button(label="📋 Copy")
        copy_btn.get_style_context().add_class("tchiko-copy-btn")
        hdr_box.pack_start(name_lbl, True, True, 0)
        hdr_box.pack_end(copy_btn, False, False, 0)
        card.pack_start(hdr_box, False, False, 0)

        # Content container (streaming label at first, then rich blocks on completion)
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        stream_lbl = Gtk.Label(xalign=0.0)
        stream_lbl.set_line_wrap(True)
        stream_lbl.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        stream_lbl.set_selectable(True)
        stream_lbl.set_markup("<span foreground='#94a3b8'><i>Thinking...</i></span>")
        content_box.pack_start(stream_lbl, False, False, 0)
        card.pack_start(content_box, False, False, 0)

        self._active_stream_label = stream_lbl
        self._active_stream_card = content_box
        self._active_stream_text = []

        def _copy_all(_btn: Gtk.Button) -> None:
            raw = "".join(self._active_stream_text).strip() if content_box == self._active_stream_card else getattr(content_box, "_raw_text", "")
            self._copy_to_clipboard(raw, copy_btn)

        copy_btn.connect("clicked", _copy_all)

        row.pack_start(card, True, True, 0)
        self.feed_box.pack_start(row, False, False, 0)
        row.show_all()

    def _on_send_clicked(self, *_args: Any) -> None:
        prompt = self.prompt_entry.get_text().strip()
        if not prompt:
            return
        self.prompt_entry.set_text("")
        self._dispatch_prompt(prompt)

    def _dispatch_prompt(self, prompt: str) -> None:
        ts = datetime.now().strftime("%H:%M")
        self._append_user_bubble(prompt, ts)
        self._create_bot_streaming_card(ts)
        self._scroll_feed_to_bottom()

        self._set_header_mood("thinking", "Thinking...")
        self.engine.process_prompt_async(
            prompt=prompt,
            on_thought=lambda th: GLib.idle_add(self._on_thought_update, th),
            on_tool_call=lambda name, args: GLib.idle_add(
                self._on_tool_update, name, args
            ),
            on_token=lambda tok: GLib.idle_add(self._append_token, tok),
            on_complete=lambda _full: GLib.idle_add(self._on_response_complete),
            on_state_change=lambda st: GLib.idle_add(self._on_engine_state, st),
            on_approval_needed=lambda cmd, yes, no: GLib.idle_add(
                self._prompt_inline_approval, cmd, yes, no
            ),
        )

    def _on_thought_update(self, thought_text: str) -> bool:
        self._append_activity(f"[Thinking] {thought_text}")
        if not self._active_stream_text:
            status_line = f"🧠 {thought_text}"
            if self._active_stream_label is not None:
                self._active_stream_label.set_text(status_line)
            bubble_cb = getattr(self, "_bubble_listener", None)
            if bubble_cb is not None:
                bubble_cb(f"### ⚡ Tchiko Autonomous Agent\n- {status_line}")
        return False

    def _on_tool_update(self, name: str, args: str) -> bool:
        self._append_activity(f"[Executing Tool] {name} {args}")
        self._set_header_mood("executing", f"Running {name}...")
        if not self._active_stream_text:
            status_line = f"🔧 Tool `{name}`: {args[:120]}"
            if self._active_stream_label is not None:
                self._active_stream_label.set_text(status_line)
            bubble_cb = getattr(self, "_bubble_listener", None)
            if bubble_cb is not None:
                bubble_cb(f"### ⚡ Tchiko Autonomous Agent\n- {status_line}")
        return False

    def _on_engine_state(self, state: str) -> bool:
        labels = {
            "idle": "Ready • Antigravity SDK",
            "thinking": "Thinking...",
            "executing": "Executing Linux Tool...",
            "alert": "Attention Needed",
        }
        self._set_header_mood(state, labels.get(state, state.capitalize()))
        self.on_ghost_state(state, None)
        return False

    def _set_header_mood(self, emotion: str, subtitle: str) -> None:
        self._mini_renderer.set_emotion(emotion, duration=4.0)
        color = "#38bdf8" if emotion in ("idle", "happy") else ("#a855f7" if emotion == "thinking" else "#fbbf24")
        self.status_sub_lbl.set_markup(
            f"<span size='x-small' foreground='{color}'>● {html.escape(subtitle)}</span>"
        )

    def _append_token(self, token: str) -> bool:
        self._active_stream_text.append(token)
        current = "".join(self._active_stream_text)
        if self._active_stream_label is not None:
            self._active_stream_label.set_text(current)
            self._scroll_feed_to_bottom()
        bubble_cb = getattr(self, "_bubble_listener", None)
        if bubble_cb is not None:
            bubble_cb(current)
        return False

    def _on_response_complete(self) -> bool:
        full_raw = "".join(self._active_stream_text).strip()
        if self._active_stream_card is not None:
            setattr(self._active_stream_card, "_raw_text", full_raw)
            self._render_rich_markdown_into_card(self._active_stream_card, full_raw)
        self._active_stream_label = None
        bubble_cb = getattr(self, "_bubble_listener", None)
        if bubble_cb is not None and full_raw:
            bubble_cb(full_raw)
        self._set_header_mood("happy", "Ready • Antigravity SDK")
        self.on_ghost_state("happy", None)
        self._scroll_feed_to_bottom()
        return False

    def _render_rich_markdown_into_card(self, container: Gtk.Box, markdown_text: str) -> None:
        """Replace raw streaming text with styled Markdown blocks & terminal output cards."""
        for child in list(container.get_children()):
            container.remove(child)

        # Split by fenced code blocks ```...```
        parts = re.split(r"```(?:[a-zA-Z0-9_-]*\n)?(.*?)```", markdown_text, flags=re.DOTALL)
        for idx, segment in enumerate(parts):
            seg = segment.strip()
            if not seg:
                continue
            if idx % 2 == 1:
                # Fenced Code / Terminal Output Block
                code_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
                code_box.get_style_context().add_class("tchiko-code-card")

                top_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                term_lbl = Gtk.Label(xalign=0.0)
                term_lbl.set_markup("<span size='x-small' foreground='#64748b'>TERMINAL OUTPUT</span>")
                c_btn = Gtk.Button(label="📋 Copy Output")
                c_btn.get_style_context().add_class("tchiko-copy-btn")
                c_btn.connect("clicked", lambda b, t=seg: self._copy_to_clipboard(t, b))
                top_bar.pack_start(term_lbl, True, True, 0)
                top_bar.pack_end(c_btn, False, False, 0)
                code_box.pack_start(top_bar, False, False, 0)

                code_lbl = Gtk.Label(xalign=0.0)
                code_lbl.get_style_context().add_class("tchiko-code-text")
                code_lbl.set_selectable(True)
                code_lbl.set_line_wrap(True)
                code_lbl.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
                code_lbl.set_text(seg)
                code_box.pack_start(code_lbl, False, False, 0)
                container.pack_start(code_box, False, False, 0)
            else:
                # Format Markdown headings, bold, and inline code into clean Pango markup
                lbl = Gtk.Label(xalign=0.0)
                lbl.set_line_wrap(True)
                lbl.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
                lbl.set_selectable(True)
                lbl.set_markup(self._markdown_to_pango(seg))
                container.pack_start(lbl, False, False, 0)

        container.show_all()

    @staticmethod
    def _markdown_to_pango(text: str) -> str:
        lines: List[str] = []
        for raw_line in text.splitlines():
            line = html.escape(raw_line)
            if line.startswith("### "):
                heading = line[4:].strip()
                lines.append(f"<span size='medium' weight='bold' foreground='#38bdf8'>{heading}</span>")
                continue
            if line.startswith("- "):
                line = "  • " + line[2:]
            # Bold **...**
            line = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", line)
            # Inline code `...`
            line = re.sub(
                r"`([^`]+)`",
                r"<span font_family='monospace' foreground='#7dd3fc'>\1</span>",
                line,
            )
            lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _copy_to_clipboard(text: str, btn: Gtk.Button) -> None:
        clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clip.set_text(text, -1)
        orig_label = btn.get_label()
        btn.set_label("✓ Copied!")
        GLib.timeout_add(1600, lambda: (btn.set_label(orig_label), False)[1])

    def _append_activity(self, line: str) -> bool:
        ts = datetime.now().strftime("%H:%M:%S")
        end = self.activity_buffer.get_end_iter()
        self.activity_buffer.insert(end, f"[{ts}] {line}\n")
        return False

    def _prompt_inline_approval(
        self, cmd: str, approve_cb: Callable[[], None], deny_cb: Callable[[], None]
    ) -> bool:
        self._approve_cb = approve_cb
        self._deny_cb = deny_cb
        self.approval_lbl.set_text(f"🔒 Allow command: {cmd} ?")
        self.approval_bar.show_all()
        return False

    def _on_approve_clicked(self, *_args: Any) -> None:
        self.approval_bar.hide()
        if self._approve_cb:
            cb = self._approve_cb
            self._approve_cb = None
            cb()

    def _on_approve_all_clicked(self, *_args: Any) -> None:
        self.approval_bar.hide()
        self.config.set_all_permissions(True)
        if self._approve_cb:
            cb = self._approve_cb
            self._approve_cb = None
            cb()

    def _on_deny_clicked(self, *_args: Any) -> None:
        self.approval_bar.hide()
        if self._deny_cb:
            cb = self._deny_cb
            self._deny_cb = None
            cb()

    def _scroll_feed_to_bottom(self) -> None:
        def _do_scroll() -> bool:
            adj = self.chat_scroll.get_vadjustment()
            if adj is not None:
                adj.set_value(max(0.0, adj.get_upper() - adj.get_page_size()))
            return False

        GLib.idle_add(_do_scroll)
