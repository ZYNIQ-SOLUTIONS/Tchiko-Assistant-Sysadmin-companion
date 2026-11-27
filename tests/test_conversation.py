"""Unit tests for Pillar 1: Humanized Natural Conversation & Interactive Clarification."""

from __future__ import annotations

import time
import unittest

from tchiko.conversation import (
    ConversationAnalyzer,
    PendingTask,
    extract_suggested_command,
    is_anaphoric_run_target,
    parse_ask_user_tag,
    strip_ask_user_tags,
)


class TestConversationAnalyzer(unittest.TestCase):
    def setUp(self) -> None:
        self.analyzer = ConversationAnalyzer()

    def test_casual_greetings_and_thanks(self) -> None:
        for text in ("hi", "hey tchiko", "hello!", "thanks so much", "good morning"):
            dec = self.analyzer.analyze(text, memory={})
            self.assertEqual(dec.kind, "casual_chat", f"Expected casual_chat for {text!r}")
            self.assertTrue(len(dec.reply_text) > 0)

    def test_slash_commands_always_bypass_gating(self) -> None:
        for cmd in ("/doctor", "/experiences", "/learn", "$ uname -a"):
            dec = self.analyzer.analyze(cmd, memory={})
            self.assertEqual(dec.kind, "clear_task")
            self.assertEqual(dec.resolved_prompt, cmd)

    def test_anaphora_run_it_resolves_suggested_command_and_converts_sudo(self) -> None:
        mem = {
            "last_suggested_command": "sudo tailscale up --ssh",
            "history": [],
        }
        dec = self.analyzer.analyze("run it", memory=mem)
        self.assertEqual(dec.kind, "anaphora_command")
        self.assertEqual(dec.suggested_command, "pkexec tailscale up --ssh")

    def test_anaphora_run_it_falls_back_to_history_code_block(self) -> None:
        mem = {
            "history": [
                {"role": "assistant", "content": "Next step:\n```bash\nsystemctl status nginx\n```"}
            ]
        }
        dec = self.analyzer.analyze("go ahead", memory=mem)
        self.assertEqual(dec.kind, "anaphora_command")
        self.assertEqual(dec.suggested_command, "systemctl status nginx")

    def test_anaphora_run_it_asks_clarification_when_no_command_exists(self) -> None:
        dec = self.analyzer.analyze("run it", memory={})
        self.assertEqual(dec.kind, "needs_clarification")
        self.assertIsNotNone(dec.clarification)
        assert dec.clarification is not None
        self.assertTrue(len(dec.clarification.options) >= 2)

    def test_underspecified_prompts_trigger_clarification(self) -> None:
        for prompt in (
            "install something",
            "clean up",
            "fix it",
            "restart the service",
            "kill the port",
            "delete files",
            "setup my server",
        ):
            dec = self.analyzer.analyze(prompt, memory={})
            self.assertEqual(dec.kind, "needs_clarification", f"Expected clarification for {prompt!r}")
            self.assertIsNotNone(dec.clarification)
            assert dec.clarification is not None
            self.assertTrue(len(dec.clarification.question) > 5)

    def test_fix_it_proceeds_when_recent_error_in_memory(self) -> None:
        mem = {"last_output": "Error: nginx.service failed with exit code 1"}
        dec = self.analyzer.analyze("fix it", memory=mem)
        self.assertEqual(dec.kind, "clear_task")

    def test_ask_before_ambiguous_false_bypasses_preflight(self) -> None:
        dec = self.analyzer.analyze("clean up", memory={}, ask_before_ambiguous=False)
        self.assertEqual(dec.kind, "clear_task")

    def test_pending_task_merges_ordinal_reply(self) -> None:
        pending = PendingTask(
            id="clarify_1234",
            original_prompt="clean up",
            question="What level of cleanup?",
            options=["Safe audit first", "Clean safe caches", "Include Docker cache"],
        )
        dec = self.analyzer.analyze("2", memory={"pending_task": pending.to_dict()})
        self.assertEqual(dec.kind, "clarification_reply")
        self.assertIn("clean up", dec.resolved_prompt)
        self.assertIn("Clean safe caches", dec.resolved_prompt)

    def test_pending_task_cancel_phrase(self) -> None:
        pending = PendingTask(
            id="clarify_1234",
            original_prompt="delete files",
            question="Which path?",
        )
        dec = self.analyzer.analyze("nevermind", memory={"pending_task": pending.to_dict()})
        self.assertEqual(dec.kind, "cancel_pending")
        self.assertIn("cancelled", dec.reply_text.lower())

    def test_pending_task_expiry(self) -> None:
        old = PendingTask(
            id="clarify_old",
            original_prompt="clean up",
            question="Which level?",
            created_at=time.time() - 3600,
        )
        self.assertTrue(old.is_expired())
        dec = self.analyzer.analyze("check listening ports", memory={"pending_task": old.to_dict()})
        self.assertEqual(dec.kind, "clear_task")

    def test_extract_suggested_command(self) -> None:
        md = "Here is the command:\n```bash\n# comment\napt update\napt upgrade -y\n```"
        self.assertEqual(extract_suggested_command(md), "apt update && apt upgrade -y")
        inline = "Try running `systemctl restart docker` to apply."
        self.assertEqual(extract_suggested_command(inline), "systemctl restart docker")

    def test_parse_and_strip_ask_user_tags(self) -> None:
        raw = (
            "Before proceeding, I need one detail.\n"
            '<ask_user question="Which container should I restart?" context="Found 2 nginx containers.">'
            "<option>nginx-prod</option><option>nginx-staging</option></ask_user>"
        )
        req = parse_ask_user_tag(raw, original_prompt="restart nginx")
        self.assertIsNotNone(req)
        assert req is not None
        self.assertEqual(req.question, "Which container should I restart?")
        self.assertEqual(req.context, "Found 2 nginx containers.")
        self.assertEqual(req.options, ["nginx-prod", "nginx-staging"])
        self.assertEqual(strip_ask_user_tags(raw), "Before proceeding, I need one detail.")

    def test_parse_ask_user_self_closing_with_reason_alias(self) -> None:
        raw = '<ask_user question="Confirm target host?" reason="Multiple SSH hosts configured." />'
        req = parse_ask_user_tag(raw)
        self.assertIsNotNone(req)
        assert req is not None
        self.assertEqual(req.question, "Confirm target host?")
        self.assertEqual(req.context, "Multiple SSH hosts configured.")
        self.assertEqual(strip_ask_user_tags(raw), "")

    def test_is_anaphoric_run_target(self) -> None:
        self.assertTrue(is_anaphoric_run_target("it"))
        self.assertTrue(is_anaphoric_run_target("that command"))
        self.assertFalse(is_anaphoric_run_target("uname -a"))

    def test_elongated_greetings_and_natural_ambiguity(self) -> None:
        for casual in ("heyyy", "good night", "thx bro", "how are you doing?", "are you there?"):
            dec = self.analyzer.analyze(casual, memory={})
            self.assertEqual(dec.kind, "casual_chat", f"Expected casual_chat for: {casual}")

        for ambig in ("can you help me", "update my apps", "my docker is acting weird", "network is slow", "fix permissions", "delete old backups"):
            dec = self.analyzer.analyze(ambig, memory={})
            self.assertEqual(dec.kind, "needs_clarification", f"Expected needs_clarification for: {ambig}")

        # Must preserve 0% false positives on specific commands
        for clear in ("restart docker", "show listening ports", "check nginx status", "update apt packages"):
            dec = self.analyzer.analyze(clear, memory={})
            self.assertEqual(dec.kind, "clear_task", f"Unexpected clarify for clear task: {clear}")

        dec_anaph = self.analyzer.analyze("try it", memory={"last_suggested_command": "ss -tulnp"})
        self.assertEqual(dec_anaph.kind, "anaphora_command")
        self.assertEqual(dec_anaph.suggested_command, "ss -tulnp")


if __name__ == "__main__":
    unittest.main()
