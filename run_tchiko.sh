#!/usr/bin/env bash
# Launch Tchiko Assistant (Floating SVG Ghost + Antigravity SDK Desktop UI)
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export DISPLAY="${DISPLAY:-:0}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
# Force GDK x11 backend fallback if needed so window positioning & always-on-top work across Ubuntu Wayland/X11
export GDK_BACKEND="${GDK_BACKEND:-x11,wayland}"

exec /usr/bin/python3 "$SCRIPT_DIR/main.py" "$@"
