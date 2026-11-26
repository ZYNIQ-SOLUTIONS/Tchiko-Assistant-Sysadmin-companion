"""Humanized natural conversation, anaphora resolution, and interactive clarification for Tchiko.

Provides:
- `PendingTask`: persistent state when Tchiko pauses to ask the user for clarifying details.
- `ConversationAnalyzer`: distinguishes casual chat, anaphoric follow-ups ("run it"),
  underspecified/ambiguous requests, clarification replies, and clear actionable tasks.
- XML tag extraction for `<ask_user question="..." context="..."><option>...</option></ask_user>`.
"""

from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


PENDING_TASK_TTL_SEC = 15 * 60  # 15 minutes before a stale clarification auto-expires

ANAPHORIC_TOKENS = frozenset({
    "it", "that", "this", "them", "those", "one", "again",
    "the command", "that command", "last command", "the script",
})

CANCEL_PHRASES = frozenset({
    "cancel", "never mind", "nevermind", "forget it", "skip", "abort",
    "stop", "no thanks", "leave it", "dont", "don't", "nope", "nah",
})

ORDINAL_MAP = {
    "1": 0, "first": 0, "1st": 0, "one": 0, "option 1": 0, "the first": 0, "the first one": 0,
    "2": 1, "second": 1, "2nd": 1, "two": 1, "option 2": 1, "the second": 1, "the second one": 1,
    "3": 2, "third": 2, "3rd": 2, "three": 2, "option 3": 2, "the third": 2, "the third one": 2,
    "4": 3, "fourth": 3, "4th": 3, "four": 3, "option 4": 3, "the fourth": 3, "the fourth one": 3,
}

CASUAL_GREETINGS: Dict[str, str] = {
    "hi": "Hey! What are we working on today?",
    "hello": "Hello! Tell me what you want to check, install, or fix on this machine.",
    "hey": "Hey there! Need a hand with something on your system?",
    "hey tchiko": "Hey! I'm right here — what do you need done?",
    "hi tchiko": "Hi! Ready whenever you are — just tell me what's on your mind.",
    "hello tchiko": "Hello! What can I help you with on this machine?",
    "yo": "Yo! What's up — anything on the system you want me to look at?",
    "sup": "All quiet on this machine! What would you like to tackle?",
    "good morning": "Good morning! Want a quick `/doctor` health check, or jumping straight into a task?",
    "good afternoon": "Good afternoon! What can I help you with today?",
    "good evening": "Good evening! What are we working on tonight?",
    "how are you": "Doing great and keeping an eye on your system! What can I help you with?",
    "how are you?": "Doing great and keeping an eye on your system! What can I help you with?",
    "who are you": "I'm **Tchiko**, your local Ubuntu sysadmin companion. Talk to me naturally to diagnose issues, install or configure apps, manage services, or build reusable Python Experiences.",
    "who are you?": "I'm **Tchiko**, your local Ubuntu sysadmin companion. Talk to me naturally to diagnose issues, install or configure apps, manage services, or build reusable Python Experiences.",
    "what can you do": "Tell me in plain words what you need — I can inspect logs, manage services/ports/Docker/SSH, install or fix apps, learn reusable Python **Experiences** from solved tasks, and ask when something is unclear.",
    "what can you do?": "Tell me in plain words what you need — I can inspect logs, manage services/ports/Docker/SSH, install or fix apps, learn reusable Python **Experiences** from solved tasks, and ask when something is unclear.",
    "thanks": "Anytime! Let me know if anything else comes up.",
    "thank you": "You're welcome! Always here if you need another hand.",
    "thx": "Anytime!",
    "ty": "You got it!",
    "awesome": "Glad that worked out! What's next?",
    "nice": "Nice! Let me know whenever you need anything else.",
    "cool": "Cool — just ping me when you want to do the next thing.",
    "great": "Awesome! Holler if anything else needs attention.",
    "ok": "Got it! Let me know when you're ready for the next step.",
    "okay": "Sounds good! I'm right here if you need anything.",
}


