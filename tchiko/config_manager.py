"""Configuration and Permission Policy Manager for Tchiko Assistant.

Manages `config/settings.json` and synchronizes with `antigravity.yaml` so that
Tchiko's permissions, Antigravity SDK `CapabilitiesConfig`, and Floating Ghost
preferences stay in sync across all windows.
"""

from __future__ import annotations

import copy
import json
import os
import re
import shlex
from pathlib import Path
from typing import Any, Callable, Dict, List


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "settings.json"
ANTIGRAVITY_YAML_PATH = PROJECT_ROOT / "antigravity.yaml"

DEFAULT_SETTINGS: Dict[str, Any] = {
    "app_name": "Tchiko Assistant",
    "version": "1.0.0",
    "permissions": {
        "approve_all_system_permissions": True,
        "tool_execution_policy": "always-proceed",
        "terminal_sandbox": False,
        "non_workspace_file_access": "allow",
        "internet_access_policy": "allow",
        "artifact_review_mode": "always-proceed",
        "capabilities": {
            "bash_execution": True,
            "filesystem_read_write": True,
            "process_management": True,
            "desktop_automation": True,
            "package_management": True,
            "network_requests": True,
        },
        "command_allowlist": ["*"],
        "command_denylist": [],
    },
    "agent": {
        "model": "gemini-2.5-pro",
        "workspace_dir": str(Path.home()),
        "system_instructions": (
            "You are Tchiko, a friendly, powerful floating ghost AI assistant "
            "living on the user's Ubuntu Linux desktop. Powered by the Google "
            "Antigravity SDK, you can inspect and control the Linux system, "
            "run shell commands, manage files, launch applications, and assist "
            "with coding and daily tasks whenever permissions are enabled in "
            "the Tchiko Settings window."
        ),
        "use_antigravity_sdk": True,
        "use_agy_cli_fallback": True,
    },
    "ghost_widget": {
        "size": 140,
        "opacity": 0.96,
        "always_on_top": True,
        "stick_all_workspaces": True,
        "theme": "phantom_cyan",
        "animation_speed": 1.0,
        "show_speech_bubble": True,
        "show_permission_badge": True,
        "position_x": 1120,
        "position_y": 140,
    },
    "ui": {
        "theme_mode": "dark",
        "notifications_enabled": True,
        "keep_awake": False,
    },
}


