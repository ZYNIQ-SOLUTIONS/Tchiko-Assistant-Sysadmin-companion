# Changelog

All notable changes to **Tchiko Assistant (`Tchiko-Assistant-Sysadmin-companion`)** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- Open-source community & governance documentation: `LICENSE` (MIT), `CODE_OF_CONDUCT.md`, `SECURITY.md`, and `CHANGELOG.md`.
- GitHub Issue templates (`.github/ISSUE_TEMPLATE/bug_report.yml`, `feature_request.yml`, `config.yml`), Pull Request template (`.github/pull_request_template.md`), and CI workflow (`.github/workflows/ci.yml`).
- Expanded `CONTRIBUTING.md` with fork/branch workflow, Conventional Commits, quality gates, and step-by-step guides for adding tools, emotions, coats, and UI styles.
- `Makefile` targets for `lint`, `typecheck`, and `install-desktop`.

### Changed
- Generalized hardcoded developer home paths in documentation and `Tchiko-Assistant.desktop`.
- Updated `README.md` and `docs/ARCHITECTURE.md` to document the `tchiko/ui_theme.py` design system.

---

## [1.2.0]

### Added
- **Unified Design System (`tchiko/ui_theme.py`)**: Centralized graphite & crimson-accent CSS tokens, `RingGauge` telemetry widget, and shared Markdown-to-Pango markup renderer.
- **5-Tier Autonomous Agent Engine (`tchiko/agent_engine.py`)**: Added real-time `agy` CLI NDJSON stream-json bridge (`--output-format stream-json`), persistent `agy_conversation_id` memory, and an 8-step Multi-Tool ReAct loop with `<think>` block sanitization.
- **6-Step Autonomous Crash Doctor (`LinuxSystemToolkit.diagnose_and_heal_app`)**: Automated binary/symlink resolution, `SingletonLock`/`Crashpad` inspection, crash log scanning, OpenSSL X.509 certificate auditing, and atomic `.bak` patching.
- **Engineering Docs & Test Suite**: Added `docs/ARCHITECTURE.md` and `tests/test_engine_and_tools.py`.

---

## [1.1.0]

### Added
- **Parametric Cairo Vector & Spring-Jelly Physics (`tchiko/svg_ghost_renderer.py`)**: 32-puff closed cubic Bézier body, 4 articulated wings, 6 animated paws, 10 procedural emotion states, and 4 coat palettes with lossless SVG export.
- **GTK3 Desktop Companion (`tchiko/ghost_widget.py`, `tchiko/assistant_window.py`, `tchiko/settings_window.py`)**: Frameless RGBA overlay, middle-click Quick Input Pill, live Pango speech bubble, Chat & System Studio, and RBAC permission settings.
- **Interactive Web Showcase (`landing/index.html`)**: 1:1 HTML5 Canvas + SVG port and Netlify deployment configuration (`netlify.toml`).
