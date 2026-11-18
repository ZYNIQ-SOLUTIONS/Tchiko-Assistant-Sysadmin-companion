# Contributing to Tchiko Assistant

Thank you for your interest in contributing to **Tchiko Assistant (`Tchiko-Assistant-Sysadmin-companion`)**! Whether you are fixing a bug, adding a Linux sysadmin tool, crafting a new procedural Cairo emotion, or improving documentation, this guide walks you through **the contribution way** from setup to merge.

By participating in this project, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md). If you discover a security vulnerability, please follow [SECURITY.md](SECURITY.md) instead of opening a public issue.

---

## Table of Contents

1. [Ways to Contribute](#1-ways-to-contribute)
2. [Development Environment Setup](#2-development-environment-setup)
3. [Git Workflow & Conventional Commits](#3-git-workflow--conventional-commits)
4. [Step-by-Step Engineering Guides](#4-step-by-step-engineering-guides)
   - [4.1 Adding a New Autonomous Linux Tool](#41-adding-a-new-autonomous-linux-tool)
   - [4.2 Adding a New Procedural Emotion or Coat Palette](#42-adding-a-new-procedural-emotion-or-coat-palette)
   - [4.3 Updating the Design System & GTK3 UI](#43-updating-the-design-system--gtk3-ui)
   - [4.4 Adding a Pluggable Skill (`skills/*.md`)](#44-adding-a-pluggable-skill-skillsmd)
5. [Code Quality & Verification Gates](#5-code-quality--verification-gates)
6. [Opening a Pull Request](#6-opening-a-pull-request)

---

## 1. Ways to Contribute

- **Report Bugs:** Use the [Bug Report template](.github/ISSUE_TEMPLATE/bug_report.yml) with your Ubuntu version, display server (`X11` / `Wayland`), and `python3 main.py --self-test` output.
- **Propose Features:** Use the [Feature Request template](.github/ISSUE_TEMPLATE/feature_request.yml) to discuss new tools, emotions, or UI improvements before writing large patches.
- **Write Code & Tests:** Pick up an open issue, implement a new `LinuxSystemToolkit` capability, or expand `tests/test_engine_and_tools.py`.
- **Improve Documentation:** Clarify setup steps, add examples to `README.md`, or expand `docs/ARCHITECTURE.md`.

---

## 2. Development Environment Setup

Tchiko uses Ubuntu's native `python3-gi` and `python3-gi-cairo` bindings for zero-overhead GTK3 compositing.

### 2.1 Install System Dependencies (Ubuntu 22.04 / 24.04 / 25.10)

```bash
sudo apt update && sudo apt install -y \
    python3 python3-venv python3-gi python3-gi-cairo gir1.2-gtk-3.0 xclip
```

### 2.2 Fork, Clone & Create a Virtual Environment

```bash
# 1. Fork the repository on GitHub, then clone your fork
git clone git@github.com:<your-username>/Tchiko-Assistant-Sysadmin-companion.git
cd Tchiko-Assistant-Sysadmin-companion

# 2. Add upstream remote to stay in sync
git remote add upstream git@github.com:ZYNIQ-SOLUTIONS/Tchiko-Assistant-Sysadmin-companion.git

# 3. Create a venv that inherits system GTK3/Cairo packages
python3 -m venv --system-site-packages venv
source venv/bin/activate

# 4. Install optional developer tools (pytest, ruff, mypy)
pip install -e ".[dev]"
```

### 2.3 Verify Your Local Setup

```bash
make self-test   # Runs end-to-end subsystem checks & exports canonical SVGs
make test        # Runs the unit & integration test suite
```

Both commands should exit with code `0`.

---

## 3. Git Workflow & Conventional Commits

1. **Sync `main` and branch off:**
   ```bash
   git checkout main
   git pull upstream main
   git checkout -b feat/your-short-topic
   ```
   Use descriptive branch prefixes: `feat/`, `fix/`, `docs/`, `refactor/`, `test/`, or `ci/`.

2. **Use Conventional Commits:**
   Write clear, imperative commit messages following `<type>(<scope>): <summary>`:
   - `feat(tools): add systemd journal log inspector`
   - `fix(renderer): clamp spring-jelly velocity on rapid clicks`
   - `docs(contributing): document coat palette registration`
   - `test(engine): verify denylist blocks subshell patterns`

3. **Keep PRs Focused:**
   One logical change per Pull Request makes reviews faster and rollbacks safer.

---

## 4. Step-by-Step Engineering Guides

### 4.1 Adding a New Autonomous Linux Tool

All host-level capabilities live in [`tchiko/system_tools.py`](tchiko/system_tools.py) inside [`LinuxSystemToolkit`](tchiko/system_tools.py) and return a strongly-typed [`ToolResult`](tchiko/system_tools.py):

```python
@dataclass
class ToolResult:
    ok: bool
    title: str
    output: str
    command: str = ""
    exit_code: int = 0
    duration_ms: int = 0
```

**Checklist for adding a tool:**
1. **Enforce RBAC Permission Gating:** Check `self.config.can_execute_capability("<capability_domain>")` at the top of the method using one of the six domains:
   - `bash_execution`
   - `filesystem_read_write`
   - `process_management`
   - `desktop_automation`
   - `package_management`
   - `network_requests`
2. **Respect `command_denylist`:** Any shell execution must go through `run_shell_command()` or check `self.config.is_command_allowed(...)`.
3. **Create `.bak` Backups Before Mutating Files:** Follow `patch_file_content()` (`shutil.copy2(target, str(target) + ".bak")`).
4. **Expose in the Multi-Tool ReAct Parser (Optional):** Register the XML tag in `TchikoAgentEngine._extract_tool_actions()` and dispatch it in `TchikoAgentEngine._try_external_llm_with_tools()` inside [`tchiko/agent_engine.py`](tchiko/agent_engine.py).
5. **Add Unit Tests:** Add test coverage in [`tests/test_engine_and_tools.py`](tests/test_engine_and_tools.py).

---

### 4.2 Adding a New Procedural Emotion or Coat Palette

All vector rendering lives in [`tchiko/svg_ghost_renderer.py`](tchiko/svg_ghost_renderer.py):

1. **New Coat Theme:**
   - Add an RGB tuple dictionary to `THEMES` in [`tchiko/svg_ghost_renderer.py`](tchiko/svg_ghost_renderer.py).
   - Register its human-readable display name in `COAT_NAMES` inside [`tchiko/ui_theme.py`](tchiko/ui_theme.py).
2. **New Emotion State:**
   - Add the state name to `EMOTION_LIST` in `tchiko/svg_ghost_renderer.py` and `MOOD_NAMES` in `tchiko/ui_theme.py`.
   - Define its spring-jelly target `(target_sx, target_sy)` in `SvgGhostRenderer.step()`.
   - Add any custom particle/aura effects in `_draw_emotion_fx()`.
3. **Export Canonical SVGs:**
   ```bash
   make export-svg
   ```
   This regenerates `assets/tchiko-*.svg` and `landing/assets/tchiko-*.svg`. Include any updated SVGs in your PR.

---

### 4.3 Updating the Design System & GTK3 UI

All shared GTK3 colors, typography tokens, CSS rules, and the Markdown-to-Pango renderer live in [`tchiko/ui_theme.py`](tchiko/ui_theme.py):

- Reuse existing color tokens (`BG`, `SURFACE`, `ACCENT`, `SUCCESS`, `WARNING`, etc.) rather than hardcoding hex values inside widget files.
- Keep `render_markdown_pango()` resilient to partial/streaming Markdown chunks—always verify with `test_markdown_rendering_is_always_valid_pango` in [`tests/test_engine_and_tools.py`](tests/test_engine_and_tools.py).
- Remember that GTK3 is strictly single-threaded: any background callback mutating UI widgets must be marshaled through `GLib.idle_add()`.

---

### 4.4 Adding a Pluggable Skill (`skills/*.md`)

Domain-specific runbooks live in `skills/*.md` (loaded by [`SkillsLoader`](tchiko/skills_loader.py)) and require no Python changes:

```markdown
---
name: redis-doctor
description: Inspect Redis memory, evictions, slowlog, and persistence health.
triggers: redis, redis-cli, evictions, rdb, aof
---
# Redis Doctor Runbook

1. Check service & logs with `<systemd unit="redis-server" />`.
2. Inspect memory & keyspace via `redis-cli info memory`.
```

Verify your skill loads and matches triggers cleanly with `/skills` or `SkillsLoader().match_skills("...")`.

---

## 5. Code Quality & Verification Gates

- **Type Annotations:** All new functions and methods must include Python `3.10+` type annotations (`from __future__ import annotations`).
- **Docstrings:** Document module responsibilities, class invariants, thread-safety notes, and return types.
- **Cleanliness:** Never commit secrets, personal paths, `.bak` files, or `config/agent_memory.json`.

Run all checks before pushing:

```bash
make test        # Unit & integration tests
make self-test   # Subsystem self-test & SVG export
make lint        # Ruff linter (if installed)
```

---

## 6. Opening a Pull Request

1. Push your feature branch to your fork:
   ```bash
   git push origin feat/your-short-topic
   ```
2. Open a Pull Request against `main` using the [Pull Request template](.github/pull_request_template.md).
3. Link any related issue (`Closes #123`) and ensure all CI checks in [`.github/workflows/ci.yml`](.github/workflows/ci.yml) pass.
4. Respond to review feedback with additional commits (avoid force-pushing after review starts unless requested).

Welcome to the community—happy hacking! 🐾
