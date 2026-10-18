"""Ubuntu Linux System Interaction Toolkit for Tchiko Assistant.

Executes shell commands, inspects system telemetry (CPU, RAM, Disk, Uptime,
Processes, Network), manages files, launches desktop apps, and sends desktop
notifications — strictly enforcing the user's Tchiko Settings permission state.
"""

from __future__ import annotations

import os
import platform
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
        target = Path(os.path.expanduser(path_str)).resolve()
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
