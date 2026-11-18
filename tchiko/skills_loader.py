"""Pluggable Markdown/YAML-Frontmatter Skills & Runbooks Loader for Tchiko Assistant.

Allows contributors and sysadmins to drop domain-specific runbooks into `skills/*.md`
(or `skills/<name>/SKILL.md`) without editing Python core. Skills are matched
against user prompts and injected into the agent's context or invoked via `/skills`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .config_manager import PROJECT_ROOT


SKILLS_DIR = PROJECT_ROOT / "skills"


@dataclass
class Skill:
    """A pluggable Tchiko sysadmin skill or diagnostic runbook."""

    name: str
    description: str
    triggers: List[str] = field(default_factory=list)
    body: str = ""
    path: str = ""


class SkillsLoader:
    """Discovers, parses, and matches `skills/*.md` runbooks."""

    def __init__(self, skills_dir: Path = SKILLS_DIR) -> None:
        self.skills_dir = Path(skills_dir)

    @staticmethod
    def _parse_skill_file(file_path: Path) -> Optional[Skill]:
        try:
            raw = file_path.read_text(encoding="utf-8")
        except Exception:
            return None

        name = file_path.parent.name if file_path.name == "SKILL.md" else file_path.stem
        description = ""
        triggers: List[str] = []
        body = raw

        fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", raw, flags=re.DOTALL)
        if fm_match:
            fm_text, body = fm_match.group(1), fm_match.group(2).strip()
            for line in fm_text.splitlines():
                if ":" not in line:
                    continue
                key, val = line.split(":", 1)
                k = key.strip().lower()
                v = val.strip().strip("\"'")
                if k == "name" and v:
                    name = v
                elif k == "description":
                    description = v
                elif k == "triggers":
                    triggers = [t.strip().lower() for t in v.strip("[]").split(",") if t.strip()]

        if not triggers:
            triggers = [t for t in re.split(r"[-_\s]+", name.lower()) if len(t) > 2]

        return Skill(
            name=name,
            description=description or f"Runbook for {name}",
            triggers=triggers,
            body=body,
            path=str(file_path),
        )

    def list_skills(self) -> List[Skill]:
        """Return all valid skills sorted by name."""
        if not self.skills_dir.exists():
            return []
        candidates: List[Path] = []
        for entry in sorted(self.skills_dir.iterdir()):
            if entry.is_file() and entry.suffix.lower() == ".md" and entry.name.lower() != "readme.md":
                candidates.append(entry)
            elif entry.is_dir() and (entry / "SKILL.md").is_file():
                candidates.append(entry / "SKILL.md")

        skills: List[Skill] = []
        for path in candidates:
            parsed = self._parse_skill_file(path)
            if parsed is not None:
                skills.append(parsed)
        return sorted(skills, key=lambda s: s.name.lower())

    def get_skill(self, name: str) -> Optional[Skill]:
        """Look up a skill by exact or case-insensitive name."""
        target = name.strip().lower()
        for skill in self.list_skills():
            if skill.name.lower() == target:
                return skill
        return None

    def match_skills(self, prompt: str, max_matches: int = 2) -> List[Skill]:
        """Match skills whose triggers appear in the user prompt."""
        lower = prompt.lower()
        scored: List[tuple[int, Skill]] = []
        for skill in self.list_skills():
            hits = sum(1 for trig in skill.triggers if trig and trig in lower)
            if hits > 0:
                scored.append((hits, skill))
        scored.sort(key=lambda item: (-item[0], item[1].name))
        return [s for _, s in scored[:max_matches]]

    def format_skills_index(self) -> str:
        """Render a Markdown summary of all installed skills."""
        skills = self.list_skills()
        if not skills:
            return "No skills found in `skills/`."
        lines = [
            f"- **`{s.name}`** — {s.description} *(triggers: {', '.join(s.triggers)})*"
            for s in skills
        ]
        return (
            "### 🧩 Tchiko Loaded Skills & Runbooks\n"
            + "\n".join(lines)
            + "\n\nUse `/skills <name>` to view a runbook, or mention its topic in any prompt."
        )
