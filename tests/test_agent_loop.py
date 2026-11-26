"""Unit tests for Pillar 2: Resilient Do -> Observe -> Try/Catch & Recover -> Verify Agentic Loop."""

from __future__ import annotations

import asyncio
import re
import unittest
from typing import Any, Dict, List, Optional, Tuple

from tchiko.agent_loop import FailureClass, FailureClassifier, ResilientAgentLoop
from tchiko.system_tools import ToolResult


def _simple_extract(text: str) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = []
    for m in re.finditer(r"<bash>(.*?)</bash>", text, flags=re.DOTALL | re.IGNORECASE):
        actions.append({"tool": "bash", "command": m.group(1).strip()})
    for m in re.finditer(r'<patch_file\s+path=["\']([^"\']+)["\']>(.*?)</patch_file>', text, flags=re.DOTALL):
        actions.append({"tool": "patch_file", "path": m.group(1), "content": m.group(2)})
    return actions


class TestFailureClassifier(unittest.TestCase):
    def test_normalize_common_tag_mistakes(self) -> None:
        raw = "Let me fix that: <pkexec>apt update</pkexec> and <sudo>systemctl restart nginx</sudo> and <shell>ss -tulnp</shell>"
        fixed, repairs = FailureClassifier.normalize_common_tag_mistakes(raw)
        self.assertIn("<bash>pkexec apt update</bash>", fixed)
        self.assertIn("<bash>pkexec systemctl restart nginx</bash>", fixed)
        self.assertIn("<bash>ss -tulnp</bash>", fixed)
        self.assertEqual(len(repairs), 3)

    def test_detect_unrecognized_tool_tags_ignores_code_fences(self) -> None:
        prose = "```xml\n<custom_example>ok</custom_example>\n```\nNow run <foobar>test</foobar>"
        unknown = FailureClassifier.detect_unrecognized_tool_tags(prose)
        self.assertEqual(unknown, ["foobar"])

    def test_classify_all_major_error_classes(self) -> None:
        cases = [
            (ToolResult(False, "err", "Permission denied (are you root?)", exit_code=1), FailureClass.PERMISSION_DENIED),
            (ToolResult(False, "err", "Unable to acquire the dpkg frontend lock", exit_code=100), FailureClass.LOCK_OR_BUSY),
            (ToolResult(False, "err", "bash: foo: command not found", exit_code=127), FailureClass.COMMAND_NOT_FOUND),
            (ToolResult(False, "err", "No such file or directory", exit_code=2), FailureClass.NOT_FOUND_OR_404),
            (ToolResult(False, "err", "Command timed out after 30s", exit_code=124), FailureClass.TIMEOUT),
            (ToolResult(False, "err", "User denied execution", exit_code=126), FailureClass.USER_DENIED),
        ]
        for res, expected in cases:
            cls, hint = FailureClassifier.classify(res)
            self.assertEqual(cls, expected, f"Expected {expected} for {res.output!r}, got {cls}")
            self.assertTrue(len(hint) > 10)


