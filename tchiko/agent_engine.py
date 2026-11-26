"""Google Antigravity SDK, NDJSON Stream Bridge & 5-Tier Autonomous Linux Agent Engine.

Architectural Overview (`tchiko/agent_engine.py`):
--------------------------------------------------
Orchestrates prompt dispatch across five prioritized execution tiers on a dedicated
daemon worker thread while marshaling UI updates (`on_thought`, `on_tool_call`,
`on_token`, `on_complete`, `on_state_change`) back to the GTK3 main loop:

- **Tier 1 (`_try_handle_slash_commands`)**: Zero-latency built-in operator commands
  (`/doctor`, `/sysinfo`, `/procs`, `/files`, `/memory`, `/permissions`, `/run`).
- **Tier 2 (`_try_contextual_followup`)**: Anaphoric & stateful follow-up resolution
  (`"copy it"`, `"retry"`, `"where did you save it?"`, `"cd <dir>"`, `"remember ..."`),
  backed by `config/agent_memory.json`.
- **Tier 3 (`_try_autonomous_linux_action`)**: Deterministic sysadmin & DevOps planners:
  - 6-Step Autonomous IDE & Application Crash Doctor (`_run_ide_crash_doctor`)
  - 5-Point Ubuntu System Health Audit (`_run_system_doctor`)
  - OpenSSH (`ed25519` / `rsa`) Keypair & `~/.ssh/config` Lifecycle Manager
  - Port & Process Reaper (`ss -tulnp` / `lsof -i`) and Git Repository Scaffolder
- **Tier 4A / 4B (`google.antigravity` SDK & `_run_agy_cli_stream_json`)**:
  - Streams real-time NDJSON events (`init`, `step_update`, `result`) from
    `agy -p --output-format stream-json --dangerously-skip-permissions`, preserving
    multi-turn session state via `agy_conversation_id`.
- **Tier 5 (`_try_external_llm_with_tools`)**: 8-step Multi-Tool ReAct Loop for
  Gemini 2.5 Flash REST API and Local Ollama (`gemma4:e4b`, `qwen2.5-coder:1.5b`,
  `llama3.2:latest`, `lfm2.5:8b`) supporting `<view_file>`, `<grep>`, `<patch_file>`,
  `<write_file>`, and `<bash>` with `<think>...</think>` chain-of-thought isolation.
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

from .agent_loop import ResilientAgentLoop
from .config_manager import ConfigManager, PROJECT_ROOT
from .conversation import (
    ClarificationRequest,
    ConversationAnalyzer,
    PendingTask,
    extract_suggested_command,
    is_anaphoric_run_target,
)
from .experiences import EXPERIENCES_DIR, ExperienceRegistry
from .skills_loader import SkillsLoader
from .system_tools import LinuxSystemToolkit, ToolResult

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

# An `agy` conversation is resumed only while it is this fresh; older ones start
# over with a full context briefing so stale topics never colour a new request.
AGY_SESSION_MAX_IDLE_SEC = 45 * 60
# Longest silence tolerated between two `agy` stream events (a long install emits nothing).
AGY_EVENT_IDLE_TIMEOUT_SEC = 900.0
# Shell timeout for commands issued by the local-LLM tool loop (installs, clones, builds).
LLM_TOOL_BASH_TIMEOUT_SEC = 300
LLM_MAX_TOOL_STEPS = 14

OPERATING_RULES = (
    "How to work:\n"
    "- You are Tchiko, a warm, perceptive, natural-sounding desktop companion. Talk like a helpful human "
    "sysadmin colleague — concise, clear, and honest.\n"
    "- The user types fast, often casually or with typos. If their intent is clear, carry the task through "
    "end to end in this turn. If a request is ambiguous, has an unrecognized/misspelled target, or involves "
    "a choice that materially changes what you would do (e.g. destructive cleanup, install source, ambiguous "
    "service/file), pause and ask 1–2 brief clarifying questions using `<ask_user question=\"...\"><option>...</option></ask_user>` "
    "instead of guessing.\n"
    "- If the user is just chatting or asking a conceptual question, answer warmly and naturally without running unnecessary tools.\n"
    "- Look before acting (is it already installed, which version, does the path exist) and verify "
    "after (run it, check the exit code or version). Report only what you observed; never invent "
    "command output.\n"
    "- When a command fails, read the error carefully, adapt your strategy (e.g. `pkexec` for root, check locks/paths/releases), "
    "and avoid repeating the exact same failing command.\n"
    "- For root actions prefer `pkexec` inside `<bash>pkexec ...</bash>`, which shows a graphical password dialog; "
    "plain `sudo` has no terminal to prompt on here.\n"
    "- Reuse matching learned Python Experience tools (`<experience name=\"...\" params='...' />`) whenever they fit.\n"
    "- Start long-running services in the background and confirm they are listening instead of blocking on them.\n"
    "- Skip session-start routines such as inbox watchers or listeners and go straight to the request.\n"
    "- Keep the reply short: what you did, the result, and the next step if there is one. Use only "
    "`###` headings, `-` bullets, **bold** and fenced code blocks; that is all the UI renders."
)

# Commands safe to run instantly when the whole prompt is clearly a shell command.
DIRECT_SHELL_COMMANDS = frozenset((
    "ls", "pwd", "whoami", "id", "uptime", "df", "du", "free", "ps", "top",
    "ip", "ss", "netstat", "ping", "dig", "curl", "wget", "git", "docker",
    "systemctl", "journalctl", "ufw", "lsb_release", "uname", "cat", "head",
    "tail", "grep", "find", "which", "whereis", "env", "lsblk", "lspci", "lsusb",
))
DIRECT_SHELL_SUBCOMMANDS = {
    "git": {"status", "log", "diff", "branch", "remote", "pull", "fetch", "stash", "show"},
    "docker": {"ps", "images", "logs", "stats", "info", "version", "compose"},
    "systemctl": {"status", "list-units", "is-active", "is-enabled"},
    "ip": {"a", "addr", "address", "r", "route", "link"},
    "ufw": {"status"},
}


class TchikoAgentEngine:
    """Orchestrates Antigravity SDK sessions, persistent memory, resilient loops, and learned Experiences."""

    def __init__(
        self,
        config: ConfigManager,
        toolkit: LinuxSystemToolkit,
        experiences_dir: Optional[Path] = None,
    ) -> None:
        self.config = config
        self.toolkit = toolkit
        self.skills = SkillsLoader()
        self.experiences = ExperienceRegistry(
            experiences_dir=experiences_dir or EXPERIENCES_DIR,
            config=self.config,
        )
        self.conversation = ConversationAnalyzer()
        self.last_episode: Optional[Dict[str, Any]] = None
        self.agy_bin = shutil.which("agy") or (
            "/home/level-78/.local/bin/agy"
            if os.path.exists("/home/level-78/.local/bin/agy")
            else None
        )
        self.memory: Dict[str, Any] = self._load_memory()
        self._prompt_lock = threading.Lock()  # one prompt at a time: tiers share memory + agy session
        self._machine_profile_cache: Optional[str] = None
        self._backend_notes: List[str] = []  # why each AI backend was skipped/failed for the current prompt
        # Warm the machine profile off-thread so the very first prompt does not pay for it.
        threading.Thread(target=self._machine_profile, daemon=True).start()

    # ── Context briefing: what every AI backend is told before the first request ──
    def _machine_profile(self) -> str:
        """One-line-per-fact description of this machine, gathered once per session."""
        if self._machine_profile_cache is not None:
            return self._machine_profile_cache
        t = self.toolkit.get_system_telemetry()
        lines = [
            f"- Host `{t.get('hostname', 'localhost')}`, {t.get('distro', 'Linux')}, kernel {t.get('os', '')}",
            f"- {t.get('cpu_cores', '?')} CPU cores, {t.get('ram_total_gb', '?')} GB RAM, "
            f"home disk {t.get('disk_percent', '?')}% used of {t.get('disk_total_gb', '?')} GB",
        ]
        gpu = ""
        if shutil.which("nvidia-smi"):
            try:
                gpu = subprocess.run(
                    ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                    capture_output=True, text=True, timeout=4,
                ).stdout.strip().replace("\n", "; ")
            except Exception:
                gpu = ""
        if gpu:
            lines.append(f"- GPU: {gpu}")
        shell = os.path.basename(os.environ.get("SHELL", "") or "bash")
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
        session = os.environ.get("XDG_SESSION_TYPE", "")
        lines.append(
            f"- User `{os.environ.get('USER', '')}`, home `{Path.home()}`, login shell `{shell}` "
            f"(rc file `~/.{shell}rc`)" + (f", desktop {desktop} on {session}" if desktop else "")
        )
        present = [
            n for n in (
                "apt", "snap", "flatpak", "docker", "uv", "pipx", "pip3", "node", "npm",
                "git", "ollama", "code", "pkexec",
            ) if shutil.which(n)
        ]
        if present:
            lines.append(f"- Available tools: {', '.join(present)}")
        self._machine_profile_cache = "\n".join(lines)
        return self._machine_profile_cache

    def _build_context_brief(self, include_history: bool = True, prompt_hint: str = "") -> str:
        """Persona + machine facts + user memory + matching Experiences + working rules."""
        persona = (self.config.data.get("agent", {}).get("system_instructions", "") or "").strip()
        parts: List[str] = []
        if persona:
            parts.append(persona)
        parts.append("This machine:\n" + self._machine_profile())
        parts.append(f"Current working directory: `{self.memory.get('cwd', str(Path.home()))}`")
        notes = self.memory.get("notes", {})
        if notes:
            parts.append(
                "Things the user asked you to remember:\n"
                + "\n".join(f"- {k}: {v}" for k, v in notes.items())
            )
        if prompt_hint:
            matched_exps = self.experiences.match_experiences(prompt_hint, max_matches=3)
            if matched_exps:
                exp_lines = [
                    f"- `{e.slug}` (v{e.version}, {e.maturity}, script `{e.script_path}`): {e.description} "
                    f"(params: {json.dumps(e.parameters)})"
                    for e in matched_exps
                ]
                parts.append(
                    "Learned Python Experiences available for this request:\n" + "\n".join(exp_lines)
                )
        if include_history:
            # history[-1] is the request being handled right now, so leave it out.
            earlier = self.memory.get("history", [])[:-1][-4:]
            if earlier:
                parts.append(
                    "Earlier in this chat (for continuity; may be unrelated to the new request):\n"
                    + "\n".join(
                        f"- {t.get('role', 'user')}: {' '.join(str(t.get('content', '')).split())[:280]}"
                        for t in earlier
                    )
                )
        parts.append(OPERATING_RULES)
        return "\n\n".join(parts)

    def reset_conversation(self) -> None:
        """Forget the running conversation (agent session + chat turns + pending clarification); saved notes are kept."""
        self.memory["agy_conversation_id"] = ""
        self.memory["agy_conversation_ts"] = 0
        self.memory["history"] = []
        self.memory["pending_task"] = None
        self.memory["last_suggested_command"] = ""
        self._save_memory()

    def _resolve_user_path(self, raw_path: str) -> str:
        """Expand `~` and `$VARS`, and anchor relative paths to the agent's working directory."""
        expanded = os.path.expanduser(os.path.expandvars(raw_path.strip().strip("'\"")))
        if not os.path.isabs(expanded):
            expanded = os.path.join(self.memory.get("cwd", str(Path.home())), expanded)
        return os.path.normpath(expanded)

    @staticmethod
    def _looks_like_direct_shell_command(prompt: str) -> bool:
        """True only when the prompt is unmistakably a shell command, not a sentence starting with one."""
        tokens = prompt.strip().split()
        if not tokens or tokens[0] not in DIRECT_SHELL_COMMANDS or prompt.strip().endswith("?"):
            return False
        if len(tokens) == 1:
            return True
        subcommands = DIRECT_SHELL_SUBCOMMANDS.get(tokens[0])
        if subcommands is not None:
            return tokens[1] in subcommands or tokens[1].startswith("-")
        return any(tok[0] in "-/~." or "." in tok for tok in tokens[1:])

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
        on_clarification_needed: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_experience_event: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        on_phase: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        """Run prompt handling on a background thread with streaming UI callbacks."""

        def _worker() -> None:
            try:
                user_text = prompt.strip()

                def _wrapped_complete(final_text: str) -> None:
                    self.record_turn("assistant", final_text)
                    suggested = extract_suggested_command(final_text)
                    if suggested:
                        self.memory["last_suggested_command"] = suggested
                        self._save_memory()
                    on_complete(final_text)

                with self._prompt_lock:
                    self.record_turn("user", user_text)
                    self._backend_notes = []
                    asyncio.run(
                        self._handle_prompt(
                            user_text,
                            on_thought,
                            on_tool_call,
                            on_token,
                            _wrapped_complete,
                            on_state_change,
                            on_approval_needed,
                            on_clarification_needed,
                            on_experience_event,
                            on_phase,
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
        on_clarification_needed: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_experience_event: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        on_phase: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        on_state_change("thinking")

        # 1. Check built-in Slash Commands (/doctor, /experiences, /learn, /memory, /sysinfo, /run, etc.)
        slash_handled = await self._try_handle_slash_commands(
            prompt,
            on_thought,
            on_tool_call,
            on_token,
            on_complete,
            on_state_change,
            on_approval_needed,
            on_experience_event=on_experience_event,
        )
        if slash_handled:
            return

        # 1B. Humanized Conversation & Clarification Gate (casual chat, pending clarification, anaphora, ambiguity)
        ask_ambig = bool(self.config.data.get("learning", {}).get("ask_before_ambiguous", True))
        conv = self.conversation.analyze(prompt, self.memory, ask_before_ambiguous=ask_ambig)

        if conv.kind == "casual_chat":
            await self._stream_markdown(conv.reply_text, on_token)
            on_state_change("happy")
            on_complete(conv.reply_text)
            return

        if conv.kind == "cancel_pending":
            self.memory["pending_task"] = None
            self._save_memory()
            await self._stream_markdown(conv.reply_text, on_token)
            on_state_change("idle")
            on_complete(conv.reply_text)
            return

        if conv.kind == "needs_clarification" and conv.clarification is not None:
            clar = conv.clarification
            self.memory["pending_task"] = PendingTask(
                id=clar.id,
                original_prompt=clar.original_prompt or prompt,
                question=clar.question,
                options=list(clar.options),
                context=clar.context,
            ).to_dict()
            self._save_memory()
            if on_phase is not None:
                on_phase("ASK_USER", clar.question[:120])
            md = clar.format_markdown()
            await self._stream_markdown(md, on_token)
            if on_clarification_needed is not None:
                try:
                    on_clarification_needed(clar.to_dict())
                except Exception:
                    pass
            on_state_change("thinking")
            on_complete(md)
            return

        if conv.kind == "anaphora_command" and conv.suggested_command:
            on_thought(f"Resolved reference to suggested command: `{conv.suggested_command}`")
            await self._run_and_report(
                f"Running the suggested command (`{conv.suggested_command}`):",
                conv.suggested_command,
                on_thought,
                on_tool_call,
                on_token,
                on_complete,
                on_state_change,
                on_approval_needed,
            )
            return

        if conv.kind == "clarification_reply":
            self.memory["pending_task"] = None
            self._save_memory()
            prompt = conv.resolved_prompt
            on_thought("Merged your clarification into the pending task; proceeding...")
            # Check if the user selected a built-in slash shortcut inside the option text
            m_slash_opt = re.search(r"(/[a-z][a-z0-9_-]*)", prompt.splitlines()[-1].lower())
            if m_slash_opt and m_slash_opt.group(1) in ("/doctor", "/procs", "/net", "/disk", "/gpu", "/experiences"):
                if await self._try_handle_slash_commands(
                    m_slash_opt.group(1),
                    on_thought,
                    on_tool_call,
                    on_token,
                    on_complete,
                    on_state_change,
                    on_approval_needed,
                    on_experience_event=on_experience_event,
                ):
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

        # 3B. A prompt that is plainly a shell command ("df -h", "git status") runs instantly
        #     instead of waiting on an AI backend to decide to run it.
        if self._looks_like_direct_shell_command(prompt):
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

        # 4. If Google Antigravity Python SDK is installed & enabled, run via SDK!
        if HAS_ANTIGRAVITY_SDK and self.config.data.get("agent", {}).get("use_antigravity_sdk", True):
            on_thought("Initializing Google Antigravity SDK `LocalAgentConfig`...")
            all_perms = self.config.is_all_permissions_approved()
            caps_enabled = all_perms or (
                self.config.data.get("permissions", {}).get("tool_execution_policy") == "always-proceed"
            )
            sys_instructions = self._build_context_brief(prompt_hint=prompt)

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

        # 4B. If Antigravity CLI (`agy`) is installed & enabled, run via `agy -p --output-format stream-json`!
        if self.agy_bin and self.config.data.get("agent", {}).get("use_agy_cli_fallback", True):
            agy_handled = await self._run_agy_cli_stream_json(
                prompt,
                on_thought,
                on_tool_call,
                on_token,
                on_complete,
                on_state_change,
                on_experience_event=on_experience_event,
                on_phase=on_phase,
            )
            if agy_handled:
                return

        # 5. Try Optional Gemini API / Local Ollama LLM with Resilient Do->Try/Catch->Verify Loop
        llm_reply = await self._try_external_llm_with_tools(
            prompt,
            on_thought,
            on_tool_call,
            on_token,
            on_complete,
            on_state_change,
            on_approval_needed,
            on_clarification_needed=on_clarification_needed,
            on_experience_event=on_experience_event,
            on_phase=on_phase,
        )
        if llm_reply:
            return

        # 6. Smart Shell Heuristic: if the prompt looks like a valid Linux command directly (e.g. "ls -la", "git status", "df -h", "uname -a")
        first_token = prompt.split()[0] if prompt.split() else ""
        if first_token in DIRECT_SHELL_COMMANDS:
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
        why = "\n".join(f"- {n}" for n in self._backend_notes) or "- No AI backend is configured."
        reply = (
            f"### ⚠️ I could not get an AI backend to answer that\n"
            f"{why}\n\n"
            f"### 🐾 Tchiko (`{telemetry['hostname']}`)\n"
            f"- **Working Dir:** `{cwd}` • **Memory Notes:** `{notes_count}`\n\n"
            f"These still work without an AI backend:\n"
            f"- **🔑 SSH & Remote Servers:** *\"create an ssh key for my hetzner server in OpenSSH format\"* or *\"add hetzner server 95.216.1.2 to ssh config\"*\n"
            f"- **🩺 System Doctor:** Type `/doctor` or *\"diagnose my system\"* for a 5-point Ubuntu health audit\n"
            f"- **⚙️ Ports & Processes:** *\"what is using port 8000\"*, *\"kill port 3000\"*, *\"what is eating my RAM\"*\n"
            f"- **📂 Files & Scaffolding:** *\"create a folder on Desktop named api and init git\"*, *\"find *.py in ~/Desktop\"*\n"
            f"- **🧠 Context & Memory:** *\"remember my hetzner ip is 95.216.10.20\"*, *\"copy it\"*, *\"retry\"*, or `/memory`\n"
            f"- **💻 Direct Bash:** Type `$ <command>` or `/run <command>`"
        )
        await self._stream_markdown(reply, on_token)
        on_state_change("alert")
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

        # ── A0. ANTIGRAVITY CODE IDE / VSCODE / APP CRASH DOCTOR & AUTO-HEAL ──
        if any(k in lower for k in ("antigravity", "agy", "code ide", "vscode", "vs code", "claude-desktop", "claude desktop")) and any(
            w in lower for w in ("crash", "crashing", "not working", "fix", "broken", "error", "won't start", "why")
        ):
            return await self._run_ide_crash_doctor(
                prompt, on_thought, on_tool_call, on_token, on_complete, on_state_change
            )

        # ── A1. APPLICATION & SYSTEM PACKAGE UPDATE / UPGRADE ─────────────────
        if any(w in lower for w in ("update", "upgrade", "reinstall")):
            if any(k in lower for k in ("claude-desktop", "claude desktop", "claude app")):
                return await self._run_app_update(
                    "claude-desktop", prompt, on_thought, on_tool_call, on_token, on_complete, on_state_change, on_approval_needed
                )
            m_pkg = re.search(
                r"(?:update|upgrade)\s+(?:and\s+(?:update|upgrade)\s+)?(?:the\s+)?['\"]?([a-zA-Z0-9_.-]+)['\"]?(?:\s+(?:app|application|package))?$",
                lower.strip(),
            )
            if m_pkg:
                target_pkg = m_pkg.group(1).strip()
                # Only take the apt shortcut for whole-system upgrades or a package dpkg actually
                # knows; "update the readme" and friends belong to the AI agent.
                is_system = target_pkg in ("system", "ubuntu", "all", "packages", "apt")
                if is_system or (
                    re.fullmatch(r"[a-z0-9][a-z0-9+.-]+", target_pkg)
                    and self.toolkit.run_shell_command(
                        f"dpkg -s {target_pkg} >/dev/null 2>&1", bypass_check=True
                    ).ok
                ):
                    return await self._run_app_update(
                        target_pkg, prompt, on_thought, on_tool_call, on_token, on_complete, on_state_change, on_approval_needed
                    )

        # ── A. SYSTEM DOCTOR / COMPREHENSIVE HEALTH DIAGNOSTIC ────────────────
        if len(prompt.split()) <= 8 and any(
            k in lower
            for k in (
                "diagnose my system", "diagnose system", "diagnose my pc", "diagnose this machine",
                "health check", "system doctor", "full check",
                "audit system", "check everything", "why is my pc slow",
            )
        ) or lower.strip() == "diagnose":
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
        # Generating a key rotates any existing one to `.bak`, so require an explicit ask for a key:
        # "ssh into my hetzner box" or "why can't I ssh" must reach the AI agent instead.
        ssh_create_words = ("create", "generate", "make", "new", "need")
        ssh_list_words = ("list", "show", "existing", "what are")
        if (
            re.search(r"\b(?:open)?ssh\b", lower)
            and re.search(r"\bkeys?\b|\bkeypair\b", lower)
            and any(re.search(rf"\b{w}\b", lower) for w in ssh_create_words + ssh_list_words)
            and len(prompt.split()) <= 20
        ):
            is_list_only = any(w in lower for w in ssh_list_words) and not any(
                re.search(rf"\b{w}\b", lower) for w in ssh_create_words
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
            if self.config.requires_manual_review(gen_cmd) and on_approval_needed is not None:
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
        """Map unambiguous short diagnostic Linux queries to instant shell commands, leaving complex/multi-step requests to the AI agent."""
        m_cmd = re.search(r"^(?:tchiko\s+)?(?:please\s+)?(?:run|execute)\s+[`'\"]?(.+?)[`'\"]?$", prompt.strip(), re.IGNORECASE)
        if m_cmd:
            cmd = m_cmd.group(1).strip()
            if not is_anaphoric_run_target(cmd):
                return (f"Executing command `{cmd}`:", cmd)

        # Do not intercept complex or multi-step action requests (install, configure, update, start, debug, fix, etc.)
        complex_action_verbs = (
            "install", "uninstall", "remove", "update", "upgrade", "configure", "config",
            "setup", "set up", "start", "restart", "enable", "disable", "fix", "repair",
            "debug", "why", "how to", "how do i", "deploy", "build", "compile", "clone",
            "write", "edit", "patch", "modify", "change", "add", "connect",
        )
        if any(re.search(rf"\b{re.escape(v)}\b", lower) for v in complex_action_verbs) or len(prompt.split()) > 12:
            return None

        m_port = re.search(r"\bport\s+(\d{2,5})\b", lower)
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

        if any(k in lower for k in ("public ip", "external ip", "my ip", "ip address", "network interfaces")):
            return (
                "Checking your local network interfaces and IP addresses:",
                "ip -br addr && echo '' && (curl -s --max-time 4 https://ifconfig.me && echo ' (Public IP)' || true)",
            )

        if any(k in lower for k in ("disk usage", "disk space", "free space", "df -h", "check disk", "check storage")):
            return ("Checking mounted filesystem disk usage (`df -h`):", "df -h -x tmpfs -x squashfs")

        if any(k in lower for k in ("big files", "largest files", "heavy files", "disk hog")):
            return ("Finding the 15 largest files/folders in your home directory:", "du -ah ~ 2>/dev/null | sort -rh | head -n 15")

        if any(k in lower for k in ("memory usage", "ram usage", "swap usage", "free -h", "check ram", "check memory")):
            return ("Checking system RAM and Swap allocation (`free -h`):", "free -h")

        if any(k in lower for k in ("docker ps", "running containers", "docker containers", "check docker", "list containers")):
            return (
                "Checking running Docker containers:",
                "docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' 2>&1",
            )

        if any(k in lower for k in ("git status", "git branch", "git log")):
            return ("Checking Git repository status:", "git status -sb && echo '' && git log -n 5 --oneline")

        if (
            any(k in lower for k in ("files on desktop", "list desktop", "show desktop", "~/desktop"))
            or (
                "desktop" in lower
                and any(w in lower for w in ("list", "show", "files", "folders", "what is on", "what's on"))
                and not any(w in lower for w in ("claude", "app"))
            )
        ):
            return ("Listing files on your Ubuntu Desktop (`~/Desktop`):", "ls -la ~/Desktop")

        if any(k in lower for k in ("check gpu", "gpu status", "nvidia-smi", "graphics card", "display card", "what gpu")):
            return (
                "Checking GPU & display hardware:",
                "lspci | grep -iE 'vga|3d|display' && (nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv 2>/dev/null || true)",
            )

        if any(k in lower for k in ("check cpu", "cpu info", "lscpu", "cpu cores", "what cpu")):
            return ("Checking CPU architecture and load:", "lscpu | grep -E 'Model name|Socket|Thread|NUMA|CPU\\(s\\)' && uptime")

        if any(k in lower for k in ("uptime", "kernel version", "uname", "os version", "ubuntu version")):
            return ("Checking Ubuntu OS version, kernel, and uptime:", "lsb_release -a 2>/dev/null || cat /etc/os-release; echo ''; uname -a; uptime -p")

        if any(k in lower for k in ("firewall status", "check firewall", "ufw status")):
            return ("Checking firewall status:", "ufw status verbose 2>&1 || iptables -L -n 2>&1 | head -n 20")

        if any(k in lower for k in ("failed service", "failed systemd", "check services", "running services", "systemctl status")):
            return (
                "Checking active and failed systemd services:",
                "systemctl --failed --no-pager && echo '' && systemctl list-units --type=service --state=running --no-pager | head -n 20",
            )

        if any(k in lower for k in ("installed tools", "dev tools", "check tools", "tool versions")):
            return (
                "Checking installed developer tool versions on Ubuntu:",
                "for cmd in python3 node npm git docker ssh go rustc gcc; do "
                "if command -v $cmd >/dev/null 2>&1; then printf '%-10s: ' $cmd && $cmd --version 2>&1 | head -n 1; fi; done",
            )

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

    async def _run_ide_crash_doctor(
        self,
        prompt: str,
        on_thought: Callable[[str], None],
        on_tool_call: Callable[[str, str], None],
        on_token: Callable[[str], None],
        on_complete: Callable[[str], None],
        on_state_change: Callable[[str], None],
    ) -> bool:
        """Run the 6-step autonomous application & IDE crash doctor and auto-repair pipeline."""
        on_state_change("executing")
        lower = prompt.lower()
        target_app = "Antigravity Code IDE"
        if "vscode" in lower or "vs code" in lower:
            target_app = "VS Code"

        def _on_step(step_msg: str, t_name: str, t_args: str) -> None:
            on_thought(step_msg)
            if t_name:
                on_tool_call(t_name, t_args)

        res = await asyncio.to_thread(self.toolkit.diagnose_and_heal_app, target_app, _on_step)
        await self._stream_markdown(res.output, on_token)
        on_state_change("happy" if res.ok else "alert")
        on_complete(res.output)
        return True

    async def _run_app_update(
        self,
        app_target: str,
        prompt: str,
        on_thought: Callable[[str], None],
        on_tool_call: Callable[[str, str], None],
        on_token: Callable[[str], None],
        on_complete: Callable[[str], None],
        on_state_change: Callable[[str], None],
        on_approval_needed: Optional[Callable[[str, Callable[[], None], Callable[[], None]], None]],
    ) -> bool:
        """Inspect installed version vs upstream repo and upgrade the requested application/package."""
        on_state_change("executing")
        slug = app_target.lower().strip()

        if "claude" in slug:
            on_thought("Step 1/3: Checking installed `claude-desktop-unofficial` version and upstream APT repository...")
            on_tool_call("check_package_version", "{'package': 'claude-desktop-unofficial'}")
            check_cmd = (
                "dpkg-query -W -f='${Version}' claude-desktop-unofficial 2>/dev/null || echo 'not-installed'"
            )
            cur_ver = self.toolkit.run_shell_command(check_cmd, bypass_check=True).output.strip()

            repo_cmd = (
                "curl -fsSL --max-time 8 https://pkg.claude-desktop-debian.dev/dists/stable/main/binary-amd64/Packages "
                "| awk '/^Package: claude-desktop-unofficial$/,/^$/' "
                "| awk '/^Version:/ {v=$2} /^Filename:/ {f=$2} END {print v \"|\" f}'"
            )
            repo_info = self.toolkit.run_shell_command(repo_cmd, bypass_check=True).output.strip()
            latest_ver, deb_rel_path = (repo_info.split("|", 1) + [""])[:2] if "|" in repo_info else ("", "")

            disabled_list = Path("/etc/apt/sources.list.d/claude-desktop.list.disabled")
            active_list = Path("/etc/apt/sources.list.d/claude-desktop.list")
            repo_note = ""
            if disabled_list.exists() and not active_list.exists():
                repo_note = (
                    "- ⚠️ **APT Source Note:** `/etc/apt/sources.list.d/claude-desktop.list.disabled` was disabled during a previous Ubuntu upgrade, preventing standard `apt upgrade` from seeing new releases.\n"
                )

            if latest_ver and deb_rel_path:
                deb_url = f"https://pkg.claude-desktop-debian.dev/{deb_rel_path.lstrip('/')}"
                deb_file = f"/tmp/claude-desktop-unofficial_{latest_ver}_amd64.deb"

                if cur_ver == latest_ver:
                    report = (
                        f"### ✅ Claude Desktop is Already Up to Date!\n"
                        f"- **Installed Version:** `{cur_ver}` (`claude-desktop-unofficial`)\n"
                        f"- **Latest Upstream Version:** `{latest_ver}`\n"
                    )
                    await self._stream_markdown(report, on_token)
                    on_state_change("happy")
                    on_complete(report)
                    return True

                on_thought(f"Step 2/3: Ensuring `claude-desktop-unofficial` `{latest_ver}` `.deb` package is downloaded...")
                on_tool_call("download_deb", f"{{'url': {deb_url!r}, 'dest': {deb_file!r}}}")
                dl_res = await asyncio.to_thread(
                    self.toolkit.run_shell_command,
                    f"if [ ! -s '{deb_file}' ]; then curl -fL --max-time 60 -o '{deb_file}' '{deb_url}'; fi && ls -lh '{deb_file}'",
                    timeout=70,
                )

                on_thought("Step 3/3: Installing `.deb` package and re-enabling APT repository via `pkexec` / `sudo`...")
                upgrade_cmd = (
                    f"pkexec sh -c \""
                    f"if [ -f /etc/apt/sources.list.d/claude-desktop.list.disabled ]; then "
                    f"sed 's/^# deb /deb /' /etc/apt/sources.list.d/claude-desktop.list.disabled > /etc/apt/sources.list.d/claude-desktop.list && "
                    f"rm -f /etc/apt/sources.list.d/claude-desktop.list.disabled; fi && "
                    f"apt-get install -y '{deb_file}' || dpkg -i '{deb_file}'\""
                )
                on_tool_call("install_package", f"{{'package': 'claude-desktop-unofficial', 'version': {latest_ver!r}}}")
                inst_res = await asyncio.to_thread(
                    self.toolkit.run_shell_command,
                    upgrade_cmd,
                    timeout=120,
                )

                new_ver = self.toolkit.run_shell_command(check_cmd, bypass_check=True).output.strip()
                if inst_res.ok and new_ver == latest_ver:
                    report = (
                        f"### 🚀 Claude Desktop Upgraded Successfully!\n"
                        f"- **Previous Version:** `{cur_ver}`\n"
                        f"- **New Installed Version:** `{new_ver}`\n"
                        f"{repo_note}"
                        f"- **APT Repository:** Re-enabled `/etc/apt/sources.list.d/claude-desktop.list` for future automatic updates.\n\n"
                        f"**Installation Output:**\n```text\n{inst_res.output[-1200:]}\n```"
                    )
                    await self._stream_markdown(report, on_token)
                    on_state_change("happy")
                    on_complete(report)
                    return True
                else:
                    manual_cmd = (
                        f"sudo sed 's/^# deb /deb /' /etc/apt/sources.list.d/claude-desktop.list.disabled "
                        f"| sudo tee /etc/apt/sources.list.d/claude-desktop.list >/dev/null && "
                        f"sudo rm -f /etc/apt/sources.list.d/claude-desktop.list.disabled && "
                        f"sudo apt install -y {deb_file}"
                    )
                    self.memory["last_artifact_path"] = deb_file
                    self.memory["last_artifact_content"] = manual_cmd
                    self._save_memory()
                    report = (
                        f"### 📦 Claude Desktop Update Ready (`{cur_ver}` → `{latest_ver}`)\n"
                        f"- **Installed Version:** `{cur_ver}` (`claude-desktop-unofficial`)\n"
                        f"- **Latest Available Version:** `{latest_ver}`\n"
                        f"- **Downloaded Package:** `{deb_file}` ({'✅ Ready' if dl_res.ok else '⚠️ Download failed'})\n"
                        f"{repo_note}\n"
                        f"**Complete Installation (requires `sudo` password in terminal):**\n"
                        f"```bash\nsudo apt install -y {deb_file}\n```\n"
                        f"*(Or to also re-enable automatic APT updates:)*\n"
                        f"```bash\n{manual_cmd}\n```"
                    )
                    await self._stream_markdown(report, on_token)
                    on_state_change("happy" if dl_res.ok else "alert")
                    on_complete(report)
                    return True

        # Generic Linux package / system update
        if slug in ("system", "ubuntu", "all", "packages", "apt"):
            cmd = "pkexec sh -c 'apt-get update && apt-get upgrade -y' || (apt list --upgradable 2>/dev/null | head -n 30)"
            await self._run_and_report(
                "Checking and upgrading Ubuntu system packages:",
                cmd,
                on_thought,
                on_tool_call,
                on_token,
                on_complete,
                on_state_change,
                on_approval_needed,
            )
            return True

        cmd = (
            f"dpkg -l | grep -i {slug!r} || true; "
            f"apt-cache policy {slug!r} 2>/dev/null || true; "
            f"pkexec apt-get install --only-upgrade -y {slug!r} 2>&1 || echo 'Run: sudo apt update && sudo apt install --only-upgrade {slug}'"
        )
        await self._run_and_report(
            f"Updating package `{app_target}`:",
            cmd,
            on_thought,
            on_tool_call,
            on_token,
            on_complete,
            on_state_change,
            on_approval_needed,
        )
        return True

    async def _run_agy_cli_stream_json(
        self,
        prompt: str,
        on_thought: Callable[[str], None],
        on_tool_call: Callable[[str, str], None],
        on_token: Callable[[str], None],
        on_complete: Callable[[str], None],
        on_state_change: Callable[[str], None],
        on_experience_event: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        on_phase: Optional[Callable[[str, str], None]] = None,
    ) -> bool:
        """Answer via the Antigravity CLI (`agy -p --output-format stream-json`).

        A recent conversation is resumed; otherwise (or if resuming fails) a fresh one is started
        with the full context briefing. Returns False only when nothing was said or done, so a
        weaker backend never repeats work the agent already performed.
        """
        if not self.agy_bin or not os.path.exists(self.agy_bin):
            return False

        prev_conv_id = str(self.memory.get("agy_conversation_id", "") or "")
        last_used = float(self.memory.get("agy_conversation_ts", 0) or 0)
        resumable = bool(prev_conv_id) and (time.time() - last_used) < AGY_SESSION_MAX_IDLE_SEC
        attempts = [prev_conv_id, ""] if resumable else [""]

        last_error = "no response"
        for conv_id in attempts:
            status, text, error, episode = await self._agy_turn(
                prompt, conv_id, on_thought, on_tool_call, on_token, on_state_change
            )
            if status == "ok":
                if episode.get("steps"):
                    self.last_episode = episode
                    learned_note = await self._maybe_auto_learn(episode, on_phase, on_experience_event)
                    if learned_note:
                        await self._stream_markdown("\n\n" + learned_note, on_token)
                        text = (text + "\n\n" + learned_note).strip()
                on_state_change("happy")
                on_complete(text)
                return True
            if status == "partial":
                note = f"\n\n⚠️ **The agent stopped before finishing:** {error}\n"
                on_token(note)
                on_state_change("alert")
                on_complete((text + note).strip())
                return True
            last_error = error
            self.memory["agy_conversation_id"] = ""
            self.memory["agy_conversation_ts"] = 0
            self._save_memory()
            if conv_id:
                on_thought("Could not resume the previous agent session; starting a fresh one...")

        self._backend_notes.append(f"**Antigravity CLI (`agy`):** {last_error}")
        on_thought(f"Antigravity CLI unavailable ({last_error[:120]}); trying the next backend...")
        return False

    async def _agy_turn(
        self,
        prompt: str,
        conv_id: str,
        on_thought: Callable[[str], None],
        on_tool_call: Callable[[str, str], None],
        on_token: Callable[[str], None],
        on_state_change: Callable[[str], None],
    ) -> Tuple[str, str, str, Dict[str, Any]]:
        """Run one `agy` turn. Returns (status, text, error, episode) with status ok | partial | failed.

        `partial` means the agent already streamed text or ran tools before failing.
        """
        active_cwd = self.memory.get("cwd", str(Path.home()))
        if not os.path.isdir(active_cwd):
            active_cwd = str(Path.home())

        # A resumed conversation already holds the briefing; a new one gets it up front so the
        # first request lands with the machine, memory, matching Experiences, and rules already known.
        agent_prompt = (
            prompt
            if conv_id
            else f"{self._build_context_brief(prompt_hint=prompt)}\n\nUser request:\n{prompt}"
        )
        cmd_args = [
            str(self.agy_bin), "-p", agent_prompt,
            "--output-format", "stream-json",
            "--add-dir", active_cwd,
        ]
        if self.config.is_all_permissions_approved() or not self.config.requires_manual_review():
            cmd_args.append("--dangerously-skip-permissions")
        if conv_id:
            cmd_args.extend(["--conversation", conv_id])

        on_thought("Continuing with the Antigravity agent..." if conv_id else "Briefing the Antigravity agent...")
        tokens: List[str] = []
        final_response_text = ""
        tools_ran = 0
        captured_steps: List[Dict[str, Any]] = []
        last_text_step: Any = None
        error = ""
        denied: List[str] = []
        proc = None
        stderr_task: Optional["asyncio.Task[bytes]"] = None
        started = time.monotonic()

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd_args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=active_cwd,
                limit=32 * 1024 * 1024,  # tool-output events can be far larger than the 64 KB default
            )
            assert proc.stdout is not None and proc.stderr is not None
            stderr_task = asyncio.create_task(proc.stderr.read())

            while True:
                line_bytes = await asyncio.wait_for(
                    proc.stdout.readline(), timeout=AGY_EVENT_IDLE_TIMEOUT_SEC
                )
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace").strip()
                if not line.startswith("{"):
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue

                ev_type = ev.get("event")
                if ev_type == "init":
                    new_id = ev.get("conversation_id", "")
                    if new_id:
                        self.memory["agy_conversation_id"] = new_id
                        self.memory["agy_conversation_ts"] = int(time.time())
                        self._save_memory()

                elif ev_type == "step_update":
                    su = ev.get("step_update", {})
                    step_type = su.get("step_type", "")
                    state = su.get("state", "")
                    if step_type == "tool":
                        t_info = su.get("tool_info", {})
                        t_name = su.get("tool_name") or t_info.get("name", "tool")
                        params_obj = t_info.get("parameters", {}) or {}
                        param_str = json.dumps(params_obj)[:160]
                        t_out = t_info.get("output", "")
                        if state == "ACTIVE":
                            tools_ran += 1
                            on_state_change("executing")
                            on_tool_call(t_name, param_str)
                            on_thought(f"Executing `{t_name}`: {param_str}")
                        elif state == "DONE":
                            if t_out:
                                on_thought(f"Completed `{t_name}` → {str(t_out)[:120]}")
                            cmd_val = ""
                            if isinstance(params_obj, dict):
                                cmd_val = str(
                                    params_obj.get("CommandLine")
                                    or params_obj.get("command")
                                    or params_obj.get("cmd")
                                    or ""
                                ).strip()
                            if cmd_val:
                                captured_steps.append({
                                    "step_index": len(captured_steps) + 1,
                                    "phase": "ACT",
                                    "tool": "bash",
                                    "args_summary": cmd_val,
                                    "ok": "exit code 0" in str(t_out).lower() or "error" not in str(t_out).lower()[:120],
                                })
                    elif step_type == "agent_response":
                        delta = su.get("text_delta", "")
                        if delta:
                            step_idx = su.get("step_index")
                            if tokens and step_idx != last_text_step and not tokens[-1].endswith("\n"):
                                tokens.append("\n\n")
                                on_token("\n\n")
                            last_text_step = step_idx
                            tokens.append(delta)
                            on_token(delta)

                elif ev_type == "result":
                    res_obj = ev.get("result", {})
                    final_response_text = res_obj.get("response", "") or ""
                    denied = [
                        str(d.get("display_name") or d.get("action") or "tool")
                        for d in res_obj.get("denied_actions", []) or []
                    ]

            await asyncio.wait_for(proc.wait(), timeout=15.0)
        except asyncio.TimeoutError:
            error = f"no activity from `agy` for {int(AGY_EVENT_IDLE_TIMEOUT_SEC // 60)} minutes, so it was stopped"
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        finally:
            if proc is not None and proc.returncode is None:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass

        stderr_text = ""
        if stderr_task is not None:
            try:
                stderr_text = (await asyncio.wait_for(stderr_task, timeout=5.0)).decode("utf-8", errors="replace")
            except Exception:
                stderr_task.cancel()
        stderr_tail = next((ln.strip() for ln in reversed(stderr_text.splitlines()) if ln.strip()), "")[:400]

        if not error and proc is not None and proc.returncode not in (0, None):
            error = stderr_tail or f"`agy` exited with code {proc.returncode}"
        if not error and denied:
            error = (
                f"permission denied for {', '.join(sorted(set(denied)))} — Tchiko is in review mode; "
                "enable 'Grant All System Permissions' in Settings (or `/grant-all`) to let the agent act"
            )

        combined = "".join(tokens).strip() or final_response_text.strip()
        episode = {
            "prompt": prompt,
            "steps": captured_steps,
            "succeeded": bool(combined and not error),
            "verified": bool(combined and not error and len(captured_steps) >= 2),
            "recoveries_succeeded": 0,
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
        if combined and not error:
            if not tokens:
                await self._stream_markdown(final_response_text, on_token)
            self.memory["agy_conversation_ts"] = int(time.time())
            self._save_memory()
            return "ok", combined, "", episode
        if combined or tools_ran:
            return "partial", combined, error or stderr_tail or "it returned no final answer", episode
        return "failed", "", error or stderr_tail or "it returned an empty response", episode

    async def _maybe_auto_learn(
        self,
        episode: Dict[str, Any],
        on_phase: Optional[Callable[[str, str], None]] = None,
        on_experience_event: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Optional[str]:
        """Distill a verified multi-step episode into a reusable Python Experience when auto-learning is enabled."""
        learning_cfg = self.config.data.get("learning", {})
        if not bool(learning_cfg.get("auto_learn_experiences", True)):
            return None
        exp, msg = await asyncio.to_thread(self.experiences.learn_from_episode, episode)
        if exp is None:
            return None
        if on_phase is not None:
            try:
                on_phase("LEARN", f"Distilled Python experience `{exp.slug}` v{exp.version} ({exp.maturity})")
            except Exception:
                pass
        if on_experience_event is not None:
            try:
                on_experience_event({
                    "event": "learned",
                    "slug": exp.slug,
                    "title": exp.title,
                    "version": exp.version,
                    "maturity": exp.maturity,
                    "risk_tier": exp.risk_tier,
                    "message": msg,
                })
            except Exception:
                pass
        return (
            f"🧠 **Learned Reusable Experience:** `{exp.slug}` `v{exp.version}` "
            f"[{exp.maturity}] — saved as Python tool in `experiences/{exp.slug}/tool.py`. "
            f"Inspect or run it anytime in the **Experiences** tab or via `/exp run {exp.slug}`."
        )

    @staticmethod
    def _strip_think_blocks(raw_text: str) -> Tuple[str, List[str]]:
        """Extract <think>...</think> and <channel|> blocks cleanly so internal reasoning or hallucinated <output> tags never leak into chat output."""
        thoughts: List[str] = []
        text = raw_text
        if "<channel|>" in text:
            parts = text.split("<channel|>", 1)
            if parts[0].strip():
                thoughts.append(parts[0].strip())
            text = parts[1]
        for m in re.finditer(r"<think>(.*?)</think>", text, flags=re.DOTALL | re.IGNORECASE):
            t_body = m.group(1).strip()
            if t_body:
                thoughts.append(t_body)
        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
        if "<think>" in cleaned.lower():
            idx = cleaned.lower().find("<think>")
            tail_thought = cleaned[idx + 7 :].strip()
            if tail_thought:
                thoughts.append(tail_thought)
            cleaned = cleaned[:idx]
        # Strip hallucinated <output>...</output> blocks that some local models emit instead of waiting for real tool execution
        cleaned = re.sub(r"<output>.*?</output>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
        return cleaned.strip(), thoughts

    @staticmethod
    def _extract_valid_bash_commands(clean_text: str) -> List[str]:
        """Extract executable bash commands from <bash>...</bash> outside <think> blocks, ignoring placeholders."""
        commands: List[str] = []
        placeholders = {
            "command", "your_command", "your_command_here", "<command>",
            "bash_command", "cmd", "ls /path/to/...",
        }
        for m in re.finditer(r"<bash>(.*?)</bash>", clean_text, flags=re.DOTALL | re.IGNORECASE):
            cmd = m.group(1).strip()
            if not cmd or cmd.lower() in placeholders:
                continue
            commands.append(cmd)
        return commands

    @classmethod
    def _extract_tool_actions(cls, clean_text: str) -> List[Dict[str, Any]]:
        """Extract multi-tool calls (`view_file`, `grep`, `patch_file`, `write_file`, `experience`, `bash`, etc.) from LLM output."""
        actions: List[Dict[str, Any]] = []

        # 1. <view_file path="..." start="1" end="120" /> or <view_file path="...">
        for m in re.finditer(
            r'<view_file\s+path=["\']([^"\']+)["\'](?:\s+start=["\']?(\d+)["\']?)?(?:\s+end=["\']?(\d+)["\']?)?\s*/?>',
            clean_text,
            flags=re.IGNORECASE,
        ):
            actions.append(
                {
                    "tool": "view_file",
                    "path": m.group(1),
                    "start": int(m.group(2) or 1),
                    "end": int(m.group(3) or 120),
                }
            )

        # 2. <grep pattern="..." path="..." />
        for m in re.finditer(
            r'<grep\s+pattern=["\']([^"\']+)["\'](?:\s+path=["\']([^"\']+)["\'])?\s*/?>',
            clean_text,
            flags=re.IGNORECASE,
        ):
            actions.append(
                {
                    "tool": "grep",
                    "pattern": m.group(1),
                    "path": m.group(2) or "~",
                }
            )

        # 3. <patch_file path="..."><search>...</search><replace>...</replace></patch_file>
        for m in re.finditer(
            r'<patch_file\s+path=["\']([^"\']+)["\']>\s*<search>(.*?)</search>\s*<replace>(.*?)</replace>\s*</patch_file>',
            clean_text,
            flags=re.DOTALL | re.IGNORECASE,
        ):
            actions.append(
                {
                    "tool": "patch_file",
                    "path": m.group(1),
                    "search": m.group(2),
                    "replace": m.group(3),
                }
            )

        # 4. <write_file path="...">...</write_file>
        for m in re.finditer(
            r'<write_file\s+path=["\']([^"\']+)["\']>(.*?)</write_file>',
            clean_text,
            flags=re.DOTALL | re.IGNORECASE,
        ):
            actions.append(
                {
                    "tool": "write_file",
                    "path": m.group(1),
                    "content": m.group(2).strip("\n"),
                }
            )

        # 5. <containers target="..." />
        for m in re.finditer(
            r'<containers(?:\s+target=["\']([^"\']*)["\'])?\s*/?>',
            clean_text,
            flags=re.IGNORECASE,
        ):
            actions.append({"tool": "containers", "target": (m.group(1) or "").strip()})

        # 6. <systemd unit="..." lines="40" />
        for m in re.finditer(
            r'<systemd(?:\s+unit=["\']([^"\']*)["\'])?(?:\s+lines=["\']?(\d+)["\']?)?\s*/?>',
            clean_text,
            flags=re.IGNORECASE,
        ):
            actions.append(
                {
                    "tool": "systemd",
                    "unit": (m.group(1) or "").strip(),
                    "lines": int(m.group(2) or 40),
                }
            )

        # 7. <network_audit />
        if re.search(r'<network_audit\s*/?>', clean_text, flags=re.IGNORECASE):
            actions.append({"tool": "network_audit"})

        # 8. <disk />
        if re.search(r'<disk\s*/?>', clean_text, flags=re.IGNORECASE):
            actions.append({"tool": "disk"})

        # 9. <gpu />
        if re.search(r'<gpu\s*/?>', clean_text, flags=re.IGNORECASE):
            actions.append({"tool": "gpu"})

        # 10. <tls host="..." />
        for m in re.finditer(
            r'<tls\s+host=["\']([^"\']+)["\']\s*/?>',
            clean_text,
            flags=re.IGNORECASE,
        ):
            actions.append({"tool": "tls", "host": m.group(1).strip()})

        # 11. <git path="..." />
        for m in re.finditer(
            r'<git(?:\s+path=["\']([^"\']*)["\'])?\s*/?>',
            clean_text,
            flags=re.IGNORECASE,
        ):
            actions.append({"tool": "git", "path": (m.group(1) or ".").strip()})

        # 12. <experience name="slug" params='{"k":"v"}' /> or <experience name="slug">{...}</experience>
        for m in re.finditer(
            r'<experience\s+name=["\']([^"\']+)["\'](?:\s+params=(?:"([^"]*)"|\'([^\']*)\'))?\s*(?:/>|>(.*?)</experience>)',
            clean_text,
            flags=re.DOTALL | re.IGNORECASE,
        ):
            raw_params = (m.group(2) or m.group(3) or m.group(4) or "").strip()
            parsed_params: Dict[str, Any] = {}
            if raw_params:
                try:
                    loaded = json.loads(raw_params)
                    if isinstance(loaded, dict):
                        parsed_params = loaded
                except Exception:
                    parsed_params = {}
            actions.append({"tool": "experience", "name": m.group(1).strip(), "params": parsed_params})

        # 13. <bash>...</bash>
        for cmd in cls._extract_valid_bash_commands(clean_text):
            actions.append({"tool": "bash", "command": cmd})

        return actions

    async def _try_external_llm_with_tools(
        self,
        prompt: str,
        on_thought: Callable[[str], None],
        on_tool_call: Callable[[str, str], None],
        on_token: Callable[[str], None],
        on_complete: Callable[[str], None],
        on_state_change: Callable[[str], None],
        on_approval_needed: Optional[Callable[[str, Callable[[], None], Callable[[], None]], None]],
        on_clarification_needed: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_experience_event: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_phase: Optional[Callable[[str, str], None]] = None,
    ) -> bool:
        """Run the resilient Do -> Observe -> Try/Catch & Recover -> Verify loop against Gemini or Ollama."""
        matched_skills = self.skills.match_skills(prompt)
        skills_block = ""
        if matched_skills:
            skills_block = "\n\nRelevant Runbooks:\n" + "\n\n".join(
                f"### Skill: {s.name}\n{s.body}" for s in matched_skills
            )

        sys_prompt = (
            self._build_context_brief(include_history=False, prompt_hint=prompt) + skills_block + "\n\n"
            "Tools. To act, end your message with tool tags, then stop and wait. "
            "Read-only tools can be batched together; mutating tools run one at a time.\n"
            "- Run a shell command: <bash>ls -la ~/.config</bash> (use `<bash>pkexec ...</bash>` for root, never `<pkexec>`)\n"
            "- Run a learned Python Experience tool: <experience name=\"port-socket-inspector\" params='{\"port\": 8000}' />\n"
            "- Ask the user a concise clarifying question before acting (when ambiguous/underspecified):\n"
            "  <ask_user question=\"Which target should I operate on?\" reason=\"Short reason\"><option>Option A</option><option>Option B</option></ask_user>\n"
            "- View file lines: <view_file path=\"/path/to/file\" start=\"1\" end=\"120\" />\n"
            "- Search logs/code: <grep pattern=\"error\" path=\"/path/to/dir\" />\n"
            "- Patch a file (snapshot saved for /undo): <patch_file path=\"/path/to/file\"><search>old</search><replace>new</replace></patch_file>\n"
            "- Write a file: <write_file path=\"/path/to/file\">content</write_file>\n"
            "- Inspect containers: <containers target=\"\" />\n"
            "- Inspect systemd unit: <systemd unit=\"\" lines=\"40\" />\n"
            "- Network & firewall audit: <network_audit />\n"
            "- Disk & inode audit: <disk />\n"
            "- GPU & Ollama/vLLM health: <gpu />\n"
            "- DNS & TLS cert check: <tls host=\"example.com\" />\n"
            "- Git repo status: <git path=\".\" />\n\n"
            "Tool & Recovery rules:\n"
            "- Use real values, never placeholders, and never place tool tags inside <think> blocks.\n"
            "- Never write a command's output yourself (no <output> blocks, no pretend logs). Only tool results are real.\n"
            "- If a tool returns a `[TRY/CATCH]` error block, follow its recovery guidance instead of repeating the same command.\n"
            "- After making a change, run a quick read-only verification check before declaring success.\n"
            "- Use absolute paths or paths starting with `~`.\n"
            "- When the task is finished or cannot proceed, reply with a short summary and no tool tag."
        )

        # Real multi-turn context: earlier chat turns, then the current request (history[-1]).
        messages: List[Dict[str, str]] = []
        for turn in self.memory.get("history", [])[:-1][-6:]:
            role = "assistant" if turn.get("role") == "assistant" else "user"
            content = str(turn.get("content", "")).strip()
            if not content:
                continue
            if messages and messages[-1]["role"] == role:
                messages[-1]["content"] += "\n\n" + content
            else:
                messages.append({"role": role, "content": content})
        if messages and messages[-1]["role"] == "user":
            messages[-1]["content"] += "\n\n" + prompt
        else:
            messages.append({"role": "user", "content": prompt})

        agent_cfg = self.config.data.get("agent", {})
        learning_cfg = self.config.data.get("learning", {})
        gemini_key = (os.getenv("GEMINI_API_KEY") or agent_cfg.get("gemini_api_key", "")).strip()
        has_gemini = bool(gemini_key) and gemini_key != "your_gemini_api_key_here"
        ollama_target: List[Any] = []  # [port, model] once a local server has been found

        async def _query_llm(cur_messages: List[Dict[str, str]]) -> Optional[str]:
            if has_gemini:
                on_thought("Thinking with Gemini 2.5 Flash...")
                res_txt = await asyncio.to_thread(self._call_gemini_rest, gemini_key, sys_prompt, cur_messages)
                if res_txt:
                    return res_txt
                self._backend_notes.append("**Gemini API:** request failed or returned nothing.")
            if not ollama_target:
                for port in (11434, 11435):
                    models = await asyncio.to_thread(self._list_ollama_models, port)
                    model = self._pick_ollama_model(models, str(agent_cfg.get("ollama_model", "")))
                    if model:
                        ollama_target.extend([port, model])
                        break
            if not ollama_target:
                self._backend_notes.append(
                    "**Local Ollama:** no server with a chat model on ports 11434/11435 (`ollama serve`)."
                )
                return None
            port, model = ollama_target
            on_thought(f"Thinking with local model `{model}`...")
            res_txt = await asyncio.to_thread(self._call_local_ollama, port, model, sys_prompt, cur_messages)
            if not res_txt:
                self._backend_notes.append(f"**Local Ollama (`{model}`):** no reply (timed out or errored).")
            return res_txt

        async def _run_single_action(act: Dict[str, Any]) -> Tuple[str, ToolResult]:
            cwd_snap = self.memory.get("cwd", str(Path.home()))
            tk = act["tool"]
            if tk == "view_file":
                path = self._resolve_user_path(act["path"])
                on_tool_call("view_file", f"{{'path': {path!r}, 'lines': '{act['start']}-{act['end']}'}}")
                return tk, await asyncio.to_thread(self.toolkit.view_file_lines, path, act["start"], act["end"])
            if tk == "grep":
                path = self._resolve_user_path(act["path"])
                on_tool_call("grep_files", f"{{'pattern': {act['pattern']!r}, 'path': {path!r}}}")
                return tk, await asyncio.to_thread(self.toolkit.grep_files, act["pattern"], path)
            if tk == "patch_file":
                path = self._resolve_user_path(act["path"])
                on_tool_call("patch_file_content", f"{{'path': {path!r}}}")
                return tk, await asyncio.to_thread(
                    self.toolkit.patch_file_content, path, act["search"], act["replace"], True
                )
            if tk == "write_file":
                path = self._resolve_user_path(act["path"])
                on_tool_call("write_file_content", f"{{'path': {path!r}}}")
                return tk, await asyncio.to_thread(self.toolkit.write_file_content, path, act["content"], True)
            if tk == "containers":
                on_tool_call("diagnose_containers", f"{{'target': {act['target']!r}}}")
                return tk, await asyncio.to_thread(self.toolkit.diagnose_containers, act["target"])
            if tk == "systemd":
                on_tool_call("inspect_systemd_unit", f"{{'unit': {act['unit']!r}, 'lines': {act['lines']}}}")
                return tk, await asyncio.to_thread(self.toolkit.inspect_systemd_unit, act["unit"], act["lines"])
            if tk == "network_audit":
                on_tool_call("audit_network_security", "{}")
                return tk, await asyncio.to_thread(self.toolkit.audit_network_security)
            if tk == "disk":
                on_tool_call("audit_disk_and_inodes", "{}")
                return tk, await asyncio.to_thread(self.toolkit.audit_disk_and_inodes)
            if tk == "gpu":
                on_tool_call("diagnose_gpu_and_ai", "{}")
                return tk, await asyncio.to_thread(self.toolkit.diagnose_gpu_and_ai)
            if tk == "tls":
                on_tool_call("diagnose_dns_and_tls", f"{{'host': {act['host']!r}}}")
                return tk, await asyncio.to_thread(self.toolkit.diagnose_dns_and_tls, act["host"])
            if tk == "git":
                path = self._resolve_user_path(act["path"])
                on_tool_call("inspect_git_repo", f"{{'path': {path!r}}}")
                return tk, await asyncio.to_thread(self.toolkit.inspect_git_repo, path)
            if tk == "experience":
                exp_slug = act["name"]
                exp_params = act.get("params") or {}
                exp = self.experiences.get_experience(exp_slug)
                if exp is None:
                    return tk, ToolResult(
                        ok=False,
                        title="Experience Not Found",
                        output=f"No experience named `{exp_slug}` exists.",
                        exit_code=127,
                    )
                needs_review = (
                    exp.risk_tier != "SAFE_READONLY"
                    and not self.config.is_all_permissions_approved()
                    and self.config.data.get("permissions", {}).get("tool_execution_policy") != "always-proceed"
                )
                if needs_review and on_approval_needed is not None:
                    loop = asyncio.get_running_loop()
                    approval_fut: asyncio.Future[bool] = loop.create_future()
                    on_state_change("thinking")
                    label = f"experience:{exp.slug} ({exp.risk_tier})"
                    on_token(f"🔒 **Approval Required** for Python Experience `{exp.slug}` (`{exp.risk_tier}`)...\n")

                    def _approve_exp() -> None:
                        if not approval_fut.done():
                            loop.call_soon_threadsafe(approval_fut.set_result, True)

                    def _deny_exp() -> None:
                        if not approval_fut.done():
                            loop.call_soon_threadsafe(approval_fut.set_result, False)

                    on_approval_needed(label, _approve_exp, _deny_exp)
                    if not await approval_fut:
                        return tk, ToolResult(
                            ok=False,
                            title="Experience Cancelled",
                            output=f"User denied execution of experience `{exp.slug}`.",
                            exit_code=126,
                        )
                    on_state_change("executing")

                on_tool_call("run_experience", f"{{'slug': {exp.slug!r}, 'params': {exp_params!r}}}")
                res_exp = await asyncio.to_thread(self.experiences.run_experience, exp.slug, exp_params)
                if on_experience_event is not None:
                    try:
                        updated_exp = self.experiences.get_experience(exp.slug) or exp
                        on_experience_event({
                            "event": "used",
                            "slug": updated_exp.slug,
                            "title": updated_exp.title,
                            "version": updated_exp.version,
                            "maturity": updated_exp.maturity,
                            "ok": res_exp.ok,
                        })
                    except Exception:
                        pass
                return tk, res_exp

            cmd = act["command"]
            if self.config.requires_manual_review(cmd) and on_approval_needed is not None:
                loop = asyncio.get_running_loop()
                approval_fut = loop.create_future()
                on_state_change("thinking")
                on_token(f"🔒 **Approval Required** for `{cmd}`...\n")

                def _approve() -> None:
                    if not approval_fut.done():
                        loop.call_soon_threadsafe(approval_fut.set_result, True)

                def _deny() -> None:
                    if not approval_fut.done():
                        loop.call_soon_threadsafe(approval_fut.set_result, False)

                on_approval_needed(cmd, _approve, _deny)
                approved = await approval_fut
                if not approved:
                    return tk, ToolResult(
                        ok=False,
                        title="Command Cancelled",
                        output=f"User denied execution of `{cmd}`.",
                        exit_code=126,
                    )
                on_state_change("executing")
                res_cmd = await asyncio.to_thread(
                    self.toolkit.run_shell_command, cmd, cwd_snap, LLM_TOOL_BASH_TIMEOUT_SEC, True
                )
            else:
                on_tool_call("run_shell_command", f"{{'command': {cmd!r}, 'cwd': {cwd_snap!r}}}")
                res_cmd = await asyncio.to_thread(
                    self.toolkit.run_shell_command, cmd, cwd_snap, LLM_TOOL_BASH_TIMEOUT_SEC
                )
            self.memory["last_command"] = cmd
            self.memory["last_output"] = res_cmd.output
            self._save_memory()
            return tk, res_cmd

        agent_loop = ResilientAgentLoop(
            query_llm=_query_llm,
            strip_think=self._strip_think_blocks,
            extract_actions=self._extract_tool_actions,
            execute_action=_run_single_action,
            rollback_tx=self.toolkit.rollback_transaction,
            on_thought=on_thought,
            on_token=on_token,
            on_state_change=on_state_change,
            on_phase=on_phase,
            stream_markdown=self._stream_markdown,
            max_steps=int(learning_cfg.get("max_loop_steps", LLM_MAX_TOOL_STEPS) or LLM_MAX_TOOL_STEPS),
            auto_rollback=bool(learning_cfg.get("auto_rollback_on_failure", False)),
        )
        handled, trace = await agent_loop.run(prompt, messages)
        if not handled:
            return False

        # Save structured episode for manual `/learn` or automatic Experience distillation
        episode = trace.to_episode_dict()
        self.last_episode = episode

        if trace.asked_user is not None:
            clar = trace.asked_user
            self.memory["pending_task"] = PendingTask(
                original_prompt=prompt,
                question=clar.question,
                options=clar.options,
                reason=clar.reason,
                created_at=time.time(),
            ).to_dict()
            self._save_memory()
            if on_clarification_needed is not None:
                try:
                    on_clarification_needed(clar.to_dict())
                except Exception:
                    pass
            on_complete(trace.final_text)
            return True

        final_summary = trace.final_text or "Completed."
        if trace.succeeded:
            learned_note = await self._maybe_auto_learn(episode, on_phase, on_experience_event)
            if learned_note:
                await self._stream_markdown("\n\n" + learned_note, on_token)
                final_summary = (final_summary + "\n\n" + learned_note).strip()

        on_complete(final_summary)
        return True

    @staticmethod
    def _call_gemini_rest(api_key: str, sys_prompt: str, messages: List[Dict[str, str]]) -> Optional[str]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
        payload = {
            "system_instruction": {"parts": [{"text": sys_prompt}]},
            "contents": [
                {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                for m in messages
            ],
        }
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception:
            return None

    @staticmethod
    def _list_ollama_models(port: int) -> List[Dict[str, Any]]:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/tags", timeout=0.8) as resp:
                return list(json.loads(resp.read().decode("utf-8")).get("models", []))
        except Exception:
            return []

    @staticmethod
    def _pick_ollama_model(models: List[Dict[str, Any]], override: str = "") -> Optional[str]:
        """Choose the local chat model: explicit `agent.ollama_model`, then the known-good list,
        then the largest tool-capable model that fits comfortably in memory (never an embedding
        or speech model just because it happens to be listed first)."""
        chat = []
        for m in models:
            name = m.get("name", "")
            caps = m.get("capabilities") or []
            if not name or "embed" in name or (caps and "completion" not in caps):
                continue
            chat.append(m)
        names = [m["name"] for m in chat]
        if override and override in names:
            return override
        for pref in ("gemma4:e4b", "qwen2.5:14b", "lfm2.5:8b", "llama3.2:latest", "qwen2.5-coder:1.5b"):
            if pref in names:
                return pref
        if not chat:
            return None
        max_bytes = 12 * 1024**3
        fits = [m for m in chat if 0 < int(m.get("size", 0) or 0) <= max_bytes]
        if fits:
            best = max(fits, key=lambda m: ("tools" in (m.get("capabilities") or []), int(m.get("size", 0))))
            return str(best["name"])
        return str(min(chat, key=lambda m: int(m.get("size", 0) or 0))["name"])

    @staticmethod
    def _call_local_ollama(
        port: int,
        model_name: str,
        sys_prompt: str,
        messages: List[Dict[str, str]],
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> Optional[str]:
        payload = {
            "model": model_name,
            "stream": True,
            # Ollama's default context window silently truncates the briefing plus tool results.
            "options": {"num_ctx": 16384},
            "messages": [{"role": "system", "content": sys_prompt}] + messages,
        }
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/chat",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            # Generous: the first call may have to load the model into memory.
            chunks: List[str] = []
            with urllib.request.urlopen(req, timeout=240) as c_resp:
                for raw_line in c_resp:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        c_data = json.loads(line)
                    except Exception:
                        continue
                    delta = c_data.get("message", {}).get("content", "")
                    if delta:
                        chunks.append(delta)
                        if on_chunk is not None:
                            on_chunk(delta)
                    if c_data.get("done"):
                        break
            return "".join(chunks) or None
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
        on_experience_event: Optional[Callable[[Dict[str, Any]], None]] = None,
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
                "- **Learning & Python Experiences:**\n"
                "  - `/experiences` — List all learned Python Experience tools & maturity stats\n"
                "  - `/exp run <slug> [json]` — Run a learned Python Experience script\n"
                "  - `/exp test <slug>` — Dry-run / self-test an Experience without mutating the host\n"
                "  - `/exp show <slug>` — View an Experience's Python script & manifest\n"
                "  - `/learn [name]` — Distill the last completed task into a reusable Python Experience\n"
                "- **Slash Commands:**\n"
                "  - `/doctor` — Run 5-point Ubuntu System Doctor diagnostic\n"
                "  - `/containers [name]` — Inspect Docker/Podman containers & crash logs\n"
                "  - `/systemd [unit]` — Inspect failed systemd units or unit journal logs\n"
                "  - `/net` — Audit listening sockets, established TCP & UFW/nftables firewall\n"
                "  - `/disk` — Audit filesystem space, inodes, journald & `~` usage\n"
                "  - `/gpu` — Check NVIDIA/AMD GPU VRAM & local Ollama/vLLM servers\n"
                "  - `/tls <host>` — Audit DNS resolution & TLS certificate expiry\n"
                "  - `/git [path]` — Inspect Git branch, status, commits & remotes\n"
                "  - `/skills [name]` — List or inspect loaded `skills/*.md` runbooks\n"
                "  - `/undo` / `/rollback [id|list]` — Roll back file patches or writes\n"
                "  - `/memory` — Inspect or clear Tchiko's persistent memory & notes\n"
                "  - `/new` — Start a fresh conversation (keeps saved notes)\n"
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

        if lower in ("/new", "/reset", "new chat", "start over"):
            self.reset_conversation()
            msg = "🧼 **Fresh start.** Previous conversation context cleared; saved notes are kept."
            await self._stream_markdown(msg, on_token)
            on_state_change("idle")
            on_complete(msg)
            return True

        if lower in ("/experiences", "/exp", "/exps"):
            out = self.experiences.format_experiences_index()
            await self._stream_markdown(out, on_token)
            on_state_change("idle")
            on_complete(out)
            return True

        if lower.startswith("/exp "):
            rest = prompt.strip()[5:].strip()
            parts = rest.split(None, 2)
            sub = parts[0].lower() if parts else ""
            slug = parts[1].strip() if len(parts) > 1 else ""
            extra = parts[2].strip() if len(parts) > 2 else ""

            if sub in ("run", "test", "dry-run") and slug:
                dry = sub in ("test", "dry-run")
                params: Dict[str, Any] = {}
                if extra:
                    try:
                        loaded = json.loads(extra)
                        if isinstance(loaded, dict):
                            params = loaded
                    except Exception:
                        pass
                on_thought(f"{'Dry-running' if dry else 'Running'} Python Experience `{slug}`...")
                on_state_change("executing")
                on_tool_call("run_experience", f"{{'slug': {slug!r}, 'dry_run': {dry}}}")
                res = await asyncio.to_thread(self.experiences.run_experience, slug, params, dry)
                if not dry and on_experience_event is not None:
                    exp_obj = self.experiences.get_experience(slug)
                    if exp_obj is not None:
                        try:
                            on_experience_event({
                                "event": "used",
                                "slug": exp_obj.slug,
                                "title": exp_obj.title,
                                "version": exp_obj.version,
                                "maturity": exp_obj.maturity,
                                "ok": res.ok,
                            })
                        except Exception:
                            pass
                icon = "✅" if res.ok else "⚠️"
                out = f"{icon} **{res.title}** (`exit={res.exit_code}`, `{res.duration_ms}ms`)\n```text\n{res.output}\n```"
                await self._stream_markdown(out, on_token)
                on_state_change("happy" if res.ok else "alert")
                on_complete(out)
                return True

            if sub == "show" and slug:
                exp = self.experiences.get_experience(slug)
                if exp is None:
                    out = f"⚠️ Experience `{slug}` not found."
                else:
                    code = self.experiences.get_script_source(slug)
                    out = (
                        f"### 🧠 Experience: `{exp.slug}` `v{exp.version}` [{exp.maturity}]\n"
                        f"- **Title:** {exp.title}\n"
                        f"- **Description:** {exp.description}\n"
                        f"- **Category:** `{exp.category}` · **Risk Tier:** `{exp.risk_tier}`\n"
                        f"- **Stats:** `{exp.runs}` runs, `{int(round(exp.success_rate * 100))}%` success, `{exp.recoveries}` recoveries\n"
                        f"- **Triggers:** {', '.join(f'`{t}`' for t in exp.triggers)}\n\n"
                        f"```python\n{code[:4000]}\n```"
                    )
                await self._stream_markdown(out, on_token)
                on_state_change("idle")
                on_complete(out)
                return True

            if sub == "approve" and slug:
                exp = self.experiences.approve_experience(slug)
                out = (
                    f"✅ Approved Experience `{exp.slug}` -> `{exp.maturity}`."
                    if exp
                    else f"⚠️ Experience `{slug}` not found."
                )
                await self._stream_markdown(out, on_token)
                on_state_change("happy" if exp else "alert")
                on_complete(out)
                return True

            if sub == "rollback" and slug:
                ok_rb, msg_rb = self.experiences.rollback_version(slug)
                out = ("↩️ " if ok_rb else "⚠️ ") + msg_rb
                await self._stream_markdown(out, on_token)
                on_state_change("happy" if ok_rb else "alert")
                on_complete(out)
                return True

            out = "Usage: `/exp run <slug> [json]`, `/exp test <slug>`, `/exp show <slug>`, `/exp approve <slug>`, `/exp rollback <slug>`"
            await self._stream_markdown(out, on_token)
            on_state_change("idle")
            on_complete(out)
            return True

        if lower == "/learn" or lower.startswith("/learn "):
            custom_name = prompt.strip()[6:].strip()
            ep = self.last_episode
            if not ep and self.memory.get("last_command"):
                ep = {
                    "prompt": custom_name or self.memory.get("last_command", "learned-command"),
                    "steps": [
                        {
                            "tool": "bash",
                            "args_summary": self.memory.get("last_command", ""),
                            "ok": True,
                        }
                    ],
                    "succeeded": True,
                    "verified": True,
                    "recoveries_succeeded": 0,
                }
            if not ep:
                out = "⚠️ No recent completed task to learn from yet. Run a task first, then call `/learn [name]`."
                await self._stream_markdown(out, on_token)
                on_state_change("idle")
                on_complete(out)
                return True

            on_thought("Distilling last task into a validated Python Experience tool...")
            exp, msg = await asyncio.to_thread(self.experiences.learn_from_episode, ep, custom_name, True)
            if exp is None:
                out = f"⚠️ Could not create Experience: {msg}"
                await self._stream_markdown(out, on_token)
                on_state_change("alert")
                on_complete(out)
                return True

            if on_experience_event is not None:
                try:
                    on_experience_event({
                        "event": "learned",
                        "slug": exp.slug,
                        "title": exp.title,
                        "version": exp.version,
                        "maturity": exp.maturity,
                        "risk_tier": exp.risk_tier,
                        "message": msg,
                    })
                except Exception:
                    pass
            out = (
                f"🧠 **Experience Saved:** `{exp.slug}` `v{exp.version}` [{exp.maturity}]\n"
                f"- **Script:** `experiences/{exp.slug}/tool.py`\n"
                f"- **Risk Tier:** `{exp.risk_tier}`\n"
                f"- **Run anytime:** `/exp run {exp.slug}` or open the **Experiences** tab."
            )
            await self._stream_markdown(out, on_token)
            on_state_change("happy")
            on_complete(out)
            return True

        if lower in ("/doctor", "doctor"):
            return await self._run_system_doctor(
                on_thought, on_tool_call, on_token, on_complete, on_state_change
            )

        if lower.startswith(("/containers", "/docker")):
            target = prompt.strip().split(None, 1)[1] if len(prompt.strip().split(None, 1)) > 1 else ""
            on_thought("Inspecting Docker/Podman containers and recent logs...")
            on_state_change("executing")
            on_tool_call("diagnose_containers", f"{{'target': {target!r}}}")
            res = await asyncio.to_thread(self.toolkit.diagnose_containers, target)
            await self._stream_markdown(res.output, on_token)
            on_state_change("happy" if res.ok else "alert")
            on_complete(res.output)
            return True

        if lower.startswith(("/systemd", "/service")):
            unit = prompt.strip().split(None, 1)[1] if len(prompt.strip().split(None, 1)) > 1 else ""
            on_thought(f"Inspecting systemd unit {unit or '(failed units)'}...")
            on_state_change("executing")
            on_tool_call("inspect_systemd_unit", f"{{'unit': {unit!r}}}")
            res = await asyncio.to_thread(self.toolkit.inspect_systemd_unit, unit)
            await self._stream_markdown(res.output, on_token)
            on_state_change("happy" if res.ok else "alert")
            on_complete(res.output)
            return True

        if lower in ("/net", "/ports", "/firewall"):
            on_thought("Auditing listening sockets, established connections & firewall rules...")
            on_state_change("executing")
            on_tool_call("audit_network_security", "{}")
            res = await asyncio.to_thread(self.toolkit.audit_network_security)
            await self._stream_markdown(res.output, on_token)
            on_state_change("happy" if res.ok else "alert")
            on_complete(res.output)
            return True

        if lower in ("/disk", "/df"):
            on_thought("Auditing filesystem space, inodes, and journald usage...")
            on_state_change("executing")
            on_tool_call("audit_disk_and_inodes", "{}")
            res = await asyncio.to_thread(self.toolkit.audit_disk_and_inodes)
            await self._stream_markdown(res.output, on_token)
            on_state_change("happy" if res.ok else "alert")
            on_complete(res.output)
            return True

        if lower in ("/gpu", "/vram"):
            on_thought("Checking GPU VRAM, thermals, and local Ollama/vLLM endpoints...")
            on_state_change("executing")
            on_tool_call("diagnose_gpu_and_ai", "{}")
            res = await asyncio.to_thread(self.toolkit.diagnose_gpu_and_ai)
            await self._stream_markdown(res.output, on_token)
            on_state_change("happy" if res.ok else "alert")
            on_complete(res.output)
            return True

        if lower.startswith("/tls "):
            host = prompt.strip().split(None, 1)[1]
            on_thought(f"Auditing DNS & TLS certificate for `{host}`...")
            on_state_change("executing")
            on_tool_call("diagnose_dns_and_tls", f"{{'host': {host!r}}}")
            res = await asyncio.to_thread(self.toolkit.diagnose_dns_and_tls, host)
            await self._stream_markdown(res.output, on_token)
            on_state_change("happy" if res.ok else "alert")
            on_complete(res.output)
            return True

        if lower == "/git" or lower.startswith("/git "):
            arg = prompt.strip().split(None, 1)[1] if len(prompt.strip().split(None, 1)) > 1 else self.memory.get("cwd", ".")
            repo_path = self._resolve_user_path(arg)
            on_thought(f"Inspecting Git repository at `{repo_path}`...")
            on_state_change("executing")
            on_tool_call("inspect_git_repo", f"{{'path': {repo_path!r}}}")
            res = await asyncio.to_thread(self.toolkit.inspect_git_repo, repo_path)
            await self._stream_markdown(res.output, on_token)
            on_state_change("happy" if res.ok else "alert")
            on_complete(res.output)
            return True

        if lower == "/skills" or lower.startswith("/skills "):
            arg = prompt.strip().split(None, 1)[1] if len(prompt.strip().split(None, 1)) > 1 else ""
            if arg:
                skill = self.skills.get_skill(arg)
                out = f"### 🧩 Skill: `{skill.name}`\n{skill.body}" if skill else f"⚠️ Skill `{arg}` not found."
            else:
                out = self.skills.format_skills_index()
            await self._stream_markdown(out, on_token)
            on_state_change("idle")
            on_complete(out)
            return True

        if lower == "/undo" or lower.startswith("/rollback"):
            arg = prompt.strip().split(None, 1)[1] if len(prompt.strip().split(None, 1)) > 1 else ""
            if arg.lower() == "list":
                res = await asyncio.to_thread(self.toolkit.list_transactions)
            else:
                res = await asyncio.to_thread(self.toolkit.rollback_transaction, arg)
            await self._stream_markdown(res.output, on_token)
            on_state_change("happy" if res.ok else "alert")
            on_complete(res.output)
            return True

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

        if self.config.requires_manual_review(cmd) and on_approval_needed is not None:
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
