#!/usr/bin/env python3
"""Container HEALTHCHECK: GET /health on the running Tchiko RC server.

The port and TLS mode are read from the live `main.py --remote` process arguments, so
`docker run <image> --rc-port 9000` or `--rc-no-tls` cannot desync the check. The env
defaults are only a fallback when the process is not found.
"""

import os
import ssl
import sys
import urllib.request
from pathlib import Path


def server_args() -> list:
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            argv = (proc / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        args = [a.decode("utf-8", "replace") for a in argv if a]
        if any(a.endswith("main.py") for a in args) and "--remote" in args:
            return args
    return []


def effective_endpoint() -> tuple:
    port = os.environ.get("TCHIKO_RC_PORT", "8765")
    tls = os.environ.get("TCHIKO_RC_TLS", "1") != "0"
    args = server_args()
    for i, arg in enumerate(args):
        if arg == "--rc-port" and i + 1 < len(args):
            port = args[i + 1]  # argparse keeps the last occurrence; so do we
        elif arg.startswith("--rc-port="):
            port = arg.split("=", 1)[1]
        elif arg == "--rc-no-tls":
            tls = False
    return port, tls


port, tls = effective_endpoint()
scheme = "https" if tls else "http"
ctx = ssl._create_unverified_context() if tls else None

try:
    with urllib.request.urlopen(f"{scheme}://127.0.0.1:{port}/health", context=ctx, timeout=4) as resp:
        sys.exit(0 if resp.status == 200 else 1)
except Exception as exc:  # noqa: BLE001 - any failure means unhealthy
    print(f"unhealthy ({scheme}://127.0.0.1:{port}/health): {exc}", file=sys.stderr)
    sys.exit(1)
