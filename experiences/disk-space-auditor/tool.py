#!/usr/bin/env python3
"""Tchiko Experience Tool: Disk & Directory Space Auditor."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _dir_size_shallow(root: Path) -> List[Tuple[int, str]]:
    items: List[Tuple[int, str]] = []
    try:
        for child in root.iterdir():
            try:
                if child.is_symlink():
                    continue
                if child.is_file():
                    items.append((child.stat().st_size, child.name))
                elif child.is_dir():
                    total = 0
                    for dirpath, _dirs, files in os.walk(child, followlinks=False):
                        for fn in files:
                            try:
                                total += os.path.getsize(os.path.join(dirpath, fn))
                            except OSError:
                                pass
                    items.append((total, child.name + "/"))
            except OSError:
                continue
    except OSError:
        pass
    items.sort(reverse=True)
    return items[:10]


def run(params: Dict[str, Any], dry_run: bool = False) -> Dict[str, Any]:
    target = Path(os.path.expanduser(str(params.get("path") or "~"))).resolve()
    if dry_run:
        return {"ok": True, "summary": f"Dry-run OK: would audit disk usage for {target}."}
    if not target.exists():
        return {"ok": False, "summary": f"Path does not exist: {target}"}

    du = shutil.disk_usage(str(target))
    pct = round((du.used / du.total) * 100.0, 1) if du.total else 0.0
    used_gb = round(du.used / (1024**3), 1)
    total_gb = round(du.total / (1024**3), 1)
    top = _dir_size_shallow(target)
    lines = [f"{round(sz / (1024**2), 1):>8.1f} MB  {name}" for sz, name in top]
    return {
        "ok": True,
        "summary": f"{target}: {used_gb}/{total_gb} GB used ({pct}%).",
        "details": "\n".join(lines) if lines else "(empty directory)",
    }


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
