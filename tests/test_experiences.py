"""Unit & integration tests for Pillar 3: Hardened Learning Curve & Python Experiences."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from tchiko.agent_engine import TchikoAgentEngine
from tchiko.config_manager import ConfigManager
from tchiko.experiences import (
    ExperienceRegistry,
    ExperienceValidator,
    MATURITY_DRAFT,
    MATURITY_HARDENED,
    MATURITY_NEEDS_REPAIR,
    MATURITY_VERIFIED,
    redact_secrets,
)
from tchiko.system_tools import LinuxSystemToolkit


VALID_TOOL_TEMPLATE = '''#!/usr/bin/env python3
"""Demo safe tool."""
import argparse, json, sys

def run(params, dry_run=False):
    if dry_run:
        return {"ok": True, "summary": "dry-run ok", "details": "preview"}
    if params.get("fail"):
        return {"ok": False, "summary": "forced failure", "details": "boom"}
    return {"ok": True, "summary": "demo ok v1", "details": "hello from v1"}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--params", default="{}")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args()
    res = run(json.loads(a.params), dry_run=(a.dry_run or a.self_test))
    print(json.dumps(res))
    return 0 if res.get("ok") else 1

if __name__ == "__main__":
    sys.exit(main())
'''


class TestExperienceValidator(unittest.TestCase):
    def test_rejects_banned_calls_syntax_errors_and_secrets(self) -> None:
        r_eval = ExperienceValidator.validate_script("def run(p, dry_run=False):\n    return eval('1+1')\n")
        self.assertFalse(r_eval.ok)
        self.assertTrue(any("eval" in e for e in r_eval.errors))

        r_syn = ExperienceValidator.validate_script("def run(:\n    pass")
        self.assertFalse(r_syn.ok)
        self.assertTrue(any("syntax" in e.lower() for e in r_syn.errors))

        r_sec = ExperienceValidator.validate_script('API_KEY = "AIzaSyA1234567890123456789012345678901234"\n')
        self.assertFalse(r_sec.ok)
        self.assertTrue(any("secret" in e.lower() for e in r_sec.errors))

    def test_redact_secrets_scrubs_keys_and_passwords(self) -> None:
        raw = 'token="ghp_abcdefghijklmnopqrstuvwxyz123456" password="supersecretvalue"'
        scrubbed = redact_secrets(raw)
        self.assertNotIn("ghp_abcdef", scrubbed)
        self.assertNotIn("supersecretvalue", scrubbed)

    def test_accepts_valid_script_and_classifies_risk_tier(self) -> None:
        rep = ExperienceValidator.validate_script(VALID_TOOL_TEMPLATE)
        self.assertTrue(rep.ok, rep.errors)
        self.assertEqual(rep.risk_tier, "SAFE_READONLY")


class TestExperienceRegistryAndEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmp_dir.name)
        self.cfg_path = self.tmp / "settings.json"
        self.exp_dir = self.tmp / "experiences"
        self.config = ConfigManager(config_path=self.cfg_path)
        self.config.set_all_permissions(True)
        self.registry = ExperienceRegistry(experiences_dir=self.exp_dir, config=self.config)
        self.registry.ensure_starter_experiences()

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_starter_experiences_seeded_and_executable(self) -> None:
        exps = self.registry.list_experiences()
        slugs = {e.slug for e in exps}
        self.assertIn("port-socket-inspector", slugs)
        self.assertIn("systemd-service-doctor", slugs)
        self.assertIn("disk-space-auditor", slugs)

        # Dry-run every starter experience
        for slug in ("port-socket-inspector", "systemd-service-doctor", "disk-space-auditor"):
            res = self.registry.run_experience(slug, dry_run=True)
            self.assertTrue(res.ok, f"Dry-run failed for {slug}: {res.output}")

        # Live execution of disk-space-auditor should succeed
        live = self.registry.run_experience("disk-space-auditor", params={"path": str(self.tmp)}, dry_run=False)
        self.assertTrue(live.ok, live.output)

    def test_maturity_progression_hardened_and_needs_repair_and_rollback(self) -> None:
        exp, msg = self.registry.save_experience(
            slug="demo-check",
            title="Demo Check",
            description="Safe demo checker",
            code=VALID_TOOL_TEMPLATE,
            triggers=["demo", "check"],
            category="system",
            auto_promote=True,
        )
        self.assertIsNotNone(exp, msg)
        assert exp is not None
        self.assertEqual(exp.maturity, MATURITY_VERIFIED)

        # 3 successful runs promote VERIFIED -> HARDENED
        for _ in range(3):
            res = self.registry.run_experience("demo-check", dry_run=False)
            self.assertTrue(res.ok, res.output)
        exp_after = self.registry.get_experience("demo-check")
        assert exp_after is not None
        self.assertEqual(exp_after.maturity, MATURITY_HARDENED)
        self.assertEqual(exp_after.runs, 3)

        # 2 consecutive failures transition to NEEDS_REPAIR
        for _ in range(2):
            res = self.registry.run_experience("demo-check", params={"fail": True}, dry_run=False)
            self.assertFalse(res.ok)
        exp_repair = self.registry.get_experience("demo-check")
        assert exp_repair is not None
        self.assertEqual(exp_repair.maturity, MATURITY_NEEDS_REPAIR)

        # Updating archives v1 and bumps version to 2; rollback restores v1
        v2_code = VALID_TOOL_TEMPLATE.replace("hello from v1", "hello from v2")
        exp_v2, _ = self.registry.save_experience(
            slug="demo-check",
            title="Demo Check",
            description="Safe demo checker v2",
            code=v2_code,
            triggers=["demo", "check"],
            category="system",
            auto_promote=True,
        )
        assert exp_v2 is not None
        self.assertEqual(exp_v2.version, 2)
        self.assertIn(1, self.registry.get_versions("demo-check"))

        ok_rb, rb_msg = self.registry.rollback_version("demo-check")
        self.assertTrue(ok_rb, rb_msg)
        self.assertIn("hello from v1", self.registry.get_script_source("demo-check"))

    def test_learn_from_episode_distills_python_script_and_respects_risk_policy(self) -> None:
        safe_episode = {
            "prompt": "inspect kernel version and uptime",
            "steps": [
                {"tool": "bash", "args_summary": "uname -r", "ok": True},
                {"tool": "bash", "args_summary": "cat /proc/uptime", "ok": True},
            ],
            "succeeded": True,
            "verified": True,
            "recoveries_succeeded": 0,
        }
        exp, msg = self.registry.learn_from_episode(safe_episode, custom_slug="kernel-uptime-audit")
        self.assertIsNotNone(exp, msg)
        assert exp is not None
        self.assertEqual(exp.maturity, MATURITY_VERIFIED)
        res = self.registry.run_experience(exp.slug, dry_run=False)
        self.assertTrue(res.ok, res.output)

        # Privileged script must stay DRAFT until explicitly approved
        priv_episode = {
            "prompt": "refresh apt packages with pkexec",
            "steps": [
                {"tool": "bash", "args_summary": "pkexec apt-get update", "ok": True},
                {"tool": "bash", "args_summary": "apt-cache stats", "ok": True},
            ],
            "succeeded": True,
            "verified": True,
            "recoveries_succeeded": 1,
        }
        p_exp, p_msg = self.registry.learn_from_episode(priv_episode, custom_slug="apt-refresh-tool")
        self.assertIsNotNone(p_exp, p_msg)
        assert p_exp is not None
        self.assertEqual(p_exp.risk_tier, "PRIVILEGED_DESTRUCTIVE")
        self.assertEqual(p_exp.maturity, MATURITY_DRAFT)

        approved = self.registry.approve_experience(p_exp.slug)
        self.assertIsNotNone(approved)
        assert approved is not None
        self.assertEqual(approved.maturity, MATURITY_VERIFIED)

    def test_match_experiences_and_learning_metrics(self) -> None:
        matches = self.registry.match_experiences("check which listening port is open on tcp")
        self.assertTrue(any(e.slug == "port-socket-inspector" for e in matches))

        metrics = self.registry.learning_metrics()
        self.assertGreaterEqual(metrics["total"], 3)
        self.assertIn("curve_points", metrics)
        self.assertIn("by_maturity", metrics)
        self.assertIn("overall_success_rate", metrics)

    def test_engine_slash_commands_for_experiences_and_learn(self) -> None:
        toolkit = LinuxSystemToolkit(self.config)
        engine = TchikoAgentEngine(self.config, toolkit, experiences_dir=self.exp_dir)

        async def _run_slash(cmd: str) -> str:
            out: list[str] = []
            await engine._handle_prompt(
                prompt=cmd,
                on_thought=lambda _: None,
                on_tool_call=lambda _n, _a: None,
                on_token=lambda _: None,
                on_complete=lambda txt: out.append(txt),
                on_state_change=lambda _: None,
                on_approval_needed=None,
            )
            return out[-1] if out else ""

        idx_out = asyncio.run(_run_slash("/experiences"))
        self.assertIn("port-socket-inspector", idx_out)

        test_out = asyncio.run(_run_slash("/exp test disk-space-auditor"))
        self.assertIn("disk-space-auditor", test_out)

        engine.last_episode = {
            "prompt": "check python and host kernel",
            "steps": [
                {"tool": "bash", "args_summary": "python3 --version", "ok": True},
                {"tool": "bash", "args_summary": "uname -s", "ok": True},
            ],
            "succeeded": True,
            "verified": True,
            "recoveries_succeeded": 0,
        }
        learn_out = asyncio.run(_run_slash("/learn python-host-check"))
        self.assertIn("python-host-check", learn_out)
        self.assertIsNotNone(engine.experiences.get_experience("python-host-check"))

    def test_security_hardening_blocks_dangerous_imports_and_secrets(self) -> None:
        for bad_import in ("import importlib\n", "import ctypes\n", "import pickle\n"):
            rep = ExperienceValidator.validate_script(bad_import + VALID_TOOL_TEMPLATE)
            self.assertFalse(rep.ok, f"Expected AST validator to reject: {bad_import.strip()}")

        aws_code = VALID_TOOL_TEMPLATE.replace("hello from v1", "AKIAIOSFODNN7EXAMPLE")
        self.assertFalse(ExperienceValidator.validate_script(aws_code).ok)

        jwt_code = VALID_TOOL_TEMPLATE.replace("hello from v1", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123def456")
        self.assertFalse(ExperienceValidator.validate_script(jwt_code).ok)

    def test_structured_tool_distillation_and_synonym_retrieval(self) -> None:
        ep = {
            "prompt": "audit network interfaces and listening sockets",
            "steps": [
                {"tool": "network_audit", "args_summary": "scope=all", "ok": True},
                {"tool": "bash", "args_summary": "ip -brief addr", "ok": True},
            ],
            "succeeded": True,
            "verified": True,
            "recoveries_succeeded": 0,
        }
        exp, msg = self.registry.learn_from_episode(ep)
        self.assertIsNotNone(exp, msg)

        # Synonym query should still retrieve disk-space-auditor at #1
        disk_matches = self.registry.match_experiences("my drive is almost full, find largest folders")
        self.assertTrue(disk_matches and disk_matches[0].slug == "disk-space-auditor")

        # Port query should still prefer port-socket-inspector at #1
        port_matches = self.registry.match_experiences("check listening ports on tcp")
        self.assertTrue(port_matches and port_matches[0].slug == "port-socket-inspector")


if __name__ == "__main__":
    unittest.main()
