#!/usr/bin/env bash
# Launch Tchiko Assistant (Floating BoopFace + Antigravity SDK Desktop UI)
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOG_DIR="$SCRIPT_DIR/logs"
LOG_FILE="${TCHIKO_LOG_FILE:-$LOG_DIR/tchiko.log}"
mkdir -p "$LOG_DIR"

# Stream unbuffered stdout & stderr to both terminal and log file
export PYTHONUNBUFFERED=1
exec > >(tee -a "$LOG_FILE") 2>&1

echo ""
echo "=================================================================="
echo "[$(date -Iseconds)] Launching Tchiko Assistant (args: $*)"
echo "Log file: $LOG_FILE"
echo "=================================================================="

export DISPLAY="${DISPLAY:-:0}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
# Force GDK x11 backend fallback if needed so window positioning & always-on-top work across Ubuntu Wayland/X11
export GDK_BACKEND="${GDK_BACKEND:-x11,wayland}"

exec /usr/bin/python3 "$SCRIPT_DIR/main.py" "$@"
