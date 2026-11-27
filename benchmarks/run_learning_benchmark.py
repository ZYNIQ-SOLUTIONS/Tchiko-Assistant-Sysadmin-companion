#!/usr/bin/env python3
"""Quantitative Benchmark & Learning-Curve Evaluation Suite for Tchiko Assistant.

Measures real, reproducible metrics across all 4 pillars:
  1. Conversation & Clarification Intelligence (Precision, Recall, F1, False-Positive Rate)
  2. Resilient Agentic Loop (Failure classification, Tag repair, Recovery rate, Rollback)
  3. Hardened Learning Curve & Python Experiences (Distillation rate, Retrieval Hit@1/Hit@3
     on paraphrased/synonym queries, Cold vs Warm latency & step reduction, Evolution/Dedup)
  4. Security & AST Validator Hardening (Adversarial block rate & risk-tier accuracy)

Outputs a structured JSON report and concise terminal summary so before/after
improvements can be tracked objectively.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tchiko.agent_loop import FailureClass, FailureClassifier, ResilientAgentLoop
from tchiko.config_manager import ConfigManager
from tchiko.conversation import ConversationAnalyzer
from tchiko.experiences import (
    ExperienceRegistry,
    ExperienceValidator,
    MATURITY_HARDENED,
    MATURITY_VERIFIED,
)
from tchiko.system_tools import LinuxSystemToolkit, ToolResult


# ── Suite A: Conversation & Clarification Benchmark ──────────────────────────
def run_conversation_benchmark() -> Dict[str, Any]:
    analyzer = ConversationAnalyzer()

    # (prompt, memory, expected_kind, category)
    cases: List[Tuple[str, Dict[str, Any], str, str]] = [
        # Casual chat (greetings, thanks, natural small talk)
        ("hi", {}, "casual_chat", "casual"),
        ("heyyy tchiko", {}, "casual_chat", "casual"),
        ("good morning!", {}, "casual_chat", "casual"),
        ("good night", {}, "casual_chat", "casual"),
        ("thx bro", {}, "casual_chat", "casual"),
        ("thank you so much!", {}, "casual_chat", "casual"),
        ("appreciate it", {}, "casual_chat", "casual"),
        ("how are you doing?", {}, "casual_chat", "casual"),
        ("are you there?", {}, "casual_chat", "casual"),
        ("can you help me?", {}, "needs_clarification", "ambiguous"),

        # Ambiguous / underspecified tasks -> SHOULD ask clarification
        ("install something", {}, "needs_clarification", "ambiguous"),
        ("clean up", {}, "needs_clarification", "ambiguous"),
        ("fix it", {}, "needs_clarification", "ambiguous"),
        ("restart the service", {}, "needs_clarification", "ambiguous"),
        ("kill the port", {}, "needs_clarification", "ambiguous"),
        ("delete files", {}, "needs_clarification", "ambiguous"),
        ("setup my server", {}, "needs_clarification", "ambiguous"),
        ("update my apps", {}, "needs_clarification", "ambiguous"),
        ("my docker is acting weird", {}, "needs_clarification", "ambiguous"),
        ("network is slow", {}, "needs_clarification", "ambiguous"),
        ("fix permissions", {}, "needs_clarification", "ambiguous"),
        ("delete old backups", {}, "needs_clarification", "ambiguous"),
        ("run it", {}, "needs_clarification", "anaphora_missing"),

        # Clear actionable tasks -> MUST NOT over-clarify (zero false positives)
        ("install htop with apt", {}, "clear_task", "clear"),
        ("restart nginx service", {}, "clear_task", "clear"),
        ("delete /tmp/tchiko_old.log", {}, "clear_task", "clear"),
        ("check which process is listening on port 8080", {}, "clear_task", "clear"),
        ("clean apt cache and journald logs older than 7 days", {}, "clear_task", "clear"),
        ("fix it", {"last_output": "Error: nginx.service failed with exit code 1"}, "clear_task", "clear"),
        ("show disk usage in /var/log", {}, "clear_task", "clear"),
        ("/doctor", {}, "clear_task", "clear"),

        # Anaphora resolution with context
        ("run it", {"last_suggested_command": "sudo systemctl restart nginx"}, "anaphora_command", "anaphora"),
        ("go ahead", {"last_suggested_command": "ss -tulnp"}, "anaphora_command", "anaphora"),
        ("execute that", {"history": [{"role": "assistant", "content": "Run:\n```bash\ndocker ps -a\n```"}]}, "anaphora_command", "anaphora"),
        ("try it", {"last_suggested_command": "journalctl -u docker -n 50"}, "anaphora_command", "anaphora"),
    ]

    passed = 0
    failures: List[Dict[str, str]] = []
    # Clarification confusion matrix
    tp = fp = fn = tn = 0
    casual_ok = casual_total = 0
    anaphora_ok = anaphora_total = 0

    for prompt, mem, expected, cat in cases:
        dec = analyzer.analyze(prompt, memory=mem, ask_before_ambiguous=True)
        ok = dec.kind == expected
        if ok:
            passed += 1
        else:
            failures.append({"prompt": prompt, "category": cat, "expected": expected, "got": dec.kind})

        if expected == "needs_clarification":
            if dec.kind == "needs_clarification":
                tp += 1
            else:
                fn += 1
        else:
            if dec.kind == "needs_clarification":
                fp += 1
            else:
                tn += 1

        if cat == "casual":
            casual_total += 1
            if ok:
                casual_ok += 1
        elif cat == "anaphora":
            anaphora_total += 1
            if ok:
                anaphora_ok += 1

    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    f1 = (2 * precision * recall) / max(1e-9, precision + recall)
    fpr = fp / max(1, fp + tn)

    return {
        "total_cases": len(cases),
        "passed": passed,
        "accuracy": round(passed / len(cases), 4),
        "clarification_precision": round(precision, 4),
        "clarification_recall": round(recall, 4),
        "clarification_f1": round(f1, 4),
        "false_positive_rate": round(fpr, 4),
        "casual_accuracy": round(casual_ok / max(1, casual_total), 4),
        "anaphora_accuracy": round(anaphora_ok / max(1, anaphora_total), 4),
        "failures": failures,
    }


# ── Suite B: Resilient Agentic Loop Benchmark ────────────────────────────────
def run_agent_loop_benchmark() -> Dict[str, Any]:
    # 1. Tag repair cases
    tag_cases = [
        ("<pkexec>apt update</pkexec>", "<bash>pkexec apt update</bash>"),
        ("<sudo>systemctl restart nginx</sudo>", "<bash>pkexec systemctl restart nginx</bash>"),
        ("<shell>ss -tulnp</shell>", "<bash>ss -tulnp</bash>"),
        ('<bash command="uname -a" />', "<bash>uname -a</bash>"),
        ('<bash cmd="df -h"/>', "<bash>df -h</bash>"),
        ("<run>uptime</run>", "<bash>uptime</bash>"),
    ]
    tag_passed = 0
    tag_failures: List[Dict[str, str]] = []
    for raw, expected in tag_cases:
        fixed, _ = FailureClassifier.normalize_common_tag_mistakes(raw)
        if expected in fixed:
            tag_passed += 1
        else:
            tag_failures.append({"raw": raw, "expected": expected, "got": fixed})

    # 2. Failure classification cases (including transient network & syntax errors)
    classify_cases = [
        (ToolResult(False, "e", "Permission denied (are you root?)", exit_code=1), FailureClass.PERMISSION_DENIED),
        (ToolResult(False, "e", "Unable to acquire the dpkg frontend lock", exit_code=100), FailureClass.LOCK_OR_BUSY),
        (ToolResult(False, "e", "bash: rg: command not found", exit_code=127), FailureClass.COMMAND_NOT_FOUND),
        (ToolResult(False, "e", "No such file or directory", exit_code=2), FailureClass.NOT_FOUND_OR_404),
        (ToolResult(False, "e", "Command timed out after 30s", exit_code=124), FailureClass.TIMEOUT),
        (ToolResult(False, "e", "User denied execution", exit_code=126), FailureClass.USER_DENIED),
        (ToolResult(False, "e", "curl: (6) Could not resolve host: example.invalid", exit_code=6), "NETWORK_TRANSIENT"),
        (ToolResult(False, "e", "Temporary failure in name resolution", exit_code=1), "NETWORK_TRANSIENT"),
        (ToolResult(False, "e", "unrecognized arguments: --bogus-flag", exit_code=2), FailureClass.SYNTAX_OR_USAGE),
        (ToolResult(False, "e", "invalid option -- 'Z'\nTry 'ls --help' for more information.", exit_code=2), FailureClass.SYNTAX_OR_USAGE),
    ]
    cls_passed = 0
    cls_failures: List[Dict[str, str]] = []
    for res, expected_cls in classify_cases:
        got_cls, hint = FailureClassifier.classify(res)
        if got_cls == expected_cls and len(hint) > 10:
            cls_passed += 1
        else:
            cls_failures.append({"output": res.output[:60], "expected": expected_cls, "got": got_cls})

    # 3. End-to-end recovery + rollback loop scenarios
    def _extract(text: str) -> List[Dict[str, Any]]:
        acts: List[Dict[str, Any]] = []
        for m in re.finditer(r"<bash>(.*?)</bash>", text, flags=re.DOTALL | re.IGNORECASE):
            acts.append({"tool": "bash", "command": m.group(1).strip()})
        for m in re.finditer(r'<patch_file\s+path=["\']([^"\']+)["\']>(.*?)</patch_file>', text, flags=re.DOTALL):
            acts.append({"tool": "patch_file", "path": m.group(1), "content": m.group(2)})
        return acts

    async def _run_loop_scenarios() -> Dict[str, Any]:
        scenarios_ok = 0
        scenarios_total = 3
        recovery_steps: List[int] = []

        # Scenario 1: Permission error -> recover via normalized <pkexec> -> verify
        r1 = iter(["<bash>apt update</bash>", "<pkexec>apt update</pkexec>", "<bash>apt-cache stats</bash>", "Done."])
        async def exec1(act: Dict[str, Any]) -> Tuple[str, ToolResult]:
            if act["command"] == "apt update":
                return "bash", ToolResult(False, "apt", "Permission denied", exit_code=100)
            return "bash", ToolResult(True, "apt", "OK", exit_code=0)

        l1 = ResilientAgentLoop(
            query_llm=lambda _m: asyncio.sleep(0, result=next(r1, None)),
            strip_think=lambda s: (s, []),
            extract_actions=_extract,
            execute_action=exec1,
            on_thought=lambda _: None,
            on_token=lambda _: None,
            on_state_change=lambda _: None,
        )
        _, t1 = await l1.run("refresh apt", [{"role": "user", "content": "refresh apt"}])
        if t1.succeeded and t1.recoveries_succeeded >= 1:
            scenarios_ok += 1
            recovery_steps.append(t1.tool_steps_count)

        # Scenario 2: Duplicate failure blocked
        r2 = iter(["<bash>fail_twice</bash>", "<bash>fail_twice</bash>", "Stopped."])
        calls2 = 0
        async def exec2(_act: Dict[str, Any]) -> Tuple[str, ToolResult]:
            nonlocal calls2
            calls2 += 1
            return "bash", ToolResult(False, "e", "command not found", exit_code=127)

        l2 = ResilientAgentLoop(
            query_llm=lambda _m: asyncio.sleep(0, result=next(r2, None)),
            strip_think=lambda s: (s, []),
            extract_actions=_extract,
            execute_action=exec2,
            on_thought=lambda _: None,
            on_token=lambda _: None,
            on_state_change=lambda _: None,
        )
        await l2.run("run fail_twice", [{"role": "user", "content": "run fail_twice"}])
        if calls2 == 1:
            scenarios_ok += 1

        # Scenario 3: Failed mutation triggers auto-rollback
        r3 = iter(['<patch_file path="/tmp/x.conf">a=1</patch_file>', "<bash>check1</bash>", "<bash>check2</bash>"])
        rolled: List[str] = []
        async def exec3(act: Dict[str, Any]) -> Tuple[str, ToolResult]:
            if act["tool"] == "patch_file":
                return "patch_file", ToolResult(True, "p", "Patched [`tx_bench1`]", exit_code=0)
            return "bash", ToolResult(False, "e", "config test failed", exit_code=1)

        l3 = ResilientAgentLoop(
            query_llm=lambda _m: asyncio.sleep(0, result=next(r3, None)),
            strip_think=lambda s: (s, []),
            extract_actions=_extract,
            execute_action=exec3,
            rollback_tx=lambda tx: (rolled.append(tx) or ToolResult(True, "rb", f"Restored {tx}")),
            on_thought=lambda _: None,
            on_token=lambda _: None,
            on_state_change=lambda _: None,
            max_consecutive_failures=2,
            auto_rollback=True,
        )
        _, t3 = await l3.run("patch config", [{"role": "user", "content": "patch config"}])
        if not t3.succeeded and rolled == ["tx_bench1"]:
            scenarios_ok += 1

        return {
            "scenarios_passed": scenarios_ok,
            "scenarios_total": scenarios_total,
            "avg_recovery_steps": round(sum(recovery_steps) / max(1, len(recovery_steps)), 2),
        }

    loop_stats = asyncio.run(_run_loop_scenarios())

    return {
        "tag_repair_passed": tag_passed,
        "tag_repair_total": len(tag_cases),
        "tag_repair_rate": round(tag_passed / len(tag_cases), 4),
        "tag_failures": tag_failures,
        "failure_classify_passed": cls_passed,
        "failure_classify_total": len(classify_cases),
        "failure_classify_rate": round(cls_passed / len(classify_cases), 4),
        "classify_failures": cls_failures,
        **loop_stats,
    }


# ── Suite C: Learning Curve, Distillation & Retrieval Benchmark ──────────────
def run_learning_curve_benchmark() -> Dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        cfg = ConfigManager(config_path=tmp / "settings.json")
        cfg.set_all_permissions(True)
        toolkit = LinuxSystemToolkit(cfg)
        exp_dir = tmp / "experiences"
        reg = ExperienceRegistry(experiences_dir=exp_dir, config=cfg, seed_starters=True)

        # Create realistic sandbox log & workspace files for real command execution
        log_dir = tmp / "logs"
        log_dir.mkdir()
        (log_dir / "app.log").write_text(
            "2026-11-26 INFO startup ok\n2026-11-26 ERROR database timeout on pool-1\n2026-11-26 WARN retry succeeded\n",
            encoding="utf-8",
        )
        (log_dir / "worker.log").write_text(
            "2026-11-26 INFO job #42 done\n2026-11-26 ERROR connection reset by peer\n",
            encoding="utf-8",
        )

        # Realistic sysadmin episodes (mix of multi-step bash & single-recovery & structured-tool episodes)
        episodes: List[Dict[str, Any]] = [
            {
                "id": "ep1_runtime_versions",
                "prompt": "check installed developer toolchains python git and kernel version",
                "commands": ["python3 --version", "git --version", "uname -r"],
                "steps": [
                    {"tool": "bash", "args_summary": "python3 --version", "ok": True},
                    {"tool": "bash", "args_summary": "git --version", "ok": True},
                    {"tool": "bash", "args_summary": "uname -r", "ok": True},
                ],
                "succeeded": True,
                "verified": True,
                "recoveries_succeeded": 0,
            },
            {
                "id": "ep2_log_error_scan",
                "prompt": f"scan application logs in {log_dir} for errors and count failures",
                "commands": [f"grep -rn ERROR {log_dir}", f"wc -l {log_dir}/*.log"],
                "steps": [
                    {"tool": "bash", "args_summary": f"grep -rn ERROR {log_dir}", "ok": True},
                    {"tool": "bash", "args_summary": f"wc -l {log_dir}/*.log", "ok": True},
                ],
                "succeeded": True,
                "verified": True,
                "recoveries_succeeded": 0,
            },
            {
                "id": "ep3_memory_cpu_snapshot",
                "prompt": "inspect host memory free ram and cpu architecture details",
                "commands": ["free -h", "lscpu | head -n 12"],
                "steps": [
                    {"tool": "bash", "args_summary": "free -h", "ok": True},
                    {"tool": "bash", "args_summary": "lscpu | head -n 12", "ok": True},
                ],
                "succeeded": True,
                "verified": True,
                "recoveries_succeeded": 1,
            },
            {
                "id": "ep4_structured_network_audit",
                "prompt": "audit network interfaces and listening tcp sockets",
                "commands": ["ip -brief addr", "ss -tulnp | head -n 15"],
                "steps": [
                    {"tool": "network_audit", "args_summary": "scope=all", "ok": True},
                    {"tool": "bash", "args_summary": "ip -brief addr", "ok": True},
                ],
                "succeeded": True,
                "verified": True,
                "recoveries_succeeded": 0,
            },
            {
                "id": "ep5_duplicate_evolve_runtime",
                "prompt": "check installed developer toolchains python git kernel versions again",
                "commands": ["python3 --version", "git --version", "uname -sr"],
                "steps": [
                    {"tool": "bash", "args_summary": "python3 --version", "ok": True},
                    {"tool": "bash", "args_summary": "git --version", "ok": True},
                    {"tool": "bash", "args_summary": "uname -sr", "ok": True},
                ],
                "succeeded": True,
                "verified": True,
                "recoveries_succeeded": 1,
            },
            {
                "id": "ep6_env_audit",
                "prompt": "check storage block devices and mounted filesystem types",
                "commands": ["lsblk -o NAME,SIZE,TYPE,MOUNTPOINT | head -n 15", "df -hT | head -n 15"],
                "steps": [
                    {"tool": "bash", "args_summary": "lsblk -o NAME,SIZE,TYPE,MOUNTPOINT | head -n 15", "ok": True},
                    {"tool": "bash", "args_summary": "df -hT | head -n 15", "ok": True},
                ],
                "succeeded": True,
                "verified": True,
                "recoveries_succeeded": 0,
            },
        ]

        # Measure COLD execution (running raw multi-step shell commands) and learn from each episode
        distilled_ok = 0
        distilled_slugs: Dict[str, str] = {}
        cold_latencies_ms: List[float] = []
        cold_step_counts: List[int] = []
        curve_snapshots: List[Dict[str, Any]] = []
        evolved_cleanly = False

        for idx, ep in enumerate(episodes, 1):
            t0 = time.monotonic()
            for cmd in ep["commands"]:
                toolkit.run_shell_command(cmd)
            cold_ms = (time.monotonic() - t0) * 1000.0
            cold_latencies_ms.append(cold_ms)
            cold_step_counts.append(len(ep["commands"]))

            before_count = len(reg.list_experiences())
            exp, _msg = reg.learn_from_episode(ep)
            after_count = len(reg.list_experiences())
            if exp is not None:
                distilled_ok += 1
                distilled_slugs[ep["id"]] = exp.slug
                if ep["id"] == "ep5_duplicate_evolve_runtime" and exp.version >= 2 and after_count == before_count:
                    evolved_cleanly = True
                # Execute learned tool once immediately to start maturity tracking
                reg.run_experience(exp.slug, dry_run=False)

            m = reg.learning_metrics()
            curve_snapshots.append({
                "epoch": idx,
                "episode": ep["id"],
                "total_tools": m["total"],
                "total_runs": m["total_runs"],
                "success_rate": m["overall_success_rate"],
                "hardened": m["by_maturity"].get(MATURITY_HARDENED, 0),
                "verified": m["by_maturity"].get(MATURITY_VERIFIED, 0),
            })

        # Warm round: run each learned experience 2 more times -> measure latency & HARDENED promotion
        warm_latencies_ms: List[float] = []
        warm_success = 0
        warm_total = 0
        unique_slugs = sorted(set(distilled_slugs.values()))
        for slug in unique_slugs:
            for _ in range(2):
                t0 = time.monotonic()
                res = reg.run_experience(slug, dry_run=False)
                warm_latencies_ms.append((time.monotonic() - t0) * 1000.0)
                warm_total += 1
                if res.ok:
                    warm_success += 1

        # Retrieval benchmark: natural paraphrased / synonym / typo queries!
        rt_slug = distilled_slugs.get("ep1_runtime_versions", "")
        log_slug = distilled_slugs.get("ep2_log_error_scan", "")
        mem_slug = distilled_slugs.get("ep3_memory_cpu_snapshot", "")
        blk_slug = distilled_slugs.get("ep6_env_audit", "")

        retrieval_queries: List[Tuple[str, str]] = [
            # Exact / near-exact
            ("check listening ports on tcp", "port-socket-inspector"),
            ("check failed systemd services", "systemd-service-doctor"),
            ("audit disk space usage", "disk-space-auditor"),
            # Paraphrased / synonym / natural human queries!
            ("which app is using tcp sockets right now", "port-socket-inspector"),
            ("any crashed daemons or units?", "systemd-service-doctor"),
            ("my drive is almost full, find largest folders", "disk-space-auditor"),
            ("what python and git versions are installed?", rt_slug),
            ("show dev toolchain versions", rt_slug),
            ("search app logs for exceptions and errors", log_slug),
            ("how much ram and cpu cores do i have?", mem_slug),
            ("list mounted partitions and block devices", blk_slug),
            ("find open listening network ports", "port-socket-inspector"),
        ]
        hit1 = 0
        hit3 = 0
        retrieval_misses: List[Dict[str, Any]] = []
        valid_queries = [(q, exp_s) for q, exp_s in retrieval_queries if exp_s]

        for query, expected_slug in valid_queries:
            matches = reg.match_experiences(query, max_matches=3)
            got_slugs = [e.slug for e in matches]
            if got_slugs and got_slugs[0] == expected_slug:
                hit1 += 1
            if expected_slug in got_slugs:
                hit3 += 1
            else:
                retrieval_misses.append({"query": query, "expected": expected_slug, "got": got_slugs})

        final_metrics = reg.learning_metrics()
        hardened_count = sum(1 for s in unique_slugs if (reg.get_experience(s) and reg.get_experience(s).maturity == MATURITY_HARDENED))

        return {
            "episodes_total": len(episodes),
            "episodes_distilled": distilled_ok,
            "distillation_rate": round(distilled_ok / len(episodes), 4),
            "dedup_evolution_ok": evolved_cleanly,
            "unique_learned_tools": len(unique_slugs),
            "hardened_after_warm": hardened_count,
            "hardened_rate": round(hardened_count / max(1, len(unique_slugs)), 4),
            "warm_execution_success_rate": round(warm_success / max(1, warm_total), 4),
            "avg_cold_latency_ms": round(sum(cold_latencies_ms) / max(1, len(cold_latencies_ms)), 2),
            "avg_warm_latency_ms": round(sum(warm_latencies_ms) / max(1, len(warm_latencies_ms)), 2),
            "avg_cold_steps": round(sum(cold_step_counts) / max(1, len(cold_step_counts)), 2),
            "avg_warm_steps": 1.0,
            "retrieval_queries": len(valid_queries),
            "retrieval_hit_at_1": round(hit1 / max(1, len(valid_queries)), 4),
            "retrieval_hit_at_3": round(hit3 / max(1, len(valid_queries)), 4),
            "retrieval_misses": retrieval_misses,
            "final_metrics": final_metrics,
            "curve_snapshots": curve_snapshots,
        }


# ── Suite D: Security & AST Validator Hardening Benchmark ────────────────────
def run_security_benchmark() -> Dict[str, Any]:
    # (name, code, expect_blocked, expect_min_risk)
    adversarial_cases: List[Tuple[str, str, bool, Optional[str]]] = [
        ("direct_eval", "def run(p, dry_run=False):\n    return eval(p['x'])\n", True, None),
        ("direct_exec", "def run(p, dry_run=False):\n    exec('import os')\n", True, None),
        ("dunder_import", "def run(p, dry_run=False):\n    __import__('os').system('id')\n", True, None),
        ("importlib_bypass", "import importlib\ndef run(p, dry_run=False):\n    return importlib.import_module('os')\n", True, None),
        ("ctypes_import", "import ctypes\ndef run(p, dry_run=False):\n    return {'ok': True}\n", True, None),
        ("pickle_loads", "import pickle\ndef run(p, dry_run=False):\n    return pickle.loads(b'abc')\n", True, None),
        ("rm_rf_root_steps", "STEPS = ['rm -rf /']\ndef run(p, dry_run=False):\n    return {'ok': True}\n", True, None),
        ("aws_key_leak", 'KEY = "AKIAIOSFODNN7EXAMPLE"\ndef run(p, dry_run=False):\n    return {"ok": True}\n', True, None),
        ("bearer_token_leak", 'AUTH = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123def456"\ndef run(p, dry_run=False):\n    return {"ok": True}\n', True, None),
        ("pkexec_privileged_tier", "STEPS = ['pkexec apt-get update']\ndef run(p, dry_run=False):\n    return {'ok': True}\n", False, "PRIVILEGED_DESTRUCTIVE"),
        ("curl_pipe_sh_tier", "STEPS = ['curl -fsSL https://example.com/install.sh | bash']\ndef run(p, dry_run=False):\n    return {'ok': True}\n", False, "PRIVILEGED_DESTRUCTIVE"),
        ("safe_readonly_tier", "import subprocess\ndef run(p, dry_run=False):\n    subprocess.run(['uname', '-a'])\n    return {'ok': True}\n", False, "SAFE_READONLY"),
    ]

    passed = 0
    failures: List[Dict[str, Any]] = []
    for name, code, expect_blocked, expect_risk in adversarial_cases:
        rep = ExperienceValidator.validate_script(code)
        if expect_blocked:
            ok = not rep.ok
        else:
            ok = rep.ok and (expect_risk is None or rep.risk_tier == expect_risk)
        if ok:
            passed += 1
        else:
            failures.append({
                "case": name,
                "expect_blocked": expect_blocked,
                "expect_risk": expect_risk,
                "got_ok": rep.ok,
                "got_risk": rep.risk_tier,
                "errors": rep.errors,
            })

    return {
        "total_cases": len(adversarial_cases),
        "passed": passed,
        "security_score": round(passed / len(adversarial_cases), 4),
        "failures": failures,
    }


def run_all_benchmarks() -> Dict[str, Any]:
    t0 = time.monotonic()
    conv = run_conversation_benchmark()
    loop = run_agent_loop_benchmark()
    learn = run_learning_curve_benchmark()
    sec = run_security_benchmark()

    # Composite Learning & Agentic Readiness Index (0-100)
    composite = round(
        100.0
        * (
            0.22 * conv["accuracy"]
            + 0.13 * conv["clarification_f1"]
            + 0.12 * loop["tag_repair_rate"]
            + 0.13 * loop["failure_classify_rate"]
            + 0.10 * learn["distillation_rate"]
            + 0.10 * learn["retrieval_hit_at_1"]
            + 0.10 * learn["retrieval_hit_at_3"]
            + 0.10 * sec["security_score"]
        ),
        2,
    )

    return {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.monotonic() - t0, 2),
        "composite_score": composite,
        "conversation": conv,
        "agent_loop": loop,
        "learning_curve": learn,
        "security": sec,
    }


def main() -> int:
    report = run_all_benchmarks()
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=" * 72)
    print(f"TCHIKO BENCHMARK REPORT  |  Composite Score: {report['composite_score']}/100  ({report['elapsed_sec']}s)")
    print("=" * 72)
    c = report["conversation"]
    print(
        f"[A] Conversation & Clarification : {c['passed']}/{c['total_cases']} ({c['accuracy']*100:.1f}%) "
        f"| Clarify F1={c['clarification_f1']*100:.1f}% (P={c['clarification_precision']*100:.0f}% R={c['clarification_recall']*100:.0f}% FPR={c['false_positive_rate']*100:.1f}%) "
        f"| Casual={c['casual_accuracy']*100:.0f}% | Anaphora={c['anaphora_accuracy']*100:.0f}%"
    )
    loop_r = report["agent_loop"]
    print(
        f"[B] Resilient Agentic Loop       : TagRepair={loop_r['tag_repair_passed']}/{loop_r['tag_repair_total']} ({loop_r['tag_repair_rate']*100:.1f}%) "
        f"| FailClassify={loop_r['failure_classify_passed']}/{loop_r['failure_classify_total']} ({loop_r['failure_classify_rate']*100:.1f}%) "
        f"| LoopScenarios={loop_r['scenarios_passed']}/{loop_r['scenarios_total']}"
    )
    e = report["learning_curve"]
    print(
        f"[C] Learning Curve & Experiences : Distill={e['episodes_distilled']}/{e['episodes_total']} ({e['distillation_rate']*100:.1f}%) "
        f"| DedupEvolve={e['dedup_evolution_ok']} | Hardened={e['hardened_after_warm']}/{e['unique_learned_tools']} "
        f"| Retrieval Hit@1={e['retrieval_hit_at_1']*100:.1f}% Hit@3={e['retrieval_hit_at_3']*100:.1f}% "
        f"| Steps {e['avg_cold_steps']}->{e['avg_warm_steps']} | Latency {e['avg_cold_latency_ms']}ms->{e['avg_warm_latency_ms']}ms"
    )
    s = report["security"]
    print(f"[D] Security & AST Validator     : {s['passed']}/{s['total_cases']} ({s['security_score']*100:.1f}%)")
    print("-" * 72)

    if c["failures"]:
        print("  Weak points [A Conversation]:")
        for f in c["failures"]:
            print(f"    - {f['prompt']!r} ({f['category']}): expected {f['expected']}, got {f['got']}")
    if loop_r["tag_failures"] or loop_r["classify_failures"]:
        print("  Weak points [B Agent Loop]:")
        for f in loop_r["tag_failures"]:
            print(f"    - Tag {f['raw']!r}: expected {f['expected']!r}, got {f['got']!r}")
        for f in loop_r["classify_failures"]:
            print(f"    - Classify {f['output']!r}: expected {f['expected']}, got {f['got']}")
    if e["retrieval_misses"] or not e["dedup_evolution_ok"] or e["episodes_distilled"] < e["episodes_total"]:
        print("  Weak points [C Learning Curve]:")
        if e["episodes_distilled"] < e["episodes_total"]:
            print(f"    - Only {e['episodes_distilled']}/{e['episodes_total']} episodes distilled (check structured-tool episodes!)")
        if not e["dedup_evolution_ok"]:
            print("    - Similar episode did NOT evolve existing experience (created duplicate instead)")
        for m in e["retrieval_misses"]:
            print(f"    - Miss: {m['query']!r} -> expected {m['expected']!r}, got {m['got']}")
    if s["failures"]:
        print("  Weak points [D Security]:")
        for f in s["failures"]:
            print(f"    - {f['case']}: expect_blocked={f['expect_blocked']} risk={f['expect_risk']} -> got ok={f['got_ok']} risk={f['got_risk']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
