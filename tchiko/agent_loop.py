"""Resilient Do -> Observe -> Try/Catch -> Recover -> Verify Agentic Loop for Tchiko.

Replaces the linear ReAct loop with a structured state machine featuring:
- Typed failure classification (`PERMISSION_DENIED`, `COMMAND_NOT_FOUND`, `LOCK_OR_BUSY`,
  `NOT_FOUND_OR_404`, `TIMEOUT`, `SYNTAX_OR_USAGE`, `MALFORMED_TOOL_TAG`, `USER_DENIED`).
- Automatic repair of common model tag mistakes (e.g. `<pkexec>...</pkexec>` -> `<bash>pkexec ...</bash>`)
  and explicit parser-exception feedback for unknown XML tags so turns never drop silently.
- Duplicate-failure fingerprinting and retry budgets to stop infinite retry loops.
- Post-mutation verification prompting and automatic/optional rollback via the Snapshot Ledger.
- Structured `LoopTrace` export consumed by `ExperienceLearner` (Pillar 3) and the visual UI (Pillar 4).
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple

from .conversation import ClarificationRequest, parse_ask_user_tag, strip_ask_user_tags
from .system_tools import ToolResult


# ── Failure Taxonomy ─────────────────────────────────────────────────────────
class FailureClass:
    NONE = "NONE"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    COMMAND_NOT_FOUND = "COMMAND_NOT_FOUND"
    NOT_FOUND_OR_404 = "NOT_FOUND_OR_404"
    LOCK_OR_BUSY = "LOCK_OR_BUSY"
    NETWORK_TRANSIENT = "NETWORK_TRANSIENT"
    TIMEOUT = "TIMEOUT"
    SYNTAX_OR_USAGE = "SYNTAX_OR_USAGE"
    MALFORMED_TOOL_TAG = "MALFORMED_TOOL_TAG"
    USER_DENIED = "USER_DENIED"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


KNOWN_TOOL_TAGS = frozenset({
    "bash", "view_file", "grep", "patch_file", "write_file",
    "containers", "systemd", "network_audit", "disk", "gpu",
    "tls", "git", "experience", "ask_user", "search", "replace", "option",
})

READONLY_TOOLS = frozenset({
    "view_file", "grep", "containers", "systemd", "network_audit",
    "disk", "gpu", "tls", "git",
})

MUTATING_TOOLS = frozenset({
    "patch_file", "write_file", "bash", "experience",
})

_TX_ID_RE = re.compile(r"\[`(tx_[a-zA-Z0-9_-]+)`\]")


@dataclass
class StepRecord:
    """Single audited step inside a resilient agentic loop."""

    step_index: int
    phase: str  # PLAN | ACT | OBSERVE | RECOVER | VERIFY | ROLLBACK | ASK_USER
    tool: str
    args_summary: str
    ok: bool
    exit_code: int = 0
    error_class: str = FailureClass.NONE
    recovery_hint: str = ""
    duration_ms: int = 0
    tx_id: str = ""
    output_excerpt: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_index": self.step_index,
            "phase": self.phase,
            "tool": self.tool,
            "args_summary": self.args_summary,
            "ok": self.ok,
            "exit_code": self.exit_code,
            "error_class": self.error_class,
            "recovery_hint": self.recovery_hint,
            "duration_ms": self.duration_ms,
            "tx_id": self.tx_id,
            "output_excerpt": self.output_excerpt[:400],
        }


@dataclass
class LoopTrace:
    """Complete structured execution record for a single agent prompt turn."""

    prompt: str
    steps: List[StepRecord] = field(default_factory=list)
    tx_ids: List[str] = field(default_factory=list)
    recoveries_attempted: int = 0
    recoveries_succeeded: int = 0
    verified: bool = False
    succeeded: bool = False
    asked_user: Optional[ClarificationRequest] = None
    final_text: str = ""
    used_experiences: List[str] = field(default_factory=list)
    duration_ms: int = 0
    rolled_back_txs: List[str] = field(default_factory=list)

    @property
    def tool_steps_count(self) -> int:
        return sum(1 for s in self.steps if s.phase in ("ACT", "VERIFY"))

    def to_episode_dict(self) -> Dict[str, Any]:
        return {
            "prompt": self.prompt,
            "steps": [s.to_dict() for s in self.steps],
            "tx_ids": list(self.tx_ids),
            "recoveries_attempted": self.recoveries_attempted,
            "recoveries_succeeded": self.recoveries_succeeded,
            "verified": self.verified,
            "succeeded": self.succeeded,
            "used_experiences": list(self.used_experiences),
            "duration_ms": self.duration_ms,
        }


class FailureClassifier:
    """Classifies tool/command failures into typed exception classes with recovery hints."""

    @staticmethod
    def extract_tx_id(output: str) -> str:
        m = _TX_ID_RE.search(output or "")
        return m.group(1) if m else ""

    @staticmethod
    def normalize_common_tag_mistakes(clean_text: str) -> Tuple[str, List[str]]:
        """Auto-repair common local-LLM tag hallucinations such as `<pkexec>...</pkexec>`."""
        repairs: List[str] = []
        updated = clean_text

        def _wrap_pkexec(match: "re.Match[str]") -> str:
            inner = match.group(1).strip()
            repairs.append(f"Normalized `<pkexec>` tag into `<bash>pkexec {inner[:60]}</bash>`")
            if inner.startswith("pkexec "):
                return f"<bash>{inner}</bash>"
            return f"<bash>pkexec {inner}</bash>"

        updated = re.sub(
            r"<pkexec>(.*?)</pkexec>",
            _wrap_pkexec,
            updated,
            flags=re.DOTALL | re.IGNORECASE,
        )

        def _wrap_sudo(match: "re.Match[str]") -> str:
            inner = match.group(1).strip()
            repairs.append(f"Normalized `<sudo>` tag into `<bash>pkexec {inner[:60]}</bash>`")
            return f"<bash>pkexec {inner}</bash>"

        updated = re.sub(
            r"<sudo>(.*?)</sudo>",
            _wrap_sudo,
            updated,
            flags=re.DOTALL | re.IGNORECASE,
        )

        def _wrap_shell(match: "re.Match[str]") -> str:
            tag = match.group(1).lower()
            inner = match.group(2).strip()
            repairs.append(f"Normalized `<{tag}>` tag into `<bash>`")
            return f"<bash>{inner}</bash>"

        updated = re.sub(
            r"<(shell|sh|cmd|command|terminal|run|exec)>(.*?)</\1>",
            _wrap_shell,
            updated,
            flags=re.DOTALL | re.IGNORECASE,
        )

        # Normalize self-closing attribute tags like `<bash command="uname -a" />` or `<bash cmd="df -h"/>`
        def _wrap_attr_bash(match: "re.Match[str]") -> str:
            inner = match.group(1).strip()
            repairs.append(f"Normalized attribute `<bash>` tag into `<bash>{inner[:60]}</bash>`")
            return f"<bash>{inner}</bash>"

        updated = re.sub(
            r'<bash\s+(?:command|cmd)=["\']([^"\']+)["\']\s*/?>',
            _wrap_attr_bash,
            updated,
            flags=re.IGNORECASE,
        )
        return updated, repairs

    @staticmethod
    def detect_unrecognized_tool_tags(clean_text: str) -> List[str]:
        """Find XML-like action tags emitted outside code fences that do not match known tools."""
        # Ignore fenced code blocks so prose examples do not trigger false positives
        no_code = re.sub(r"```.*?```", "", clean_text, flags=re.DOTALL)
        no_code = re.sub(r"`[^`]+`", "", no_code)
        unknown: List[str] = []
        for m in re.finditer(r"<([a-zA-Z_][a-zA-Z0-9_-]*)(?:\s[^>]*)?(?:/>|>.*?</\1>)", no_code, flags=re.DOTALL):
            tag = m.group(1).lower()
            if tag not in KNOWN_TOOL_TAGS and tag not in ("br", "hr", "b", "i", "code", "pre", "p", "a", "span", "ul", "li"):
                if tag not in unknown:
                    unknown.append(tag)
        return unknown

    @staticmethod
    def classify(res: ToolResult) -> Tuple[str, str]:
        """Return `(FailureClass, actionable recovery directive)` for a failed `ToolResult`."""
        if res.ok:
            return FailureClass.NONE, ""

        out_l = (res.output or "").lower()
        code = int(res.exit_code or 0)

        if code == 126 or "user denied" in out_l or "permission denied by tchiko settings" in out_l:
            return (
                FailureClass.USER_DENIED,
                "The action was blocked by user denial or Tchiko Settings. Do NOT retry the exact same "
                "command; explain clearly or ask the user for an alternative via <ask_user>.",
            )

        if code == 124 or "timed out" in out_l:
            return (
                FailureClass.TIMEOUT,
                "The command timed out. If it starts a daemon/service, launch it in the background and verify "
                "its listening port/status; if it is a large scan, narrow the scope or path.",
            )

        if any(
            k in out_l
            for k in (
                "could not open lock file",
                "unable to lock directory",
                "permission denied",
                "operation not permitted",
                "are you root",
                "must be root",
                "eacces",
                "eperm",
            )
        ):
            return (
                FailureClass.PERMISSION_DENIED,
                "Root/elevated privileges are required. Retry using `pkexec` inside `<bash>pkexec ...</bash>` "
                "(never use interactive `sudo` or an invalid `<pkexec>` XML tag).",
            )

        if any(
            k in out_l
            for k in (
                "unable to acquire the dpkg frontend lock",
                "could not get lock /var/lib/dpkg",
                "address already in use",
                "eaddrinuse",
                "singletonlock",
                "resource temporarily unavailable",
            )
        ):
            return (
                FailureClass.LOCK_OR_BUSY,
                "A lock or port is currently held by another process. Inspect what holds the lock/port "
                "(e.g. `ss -tulnp`, `lsof`, or `fuser`) before retrying.",
            )

        if any(
            k in out_l
            for k in (
                "could not resolve host",
                "temporary failure in name resolution",
                "name or service not known",
                "connection refused",
                "connection reset by peer",
                "network is unreachable",
                "no route to host",
                "502 bad gateway",
                "503 service unavailable",
                "504 gateway timeout",
                "429 too many requests",
            )
        ):
            return (
                FailureClass.NETWORK_TRANSIENT,
                "A transient network, DNS, or upstream service error occurred. Verify connectivity/DNS "
                "(`ip route`, `resolvectl status`) or target service status before retrying.",
            )

        if code == 127 or "command not found" in out_l:
            return (
                FailureClass.COMMAND_NOT_FOUND,
                "The binary is not installed or not in PATH. Check available alternatives (e.g. `which`, "
                "`snap`, `flatpak`, `apt-cache search`) or install the package if appropriate.",
            )

        if any(
            k in out_l
            for k in (
                "404 not found",
                "error 404",
                "unable to locate package",
                "no such file or directory",
                "file not found",
                "target snippet not found",
                "could not be found",
            )
        ):
            return (
                FailureClass.NOT_FOUND_OR_404,
                "The target file, package, or URL was not found. Inspect the real path/package name first "
                "(e.g. `ls`, `apt-cache search`, upstream release assets), or call `<ask_user>` if the user "
                "may have made a typo.",
            )

        if any(
            k in out_l
            for k in (
                "invalid option",
                "unrecognized option",
                "unrecognized arguments",
                "unknown flag",
                "unknown option",
                "syntax error",
                "unexpected token",
                "usage:",
            )
        ):
            return (
                FailureClass.SYNTAX_OR_USAGE,
                "Command syntax or flag error. Check `--help` or adjust the flags for this Ubuntu host before retrying.",
            )

        return (
            FailureClass.UNKNOWN_ERROR,
            "Inspect the stderr output above carefully, diagnose the root cause, and try a corrected strategy "
            "(or ask the user via `<ask_user>` if human input is needed).",
        )


def _action_fingerprint(act: Dict[str, Any], error_class: str) -> str:
    """Stable hash for duplicate-failure detection."""
    tool = str(act.get("tool", ""))
    detail = str(act.get("command") or act.get("path") or act.get("name") or act.get("unit") or act.get("pattern") or "")
    raw = f"{tool}::{detail.strip()}::{error_class}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _format_action_args(act: Dict[str, Any]) -> str:
    tool = act.get("tool", "tool")
    if tool == "bash":
        return str(act.get("command", ""))[:160]
    if tool == "experience":
        return f"{act.get('name', '')} {act.get('params', {})}"[:160]
    parts = [f"{k}={v!r}" for k, v in act.items() if k != "tool" and k != "content"]
    return ", ".join(parts)[:160]


class ResilientAgentLoop:
    """Executes the Do -> Observe -> Catch/Recover -> Verify multi-tool agentic loop."""

    def __init__(
        self,
        *,
        query_llm: Callable[[List[Dict[str, str]]], Awaitable[Optional[str]]],
        strip_think: Callable[[str], Tuple[str, List[str]]],
        extract_actions: Callable[[str], List[Dict[str, Any]]],
        execute_action: Callable[[Dict[str, Any]], Awaitable[Tuple[str, ToolResult]]],
        rollback_tx: Optional[Callable[[str], ToolResult]] = None,
        on_thought: Callable[[str], None],
        on_token: Callable[[str], None],
        on_state_change: Callable[[str], None],
        on_phase: Optional[Callable[[str, str], None]] = None,
        stream_markdown: Optional[Callable[[str, Callable[[str], None]], Awaitable[None]]] = None,
        max_steps: int = 14,
        max_consecutive_failures: int = 3,
        auto_rollback: bool = False,
    ) -> None:
        self.query_llm = query_llm
        self.strip_think = strip_think
        self.extract_actions = extract_actions
        self.execute_action = execute_action
        self.rollback_tx = rollback_tx
        self.on_thought = on_thought
        self.on_token = on_token
        self.on_state_change = on_state_change
        self.on_phase = on_phase
        self.stream_markdown = stream_markdown
        self.max_steps = max(2, int(max_steps))
        self.max_consecutive_failures = max(2, int(max_consecutive_failures))
        self.auto_rollback = auto_rollback

    def _emit_phase(self, phase: str, text: str) -> None:
        if self.on_phase is not None:
            try:
                self.on_phase(phase, text)
            except Exception:
                pass
        else:
            self.on_thought(f"[{phase}] {text}")

    async def _emit_markdown(self, text: str) -> None:
        if self.stream_markdown is not None:
            await self.stream_markdown(text, self.on_token)
        else:
            self.on_token(text)

    @staticmethod
    def _strip_all_tool_tags(visible_text: str) -> str:
        cleaned = re.sub(
            r"(<bash>.*?</bash>|<view_file[^>]*/?>|<grep[^>]*/?>|<patch_file.*?</patch_file>|"
            r"<write_file.*?</write_file>|<containers[^>]*/?>|<systemd[^>]*/?>|<network_audit[^>]*/?>|"
            r"<disk\s*/?>|<gpu\s*/?>|<tls[^>]*/?>|<git[^>]*/?>|<experience[^>]*/?>|<experience.*?</experience>)",
            "",
            visible_text,
            flags=re.DOTALL | re.IGNORECASE,
        )
        return strip_ask_user_tags(cleaned).strip()

    async def run(
        self,
        prompt: str,
        messages: List[Dict[str, str]],
    ) -> Tuple[bool, LoopTrace]:
        """Run the loop. Returns `(handled, LoopTrace)`. `handled=False` only if step 0 LLM failed."""
        started = time.monotonic()
        trace = LoopTrace(prompt=prompt)
        accumulated_markdown: List[str] = []

        failed_fingerprints: Set[str] = set()
        consecutive_failures = 0
        had_prior_failure = False
        had_unverified_mutation = False
        verification_nudged = False
        malformed_tag_retries = 0

        for step_idx in range(1, self.max_steps + 1):
            llm_text = await self.query_llm(messages)
            if not llm_text:
                if not accumulated_markdown and not trace.steps:
                    trace.duration_ms = int((time.monotonic() - started) * 1000)
                    return False, trace
                note = "⚠️ **The model stopped responding before finishing the task.**"
                accumulated_markdown.append(note)
                await self._emit_markdown(note + "\n")
                self.on_state_change("alert")
                trace.final_text = "\n\n".join(accumulated_markdown).strip()
                trace.duration_ms = int((time.monotonic() - started) * 1000)
                return True, trace

            visible_text, thoughts = self.strip_think(llm_text)
            for th in thoughts:
                first_line = next((ln.strip() for ln in th.splitlines() if ln.strip()), "Reasoning...")
                self.on_thought(first_line[:140])

            # 1. Check for `<ask_user>` interactive clarification before tools
            ask_req = parse_ask_user_tag(visible_text, original_prompt=prompt)
            if ask_req is not None:
                clean_prose = self._strip_all_tool_tags(visible_text)
                if clean_prose:
                    accumulated_markdown.append(clean_prose)
                    await self._emit_markdown(clean_prose + "\n\n")
                clar_md = ask_req.format_markdown()
                accumulated_markdown.append(clar_md)
                await self._emit_markdown(clar_md + "\n")
                trace.steps.append(
                    StepRecord(
                        step_index=step_idx,
                        phase="ASK_USER",
                        tool="ask_user",
                        args_summary=ask_req.question[:140],
                        ok=True,
                    )
                )
                trace.asked_user = ask_req
                trace.final_text = "\n\n".join(accumulated_markdown).strip()
                trace.duration_ms = int((time.monotonic() - started) * 1000)
                self._emit_phase("ASK_USER", ask_req.question[:120])
                self.on_state_change("thinking")
                return True, trace

            # 2. Try/Catch malformed tool tags: auto-normalize `<pkexec>` / `<sudo>` / `<shell>`
            normalized_text, tag_repairs = FailureClassifier.normalize_common_tag_mistakes(visible_text)
            for rep in tag_repairs:
                trace.recoveries_attempted += 1
                self._emit_phase("RECOVER", rep)
                trace.steps.append(
                    StepRecord(
                        step_index=step_idx,
                        phase="RECOVER",
                        tool="tag_normalizer",
                        args_summary=rep[:140],
                        ok=True,
                        error_class=FailureClass.MALFORMED_TOOL_TAG,
                    )
                )

            actions = self.extract_actions(normalized_text)

            # Catch unrecognized XML action tags when no valid actions were parsed
            if not actions:
                unknown_tags = FailureClassifier.detect_unrecognized_tool_tags(normalized_text)
                if unknown_tags and malformed_tag_retries < 2:
                    malformed_tag_retries += 1
                    trace.recoveries_attempted += 1
                    err_msg = (
                        f"Parser exception (`MALFORMED_TOOL_TAG`): unrecognized tool tag(s) "
                        f"{', '.join(f'<{t}>' for t in unknown_tags)}. "
                        f"Valid tool tags are ONLY: `<bash>...</bash>` (use `<bash>pkexec ...</bash>` for root), "
                        f"`<view_file ... />`, `<grep ... />`, `<patch_file ...>`, `<write_file ...>`, "
                        f"`<experience name=\"...\" params='...' />`, `<ask_user question=\"...\">...</ask_user>`, "
                        f"and built-in diagnostic tags (`<containers />`, `<systemd />`, `<network_audit />`, `<disk />`, `<gpu />`, `<tls />`, `<git />`). "
                        f"Re-issue your intended action using valid tags now."
                    )
                    self._emit_phase("RECOVER", f"Caught unknown tool tag(s): {', '.join(unknown_tags)}")
                    trace.steps.append(
                        StepRecord(
                            step_index=step_idx,
                            phase="RECOVER",
                            tool="parser_catch",
                            args_summary=", ".join(unknown_tags),
                            ok=False,
                            error_class=FailureClass.MALFORMED_TOOL_TAG,
                            recovery_hint=err_msg[:180],
                        )
                    )
                    messages.append({"role": "assistant", "content": visible_text or "(no visible reply)"})
                    messages.append({"role": "user", "content": err_msg})
                    continue

            clean_reply = self._strip_all_tool_tags(normalized_text)

            # 3. No more tool calls: check if we should nudge once to verify mutations
            if not actions:
                if had_unverified_mutation and not verification_nudged and step_idx < self.max_steps:
                    verification_nudged = True
                    self._emit_phase("VERIFY", "Checking mutation outcome before finalizing...")
                    messages.append({"role": "assistant", "content": visible_text or "(no visible reply)"})
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Verification check: you made system/file changes above. Run one quick read-only "
                                "verification command (e.g. check exit status, installed version, service status, or "
                                "file contents) to confirm the change worked, OR if you already observed proof in "
                                "tool output above, give your concise final summary now with no tool tags."
                            ),
                        }
                    )
                    continue

                if clean_reply:
                    accumulated_markdown.append(clean_reply)
                    await self._emit_markdown(clean_reply + "\n")
                messages.append({"role": "assistant", "content": visible_text or "(no visible reply)"})
                trace.succeeded = consecutive_failures == 0
                if trace.tool_steps_count == 0 or not had_unverified_mutation:
                    trace.verified = trace.succeeded
                break

            # Stream interim explanation text if present
            if clean_reply:
                accumulated_markdown.append(clean_reply)
                await self._emit_markdown(clean_reply + "\n\n")

            messages.append({"role": "assistant", "content": normalized_text or "(no visible reply)"})
            self.on_state_change("executing")

            # Batch leading read-only actions in parallel; run mutating actions sequentially
            ro_batch = [a for a in actions if a["tool"] in READONLY_TOOLS]
            if ro_batch and len(ro_batch) == len(actions) and len(actions) > 1:
                batch_to_run = ro_batch
            else:
                batch_to_run = [actions[0]]

            # Duplicate-failure guard before executing
            blocked_dup: Optional[Dict[str, Any]] = None
            for act in batch_to_run:
                for prev_cls in (
                    FailureClass.PERMISSION_DENIED,
                    FailureClass.COMMAND_NOT_FOUND,
                    FailureClass.NOT_FOUND_OR_404,
                    FailureClass.SYNTAX_OR_USAGE,
                    FailureClass.USER_DENIED,
                    FailureClass.UNKNOWN_ERROR,
                ):
                    if _action_fingerprint(act, prev_cls) in failed_fingerprints:
                        blocked_dup = act
                        break
                if blocked_dup is not None:
                    break

            if blocked_dup is not None:
                consecutive_failures += 1
                dup_msg = (
                    f"Loop guard (`DUPLICATE_FAILURE`): `{blocked_dup.get('tool')}` with "
                    f"`{_format_action_args(blocked_dup)}` already failed earlier. "
                    f"Do NOT repeat the same failing command. Try a genuinely different approach "
                    f"(e.g. different tool/flags/permissions) or ask the user via `<ask_user>`."
                )
                self._emit_phase("RECOVER", f"Blocked repeated failing command: {_format_action_args(blocked_dup)[:80]}")
                trace.steps.append(
                    StepRecord(
                        step_index=step_idx,
                        phase="RECOVER",
                        tool=str(blocked_dup.get("tool", "tool")),
                        args_summary=_format_action_args(blocked_dup),
                        ok=False,
                        error_class="DUPLICATE_FAILURE",
                        recovery_hint=dup_msg[:180],
                    )
                )
                messages.append({"role": "user", "content": dup_msg})
                if consecutive_failures >= self.max_consecutive_failures:
                    break
                continue

            # Execute batch
            t0 = time.monotonic()
            if len(batch_to_run) > 1:
                results = list(await asyncio.gather(*[self.execute_action(a) for a in batch_to_run]))
            else:
                results = [await self.execute_action(batch_to_run[0])]
            batch_ms = int((time.monotonic() - t0) * 1000)

            obs_blocks: List[str] = []
            batch_any_fail = False
            batch_user_denied = False

            for act, (t_kind, res) in zip(batch_to_run, results):
                if t_kind == "experience" and act.get("name"):
                    exp_name = str(act.get("name"))
                    if exp_name not in trace.used_experiences:
                        trace.used_experiences.append(exp_name)

                tx_id = FailureClassifier.extract_tx_id(res.output)
                if tx_id and tx_id not in trace.tx_ids:
                    trace.tx_ids.append(tx_id)

                err_cls, recovery_hint = FailureClassifier.classify(res)
                phase = "VERIFY" if (verification_nudged and t_kind in READONLY_TOOLS or (had_unverified_mutation and t_kind in READONLY_TOOLS)) else "ACT"

                step_rec = StepRecord(
                    step_index=step_idx,
                    phase=phase,
                    tool=t_kind,
                    args_summary=_format_action_args(act),
                    ok=res.ok,
                    exit_code=res.exit_code,
                    error_class=err_cls,
                    recovery_hint=recovery_hint,
                    duration_ms=res.duration_ms or batch_ms,
                    tx_id=tx_id,
                    output_excerpt=(res.output or "")[:400],
                )
                trace.steps.append(step_rec)

                status_icon = "✅" if res.ok else "⚠️"
                meta_badge = f" (`{err_cls}`)" if not res.ok and err_cls != FailureClass.NONE else ""
                cmd_card = (
                    f"{status_icon} **{res.title}**{meta_badge}\n"
                    f"```text\n{res.output[:1800]}\n```\n\n"
                )
                accumulated_markdown.append(cmd_card.strip())
                await self._emit_markdown(cmd_card)

                if res.ok:
                    if had_prior_failure:
                        trace.recoveries_succeeded += 1
                        had_prior_failure = False
                        self._emit_phase("RECOVER", f"Recovered successfully via `{t_kind}`")
                    if t_kind in MUTATING_TOOLS and not self._is_readonly_bash(act):
                        had_unverified_mutation = True
                    else:
                        if had_unverified_mutation:
                            trace.verified = True
                            had_unverified_mutation = False
                            self._emit_phase("VERIFY", f"Verified outcome via `{t_kind}`")
                    obs_blocks.append(f"Tool `{t_kind}` succeeded (exit={res.exit_code}):\n{res.output[:3500]}")
                else:
                    batch_any_fail = True
                    had_prior_failure = True
                    trace.recoveries_attempted += 1
                    failed_fingerprints.add(_action_fingerprint(act, err_cls))
                    self._emit_phase("RECOVER", f"Caught {err_cls} on `{t_kind}` (exit={res.exit_code})")
                    if err_cls == FailureClass.USER_DENIED:
                        batch_user_denied = True
                    obs_blocks.append(
                        f"Tool `{t_kind}` FAILED (exit={res.exit_code}, exception={err_cls}):\n"
                        f"{res.output[:3000]}\n\n"
                        f"Exception recovery guidance: {recovery_hint}"
                    )

            if batch_any_fail:
                consecutive_failures += 1
            else:
                consecutive_failures = 0
                if tag_repairs:
                    trace.recoveries_succeeded += 1

            # Abort & optionally roll back if user denied or consecutive failure budget exhausted
            if batch_user_denied:
                stop_note = "⏸️ Stopped because the action was not authorized. Let me know how you'd like to proceed."
                accumulated_markdown.append(stop_note)
                await self._emit_markdown(stop_note + "\n")
                self.on_state_change("idle")
                trace.succeeded = False
                break

            if consecutive_failures >= self.max_consecutive_failures:
                rb_notes = self._maybe_rollback(trace)
                fail_note = (
                    f"⚠️ **Stopped after {consecutive_failures} consecutive failed attempts** to avoid looping."
                    + (f"\n\n{rb_notes}" if rb_notes else "")
                    + "\n\nShare a bit more detail or let me know how you want to continue."
                )
                accumulated_markdown.append(fail_note)
                await self._emit_markdown(fail_note + "\n")
                self.on_state_change("alert")
                trace.succeeded = False
                break

            next_prompt = (
                "\n\n".join(obs_blocks)
                + "\n\nContinue with the next tool tag (or adapt your strategy if an exception occurred), "
                "call `<ask_user question=\"...\">` if you need user input, or provide a concise final "
                "summary with no tool tags once verified and complete."
            )
            messages.append({"role": "user", "content": next_prompt})

        trace.final_text = "\n\n".join(accumulated_markdown).strip() or "Completed."
        trace.duration_ms = int((time.monotonic() - started) * 1000)
        if not trace.succeeded and trace.steps and trace.steps[-1].ok and consecutive_failures == 0:
            trace.succeeded = True
        if trace.succeeded and not had_unverified_mutation:
            trace.verified = True
        self.on_state_change("happy" if trace.succeeded else "alert")
        return True, trace

    @staticmethod
    def _is_readonly_bash(act: Dict[str, Any]) -> bool:
        if act.get("tool") != "bash":
            return False
        cmd = str(act.get("command", "")).strip()
        if not cmd:
            return True
        first = cmd.split()[0]
        return first in (
            "ls", "cat", "head", "tail", "grep", "rg", "find", "ps", "ss", "lsof",
            "df", "du", "free", "uptime", "uname", "which", "dpkg", "dpkg-query",
            "apt-cache", "systemctl", "journalctl", "ip", "dig", "curl", "openssl",
        ) and not any(w in cmd for w in ("install", "remove", "purge", "restart", "stop", "kill", "rm ", "mv ", "cp ", ">"))

    def _maybe_rollback(self, trace: LoopTrace) -> str:
        if not trace.tx_ids:
            return ""
        if self.auto_rollback and self.rollback_tx is not None:
            notes: List[str] = []
            for tx_id in reversed(trace.tx_ids):
                rb_res = self.rollback_tx(tx_id)
                if rb_res.ok:
                    trace.rolled_back_txs.append(tx_id)
                    self._emit_phase("ROLLBACK", f"Rolled back snapshot `{tx_id}`")
                    trace.steps.append(
                        StepRecord(
                            step_index=len(trace.steps) + 1,
                            phase="ROLLBACK",
                            tool="rollback_transaction",
                            args_summary=tx_id,
                            ok=True,
                            tx_id=tx_id,
                        )
                    )
                    notes.append(f"↩️ Automatically rolled back `{tx_id}`.")
            return "\n".join(notes)
        return (
            f"💾 Snapshots were saved for file edits (`{', '.join(trace.tx_ids)}`). "
            f"Run `/undo` if you want to revert them."
        )
