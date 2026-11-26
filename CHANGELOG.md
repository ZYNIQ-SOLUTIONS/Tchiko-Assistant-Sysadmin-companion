# Changelog

All notable changes to **Tchiko Assistant (`Tchiko-Assistant-Sysadmin-companion`)** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- **Tchiko RC — Encrypted Remote Control (`tchiko/remote/`, `rc/`)**: Zero-dependency `asyncio` HTTPS + RFC 6455 WebSocket server with self-signed SAN TLS certificates (`~/.config/tchiko/`), paired with a pure HTML/CSS/vanilla ES-module **Tele-Command Link** web app offering full desktop parity (streaming chat, inline **Privileged Command Authorization**, `/proc` SVG ring gauges, live activity timeline, RBAC settings sync, and BoopFace companion).
- **One-Step Optical Tchiko Sigil (`tchiko/remote/sigil.py`, `rc/js/sigil.js`, `rc/js/scanner.js`)**: 192-bit circular 3-ring data pattern (`72 / 64 / 56` cells) with CRC-16/CCITT and 6-byte `GF(256)` Reed-Solomon parity (correcting up to 3 corrupted bytes), decoded in-browser via affine locator fitting, rotation search, and Berlekamp-Massey from live camera video, dropped/pasted screenshots, or `#pair=<token>` fragments.
- **Zero-Trust E2E Protocol (`tchiko/remote/crypto.py`, `rc/js/channel.js`)**: Ephemeral ECDH P-256 + HKDF-SHA256 + mutual HMAC-SHA256 transcript proof + AES-256-GCM frames with monotonic 64-bit counters, 6-digit visual Safety Code MITM check, single active client enforcement (`4009` eviction), and `0600` `config/rc_pair.json` resume credentials.
- **Headless & Remote CLI Targets (`main.py`, `Makefile`)**: Added `--open-remote`, `--remote`, `--rc-port`, `--rc-no-tls`, and `--sigil-out`, plus `make remote` and `make remote-headless`.
- **Tchiko RC & Sigil Test Suites (`tests/test_remote_crypto.py`, `tests/test_remote_sigil.py`, `tests/test_remote_e2e.py`, `tests/rc/`)**: Unit and full-stack Node.js WebCrypto E2E tests plus 14-case warped/rotated/noisy optical sigil decoding verification.
- Open-source community & governance documentation: `LICENSE` (MIT), `CODE_OF_CONDUCT.md`, `SECURITY.md`, and `CHANGELOG.md`.
- GitHub Issue templates (`.github/ISSUE_TEMPLATE/bug_report.yml`, `feature_request.yml`, `config.yml`), Pull Request template (`.github/pull_request_template.md`), and CI workflow (`.github/workflows/ci.yml`).
- Expanded `CONTRIBUTING.md` with fork/branch workflow, Conventional Commits, quality gates, and step-by-step guides for adding tools, emotions, coats, and UI styles.
- `Makefile` targets for `lint`, `typecheck`, and `install-desktop`.
- **3-Tier Shell Risk Classifier (`ConfigManager.classify_command`)**: Classifies commands into `SAFE_READONLY`, `MUTATING_LOCAL`, and `PRIVILEGED_DESTRUCTIVE`, auto-allowing `SAFE_READONLY` diagnostics in Supervised Review mode.
- **Snapshot & Rollback Ledger (`/undo`, `/rollback`)**: Immutable pre-edit snapshots for `patch_file_content()` and `write_file_content()`.
- **Pluggable Skills System (`tchiko/skills_loader.py`, `skills/*.md`)**: Added `/skills` and built-in runbooks (`nginx-tls-audit`, `postgres-doctor`, `gpu-cuda-doctor`, `git-recovery`).
- **Expanded Sysadmin Toolkit**: Added `/containers`, `/systemd`, `/net`, `/disk`, `/gpu`, `/tls <host>`, and `/git [path]` tools with RBAC gating and ReAct XML tags.
- **Next-Gen ReAct Engine**: Parallel read-only tool execution (`asyncio.gather`), mid-loop `asyncio.Future` approval resumption, and Ollama NDJSON streaming.
- **Proactive Desktop UX**: Background `SystemWatchdog` (`tchiko/watchdog.py`), GTK3 drag-and-drop file/dir analyzer, and **Diagnose Clipboard** context menu action.
- **BoopFace Visual Redesign & GitHub Pages / Netlify**: Replaced legacy mascot with `CX-ArtLab/BoopFace` across both the GTK3 desktop app (`SvgGhostRenderer`) and `landing/` (`<boop-face>`).

### Changed
- **Tactile Cyber-Physical Instrumentation Console UI (`rc/css/rc.css`, `rc/index.html`, `rc/js/app.js`, `tchiko/ui_theme.py`)**: Redesigned both Tchiko RC and the GTK3 desktop UI with micro-grid basalt/obsidian surfaces, 5–6px beveled keycaps, mechanical rocker switches with phosphor LEDs, `SYS.01` specimen CRT framing for BoopFace, and coded sysadmin action modules (`DIAG // SYS_HEALTH`, `NET // PORT_AUDIT`, `SEC // SSH_KEYSMITH`, `MEM // CONTEXT_LEDGER`).
- Generalized hardcoded developer home paths in documentation and `Tchiko-Assistant.desktop`.
- Updated `README.md`, `docs/ARCHITECTURE.md`, `SECURITY.md`, and the web landing page (`index.html`, `landing/index.html`) to document Tchiko RC, the Optical Sigil protocol, and the new UI architecture.

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
