"""Tchiko RC — secure remote control of the Tchiko desktop from a browser.

Modules:

- `crypto`      ECDH P-256, HKDF-SHA256, AES-256-GCM and the paired secure channel.
- `sigil`       The Tchiko Sigil: the circular pairing pattern (payload, Reed-Solomon, drawing).
- `server`      Minimal HTTPS + WebSocket server (stdlib asyncio + ssl) that serves `rc/`.
- `service`     The remote-control session: handshake, single connection, engine bridge.
- `pair_window` GTK window that shows the sigil and the connected device.
"""

from __future__ import annotations

PROTOCOL_VERSION = 1