@dataclass
class PendingTask:
    """State saved while waiting for the user to clarify details before proceeding."""

    id: str
    original_prompt: str
    question: str
    options: List[str] = field(default_factory=list)
    context: str = ""
    collected_details: Dict[str, str] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def is_expired(self, now: Optional[float] = None) -> bool:
        t = time.time() if now is None else now
        return (t - float(self.created_at)) > PENDING_TASK_TTL_SEC

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "original_prompt": self.original_prompt,
            "question": self.question,
            "options": list(self.options),
            "context": self.context,
            "collected_details": dict(self.collected_details),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Optional["PendingTask"]:
        if not isinstance(data, dict) or not data.get("original_prompt"):
            return None
        return cls(
            id=str(data.get("id") or f"clarify_{secrets.token_hex(4)}"),
            original_prompt=str(data.get("original_prompt", "")),
            question=str(data.get("question", "")),
            options=[str(o) for o in (data.get("options") or []) if str(o).strip()],
            context=str(data.get("context", "")),
            collected_details={
                str(k): str(v) for k, v in (data.get("collected_details") or {}).items()
            },
            created_at=float(data.get("created_at") or time.time()),
        )


@dataclass
class ClarificationRequest:
    """Structured clarification emitted by either the pre-flight gate or `<ask_user>`."""

    id: str
    question: str
    options: List[str] = field(default_factory=list)
    context: str = ""
    original_prompt: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "question": self.question,
            "options": list(self.options),
            "context": self.context,
            "original_prompt": self.original_prompt,
        }

    def format_markdown(self) -> str:
        lines = [f"### 💬 Quick Clarification", self.question]
        if self.context:
            lines.append(f"*{self.context}*")
        if self.options:
            lines.append("")
            for idx, opt in enumerate(self.options, 1):
                lines.append(f"{idx}. **{opt}**")
            lines.append("\nReply with a number, click an option below, or tell me in your own words.")
        return "\n".join(lines)


@dataclass
class ConversationDecision:
    """Outcome of analyzing a user turn before command/LLM dispatch."""

    kind: str  # casual_chat | cancel_pending | clarification_reply | needs_clarification | anaphora_command | clear_task
    resolved_prompt: str = ""
    reply_text: str = ""
    suggested_command: str = ""
    clarification: Optional[ClarificationRequest] = None


