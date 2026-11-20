"""Tchiko RC pairing window (`tchiko/remote/pair_window.py`).

Displays the generated Tchiko Sigil (circular pairing pattern), the local HTTPS address,
one-step link copy, live expiry countdown, and active remote connection status with the
6-digit end-to-end Safety Code and disconnect/unpair controls.
"""

from __future__ import annotations

import html
from typing import Any, Dict, Optional

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango

from .. import ui_theme as ui
from .service import PAIR_TTL_SEC, PairingSession, RemoteControlService


class TchikoPairWindow(Gtk.Window):
    """Desktop pairing & remote session manager for Tchiko RC."""

    def __init__(self, service: RemoteControlService) -> None:
        super().__init__(title="Tchiko RC — Remote Control")
        self.service = service
        self._current_session: Optional[PairingSession] = None
        self._tick_id: Optional[int] = None

        ui.apply_theme()
        self.get_style_context().add_class("tchiko-window")
        self.set_default_size(460, 650)
        self.set_resizable(False)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_keep_above(True)
        self.connect("delete-event", self._on_delete_event)
        self.connect("show", self._on_show)
        self.connect("hide", self._on_hide)

        self._build_ui()

    def _on_delete_event(self, _widget: Gtk.Widget, _event: Any) -> bool:
        self.hide()
        return True

    def _build_ui(self) -> None:
        hbar = Gtk.HeaderBar()
        hbar.set_show_close_button(True)
        hbar.set_title("Tchiko RC")
        hbar.set_subtitle("Encrypted Remote Control")
        hbar.get_style_context().add_class("tchiko-titlebar")
        self.set_titlebar(hbar)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        root.get_style_context().add_class("tchiko-root")
        root.set_margin_start(22)
        root.set_margin_end(22)
        root.set_margin_top(18)
        root.set_margin_bottom(20)

        # ── Connection status card ───────────────────────────────────────────
        self.status_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.status_card.get_style_context().add_class("tchiko-card")
        self.status_card.get_style_context().add_class("tchiko-card-pad")

        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.status_dot = Gtk.Label(xalign=0.0)
        self.status_dot.set_markup(f"<span foreground='{ui.TEXT_MUTED}'>●</span>")
        top_row.pack_start(self.status_dot, False, False, 0)

        st_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self.status_title = ui.label("Waiting for Tchiko RC", "tchiko-row-title")
        self.status_sub = ui.label("Single encrypted connection · ECDH P-256 + AES-256-GCM", "dim")
        self.status_sub.set_ellipsize(Pango.EllipsizeMode.END)
        st_text.pack_start(self.status_title, False, False, 0)
        st_text.pack_start(self.status_sub, False, False, 0)
        top_row.pack_start(st_text, True, True, 0)
        self.status_card.pack_start(top_row, False, False, 0)

        self.conn_controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.safety_lbl = Gtk.Label(xalign=0.0)
        self.conn_controls.pack_start(self.safety_lbl, True, True, 0)

        self.disconnect_btn = Gtk.Button(label="Disconnect")
        self.disconnect_btn.get_style_context().add_class("tchiko-btn")
        self.disconnect_btn.connect("clicked", lambda *_: self.service.disconnect_active())
        self.conn_controls.pack_end(self.disconnect_btn, False, False, 0)

        self.unpair_btn = Gtk.Button(label="Unpair")
        self.unpair_btn.get_style_context().add_class("tchiko-btn")
        self.unpair_btn.connect("clicked", self._on_unpair_clicked)
        self.conn_controls.pack_end(self.unpair_btn, False, False, 0)

        self.conn_controls.set_no_show_all(True)
        self.status_card.pack_start(self.conn_controls, False, False, 0)
        root.pack_start(self.status_card, False, False, 0)

        # ── Tchiko Sigil card ────────────────────────────────────────────────
        sigil_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        sigil_card.get_style_context().add_class("tchiko-card")
        sigil_card.get_style_context().add_class("tchiko-card-pad")

        sigil_head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        sigil_head.pack_start(ui.label("TCHIKO SIGIL  ·  ONE-STEP PAIR", "caption"), True, True, 0)
        self.ttl_lbl = ui.label("", "dim", xalign=1.0)
        sigil_head.pack_end(self.ttl_lbl, False, False, 0)
        sigil_card.pack_start(sigil_head, False, False, 0)

        self.sigil_image = Gtk.Image()
        self.sigil_image.set_halign(Gtk.Align.CENTER)
        sigil_card.pack_start(self.sigil_image, False, False, 0)

        self.ttl_bar = Gtk.ProgressBar()
        self.ttl_bar.set_fraction(1.0)
        sigil_card.pack_start(self.ttl_bar, False, False, 0)

        hint = ui.label(
            "Open the address below in your phone or browser and scan this Tchiko Sigil. "
            "Each sigil is single-use and pairs one device at a time.",
            "dim",
            xalign=0.5,
            wrap=True,
        )
        hint.set_justify(Gtk.Justification.CENTER)
        sigil_card.pack_start(hint, False, False, 0)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_row.set_halign(Gtk.Align.CENTER)

        self.refresh_btn = Gtk.Button(label="New Sigil")
        self.refresh_btn.get_style_context().add_class("tchiko-btn")
        self.refresh_btn.connect("clicked", lambda *_: self.regenerate_sigil())
        btn_row.pack_start(self.refresh_btn, False, False, 0)

        self.copy_link_btn = Gtk.Button(label="Copy One-Step Link")
        self.copy_link_btn.get_style_context().add_class("tchiko-primary")
        self.copy_link_btn.connect("clicked", self._on_copy_one_step_link)
        btn_row.pack_start(self.copy_link_btn, False, False, 0)

        sigil_card.pack_start(btn_row, False, False, 0)
        root.pack_start(sigil_card, False, False, 0)

        # ── Address card ─────────────────────────────────────────────────────
        addr_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        addr_card.get_style_context().add_class("tchiko-card")
        addr_card.get_style_context().add_class("tchiko-card-pad")

        addr_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        addr_text.pack_start(ui.label("WEB APP ADDRESS", "caption"), False, False, 0)
        self.url_lbl = ui.label("", "tchiko-code-text", selectable=True)
        self.url_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        addr_text.pack_start(self.url_lbl, False, False, 0)
        addr_card.pack_start(addr_text, True, True, 0)

        self.copy_url_btn = ui.icon_button("edit-copy-symbolic", "Copy URL")
        self.copy_url_btn.connect("clicked", self._on_copy_url)
        addr_card.pack_end(self.copy_url_btn, False, False, 0)
        root.pack_start(addr_card, False, False, 0)

        self.add(root)

    # ── Lifecycle & rendering ────────────────────────────────────────────────
    def _on_show(self, *_args: Any) -> None:
        self.service.start()
        self._ensure_sigil()
        self.refresh_status(self.service.status_snapshot())
        if self._tick_id is None:
            self._tick_id = GLib.timeout_add(500, self._on_tick)

    def _on_hide(self, *_args: Any) -> None:
        if self._tick_id is not None:
            GLib.source_remove(self._tick_id)
            self._tick_id = None

    def _ensure_sigil(self) -> None:
        session = self.service.get_or_create_pairing()
        if session is not self._current_session:
            self._current_session = session
            self._render_sigil(session)

    def regenerate_sigil(self) -> None:
        session = self.service.new_pairing_session()
        self._current_session = session
        self._render_sigil(session)
        self._update_countdown()

    def _render_sigil(self, session: PairingSession) -> None:
        logical = 250
        scale = max(1, self.get_scale_factor())
        svg_bytes = session.svg(size=logical * scale).encode("utf-8")
        loader = GdkPixbuf.PixbufLoader.new_with_type("svg")
        loader.write(svg_bytes)
        loader.close()
        pixbuf = loader.get_pixbuf()
        if pixbuf is not None:
            ui.set_hidpi_pixbuf(self.sigil_image, pixbuf, logical)

    def _on_tick(self) -> bool:
        if not self.get_visible():
            self._tick_id = None
            return False
        self._update_countdown()
        return True

    def _update_countdown(self) -> None:
        session = self._current_session
        if session is None or not session.active:
            # Automatically mint a fresh sigil once the old one expires or gets consumed.
            self.regenerate_sigil()
            return
        rem = session.remaining_sec
        self.ttl_bar.set_fraction(max(0.0, min(1.0, rem / PAIR_TTL_SEC)))
        self.ttl_lbl.set_text(f"{int(round(rem))}s")

    def refresh_status(self, snapshot: Dict[str, Any]) -> None:
        """Update the UI from a `RemoteControlService.status_snapshot()` dict (main-thread safe)."""
        GLib.idle_add(self._apply_status, snapshot)

    def _apply_status(self, snapshot: Dict[str, Any]) -> bool:
        self.url_lbl.set_text(snapshot.get("primary_url", ""))
        connected = bool(snapshot.get("connected"))
        paired = bool(snapshot.get("paired"))

        ctx = self.status_card.get_style_context()
        ctx.remove_class("tchiko-hero-ok")
        ctx.remove_class("tchiko-hero-review")

        if connected:
            ctx.add_class("tchiko-hero-ok")
            dev = snapshot.get("device_name") or "Remote Browser"
            ip = snapshot.get("peer_ip") or ""
            code = snapshot.get("safety_code") or ""
            self.status_dot.set_markup(f"<span foreground='{ui.SUCCESS}'>●</span>")
            self.status_title.set_text(f"Connected · {dev}")
            self.status_sub.set_text(f"{ip} · End-to-end encrypted channel active")
            self.safety_lbl.set_markup(
                f"<span size='small' foreground='{ui.TEXT_MUTED}'>SAFETY CODE  </span>"
                f"<span font_family='{ui.PANGO_MONO}' weight='bold' foreground='{ui.TEXT}'>"
                f"{html.escape(code)}</span>"
            )
            self.disconnect_btn.show()
            self.unpair_btn.show()
            self.conn_controls.set_no_show_all(False)
            self.conn_controls.show_all()
            self.conn_controls.set_no_show_all(True)
        elif paired:
            dev = snapshot.get("device_name") or "Paired device"
            self.status_dot.set_markup(f"<span foreground='{ui.WARNING}'>●</span>")
            self.status_title.set_text(f"Paired · {dev} (offline)")
            self.status_sub.set_text("Will reconnect automatically, or scan a new sigil to replace it.")
            self.safety_lbl.set_markup(
                f"<span size='small' foreground='{ui.TEXT_MUTED}'>1 device paired</span>"
            )
            self.conn_controls.set_no_show_all(False)
            self.conn_controls.show_all()
            self.disconnect_btn.hide()
            self.conn_controls.set_no_show_all(True)
        else:
            self.status_dot.set_markup(f"<span foreground='{ui.TEXT_MUTED}'>●</span>")
            self.status_title.set_text("Ready to pair")
            self.status_sub.set_text("Single encrypted connection · ECDH P-256 + AES-256-GCM")
            self.conn_controls.hide()

        if self._current_session is not None and self._current_session.used and self.get_visible():
            self.regenerate_sigil()
        return False

    # ── Actions ──────────────────────────────────────────────────────────────
    def _on_copy_url(self, btn: Gtk.Button) -> None:
        url = self.service.primary_url()
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(url, -1)
        ui.flash_button_icon(btn)

    def _on_copy_one_step_link(self, _btn: Gtk.Button) -> None:
        self._ensure_sigil()
        if self._current_session is None:
            return
        link = f"{self.service.primary_url()}/#pair={self._current_session.pair_fragment()}"
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(link, -1)
        self.copy_link_btn.set_label("Copied!")
        GLib.timeout_add(1600, lambda: (self.copy_link_btn.set_label("Copy One-Step Link"), False)[1])

    def _on_unpair_clicked(self, *_args: Any) -> None:
        self.service.revoke_pairing()
        self.regenerate_sigil()
