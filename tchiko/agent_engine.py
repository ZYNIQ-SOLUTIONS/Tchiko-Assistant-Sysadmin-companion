"""Google Antigravity SDK & Advanced Autonomous Linux Agent Engine for Tchiko Assistant.

Capabilities:
1. Official Google Antigravity Python SDK (`google.antigravity`: `Agent`,
   `LocalAgentConfig`, `CapabilitiesConfig`) with real-time streaming of
   `response.thoughts`, `response.tool_calls`, and `response` tokens.
2. Persistent Conversational & Contextual Memory (`config/agent_memory.json`):
   - Remembers conversation history, active working directory (`cwd`), last executed
     command & output, last generated artifact (e.g. OpenSSH `.pub` key or folder),
     and user-saved facts/notes (`"remember my hetzner ip is ..."`).
   - Resolves contextual follow-ups (*"copy it"*, *"run it again"*, *"where did you save it?"*).
3. Multi-Step Autonomous Linux & DevOps Action Planner:
   - OpenSSH key generation (`ed25519` / `rsa`) + automatic clipboard copy + `~/.ssh/config` host setup
   - Comprehensive Ubuntu System Doctor (`/doctor` or *"diagnose system"*)
   - Port & Process Doctor (*"what is using port 8000"*, *"kill port 3000"*, *"what is eating my RAM/CPU"*)
   - Multi-step folder + Git repo / script scaffolding
   - Smart file finder & code search (`find` / `grep`)
   - Docker, systemd service management, package version checks, and network auditing
4. Multi-Turn ReAct Tool Loop for Gemini REST API & Local Ollama with `<bash>` execution.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .config_manager import ConfigManager, PROJECT_ROOT
from .system_tools import LinuxSystemToolkit

# Attempt to import the official Google Antigravity Python SDK
try:
    from google.antigravity import Agent, CapabilitiesConfig, LocalAgentConfig  # type: ignore

    HAS_ANTIGRAVITY_SDK = True
except Exception:
    Agent = None  # type: ignore
    CapabilitiesConfig = None  # type: ignore
    LocalAgentConfig = None  # type: ignore
    HAS_ANTIGRAVITY_SDK = False


MEMORY_FILE = PROJECT_ROOT / "config" / "agent_memory.json"


class TchikoAgentEngine:
    """Orchestrates Antigravity SDK sessions, persistent memory, and multi-step Linux actions."""

    def __init__(self, config: ConfigManager, toolkit: LinuxSystemToolkit) -> None:
        self.config = config
        self.toolkit = toolkit
        self.agy_bin = shutil.which("agy") or (
            "/home/level-78/.local/bin/agy"
            if os.path.exists("/home/level-78/.local/bin/agy")
            else None
        )
        self.memory: Dict[str, Any] = self._load_memory()

    def _load_memory(self) -> Dict[str, Any]:
        default_mem: Dict[str, Any] = {
            "cwd": str(Path.home()),
            "last_command": "",
            "last_output": "",
            "last_artifact_path": "",
            "last_artifact_content": "",
            "notes": {},
            "history": [],
        }
        if MEMORY_FILE.exists():
            try:
                loaded = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    default_mem.update(loaded)
            except Exception:
                pass
        if not os.path.isdir(default_mem.get("cwd", "")):
            default_mem["cwd"] = str(Path.home())
        return default_mem

    def _save_memory(self) -> None:
        try:
            MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            # Keep last 24 conversation turns
            if len(self.memory.get("history", [])) > 24:
                self.memory["history"] = self.memory["history"][-24:]
            MEMORY_FILE.write_text(json.dumps(self.memory, indent=2), encoding="utf-8")
        except Exception:
            pass

    def record_turn(self, role: str, content: str) -> None:
        hist = self.memory.setdefault("history", [])
        hist.append({"role": role, "content": content[:1200], "ts": int(time.time())})
        self._save_memory()

    @staticmethod
    def copy_to_system_clipboard(text: str) -> bool:
        """Copy text to X11/Wayland clipboard if possible."""
        if not text:
            return False
        for cmd in (
            ["xclip", "-selection", "clipboard"],
            ["xsel", "--clipboard", "--input"],
            ["wl-copy"],
        ):
            if shutil.which(cmd[0]):
                try:
                    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, close_fds=True)
                    proc.communicate(input=text.encode("utf-8"), timeout=2)
                    return proc.returncode == 0
                except Exception:
                    pass
        return False

    def get_engine_status_label(self) -> str:
        """Return a concise description of the active Antigravity runtime."""
        sdk_status = "Antigravity Python SDK" if HAS_ANTIGRAVITY_SDK else "Tchiko Autonomous Linux Engine"
        agy_status = " + agy CLI" if self.agy_bin else ""
        perms = "ALL PERMISSIONS GRANTED" if self.config.is_all_permissions_approved() else "REVIEW MODE"
        return f"{sdk_status}{agy_status} • {perms}"

    def process_prompt_async(
        self,
        prompt: str,
        on_thought: Callable[[str], None],
        on_tool_call: Callable[[str, str], None],
        on_token: Callable[[str], None],
        on_complete: Callable[[str], None],
        on_state_change: Callable[[str], None],
        on_approval_needed: Optional[Callable[[str, Callable[[], None], Callable[[], None]], None]] = None,
    ) -> None:
        """Run prompt handling on a background thread with streaming UI callbacks."""

        def _worker() -> None:
            try:
                user_text = prompt.strip()
                self.record_turn("user", user_text)

                def _wrapped_complete(final_text: str) -> None:
                    self.record_turn("assistant", final_text)
                    on_complete(final_text)

                asyncio.run(
                    self._handle_prompt(
                        user_text,
                        on_thought,
                        on_tool_call,
                        on_token,
                        _wrapped_complete,
                        on_state_change,
                        on_approval_needed,
                    )
                )
            except Exception as exc:
                on_state_change("alert")
                on_token(f"\n⚠️ Error: {exc}\n")
                on_complete(f"Error: {exc}")

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

    async def _handle_prompt(
        self,
        prompt: str,
        on_thought: Callable[[str], None],
        on_tool_call: Callable[[str, str], None],
        on_token: Callable[[str], None],
        on_complete: Callable[[str], None],
        on_state_change: Callable[[str], None],
        on_approval_needed: Optional[Callable[[str, Callable[[], None], Callable[[], None]], None]],
    ) -> None:
        on_state_change("thinking")

        # 1. Check built-in Slash Commands (/doctor, /memory, /sysinfo, /run, etc.)
        slash_handled = await self._try_handle_slash_commands(
            prompt,
            on_thought,
            on_tool_call,
            on_token,
            on_complete,
            on_state_change,
            on_approval_needed,
        )
        if slash_handled:
            return

        # 2. Check Contextual Memory & Follow-up Actions ("copy it", "remember ...", "cd ...")
        context_handled = await self._try_contextual_followup(
            prompt,
            on_thought,
            on_tool_call,
            on_token,
            on_complete,
            on_state_change,
            on_approval_needed,
        )
        if context_handled:
            return

        # 3. Check Autonomous Natural-Language Linux Action Planner (SSH keys, Doctor, Ports, Files, DevOps)
        action_handled = await self._try_autonomous_linux_action(
            prompt,
            on_thought,
            on_tool_call,
            on_token,
            on_complete,
            on_state_change,
            on_approval_needed,
        )
        if action_handled:
            return

        # 4. If Google Antigravity Python SDK is installed & enabled, run via SDK!
        if HAS_ANTIGRAVITY_SDK and self.config.data.get("agent", {}).get("use_antigravity_sdk", True):
            on_thought("Initializing Google Antigravity SDK `LocalAgentConfig`...")
            all_perms = self.config.is_all_permissions_approved()
            caps_enabled = all_perms or (
                self.config.data.get("permissions", {}).get("tool_execution_policy") == "always-proceed"
            )
            sys_instructions = self.config.data.get("agent", {}).get("system_instructions", "")

            sdk_config = LocalAgentConfig(
                system_instructions=sys_instructions,
                capabilities=CapabilitiesConfig() if caps_enabled else None,
            )

            full_text: list[str] = []
            async with Agent(sdk_config) as agent:
                response = await agent.chat(prompt)

                async def _stream_thoughts() -> None:
                    if hasattr(response, "thoughts"):
                        async for thought in response.thoughts:
                            on_thought(str(thought))

                async def _stream_tools() -> None:
                    if hasattr(response, "tool_calls"):
                        async for call in response.tool_calls:
                            on_state_change("executing")
                            on_tool_call(getattr(call, "name", "tool"), str(getattr(call, "args", "")))

                thought_task = asyncio.create_task(_stream_thoughts())
                tool_task = asyncio.create_task(_stream_tools())

                async for token in response:
                    tok_str = str(token)
                    full_text.append(tok_str)
                    on_token(tok_str)

                await asyncio.gather(thought_task, tool_task, return_exceptions=True)

            on_state_change("idle")
            on_complete("".join(full_text))
            return

        # 5. Try Optional Gemini API / Local Ollama LLM with Multi-Turn Memory & ReAct Tool Loop
        llm_reply = await self._try_external_llm_with_tools(
            prompt,
            on_thought,
            on_tool_call,
            on_token,
            on_complete,
            on_state_change,
            on_approval_needed,
        )
        if llm_reply:
            return

        # 6. Smart Shell Heuristic: if the prompt looks like a valid Linux command directly (e.g. "ls -la", "git status", "df -h", "uname -a")
        first_token = prompt.split()[0] if prompt.split() else ""
        if first_token in (
            "ls", "pwd", "whoami", "id", "uptime", "df", "du", "free", "ps", "top",
            "ip", "ss", "netstat", "ping", "dig", "curl", "wget", "git", "docker",
            "systemctl", "journalctl", "ufw", "lsb_release", "uname", "cat", "head",
            "tail", "grep", "find", "which", "whereis", "env", "lsblk", "lspci", "lsusb",
        ):
            await self._execute_command_with_policy(
                prompt,
                on_thought,
                on_tool_call,
                on_token,
                on_complete,
                on_state_change,
                on_approval_needed,
            )
            return

        # 7. Helpful fallback with active context summary
        telemetry = self.toolkit.get_system_telemetry()
        cwd = self.memory.get("cwd", str(Path.home()))
        notes_count = len(self.memory.get("notes", {}))
        reply = (
            f"### 🐾 Tchiko Autonomous Agent (`{telemetry['hostname']}`)\n"
            f"- **Working Dir:** `{cwd}` • **Memory Notes:** `{notes_count}`\n\n"
            f"Here is what I can execute autonomously for you:\n"
            f"- **🔑 SSH & Remote Servers:** *\"create an ssh key for my hetzner server in OpenSSH format\"* or *\"add hetzner server 95.216.1.2 to ssh config\"*\n"
            f"- **🩺 System Doctor:** Type `/doctor` or *\"diagnose my system\"* for a 5-point Ubuntu health audit\n"
            f"- **⚙️ Ports & Processes:** *\"what is using port 8000\"*, *\"kill port 3000\"*, *\"what is eating my RAM\"*\n"
            f"- **📂 Files & Scaffolding:** *\"create a folder on Desktop named api and init git\"*, *\"find *.py in ~/Desktop\"*\n"
            f"- **🧠 Context & Memory:** *\"remember my hetzner ip is 95.216.10.20\"*, *\"copy it\"*, *\"retry\"*, or `/memory`\n"
            f"- **💻 Direct Bash:** Type `$ <command>` or `/run <command>`"
        )
        await self._stream_markdown(reply, on_token)
        on_state_change("idle")
        on_complete(reply)

    async def _try_contextual_followup(
        self,
        prompt: str,
        on_thought: Callable[[str], None],
        on_tool_call: Callable[[str, str], None],
        on_token: Callable[[str], None],
        on_complete: Callable[[str], None],
        on_state_change: Callable[[str], None],
        on_approval_needed: Optional[Callable[[str, Callable[[], None], Callable[[], None]], None]],
    ) -> bool:
        """Handle contextual follow-ups using Tchiko's persistent memory."""
        lower = prompt.lower().strip()

        # 1. "copy it" / "copy the key" / "copy last output"
        if lower in (
            "copy", "copy it", "copy that", "copy the key", "copy ssh key",
            "copy public key", "copy output", "copy last output",
        ):
            content = self.memory.get("last_artifact_content") or self.memory.get("last_output", "")
            if not content:
                msg = "⚠️ I don't have a recent key or command output in memory yet to copy."
            else:
                self.copy_to_system_clipboard(content)
                msg = (
                    f"### 📋 Copied to Clipboard!\n"
                    f"```text\n{content}\n```"
                )
            await self._stream_markdown(msg, on_token)
            on_state_change("happy")
            on_complete(msg)
            return True

        # 2. "retry" / "run it again" / "repeat"
        if lower in ("retry", "run it again", "run again", "repeat", "repeat last command"):
            last_cmd = self.memory.get("last_command", "")
            if not last_cmd:
                msg = "⚠️ No previous command recorded in memory yet."
                await self._stream_markdown(msg, on_token)
                on_state_change("idle")
                on_complete(msg)
                return True
            await self._run_and_report(
                f"Re-running previous command (`{last_cmd}`):",
                last_cmd,
                on_thought,
                on_tool_call,
                on_token,
                on_complete,
                on_state_change,
                on_approval_needed,
            )
            return True

        # 3. "where did you save it?" / "where is it?" / "show last file"
        if lower in ("where is it", "where is it?", "where did you save it", "where did you save it?", "show last file"):
            art_path = self.memory.get("last_artifact_path", "")
            art_content = self.memory.get("last_artifact_content", "")
            if art_path:
                msg = f"### 📍 Last Saved Artifact\n- **Path:** `{art_path}`\n"
                if art_content:
                    msg += f"```text\n{art_content}\n```"
            else:
                msg = f"📍 Current working directory is `{self.memory.get('cwd', str(Path.home()))}`."
            await self._stream_markdown(msg, on_token)
            on_state_change("idle")
            on_complete(msg)
            return True

        # 4. Change working directory: "cd <path>" or "go to <path>"
        m_cd = re.match(r"^(?:cd|go\s+to\s+folder|go\s+to|change\s+directory\s+to)\s+(.+)$", prompt.strip(), re.IGNORECASE)
        if m_cd:
            raw_target = m_cd.group(1).strip().strip("'\"")
            expanded = os.path.expanduser(raw_target)
            if not os.path.isabs(expanded):
                expanded = os.path.abspath(os.path.join(self.memory.get("cwd", str(Path.home())), expanded))
            if os.path.isdir(expanded):
                self.memory["cwd"] = expanded
                self._save_memory()
                res = self.toolkit.list_directory(expanded)
                msg = f"### 📂 Changed Working Directory to `{expanded}`\n```text\n{res.output}\n```"
                await self._stream_markdown(msg, on_token)
                on_state_change("happy")
                on_complete(msg)
            else:
                msg = f"⚠️ Directory does not exist: `{expanded}`"
                await self._stream_markdown(msg, on_token)
                on_state_change("alert")
                on_complete(msg)
            return True

        # 5. Persistent user notes: "remember that <key> is <val>" or "remember <note>"
        m_rem = re.match(r"^(?:tchiko\s+)?remember\s+(?:that\s+)?(.+)$", prompt.strip(), re.IGNORECASE)
        if m_rem:
            note_text = m_rem.group(1).strip()
            notes = self.memory.setdefault("notes", {})
            if " is " in note_text:
                k, v = note_text.split(" is ", 1)
                notes[k.strip()] = v.strip()
            else:
                notes[f"note_{len(notes) + 1}"] = note_text
            self._save_memory()
            msg = (
                f"### 🧠 Saved to Tchiko Memory!\n"
                f"- **Remembered:** `{note_text}`\n"
                f"- Type `/memory` anytime to inspect or clear your saved notes."
            )
            await self._stream_markdown(msg, on_token)
            on_state_change("happy")
            on_complete(msg)
            return True

        if any(q in lower for q in ("what do you remember", "show memory", "my notes")):
            return await self._try_handle_slash_commands(
                "/memory", on_thought, on_tool_call, on_token, on_complete, on_state_change, on_approval_needed
            )

        return False

    async def _try_autonomous_linux_action(
        self,
        prompt: str,
        on_thought: Callable[[str], None],
        on_tool_call: Callable[[str, str], None],
        on_token: Callable[[str], None],
        on_complete: Callable[[str], None],
        on_state_change: Callable[[str], None],
        on_approval_needed: Optional[Callable[[str, Callable[[], None], Callable[[], None]], None]],
    ) -> bool:
        """Parse single or multi-step natural-language Linux tasks and execute them directly on Ubuntu."""
        lower = prompt.lower()

        # ── A. SYSTEM DOCTOR / COMPREHENSIVE HEALTH DIAGNOSTIC ────────────────
        if any(
            k in lower
            for k in (
                "diagnose", "health check", "system doctor", "full check",
                "audit system", "check everything", "why is my pc slow",
            )
        ):
            return await self._run_system_doctor(
                on_thought, on_tool_call, on_token, on_complete, on_state_change
            )

        # ── B. SSH CONFIG HOST SETUP ("add hetzner server 1.2.3.4 to ssh config") ─
        m_ssh_cfg = re.search(
            r"add\s+(?:([a-zA-Z0-9_-]+)\s+)?(?:server|host)\s+(\d{1,3}(?:\.\d{1,3}){3}|[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\s+to\s+(?:my\s+)?ssh\s+config",
            lower,
        )
        if m_ssh_cfg:
            host_alias = m_ssh_cfg.group(1) or "hetzner"
            host_ip = m_ssh_cfg.group(2)
            user_match = re.search(r"user\s+([a-zA-Z0-9_-]+)", lower)
            ssh_user = user_match.group(1) if user_match else "root"
            key_file = Path.home() / ".ssh" / f"id_ed25519_{host_alias}"
            identity_line = f"    IdentityFile {key_file}\n" if key_file.exists() else ""
            block = (
                f"\nHost {host_alias}\n"
                f"    HostName {host_ip}\n"
                f"    User {ssh_user}\n"
                f"{identity_line}"
                f"    ServerAliveInterval 60\n"
            )
            ssh_cfg_path = Path.home() / ".ssh" / "config"
            ssh_cfg_path.parent.mkdir(parents=True, exist_ok=True)
            with open(ssh_cfg_path, "a", encoding="utf-8") as f:
                f.write(block)
            os.chmod(ssh_cfg_path, 0o600)
            self.memory["last_artifact_path"] = str(ssh_cfg_path)
            self.memory["last_artifact_content"] = block.strip()
            self._save_memory()
            report = (
                f"### 🔧 Added Host `{host_alias}` to `~/.ssh/config`\n"
                f"```ssh-config\n{block.strip()}\n```\n"
                f"You can now connect with simply: `ssh {host_alias}`"
            )
            await self._stream_markdown(report, on_token)
            on_state_change("happy")
            on_complete(report)
            return True

        # ── C. SSH KEY CREATION & OPENSSH MANAGEMENT ──────────────────────────
        if "ssh" in lower and any(
            w in lower for w in ("create", "generate", "make", "new", "need", "add", "key", "openssh", "hetzner", "htzner")
        ):
            is_list_only = any(w in lower for w in ("list", "show", "existing", "what are")) and not any(
                w in lower for w in ("create", "generate", "make", "new", "need")
            )
            if is_list_only:
                cmd = "ls -la ~/.ssh && for f in ~/.ssh/*.pub; do [ -f \"$f\" ] && echo \"=== $f ===\" && cat \"$f\"; done"
                await self._run_and_report(
                    "Listing your existing OpenSSH public keys in `~/.ssh`:",
                    cmd,
                    on_thought,
                    on_tool_call,
                    on_token,
                    on_complete,
                    on_state_change,
                    on_approval_needed,
                )
                return True

            key_label = "tchiko"
            if any(k in lower for k in ("hetzner", "htzner")):
                key_label = "hetzner"
            elif "github" in lower:
                key_label = "github"
            elif "gitlab" in lower:
                key_label = "gitlab"
            elif "aws" in lower:
                key_label = "aws"
            elif "digitalocean" in lower:
                key_label = "digitalocean"
            else:
                m_srv = re.search(r"(?:for|to|named)\s+([a-zA-Z0-9_-]{3,20})\s+server", lower)
                if m_srv and m_srv.group(1) not in ("my", "the", "remote", "new", "add"):
                    key_label = m_srv.group(1).lower()

            hostname = socket.gethostname() or "ubuntu"
            ssh_dir = Path.home() / ".ssh"
            key_file = ssh_dir / f"id_ed25519_{key_label}"
            key_type = "rsa -b 4096" if "rsa" in lower else "ed25519 -a 100"
            if "rsa" in lower:
                key_file = ssh_dir / f"id_rsa_{key_label}"

            comment = f"{key_label}@{hostname}"
            gen_cmd = (
                f"mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
                f"if [ -f '{key_file}' ]; then mv '{key_file}' '{key_file}.bak' && mv '{key_file}.pub' '{key_file}.pub.bak' 2>/dev/null || true; fi && "
                f"ssh-keygen -t {key_type} -f '{key_file}' -N '' -C '{comment}' >/dev/null && "
                f"chmod 600 '{key_file}' && chmod 644 '{key_file}.pub' && "
                f"cat '{key_file}.pub'"
            )

            on_thought(f"Generating OpenSSH keypair `{key_file}` for `{key_label}`...")
            if self.config.requires_manual_review() and on_approval_needed is not None:
                await self._execute_command_with_policy(
                    gen_cmd,
                    on_thought,
                    on_tool_call,
                    on_token,
                    on_complete,
                    on_state_change,
                    on_approval_needed,
                )
                return True

            on_state_change("executing")
            on_tool_call("ssh-keygen (OpenSSH)", f"{{'path': '{key_file}', 'comment': '{comment}'}}")
            res = self.toolkit.run_shell_command(gen_cmd)
            pub_key = res.output.strip()

            if res.ok and pub_key.startswith("ssh-"):
                copied = self.copy_to_system_clipboard(pub_key)
                self.memory["last_artifact_path"] = f"{key_file}.pub"
                self.memory["last_artifact_content"] = pub_key
                self._save_memory()
                copy_badge = " *(Auto-copied to system clipboard!)*" if copied else ""
                report = (
                    f"### 🔑 OpenSSH Keypair Created for `{key_label.capitalize()}`!{copy_badge}\n"
                    f"- **Format:** OpenSSH (`{pub_key.split()[0]}`)\n"
                    f"- **Private Key:** `{key_file}` (`chmod 600`)\n"
                    f"- **Public Key:** `{key_file}.pub` (`chmod 644`)\n\n"
                    f"**1. Your OpenSSH Public Key** (click **📋 Copy** or paste directly into **Hetzner Cloud Console → Security → SSH Keys**):\n"
                    f"```text\n{pub_key}\n```\n\n"
                    f"**2. Connect to your server:**\n"
                    f"```text\nssh -i {key_file} root@<YOUR_SERVER_IP>\n```"
                )
            else:
                report = f"### ⚠️ SSH Key Generation Output\n```text\n{res.output}\n```"

            await self._stream_markdown(report, on_token)
            on_state_change("happy" if res.ok else "alert")
            on_complete(report)
            return True

        # ── D. KILL / FREE PORT ("kill port 8000" / "free port 3000") ─────────
        m_kill_port = re.search(r"(?:kill|stop|free|close)\s+(?:process\s+on\s+)?port\s+(\d{2,5})", lower)
        if m_kill_port:
            port = m_kill_port.group(1)
            cmd = (
                f"pids=$(lsof -t -i:{port} 2>/dev/null); "
                f"if [ -n \"$pids\" ]; then kill -9 $pids && echo \"✅ Terminated PID(s) on port {port}: $pids\"; "
                f"else echo \"ℹ️ No process was listening on port {port}.\"; fi"
            )
            await self._run_and_report(
                f"Freeing port `{port}`:",
                cmd,
                on_thought,
                on_tool_call,
                on_token,
                on_complete,
                on_state_change,
                on_approval_needed,
            )
            return True

        # ── E. CREATE FOLDER (+ OPTIONAL GIT INIT / SUBFOLDERS) ───────────────
        m_mkdir = re.search(
            r"(?:create|make|new)\s+(?:a\s+)?(?:folder|directory|dir)\s+(?:on\s+desktop\s+)?(?:named|called|under\s+the\s+name\s+of)?\s*['\"]?([a-zA-Z0-9_./-]+)['\"]?",
            prompt,
            re.IGNORECASE,
        )
        if m_mkdir:
            raw_name = m_mkdir.group(1).strip()
            if "desktop" in lower and not raw_name.startswith(("/", "~")):
                target_path = str(Path.home() / "Desktop" / raw_name)
            else:
                target_path = os.path.expanduser(raw_name)
                if not os.path.isabs(target_path):
                    target_path = os.path.join(self.memory.get("cwd", str(Path.home())), target_path)

            steps = [f"mkdir -p {target_path!r}"]
            if "git" in lower and any(w in lower for w in ("init", "repo", "repository")):
                steps.append(f"git -C {target_path!r} init")
            if "readme" in lower:
                steps.append(f"echo '# {Path(target_path).name}' > {os.path.join(target_path, 'README.md')!r}")
            steps.append(f"ls -la {target_path!r}")
            cmd = " && ".join(steps)

            self.memory["last_artifact_path"] = target_path
            self._save_memory()
            await self._run_and_report(
                f"Scaffolding directory `{target_path}`:",
                cmd,
                on_thought,
                on_tool_call,
                on_token,
                on_complete,
                on_state_change,
                on_approval_needed,
            )
            return True

        # ── F. SMART FILE FINDER & CONTENT GREP ───────────────────────────────
        m_find = re.search(
            r"(?:find|search\s+for|locate)\s+files?\s+(?:named|matching|like)?\s*['\"]?([a-zA-Z0-9_*.-]+)['\"]?(?:\s+(?:in|on)\s+([a-zA-Z0-9_./~-]+))?",
            prompt,
            re.IGNORECASE,
        )
        if m_find:
            pattern = m_find.group(1).strip()
            where = m_find.group(2).strip() if m_find.group(2) else self.memory.get("cwd", "~")
            if where.lower() == "desktop":
                where = "~/Desktop"
            search_dir = os.path.expanduser(where)
            cmd = f"find {search_dir!r} -maxdepth 4 -iname {f'*{pattern}*' if '*' not in pattern else pattern!r} 2>/dev/null | head -n 40"
            await self._run_and_report(
                f"Searching for files matching `{pattern}` in `{search_dir}`:",
                cmd,
                on_thought,
                on_tool_call,
                on_token,
                on_complete,
                on_state_change,
                on_approval_needed,
            )
            return True

        # ── G. COMMON NATURAL-LANGUAGE LINUX DIAGNOSTICS & ACTIONS ────────────
        intent_command = self._match_common_linux_intent(prompt, lower)
        if intent_command is not None:
            explanation, cmd = intent_command
            await self._run_and_report(
                explanation,
                cmd,
                on_thought,
                on_tool_call,
                on_token,
                on_complete,
                on_state_change,
                on_approval_needed,
            )
            return True

        return False

    async def _run_system_doctor(
        self,
        on_thought: Callable[[str], None],
        on_tool_call: Callable[[str, str], None],
        on_token: Callable[[str], None],
        on_complete: Callable[[str], None],
        on_state_change: Callable[[str], None],
    ) -> bool:
        """Run a multi-step 5-point Ubuntu System Doctor diagnostic."""
        on_state_change("executing")
        on_thought("Step 1/4: Auditing Ubuntu CPU, RAM, and Disk health...")
        on_tool_call("system_doctor", "{'checks': ['telemetry', 'processes', 'systemd', 'ports']}")

        t = self.toolkit.get_system_telemetry()
        top_cpu = self.toolkit.run_shell_command(
            "ps -eo pid,user,%cpu,%mem,comm --sort=-%cpu | head -n 6", bypass_check=True
        ).output
        failed_units = self.toolkit.run_shell_command(
            "systemctl --failed --no-legend --no-pager 2>/dev/null | head -n 5", bypass_check=True
        ).output
        ports = self.toolkit.run_shell_command(
            "ss -tulnp 2>/dev/null | grep LISTEN | head -n 8", bypass_check=True
        ).output

        health_status = "🟢 HEALTHY"
        warnings: List[str] = []
        if t["ram_percent"] > 85.0:
            health_status = "🟡 HIGH MEMORY PRESSURE"
            warnings.append(f"RAM usage is at {t['ram_percent']}% ({t['ram_used_gb']}/{t['ram_total_gb']} GB).")
        if t["disk_percent"] > 88.0:
            health_status = "🟡 LOW DISK SPACE"
            warnings.append(f"Disk usage is at {t['disk_percent']}%.")
        if failed_units and "0 loaded units" not in failed_units and not failed_units.startswith("(Command"):
            warnings.append("One or more systemd services reported a failed state.")

        warn_block = (
            "\n".join(f"- ⚠️ {w}" for w in warnings)
            if warnings
            else "- ✅ All core resource thresholds (CPU, RAM, Disk, Services) are within healthy limits."
        )

        report = (
            f"### 🩺 Tchiko System Doctor Report — {health_status}\n"
            f"- **Host:** `{t['hostname']}` • **OS:** `{t['distro']}` • **Uptime:** `{t['uptime_str']}`\n"
            f"- **CPU Load:** `{t['cpu_load_1m']}` ({t['cpu_cores']} cores) • **RAM:** `{t['ram_used_gb']}/{t['ram_total_gb']} GB ({t['ram_percent']}%)` • **Disk:** `{t['disk_percent']}%`\n\n"
            f"**Diagnostic Summary:**\n{warn_block}\n\n"
            f"**Top CPU Processes:**\n```text\n{top_cpu}\n```\n\n"
            f"**Active Listening Ports:**\n```text\n{ports or 'No listening TCP/UDP ports detected.'}\n```"
        )
        await self._stream_markdown(report, on_token)
        on_state_change("happy")
        on_complete(report)
        return True

    def _match_common_linux_intent(self, prompt: str, lower: str) -> Optional[Tuple[str, str]]:
        """Map natural-language Linux questions/requests to shell commands."""
        m_port = re.search(r"port\s+(\d{2,5})", lower)
        if m_port:
            port = m_port.group(1)
            return (
                f"Checking processes listening on port `{port}`:",
                f"ss -tulnp | grep ':{port}' || lsof -i :{port} || echo 'No process currently listening on port {port}'",
            )

        if any(k in lower for k in ("listening port", "open port", "active port", "check port", "ss -tuln")):
            return ("Checking active listening network ports (`ss -tulnp`):", "ss -tulnp | head -n 30")

        if any(k in lower for k in ("eating my cpu", "high cpu", "top cpu")):
            return ("Checking top CPU-consuming processes:", "ps -eo pid,user,%cpu,%mem,cmd --sort=-%cpu | head -n 12")

        if any(k in lower for k in ("eating my ram", "eating my memory", "high memory", "top memory", "top ram")):
            return ("Checking top RAM-consuming processes:", "ps -eo pid,user,%mem,%cpu,cmd --sort=-%mem | head -n 12")

        if any(k in lower for k in ("public ip", "external ip", "my ip", "ip address", "network", "interfaces")):
            return (
                "Checking your local network interfaces and IP addresses:",
                "ip -br addr && echo '' && (curl -s --max-time 4 https://ifconfig.me && echo ' (Public IP)' || true)",
            )

        if any(k in lower for k in ("disk", "storage", "free space", "df -h")):
            return ("Checking mounted filesystem disk usage (`df -h`):", "df -h -x tmpfs -x squashfs")

        if any(k in lower for k in ("big files", "largest files", "heavy files", "disk hog")):
            return ("Finding the 15 largest files/folders in your home directory:", "du -ah ~ 2>/dev/null | sort -rh | head -n 15")

        if any(k in lower for k in ("memory", "ram", "swap", "free -h")):
            return ("Checking system RAM and Swap allocation (`free -h`):", "free -h")

        if any(k in lower for k in ("docker", "containers", "docker ps")):
            return (
                "Checking running Docker containers:",
                "docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' 2>&1",
            )

        if any(k in lower for k in ("git status", "git branch", "git log")):
            return ("Checking Git repository status:", "git status -sb && echo '' && git log -n 5 --oneline")

        if any(k in lower for k in ("desktop", "files on desktop")):
            return ("Listing files on your Ubuntu Desktop (`~/Desktop`):", "ls -la ~/Desktop")

        if any(k in lower for k in ("gpu", "graphics", "nvidia", "display card")):
            return (
                "Checking GPU & display hardware:",
                "lspci | grep -iE 'vga|3d|display' && (nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv 2>/dev/null || true)",
            )

        if any(k in lower for k in ("cpu", "processor", "lscpu", "cores")):
            return ("Checking CPU architecture and load:", "lscpu | grep -E 'Model name|Socket|Thread|NUMA|CPU\\(s\\)' && uptime")

        if any(k in lower for k in ("uptime", "kernel", "uname", "os version", "ubuntu version")):
            return ("Checking Ubuntu OS version, kernel, and uptime:", "lsb_release -a 2>/dev/null || cat /etc/os-release; echo ''; uname -a; uptime -p")

        if any(k in lower for k in ("firewall", "ufw")):
            return ("Checking firewall status:", "ufw status verbose 2>&1 || iptables -L -n 2>&1 | head -n 20")

        if any(k in lower for k in ("systemd", "services", "failed service", "systemctl")):
            return (
                "Checking active and failed systemd services:",
                "systemctl --failed --no-pager && echo '' && systemctl list-units --type=service --state=running --no-pager | head -n 20",
            )

        if any(k in lower for k in ("versions", "installed tools", "dev tools", "check tools")):
            return (
                "Checking installed developer tool versions on Ubuntu:",
                "for cmd in python3 node npm git docker ssh go rustc gcc; do "
                "if command -v $cmd >/dev/null 2>&1; then printf '%-10s: ' $cmd && $cmd --version 2>&1 | head -n 1; fi; done",
            )

        m_cmd = re.search(r"^(?:tchiko\s+)?(?:please\s+)?(?:run|execute)\s+[`'\"]?(.+?)[`'\"]?$", prompt.strip(), re.IGNORECASE)
        if m_cmd:
            cmd = m_cmd.group(1).strip()
            return (f"Executing command `{cmd}`:", cmd)

        return None

    async def _run_and_report(
        self,
        explanation: str,
        cmd: str,
        on_thought: Callable[[str], None],
        on_tool_call: Callable[[str, str], None],
        on_token: Callable[[str], None],
        on_complete: Callable[[str], None],
        on_state_change: Callable[[str], None],
        on_approval_needed: Optional[Callable[[str, Callable[[], None], Callable[[], None]], None]],
    ) -> None:
        on_token(f"🐾 **Tchiko:** {explanation}\n\n")
        await self._execute_command_with_policy(
            cmd,
            on_thought,
            on_tool_call,
            on_token,
            on_complete,
            on_state_change,
            on_approval_needed,
        )

    async def _try_external_llm_with_tools(
        self,
        prompt: str,
        on_thought: Callable[[str], None],
        on_tool_call: Callable[[str, str], None],
        on_token: Callable[[str], None],
        on_complete: Callable[[str], None],
        on_state_change: Callable[[str], None],
        on_approval_needed: Optional[Callable[[str, Callable[[], None], Callable[[], None]], None]],
    ) -> bool:
        """Query Gemini API or Local Ollama with conversation memory and execute <bash> tool blocks."""
        telemetry = self.toolkit.get_system_telemetry()
        cwd = self.memory.get("cwd", str(Path.home()))
        notes = json.dumps(self.memory.get("notes", {}))
        recent_turns = "\n".join(
            f"{t['role'].upper()}: {t['content']}"
            for t in self.memory.get("history", [])[-6:]
        )

        sys_prompt = (
            f"You are Tchiko, an advanced autonomous Ubuntu Linux desktop AI companion on host '{telemetry['hostname']}' "
            f"({telemetry['distro']}), working directory '{cwd}'.\n"
            f"User saved memory notes: {notes}\n"
            f"Recent conversation context:\n{recent_turns}\n\n"
            "Whenever the user asks you to perform any action, create keys/files, inspect the system, or configure something on Linux, "
            "include the exact bash command inside <bash>COMMAND</bash> tags so Tchiko executes it automatically on Ubuntu. "
            "Be concise, helpful, and action-oriented."
        )

        gemini_key = (
            os.getenv("GEMINI_API_KEY")
            or self.config.data.get("agent", {}).get("gemini_api_key", "")
        ).strip()

        llm_text: Optional[str] = None
        if gemini_key and gemini_key != "your_gemini_api_key_here":
            on_thought("Querying Gemini 2.5 Flash with multi-turn memory...")
            llm_text = await asyncio.to_thread(self._call_gemini_rest, gemini_key, sys_prompt, prompt)

        if not llm_text:
            for port in (11434, 11435):
                llm_text = await asyncio.to_thread(self._call_local_ollama, port, sys_prompt, prompt)
                if llm_text:
                    break

        if not llm_text:
            return False

        m_bash = re.search(r"<bash>(.*?)</bash>", llm_text, re.DOTALL)
        clean_reply = re.sub(r"<bash>.*?</bash>", "", llm_text, flags=re.DOTALL).strip()
        if clean_reply:
            await self._stream_markdown(clean_reply + "\n\n", on_token)

        if m_bash:
            cmd = m_bash.group(1).strip()
            if cmd:
                await self._execute_command_with_policy(
                    cmd,
                    on_thought,
                    on_tool_call,
                    on_token,
                    on_complete,
                    on_state_change,
                    on_approval_needed,
                )
                return True

        on_state_change("idle")
        on_complete(clean_reply or llm_text)
        return True

    @staticmethod
    def _call_gemini_rest(api_key: str, sys_prompt: str, user_prompt: str) -> Optional[str]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
        payload = {
            "system_instruction": {"parts": [{"text": sys_prompt}]},
            "contents": [{"parts": [{"text": user_prompt}]}],
        }
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception:
            return None

    @staticmethod
    def _call_local_ollama(port: int, sys_prompt: str, user_prompt: str) -> Optional[str]:
        url = f"http://127.0.0.1:{port}/api/tags"
        try:
            with urllib.request.urlopen(url, timeout=0.8) as resp:
                tags = json.loads(resp.read().decode("utf-8")).get("models", [])
                if not tags:
                    return None
                model_name = tags[0]["name"]
            chat_url = f"http://127.0.0.1:{port}/api/chat"
            payload = {
                "model": model_name,
                "stream": False,
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            }
            req = urllib.request.Request(
                chat_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=20) as c_resp:
                c_data = json.loads(c_resp.read().decode("utf-8"))
                return c_data.get("message", {}).get("content")
        except Exception:
            return None

    async def _try_handle_slash_commands(
        self,
        prompt: str,
        on_thought: Callable[[str], None],
        on_tool_call: Callable[[str, str], None],
        on_token: Callable[[str], None],
        on_complete: Callable[[str], None],
        on_state_change: Callable[[str], None],
        on_approval_needed: Optional[Callable[[str, Callable[[], None], Callable[[], None]], None]],
    ) -> bool:
        lower = prompt.lower().strip()

        if lower in ("/help", "help"):
            help_text = (
                "### 🐾 Tchiko Autonomous Agent — Reference\n"
                "- **Natural Language & DevOps:**\n"
                "  - *\"create an ssh key for my hetzner server in OpenSSH format\"* *(auto-copies `.pub` key!)*\n"
                "  - *\"add hetzner server 95.216.1.2 to ssh config\"*\n"
                "  - *\"create a folder on Desktop named my-app and init git\"*\n"
                "  - *\"what is using port 8000\"* or *\"kill port 8000\"*\n"
                "  - *\"find files named *.py in ~/Desktop\"*\n"
                "- **Context & Memory:**\n"
                "  - *\"remember my hetzner ip is 95.216.10.20\"*, *\"copy it\"*, *\"retry\"*, *\"cd ~/Desktop\"*\n"
                "- **Slash Commands:**\n"
                "  - `/doctor` — Run 5-point Ubuntu System Doctor diagnostic\n"
                "  - `/memory` — Inspect or clear Tchiko's persistent memory & notes\n"
                "  - `/sysinfo` — Live Ubuntu CPU, RAM, Disk & Uptime report\n"
                "  - `/run <command>` or `$ <command>` — Execute any Linux bash command\n"
                "  - `/procs` — List top CPU/Memory processes\n"
                "  - `/files [path]` — Inspect directory contents\n"
                "  - `/open <app-or-url>` — Launch an Ubuntu desktop app, folder, or URL\n"
                "  - `/permissions` — View current Antigravity & Linux permission state"
            )
            on_thought("Formatting Tchiko command reference...")
            await self._stream_markdown(help_text, on_token)
            on_state_change("idle")
            on_complete(help_text)
            return True

        if lower in ("/doctor", "doctor"):
            return await self._run_system_doctor(
                on_thought, on_tool_call, on_token, on_complete, on_state_change
            )

        if lower.startswith("/memory"):
            if "clear" in lower:
                self.memory["notes"] = {}
                self.memory["history"] = []
                self._save_memory()
                msg = "🧹 **Cleared Tchiko's saved notes and conversation history.**"
            else:
                notes = self.memory.get("notes", {})
                notes_lines = (
                    "\n".join(f"  - **{k}:** `{v}`" for k, v in notes.items())
                    if notes
                    else "  - *(No custom notes saved yet — try saying: `remember my server ip is 1.2.3.4`)*"
                )
                msg = (
                    f"### 🧠 Tchiko Persistent Agent Memory\n"
                    f"- **Active Working Directory (`cwd`):** `{self.memory.get('cwd')}`\n"
                    f"- **Last Command:** `{self.memory.get('last_command') or 'None'}`\n"
                    f"- **Last Artifact:** `{self.memory.get('last_artifact_path') or 'None'}`\n"
                    f"- **Conversation Turns Stored:** `{len(self.memory.get('history', []))}`\n"
                    f"- **Saved User Notes:**\n{notes_lines}\n"
                )
            await self._stream_markdown(msg, on_token)
            on_state_change("idle")
            on_complete(msg)
            return True

        if lower in ("/sysinfo", "sysinfo", "system status", "status", "health"):
            on_thought("Reading `/proc/meminfo`, `/proc/uptime`, and disk telemetry...")
            on_state_change("executing")
            on_tool_call("get_system_telemetry", "{}")
            report = self.toolkit.format_telemetry_report()
            await self._stream_markdown(report, on_token)
            on_state_change("idle")
            on_complete(report)
            return True

        if lower in ("/permissions", "permissions"):
            perms = self.config.data.get("permissions", {})
            all_ok = self.config.is_all_permissions_approved()
            caps = perms.get("capabilities", {})
            cap_lines = "\n".join(
                f"  - `{k}`: {'✅ Allowed' if (all_ok or v) else '🔒 Blocked'}"
                for k, v in caps.items()
            )
            msg = (
                f"### 🛡️ Tchiko Permission Policy\n"
                f"- **Master Approval (All System Permissions):** {'🟢 ENABLED' if all_ok else '🟡 DISABLED'}\n"
                f"- **Tool Execution Policy:** `{perms.get('tool_execution_policy')}`\n"
                f"- **Terminal Sandbox:** `{'Enabled' if perms.get('terminal_sandbox') else 'Disabled (Full Host Access)'}`\n"
                f"- **Non-Workspace File Access:** `{perms.get('non_workspace_file_access')}`\n"
                f"- **Internet Access Policy:** `{perms.get('internet_access_policy')}`\n"
                f"- **Capabilities:**\n{cap_lines}\n"
            )
            await self._stream_markdown(msg, on_token)
            on_state_change("idle")
            on_complete(msg)
            return True

        if lower == "/grant-all":
            self.config.set_all_permissions(True)
            msg = "🟢 **All Linux System Permissions Granted!** Tchiko can now interact with your Ubuntu system autonomously."
            await self._stream_markdown(msg, on_token)
            on_state_change("idle")
            on_complete(msg)
            return True

        if lower == "/revoke-all":
            self.config.set_all_permissions(False)
            msg = "🟡 **Switched to Supervised Review Mode.** Tchiko will ask for confirmation before running system commands."
            await self._stream_markdown(msg, on_token)
            on_state_change("idle")
            on_complete(msg)
            return True

        if lower.startswith("/procs") or lower in ("processes", "top processes", "show processes"):
            on_thought("Inspecting running Linux processes via `ps`...")
            on_state_change("executing")
            on_tool_call("list_top_processes", "{'limit': 12}")
            res = self.toolkit.list_top_processes(12)
            formatted = f"### ⚙️ Top Running Processes\n```text\n{res.output}\n```"
            await self._stream_markdown(formatted, on_token)
            on_state_change("idle" if res.ok else "alert")
            on_complete(formatted)
            return True

        if lower.startswith("/files"):
            arg = prompt[6:].strip() or self.memory.get("cwd", "~")
            on_thought(f"Listing directory contents for `{arg}`...")
            on_state_change("executing")
            on_tool_call("list_directory", f"{{'path': '{arg}'}}")
            res = self.toolkit.list_directory(arg)
            formatted = f"### 📂 {res.title}\n```text\n{res.output}\n```"
            await self._stream_markdown(formatted, on_token)
            on_state_change("idle" if res.ok else "alert")
            on_complete(formatted)
            return True

        if lower.startswith("/open "):
            target = prompt[6:].strip()
            on_thought(f"Launching desktop target `{target}`...")
            on_state_change("executing")
            on_tool_call("launch_application", f"{{'target': '{target}'}}")
            res = self.toolkit.launch_application(target)
            await self._stream_markdown(res.output, on_token)
            on_state_change("idle" if res.ok else "alert")
            on_complete(res.output)
            return True

        if lower.startswith("/run ") or prompt.startswith("$ "):
            cmd = prompt[5:].strip() if lower.startswith("/run ") else prompt[2:].strip()
            await self._execute_command_with_policy(
                cmd,
                on_thought,
                on_tool_call,
                on_token,
                on_complete,
                on_state_change,
                on_approval_needed,
            )
            return True

        return False

    async def _execute_command_with_policy(
        self,
        cmd: str,
        on_thought: Callable[[str], None],
        on_tool_call: Callable[[str, str], None],
        on_token: Callable[[str], None],
        on_complete: Callable[[str], None],
        on_state_change: Callable[[str], None],
        on_approval_needed: Optional[Callable[[str, Callable[[], None], Callable[[], None]], None]],
    ) -> None:
        """Execute a shell command in the agent's active cwd, recording memory and enforcing policy."""
        active_cwd = self.memory.get("cwd", str(Path.home()))
        on_thought(f"Executing in `{active_cwd}`: `{cmd}`")

        if self.config.requires_manual_review() and on_approval_needed is not None:
            on_state_change("thinking")
            on_token(
                f"🔒 **Approval Required** (Tool Policy is `request-review`).\n"
                f"Command queued: `{cmd}`\n"
            )

            def _approve() -> None:
                res = self.toolkit.run_shell_command(cmd, cwd=active_cwd, bypass_check=True)
                self.memory["last_command"] = cmd
                self.memory["last_output"] = res.output
                self._save_memory()
                out = f"\n✅ **Approved & Executed** (`{cmd}` — {res.duration_ms}ms):\n```text\n{res.output}\n```\n"
                on_token(out)
                on_state_change("idle" if res.ok else "alert")
                on_complete(out)

            def _deny() -> None:
                out = f"\n❌ **Cancelled execution of** `{cmd}`.\n"
                on_token(out)
                on_state_change("idle")
                on_complete(out)

            on_approval_needed(cmd, _approve, _deny)
            return

        on_state_change("executing")
        on_tool_call("run_shell_command", f"{{'command': {cmd!r}, 'cwd': {active_cwd!r}}}")
        res = self.toolkit.run_shell_command(cmd, cwd=active_cwd)
        self.memory["last_command"] = cmd
        self.memory["last_output"] = res.output
        self._save_memory()

        status_icon = "✅" if res.ok else "⚠️"
        formatted = (
            f"{status_icon} **{res.title}** (`exit={res.exit_code}`, `{res.duration_ms}ms`)\n"
            f"```text\n{res.output}\n```"
        )
        await self._stream_markdown(formatted, on_token)
        on_state_change("idle" if res.ok else "alert")
        on_complete(formatted)

    @staticmethod
    async def _stream_markdown(text: str, on_token: Callable[[str], None]) -> None:
        """Stream tokens smoothly into the active chat card."""
        chunk_size = 24
        for i in range(0, len(text), chunk_size):
            on_token(text[i : i + chunk_size])
            await asyncio.sleep(0.006)
        on_token("\n")