class TestResilientAgentLoop(unittest.TestCase):
    def test_recovers_from_permission_error_and_repairs_pkexec_tag(self) -> None:
        # Step 1: emits unprivileged apt update -> fails PERMISSION_DENIED
        # Step 2: emits malformed <pkexec>apt update</pkexec> -> auto-normalized -> succeeds
        # Step 3: post-mutation verification check
        # Step 4: final summary
        responses = iter([
            "<bash>apt update</bash>",
            "<pkexec>apt update</pkexec>",
            "<bash>apt-cache policy</bash>",
            "All done — package lists refreshed and verified.",
        ])
        executed: List[str] = []
        phases: List[str] = []

        async def query_llm(_msgs: List[Dict[str, str]]) -> Optional[str]:
            return next(responses, None)

        async def execute_action(act: Dict[str, Any]) -> Tuple[str, ToolResult]:
            cmd = act["command"]
            executed.append(cmd)
            if cmd == "apt update":
                return "bash", ToolResult(False, "apt", "E: Could not open lock file - Permission denied", exit_code=100)
            return "bash", ToolResult(True, "apt", "Reading package lists... Done", exit_code=0)

        loop = ResilientAgentLoop(
            query_llm=query_llm,
            strip_think=lambda s: (s, []),
            extract_actions=_simple_extract,
            execute_action=execute_action,
            on_thought=lambda _: None,
            on_token=lambda _: None,
            on_state_change=lambda _: None,
            on_phase=lambda p, _t: phases.append(p),
        )

        handled, trace = asyncio.run(loop.run("refresh apt", [{"role": "user", "content": "refresh apt"}]))
        self.assertTrue(handled)
        self.assertTrue(trace.succeeded)
        self.assertGreaterEqual(trace.recoveries_attempted, 1)
        self.assertGreaterEqual(trace.recoveries_succeeded, 1)
        self.assertIn("pkexec apt update", executed)
        self.assertIn("RECOVER", phases)

    def test_duplicate_failure_guard_blocks_infinite_retry(self) -> None:
        responses = iter([
            "<bash>badcmd --flag</bash>",
            "<bash>badcmd --flag</bash>",
            "Stopped retrying the failing command and reporting the issue.",
        ])
        exec_count = 0

        async def query_llm(_msgs: List[Dict[str, str]]) -> Optional[str]:
            return next(responses, None)

        async def execute_action(_act: Dict[str, Any]) -> Tuple[str, ToolResult]:
            nonlocal exec_count
            exec_count += 1
            return "bash", ToolResult(False, "err", "bash: badcmd: command not found", exit_code=127)

        loop = ResilientAgentLoop(
            query_llm=query_llm,
            strip_think=lambda s: (s, []),
            extract_actions=_simple_extract,
            execute_action=execute_action,
            on_thought=lambda _: None,
            on_token=lambda _: None,
            on_state_change=lambda _: None,
        )

        handled, trace = asyncio.run(loop.run("run badcmd", [{"role": "user", "content": "run badcmd"}]))
        self.assertTrue(handled)
        self.assertEqual(exec_count, 1, "Duplicate failing command must not be executed twice")
        self.assertIn("Stopped retrying", trace.final_text)

    def test_consecutive_failures_trigger_auto_rollback(self) -> None:
        responses = iter([
            '<patch_file path="/tmp/demo.conf">bad=1</patch_file>',
            "<bash>nginx -t</bash>",
            "<bash>systemctl reload nginx</bash>",
            "<bash>curl -I http://localhost</bash>",
        ])
        rolled_back: List[str] = []

        async def query_llm(_msgs: List[Dict[str, str]]) -> Optional[str]:
            return next(responses, None)

        async def execute_action(act: Dict[str, Any]) -> Tuple[str, ToolResult]:
            if act["tool"] == "patch_file":
                return "patch_file", ToolResult(True, "patch", "Patched /tmp/demo.conf [`tx_abc123`]", exit_code=0)
            return "bash", ToolResult(False, "err", "nginx: configuration file test failed", exit_code=1)

        def rollback_tx(tx_id: str) -> ToolResult:
            rolled_back.append(tx_id)
            return ToolResult(True, "rollback", f"Restored {tx_id}")

        loop = ResilientAgentLoop(
            query_llm=query_llm,
            strip_think=lambda s: (s, []),
            extract_actions=_simple_extract,
            execute_action=execute_action,
            rollback_tx=rollback_tx,
            on_thought=lambda _: None,
            on_token=lambda _: None,
            on_state_change=lambda _: None,
            max_consecutive_failures=2,
            auto_rollback=True,
        )

        handled, trace = asyncio.run(loop.run("update nginx", [{"role": "user", "content": "update nginx"}]))
        self.assertTrue(handled)
        self.assertFalse(trace.succeeded)
        self.assertEqual(rolled_back, ["tx_abc123"])
        self.assertEqual(trace.rolled_back_txs, ["tx_abc123"])

    def test_ask_user_tag_pauses_loop_and_populates_trace(self) -> None:
        responses = iter([
            'I need one quick confirmation.\n<ask_user question="Use port 8080 or 9090?" context="Port 80 is busy."><option>8080</option><option>9090</option></ask_user>'
        ])

        async def query_llm(_msgs: List[Dict[str, str]]) -> Optional[str]:
            return next(responses, None)

        async def execute_action(_act: Dict[str, Any]) -> Tuple[str, ToolResult]:
            raise AssertionError("No tool should execute when <ask_user> pauses the turn")

        loop = ResilientAgentLoop(
            query_llm=query_llm,
            strip_think=lambda s: (s, []),
            extract_actions=_simple_extract,
            execute_action=execute_action,
            on_thought=lambda _: None,
            on_token=lambda _: None,
            on_state_change=lambda _: None,
        )

        handled, trace = asyncio.run(loop.run("start web server", [{"role": "user", "content": "start web server"}]))
        self.assertTrue(handled)
        self.assertIsNotNone(trace.asked_user)
        assert trace.asked_user is not None
        self.assertEqual(trace.asked_user.question, "Use port 8080 or 9090?")
        self.assertEqual(trace.asked_user.options, ["8080", "9090"])

    def test_network_transient_and_tag_repair_variants(self) -> None:
        cls_net, _ = FailureClassifier.classify(ToolResult(False, "curl", "Temporary failure in name resolution", exit_code=6))
        self.assertEqual(cls_net, FailureClass.NETWORK_TRANSIENT)
        cls_syn, _ = FailureClassifier.classify(ToolResult(False, "cli", "error: unrecognized arguments: --bogus", exit_code=2))
        self.assertEqual(cls_syn, FailureClass.SYNTAX_OR_USAGE)

        repaired_attr, _ = FailureClassifier.normalize_common_tag_mistakes('<bash command="uname -a" />')
        self.assertIn("<bash>uname -a</bash>", repaired_attr)
        repaired_run, _ = FailureClassifier.normalize_common_tag_mistakes("<run>df -h</run>")
        self.assertIn("<bash>df -h</bash>", repaired_run)


if __name__ == "__main__":
    unittest.main()
