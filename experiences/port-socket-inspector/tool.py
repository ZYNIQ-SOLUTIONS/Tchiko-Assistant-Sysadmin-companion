#!/usr/bin/env python3
"""Tchiko Experience Tool: Port & Socket Inspector."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from typing import Any, Dict


def run(params: Dict[str, Any], dry_run: bool = False) -> Dict[str, Any]:
    port = str(params.get("port") or "").strip()
    if dry_run:
        return {"ok": True, "summary": f"Dry-run OK: would inspect listening sockets (port={port or 'all'})."}

    if not shutil.which("ss"):
        return {"ok": False, "summary": "`ss` utility is not available on this host."}

    proc = subprocess.run(["ss", "-tulnp"], capture_output=True, text=True, timeout=10)
    lines = proc.stdout.splitlines()
    if port:
        matched = [ln for ln in lines if f":{port} " in ln or ln.endswith(f":{port}")]
        body = "\n".join(matched[:25]) if matched else f"No process is currently listening on port {port}."
        return {"ok": True, "summary": f"Port {port}: {len(matched)} matching socket(s).", "details": body}

    return {"ok": proc.returncode == 0, "summary": f"Found {max(0, len(lines) - 1)} socket entries.", "details": "\n".join(lines[:30])}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--params", default="{}")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    params = json.loads(args.params) if args.params else {}
    res = run(params if isinstance(params, dict) else {}, dry_run=(args.dry_run or args.self_test))
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
