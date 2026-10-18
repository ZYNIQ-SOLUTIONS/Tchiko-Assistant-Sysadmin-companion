"""Tchiko Settings & Antigravity Permission Window (`tchiko/settings_window.py`).

Modeled after the Antigravity 2.0 Settings panel:
- Master switch: "Approve All Linux System Permissions (Full Autonomous Mode)"
- Tool Execution Policy (`always-proceed`, `request-review`, `proceed-in-sandbox`, `strict`)
- Terminal Sandbox (`BypassSandbox`), Non-Workspace File Access, Internet Access Policy
- Granular Linux System Capabilities (Bash, Filesystem, Processes, Desktop Automation, Packages, Network)
- Floating SVG Ghost Appearance customization (Theme, Size, Opacity, Always-on-Top, Speech Bubble)
"""

from __future__ import annotations

from typing import Any, Dict

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from .config_manager import ConfigManager


class TchikoSettingsWindow(Gtk.Window):
    """Antigravity-styled Settings & System Permissions Window for Tchiko Assistant."""

    def __init__(self, config: ConfigManager) -> None:
        super().__init__(title="⚙️ Tchiko Settings & System Permissions")
        self.config = config
        self._updating_ui = False
        self._cap_checks: Dict[str, Gtk.CheckButton] = {}

        self.set_default_size(680, 660)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_keep_above(True)
        self.connect("delete-event", self._on_delete_event)

        self._build_ui()
        self.config.subscribe(self._sync_from_config)
        self._sync_from_config(self.config.data)

    def _on_delete_event(self, _widget: Gtk.Widget, _event: Any) -> bool:
        self.hide()
        return True

    def _build_ui(self) -> None:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        outer.get_style_context().add_class("tchiko-root")

        # Top Banner
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        header_box.set_margin_top(16)
        header_box.set_margin_bottom(12)
        header_box.set_margin_start(20)
        header_box.set_margin_end(20)

        title_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        title_lbl = Gtk.Label(xalign=0.0)
        title_lbl.set_markup(
            "<span size='large' weight='bold' foreground='#58a6ff'>"
            "👻 Tchiko Assistant — Settings &amp; Linux System Permissions</span>"
        )
        sub_lbl = Gtk.Label(xalign=0.0)
        sub_lbl.set_markup(
            "<span size='small' foreground='#8b949e'>"
            "Powered by Google Antigravity SDK (`LocalAgentConfig` &amp; `CapabilitiesConfig`)</span>"
        )
        title_vbox.pack_start(title_lbl, False, False, 0)
        title_vbox.pack_start(sub_lbl, False, False, 0)
        header_box.pack_start(title_vbox, True, True, 0)
        outer.pack_start(header_box, False, False, 0)

        # Scrollable content area
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_start(20)
        content.set_margin_end(20)
        content.set_margin_bottom(20)
        scroller.add(content)
        outer.pack_start(scroller, True, True, 0)

        # 1. MASTER PERMISSION APPROVAL CARD
        master_frame = Gtk.Frame()
        master_frame.get_style_context().add_class("tchiko-card")
        master_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        master_box.set_margin_top(14)
        master_box.set_margin_bottom(14)
        master_box.set_margin_start(16)
        master_box.set_margin_end(16)

        master_text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.master_title_lbl = Gtk.Label(xalign=0.0)
        self.master_title_lbl.set_markup(
            "<span weight='bold' size='medium' foreground='#3fb950'>"
            "🛡️ Approve All Linux System Permissions (Full Autonomous Mode)</span>"
        )
        master_desc = Gtk.Label(xalign=0.0)
        master_desc.set_line_wrap(True)
        master_desc.set_markup(
            "<span size='small' foreground='#c9d1d9'>"
            "When approved, Tchiko has full permission to interact with your Ubuntu Linux system "
            "(execute bash commands, read/write files, manage processes, launch desktop apps, and "
            "enable `CapabilitiesConfig()` in the Antigravity SDK) without asking for confirmation.</span>"
        )
        master_text_box.pack_start(self.master_title_lbl, False, False, 0)
        master_text_box.pack_start(master_desc, False, False, 0)

        self.master_switch = Gtk.Switch()
        self.master_switch.set_valign(Gtk.Align.CENTER)
        self.master_switch.connect("notify::active", self._on_master_switch_toggled)

        master_box.pack_start(master_text_box, True, True, 0)
        master_box.pack_end(self.master_switch, False, False, 0)
        master_frame.add(master_box)
        content.pack_start(master_frame, False, False, 0)

        # 2. ANTIGRAVITY 2.0 SDK & SECURITY POLICIES CARD
        policy_frame = Gtk.Frame(label="  🚀 Antigravity SDK & Execution Policies  ")
        policy_frame.get_style_context().add_class("tchiko-card")
        policy_grid = Gtk.Grid(column_spacing=16, row_spacing=10)
        policy_grid.set_margin_top(12)
        policy_grid.set_margin_bottom(14)
        policy_grid.set_margin_start(16)
        policy_grid.set_margin_end(16)

        # Model Selection
        policy_grid.attach(self._make_field_label("Active Gemini / Antigravity Model:"), 0, 0, 1, 1)
        self.model_combo = Gtk.ComboBoxText()
        for mid in ("gemini-2.5-pro", "gemini-2.5-flash", "gemini-next", "antigravity-default"):
            self.model_combo.append(mid, mid)
        self.model_combo.connect("changed", self._on_field_changed)
        policy_grid.attach(self.model_combo, 1, 0, 1, 1)

        # Tool Execution Policy
        policy_grid.attach(self._make_field_label("Tool Execution Policy:"), 0, 1, 1, 1)
        self.policy_combo = Gtk.ComboBoxText()
        for pid, label in (
            ("always-proceed", "always-proceed (Auto-execute without asking)"),
            ("request-review", "request-review (Ask for confirmation)"),
            ("proceed-in-sandbox", "proceed-in-sandbox (Sandboxed execution)"),
            ("strict", "strict (Read-only mode)"),
        ):
            self.policy_combo.append(pid, label)
        self.policy_combo.connect("changed", self._on_field_changed)
        policy_grid.attach(self.policy_combo, 1, 1, 1, 1)

        # Non-Workspace File Access
        policy_grid.attach(self._make_field_label("Non-Workspace File Access:"), 0, 2, 1, 1)
        self.file_access_combo = Gtk.ComboBoxText()
        for fid in ("allow", "ask", "deny"):
            self.file_access_combo.append(fid, fid)
        self.file_access_combo.connect("changed", self._on_field_changed)
        policy_grid.attach(self.file_access_combo, 1, 2, 1, 1)

        # Internet Access Policy
        policy_grid.attach(self._make_field_label("Internet Access Policy:"), 0, 3, 1, 1)
        self.net_access_combo = Gtk.ComboBoxText()
        for nid in ("allow", "ask", "deny"):
            self.net_access_combo.append(nid, nid)
        self.net_access_combo.connect("changed", self._on_field_changed)
        policy_grid.attach(self.net_access_combo, 1, 3, 1, 1)

        # Terminal Sandbox checkbox
        self.sandbox_check = Gtk.CheckButton(
            label="Enable Terminal Sandbox (Uncheck to grant direct host Ubuntu access)"
        )
        self.sandbox_check.connect("toggled", self._on_field_changed)
        policy_grid.attach(self.sandbox_check, 0, 4, 2, 1)

        policy_frame.add(policy_grid)
        content.pack_start(policy_frame, False, False, 0)

        # 3. GRANULAR UBUNTU LINUX SYSTEM CAPABILITIES
        caps_frame = Gtk.Frame(label="  🛠️ Ubuntu Linux System Capabilities  ")
        caps_frame.get_style_context().add_class("tchiko-card")
        caps_grid = Gtk.Grid(column_spacing=20, row_spacing=8)
        caps_grid.set_margin_top(12)
        caps_grid.set_margin_bottom(14)
        caps_grid.set_margin_start(16)
        caps_grid.set_margin_end(16)

        cap_defs = [
            ("bash_execution", "⚡ Execute Bash & Terminal Commands (`/bin/bash`)"),
            ("filesystem_read_write", "📂 Read & Write Files Across Linux Filesystem"),
            ("process_management", "⚙️ Inspect & Manage Processes / Services (`ps`, `systemctl`)"),
            ("desktop_automation", "🖥️ Desktop Automation (`xdg-open`, `notify-send`, apps)"),
            ("package_management", "📦 Package & Environment Management (`apt`, `pip`, `npm`)"),
            ("network_requests", "🌐 Network Diagnostics & External API Requests"),
        ]
        for idx, (cap_key, cap_label) in enumerate(cap_defs):
            chk = Gtk.CheckButton(label=cap_label)
            chk.connect("toggled", self._on_field_changed)
            self._cap_checks[cap_key] = chk
            caps_grid.attach(chk, idx % 2, idx // 2, 1, 1)

        caps_frame.add(caps_grid)
        content.pack_start(caps_frame, False, False, 0)

        # 4. FLOATING SVG GHOST CUSTOMIZATION CARD
        ghost_frame = Gtk.Frame(label="  👻 Floating SVG Ghost Widget Preferences  ")
        ghost_frame.get_style_context().add_class("tchiko-card")
        ghost_grid = Gtk.Grid(column_spacing=16, row_spacing=10)
        ghost_grid.set_margin_top(12)
        ghost_grid.set_margin_bottom(14)
        ghost_grid.set_margin_start(16)
        ghost_grid.set_margin_end(16)

        ghost_grid.attach(self._make_field_label("Ghost Visual Theme:"), 0, 0, 1, 1)
        self.theme_combo = Gtk.ComboBoxText()
        for tk, tlabel in (
            ("phantom_cyan", "Phantom Cyan (Antigravity Cyber)"),
            ("astral_violet", "Astral Violet"),
            ("emerald_matrix", "Emerald Matrix"),
            ("solar_gold", "Solar Gold"),
        ):
            self.theme_combo.append(tk, tlabel)
        self.theme_combo.connect("changed", self._on_field_changed)
        ghost_grid.attach(self.theme_combo, 1, 0, 1, 1)

        ghost_grid.attach(self._make_field_label("Ghost Size (px):"), 0, 1, 1, 1)
        self.size_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 90, 220, 5)
        self.size_scale.set_hexpand(True)
        self.size_scale.connect("value-changed", self._on_field_changed)
        ghost_grid.attach(self.size_scale, 1, 1, 1, 1)

        ghost_grid.attach(self._make_field_label("Ghost Opacity:"), 0, 2, 1, 1)
        self.opacity_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.40, 1.0, 0.02)
        self.opacity_scale.set_hexpand(True)
        self.opacity_scale.connect("value-changed", self._on_field_changed)
        ghost_grid.attach(self.opacity_scale, 1, 2, 1, 1)

        self.always_top_check = Gtk.CheckButton(label="Always on Top of All Ubuntu Windows")
        self.always_top_check.connect("toggled", self._on_field_changed)
        ghost_grid.attach(self.always_top_check, 0, 3, 1, 1)

        self.bubble_check = Gtk.CheckButton(label="Show Floating Speech Bubble Above Ghost")
        self.bubble_check.connect("toggled", self._on_field_changed)
        ghost_grid.attach(self.bubble_check, 1, 3, 1, 1)

        ghost_frame.add(ghost_grid)
        content.pack_start(ghost_frame, False, False, 0)

        # Bottom Action Footer
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        footer.set_margin_start(20)
        footer.set_margin_end(20)
        footer.set_margin_bottom(14)

        self.status_lbl = Gtk.Label(xalign=0.0)
        self.status_lbl.set_markup(
            "<span size='small' foreground='#3fb950'>✓ Synced with `config/settings.json` &amp; `antigravity.yaml`</span>"
        )
        footer.pack_start(self.status_lbl, True, True, 0)

        grant_btn = Gtk.Button(label="🛡️ Approve All Permissions Now")
        grant_btn.connect("clicked", lambda *_: self.config.set_all_permissions(True))
        footer.pack_end(grant_btn, False, False, 0)

        close_btn = Gtk.Button(label="Done")
        close_btn.connect("clicked", lambda *_: self.hide())
        footer.pack_end(close_btn, False, False, 0)

        outer.pack_start(footer, False, False, 0)
        self.add(outer)

    @staticmethod
    def _make_field_label(text: str) -> Gtk.Label:
        lbl = Gtk.Label(label=text, xalign=0.0)
        return lbl

    def _sync_from_config(self, data: Dict[str, Any]) -> None:
        self._updating_ui = True
        try:
            perms = data.get("permissions", {})
            all_ok = bool(perms.get("approve_all_system_permissions", True))
            self.master_switch.set_active(all_ok)
            if all_ok:
                self.master_title_lbl.set_markup(
                    "<span weight='bold' size='medium' foreground='#3fb950'>"
                    "🟢 All Linux System Permissions Approved (Unrestricted Mode)</span>"
                )
            else:
                self.master_title_lbl.set_markup(
                    "<span weight='bold' size='medium' foreground='#d29922'>"
                    "🟡 Supervised / Custom Permission Mode</span>"
                )

            self.model_combo.set_active_id(data.get("agent", {}).get("model", "gemini-2.5-pro"))
            self.policy_combo.set_active_id(perms.get("tool_execution_policy", "always-proceed"))
            self.file_access_combo.set_active_id(perms.get("non_workspace_file_access", "allow"))
            self.net_access_combo.set_active_id(perms.get("internet_access_policy", "allow"))
            self.sandbox_check.set_active(bool(perms.get("terminal_sandbox", False)))

            caps = perms.get("capabilities", {})
            for key, chk in self._cap_checks.items():
                chk.set_active(bool(caps.get(key, True)))

            ghost_cfg = data.get("ghost_widget", {})
            self.theme_combo.set_active_id(ghost_cfg.get("theme", "phantom_cyan"))
            self.size_scale.set_value(float(ghost_cfg.get("size", 140)))
            self.opacity_scale.set_value(float(ghost_cfg.get("opacity", 0.96)))
            self.always_top_check.set_active(bool(ghost_cfg.get("always_on_top", True)))
            self.bubble_check.set_active(bool(ghost_cfg.get("show_speech_bubble", True)))
        finally:
            self._updating_ui = False

    def _on_master_switch_toggled(self, switch: Gtk.Switch, _gparam: Any) -> None:
        if self._updating_ui:
            return
        self.config.set_all_permissions(switch.get_active())

    def _on_field_changed(self, *_args: Any) -> None:
        if self._updating_ui:
            return
        perms = self.config.data.setdefault("permissions", {})
        perms["tool_execution_policy"] = self.policy_combo.get_active_id() or "always-proceed"
        perms["non_workspace_file_access"] = self.file_access_combo.get_active_id() or "allow"
        perms["internet_access_policy"] = self.net_access_combo.get_active_id() or "allow"
        perms["terminal_sandbox"] = self.sandbox_check.get_active()

        caps = perms.setdefault("capabilities", {})
        for key, chk in self._cap_checks.items():
            caps[key] = chk.get_active()

        # If any capability is unchecked or policy is request-review/strict, reflect in master switch
        all_caps_true = all(caps.values()) and perms["tool_execution_policy"] == "always-proceed"
        perms["approve_all_system_permissions"] = all_caps_true

        self.config.data.setdefault("agent", {})["model"] = (
            self.model_combo.get_active_id() or "gemini-2.5-pro"
        )

        ghost_cfg = self.config.data.setdefault("ghost_widget", {})
        ghost_cfg["theme"] = self.theme_combo.get_active_id() or "phantom_cyan"
        ghost_cfg["size"] = int(self.size_scale.get_value())
        ghost_cfg["opacity"] = round(float(self.opacity_scale.get_value()), 2)
        ghost_cfg["always_on_top"] = self.always_top_check.get_active()
        ghost_cfg["show_speech_bubble"] = self.bubble_check.get_active()

        self.config.save(notify=True)