class ConfigManager:
    """Thread-safe configuration and Antigravity permission manager."""

    def __init__(self, config_path: Path = CONFIG_PATH) -> None:
        self.config_path = config_path
        self.data: Dict[str, Any] = copy.deepcopy(DEFAULT_SETTINGS)
        self._listeners: List[Callable[[Dict[str, Any]], None]] = []
        self.load()

    def load(self) -> Dict[str, Any]:
        """Load configuration from disk, merging missing keys with defaults."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        if self.config_path.exists():
            try:
                loaded = json.loads(self.config_path.read_text(encoding="utf-8"))
                self._deep_merge(self.data, loaded)
            except Exception:
                pass
        else:
            self.save(notify=False)
        return self.data

    def save(self, notify: bool = True) -> None:
        """Persist configuration to `config/settings.json` and `antigravity.yaml`."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        self._sync_antigravity_yaml()
        if notify:
            for callback in list(self._listeners):
                try:
                    callback(self.data)
                except Exception:
                    pass

    def subscribe(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Register a listener invoked whenever settings are updated."""
        if callback not in self._listeners:
            self._listeners.append(callback)

    def is_all_permissions_approved(self) -> bool:
        """Return True if the user approved all Linux system permissions."""
        perms = self.data.get("permissions", {})
        return bool(perms.get("approve_all_system_permissions", False))

    def set_all_permissions(self, approved: bool) -> None:
        """Toggle master full-system permission state and sync granular policies."""
        perms = self.data.setdefault("permissions", {})
        perms["approve_all_system_permissions"] = bool(approved)
        caps = perms.setdefault("capabilities", {})
        if approved:
            perms["tool_execution_policy"] = "always-proceed"
            perms["terminal_sandbox"] = False
            perms["non_workspace_file_access"] = "allow"
            perms["internet_access_policy"] = "allow"
            perms["artifact_review_mode"] = "always-proceed"
            for key in (
                "bash_execution",
                "filesystem_read_write",
                "process_management",
                "desktop_automation",
                "package_management",
                "network_requests",
            ):
                caps[key] = True
        else:
            perms["tool_execution_policy"] = "request-review"
            perms["terminal_sandbox"] = True
        self.save(notify=True)

    def can_execute_capability(self, capability_name: str) -> bool:
        """Check whether a specific system capability is permitted."""
        perms = self.data.get("permissions", {})
        if perms.get("approve_all_system_permissions", False):
            return True
        if perms.get("tool_execution_policy") == "strict":
            return False
        caps = perms.get("capabilities", {})
        return bool(caps.get(capability_name, False))

    def requires_manual_review(self, command: str = "") -> bool:
        """Check whether tool calls require interactive user approval before running."""
        perms = self.data.get("permissions", {})
        if perms.get("approve_all_system_permissions", False):
            return False
        needs_review = perms.get("tool_execution_policy", "request-review") == "request-review"
        if needs_review and command.strip():
            tier, _ = self.classify_command(command)
            if tier == "SAFE_READONLY":
                return False
        return needs_review

    @staticmethod
    def classify_command(command: str) -> tuple[str, str]:
        """Classify a shell command into SAFE_READONLY, MUTATING_LOCAL, or PRIVILEGED_DESTRUCTIVE."""
        cmd = command.strip()
        if not cmd:
            return "SAFE_READONLY", "Empty command"

        destructive_patterns = (
            r"(?:^|[;&|\s])sudo\b",
            r"\brm\s+-[a-zA-Z]*[rf][a-zA-Z]*\b",
            r"\bmkfs(?:\.[a-z0-9]+)?\b",
            r"\bdd\s+if=",
            r"\bchmod\s+-R\b",
            r"\bchown\b",
            r"\bkill\s+-9\b",
            r"\bpkill\b",
            r"\bsystemctl\s+(?:stop|disable|mask|reboot|poweroff)\b",
            r"\b(?:ufw|iptables|nft)\b",
            r"\b(?:curl|wget)\b[^|]*\|\s*(?:ba)?sh\b",
        )
        for pat in destructive_patterns:
            if re.search(pat, cmd, flags=re.IGNORECASE):
                return "PRIVILEGED_DESTRUCTIVE", f"Matches privileged/destructive pattern: {pat}"

        has_redirect = bool(re.search(r"(?:^|[^0-9])>{1,2}", cmd))
        has_subshell = "$(" in cmd or "`" in cmd

        safe_bins = {
            "ls", "pwd", "whoami", "id", "uname", "hostname", "date", "df", "du",
            "free", "ps", "uptime", "cat", "head", "tail", "wc", "grep", "rg",
            "awk", "which", "readlink", "stat", "file", "ss", "lsof", "ip",
            "dig", "nslookup", "resolvectl", "ping", "journalctl", "nvidia-smi",
            "echo", "printf", "env", "printenv", "lsblk", "lscpu",
        }

        segments = [s.strip() for s in re.split(r"\s*(?:&&|\|\||;|\|)\s*", cmd) if s.strip()]
        if not segments:
            return "SAFE_READONLY", "No executable segments"

        all_safe = not has_redirect and not has_subshell
        for seg in segments:
            try:
                tokens = shlex.split(seg)
            except ValueError:
                return "MUTATING_LOCAL", "Unbalanced shell quotes"
            if not tokens:
                continue
            head = os.path.basename(tokens[0])
            if head in safe_bins:
                continue
            if head == "find":
                if any(t in ("-delete", "-exec", "-execdir", "-ok") for t in tokens[1:]):
                    all_safe = False
                continue
            if head == "git" and len(tokens) >= 2 and tokens[1] in ("status", "log", "diff", "branch", "show", "rev-parse"):
                continue
            if head == "systemctl" and any(t in ("status", "--failed", "list-units", "is-active") for t in tokens[1:]):
                continue
            if head in ("docker", "podman") and len(tokens) >= 2 and tokens[1] in ("ps", "logs", "images", "inspect", "version"):
                continue
            if head == "openssl" and len(tokens) >= 2 and tokens[1] in ("x509", "s_client", "version"):
                continue
            all_safe = False

        if all_safe:
            return "SAFE_READONLY", "All pipeline segments are read-only diagnostics"
        return "MUTATING_LOCAL", "Command performs local state or file modifications"

    def is_command_allowed(self, command: str) -> tuple[bool, str]:
        """Validate a shell command against permissions and denylist."""
        perms = self.data.get("permissions", {})
        denylist = perms.get("command_denylist", [])
        cmd_stripped = command.strip()
        for denied in denylist:
            if denied and denied in cmd_stripped:
                return False, f"Command blocked by denylist rule: '{denied}'"

        if perms.get("approve_all_system_permissions", False):
            return True, "Approved via Master System Permissions"

        if not self.can_execute_capability("bash_execution"):
            return (
                False,
                "Bash execution is disabled in Tchiko Settings. Open Settings (⚙️) to approve permissions.",
            )

        return True, "Permitted by capability policy"

    def _sync_antigravity_yaml(self) -> None:
        """Write `antigravity.yaml` reflecting the current permission state."""
        perms = self.data.get("permissions", {})
        all_ok = bool(perms.get("approve_all_system_permissions", False))
        policy = perms.get("tool_execution_policy", "always-proceed" if all_ok else "request-review")
        sandbox = bool(perms.get("terminal_sandbox", not all_ok))
        file_access = perms.get("non_workspace_file_access", "allow" if all_ok else "ask")
        net_access = perms.get("internet_access_policy", "allow" if all_ok else "ask")
        caps = perms.get("capabilities", {})

        mode = "autonomous" if (all_ok or policy == "always-proceed") else "supervised"
        yaml_text = (
            f"mode: {mode}\n"
            f"permissions:\n"
            f"  approve_all_system_permissions: {str(all_ok).lower()}\n"
            f"  tool_execution_policy: {policy}\n"
            f"  sandbox_mode: {str(sandbox).lower()}\n"
            f"  non_workspace_file_access: {file_access}\n"
            f"  internet_access_policy: {net_access}\n"
            f"  tools:\n"
            f"    bash:\n"
            f"      auto_approve: {str(all_ok or bool(caps.get('bash_execution', False))).lower()}\n"
            f"    file_system:\n"
            f"      auto_approve: {str(all_ok or bool(caps.get('filesystem_read_write', False))).lower()}\n"
            f"    browser:\n"
            f"      auto_approve: {str(all_ok or bool(caps.get('network_requests', False))).lower()}\n"
            f"    system_control:\n"
            f"      auto_approve: {str(all_ok or bool(caps.get('desktop_automation', False))).lower()}\n"
        )
        try:
            ANTIGRAVITY_YAML_PATH.write_text(yaml_text, encoding="utf-8")
        except Exception:
            pass

    @staticmethod
    def _deep_merge(target: Dict[str, Any], source: Dict[str, Any]) -> None:
        for k, v in source.items():
            if isinstance(v, dict) and isinstance(target.get(k), dict):
                ConfigManager._deep_merge(target[k], v)
            else:
                target[k] = v
