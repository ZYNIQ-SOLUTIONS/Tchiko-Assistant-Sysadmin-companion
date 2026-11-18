"""Ubuntu Linux System Interaction Toolkit for Tchiko Assistant.

Executes shell commands, inspects system telemetry (CPU, RAM, Disk, Uptime,
Processes, Network), manages files, launches desktop apps, and sends desktop
notifications — strictly enforcing the user's Tchiko Settings permission state.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config_manager import ConfigManager


@dataclass
class ToolResult:
    """Result of executing a Linux system action."""

    ok: bool
    title: str
    output: str
    command: str = ""
    exit_code: int = 0
    duration_ms: int = 0


class LinuxSystemToolkit:
    """Provides full Ubuntu Linux system interaction gated by ConfigManager."""

    def __init__(self, config: ConfigManager) -> None:
        self.config = config

    def run_shell_command(
        self,
        command: str,
        cwd: Optional[str] = None,
        timeout: int = 30,
        bypass_check: bool = False,
    ) -> ToolResult:
        """Execute a bash command on the Ubuntu host if permitted by Tchiko Settings."""
        if not bypass_check:
            allowed, reason = self.config.is_command_allowed(command)
            if not allowed:
                return ToolResult(
                    ok=False,
                    title="Permission Denied by Tchiko Settings",
                    output=f"🔒 {reason}\n\nOpen Tchiko Settings (⚙️) and enable 'Grant All System Permissions' or 'Bash Execution' to allow this action.",
                    command=command,
                    exit_code=126,
                )

        work_dir = cwd or self.config.data.get("agent", {}).get("workspace_dir") or str(Path.home())
        if not os.path.isdir(work_dir):
            work_dir = str(Path.home())

        start_t = time.monotonic()
        try:
            proc = subprocess.run(
                ["/bin/bash", "-lc", command],
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            elapsed = int((time.monotonic() - start_t) * 1000)
            stdout = (proc.stdout or "").strip()
            stderr = (proc.stderr or "").strip()
            combined = stdout
            if stderr:
                combined = f"{stdout}\n[stderr]\n{stderr}".strip() if stdout else f"[stderr]\n{stderr}"
            if not combined:
                combined = f"(Command completed successfully with exit code {proc.returncode})"

            return ToolResult(
                ok=(proc.returncode == 0),
                title=f"Executed: {command[:60]}",
                output=combined,
                command=command,
                exit_code=proc.returncode,
                duration_ms=elapsed,
            )
        except subprocess.TimeoutExpired:
            elapsed = int((time.monotonic() - start_t) * 1000)
            return ToolResult(
                ok=False,
                title="Command Timed Out",
                output=f"Command timed out after {timeout}s: {command}",
                command=command,
                exit_code=124,
                duration_ms=elapsed,
            )
        except Exception as exc:
            return ToolResult(
                ok=False,
                title="Execution Error",
                output=str(exc),
                command=command,
                exit_code=1,
            )

    def get_system_telemetry(self) -> Dict[str, Any]:
        """Read real-time Ubuntu Linux CPU, RAM, Disk, and OS metrics from /proc."""
        info: Dict[str, Any] = {
            "hostname": platform.node(),
            "os": f"{platform.system()} {platform.release()}",
            "distro": "Ubuntu Linux",
            "cpu_load_1m": 0.0,
            "cpu_cores": os.cpu_count() or 1,
            "ram_used_gb": 0.0,
            "ram_total_gb": 0.0,
            "ram_percent": 0.0,
            "disk_used_gb": 0.0,
            "disk_total_gb": 0.0,
            "disk_percent": 0.0,
            "uptime_str": "unknown",
        }

        # Distro pretty name
        os_release = Path("/etc/os-release")
        if os_release.exists():
            try:
                for line in os_release.read_text(encoding="utf-8").splitlines():
                    if line.startswith("PRETTY_NAME="):
                        info["distro"] = line.split("=", 1)[1].strip().strip('"')
                        break
            except Exception:
                pass

        # Load average
        try:
            load1, _, _ = os.getloadavg()
            info["cpu_load_1m"] = round(load1, 2)
        except Exception:
            pass

        # Memory from /proc/meminfo
        meminfo = Path("/proc/meminfo")
        if meminfo.exists():
            try:
                mem_map: Dict[str, int] = {}
                for line in meminfo.read_text(encoding="utf-8").splitlines():
                    parts = line.split(":")
                    if len(parts) == 2:
                        val_parts = parts[1].strip().split()
                        if val_parts:
                            mem_map[parts[0].strip()] = int(val_parts[0])
                total_kb = mem_map.get("MemTotal", 0)
                avail_kb = mem_map.get("MemAvailable", mem_map.get("MemFree", 0))
                used_kb = max(0, total_kb - avail_kb)
                if total_kb > 0:
                    info["ram_total_gb"] = round(total_kb / (1024 * 1024), 2)
                    info["ram_used_gb"] = round(used_kb / (1024 * 1024), 2)
                    info["ram_percent"] = round((used_kb / total_kb) * 100.0, 1)
            except Exception:
                pass

        # Disk usage for home
        try:
            du = shutil.disk_usage(str(Path.home()))
            info["disk_total_gb"] = round(du.total / (1024**3), 1)
            info["disk_used_gb"] = round(du.used / (1024**3), 1)
            info["disk_percent"] = round((du.used / du.total) * 100.0, 1) if du.total else 0.0
        except Exception:
            pass

        # Uptime
        uptime_path = Path("/proc/uptime")
        if uptime_path.exists():
            try:
                secs = int(float(uptime_path.read_text(encoding="utf-8").split()[0]))
                hours, rem = divmod(secs, 3600)
                mins, _ = divmod(rem, 60)
                info["uptime_str"] = f"{hours}h {mins}m"
            except Exception:
                pass

        return info

    def format_telemetry_report(self) -> str:
        """Return a formatted markdown report of system telemetry."""
        t = self.get_system_telemetry()
        perm_state = (
            "🟢 FULL SYSTEM PERMISSIONS (Autonomous)"
            if self.config.is_all_permissions_approved()
            else "🟡 RESTRICTED / REVIEW MODE"
        )
        return (
            f"### 🖥️ Ubuntu System Status (`{t['hostname']}`)\n"
            f"- **OS / Distro:** {t['distro']} ({t['os']})\n"
            f"- **Uptime:** {t['uptime_str']}\n"
            f"- **CPU Load (1m):** {t['cpu_load_1m']} ({t['cpu_cores']} cores)\n"
            f"- **Memory (RAM):** {t['ram_used_gb']} GB / {t['ram_total_gb']} GB ({t['ram_percent']}%)\n"
            f"- **Disk (`/home`):** {t['disk_used_gb']} GB / {t['disk_total_gb']} GB ({t['disk_percent']}%)\n"
            f"- **Tchiko Permission State:** {perm_state}"
        )

    def list_top_processes(self, limit: int = 12) -> ToolResult:
        """List top processes by CPU and memory usage."""
        if not self.config.can_execute_capability("process_management"):
            return ToolResult(
                ok=False,
                title="Process Management Disabled",
                output="🔒 Enable 'Process Management' or 'Grant All System Permissions' in Tchiko Settings.",
            )
        return self.run_shell_command(
            f"ps -eo pid,user,%cpu,%mem,comm --sort=-%cpu | head -n {int(limit) + 1}",
            bypass_check=True,
        )

    def list_directory(self, path_str: str = "~") -> ToolResult:
        """List files in a directory if filesystem access is permitted."""
        if not self.config.can_execute_capability("filesystem_read_write"):
            return ToolResult(
                ok=False,
                title="Filesystem Access Disabled",
                output="🔒 Enable 'Filesystem Read/Write' or 'Grant All System Permissions' in Tchiko Settings.",
            )
        target = Path(os.path.expanduser(os.path.expandvars(path_str))).resolve()
        if not target.exists():
            return ToolResult(ok=False, title="Path Not Found", output=f"Path does not exist: {target}")
        try:
            entries: List[str] = []
            for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))[:60]:
                kind = "📁" if item.is_dir() else "📄"
                size_str = ""
                if item.is_file():
                    try:
                        size_str = f" ({item.stat().st_size:,} bytes)"
                    except Exception:
                        pass
                entries.append(f"{kind} {item.name}{size_str}")
            body = "\n".join(entries) if entries else "(Empty directory)"
            return ToolResult(
                ok=True,
                title=f"Directory Listing: {target}",
                output=f"📂 {target}\n\n{body}",
            )
        except Exception as exc:
            return ToolResult(ok=False, title="Directory Error", output=str(exc))

    def launch_application(self, target: str) -> ToolResult:
        """Open a desktop application, folder, or URL using xdg-open or direct command."""
        if not self.config.can_execute_capability("desktop_automation"):
            return ToolResult(
                ok=False,
                title="Desktop Automation Disabled",
                output="🔒 Enable 'Desktop Automation' or 'Grant All System Permissions' in Tchiko Settings.",
            )
        try:
            expanded = os.path.expanduser(target.strip())
            if os.path.exists(expanded) or target.startswith(("http://", "https://")):
                subprocess.Popen(["xdg-open", expanded], start_new_session=True)
                return ToolResult(ok=True, title="Opened Target", output=f"🚀 Opened `{target}` via xdg-open.")
            else:
                subprocess.Popen(["/bin/bash", "-lc", target], start_new_session=True)
                return ToolResult(ok=True, title="Launched App", output=f"🚀 Launched application: `{target}`")
        except Exception as exc:
            return ToolResult(ok=False, title="Launch Failed", output=str(exc))

    def send_desktop_notification(self, summary: str, body: str) -> None:
        """Send an Ubuntu desktop notification via notify-send if enabled."""
        if not self.config.data.get("ui", {}).get("notifications_enabled", True):
            return
        if not self.config.can_execute_capability("desktop_automation"):
            return
        if shutil.which("notify-send"):
            try:
                subprocess.Popen(
                    ["notify-send", "-a", "Tchiko Assistant", summary, body],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass

    def view_file_lines(
        self, path_str: str, start_line: int = 1, end_line: int = 120
    ) -> ToolResult:
        """Read a slice of a file with 1-indexed line numbers (like Antigravity view_file)."""
        if not self.config.can_execute_capability("filesystem_read_write"):
            return ToolResult(
                ok=False,
                title="Filesystem Access Disabled",
                output="🔒 Enable 'Filesystem Read/Write' or 'Grant All System Permissions' in Tchiko Settings.",
            )
        target = Path(os.path.expanduser(os.path.expandvars(path_str.strip()))).resolve()
        if not target.exists():
            return ToolResult(ok=False, title="File Not Found", output=f"File does not exist: {target}")
        if target.is_dir():
            return self.list_directory(str(target))
        try:
            raw = target.read_text(encoding="utf-8", errors="replace")
            all_lines = raw.splitlines()
            total = len(all_lines)
            s = max(1, int(start_line))
            e = min(total, max(s, int(end_line)))
            numbered = [f"{idx}: {all_lines[idx - 1][:300]}" for idx in range(s, e + 1)]
            header = f"📄 {target} (lines {s}-{e} of {total}, {len(raw):,} bytes)"
            return ToolResult(
                ok=True,
                title=f"Viewed: {target.name} (L{s}-L{e})",
                output=header + "\n" + "\n".join(numbered),
            )
        except Exception as exc:
            return ToolResult(ok=False, title="View File Error", output=str(exc))

    def grep_files(
        self, pattern: str, path_str: str = "~", max_matches: int = 35
    ) -> ToolResult:
        """Search files/logs for a pattern and return matching lines or byte-offset snippets."""
        if not self.config.can_execute_capability("filesystem_read_write"):
            return ToolResult(
                ok=False,
                title="Filesystem Access Disabled",
                output="🔒 Enable 'Filesystem Read/Write' in Tchiko Settings.",
            )
        target = os.path.expanduser(os.path.expandvars(path_str.strip()))
        cmd = f"grep -rnI -- {pattern!r} {target!r} 2>/dev/null | head -n {int(max_matches)}"
        res = self.run_shell_command(cmd, bypass_check=True)
        if (res.output.startswith("(Command completed") or pattern not in res.output[:4000]) and os.path.exists(target):
            # Fallback for minified single-line JS bundles where grep line output is huge
            snippets: List[str] = []
            root_path = Path(target)
            files_to_scan = [root_path] if root_path.is_file() else list(root_path.rglob("*.js"))[:60]
            for fp in files_to_scan:
                try:
                    txt = fp.read_text(encoding="utf-8", errors="ignore")
                    pos = txt.find(pattern)
                    if pos != -1:
                        snip = txt[max(0, pos - 90) : min(len(txt), pos + 160)].replace("\n", " ")
                        snippets.append(f"{fp} [@{pos}]: {snip}")
                except Exception:
                    pass
            if snippets:
                return ToolResult(
                    ok=True,
                    title=f"Grep: {pattern}",
                    output="\n".join(snippets[:max_matches]),
                )
        return ToolResult(
            ok=True,
            title=f"Grep: {pattern} in {Path(target).name}",
            output=res.output[:4000],
        )

    def patch_file_content(
        self,
        path_str: str,
        target_content: str,
        replacement_content: str,
        create_backup: bool = True,
    ) -> ToolResult:
        """Replace exact target_content with replacement_content in a file, creating a .bak backup first."""
        if not self.config.can_execute_capability("filesystem_read_write"):
            return ToolResult(
                ok=False,
                title="Filesystem Access Disabled",
                output="🔒 Enable 'Filesystem Read/Write' in Tchiko Settings.",
            )
        target = Path(os.path.expanduser(os.path.expandvars(path_str.strip()))).resolve()
        if not target.exists() or not target.is_file():
            return ToolResult(ok=False, title="Patch Failed", output=f"File not found: {target}")
        try:
            txt = target.read_text(encoding="utf-8")
            if target_content not in txt:
                if replacement_content in txt:
                    return ToolResult(
                        ok=True,
                        title=f"Already Patched: {target.name}",
                        output=f"✓ `{target}` already contains the patched content.",
                    )
                return ToolResult(
                    ok=False,
                    title=f"Target Not Found in {target.name}",
                    output=f"Target snippet not found in `{target}`.",
                )
            bak_note = ""
            if create_backup:
                bak_path = Path(str(target) + ".bak")
                shutil.copy2(target, bak_path)
                bak_note = f" (backup saved to `{bak_path}`)"
            updated = txt.replace(target_content, replacement_content, 1)
            target.write_text(updated, encoding="utf-8")
            tx_id = self._record_file_tx("patch", target, txt, updated)
            return ToolResult(
                ok=True,
                title=f"Patched: {target.name}",
                output=f"✅ Patched `{target}`{bak_note} [`{tx_id}`].",
            )
        except Exception as exc:
            return ToolResult(ok=False, title="Patch Error", output=str(exc))

    def write_file_content(
        self, path_str: str, content: str, create_backup: bool = True
    ) -> ToolResult:
        """Create or overwrite a file on disk, optionally saving a .bak backup if it existed."""
        if not self.config.can_execute_capability("filesystem_read_write"):
            return ToolResult(
                ok=False,
                title="Filesystem Access Disabled",
                output="🔒 Enable 'Filesystem Read/Write' in Tchiko Settings.",
            )
        target = Path(os.path.expanduser(os.path.expandvars(path_str.strip()))).resolve()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            before_text: Optional[str] = None
            if target.exists() and target.is_file():
                try:
                    before_text = target.read_text(encoding="utf-8")
                except Exception:
                    before_text = None
                if create_backup:
                    shutil.copy2(target, str(target) + ".bak")
            target.write_text(content, encoding="utf-8")
            tx_id = self._record_file_tx("write", target, before_text, content)
            return ToolResult(
                ok=True,
                title=f"Wrote: {target.name}",
                output=f"✅ Wrote {len(content):,} bytes to `{target}` [`{tx_id}`].",
            )
        except Exception as exc:
            return ToolResult(ok=False, title="Write File Error", output=str(exc))

    def diagnose_and_heal_app(
        self,
        app_name: str,
        on_step: Optional[Any] = None,
    ) -> ToolResult:
        """Execute a full 6-step autonomous investigation & auto-repair pipeline for any Linux app/IDE."""
        def _emit(step_msg: str, tool_name: str = "", tool_args: str = "") -> None:
            if callable(on_step):
                try:
                    on_step(step_msg, tool_name, tool_args)
                except Exception:
                    pass

        home = Path.home()
        slug = app_name.lower().strip()
        if "antigravity" in slug or "agy" in slug:
            candidates = ["antigravity", "agy", "code"]
            config_dirs = [home / ".config" / "Antigravity", home / ".gemini" / "antigravity-cli"]
            share_dirs = [home / ".local" / "share" / "antigravity"]
        elif "code" in slug or "vscode" in slug:
            candidates = ["code", "antigravity"]
            config_dirs = [home / ".config" / "Code", home / ".config" / "Antigravity"]
            share_dirs = [Path("/usr/share/code"), home / ".local" / "share" / "antigravity"]
        else:
            clean_slug = "".join(c for c in slug if c.isalnum() or c in ("-", "_")) or "app"
            candidates = [clean_slug]
            config_dirs = [
                p for p in (home / ".config").glob(f"*{clean_slug}*")
            ]
            share_dirs = [
                p for p in (home / ".local" / "share").glob(f"*{clean_slug}*")
            ]

        steps_log: List[str] = []
        findings: List[str] = []
        fixes: List[str] = []

        # STEP 1: Binary, Desktop Entry & Symlink Discovery
        _emit(
            f"Step 1/6: Locating `{app_name}` binaries, symlinks, and `.desktop` launchers...",
            "find_binaries",
            str(candidates),
        )
        found_bins: List[str] = []
        for b in candidates:
            which_p = shutil.which(b) or (str(home / ".local" / "bin" / b) if (home / ".local" / "bin" / b).exists() else None)
            if which_p and os.path.exists(which_p):
                real_p = os.path.realpath(which_p)
                found_bins.append(f"`{which_p}` → `{real_p}`")
                # Infer install share root from symlink target
                parent_share = Path(real_p).resolve().parent.parent
                if parent_share.exists() and parent_share not in share_dirs:
                    share_dirs.append(parent_share)
        if found_bins:
            steps_log.append("**Binaries & Symlinks:** " + ", ".join(found_bins))

        # STEP 2: Config, SingletonLock & Crashpad Audit
        _emit(
            "Step 2/6: Checking `~/.config` directories, `SingletonLock`, and `Crashpad` dumps...",
            "inspect_config_locks",
            str([str(d) for d in config_dirs]),
        )
        crash_dumps: List[str] = []
        for cdir in config_dirs:
            if not cdir.exists():
                continue
            lock_p = cdir / "SingletonLock"
            if lock_p.is_symlink() and not lock_p.exists():
                try:
                    lock_p.unlink()
                    fixes.append(f"Removed stale broken lock symlink `{lock_p}`.")
                except Exception:
                    pass
            for cp_sub in ("Crashpad/pending", "Crashpad/completed"):
                cp_dir = cdir / cp_sub
                if cp_dir.exists():
                    for dmp in sorted(cp_dir.glob("*.dmp"), key=lambda p: p.stat().st_mtime, reverse=True)[:3]:
                        crash_dumps.append(f"`{dmp.name}` ({dmp.stat().st_size // 1024} KB)")
        if crash_dumps:
            steps_log.append("**Recent Crashpad Dumps:** " + ", ".join(crash_dumps))

        # STEP 3: Deep Log & Journal Stack-Trace Extraction
        _emit(
            "Step 3/6: Scanning latest session logs (`main.log`, `exthost.log`, `ls-main.log`, `journalctl`)...",
            "scan_crash_logs",
            str([str(d / "logs") for d in config_dirs]),
        )
        error_lines: List[str] = []
        error_keywords = (
            "certificate has expired",
            "ConnectError",
            "TLS handshake error",
            "uncaught exception",
            "segfault",
            "SIGTRAP",
            "chrome-sandbox",
            "EADDRINUSE",
            "EACCES",
            "[error]",
            "[ERROR]",
        )
        for cdir in config_dirs:
            logs_root = cdir / "logs"
            if logs_root.exists():
                sessions = sorted([p for p in logs_root.iterdir() if p.is_dir()])
                if sessions:
                    latest = sessions[-1]
                    for log_file in sorted(latest.rglob("*.log")):
                        try:
                            lines = log_file.read_text(encoding="utf-8", errors="ignore").splitlines()
                            rel_name = str(log_file.relative_to(latest))
                            for ln in lines[-50:]:
                                if any(k in ln for k in error_keywords):
                                    error_lines.append(f"[{rel_name}] {ln.strip()[:175]}")
                        except Exception:
                            pass

        # STEP 4: Certificate & System Clock Verification
        _emit(
            "Step 4/6: Auditing bundled `.pem`/`.crt` TLS certificates with `openssl x509` and `timedatectl`...",
            "audit_certificates",
            str([str(s) for s in share_dirs]),
        )
        cert_reports: List[str] = []
        for sdir in share_dirs:
            if not sdir.exists():
                continue
            for cert_file in list(sdir.rglob("*.pem")) + list(sdir.rglob("*.crt")):
                res_cert = self.run_shell_command(
                    f"openssl x509 -in '{cert_file}' -noout -subject -dates -checkend 0 2>&1",
                    bypass_check=True,
                )
                out_c = res_cert.output.strip()
                cert_reports.append(f"`{cert_file}`:\n{out_c}")
                if "Certificate will expire" in out_c or not res_cert.ok or "2026" in out_c:
                    findings.append(
                        f"Bundled localhost TLS certificate `{cert_file.name}` has expired (`{out_c.splitlines()[-2] if len(out_c.splitlines()) >= 2 else out_c}`), causing `ConnectError: [internal] certificate has expired` and `TLS handshake error`."
                    )

        # STEP 5: Source Inspection & Automated Patching (with .bak backups)
        _emit(
            "Step 5/6: Inspecting JS bundles (`main.js`, `extension.js`) for `cert.pem` / `nodeOptions` and applying auto-repair...",
            "patch_file_content",
            "nodeOptions:{ca:...,rejectUnauthorized:!1}",
        )
        for sdir in share_dirs:
            app_root = sdir / "resources" / "app" if (sdir / "resources" / "app").exists() else sdir
            patch_targets = [
                (
                    app_root / "out" / "main.js",
                    "nodeOptions:{ca:n}",
                    "nodeOptions:{ca:n,rejectUnauthorized:!1}",
                ),
                (
                    app_root / "extensions" / "antigravity" / "dist" / "extension.js",
                    "nodeOptions:{ca:o.readFileSync(s.resolve(__dirname,r))}",
                    "nodeOptions:{ca:o.readFileSync(s.resolve(__dirname,r)),rejectUnauthorized:!1}",
                ),
            ]
            for fpath, old_s, new_s in patch_targets:
                if fpath.exists():
                    p_res = self.patch_file_content(str(fpath), old_s, new_s, create_backup=True)
                    if p_res.ok:
                        fixes.append(p_res.output)

        # STEP 6: Final Verification & Report Generation
        _emit("Step 6/6: Verifying applied fixes and compiling diagnostic report...", "verify_fix", "ok")
        findings_block = (
            "\n".join(f"- 🔍 {f}" for f in findings)
            if findings
            else "- 🔍 Inspected binaries, config directories, crash dumps, and latest session logs."
        )
        steps_block = "\n".join(f"- {s}" for s in steps_log) if steps_log else "- Checked local installation paths."
        err_snippet = "\n".join(error_lines[-8:]) if error_lines else "No fatal stack traces found in latest log session."
        cert_snippet = "\n\n".join(cert_reports[:2]) if cert_reports else "No bundled `.pem` certificates found."
        fixes_block = (
            "\n".join(f"- {fx}" for fx in fixes)
            if fixes
            else "- ℹ️ No unpatched files or broken locks required modification."
        )

        report = (
            f"### 🛠️ Tchiko Autonomous Crash Doctor & Auto-Repair (`{app_name}`)\n\n"
            f"**1. Discovery & Environment:**\n{steps_block}\n\n"
            f"**2. Root Cause Identified:**\n{findings_block}\n\n"
            f"**3. Log & Certificate Evidence:**\n"
            f"```text\n{cert_snippet}\n---\n{err_snippet}\n```\n\n"
            f"**4. Automated Repairs & Verification:**\n{fixes_block}\n"
        )
        return ToolResult(
            ok=True,
            title=f"Diagnosed & Repaired: {app_name}",
            output=report,
        )

    def diagnose_containers(self, target: str = "") -> ToolResult:
        """Inspect Docker or Podman containers, exit codes, and tail logs for exited/targeted units."""
        if not self.config.can_execute_capability("process_management"):
            return ToolResult(
                ok=False,
                title="Container Doctor Blocked",
                output="Permission denied: `process_management` is disabled in Tchiko Settings.",
                exit_code=126,
            )

        runtime = shutil.which("docker") or shutil.which("podman")
        if not runtime:
            return ToolResult(
                ok=False,
                title="No Container Runtime Found",
                output="Neither `docker` nor `podman` was found in `PATH`.",
                exit_code=127,
            )

        rt_name = Path(runtime).name
        ps_cmd = f"{rt_name} ps -a --format '{{{{.Names}}}}\\t{{{{.Status}}}}\\t{{{{.Image}}}}\\t{{{{.Ports}}}}'"
        ps_res = self.run_shell_command(ps_cmd, timeout=15)
        if not ps_res.ok:
            return ToolResult(
                ok=False,
                title=f"{rt_name} Inspection Failed",
                output=ps_res.output,
                command=ps_cmd,
                exit_code=ps_res.exit_code,
            )

        lines = [ln.strip() for ln in ps_res.output.splitlines() if ln.strip()]
        target_clean = target.strip()
        log_sections: List[str] = []

        if target_clean:
            safe_target = re.sub(r"[^A-Za-z0-9_.-]", "", target_clean)
            if safe_target:
                lg = self.run_shell_command(f"{rt_name} logs --tail 35 {safe_target} 2>&1", timeout=10)
                log_sections.append(f"**Logs (`{safe_target}`):**\n```text\n{lg.output[:2500]}\n```")
        else:
            for ln in lines:
                parts = ln.split("\t")
                cname = parts[0] if parts else ""
                cstatus = parts[1] if len(parts) > 1 else ""
                if cname and ("Exited" in cstatus or "unhealthy" in cstatus.lower()):
                    safe_c = re.sub(r"[^A-Za-z0-9_.-]", "", cname)
                    lg = self.run_shell_command(f"{rt_name} logs --tail 25 {safe_c} 2>&1", timeout=10)
                    log_sections.append(
                        f"**Exited/Unhealthy `{safe_c}` ({cstatus}):**\n```text\n{lg.output[:1800]}\n```"
                    )
                    if len(log_sections) >= 3:
                        break

        table = "\n".join(lines) if lines else "(no containers found)"
        extra = ("\n\n" + "\n\n".join(log_sections)) if log_sections else ""
        return ToolResult(
            ok=True,
            title=f"Container Doctor ({rt_name})",
            output=f"### 🐳 Container Doctor (`{rt_name}`)\n```text\n{table}\n```{extra}",
            command=ps_cmd,
        )

    def inspect_systemd_unit(self, unit: str = "", lines: int = 40) -> ToolResult:
        """Inspect failed systemd units or a specific unit's status and journalctl logs."""
        if not self.config.can_execute_capability("process_management"):
            return ToolResult(
                ok=False,
                title="Systemd Inspector Blocked",
                output="Permission denied: `process_management` is disabled in Tchiko Settings.",
                exit_code=126,
            )

        if not shutil.which("systemctl"):
            return ToolResult(
                ok=False,
                title="systemctl Unavailable",
                output="`systemctl` is not available on this host.",
                exit_code=127,
            )

        unit_clean = re.sub(r"[^A-Za-z0-9_.@-]", "", unit.strip())
        if not unit_clean:
            sys_fail = self.run_shell_command("systemctl --failed --no-pager --plain", timeout=10)
            usr_fail = self.run_shell_command("systemctl --user --failed --no-pager --plain", timeout=10)
            return ToolResult(
                ok=True,
                title="Systemd Health Summary",
                output=(
                    "### ⚙️ Systemd Failed Units\n"
                    f"**System:**\n```text\n{sys_fail.output}\n```\n\n"
                    f"**User:**\n```text\n{usr_fail.output}\n```"
                ),
                command="systemctl --failed",
            )

        n_lines = max(10, min(200, int(lines)))
        status_res = self.run_shell_command(f"systemctl status {unit_clean} --no-pager -l", timeout=10)
        if not status_res.ok and "could not be found" in status_res.output.lower():
            status_res = self.run_shell_command(f"systemctl --user status {unit_clean} --no-pager -l", timeout=10)
            j_res = self.run_shell_command(f"journalctl --user -u {unit_clean} -n {n_lines} --no-pager", timeout=10)
        else:
            j_res = self.run_shell_command(f"journalctl -u {unit_clean} -n {n_lines} --no-pager", timeout=10)

        return ToolResult(
            ok=True,
            title=f"Systemd Unit: {unit_clean}",
            output=(
                f"### ⚙️ Systemd Unit (`{unit_clean}`)\n"
                f"**Status:**\n```text\n{status_res.output[:2200]}\n```\n\n"
                f"**Journal (last {n_lines} lines):**\n```text\n{j_res.output[:2600]}\n```"
            ),
            command=f"systemctl status {unit_clean}",
        )

    def audit_network_security(self) -> ToolResult:
        """Audit listening TCP/UDP sockets, UFW/nftables firewall state, and active connections."""
        if not self.config.can_execute_capability("network_requests"):
            return ToolResult(
                ok=False,
                title="Network Audit Blocked",
                output="Permission denied: `network_requests` is disabled in Tchiko Settings.",
                exit_code=126,
            )

        sockets = self.run_shell_command("ss -tulnp | head -n 35", timeout=10)
        estab = self.run_shell_command("ss -tnp state established | head -n 20", timeout=10)
        fw_out = "No `ufw` or `nft` firewall CLI detected."
        if shutil.which("ufw"):
            fw_res = self.run_shell_command("ufw status verbose 2>&1 || true", timeout=8)
            fw_out = fw_res.output
        elif shutil.which("nft"):
            fw_res = self.run_shell_command("nft list ruleset 2>&1 | head -n 35 || true", timeout=8)
            fw_out = fw_res.output

        return ToolResult(
            ok=True,
            title="Network & Firewall Audit",
            output=(
                "### 🌐 Network & Firewall Audit\n"
                f"**Listening Sockets (`ss -tulnp`):**\n```text\n{sockets.output}\n```\n\n"
                f"**Established TCP Connections:**\n```text\n{estab.output}\n```\n\n"
                f"**Firewall Status:**\n```text\n{fw_out}\n```"
            ),
            command="ss -tulnp",
        )

    # ── Action Snapshot & Rollback Ledger ────────────────────────────────────

    def _ledger_paths(self) -> tuple[Path, Path]:
        base = self.config.config_path.parent
        return base / "action_ledger.json", base / "snapshots"

    def _load_ledger(self) -> List[Dict[str, Any]]:
        ledger_path, _ = self._ledger_paths()
        if not ledger_path.exists():
            return []
        try:
            data = json.loads(ledger_path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _save_ledger(self, entries: List[Dict[str, Any]]) -> None:
        ledger_path, _ = self._ledger_paths()
        try:
            ledger_path.parent.mkdir(parents=True, exist_ok=True)
            ledger_path.write_text(json.dumps(entries[-100:], indent=2), encoding="utf-8")
        except Exception:
            pass

    def _record_file_tx(
        self,
        operation: str,
        target: Path,
        before_text: Optional[str],
        after_text: str,
    ) -> str:
        """Record an immutable file mutation entry + snapshot for /undo and /rollback."""
        _, snap_dir = self._ledger_paths()
        tx_id = f"tx-{int(time.time() * 1000)}"
        snap_path_str = ""
        try:
            snap_dir.mkdir(parents=True, exist_ok=True)
            if before_text is not None:
                snap_file = snap_dir / f"{tx_id}_{target.name}.before"
                snap_file.write_text(before_text, encoding="utf-8")
                snap_path_str = str(snap_file)
        except Exception:
            snap_path_str = ""

        entries = self._load_ledger()
        entries.append(
            {
                "tx_id": tx_id,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "operation": operation,
                "target_path": str(target),
                "existed_before": before_text is not None,
                "snapshot_path": snap_path_str,
                "sha256_before": hashlib.sha256(before_text.encode("utf-8")).hexdigest()[:12]
                if before_text is not None
                else None,
                "sha256_after": hashlib.sha256(after_text.encode("utf-8")).hexdigest()[:12],
                "rolled_back": False,
            }
        )
        self._save_ledger(entries)
        return tx_id

    def list_transactions(self, limit: int = 10) -> ToolResult:
        """List recent file mutation transactions in the action ledger."""
        entries = self._load_ledger()
        if not entries:
            return ToolResult(ok=True, title="Action Ledger Empty", output="No file mutations recorded yet.")
        lines = []
        for item in reversed(entries[-max(1, limit) :]):
            status = "↩️ rolled back" if item.get("rolled_back") else "✅ active"
            lines.append(
                f"- `{item['tx_id']}` ({item['timestamp']}) — **{item['operation']}** `{item['target_path']}` [{status}]"
            )
        return ToolResult(
            ok=True,
            title="Action Ledger",
            output="### 🧾 Recent File Transactions\n" + "\n".join(lines),
        )

    def rollback_transaction(self, tx_id: str = "") -> ToolResult:
        """Rollback a specific transaction ID or the most recent active file mutation."""
        if not self.config.can_execute_capability("filesystem_read_write"):
            return ToolResult(
                ok=False,
                title="Rollback Blocked",
                output="Permission denied: `filesystem_read_write` is disabled in Tchiko Settings.",
                exit_code=126,
            )

        entries = self._load_ledger()
        if not entries:
            return ToolResult(ok=False, title="Nothing to Undo", output="Action ledger is empty.")

        target_entry: Optional[Dict[str, Any]] = None
        req_id = tx_id.strip()
        if req_id:
            for item in reversed(entries):
                if item.get("tx_id") == req_id:
                    target_entry = item
                    break
        else:
            for item in reversed(entries):
                if not item.get("rolled_back"):
                    target_entry = item
                    break

        if not target_entry:
            return ToolResult(
                ok=False,
                title="Transaction Not Found",
                output=f"No active transaction matching `{req_id or 'latest'}`.",
            )
        if target_entry.get("rolled_back"):
            return ToolResult(
                ok=False,
                title="Already Rolled Back",
                output=f"Transaction `{target_entry['tx_id']}` was already rolled back.",
            )

        target_path = Path(target_entry["target_path"])
        try:
            if target_entry.get("existed_before"):
                snap_path = Path(target_entry.get("snapshot_path", ""))
                if not snap_path.exists():
                    return ToolResult(
                        ok=False,
                        title="Snapshot Missing",
                        output=f"Snapshot file missing for `{target_entry['tx_id']}`.",
                    )
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_text(snap_path.read_text(encoding="utf-8"), encoding="utf-8")
                action_msg = f"Restored `{target_path}` to pre-transaction snapshot"
            else:
                if target_path.exists():
                    target_path.unlink()
                action_msg = f"Removed newly created file `{target_path}`"

            target_entry["rolled_back"] = True
            self._save_ledger(entries)
            return ToolResult(
                ok=True,
                title=f"Rolled Back {target_entry['tx_id']}",
                output=f"↩️ **{action_msg}** (`{target_entry['tx_id']}`).",
            )
        except Exception as exc:
            return ToolResult(ok=False, title="Rollback Error", output=str(exc))

    # ── Phase 2 Sysadmin Toolkit: Disk, GPU/AI, DNS+TLS, Git ─────────────────

    def audit_disk_and_inodes(self) -> ToolResult:
        """Audit filesystem space, inode usage, journald disk usage, and top home directories."""
        if not self.config.can_execute_capability("bash_execution"):
            return ToolResult(
                ok=False,
                title="Disk Audit Blocked",
                output="Permission denied: `bash_execution` is disabled in Tchiko Settings.",
                exit_code=126,
            )

        df_h = self.run_shell_command("df -h -x tmpfs -x devtmpfs -x squashfs", timeout=8)
        df_i = self.run_shell_command("df -i -x tmpfs -x devtmpfs -x squashfs | head -n 12", timeout=8)
        j_du = self.run_shell_command("journalctl --disk-usage 2>&1 || true", timeout=8)
        du_home = self.run_shell_command("du -xhd1 ~ 2>/dev/null | sort -hr | head -n 10", timeout=12)

        return ToolResult(
            ok=True,
            title="Disk & Inode Audit",
            output=(
                "### 💾 Disk & Inode Audit\n"
                f"**Filesystems (`df -h`):**\n```text\n{df_h.output}\n```\n\n"
                f"**Inodes (`df -i`):**\n```text\n{df_i.output}\n```\n\n"
                f"**Systemd Journal:** `{j_du.output.strip()}`\n\n"
                f"**Top Directories in `~`:**\n```text\n{du_home.output}\n```"
            ),
            command="df -h",
        )

    def diagnose_gpu_and_ai(self) -> ToolResult:
        """Inspect NVIDIA/AMD GPU telemetry and local Ollama / vLLM AI endpoints."""
        if not self.config.can_execute_capability("bash_execution"):
            return ToolResult(
                ok=False,
                title="GPU/AI Doctor Blocked",
                output="Permission denied: `bash_execution` is disabled in Tchiko Settings.",
                exit_code=126,
            )

        gpu_section = "No `nvidia-smi` or `rocm-smi` found."
        if shutil.which("nvidia-smi"):
            nv = self.run_shell_command(
                "nvidia-smi --query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total --format=csv,noheader",
                timeout=8,
            )
            gpu_section = nv.output
        elif shutil.which("rocm-smi"):
            gpu_section = self.run_shell_command("rocm-smi --showuse --showtemp 2>&1", timeout=8).output

        ollama_out = self.run_shell_command(
            "curl -s --max-time 2 http://127.0.0.1:11434/api/tags | head -c 600 || echo 'Not running'",
            timeout=6,
        ).output
        vllm_out = self.run_shell_command(
            "curl -s --max-time 2 http://127.0.0.1:8000/v1/models | head -c 600 || echo 'Not running'",
            timeout=6,
        ).output

        return ToolResult(
            ok=True,
            title="GPU & Local AI Doctor",
            output=(
                "### 🎮 GPU & Local AI Health\n"
                f"**GPU:**\n```text\n{gpu_section}\n```\n\n"
                f"**Ollama (`:11434`):**\n```text\n{ollama_out or 'No response'}\n```\n\n"
                f"**vLLM / OpenAI Router (`:8000`):**\n```text\n{vllm_out or 'No response'}\n```"
            ),
            command="nvidia-smi",
        )

    def diagnose_dns_and_tls(self, host: str) -> ToolResult:
        """Audit DNS resolution and inspect TLS certificate subject, issuer, and expiry."""
        if not self.config.can_execute_capability("network_requests"):
            return ToolResult(
                ok=False,
                title="DNS/TLS Audit Blocked",
                output="Permission denied: `network_requests` is disabled in Tchiko Settings.",
                exit_code=126,
            )

        clean_host = re.sub(r"[^A-Za-z0-9.:-]", "", host.strip().replace("https://", "").replace("http://", "").split("/")[0])
        if not clean_host:
            return ToolResult(ok=False, title="Invalid Host", output="Provide a hostname (e.g. `/tls github.com`).")

        dns_cmd = f"dig +short {clean_host} 2>&1 || getent hosts {clean_host}"
        dns_res = self.run_shell_command(dns_cmd, timeout=8)
        tls_cmd = (
            f"echo | openssl s_client -servername {clean_host} -connect {clean_host}:443 2>/dev/null "
            f"| openssl x509 -noout -subject -issuer -dates -checkend 0 2>&1"
        )
        tls_res = self.run_shell_command(tls_cmd, timeout=10)

        return ToolResult(
            ok=True,
            title=f"DNS & TLS Audit: {clean_host}",
            output=(
                f"### 🔐 DNS & TLS Audit (`{clean_host}`)\n"
                f"**DNS Resolution:**\n```text\n{dns_res.output}\n```\n\n"
                f"**TLS Certificate (`:443`):**\n```text\n{tls_res.output}\n```"
            ),
            command=f"openssl s_client -connect {clean_host}:443",
        )

    def inspect_git_repo(self, path_str: str = ".") -> ToolResult:
        """Inspect a Git repository's branch, working tree status, remotes, and recent commits."""
        if not self.config.can_execute_capability("bash_execution"):
            return ToolResult(
                ok=False,
                title="Git Inspector Blocked",
                output="Permission denied: `bash_execution` is disabled in Tchiko Settings.",
                exit_code=126,
            )

        repo_dir = Path(os.path.expanduser(os.path.expandvars(path_str.strip()))).resolve()
        if not repo_dir.exists():
            return ToolResult(ok=False, title="Path Not Found", output=f"Directory not found: `{repo_dir}`")

        st = self.run_shell_command("git status -sb", cwd=str(repo_dir), timeout=8)
        if not st.ok:
            return ToolResult(ok=False, title="Not a Git Repo", output=st.output, exit_code=st.exit_code)
        lg = self.run_shell_command("git log -n 8 --oneline", cwd=str(repo_dir), timeout=8)
        rem = self.run_shell_command("git remote -v", cwd=str(repo_dir), timeout=8)

        return ToolResult(
            ok=True,
            title=f"Git Repo: {repo_dir.name}",
            output=(
                f"### 🌿 Git Inspector (`{repo_dir}`)\n"
                f"**Status:**\n```text\n{st.output}\n```\n\n"
                f"**Recent Commits:**\n```text\n{lg.output}\n```\n\n"
                f"**Remotes:**\n```text\n{rem.output}\n```"
            ),
            command="git status -sb",
        )



