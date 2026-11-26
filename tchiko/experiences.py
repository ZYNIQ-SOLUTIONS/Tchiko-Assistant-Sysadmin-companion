"""Hardened Experience Learning Engine & Python Tool Scripts Registry for Tchiko.

An **Experience** is a versioned, AST-validated, self-tested Python 3 tool script
stored under `experiences/<slug>/`:

```text
experiences/
├── index.json
└── <slug>/
    ├── manifest.json     # Schema, triggers, risk_tier, maturity, stats, evolution notes
    ├── tool.py           # Executable Python 3 CLI script (JSON stdout contract)
    ├── versions/         # Archived previous versions (v1.py, v2.py, ...)
    └── history.jsonl     # Append-only execution & recovery history
```

Lifecycle maturity curve:
`DRAFT` -> (AST safety + `--self-test`/`--dry-run`) -> `VERIFIED`
-> (`runs >= 3` and `success_rate >= 80%`) -> `HARDENED`
(or `NEEDS_REPAIR` if `consecutive_failures >= 2`).
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .config_manager import ConfigManager, PROJECT_ROOT
from .system_tools import ToolResult


EXPERIENCES_DIR = PROJECT_ROOT / "experiences"

MATURITY_DRAFT = "DRAFT"
MATURITY_VERIFIED = "VERIFIED"
MATURITY_HARDENED = "HARDENED"
MATURITY_NEEDS_REPAIR = "NEEDS_REPAIR"

VALID_MATURITIES = (MATURITY_DRAFT, MATURITY_VERIFIED, MATURITY_HARDENED, MATURITY_NEEDS_REPAIR)

BANNED_CALL_NAMES = frozenset({"eval", "exec", "compile", "__import__", "import_module"})
BANNED_MODULES = frozenset({"ctypes", "cffi", "importlib", "pickle", "marshal", "shelve"})

SECRET_PATTERNS = (
    (re.compile(r"AIza[0-9A-Za-z_-]{30,}"), "<REDACTED_API_KEY>"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "<REDACTED_AWS_KEY>"),
    (re.compile(r"\bsk-[0-9A-Za-z_-]{20,}\b"), "<REDACTED_SECRET_KEY>"),
    (re.compile(r"\bghp_[0-9A-Za-z]{20,}\b"), "<REDACTED_GH_TOKEN>"),
    (re.compile(r"\bBearer\s+[0-9A-Za-z._-]{16,}\b", re.IGNORECASE), "Bearer <REDACTED_TOKEN>"),
    (re.compile(r"\beyJ[0-9A-Za-z_-]{10,}\.[0-9A-Za-z_-]{10,}\.[0-9A-Za-z_-]{6,}\b"), "<REDACTED_JWT>"),
    (re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----.*?-----END [A-Z ]+ PRIVATE KEY-----", re.DOTALL), "<REDACTED_PRIVATE_KEY>"),
    (re.compile(r"(?i)(password|passwd|api_key|token|secret)\s*[:=]\s*['\"][^'\"]{4,}['\"]"), r"\1='<REDACTED>'"),
)

TRIVIAL_COMMANDS = frozenset({"ls", "pwd", "whoami", "id", "date", "uptime", "clear", "echo"})

STRUCTURED_TOOL_TO_CMD: Dict[str, str] = {
    "network_audit": "ss -tulnp | head -n 30",
    "systemd": "systemctl --failed --no-pager",
    "containers": "docker ps -a --format 'table {{.Names}}\\t{{.Status}}\\t{{.Ports}}'",
    "disk": "df -hT | head -n 25",
    "gpu": "nvidia-smi",
    "git": "git status -sb",
}

DOMAIN_SYNONYMS: Dict[str, Tuple[str, ...]] = {
    "dev": ("developer", "toolchain", "runtime"),
    "developer": ("dev", "toolchain", "runtime"),
    "toolchain": ("dev", "developer", "version", "runtime"),
    "ram": ("memory", "free", "swap"),
    "memory": ("ram", "free", "swap"),
    "drive": ("disk", "storage", "space", "filesystem"),
    "disk": ("drive", "storage", "space", "filesystem", "partition"),
    "storage": ("disk", "drive", "space", "block", "filesystem"),
    "partition": ("mount", "block", "disk", "filesystem", "lsblk"),
    "daemon": ("service", "systemd", "unit"),
    "service": ("daemon", "systemd", "unit"),
    "socket": ("port", "ss"),
    "port": ("socket", "ss"),
    "exception": ("error", "failure", "traceback"),
    "error": ("exception", "failure", "crash"),
}


def _stem_token(tok: str) -> str:
    """Lightweight plural/suffix normalizer for English sysadmin terms."""
    t = tok.lower()
    if len(t) > 5 and t.endswith("ies"):
        return t[:-3] + "y"
    if len(t) > 4 and t.endswith("es") and t[-3] in ("s", "x", "z", "h"):
        return t[:-2]
    if len(t) > 4 and t.endswith("s") and not t.endswith(("ss", "us", "is")):
        return t[:-1]
    return t


def _expand_tokens(text: str) -> Tuple[set[str], set[str]]:
    """Return (stemmed_tokens, synonym_tokens) extracted from natural text."""
    raw = re.findall(r"[a-z0-9]{2,}", (text or "").lower())
    stemmed: set[str] = set()
    syns: set[str] = set()
    for tok in raw:
        if len(tok) < 3 and tok not in ("ip", "df", "du", "ss"):
            continue
        st = _stem_token(tok)
        stemmed.add(tok)
        stemmed.add(st)
        for s in DOMAIN_SYNONYMS.get(st, ()) or DOMAIN_SYNONYMS.get(tok, ()):
            syns.add(s)
    return stemmed, syns


def slugify(text: str) -> str:
    raw = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    raw = re.sub(r"-{2,}", "-", raw)
    return (raw[:42].strip("-") or "custom-experience")


def redact_secrets(text: str) -> str:
    cleaned = text or ""
    for pat, repl in SECRET_PATTERNS:
        cleaned = pat.sub(repl, cleaned)
    return cleaned


@dataclass
class ValidationReport:
    """Result of static AST, security, secret, and risk-tier inspection of an Experience script."""

    ok: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    risk_tier: str = "SAFE_READONLY"
    detected_commands: List[str] = field(default_factory=list)


@dataclass
class Experience:
    """Metadata and runtime stats for a single learned Python Experience tool."""

    slug: str
    title: str
    description: str
    category: str = "system"
    triggers: List[str] = field(default_factory=list)
    parameters: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    maturity: str = MATURITY_DRAFT
    risk_tier: str = "SAFE_READONLY"
    version: int = 1
    enabled: bool = True
    source_prompt: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    runs: int = 0
    successes: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    recoveries: int = 0
    avg_duration_ms: int = 0
    last_run_at: float = 0.0
    last_error: str = ""
    evolution_notes: List[Dict[str, Any]] = field(default_factory=list)
    script_path: str = ""

    @property
    def success_rate(self) -> float:
        if self.runs <= 0:
            return 1.0 if self.maturity in (MATURITY_VERIFIED, MATURITY_HARDENED) else 0.0
        return round(self.successes / max(1, self.runs), 4)

    def to_manifest_dict(self) -> Dict[str, Any]:
        return {
            "slug": self.slug,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "triggers": list(self.triggers),
            "parameters": dict(self.parameters),
            "maturity": self.maturity,
            "risk_tier": self.risk_tier,
            "version": self.version,
            "enabled": self.enabled,
            "source_prompt": self.source_prompt,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "stats": {
                "runs": self.runs,
                "successes": self.successes,
                "failures": self.failures,
                "consecutive_failures": self.consecutive_failures,
                "recoveries": self.recoveries,
                "avg_duration_ms": self.avg_duration_ms,
                "last_run_at": self.last_run_at,
                "last_error": self.last_error,
            },
            "evolution_notes": list(self.evolution_notes[-20:]),
        }

    def to_public_dict(self, include_code: bool = False) -> Dict[str, Any]:
        d = self.to_manifest_dict()
        d["success_rate"] = self.success_rate
        d["script_path"] = self.script_path
        if include_code and self.script_path and Path(self.script_path).exists():
            try:
                d["code"] = Path(self.script_path).read_text(encoding="utf-8")
            except Exception:
                d["code"] = ""
        return d

    @classmethod
    def from_manifest_dict(cls, data: Dict[str, Any], script_path: str = "") -> "Experience":
        stats = data.get("stats") if isinstance(data.get("stats"), dict) else {}
        return cls(
            slug=str(data.get("slug") or "unknown"),
            title=str(data.get("title") or data.get("slug") or "Experience"),
            description=str(data.get("description") or ""),
            category=str(data.get("category") or "system"),
            triggers=[str(t).lower() for t in (data.get("triggers") or []) if str(t).strip()],
            parameters=dict(data.get("parameters") or {}),
            maturity=str(data.get("maturity") or MATURITY_DRAFT),
            risk_tier=str(data.get("risk_tier") or "SAFE_READONLY"),
            version=max(1, int(data.get("version") or 1)),
            enabled=bool(data.get("enabled", True)),
            source_prompt=str(data.get("source_prompt") or ""),
            created_at=float(data.get("created_at") or time.time()),
            updated_at=float(data.get("updated_at") or time.time()),
            runs=int(stats.get("runs") or 0),
            successes=int(stats.get("successes") or 0),
            failures=int(stats.get("failures") or 0),
            consecutive_failures=int(stats.get("consecutive_failures") or 0),
            recoveries=int(stats.get("recoveries") or 0),
            avg_duration_ms=int(stats.get("avg_duration_ms") or 0),
            last_run_at=float(stats.get("last_run_at") or 0.0),
            last_error=str(stats.get("last_error") or ""),
            evolution_notes=list(data.get("evolution_notes") or []),
            script_path=script_path,
        )


class ExperienceValidator:
    """AST safety scanner, risk classifier, and subprocess dry-run verifier for `tool.py` scripts."""

    @staticmethod
    def validate_script(code: str) -> ValidationReport:
        errors: List[str] = []
        warnings: List[str] = []
        detected_cmds: List[str] = []

        if not code or not code.strip():
            return ValidationReport(ok=False, errors=["Script code is empty."])

        # 1. Secret leak scan
        for pat, _ in SECRET_PATTERNS:
            if pat.search(code):
                errors.append("Script appears to contain a hardcoded secret, API key, or private key.")
                break

        # 2. Syntax & AST inspection
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return ValidationReport(ok=False, errors=[f"Python syntax error on line {exc.lineno}: {exc.msg}"])

        has_run_fn = False
        has_main_guard = False
        risk_rank = {"SAFE_READONLY": 0, "MUTATING_LOCAL": 1, "PRIVILEGED_DESTRUCTIVE": 2}
        highest_risk = "SAFE_READONLY"

        def _bump_risk(tier: str) -> None:
            nonlocal highest_risk
            if risk_rank.get(tier, 0) > risk_rank.get(highest_risk, 0):
                highest_risk = tier

        def _inspect_cmd_string(cmd_str: str) -> None:
            detected_cmds.append(cmd_str)
            if re.search(r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*\s+/(?:\s|$|\*)", cmd_str):
                errors.append("Refusing catastrophic root deletion command (`rm -rf /`).")
            tier, _ = ConfigManager.classify_command(cmd_str)
            _bump_risk(tier)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top_mod = alias.name.split(".")[0]
                    if top_mod in BANNED_MODULES:
                        errors.append(f"Disallowed module import `{top_mod}` detected.")
            elif isinstance(node, ast.ImportFrom):
                top_mod = (node.module or "").split(".")[0]
                if top_mod in BANNED_MODULES:
                    errors.append(f"Disallowed module import `{top_mod}` detected.")

            if isinstance(node, ast.FunctionDef) and node.name == "run":
                has_run_fn = True
            if isinstance(node, ast.If):
                # Detect `if __name__ == "__main__":`
                test = node.test
                if isinstance(test, ast.Compare) and isinstance(test.left, ast.Name) and test.left.id == "__name__":
                    has_main_guard = True

            # Inspect command step arrays (e.g. `STEPS: List[str] = ["pkexec apt-get update", ...]`)
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                val = node.value
                targets = [node.target] if isinstance(node, ast.AnnAssign) else list(node.targets)
                is_steps_var = any(
                    isinstance(t, ast.Name) and t.id.upper() in ("STEPS", "COMMANDS", "CMDS")
                    for t in targets
                )
                if is_steps_var and isinstance(val, (ast.List, ast.Tuple)):
                    for elt in val.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str) and elt.value.strip():
                            _inspect_cmd_string(elt.value.strip())

            if isinstance(node, ast.Call):
                fn_name = ""
                if isinstance(node.func, ast.Name):
                    fn_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    fn_name = node.func.attr

                if fn_name in BANNED_CALL_NAMES:
                    errors.append(f"Disallowed dynamic execution call `{fn_name}()` detected.")

                # Check subprocess / os.system commands for risk classification
                if fn_name in ("run", "Popen", "check_output", "check_call", "call", "system"):
                    is_subproc = isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id in ("subprocess", "os")
                    if is_subproc and node.args:
                        cmd_str = ExperienceValidator._extract_cmd_literal(node.args[0])
                        if cmd_str:
                            _inspect_cmd_string(cmd_str)
                        else:
                            # Dynamic command execution defaults at least to MUTATING_LOCAL
                            _bump_risk("MUTATING_LOCAL")

                # Detect file writes via open(..., "w"/"a") or Path.write_text/unlink
                if fn_name == "open" and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                    if any(m in node.args[1].value for m in ("w", "a", "x", "+")):
                        _bump_risk("MUTATING_LOCAL")
                if fn_name in ("write_text", "write_bytes", "unlink", "rmdir", "rmtree", "chmod", "chown"):
                    _bump_risk("MUTATING_LOCAL")

        if not has_run_fn and not has_main_guard:
            warnings.append("Script has neither `def run(params, dry_run)` nor `if __name__ == '__main__'` entrypoint.")

        return ValidationReport(
            ok=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            risk_tier=highest_risk,
            detected_commands=detected_cmds,
        )

    @staticmethod
    def _extract_cmd_literal(arg_node: ast.AST) -> str:
        if isinstance(arg_node, ast.Constant) and isinstance(arg_node.value, str):
            return arg_node.value
        if isinstance(arg_node, (ast.List, ast.Tuple)):
            parts: List[str] = []
            for elt in arg_node.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    parts.append(elt.value)
            return " ".join(parts)
        return ""

    @staticmethod
    def run_self_test(script_path: Path, timeout: int = 12) -> Tuple[bool, str]:
        """Run `python3 tool.py --self-test` and verify exit=0 + valid JSON stdout contract."""
        if not script_path.exists():
            return False, f"Script not found: {script_path}"
        try:
            proc = subprocess.run(
                [sys.executable, str(script_path), "--self-test"],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return False, f"Self-test timed out after {timeout}s."
        except Exception as exc:
            return False, f"Failed to execute self-test: {exc}"

        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()
        if proc.returncode != 0:
            return False, f"Self-test exited with code {proc.returncode}: {(stderr or stdout)[:400]}"

        parsed = _parse_last_json_object(stdout)
        if parsed is None or "ok" not in parsed:
            return False, f"Self-test output did not conform to JSON `{{'ok': bool, 'summary': str}}` contract: {stdout[:300]}"
        if not bool(parsed.get("ok")):
            return False, f"Self-test reported ok=False: {parsed.get('summary') or stdout[:300]}"
        return True, str(parsed.get("summary") or "Self-test passed")


def _parse_last_json_object(text: str) -> Optional[Dict[str, Any]]:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    for line in reversed(raw.splitlines()):
        ln = line.strip()
        if ln.startswith("{") and ln.endswith("}"):
            try:
                obj = json.loads(ln)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                continue
    return None


class ExperienceRegistry:
    """Manages on-disk Python Experience scripts, validation, execution, learning, and metrics."""

    def __init__(
        self,
        experiences_dir: Path = EXPERIENCES_DIR,
        config: Optional[ConfigManager] = None,
        seed_starters: bool = True,
    ) -> None:
        self.experiences_dir = Path(experiences_dir)
        self.config = config
        self._listeners: List[Callable[[str, Optional[Experience]], None]] = []
        self.experiences_dir.mkdir(parents=True, exist_ok=True)
        if seed_starters:
            self.ensure_starter_experiences()

    def subscribe(self, callback: Callable[[str, Optional[Experience]], None]) -> None:
        if callback not in self._listeners:
            self._listeners.append(callback)

    def _notify(self, event: str, exp: Optional[Experience] = None) -> None:
        for cb in list(self._listeners):
            try:
                cb(event, exp)
            except Exception:
                pass

    def _exp_dir(self, slug: str) -> Path:
        return self.experiences_dir / slugify(slug)

    def _write_index(self) -> None:
        exps = self.list_experiences()
        index = {
            "updated_at": time.time(),
            "count": len(exps),
            "items": [
                {
                    "slug": e.slug,
                    "title": e.title,
                    "category": e.category,
                    "maturity": e.maturity,
                    "risk_tier": e.risk_tier,
                    "version": e.version,
                    "enabled": e.enabled,
                    "runs": e.runs,
                    "success_rate": e.success_rate,
                }
                for e in exps
            ],
        }
        try:
            (self.experiences_dir / "index.json").write_text(
                json.dumps(index, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except Exception:
            pass

    def list_experiences(self) -> List[Experience]:
        if not self.experiences_dir.exists():
            return []
        items: List[Experience] = []
        for entry in sorted(self.experiences_dir.iterdir()):
            if not entry.is_dir():
                continue
            manifest_path = entry / "manifest.json"
            tool_path = entry / "tool.py"
            if not manifest_path.exists() or not tool_path.exists():
                continue
            try:
                raw = json.loads(manifest_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    items.append(Experience.from_manifest_dict(raw, script_path=str(tool_path)))
            except Exception:
                continue
        order = {MATURITY_HARDENED: 0, MATURITY_VERIFIED: 1, MATURITY_DRAFT: 2, MATURITY_NEEDS_REPAIR: 3}
        items.sort(key=lambda e: (order.get(e.maturity, 9), -e.runs, e.slug))
        return items

    def get_experience(self, slug: str) -> Optional[Experience]:
        target = slugify(slug)
        for exp in self.list_experiences():
            if exp.slug == target or exp.slug == slug.strip().lower():
                return exp
        return None

    def get_script_source(self, slug: str) -> str:
        """Read the Python source code of an Experience's `tool.py` script."""
        tool_path = self._exp_dir(slug) / "tool.py"
        if not tool_path.exists():
            return ""
        try:
            return tool_path.read_text(encoding="utf-8")
        except Exception:
            return ""

    def get_history(self, slug: str, limit: int = 30) -> List[Dict[str, Any]]:
        hist_path = self._exp_dir(slug) / "history.jsonl"
        if not hist_path.exists():
            return []
        rows: List[Dict[str, Any]] = []
        try:
            for line in hist_path.read_text(encoding="utf-8").splitlines()[-limit:]:
                if line.strip():
                    rows.append(json.loads(line))
        except Exception:
            pass
        return rows

    def get_versions(self, slug: str) -> List[int]:
        vdir = self._exp_dir(slug) / "versions"
        if not vdir.exists():
            return []
        nums: List[int] = []
        for f in vdir.glob("v*.py"):
            m = re.fullmatch(r"v(\d+)\.py", f.name)
            if m:
                nums.append(int(m.group(1)))
        return sorted(nums)

    def save_experience(
        self,
        *,
        slug: str,
        title: str,
        description: str,
        code: str,
        category: str = "system",
        triggers: Optional[List[str]] = None,
        parameters: Optional[Dict[str, Dict[str, Any]]] = None,
        source_prompt: str = "",
        evolution_note: str = "",
        auto_promote: Optional[bool] = None,
    ) -> Tuple[Optional[Experience], ValidationReport]:
        """Validate, dry-run test, version-archive, and persist an Experience script."""
        clean_slug = slugify(slug)
        clean_code = redact_secrets(code)
        report = ExperienceValidator.validate_script(clean_code)
        if not report.ok:
            return None, report

        exp_dir = self._exp_dir(clean_slug)
        exp_dir.mkdir(parents=True, exist_ok=True)
        tool_path = exp_dir / "tool.py"
        manifest_path = exp_dir / "manifest.json"
        existing = self.get_experience(clean_slug)

        # Archive prior version if updating
        now = time.time()
        if existing is not None and tool_path.exists():
            versions_dir = exp_dir / "versions"
            versions_dir.mkdir(exist_ok=True)
            archived = versions_dir / f"v{existing.version}.py"
            if not archived.exists():
                shutil.copy2(tool_path, archived)
            version = existing.version + 1
            created_at = existing.created_at
            notes = list(existing.evolution_notes)
            notes.append({
                "version": version,
                "ts": now,
                "note": evolution_note or f"Refined and upgraded from v{existing.version}",
            })
        else:
            version = 1
            created_at = now
            notes = [{
                "version": 1,
                "ts": now,
                "note": evolution_note or "Initial experience synthesized",
            }]

        # Write script to temp path first, run self-test, then atomically install
        tmp_tool = exp_dir / ".tool_candidate.py"
        tmp_tool.write_text(clean_code, encoding="utf-8")
        self_test_ok, self_test_msg = ExperienceValidator.run_self_test(tmp_tool)
        if not self_test_ok:
            report.warnings.append(f"Self-test did not pass ({self_test_msg}); saved as DRAFT.")
        os.replace(tmp_tool, tool_path)
        try:
            os.chmod(tool_path, 0o755)
        except OSError:
            pass

        if auto_promote is None:
            auto_promote = True
            if self.config is not None:
                auto_promote = bool(self.config.data.get("learning", {}).get("auto_promote_verified", True))

        # Determine maturity
        if self_test_ok and auto_promote and report.risk_tier != "PRIVILEGED_DESTRUCTIVE":
            maturity = MATURITY_HARDENED if (existing and existing.maturity == MATURITY_HARDENED and existing.consecutive_failures == 0) else MATURITY_VERIFIED
        else:
            maturity = MATURITY_DRAFT

        trig_list = [t.strip().lower() for t in (triggers or []) if t.strip()]
        if not trig_list:
            trig_list = [tok for tok in re.split(r"[-_\s]+", clean_slug) if len(tok) > 2]

        exp = Experience(
            slug=clean_slug,
            title=title.strip() or clean_slug.replace("-", " ").title(),
            description=description.strip() or f"Reusable Python tool for {clean_slug}",
            category=category or "system",
            triggers=trig_list,
            parameters=parameters or {},
            maturity=maturity,
            risk_tier=report.risk_tier,
            version=version,
            enabled=existing.enabled if existing else True,
            source_prompt=source_prompt or (existing.source_prompt if existing else ""),
            created_at=created_at,
            updated_at=now,
            runs=existing.runs if existing else 0,
            successes=existing.successes if existing else 0,
            failures=existing.failures if existing else 0,
            consecutive_failures=0 if self_test_ok else (existing.consecutive_failures if existing else 0),
            recoveries=existing.recoveries if existing else 0,
            avg_duration_ms=existing.avg_duration_ms if existing else 0,
            last_run_at=existing.last_run_at if existing else 0.0,
            last_error="" if self_test_ok else self_test_msg,
            evolution_notes=notes,
            script_path=str(tool_path),
        )
        manifest_path.write_text(json.dumps(exp.to_manifest_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        self._write_index()
        self._notify("evolved" if existing else "learned", exp)
        return exp, report

    def approve_experience(self, slug: str) -> Optional[Experience]:
        """Promote a DRAFT experience to VERIFIED after verifying syntax + self-test."""
        exp = self.get_experience(slug)
        if exp is None:
            return None
        tool_path = Path(exp.script_path)
        ok, msg = ExperienceValidator.run_self_test(tool_path)
        exp.maturity = MATURITY_VERIFIED if ok else MATURITY_DRAFT
        exp.last_error = "" if ok else msg
        exp.updated_at = time.time()
        self._persist_manifest(exp)
        self._notify("updated", exp)
        return exp

    def set_enabled(self, slug: str, enabled: bool) -> Optional[Experience]:
        exp = self.get_experience(slug)
        if exp is None:
            return None
        exp.enabled = bool(enabled)
        exp.updated_at = time.time()
        self._persist_manifest(exp)
        self._notify("updated", exp)
        return exp

    def rollback_version(self, slug: str) -> Tuple[bool, str]:
        """Restore the most recent archived version of an Experience script."""
        exp = self.get_experience(slug)
        if exp is None:
            return False, f"Experience `{slug}` not found."
        versions = self.get_versions(exp.slug)
        if not versions:
            return False, f"No earlier archived version exists for `{exp.slug}`."
        prev_v = versions[-1]
        exp_dir = self._exp_dir(exp.slug)
        src = exp_dir / "versions" / f"v{prev_v}.py"
        dst = exp_dir / "tool.py"
        shutil.copy2(src, dst)
        exp.version = prev_v
        exp.updated_at = time.time()
        exp.evolution_notes.append({"version": prev_v, "ts": exp.updated_at, "note": f"Rolled back to v{prev_v}"})
        self._persist_manifest(exp)
        self._notify("updated", exp)
        return True, f"Rolled back `{exp.slug}` to v{prev_v}."

    def delete_experience(self, slug: str) -> bool:
        exp_dir = self._exp_dir(slug)
        if not exp_dir.exists():
            return False
        shutil.rmtree(exp_dir, ignore_errors=True)
        self._write_index()
        self._notify("deleted", None)
        return True

    def _persist_manifest(self, exp: Experience) -> None:
        manifest_path = self._exp_dir(exp.slug) / "manifest.json"
        manifest_path.write_text(
            json.dumps(exp.to_manifest_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        self._write_index()

    def _append_history(self, slug: str, entry: Dict[str, Any]) -> None:
        hist_path = self._exp_dir(slug) / "history.jsonl"
        try:
            with open(hist_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def match_experiences(self, prompt: str, max_matches: int = 3, include_drafts: bool = False) -> List[Experience]:
        """Relevance-first hybrid slug/title + trigger + stemmed token + capped-synonym scoring."""
        lower = (prompt or "").lower()
        prompt_tokens, prompt_syns = _expand_tokens(lower)
        if not prompt_tokens:
            return []

        maturity_bonus = {
            MATURITY_HARDENED: 0.45,
            MATURITY_VERIFIED: 0.25,
            MATURITY_DRAFT: 0.0,
            MATURITY_NEEDS_REPAIR: -0.25,
        }

        scored: List[Tuple[float, Experience]] = []
        for exp in self.list_experiences():
            if not exp.enabled:
                continue
            if not include_drafts and exp.maturity == MATURITY_DRAFT:
                continue

            exact_score = 0.0
            syn_score = 0.0
            for trig in exp.triggers:
                if not trig:
                    continue
                trig_stem = _stem_token(trig)
                if trig in lower or trig_stem in prompt_tokens:
                    exact_score += 3.2 if " " in trig else 2.2
                elif trig_stem in prompt_syns:
                    syn_score += 0.9

            title_tokens, _ = _expand_tokens(f"{exp.slug.replace('-', ' ')} {exp.title}")
            title_hits = prompt_tokens & title_tokens
            exact_score += len(title_hits) * 1.35

            desc_blob = f"{exp.slug.replace('-', ' ')} {exp.title} {exp.description} {' '.join(exp.triggers)}"
            desc_tokens, desc_syns = _expand_tokens(desc_blob)
            exact_overlap = prompt_tokens & desc_tokens
            syn_overlap = ((prompt_syns & desc_tokens) | (prompt_tokens & desc_syns)) - exact_overlap
            exact_score += len(exact_overlap) * 0.85
            syn_score += len(syn_overlap) * 0.45

            relevance = exact_score + min(2.2, syn_score)
            if relevance >= 1.8:
                final_score = relevance + maturity_bonus.get(exp.maturity, 0.0) + exp.success_rate * 0.35
                scored.append((final_score, exp))

        scored.sort(key=lambda item: (-item[0], item[1].slug))
        return [e for _, e in scored[:max_matches]]

    def run_experience(
        self,
        slug: str,
        params: Optional[Dict[str, Any]] = None,
        dry_run: bool = False,
        timeout: int = 60,
    ) -> ToolResult:
        """Execute a learned Python Experience script, update stats & maturity curve, and log history."""
        exp = self.get_experience(slug)
        if exp is None:
            return ToolResult(ok=False, title="Experience Not Found", output=f"No experience named `{slug}`.", exit_code=127)
        if not exp.enabled and not dry_run:
            return ToolResult(ok=False, title="Experience Disabled", output=f"Experience `{exp.slug}` is currently disabled.", exit_code=126)

        tool_path = Path(exp.script_path)
        if not tool_path.exists():
            return ToolResult(ok=False, title="Script Missing", output=f"Script missing: {tool_path}", exit_code=127)

        cmd = [sys.executable, "-S", str(tool_path), "--params", json.dumps(params or {})]
        if dry_run:
            cmd.append("--dry-run")

        t0 = time.monotonic()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            stdout = (proc.stdout or "").strip()
            stderr = (proc.stderr or "").strip()
            parsed = _parse_last_json_object(stdout)
            if parsed is not None:
                ok = bool(parsed.get("ok", proc.returncode == 0)) and proc.returncode == 0
                summary = str(parsed.get("summary") or f"Experience `{exp.slug}` finished")
                details = str(parsed.get("details") or "")
                output = f"{summary}\n\n{details}".strip() if details else summary
            else:
                ok = proc.returncode == 0
                output = stdout or stderr or f"(Exited with code {proc.returncode})"
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            ok = False
            output = f"Experience `{exp.slug}` timed out after {timeout}s."
            exit_code = 124
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            ok = False
            output = f"Execution error: {exc}"
            exit_code = 1

        # Update run stats & maturity progression (skip mutating run stats for dry-run tests)
        if not dry_run:
            exp.runs += 1
            if ok:
                exp.successes += 1
                exp.consecutive_failures = 0
                exp.last_error = ""
                if exp.runs >= 3 and exp.success_rate >= 0.80:
                    exp.maturity = MATURITY_HARDENED
                elif exp.maturity == MATURITY_NEEDS_REPAIR:
                    exp.maturity = MATURITY_VERIFIED
            else:
                exp.failures += 1
                exp.consecutive_failures += 1
                exp.last_error = output[:300]
                if exp.consecutive_failures >= 2:
                    exp.maturity = MATURITY_NEEDS_REPAIR

            exp.avg_duration_ms = (
                elapsed_ms if exp.runs == 1 else int((exp.avg_duration_ms * (exp.runs - 1) + elapsed_ms) / exp.runs)
            )
            exp.last_run_at = time.time()
            exp.updated_at = exp.last_run_at
            self._persist_manifest(exp)
            self._append_history(
                exp.slug,
                {
                    "ts": exp.last_run_at,
                    "version": exp.version,
                    "ok": ok,
                    "exit_code": exit_code,
                    "duration_ms": elapsed_ms,
                    "params": params or {},
                    "summary": output[:220],
                },
            )
            self._notify("executed", exp)

        return ToolResult(
            ok=ok,
            title=f"Experience: {exp.slug} v{exp.version}" + (" (dry-run)" if dry_run else ""),
            output=output,
            command=f"experience:{exp.slug}",
            exit_code=exit_code,
            duration_ms=elapsed_ms,
        )

    def learn_from_episode(
        self,
        episode: Dict[str, Any],
        custom_slug: str = "",
        force: bool = False,
    ) -> Tuple[Optional[Experience], str]:
        """Distill a verified multi-step execution trace into a reusable Python Experience script."""
        prompt = str(episode.get("prompt") or "").strip()
        steps = list(episode.get("steps") or [])
        succeeded = bool(episode.get("succeeded", False))
        verified = bool(episode.get("verified", False))
        recoveries = int(episode.get("recoveries_succeeded") or 0)

        # Collect successful shell and structured sysadmin tool commands from the trace
        actionable_cmds: List[str] = []
        for st in steps:
            if not st.get("ok"):
                continue
            tool = str(st.get("tool") or "").lower()
            args_s = str(st.get("args_summary") or "").strip()
            if tool == "bash" and args_s:
                head = args_s.split()[0]
                if head not in TRIVIAL_COMMANDS and args_s not in actionable_cmds:
                    actionable_cmds.append(args_s)
            elif tool in STRUCTURED_TOOL_TO_CMD:
                mapped = STRUCTURED_TOOL_TO_CMD[tool]
                if mapped not in actionable_cmds:
                    actionable_cmds.append(mapped)

        if not force:
            if not succeeded:
                return None, "Episode did not succeed; skipping learning."
            if not verified and recoveries == 0:
                return None, "Episode was not verified; skipping learning."
            if len(actionable_cmds) < 2 and recoveries == 0:
                return None, "Episode has fewer than 2 non-trivial steps; skipping learning."

        if not actionable_cmds:
            return None, "No reusable command steps found in the last episode."

        slug = slugify(custom_slug) if custom_slug else self._derive_slug(prompt)
        category = self._infer_category(prompt, actionable_cmds)
        triggers = self._derive_triggers(prompt, slug, actionable_cmds)
        title = slug.replace("-", " ").title()
        description = f"Learned from: {prompt[:110]}" if prompt else f"Automated Python experience for {title}"

        # Check if a closely matching existing experience should be evolved instead of duplicated
        existing = self.get_experience(slug)
        if existing is None and not custom_slug:
            matches = self.match_experiences(prompt, max_matches=1, include_drafts=True)
            if matches and set(matches[0].triggers) & set(triggers):
                overlap_ratio = len(set(matches[0].triggers) & set(triggers)) / max(1, len(set(triggers)))
                if overlap_ratio >= 0.75:
                    existing = matches[0]
                    slug = existing.slug

        script_code = self._synthesize_python_script(
            slug=slug,
            title=title,
            description=description,
            commands=actionable_cmds,
            source_prompt=prompt,
        )
        note = (
            f"Auto-evolved after solving with {recoveries} recovery step(s)"
            if existing and recoveries > 0
            else ("Auto-refined from verified execution" if existing else "Synthesized from verified multi-step episode")
        )
        exp, report = self.save_experience(
            slug=slug,
            title=existing.title if existing else title,
            description=existing.description if existing else description,
            code=script_code,
            category=category,
            triggers=sorted(set((existing.triggers if existing else []) + triggers))[:8],
            parameters={"cwd": {"type": "string", "description": "Working directory", "default": "~"}},
            source_prompt=prompt,
            evolution_note=note,
        )
        if exp is None:
            return None, "Validation rejected script: " + "; ".join(report.errors)

        if recoveries > 0:
            exp.recoveries += recoveries
            self._persist_manifest(exp)
        return exp, f"Saved experience `{exp.slug}` v{exp.version} ({exp.maturity})"

    @staticmethod
    def _derive_slug(prompt: str) -> str:
        stop = {
            "the", "and", "for", "with", "this", "that", "from", "into", "please", "tchiko",
            "can", "you", "help", "check", "make", "need", "want", "trying", "having", "about",
        }
        words = [w for w in re.findall(r"[a-z0-9]+", (prompt or "").lower()) if len(w) > 2 and w not in stop]
        return slugify("-".join(words[:4]) or "learned-task")

    @staticmethod
    def _infer_category(prompt: str, cmds: List[str]) -> str:
        blob = (prompt + " " + " ".join(cmds)).lower()
        if any(k in blob for k in ("docker", "podman", "container")):
            return "containers"
        if any(k in blob for k in ("port", "ss ", "lsof", "ufw", "tailscale", "ssh", "tls", "dns", "curl", "network")):
            return "networking"
        if any(k in blob for k in ("systemctl", "journalctl", "service", "daemon", "sunshine")):
            return "services"
        if any(k in blob for k in ("apt", "dpkg", "snap", "flatpak", "pip", "install", "upgrade", ".deb")):
            return "packages"
        if any(k in blob for k in ("git", "folder", "file", "find ", "grep", "chmod")):
            return "files"
        return "system"

    @staticmethod
    def _derive_triggers(prompt: str, slug: str, cmds: List[str]) -> List[str]:
        stop = {
            "the", "and", "for", "with", "this", "that", "from", "into", "please",
            "tchiko", "check", "run", "fix", "error", "issue", "help", "all",
        }
        tokens = re.findall(r"[a-z0-9_-]{3,}", (prompt + " " + slug).lower())
        out: List[str] = []
        for tok in tokens:
            if tok not in stop and tok not in out and not tok.isdigit():
                out.append(tok)
            if len(out) >= 6:
                break
        return out or [slug]

    @staticmethod
    def _synthesize_python_script(
        *,
        slug: str,
        title: str,
        description: str,
        commands: List[str],
        source_prompt: str,
    ) -> str:
        safe_cmds = [redact_secrets(c) for c in commands[:8]]
        cmds_json = json.dumps(safe_cmds, indent=4)
        desc_safe = redact_secrets(description).replace('"""', "'''")
        prompt_safe = redact_secrets(source_prompt).replace('"""', "'''")
        return f'''#!/usr/bin/env python3
"""Tchiko Experience Tool: {title} ({slug})

{desc_safe}
Origin: {prompt_safe[:140]}
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

STEPS: List[str] = {cmds_json}
_SHELL_META = ("|", ">", "<", "&&", "||", ";", "$", "*", "?", "~", "`")


def _exec_step(cmd: str, cwd: str) -> subprocess.CompletedProcess[str]:
    if not any(m in cmd for m in _SHELL_META):
        try:
            argv = shlex.split(cmd)
            if argv:
                return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=120)
        except Exception:
            pass
    return subprocess.run(["/bin/bash", "-c", cmd], cwd=cwd, capture_output=True, text=True, timeout=120)


def run(params: Dict[str, Any], dry_run: bool = False) -> Dict[str, Any]:
    cwd = os.path.expanduser(str(params.get("cwd") or "~"))
    if not os.path.isdir(cwd):
        cwd = str(Path.home())

    if dry_run:
        return {{
            "ok": True,
            "summary": f"Dry-run OK: {{len(STEPS)}} step(s) validated for {slug}.",
            "details": "\\n".join(f"{{i + 1}}. {{cmd}}" for i, cmd in enumerate(STEPS)),
        }}

    outputs: List[str] = []
    for idx, cmd in enumerate(STEPS, 1):
        proc = _exec_step(cmd, cwd)
        snippet = ((proc.stdout or "") + ("\\n" + proc.stderr if proc.stderr else "")).strip()
        outputs.append(f"[Step {{idx}}/{{len(STEPS)}}] $ {{cmd}} (exit={{proc.returncode}})\\n{{snippet[:800]}}")
        if proc.returncode != 0:
            return {{
                "ok": False,
                "summary": f"Step {{idx}} failed with exit code {{proc.returncode}}",
                "details": "\\n\\n".join(outputs),
            }}

    return {{
        "ok": True,
        "summary": f"Completed {slug} ({{len(STEPS)}} step(s) verified).",
        "details": "\\n\\n".join(outputs),
    }}


def main() -> int:
    parser = argparse.ArgumentParser(description="{title}")
    parser.add_argument("--params", default="{{}}", help="JSON parameters")
    parser.add_argument("--dry-run", action="store_true", help="Validate without mutating host")
    parser.add_argument("--self-test", action="store_true", help="Run built-in smoke check")
    args = parser.parse_args()

    try:
        params = json.loads(args.params) if args.params else {{}}
        if not isinstance(params, dict):
            params = {{}}
    except Exception:
        params = {{}}

    result = run(params, dry_run=(args.dry_run or args.self_test))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
'''

    def learning_metrics(self) -> Dict[str, Any]:
        """Compute aggregate learning-curve KPIs & time-series points for the visual UI."""
        exps = self.list_experiences()
        by_maturity = {m: 0 for m in VALID_MATURITIES}
        by_category: Dict[str, int] = {}
        total_runs = 0
        total_successes = 0
        total_recoveries = 0
        all_events: List[Tuple[float, str, bool]] = []

        for exp in exps:
            by_maturity[exp.maturity] = by_maturity.get(exp.maturity, 0) + 1
            by_category[exp.category] = by_category.get(exp.category, 0) + 1
            total_runs += exp.runs
            total_successes += exp.successes
            total_recoveries += exp.recoveries
            all_events.append((exp.created_at, "learned", True))
            for h in self.get_history(exp.slug, limit=50):
                all_events.append((float(h.get("ts") or exp.updated_at), "run", bool(h.get("ok"))))

        all_events.sort(key=lambda item: item[0])
        curve_points: List[Dict[str, Any]] = []
        cum_learned = 0
        cum_runs = 0
        cum_ok = 0

        for ts, kind, ok in all_events[-24:]:
            if kind == "learned":
                cum_learned += 1
            else:
                cum_runs += 1
                if ok:
                    cum_ok += 1
            rate = round((cum_ok / cum_runs) if cum_runs > 0 else 1.0, 3)
            label = datetime.fromtimestamp(ts).strftime("%m/%d %H:%M") if ts > 0 else "now"
            curve_points.append({
                "ts": ts,
                "label": label,
                "cumulative": cum_learned,
                "runs": cum_runs,
                "success_rate": rate,
            })

        # Ensure at least 2 points so charts render gracefully even before runs accumulate
        if len(curve_points) == 1:
            pt = curve_points[0]
            curve_points.insert(0, {"ts": pt["ts"] - 60, "label": "init", "cumulative": 0, "runs": 0, "success_rate": 1.0})

        overall_rate = round(total_successes / total_runs, 4) if total_runs > 0 else (1.0 if exps else 0.0)
        return {
            "total": len(exps),
            "by_maturity": by_maturity,
            "by_category": by_category,
            "total_runs": total_runs,
            "total_successes": total_successes,
            "overall_success_rate": overall_rate,
            "total_recoveries": total_recoveries,
            "curve_points": curve_points,
        }

    def format_experiences_index(self) -> str:
        exps = self.list_experiences()
        if not exps:
            return "No Python Experiences learned yet. Solve a multi-step task or run `/learn` to create one!"
        lines = []
        for e in exps:
            pct = f"{int(round(e.success_rate * 100))}%"
            lines.append(
                f"- **`{e.slug}`** `v{e.version}` [{e.maturity}] — {e.description} "
                f"*(runs: {e.runs}, success: {pct}, risk: `{e.risk_tier}`)*"
            )
        return (
            "### 🧠 Tchiko Learned Experiences (Python Tools)\n"
            + "\n".join(lines)
            + "\n\nUse `/exp run <slug>`, `/exp show <slug>`, or `/learn [name]` to capture the last task."
        )

    def ensure_starter_experiences(self) -> None:
        """Seed 3 verified stdlib starter Experiences on first run if the catalog is empty."""
        if self.list_experiences():
            return
        for spec in _STARTER_EXPERIENCES:
            self.save_experience(
                slug=spec["slug"],
                title=spec["title"],
                description=spec["description"],
                code=spec["code"],
                category=spec["category"],
                triggers=spec["triggers"],
                parameters=spec["parameters"],
                source_prompt="Built-in starter experience",
                evolution_note="Starter verified Python experience",
                auto_promote=True,
            )


# ── Built-in Verified Starter Experiences (pure stdlib Python) ───────────────
_STARTER_EXPERIENCES: List[Dict[str, Any]] = [
    {
        "slug": "port-socket-inspector",
        "title": "Port & Socket Inspector",
        "description": "Inspect listening TCP/UDP sockets or check which process owns a specific port.",
        "category": "networking",
        "triggers": ["port", "listening", "socket", "eaddrinuse", "ss"],
        "parameters": {"port": {"type": "string", "description": "Optional port number to filter", "default": ""}},
        "code": '''#!/usr/bin/env python3
"""Tchiko Experience Tool: Port & Socket Inspector."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from typing import Any, Dict


def run(params: Dict[str, Any], dry_run: bool = False) -> Dict[str, Any]:
    port = str(params.get("port") or "").strip()
    if dry_run:
        return {"ok": True, "summary": f"Dry-run OK: would inspect listening sockets (port={port or 'all'})."}

    if not shutil.which("ss"):
        return {"ok": False, "summary": "`ss` utility is not available on this host."}

    proc = subprocess.run(["ss", "-tulnp"], capture_output=True, text=True, timeout=10)
    lines = proc.stdout.splitlines()
    if port:
        matched = [ln for ln in lines if f":{port} " in ln or ln.endswith(f":{port}")]
        body = "\\n".join(matched[:25]) if matched else f"No process is currently listening on port {port}."
        return {"ok": True, "summary": f"Port {port}: {len(matched)} matching socket(s).", "details": body}

    return {"ok": proc.returncode == 0, "summary": f"Found {max(0, len(lines) - 1)} socket entries.", "details": "\\n".join(lines[:30])}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--params", default="{}")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    params = json.loads(args.params) if args.params else {}
    res = run(params if isinstance(params, dict) else {}, dry_run=(args.dry_run or args.self_test))
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
''',
    },
    {
        "slug": "systemd-service-doctor",
        "title": "Systemd Service Doctor",
        "description": "Audit failed systemd system/user units or inspect a specific service's status and recent errors.",
        "category": "services",
        "triggers": ["systemd", "service", "daemon", "failed unit", "journalctl"],
        "parameters": {"unit": {"type": "string", "description": "Optional systemd unit name", "default": ""}},
        "code": '''#!/usr/bin/env python3
"""Tchiko Experience Tool: Systemd Service Doctor."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from typing import Any, Dict


def run(params: Dict[str, Any], dry_run: bool = False) -> Dict[str, Any]:
    unit = re.sub(r"[^A-Za-z0-9_.@-]", "", str(params.get("unit") or "").strip())
    if dry_run:
        return {"ok": True, "summary": f"Dry-run OK: would audit systemd unit ({unit or 'all failed units'})."}

    if not shutil.which("systemctl"):
        return {"ok": False, "summary": "`systemctl` is not installed on this host."}

    if not unit:
        sys_p = subprocess.run(["systemctl", "--failed", "--no-pager", "--plain"], capture_output=True, text=True, timeout=10)
        usr_p = subprocess.run(["systemctl", "--user", "--failed", "--no-pager", "--plain"], capture_output=True, text=True, timeout=10)
        details = f"=== System Failed ===\\n{sys_p.stdout.strip()}\\n\\n=== User Failed ===\\n{usr_p.stdout.strip()}"
        return {"ok": True, "summary": "Audited system and user systemd units.", "details": details}

    st = subprocess.run(["systemctl", "status", unit, "--no-pager", "-l"], capture_output=True, text=True, timeout=10)
    if st.returncode != 0 and "could not be found" in (st.stderr + st.stdout).lower():
        st = subprocess.run(["systemctl", "--user", "status", unit, "--no-pager", "-l"], capture_output=True, text=True, timeout=10)
    return {"ok": True, "summary": f"Inspected systemd unit `{unit}` (exit={st.returncode}).", "details": (st.stdout or st.stderr)[:2200]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--params", default="{}")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    params = json.loads(args.params) if args.params else {}
    res = run(params if isinstance(params, dict) else {}, dry_run=(args.dry_run or args.self_test))
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
''',
    },
    {
        "slug": "disk-space-auditor",
        "title": "Disk & Directory Space Auditor",
        "description": "Report filesystem disk usage and top largest subdirectories inside a target path.",
        "category": "system",
        "triggers": ["disk space", "storage", "disk full", "largest folders", "inodes"],
        "parameters": {"path": {"type": "string", "description": "Directory to inspect", "default": "~"}},
        "code": '''#!/usr/bin/env python3
"""Tchiko Experience Tool: Disk & Directory Space Auditor."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _dir_size_shallow(root: Path) -> List[Tuple[int, str]]:
    items: List[Tuple[int, str]] = []
    try:
        for child in root.iterdir():
            try:
                if child.is_symlink():
                    continue
                if child.is_file():
                    items.append((child.stat().st_size, child.name))
                elif child.is_dir():
                    total = 0
                    for dirpath, _dirs, files in os.walk(child, followlinks=False):
                        for fn in files:
                            try:
                                total += os.path.getsize(os.path.join(dirpath, fn))
                            except OSError:
                                pass
                    items.append((total, child.name + "/"))
            except OSError:
                continue
    except OSError:
        pass
    items.sort(reverse=True)
    return items[:10]


def run(params: Dict[str, Any], dry_run: bool = False) -> Dict[str, Any]:
    target = Path(os.path.expanduser(str(params.get("path") or "~"))).resolve()
    if dry_run:
        return {"ok": True, "summary": f"Dry-run OK: would audit disk usage for {target}."}
    if not target.exists():
        return {"ok": False, "summary": f"Path does not exist: {target}"}

    du = shutil.disk_usage(str(target))
    pct = round((du.used / du.total) * 100.0, 1) if du.total else 0.0
    used_gb = round(du.used / (1024**3), 1)
    total_gb = round(du.total / (1024**3), 1)
    top = _dir_size_shallow(target)
    lines = [f"{round(sz / (1024**2), 1):>8.1f} MB  {name}" for sz, name in top]
    return {
        "ok": True,
        "summary": f"{target}: {used_gb}/{total_gb} GB used ({pct}%).",
        "details": "\\n".join(lines) if lines else "(empty directory)",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--params", default="{}")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    params = json.loads(args.params) if args.params else {}
    res = run(params if isinstance(params, dict) else {}, dry_run=(args.dry_run or args.self_test))
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
''',
    },
]