def extract_suggested_command(assistant_text: str) -> str:
    """Extract the most likely runnable command suggested by the assistant in its reply."""
    if not assistant_text:
        return ""
    # Prefer fenced ```bash / ```sh blocks near the end (e.g. Next Step)
    bash_blocks = re.findall(
        r"```(?:bash|sh|shell)\s*\n(.*?)```",
        assistant_text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    for block in reversed(bash_blocks):
        lines = [
            ln.strip()
            for ln in block.splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        if len(lines) == 1 and len(lines[0]) <= 180:
            return lines[0]
        if lines and len(lines) <= 2:
            joined = " && ".join(lines)
            if len(joined) <= 180:
                return joined

    # Fallback: inline backtick command prefixed with pkexec / sudo / systemctl / docker / tailscale
    inline_cmds = re.findall(
        r"`((?:pkexec|sudo|systemctl|docker|tailscale|apt|apt-get|snap|flatpak|git|ssh)\s+[^`\n]{2,120})`",
        assistant_text,
    )
    if inline_cmds:
        return inline_cmds[-1].strip()
    return ""


def parse_ask_user_tag(text: str, original_prompt: str = "") -> Optional[ClarificationRequest]:
    """Parse an `<ask_user question="..." context="..."><option>...</option></ask_user>` block."""
    if not text:
        return None
    # Self-closing form: <ask_user question="..." />
    m_sc = re.search(
        r'<ask_user\s+([^>]*?)\s*/\s*>',
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    attrs_str = ""
    body = ""
    if m_sc:
        attrs_str = m_sc.group(1)
    else:
        m_full = re.search(
            r'<ask_user(?:\s+([^>]*?))?>(.*?)</ask_user>',
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not m_full:
            return None
        attrs_str = m_full.group(1) or ""
        body = m_full.group(2) or ""

    q_match = re.search(r'question=["\']([^"\']+)["\']', attrs_str, flags=re.IGNORECASE)
    c_match = re.search(r'(?:context|reason)=["\']([^"\']+)["\']', attrs_str, flags=re.IGNORECASE)
    question = (q_match.group(1).strip() if q_match else "").strip()
    context = (c_match.group(1).strip() if c_match else "").strip()

    options = [
        m.group(1).strip()
        for m in re.finditer(r'<option>(.*?)</option>', body, flags=re.IGNORECASE | re.DOTALL)
        if m.group(1).strip()
    ]
    if not question:
        # Allow plain text inside <ask_user> when no attribute was provided
        plain = re.sub(r'<option>.*?</option>', '', body, flags=re.IGNORECASE | re.DOTALL).strip()
        question = plain
    if not question:
        return None

    return ClarificationRequest(
        id=f"clarify_{secrets.token_hex(4)}",
        question=question,
        options=options[:5],
        context=context,
        original_prompt=original_prompt,
    )


def strip_ask_user_tags(text: str) -> str:
    """Remove `<ask_user>...</ask_user>` or `<ask_user ... />` tags from visible prose."""
    cleaned = re.sub(
        r'<ask_user(?:\s+[^>]*)?>.*?</ask_user>',
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    cleaned = re.sub(r'<ask_user\s+[^>]*?/\s*>', "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    return cleaned.strip()


def is_anaphoric_run_target(cmd_candidate: str) -> bool:
    """Return True if a candidate after `run`/`execute` is a pronoun/reference rather than a binary."""
    norm = re.sub(r"[?!.,]+$", "", cmd_candidate.strip().lower())
    return norm in ANAPHORIC_TOKENS or norm in ("", "now", "please", "that now", "it now")


class ConversationAnalyzer:
    """Understands casual conversation, resolves references, and catches underspecified tasks."""

    def analyze(
        self,
        prompt: str,
        memory: Dict[str, Any],
        ask_before_ambiguous: bool = True,
    ) -> ConversationDecision:
        raw = prompt.strip()
        lower = raw.lower()
        norm = re.sub(r"[!.,]+$", "", lower).strip()

        # 0. Explicit slash commands or `$ cmd` always bypass conversational gating
        if raw.startswith(("/", "$")):
            return ConversationDecision(kind="clear_task", resolved_prompt=raw)

        # 1. Check active pending clarification first
        pending = PendingTask.from_dict(memory.get("pending_task"))
        if pending is not None and not pending.is_expired():
            if norm in CANCEL_PHRASES:
                return ConversationDecision(
                    kind="cancel_pending",
                    reply_text="No problem — I've cancelled that request. Let me know what you'd like to do instead!",
                )
            # If user started a brand new unrelated long request, don't trap them in the old clarification
            if not self._looks_like_topic_switch(lower, pending):
                chosen_detail = self._resolve_option_choice(raw, pending.options)
                merged = (
                    f"{pending.original_prompt}\n\n"
                    f"Clarification question asked: {pending.question}\n"
                    f"User answer: {chosen_detail}"
                )
                return ConversationDecision(
                    kind="clarification_reply",
                    resolved_prompt=merged,
                )

        # 2. Pure casual greetings / thanks / small talk
        norm_no_q = re.sub(r"[?!.,]+$", "", norm).strip()
        # Collapse repeated trailing letters on greetings ("heyyy" -> "hey", "hiiii" -> "hi")
        norm_dedup = re.sub(r"\b(hi|hey|hello|yo|hiya)([a-z])\2+\b", r"\1", norm_no_q)
        norm_dedup = re.sub(r"\b(he|hi|yo)([yi])\2+\b", lambda m: m.group(1) + m.group(2), norm_dedup)
        if norm in CASUAL_GREETINGS:
            return ConversationDecision(
                kind="casual_chat",
                reply_text=CASUAL_GREETINGS[norm],
            )
        if norm_no_q in CASUAL_GREETINGS:
            return ConversationDecision(
                kind="casual_chat",
                reply_text=CASUAL_GREETINGS[norm_no_q],
            )
        if re.fullmatch(
            r"(?:hi+|hey+|hello+|yo+|hiya|greetings|sup|what'?s\s+up)(?:\s+there)?(?:\s+(?:tchiko|buddy|mate|bro|friend))?",
            norm_dedup,
        ):
            return ConversationDecision(
                kind="casual_chat",
                reply_text="Hey! I'm Tchiko — tell me what you'd like to check, set up, or fix on this machine.",
            )
        if re.fullmatch(r"(?:good\s+)?(?:night|gn|bye|goodbye|see\s+ya|see\s+you|later)(?:\s+tchiko)?", norm_no_q):
            return ConversationDecision(
                kind="casual_chat",
                reply_text="Good night! I'll keep an eye on things — ping me anytime you need a hand.",
            )
        if re.fullmatch(
            r"(?:thanks|thank\s+you|thx|ty|appreciate\s+it|much\s+appreciated)(?:\s+(?:so\s+much|a\s+lot|tchiko|buddy|mate|bro|man|friend))*",
            norm_no_q,
        ):
            return ConversationDecision(
                kind="casual_chat",
                reply_text="You're welcome! Let me know whenever you need help with anything else.",
            )
        if re.fullmatch(
            r"(?:how\s+are\s+you(?:\s+doing)?|how'?s\s+it\s+going|are\s+you\s+(?:there|online|awake|ready))(?:\s+tchiko)?",
            norm_no_q,
        ):
            return ConversationDecision(
                kind="casual_chat",
                reply_text="I'm right here and ready to help! What would you like to check, install, or fix?",
            )

        # 3. Anaphoric "run it" / "execute it" / "try it" / "do it" / "run that"
        m_run_ref = re.match(
            r"^(?:tchiko\s+)?(?:please\s+)?(?:run|execute|do|try)\s+(it|that|this|the\s+command|that\s+command|it\s+now|that\s+now)$",
            norm_no_q,
        )
        if m_run_ref or norm_no_q in ("go ahead", "do it", "proceed", "run it", "execute it", "try it"):
            suggested = str(memory.get("last_suggested_command") or "").strip()
            if not suggested:
                # Inspect the latest assistant turn in history for a suggested command
                for turn in reversed(memory.get("history", [])):
                    if turn.get("role") == "assistant":
                        suggested = extract_suggested_command(str(turn.get("content", "")))
                        if suggested:
                            break
            if suggested:
                # Convert leading `sudo ` to `pkexec ` for desktop compatibility
                if suggested.startswith("sudo "):
                    suggested = "pkexec " + suggested[5:]
                return ConversationDecision(
                    kind="anaphora_command",
                    suggested_command=suggested,
                    resolved_prompt=raw,
                )
            # If no suggested command exists, ask what they want to run instead of running `it`!
            return ConversationDecision(
                kind="needs_clarification",
                clarification=ClarificationRequest(
                    id=f"clarify_{secrets.token_hex(4)}",
                    question="Which command or task would you like me to run?",
                    context="I didn't find a suggested command from my previous message.",
                    options=[
                        "Run a system health check (/doctor)",
                        "Repeat my last command (retry)",
                        "I'll type the command",
                    ],
                    original_prompt=raw,
                ),
            )

        # 4. Pre-flight ambiguity detection for underspecified / risky asks
        if ask_before_ambiguous:
            clar = self._detect_underspecified_task(raw, lower, norm_no_q, memory)
            if clar is not None:
                return ConversationDecision(kind="needs_clarification", clarification=clar)

        return ConversationDecision(kind="clear_task", resolved_prompt=raw)

    @staticmethod
    def _resolve_option_choice(raw: str, options: List[str]) -> str:
        norm = re.sub(r"[.!?,]+$", "", raw.strip().lower())
        if options and norm in ORDINAL_MAP:
            idx = ORDINAL_MAP[norm]
            if 0 <= idx < len(options):
                return options[idx]
        return raw.strip()

    @staticmethod
    def _looks_like_topic_switch(lower: str, pending: PendingTask) -> bool:
        """Heuristic: a brand-new multi-word command unrelated to the clarification overrides it."""
        words = lower.split()
        if len(words) < 5:
            return False
        starters = (
            "check ", "diagnose ", "create an ssh", "list ", "show me ",
            "find files", "kill port", "what is using port",
        )
        return lower.startswith(starters) and not any(
            tok in lower for tok in pending.original_prompt.lower().split() if len(tok) > 3
        )

    @staticmethod
    def _detect_underspecified_task(
        raw: str, lower: str, norm: str, memory: Dict[str, Any]
    ) -> Optional[ClarificationRequest]:
        """Catch clearly incomplete or destructive-ambiguous requests before guessing blindly."""
        words = norm.split()
        if not words:
            return None

        # Open-ended help request without a stated task
        if norm in ("can you help me", "can you help", "i need help", "help me", "help me out"):
            return ClarificationRequest(
                id=f"clarify_{secrets.token_hex(4)}",
                question="Of course! What would you like help with?",
                context="Pick a quick starting point or describe the issue in your own words.",
                options=[
                    "Run a full System Doctor check (/doctor)",
                    "Troubleshoot an app, service, or Docker issue",
                    "Install, update, or clean up packages/files",
                    "Network, SSH, or port diagnostics",
                ],
                original_prompt=raw,
            )

        # Bare action verbs with no target: "install", "remove", "delete", "restart", "fix"
        if norm in ("install", "install app", "install something", "install a package"):
            return ClarificationRequest(
                id=f"clarify_{secrets.token_hex(4)}",
                question="What application or package would you like me to install?",
                context="Share the name (or a link / .deb / Snap / Flatpak preference) and I'll handle the rest.",
                options=["Install via APT (.deb)", "Install via Snap", "Install via Flatpak"],
                original_prompt=raw,
            )

        if norm in ("update my apps", "update apps", "update everything", "upgrade my apps", "upgrade my system"):
            return ClarificationRequest(
                id=f"clarify_{secrets.token_hex(4)}",
                question="Which package sources should I update?",
                context="I can check available updates first or upgrade them right away.",
                options=[
                    "Check what updates are available first (read-only)",
                    "Update APT packages only",
                    "Update APT + Snap + Flatpak",
                ],
                original_prompt=raw,
            )

        if norm in ("clean", "clean up", "cleanup", "clean my pc", "clean my system", "free up space", "free space"):
            return ClarificationRequest(
                id=f"clarify_{secrets.token_hex(4)}",
                question="What level of cleanup would you like me to perform?",
                context="I want to make sure I don't remove anything you still need.",
                options=[
                    "Safe audit first (show largest folders & caches, delete nothing)",
                    "Clean safe caches (APT cache, old journald logs > 200M, thumbnails)",
                    "Include Docker unused images & build cache",
                ],
                original_prompt=raw,
            )

        if norm in ("fix it", "fix this", "fix my pc", "something is broken", "my pc is broken", "help me fix"):
            last_err = str(memory.get("last_output") or "")
            has_recent_err = bool(last_err) and any(
                w in last_err.lower() for w in ("error", "failed", "denied", "not found", "traceback")
            )
            if not has_recent_err:
                return ClarificationRequest(
                    id=f"clarify_{secrets.token_hex(4)}",
                    question="What seems to be going wrong? Give me a quick hint and I'll dig in.",
                    options=[
                        "Run full System Doctor (/doctor)",
                        "App or IDE is crashing",
                        "Network / VPN / remote connection issue",
                        "High CPU, RAM, or full disk",
                    ],
                    original_prompt=raw,
                )

        if re.fullmatch(r"(?:my\s+)?docker\s+(?:is\s+)?(?:acting\s+weird|broken|failing|not\s+working|has\s+issues?)", norm):
            return ClarificationRequest(
                id=f"clarify_{secrets.token_hex(4)}",
                question="What part of Docker should I investigate first?",
                context="Narrowing it down avoids touching healthy containers.",
                options=[
                    "Check Docker daemon status & failed containers",
                    "Inspect recent logs of a specific container",
                    "Check Docker disk usage & build cache",
                ],
                original_prompt=raw,
            )

        if re.fullmatch(r"(?:my\s+)?(?:network|internet|wifi|connection)\s+(?:is\s+)?(?:slow|laggy|broken|acting\s+weird|down)", norm):
            return ClarificationRequest(
                id=f"clarify_{secrets.token_hex(4)}",
                question="Which network symptom should I diagnose first?",
                options=[
                    "Test DNS resolution & gateway/internet latency",
                    "Inspect active interfaces, Wi-Fi signal & routes",
                    "Check processes using bandwidth / open sockets",
                ],
                original_prompt=raw,
            )

        if re.fullmatch(r"fix\s+(?:my\s+|the\s+)?permissions?", norm):
            return ClarificationRequest(
                id=f"clarify_{secrets.token_hex(4)}",
                question="Which folder, file, or service has a permission problem?",
                context="I need the exact path or user/group so I don't weaken system security.",
                options=[
                    "Check SSH (~/.ssh) permissions",
                    "Check Docker socket permissions for current user",
                    "I'll type the exact file or folder path",
                ],
                original_prompt=raw,
            )

        if re.fullmatch(r"(?:restart|stop|start|reload)\s+(?:the\s+)?(?:service|app|server|container)", norm):
            return ClarificationRequest(
                id=f"clarify_{secrets.token_hex(4)}",
                question="Which service, app, or container should I target?",
                options=[
                    "List failed systemd services first",
                    "List running Docker containers first",
                    "I'll type the exact name",
                ],
                original_prompt=raw,
            )

        if re.fullmatch(r"(?:kill|stop)\s+(?:a\s+|the\s+)?(?:process|port)", norm):
            return ClarificationRequest(
                id=f"clarify_{secrets.token_hex(4)}",
                question="Which process name, PID, or port number should I stop?",
                options=[
                    "Show top CPU/RAM processes first",
                    "Show listening ports first",
                    "I'll type the PID or port",
                ],
                original_prompt=raw,
            )

        if re.fullmatch(r"(?:delete|remove|wipe)\s+(?:old\s+|unused\s+|temp\s+)?(?:files|folder|logs|backups|cache)", norm):
            return ClarificationRequest(
                id=f"clarify_{secrets.token_hex(4)}",
                question="Which exact path or folder should I clean up, and do you want a preview list first?",
                context="Destructive deletion needs an exact target path.",
                options=[
                    "Show me what's taking up space first (read-only)",
                    "I'll specify the exact path",
                ],
                original_prompt=raw,
            )

        if re.fullmatch(r"(?:deploy|setup|set\s+up|configure)\s+(?:my\s+|a\s+)?(?:server|vps|ssh)", norm):
            return ClarificationRequest(
                id=f"clarify_{secrets.token_hex(4)}",
                question="What details should I use for this server setup?",
                context="Let me know the host/IP, username, and whether you want an SSH key generated.",
                options=[
                    "Generate a new Ed25519 SSH key first",
                    "Add an existing server IP to ~/.ssh/config",
                    "Audit local SSH & firewall security",
                ],
                original_prompt=raw,
            )

        return None
