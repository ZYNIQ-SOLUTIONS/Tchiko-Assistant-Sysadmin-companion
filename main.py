#!/usr/bin/env python3
"""Tchiko Assistant — Main Application Entry Point.

Launches the Floating SVG Companion on Ubuntu Linux with:
- Fast inline quick-input bar below the Tchiko SVG + talking response bubble above Tchiko
- Full Antigravity 2.0-styled Chat & System Studio window (`💬`)
- Tchiko Settings & Linux System Permissions window (`⚙️`)
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
from typing import Optional

# Ensure XWayland/X11 backend is preferred on Ubuntu GNOME Wayland so that
# frameless window positioning (`move(x, y)`) and `set_keep_above(True)` work reliably.
os.environ.setdefault("GDK_BACKEND", "x11,wayland")
os.environ.setdefault("DISPLAY", ":0")

from tchiko.agent_engine import TchikoAgentEngine
from tchiko.config_manager import ConfigManager, PROJECT_ROOT
from tchiko.system_tools import LinuxSystemToolkit


def run_self_test() -> int:
    """Verify ConfigManager, LinuxSystemToolkit, AgentEngine, and GdkPixbuf rendering."""
    from tchiko.svg_ghost_renderer import SvgGhostRenderer

    print("🔍 [1/4] Testing ConfigManager & Permission Policies...")
    cfg = ConfigManager()
    cfg.set_all_permissions(True)
    assert cfg.is_all_permissions_approved() is True
    allowed, reason = cfg.is_command_allowed("uname -a")
    assert allowed is True, reason
    print(f"    ✓ Master permissions approved: {cfg.is_all_permissions_approved()} ({reason})")

    print("🔍 [2/4] Testing LinuxSystemToolkit on Ubuntu...")
    toolkit = LinuxSystemToolkit(cfg)
    telemetry = toolkit.get_system_telemetry()
    print(
        f"    ✓ Host: {telemetry['hostname']} | OS: {telemetry['distro']} | "
        f"RAM: {telemetry['ram_used_gb']}/{telemetry['ram_total_gb']} GB"
    )
    cmd_res = toolkit.run_shell_command("echo 'Tchiko Linux Execution OK'")
    assert cmd_res.ok is True and "Tchiko Linux Execution OK" in cmd_res.output
    print(f"    ✓ Shell command execution verified ({cmd_res.duration_ms}ms)")

    print("🔍 [3/4] Testing TchikoAgentEngine...")
    engine = TchikoAgentEngine(cfg, toolkit)
    print(f"    ✓ Engine status: {engine.get_engine_status_label()}")

    print("🔍 [4/4] Testing SvgGhostRenderer Cairo + SVG + GdkPixbuf pipeline...")
    renderer = SvgGhostRenderer()
    renderer.step(0.5)
    pixbuf = renderer.render_to_pixbuf(220, 220, theme_name="phantom_cyan")
    assert pixbuf is not None and pixbuf.get_width() == 220 and pixbuf.get_height() == 220
    preview_path = PROJECT_ROOT / "assets" / "tchiko_preview.png"
    pixbuf.savev(str(preview_path), "png", [], [])
    assert preview_path.exists() and preview_path.stat().st_size > 1000

    # Export exact desktop assistant SVG files for logo & Netlify landing page
    landing_assets = PROJECT_ROOT / "landing" / "assets"
    landing_assets.mkdir(parents=True, exist_ok=True)
    logo_svg_path = PROJECT_ROOT / "assets" / "tchiko-logo.svg"
    renderer.set_emotion("idle")
    renderer.export_to_svg(str(logo_svg_path), width=360, height=340, theme_name="phantom_cyan")
    renderer.export_to_svg(str(landing_assets / "tchiko-logo.svg"), width=360, height=340, theme_name="phantom_cyan")
    for mood in ("happy", "excited", "roar", "executing", "sleepy", "thinking"):
        r_mood = SvgGhostRenderer()
        r_mood.set_emotion(mood, duration=5.0)
        r_mood.step(0.4)
        for out_dir in (PROJECT_ROOT / "assets", landing_assets):
            r_mood.export_to_svg(
                str(out_dir / f"tchiko-{mood}.svg"),
                width=360,
                height=340,
                theme_name="phantom_cyan",
            )
    print(f"    ✓ Exported exact desktop assistant SVGs to: {logo_svg_path} & {landing_assets}")
    print("\n✅ All Tchiko Assistant self-tests passed!")
    return 0


class TchikoApplication:
    """Coordinates the Floating Tchiko Companion, Quick Input Bubble, Chat Window, Settings, and RC."""

    def __init__(
        self,
        open_chat: bool = False,
        open_settings: bool = False,
        open_remote: bool = False,
        rc_port: int = 8765,
    ) -> None:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import GLib, Gtk

        from tchiko.assistant_window import TchikoAssistantWindow
        from tchiko.ghost_widget import FloatingGhostWidget
        from tchiko.remote.pair_window import TchikoPairWindow
        from tchiko.remote.service import RemoteControlService
        from tchiko.settings_window import TchikoSettingsWindow
        from tchiko.watchdog import SystemWatchdog

        self.Gtk = Gtk
        self.GLib = GLib

        self.config = ConfigManager()
        self.toolkit = LinuxSystemToolkit(self.config)
        self.engine = TchikoAgentEngine(self.config, self.toolkit)

        self.remote_service = RemoteControlService(
            config=self.config,
            toolkit=self.toolkit,
            engine=self.engine,
            port=rc_port,
            on_status_change=self._on_remote_status,
            on_remote_mood=self._on_remote_mood,
        )
        self.pair_win = TchikoPairWindow(self.remote_service)

        self.settings_win = TchikoSettingsWindow(self.config)
        self.assistant_win = TchikoAssistantWindow(
            config=self.config,
            toolkit=self.toolkit,
            engine=self.engine,
            on_open_settings=self.show_settings,
            on_ghost_state=self.set_ghost_state,
            on_open_remote=self.show_remote,
        )
        self.ghost_win = FloatingGhostWidget(
            config=self.config,
            on_toggle_chat=self.toggle_chat,
            on_open_settings=self.show_settings,
            on_quick_command=self.run_inline_prompt,
            on_inline_prompt=self.run_inline_prompt,
            on_quit=self.quit,
            on_open_remote=self.show_remote,
        )

        # Connect live streaming from AssistantWindow -> FloatingGhostWidget's talking bubble!
        self.assistant_win.set_bubble_listener(self.ghost_win.show_speech_bubble)

        # Start proactive background anomaly watchdog
        def _on_watchdog_alert(msg: str) -> None:
            self.GLib.idle_add(self._deliver_watchdog_alert, msg)
            self.remote_service.notify_watchdog_alert(msg)

        self.watchdog = SystemWatchdog(self.toolkit, on_anomaly=_on_watchdog_alert)
        self.watchdog.start()

        # Start the encrypted RC server so previously paired clients reconnect seamlessly.
        try:
            self.remote_service.start()
        except Exception as exc:
            print(f"[Tchiko RC] Warning: failed to auto-start remote server: {exc}", file=sys.stderr)

        self.ghost_win.show_all()
        self.ghost_win.present()
        if open_chat:
            self.assistant_win.show_all()
        if open_settings:
            self.settings_win.show_all()
        if open_remote:
            self.show_remote()

    def toggle_chat(self) -> None:
        if self.assistant_win.get_visible():
            self.assistant_win.hide()
        else:
            gx, gy = self.ghost_win.get_position()
            self.assistant_win.move(max(40, gx - 520), max(40, gy))
            self.assistant_win.show_all()
            self.assistant_win.present()

    def show_settings(self) -> None:
        self.settings_win.show_all()
        self.settings_win.present()

    def show_remote(self) -> None:
        self.pair_win.show_all()
        self.pair_win.present()

    def _on_remote_status(self, snapshot: dict) -> None:
        if hasattr(self, "pair_win"):
            self.pair_win.refresh_status(snapshot)
        if hasattr(self, "assistant_win"):
            connected = bool(snapshot.get("connected"))
            device = str(snapshot.get("device_name") or "")
            self.GLib.idle_add(self.assistant_win.set_remote_connected, connected, device)

    def _on_remote_mood(self, mood: str) -> None:
        if hasattr(self, "ghost_win"):
            self.GLib.idle_add(self.set_ghost_state, mood, None)

    def run_inline_prompt(self, prompt: str) -> None:
        """Execute prompt from the quick-input bar below Tchiko and reply in the talking bubble."""
        self.assistant_win.submit_inline_prompt(prompt)

    def set_ghost_state(self, state: str, speech: Optional[str] = None) -> None:
        self.ghost_win.set_agent_state(state, speech)

    def _deliver_watchdog_alert(self, msg: str) -> bool:
        self.ghost_win.set_agent_state("alert")
        self.ghost_win.show_speech_bubble(msg, is_markup=False, auto_hide_sec=14)
        return False

    def quit(self) -> None:
        if hasattr(self, "remote_service"):
            self.remote_service.stop()
        if hasattr(self, "watchdog"):
            self.watchdog.stop()
        self.Gtk.main_quit()

    def run(self) -> None:
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        self.Gtk.main()


def run_remote_headless(
    port: int = 8765,
    use_tls: bool = True,
    sigil_out: Optional[str] = None,
    public_url: Optional[str] = None,
) -> int:
    """Run Tchiko RC headless (no GTK display required) for servers / SSH sessions / containers.

    `public_url` (e.g. `https://my-host:8765`) replaces the auto-detected LAN address in the
    printed links; inside a container the detected address is the unreachable bridge IP.
    While no device is paired, an expired one-time pairing link is re-issued automatically.
    """
    import time
    from pathlib import Path

    from tchiko.remote.service import PAIR_TTL_SEC, PairingSession, RemoteControlService

    cfg = ConfigManager()
    toolkit = LinuxSystemToolkit(cfg)
    engine = TchikoAgentEngine(cfg, toolkit)

    last_state = {"connected": None, "safety_code": ""}

    def _on_status(snap: dict) -> None:
        conn = bool(snap.get("connected"))
        code = str(snap.get("safety_code") or "")
        prev_conn = last_state["connected"]
        if conn != prev_conn or code != last_state["safety_code"]:
            last_state["connected"] = conn
            last_state["safety_code"] = code
            if conn:
                dev = snap.get("device_name") or "Remote Browser"
                ip = snap.get("peer_ip") or ""
                print(f"\n[Tchiko RC] Connected: {dev} ({ip})  |  Safety Code: {code}", flush=True)
            elif prev_conn is True:
                print("\n[Tchiko RC] Client disconnected.", flush=True)

    service = RemoteControlService(
        config=cfg,
        toolkit=toolkit,
        engine=engine,
        port=port,
        use_tls=use_tls,
        on_status_change=_on_status,
    )
    bound = service.start()
    primary = (public_url or "").rstrip("/") or service.primary_url()
    out_path = Path(sigil_out) if sigil_out else (PROJECT_ROOT / "config" / "tchiko_sigil.svg")

    def _issue_pairing() -> PairingSession:
        session = service.new_pairing_session()
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(session.svg(size=420), encoding="utf-8")
            sigil_note = f"{out_path} (valid for {int(PAIR_TTL_SEC)}s, single-use)"
        except OSError as exc:
            sigil_note = f"not written ({exc}); use the One-Step Link"
        print(f"  One-Step Link: {primary}/#pair={session.pair_fragment()}")
        print(f"  Tchiko Sigil : {sigil_note}", flush=True)
        return session

    print(f"Tchiko RC listening on port {bound} ({'HTTPS/WSS' if use_tls else 'HTTP/WS'})")
    if public_url:
        print(f"  Public URL   : {primary}")
    for url in service.urls():
        print(f"  Web App      : {url}")
    session: Optional[PairingSession]
    if service.status_snapshot().get("paired"):
        print("  Paired device on record: reconnect from it. Tap Unpair in the web app to pair a new one.")
        session = None
    else:
        session = _issue_pairing()
    print("Press Ctrl+C to stop.", flush=True)

    stop_flag = {"stop": False}

    def _handle_sig(_signum: int, _frame: object) -> None:
        stop_flag["stop"] = True

    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    try:
        ticks = 0
        while not stop_flag["stop"]:
            time.sleep(0.5)
            ticks += 1
            if session is not None and session.active:
                continue
            if session is None and ticks % 4:
                continue  # idle while paired: poll the pairing state every 2s
            snap = service.status_snapshot()
            if snap.get("paired") or snap.get("connected"):
                session = None
                continue
            if session is None:
                print("\n[Tchiko RC] No device paired (unpaired); issuing a new pairing link.")
            else:
                print("\n[Tchiko RC] Pairing link expired; issuing a new one.")
            session = _issue_pairing()
    finally:
        service.stop()
        try:
            if out_path.exists() and sigil_out is None:
                out_path.unlink()
        except OSError:
            pass
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Tchiko Assistant — Floating Companion")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run automated self-tests and render preview PNG without opening GUI",
    )
    parser.add_argument(
        "--open-chat",
        action="store_true",
        help="Open the full Tchiko Chat Canvas window alongside the floating companion on startup",
    )
    parser.add_argument(
        "--open-settings",
        action="store_true",
        help="Open the Tchiko Settings & Permissions window on startup",
    )
    parser.add_argument(
        "--open-remote",
        action="store_true",
        help="Open the Tchiko RC pairing window on startup",
    )
    parser.add_argument(
        "--remote",
        action="store_true",
        help="Run Tchiko RC in headless server mode without launching the GTK desktop UI",
    )
    parser.add_argument(
        "--rc-port",
        type=int,
        default=8765,
        help="TCP port for the Tchiko RC HTTPS/WSS server (default: 8765)",
    )
    parser.add_argument(
        "--rc-no-tls",
        action="store_true",
        help="Disable TLS in headless --remote mode (only for localhost/reverse-proxy setups)",
    )
    parser.add_argument(
        "--rc-public-url",
        type=str,
        default=os.environ.get("TCHIKO_RC_PUBLIC_URL") or None,
        help="Externally reachable base URL printed in pairing links, e.g. https://host:8765 "
        "(env: TCHIKO_RC_PUBLIC_URL; useful behind NAT, Docker, or a reverse proxy)",
    )
    parser.add_argument(
        "--sigil-out",
        type=str,
        default=None,
        help="Optional path to write the Tchiko Sigil SVG in --remote mode",
    )
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()

    if args.remote:
        return run_remote_headless(
            port=args.rc_port,
            use_tls=not args.rc_no_tls,
            sigil_out=args.sigil_out,
            public_url=args.rc_public_url,
        )

    app = TchikoApplication(
        open_chat=args.open_chat,
        open_settings=args.open_settings,
        open_remote=args.open_remote,
        rc_port=args.rc_port,
    )
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
