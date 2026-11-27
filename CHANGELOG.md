# Changelog

All notable changes to **Tchiko Assistant (`Tchiko-Assistant-Sysadmin-companion`)** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [2.0.0] - 2026-11-27

First stable open-source release.

### Added
- **Container image (`Dockerfile`, `docker/`, `compose.yaml`)**: Multi-arch (`linux/amd64`, `linux/arm64`) headless Tchiko RC image published to `ghcr.io/zyniq-solutions/tchiko-assistant`. It runs as non-root user `tchiko` (UID 10001) under `tini`, with an HTTPS `/health` healthcheck, persistent volumes for config, experiences and TLS material, and **supervised permissions on first start** (`TCHIKO_PERMISSIONS`).
- **Web app QR code in the Tchiko RC window (`tchiko/remote/qr.py`, `tchiko/remote/pair_window.py`)**: The pairing window shows the web app address as a QR code instead of a text link, so a phone camera opens Tchiko RC directly. The QR encoder is dependency-free (byte mode, versions 1-10, levels L/M/Q/H, standard mask penalty scoring). It matches the `qrcode` reference library module-for-module and decodes correctly with ZXing.
- **Release pipeline (`.github/workflows/release.yml`)**: A `vX.Y.Z` tag runs a version guard against `pyproject.toml`, `tchiko/__init__.py` and `CHANGELOG.md`, then the tests, self-test and ruff. It builds and smoke-tests the image **before** anything is pushed, then pushes the multi-arch image with SBOM and build-provenance attestation and publishes a GitHub Release built from the matching changelog section. Only the highest stable tag moves `:latest` and the "Latest" release, so re-running an older tag never downgrades users.
- **CI container job**: Every push builds the image and checks `/health`, the web app, the pairing link, supervised defaults and the non-root UID. A new CI step verifies that headless mode imports without GTK or Cairo.
- **`OLLAMA_HOST` support**: The agent engine and the GPU & Local AI Doctor honour `OLLAMA_HOST` (for example `http://host.docker.internal:11434`) instead of probing loopback only.
- **`--rc-public-url` / `TCHIKO_RC_PUBLIC_URL`**: Sets the externally reachable base URL printed in headless pairing links (for NAT, Docker and reverse proxies).
- **Headless pairing renewal**: `--remote` prints a fresh single-use pairing link whenever the previous one expires or the device is unpaired. It no longer prints a link while a paired device is on record.
- **`TCHIKO_RC_SANS`**: Explicit TLS certificate names (IPs or DNS names). The container derives it from `TCHIKO_RC_PUBLIC_URL`, so the certificate matches the address clients use and is not reissued when the container IP changes. Persisted certificates are renewed after 300 days, before their 365-day expiry.
- `make docker-build` / `make docker-run` targets and a `remote` extra (`cryptography`) in `pyproject.toml`.
- **Natural conversation & clarification gate (`tchiko/conversation.py`)**: Casual chat handling, `<ask_user>` interactive pauses, scoped ambiguity detection and anaphora resolution.
- **Resilient agentic loop (`tchiko/agent_loop.py`)**: Typed `FailureClass` recovery (including `NETWORK_TRANSIENT`), malformed tag repair, duplicate-failure guard and transactional auto-rollback.
- **Hardened Python Experiences (`tchiko/experiences.py`, `experiences/`)**: AST and secret security validation, episode distillation, maturity progression (`DRAFT -> VERIFIED -> HARDENED / NEEDS_REPAIR`), versioning and rollback, synonym retrieval, and three starter experiences (`disk-space-auditor`, `port-socket-inspector`, `systemd-service-doctor`).
- **Visual Experiences & Learning Studio (`tchiko/experiences_view.py`)**: Cairo learning-curve chart, maturity metrics, search and filter, dry-run/run/approve/rollback/delete controls, synced to Tchiko RC.
- **Learning benchmark suite (`benchmarks/run_learning_benchmark.py`)** plus tests for conversation, agent loop, experiences and the remote experiences protocol.
- **Landing page editions**: The site now presents Tchiko Community (open source, MIT) and Tchiko Pro (paid).
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
- **Tchiko RC web app redesign (`rc/`)**: Mobile-first UX with the Obsidian Glass theme.
- **Landing page (`index.html`, `landing/index.html`)**: Rebuilt with a responsive, mobile-first layout.
- **Headless mode no longer needs Cairo**: `tchiko/__init__.py` and `main.py` load the Cairo renderer lazily, so `main.py --remote` runs on the standard library plus optional `cryptography`.
- CI now runs a pinned ruff (`0.17.6`) as a blocking check, including `benchmarks/`.
- **Tactile Cyber-Physical Instrumentation Console UI (`rc/css/rc.css`, `rc/index.html`, `rc/js/app.js`, `tchiko/ui_theme.py`)**: Redesigned both Tchiko RC and the GTK3 desktop UI with micro-grid basalt/obsidian surfaces, 5–6px beveled keycaps, mechanical rocker switches with phosphor LEDs, `SYS.01` specimen CRT framing for BoopFace, and coded sysadmin action modules (`DIAG // SYS_HEALTH`, `NET // PORT_AUDIT`, `SEC // SSH_KEYSMITH`, `MEM // CONTEXT_LEDGER`).
- Generalized hardcoded developer home paths in documentation and `Tchiko-Assistant.desktop`.
- Updated `README.md`, `docs/ARCHITECTURE.md`, `SECURITY.md`, and the web landing page (`index.html`, `landing/index.html`) to document Tchiko RC, the Optical Sigil protocol, and the new UI architecture.
- `SECURITY.md` supported versions now cover `2.0.x`.

### Fixed
- Resolved all ruff findings (unused imports, f-string without placeholders, unused loop variable, implicit `zip()` strictness, ambiguous variable name).
- Removed the hardcoded developer path for the `agy` CLI fallback. It now resolves to `~/.local/bin/agy`.
- `--remote` no longer crashes at startup when the Tchiko Sigil SVG path is not writable. It prints the one-step link instead.
- `settings.json` is now written atomically. An interrupted save can no longer leave a truncated file that silently loads the permissive defaults. The container entrypoint also fails closed: it backs up an unreadable `settings.json` and re-seeds the chosen permission mode.
- `OLLAMA_HOST` parsing follows the Ollama CLI (`:PORT`, bare IPv6, `0.0.0.0` bind values).
- The container healthcheck reads the running server's actual `--rc-port` / `--rc-no-tls` arguments.
- `tests/test_remote_sigil.py::test_render_svg_structure` no longer fails about 20% of the time; the arc count depended on a random payload.

### Removed
- A stray, accidentally committed `$HOME/.zshrc` file from the repository root.

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

[Unreleased]: https://github.com/ZYNIQ-SOLUTIONS/Tchiko-Assistant-Sysadmin-companion/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/ZYNIQ-SOLUTIONS/Tchiko-Assistant-Sysadmin-companion/releases/tag/v2.0.0
