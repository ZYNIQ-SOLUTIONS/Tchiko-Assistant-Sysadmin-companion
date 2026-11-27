#!/bin/sh
# Tchiko Assistant container entrypoint: headless Tchiko RC server.
#
# Environment:
#   TCHIKO_RC_PORT        Listen port inside the container (default 8765)
#   TCHIKO_RC_TLS         1 = HTTPS/WSS with a self-signed cert (default); 0 = plain HTTP/WS,
#                         only behind a TLS-terminating reverse proxy
#   TCHIKO_RC_PUBLIC_URL  URL printed in pairing links, e.g. https://192.168.1.20:8765. Its host
#                         also becomes the certificate SAN (see TCHIKO_RC_SANS).
#   TCHIKO_RC_SANS        Comma-separated certificate SANs (IPs / DNS names). Defaults to the
#                         TCHIKO_RC_PUBLIC_URL host; when set, container IPs are not used.
#   TCHIKO_PERMISSIONS    supervised (default) | autonomous. Applied when the config volume has
#                         no valid settings.json yet (first start, or an unreadable file).
#   GEMINI_API_KEY        Gemini REST backend
#   OLLAMA_HOST           Ollama server, e.g. http://host.docker.internal:11434
#
# Extra arguments are appended to `main.py --remote`. A first argument that is not an
# option (e.g. `bash`) is executed as-is instead.
set -eu

case "${1:-}" in
  ""|-*) ;;
  *) exec "$@" ;;
esac

# ── First start / unreadable settings: seed the permission mode (fail closed) ──────────────
settings=/app/config/settings.json
if [ -f "$settings" ] && ! python -c 'import json, sys; json.load(open(sys.argv[1]))' "$settings" 2>/dev/null; then
  backup="$settings.corrupt-$(date +%Y%m%d%H%M%S)"
  mv "$settings" "$backup"
  echo "[tchiko] settings.json was unreadable; moved it to $backup and re-seeding defaults."
fi
if [ ! -f "$settings" ]; then
  case "${TCHIKO_PERMISSIONS:-supervised}" in
    autonomous)
      echo "[tchiko] First start: AUTONOMOUS permissions (agent commands run without review)."
      ;;
    *)
      python - <<'PY'
import sys

sys.path.insert(0, "/app")
from tchiko.config_manager import ConfigManager

ConfigManager().set_all_permissions(False)
PY
      echo "[tchiko] First start: supervised permissions (agent commands that change the system need approval in Tchiko RC)."
      ;;
  esac
fi

# ── TLS certificate names: match the public address instead of the bridge IP ──────────────
if [ -z "${TCHIKO_RC_SANS:-}" ] && [ -n "${TCHIKO_RC_PUBLIC_URL:-}" ]; then
  TCHIKO_RC_SANS="$(python -c 'import sys, urllib.parse as u; print(u.urlsplit(sys.argv[1]).hostname or "")' "$TCHIKO_RC_PUBLIC_URL" 2>/dev/null || true)"
  export TCHIKO_RC_SANS
fi

set -- --remote --rc-port "${TCHIKO_RC_PORT:-8765}" --sigil-out "${TCHIKO_SIGIL_OUT:-/tmp/tchiko_sigil.svg}" "$@"
if [ "${TCHIKO_RC_TLS:-1}" = "0" ]; then
  set -- "$@" --rc-no-tls
fi

exec python /app/main.py "$@"
