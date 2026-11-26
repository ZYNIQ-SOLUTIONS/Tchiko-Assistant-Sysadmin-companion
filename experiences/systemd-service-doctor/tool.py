#!/usr/bin/env python3
"""Tchiko Experience Tool: Systemd Service Doctor."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from typing import Any, Dict


def run(params: Dict[str, Any], dry_run: bool = False) -> Dict[str, Any]:
    unit = re.sub(r"[^A-Za-z0-9_.@-]", "", str(params.get("unit") or "").strip())
    if dry_run:
        return {"ok": True, "summary": f"Dry-run OK: would audit systemd unit ({unit or 'all failed units'})."}

    if not shutil.which("systemctl"):
        return {"ok": False, "summary": "`systemctl` is not installed on this host."}

    if not unit:
        sys_p = subprocess.run(["systemctl", "--failed", "--no-pager", "--plain"], capture_output=True, text=True, timeout=10)
        usr_p = subprocess.run(["systemctl", "--user", "--failed", "--no-pager", "--plain"], capture_output=True, text=True, timeout=10)
        details = f"=== System Failed ===\n{sys_p.stdout.strip()}\n\n=== User Failed ===\n{usr_p.stdout.strip()}"
        return {"ok": True, "summary": "Audited system and user systemd units.", "details": details}

    st = subprocess.run(["systemctl", "status", unit, "--no-pager", "-l"], capture_output=True, text=True, timeout=10)
    if st.returncode != 0 and "could not be found" in (st.stderr + st.stdout).lower():
        st = subprocess.run(["systemctl", "--user", "status", unit, "--no-pager", "-l"], capture_output=True, text=True, timeout=10)
    return {"ok": True, "summary": f"Inspected systemd unit `{unit}` (exit={st.returncode}).", "details": (st.stdout or st.stderr)[:2200]}


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
