"""Tchiko settings window (`tchiko/settings_window.py`).

A sidebar with three pages, each built from grouped preference rows:

- **Access** — the master full-access switch, per-capability switches, and the execution
  policies (tool policy, file access, internet, terminal sandbox).
- **Agent** — model selection.
- **Companion** — coat picker with live previews, size, opacity and window behaviour.

Every change is written straight to `config/settings.json` (and mirrored to `antigravity.yaml`).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from . import ui_theme as ui
from .config_manager import ConfigManager
from .svg_ghost_renderer import SvgGhostRenderer

# (config key, icon, title, description)
CAPABILITIES: List[Tuple[str, str, str, str]] = [
    ("bash_execution", "utilities-terminal-symbolic", "Shell commands", "Run bash and terminal commands"),
    ("filesystem_read_write", "folder-symbolic", "Files", "Read and write anywhere on the filesystem"),
    ("process_management", "system-run-symbolic", "Processes and services", "Inspect and manage with ps and systemctl"),
    ("desktop_automation", "computer-symbolic", "Desktop", "Open apps, files and links; send notifications"),
    ("package_management", "package-x-generic-symbolic", "Packages", "Install and update with apt, pip and npm"),
    ("network_requests", "network-wired-symbolic", "Network", "Diagnostics and outbound requests"),
]

TOOL_POLICIES: List[Tuple[str, str]] = [
    ("always-proceed", "Run without asking"),
    ("request-review", "Ask before each command"),
    ("proceed-in-sandbox", "Run inside the sandbox"),
    ("strict", "Read-only"),
]
ACCESS_CHOICES: List[Tuple[str, str]] = [("allow", "Allow"), ("ask", "Ask first"), ("deny", "Block")]
MODELS = ("gemini-2.5-pro", "gemini-2.5-flash", "gemini-next", "antigravity-default")


class TchikoSettingsWindow(Gtk.Window):
    """Preferences for access control, the agent and the floating companion."""

    def __init__(self, config: ConfigManager) -> None:
        super().__init__(title="Tchiko Settings")
        self.config = config
        self._updating_ui = False
        self._cap_switches: Dict[str, Gtk.Switch] = {}
        self._coat_buttons: Dict[str, Gtk.RadioButton] = {}

        ui.apply_theme()
        self.get_style_context().add_class("tchiko-window")
        self.set_default_size(820, 640)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_keep_above(True)
        self.connect("delete-event", self._on_delete_event)

        self._build_ui()
        self.config.subscribe(self._sync_from_config)
        self._sync_from_config(self.config.data)

    def _on_delete_event(self, _widget: Gtk.Widget, _event: Any) -> bool:
        self.hide()
        return True

    # ── Layout ───────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        hbar = Gtk.HeaderBar()
        hbar.set_show_close_button(True)
        hbar.set_title("Settings")
        hbar.get_style_context().add_class("tchiko-titlebar")
        self.set_titlebar(hbar)

        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        root.get_style_context().add_class("tchiko-root")

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(140)

        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        sidebar.get_style_context().add_class("tchiko-sidebar")
        sidebar.set_size_request(190, -1)
        group: Optional[Gtk.RadioButton] = None
        for page_id, icon_name, title, builder in (
            ("access", "security-high-symbolic", "Access", self._build_access_page),
            ("agent", "applications-engineering-symbolic", "Agent", self._build_agent_page),
            ("companion", "preferences-desktop-appearance-symbolic", "Companion", self._build_companion_page),
        ):
            self.stack.add_named(self._scrolled(builder()), page_id)
            btn = Gtk.RadioButton.new_from_widget(group)
            group = group or btn
            btn.set_mode(False)
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            row.pack_start(ui.icon(icon_name, 16), False, False, 0)
            row.pack_start(Gtk.Label(label=title, xalign=0.0), True, True, 0)
            btn.add(row)
            btn.connect("toggled", lambda b, pid=page_id: b.get_active() and self.stack.set_visible_child_name(pid))
            sidebar.pack_start(btn, False, False, 0)

        self.status_lbl = Gtk.Label(xalign=0.0)
        self.status_lbl.set_line_wrap(True)
        self.status_lbl.set_margin_start(12)
        self.status_lbl.set_margin_bottom(6)
        self.status_lbl.set_markup(
            f"<span size='small' foreground='{ui.TEXT_MUTED}'>Changes save automatically</span>"
        )
        sidebar.pack_end(self.status_lbl, False, False, 0)

        root.pack_start(sidebar, False, False, 0)
        root.pack_start(self.stack, True, True, 0)
        self.add(root)

    @staticmethod
    def _scrolled(child: Gtk.Widget) -> Gtk.Widget:
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.get_style_context().add_class("tchiko-scroll")
        scroll.add(child)
        return scroll

    @staticmethod
    def _page(title: str, subtitle: str) -> Gtk.Box:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for setter in (page.set_margin_start, page.set_margin_end):
            setter(28)
        page.set_margin_top(24)
        page.set_margin_bottom(28)
        page.pack_start(ui.label(title, "display"), False, False, 0)
        page.pack_start(ui.label(subtitle, "dim", wrap=True), False, False, 0)
        return page

    @staticmethod
    def _group(page: Gtk.Box, caption: str) -> Gtk.Box:
        """Add a captioned card to `page` and return the box rows are packed into."""
        cap = ui.label(caption.upper(), "caption")
        cap.set_margin_top(14)
        cap.set_margin_start(4)
        page.pack_start(cap, False, False, 0)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        card.get_style_context().add_class("tchiko-card")
        page.pack_start(card, False, False, 0)
        return card

    @staticmethod
    def _row(
        card: Gtk.Box, title: str, description: str, control: Gtk.Widget, icon_name: str = ""
    ) -> Gtk.Box:
        """A preference row: optional icon, title + description on the left, control on the right."""
        if card.get_children():
            card.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        row.get_style_context().add_class("tchiko-row")
        if icon_name:
            img = ui.icon(icon_name, 16)
            img.get_style_context().add_class("tchiko-dim")
            row.pack_start(img, False, False, 0)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        text.set_valign(Gtk.Align.CENTER)
        text.pack_start(ui.label(title, "tchiko-row-title"), False, False, 0)
        if description:
            desc = Gtk.Label(xalign=0.0)
            desc.set_line_wrap(True)
            desc.set_markup(f"<span size='small' foreground='{ui.TEXT_SECONDARY}'>{description}</span>")
            text.pack_start(desc, False, False, 0)
        row.pack_start(text, True, True, 0)
        control.set_valign(Gtk.Align.CENTER)
        row.pack_end(control, False, False, 0)
        card.pack_start(row, False, False, 0)
        return row

    def _combo(self, choices: List[Tuple[str, str]]) -> Gtk.ComboBoxText:
        combo = Gtk.ComboBoxText()
        for cid, text in choices:
            combo.append(cid, text)
        combo.connect("changed", self._on_field_changed)
        return combo

    def _switch(self) -> Gtk.Switch:
        sw = Gtk.Switch()
        sw.connect("notify::active", self._on_field_changed)
        return sw

    # ── Pages ────────────────────────────────────────────────────────────────
    def _build_access_page(self) -> Gtk.Widget:
        page = self._page("Access", "Decide how much of this machine Tchiko may touch, and whether it asks first.")

        self.hero = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        self.hero.get_style_context().add_class("tchiko-card")
        self.hero.get_style_context().add_class("tchiko-card-pad")
        self.hero.set_margin_top(12)
        chip = Gtk.Box()
        chip.set_valign(Gtk.Align.CENTER)
        chip.get_style_context().add_class("tchiko-tile-icon")
        chip.add(ui.icon("security-high-symbolic", 20))
        self.hero.pack_start(chip, False, False, 0)
        hero_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.hero_title = ui.label("", "title")
        self.hero_desc = ui.label("", "dim", wrap=True)
        hero_text.pack_start(self.hero_title, False, False, 0)
        hero_text.pack_start(self.hero_desc, False, False, 0)
        self.hero.pack_start(hero_text, True, True, 0)
        self.master_switch = Gtk.Switch()
        self.master_switch.set_valign(Gtk.Align.CENTER)
        self.master_switch.connect("notify::active", self._on_master_switch_toggled)
        self.hero.pack_end(self.master_switch, False, False, 0)
        page.pack_start(self.hero, False, False, 0)

        caps = self._group(page, "Capabilities")
        for key, icon_name, title, desc in CAPABILITIES:
            sw = self._switch()
            self._cap_switches[key] = sw
            self._row(caps, title, desc, sw, icon_name)

        policy = self._group(page, "Execution policy")
        self.policy_combo = self._combo(TOOL_POLICIES)
        self._row(policy, "When Tchiko wants to run a tool", "Applies to commands and file edits", self.policy_combo)
        self.file_access_combo = self._combo(ACCESS_CHOICES)
        self._row(policy, "Files outside the workspace", "Anything beyond the working directory", self.file_access_combo)
        self.net_access_combo = self._combo(ACCESS_CHOICES)
        self._row(policy, "Internet access", "Downloads, package indexes and web requests", self.net_access_combo)
        self.sandbox_switch = self._switch()
        self._row(policy, "Terminal sandbox", "Isolate commands from the host. Turn off for direct access.", self.sandbox_switch)
        return page

    def _build_agent_page(self) -> Gtk.Widget:
        page = self._page("Agent", "The model that plans and carries out your requests.")
        card = self._group(page, "Model")
        self.model_combo = self._combo([(m, m) for m in MODELS])
        self._row(card, "Preferred model", "Used by the Antigravity backend", self.model_combo)
        return page

    def _build_companion_page(self) -> Gtk.Widget:
        page = self._page("Companion", "How the floating Tchiko looks and behaves on your desktop.")

        cap = ui.label("COAT", "caption")
        cap.set_margin_top(14)
        cap.set_margin_start(4)
        page.pack_start(cap, False, False, 0)
        coats = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, homogeneous=True)
        group: Optional[Gtk.RadioButton] = None
        preview = SvgGhostRenderer()
        preview.step(0.4)
        for theme_key, coat_name in ui.COAT_NAMES:
            btn = Gtk.RadioButton.new_from_widget(group)
            group = group or btn
            btn.set_mode(False)
            btn.get_style_context().add_class("tchiko-coat")
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            thumb = Gtk.Image()
            px = 84 * max(1, self.get_scale_factor())
            ui.set_hidpi_pixbuf(thumb, preview.render_to_pixbuf(px, px, theme_name=theme_key, opacity=1.0), 84)
            inner.pack_start(thumb, False, False, 0)
            inner.pack_start(Gtk.Label(label=coat_name), False, False, 0)
            btn.add(inner)
            btn.connect("toggled", self._on_field_changed)
            self._coat_buttons[theme_key] = btn
            coats.pack_start(btn, True, True, 0)
        page.pack_start(coats, False, False, 0)

        look = self._group(page, "Appearance")
        self.size_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 90, 220, 5)
        self.size_scale.set_draw_value(False)
        self.size_scale.set_size_request(220, -1)
        self.size_scale.connect("value-changed", self._on_field_changed)
        self.size_value_lbl = ui.label("", "dim", xalign=1.0)
        self.size_value_lbl.set_width_chars(6)
        self._row(look, "Size", "", self._with_value(self.size_scale, self.size_value_lbl))
        self.opacity_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.40, 1.0, 0.02)
        self.opacity_scale.set_draw_value(False)
        self.opacity_scale.set_size_request(220, -1)
        self.opacity_scale.connect("value-changed", self._on_field_changed)
        self.opacity_value_lbl = ui.label("", "dim", xalign=1.0)
        self.opacity_value_lbl.set_width_chars(6)
        self._row(look, "Opacity", "", self._with_value(self.opacity_scale, self.opacity_value_lbl))

        behave = self._group(page, "Behaviour")
        self.always_top_switch = self._switch()
        self._row(behave, "Always on top", "Keep Tchiko above other windows", self.always_top_switch)
        self.bubble_switch = self._switch()
        self._row(behave, "Speech bubble", "Show replies in a bubble above Tchiko", self.bubble_switch)
        return page

    @staticmethod
    def _with_value(scale: Gtk.Scale, value_lbl: Gtk.Label) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.pack_start(scale, True, True, 0)
        box.pack_start(value_lbl, False, False, 0)
        return box

    # ── Config sync ──────────────────────────────────────────────────────────
    def _sync_from_config(self, data: Dict[str, Any]) -> None:
        self._updating_ui = True
        try:
            perms = data.get("permissions", {})
            all_ok = bool(perms.get("approve_all_system_permissions", True))
            self.master_switch.set_active(all_ok)
            hero_ctx = self.hero.get_style_context()
            hero_ctx.remove_class("tchiko-hero-ok")
            hero_ctx.remove_class("tchiko-hero-review")
            hero_ctx.add_class("tchiko-hero-ok" if all_ok else "tchiko-hero-review")
            if all_ok:
                self.hero_title.set_text("Full access is on")
                self.hero_desc.set_text(
                    "Tchiko runs commands, edits files and manages services on its own, without asking."
                )
            else:
                self.hero_title.set_text("Supervised mode")
                self.hero_desc.set_text(
                    "Tchiko is limited to the capabilities below and follows the execution policy. "
                    "Turn this on to grant everything at once."
                )

            self.model_combo.set_active_id(data.get("agent", {}).get("model", "gemini-2.5-pro"))
            self.policy_combo.set_active_id(perms.get("tool_execution_policy", "always-proceed"))
            self.file_access_combo.set_active_id(perms.get("non_workspace_file_access", "allow"))
            self.net_access_combo.set_active_id(perms.get("internet_access_policy", "allow"))
            self.sandbox_switch.set_active(bool(perms.get("terminal_sandbox", False)))

            caps = perms.get("capabilities", {})
            for key, sw in self._cap_switches.items():
                sw.set_active(bool(caps.get(key, True)))

            ghost_cfg = data.get("ghost_widget", {})
            coat = ghost_cfg.get("theme", "phantom_cyan")
            if coat in self._coat_buttons:
                self._coat_buttons[coat].set_active(True)
            self.size_scale.set_value(float(ghost_cfg.get("size", 140)))
            self.opacity_scale.set_value(float(ghost_cfg.get("opacity", 0.96)))
            self.always_top_switch.set_active(bool(ghost_cfg.get("always_on_top", True)))
            self.bubble_switch.set_active(bool(ghost_cfg.get("show_speech_bubble", True)))
            self._update_value_labels()
        finally:
            self._updating_ui = False

    def _update_value_labels(self) -> None:
        self.size_value_lbl.set_text(f"{int(self.size_scale.get_value())} px")
        self.opacity_value_lbl.set_text(f"{int(round(self.opacity_scale.get_value() * 100))}%")

    def _on_master_switch_toggled(self, switch: Gtk.Switch, _gparam: Any) -> None:
        if self._updating_ui:
            return
        self.config.set_all_permissions(switch.get_active())

    def _on_field_changed(self, *_args: Any) -> None:
        if self._updating_ui:
            return
        self._update_value_labels()
        perms = self.config.data.setdefault("permissions", {})
        perms["tool_execution_policy"] = self.policy_combo.get_active_id() or "always-proceed"
        perms["non_workspace_file_access"] = self.file_access_combo.get_active_id() or "allow"
        perms["internet_access_policy"] = self.net_access_combo.get_active_id() or "allow"
        perms["terminal_sandbox"] = self.sandbox_switch.get_active()

        caps = perms.setdefault("capabilities", {})
        for key, sw in self._cap_switches.items():
            caps[key] = sw.get_active()

        # Full access means every capability on and no review step; anything less is supervised.
        perms["approve_all_system_permissions"] = (
            all(caps.values()) and perms["tool_execution_policy"] == "always-proceed"
        )

        self.config.data.setdefault("agent", {})["model"] = self.model_combo.get_active_id() or "gemini-2.5-pro"

        ghost_cfg = self.config.data.setdefault("ghost_widget", {})
        ghost_cfg["theme"] = next(
            (key for key, btn in self._coat_buttons.items() if btn.get_active()), "phantom_cyan"
        )
        ghost_cfg["size"] = int(self.size_scale.get_value())
        ghost_cfg["opacity"] = round(float(self.opacity_scale.get_value()), 2)
        ghost_cfg["always_on_top"] = self.always_top_switch.get_active()
        ghost_cfg["show_speech_bubble"] = self.bubble_switch.get_active()

        self.config.save(notify=True)
