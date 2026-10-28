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
from tchiko.svg_ghost_renderer import SvgGhostRenderer
from tchiko.system_tools import LinuxSystemToolkit


def run_self_test() -> int:
    """Verify ConfigManager, LinuxSystemToolkit, AgentEngine, and GdkPixbuf rendering."""
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
    for mood in ("love", "happy", "roar", "executing", "sleepy", "thinking"):
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
    """Coordinates the Floating Tchiko Companion, Quick Input Bubble, Chat Window, and Settings."""

    def __init__(self, open_chat: bool = False, open_settings: bool = False) -> None:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import GLib, Gtk

        from tchiko.assistant_window import TchikoAssistantWindow
        from tchiko.ghost_widget import FloatingGhostWidget
        from tchiko.settings_window import TchikoSettingsWindow

        self.Gtk = Gtk
        self.GLib = GLib

        self.config = ConfigManager()
        self.toolkit = LinuxSystemToolkit(self.config)
        self.engine = TchikoAgentEngine(self.config, self.toolkit)

        self.settings_win = TchikoSettingsWindow(self.config)
        self.assistant_win = TchikoAssistantWindow(
            config=self.config,
            toolkit=self.toolkit,
            engine=self.engine,
            on_open_settings=self.show_settings,
            on_ghost_state=self.set_ghost_state,
        )
        self.ghost_win = FloatingGhostWidget(
            config=self.config,
            on_toggle_chat=self.toggle_chat,
            on_open_settings=self.show_settings,
            on_quick_command=self.run_inline_prompt,
            on_inline_prompt=self.run_inline_prompt,
            on_quit=self.quit,
        )

        # Connect live streaming from AssistantWindow -> FloatingGhostWidget's talking bubble!
        self.assistant_win.set_bubble_listener(self.ghost_win.show_speech_bubble)

        self.ghost_win.show_all()
        self.ghost_win.present()
        if open_chat:
            self.assistant_win.show_all()
        if open_settings:
            self.settings_win.show_all()

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

    def run_inline_prompt(self, prompt: str) -> None:
        """Execute prompt from the quick-input bar below Tchiko and reply in the talking bubble."""
        self.assistant_win.submit_inline_prompt(prompt)

    def set_ghost_state(self, state: str, speech: Optional[str] = None) -> None:
        self.ghost_win.set_agent_state(state, speech)

    def quit(self) -> None:
        self.Gtk.main_quit()

    def run(self) -> None:
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        self.Gtk.main()


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
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()

    app = TchikoApplication(open_chat=args.open_chat, open_settings=args.open_settings)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
