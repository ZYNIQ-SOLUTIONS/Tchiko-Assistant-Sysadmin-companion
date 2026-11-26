# Tchiko-Assistant-Sysadmin-companion

<div align="center">
  <img src="assets/tchiko-logo.svg" alt="Tchiko Assistant Official Vector Logo" width="210" height="210" />

  # TCHIKO ASSISTANT
  **Autonomous Linux Systems Agent, 5-Tier DevOps Engine & BoopFace Cairo/SVG Desktop Companion**

  [![Google Antigravity SDK](https://img.shields.io/badge/Google_Antigravity-SDK_%2B_CLI_Stream--JSON-ef4444?style=for-the-badge)](antigravity.yaml)
  [![Runtime](https://img.shields.io/badge/Python-3.10%2B_%7C_Asyncio-38bdf8?style=for-the-badge)](pyproject.toml)
  [![Graphics](https://img.shields.io/badge/GTK3_%2B_PyCairo-BoopFace_SVG_Engine-10b981?style=for-the-badge)](tchiko/svg_ghost_renderer.py)
  [![Platform](https://img.shields.io/badge/Ubuntu_Linux-X11_%26_XWayland-0f172a?style=for-the-badge)](main.py)
  [![License: MIT](https://img.shields.io/badge/License-MIT-ffffff?style=for-the-badge)](LICENSE)
  [![Open Source Helpers](https://www.codetriage.com/zyniq-solutions/tchiko-assistant-sysadmin-companion/badges/users.svg)](https://www.codetriage.com/zyniq-solutions/tchiko-assistant-sysadmin-companion)

  **[Architecture Specification (`docs/ARCHITECTURE.md`)](docs/ARCHITECTURE.md)** • **[Contributing Guide (`CONTRIBUTING.md`)](CONTRIBUTING.md)** • **[Security Policy (`SECURITY.md`)](SECURITY.md)** • **[Web Workbench (`landing/index.html`)](landing/index.html)**
</div>

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Architecture & Execution Pipeline](#2-system-architecture--execution-pipeline)
3. [Tchiko RC — Encrypted Remote Control & Tchiko Sigil](#3-tchiko-rc--encrypted-remote-control--tchiko-sigil)
4. [Repository Structure](#4-repository-structure)
5. [Deep-Dive: Core Engineering Subsystems](#5-deep-dive-core-engineering-subsystems)
6. [Desktop Interaction Matrix](#6-desktop-interaction-matrix)
7. [Installation, Self-Test & Usage](#7-installation-self-test--usage)
8. [Built-In Slash Commands & Natural-Language Sysadmin Playbook](#8-built-in-slash-commands--natural-language-sysadmin-playbook)
9. [Security & Permission Governance (`ConfigManager`)](#9-security--permission-governance-configmanager)
10. [Contributing, Governance & License](#10-contributing-governance--license)

---

## 1. Executive Summary

**Tchiko Assistant** (`Tchiko-Assistant-Sysadmin-companion`) is an open-source, autonomous Linux systems engineering agent and floating desktop companion for **Ubuntu Linux**. Inspired by the mythical six-legged, four-winged **Dijiang (Hundun)** and built on the **Google Antigravity SDK & CLI (`agy`)**, Tchiko combines:

1. **A 5-Tier Autonomous Agent Engine (`tchiko/agent_engine.py`)** capable of multi-step root-cause investigation, log & stack-trace analysis, X.509 certificate auditing, automated binary/source patching with `.bak` rollback safety, OpenSSH key lifecycle management, and real-time NDJSON IPC streaming with `agy`.
2. **A Deterministic & ReAct Linux System Toolkit (`tchiko/system_tools.py`)** providing direct `/proc` telemetry, line-numbered file inspection (`view_file_lines`), minified-bundle-aware regex search (`grep_files`), atomic file patching (`patch_file_content`), and a 6-step **Autonomous Application Crash Doctor (`diagnose_and_heal_app`)**.
3. **A 60 FPS Parametric Cairo Vector & Spring-Jelly Physics Renderer (`tchiko/svg_ghost_renderer.py`)** that renders Tchiko procedurally using closed cubic Bézier splines (32 fur puffs, 4 articulated multi-layered wings, 6 animated paws) with area-conserving Hooke's law squash-and-stretch dynamics (`squish_x`, `squish_y`), exported identically to both `GdkPixbuf` surfaces and standalone SVG assets.
4. **Tchiko RC (`rc/`, `tchiko/remote/`)**: A pure HTML5/CSS/vanilla JS remote control web app that brings full Tchiko Desktop parity to any browser or phone over an end-to-end encrypted channel (`ECDH P-256 + HKDF + HMAC + AES-256-GCM` with 6-digit visual Safety Code), paired in one step via the circular **Tchiko Sigil** pattern or one-step link.

---

## 2. System Architecture & Execution Pipeline

```mermaid
flowchart TD
    subgraph UI["GTK3 Desktop Layer (X11 / XWayland Composited RGBA)"]
        GW["FloatingGhostWidget\n(tchiko/ghost_widget.py)\n• 28 FPS Cairo + GdkPixbuf Overlay\n• Middle-Click Quick Input Pill\n• Live Pango Speech Bubble"]
        AW["TchikoAssistantWindow\n(tchiko/assistant_window.py)\n• Card-Based Streaming Chat\n• Live CPU/RAM/Disk Studio\n• Real-Time Tool & Thought Feed"]
        SW["TchikoSettingsWindow\n(tchiko/settings_window.py)\n• RBAC & Capability Switches\n• Coat Palette & Physics Tuning"]
    end

    subgraph CORE["Autonomous Agent Core (tchiko/agent_engine.py)"]
        AE["TchikoAgentEngine\nAsync Worker Thread + GLib.idle_add Bridge"]
        MEM[("Persistent Context Store\nconfig/agent_memory.json\n• Active cwd & history[24]\n• Last command & artifact\n• agy_conversation_id")]
    end

    subgraph TIERS["5-Tier Dispatch & Reasoning Pipeline"]
        T1["Tier 1: Built-in Slash Router\n(/doctor, /sysinfo, /procs, /memory, /run)"]
        T2["Tier 2: Contextual Memory Resolver\n('copy it', 'retry', 'cd ...', 'remember ...')"]
        T3["Tier 3: Deterministic Sysadmin Planner\n• 6-Step IDE/App Crash Doctor\n• OpenSSH ed25519/RSA + ~/.ssh/config\n• Port/PID Reaper & Repo Scaffolder"]
        T4["Tier 4A/4B: Google Antigravity Runtime\n• Python SDK (google.antigravity.Agent)\n• agy CLI NDJSON Bridge (--output-format stream-json)"]
        T5["Tier 5: 8-Step Multi-Tool ReAct Loop\n• Gemini 2.5 Flash REST / Local Ollama\n• <view_file> <grep> <patch_file> <write_file> <bash>\n• <think> Block Sanitizer"]
    end

    subgraph TOOLS["Ubuntu Host Execution Layer (tchiko/system_tools.py)"]
        TK["LinuxSystemToolkit"]
        CM["ConfigManager\n(config/settings.json ↔ antigravity.yaml)"]
    end

    GW <-->|"Prompt / Live Speech Bubble"| AW
    AW -->|"process_prompt_async()"| AE
    SW -->|"Pub/Sub Observer"| CM
    AE <--> MEM
    AE --> T1 --> T2 --> T3 --> T4 --> T5
    T1 & T2 & T3 & T4 & T5 --> TK
    CM -.->|"Policy Enforcement"| TK
```

### Multi-Step Autonomous Investigation Sequence

When asked to diagnose and fix a failing Linux application (for example: *"can you check why antigravity code ide is not working and crashing fix it"*), Tchiko executes a structured 6-stage engineering workflow:

```mermaid
sequenceDiagram
    autonumber
    actor Eng as Engineer
    participant UI as FloatingGhostWidget / Chat UI
    participant Engine as TchikoAgentEngine
    participant Toolkit as LinuxSystemToolkit
    participant Host as Ubuntu Filesystem & Logs

    Eng->>UI: "check why antigravity code ide is crashing and fix it"
    UI->>Engine: process_prompt_async(prompt)
    Engine->>UI: on_state_change("executing")

    Engine->>Toolkit: Step 1 — find_binaries(["antigravity", "agy", "code"])
    Toolkit->>Host: Resolve PATH, ~/.local/bin symlinks & .desktop entries
    Engine->>UI: on_thought("Step 1/6: Locating binaries & symlinks...")

    Engine->>Toolkit: Step 2 — inspect_config_locks(~/.config/Antigravity)
    Toolkit->>Host: Audit SingletonLock symlinks & Crashpad/*.dmp reports

    Engine->>Toolkit: Step 3 — scan_crash_logs(logs/<latest>/**/*.log)
    Toolkit->>Host: Extract ConnectError / TLS handshake / segfault traces

    Engine->>Toolkit: Step 4 — audit_certificates(resources/app/**/*.pem)
    Toolkit->>Host: Run openssl x509 -noout -subject -dates -checkend 0

    Engine->>Toolkit: Step 5 — patch_file_content(main.js, extension.js)
    Toolkit->>Host: Create .bak backups & patch localhost HTTP/2 nodeOptions

    Engine->>Toolkit: Step 6 — verify_fix()
    Toolkit-->>Engine: Structured Root-Cause, Evidence & Auto-Repair Report
    Engine->>UI: Stream Markdown report + transition to "happy" state
```

---

## 3. Tchiko RC — Encrypted Remote Control & Tchiko Sigil

**Tchiko RC** (`rc/`, `tchiko/remote/`) is a pure HTML5, CSS, and vanilla ES-module **Tele-Command Link** web application styled as a **Tactile Cyber-Physical Instrumentation Console**, allowing you to control Tchiko Desktop remotely from any smartphone, tablet, or browser on your local network with **full desktop parity**.

```text
┌─────────────────────────────────┐           WebSocket / TLS           ┌─────────────────────────────────┐
│         Tchiko Desktop          │  ◄────────────────────────────────► │            Tchiko RC            │
│       (tchiko/remote/)          │     ECDH P-256 + HKDF + HMAC       │         (rc/ pure JS)           │
│  • HTTPS/WSS asyncio server     │         AES-256-GCM Frames          │  • Zero-framework web app       │
│  • Single-use Tchiko Sigil (120s│      Monotonic 64-bit Counters      │  • Tchiko Sigil camera scanner  │
│  • Single active client rule    │       6-Digit Visual Safety Code    │  • WebCrypto SubtleChannel      │
└─────────────────────────────────┘                                     └─────────────────────────────────┘
```

### Key Engineering Features
1. **One-Step Optical Tchiko Sigil Pairing**: A 192-bit circular 3-ring data pattern (`72 / 64 / 56` cells) drawn around the Tchiko specimen (`SYS.01` CRT frame) encoding a 16-byte payload + CRC-16 + 6-byte `GF(256)` Reed-Solomon parity that repairs up to 3 corrupted bytes. Pair by scanning with your camera, dropping/pasting a screenshot, or opening the `#pair=<token>` one-step link.
2. **Zero-Trust End-to-End Encryption** ([Security Policy](SECURITY.md#tchiko-rc-transport--pairing-security-tchikoremote-rc)):
   - Ephemeral **ECDH P-256** key exchange on every connection (with explicit curve-point validation).
   - **HKDF-SHA256** session key derivation with mutual HMAC-SHA256 transcript binding.
   - **AES-256-GCM** authenticated framing with strict monotonic 64-bit per-direction counters (replays, drops, and reordering instantly terminate the session).
   - **6-Digit Visual Safety Code** displayed simultaneously on both the desktop window and remote client to verify against MITM attacks.
3. **Single Active Client Enforcement**: Strictly **one** client can be connected at a time. Authenticating a new client immediately disconnects the previous one with close code `4009`, and paired resume credentials are stored in `config/rc_pair.json` (`0600`). Unpairing on desktop or remote invalidates saved credentials permanently.
4. **Full Feature Parity**: Real-time streaming Chat with inline **Privileged Command Authorization** (`Authorize` / `Authorize All` / `Deny`), live `/proc` CPU/RAM/Disk telemetry with SVG ring gauges, Activity timeline, RBAC permissions sync, and an animated SVG BoopFace companion matching all desktop coat themes and moods.
5. **Desktop & Headless Server Modes**: Launch the pairing window with `make remote` (`./run_tchiko.sh --open-remote`) or run on headless Linux servers via `make remote-headless` (`python3 main.py --remote --rc-port 8765`).

---

## 4. Repository Structure

```text
Tchiko-Assistant-Sysadmin-companion/
├── main.py                        # CLI entry point, X11/Wayland bootstrap, --remote mode & GTK lifecycle
├── run_tchiko.sh                  # Zero-config launcher (provisions .venv with --system-site-packages)
├── pyproject.toml                 # PEP 621 package metadata, console_scripts, ruff/mypy/pytest config
├── Makefile                       # Developer workflow targets (run, test, doctor, export-svg, clean)
├── antigravity.yaml               # Declarative Antigravity agent policy (auto-synced by ConfigManager)
├── netlify.toml                   # Netlify deployment specification for the interactive web showcase
├── requirements.txt               # Optional Python dependencies (google-antigravity SDK)
├── Tchiko-Assistant.desktop       # Freedesktop.org XDG desktop launcher specification
│
├── tchiko/                        # Core Python Package
│   ├── __init__.py                # Package version, metadata & public API exports
│   ├── agent_engine.py            # 5-Tier Autonomous Agent Engine, agy NDJSON bridge & 8-step ReAct loop
│   ├── system_tools.py            # Ubuntu Linux toolkit: /proc telemetry, file view/grep/patch & Crash Doctor
│   ├── config_manager.py          # Thread-safe pub/sub config store & antigravity.yaml policy synchronizer
│   ├── svg_ghost_renderer.py      # Parametric Cairo Bézier renderer, spring-jelly physics & SVG exporter
│   ├── ghost_widget.py            # Frameless RGBA GTK3 overlay, middle-click quick pill & speech bubble
│   ├── assistant_window.py        # Antigravity 2.0-styled Chat, System Studio & real-time Activity feed
│   ├── settings_window.py         # RBAC permission control panel & visual physics customizer
│   ├── ui_theme.py                # Unified graphite/crimson GTK3 design system, tokens & Markdown->Pango renderer
│   ├── skills_loader.py           # Pluggable Markdown/YAML-frontmatter skills & runbooks loader
│   ├── watchdog.py                # Proactive background anomaly detector (RAM/Disk/systemd)
│   └── remote/                    # Tchiko RC Encrypted Remote Control Subsystem
│       ├── __init__.py            # Protocol constants (PROTOCOL_VERSION = 1)
│       ├── crypto.py              # ECDH P-256, HKDF-SHA256, AES-256-GCM SecureChannel (native + pure-Python fallback)
│       ├── sigil.py               # Tchiko Sigil generator, GF(256) Reed-Solomon FEC, CRC-16 & SVG renderer
│       ├── server.py              # Zero-dependency asyncio HTTPS + WebSocket RFC 6455 server & self-signed TLS
│       ├── service.py             # RemoteControlService: 120s sigil sessions, single-connection manager & engine bridge
│       └── pair_window.py         # GTK3 pairing window with live countdown, HiDPI Sigil, Safety Code & controls
│
├── rc/                            # Pure HTML/CSS/Vanilla JS Remote Web App
│   ├── index.html                 # Single Page Application container
│   ├── manifest.webmanifest       # PWA manifest
│   ├── css/
│   │   └── rc.css                 # Responsive stylesheet matching Tchiko Desktop design tokens
│   ├── js/
│   │   ├── app.js                 # SPA controller (Chat, System Studio, Activity, Settings, Security Modal)
│   │   ├── boopface.js            # Animated SVG BoopFace mascot (all 4 coats & 9 moods)
│   │   ├── channel.js             # WebCrypto SubtleChannel & TchikoChannel WebSocket client
│   │   ├── markdown.js            # XSS-safe DOM markdown streaming renderer
│   │   ├── scanner.js             # Camera scanner, drag-and-drop/paste image decoder & #pair= token consumer
│   │   ├── sigil.js               # Circular Tchiko Sigil decoder (affine fit, rotation search, Berlekamp-Massey)
│   │   └── ui.js                  # SVG icon registry, RingGauge, copy toast & status banners
│   └── assets/
│       └── tchiko-icon.svg        # App icon
│
├── skills/                        # Domain-specific sysadmin runbooks (auto-matched & /skills)
│   ├── nginx-tls-audit.md         # Nginx reverse-proxy, TLS 1.3 & HSTS audit runbook
│   ├── postgres-doctor.md         # PostgreSQL locks, connections & WAL health runbook
│   ├── gpu-cuda-doctor.md         # NVIDIA/AMD GPU VRAM & Ollama/vLLM diagnostics
│   └── git-recovery.md            # Detached HEAD, merge conflict & reflog recovery
│
├── config/
│   ├── settings.json              # Persisted runtime settings, RBAC capabilities & window coordinates
│   ├── rc_pair.json               # Paired client credentials (0600, single device, gitignored)
│   └── agent_memory.json          # Auto-managed conversational memory, cwd, notes & agy_conversation_id
│
├── docs/
│   └── ARCHITECTURE.md            # Deep engineering specification (physics math, IPC schema, security model)
│
├── tests/
│   ├── test_engine_and_tools.py   # Unit & integration test suite (toolkit, agent, skills, watchdog)
│   ├── test_remote_crypto.py      # Crypto unit tests (native vs pure-Python, curve validation, replay rejection)
│   ├── test_remote_sigil.py       # Sigil encoding, SVG structure & Reed-Solomon error correction tests
│   ├── test_remote_e2e.py         # Full-stack HTTPS/WSS + Node.js WebCrypto E2E integration test
│   └── rc/
│       ├── e2e_channel.test.mjs   # Real JS TchikoChannel <-> Python RemoteControlService E2E suite
│       ├── render_sigils.py       # Sigil test image generator (warped, rotated, noisy, sheared)
│       └── sigil_decode.test.mjs  # Visual decoder accuracy suite (14/14 warped cases)
│
├── assets/                        # Procedurally exported desktop SVGs & raster previews
│   ├── tchiko-logo.svg            # Canonical idle pose vector exported directly by SvgGhostRenderer
│   └── tchiko-*.svg               # Emotion study vectors (love, happy, roar, executing, sleepy, thinking)
│
└── landing/                       # Self-contained interactive HTML5 Canvas + SVG showcase for Netlify
    ├── index.html                 # 1:1 JavaScript port of SvgGhostRenderer + interactive terminal demo
    ├── _redirects                 # Netlify SPA routing rules
    └── assets/                    # Mirrored vector assets for zero-dependency static hosting
```

---

## 5. Deep-Dive: Core Engineering Subsystems

### 4.1. Antigravity CLI (`agy`) Real-Time NDJSON Stream Bridge
When `~/.local/bin/agy` (or `agy` in `PATH`) is available, [`TchikoAgentEngine._run_agy_cli_stream_json()`](tchiko/agent_engine.py) spawns a non-blocking subprocess:

```bash
agy -p "<prompt>" --output-format stream-json --add-dir "<cwd>" --dangerously-skip-permissions --conversation "<id>"
```

It consumes the newline-delimited JSON (`NDJSON`) stream over `asyncio.subprocess.PIPE`:
- **`{"event": "init"}`**: Captures and persists `conversation_id` into `config/agent_memory.json` (`agy_conversation_id`) so subsequent prompts maintain full multi-turn context across the 48+ native Antigravity tools.
- **`{"event": "step_update", "step_update": {"step_type": "tool"}}`**: Transitions Tchiko's desktop avatar into the `"executing"` state (`Ten-Rings Overdrive`) and streams the active tool name and JSON arguments into both the **Activity log** and **Tchiko's floating desktop speech bubble**.
- **`{"event": "step_update", "step_update": {"step_type": "agent_response"}}`**: Streams `text_delta` chunks directly into the GTK chat card and desktop bubble with sub-10ms latency.

### 4.2. 8-Step Multi-Tool ReAct Loop & `<think>` Sanitizer (Offline / REST Mode)
When running against **Local Ollama** (`gemma4:e4b`, `qwen2.5-coder:1.5b`, `llama3.2:latest`, `lfm2.5:8b`) or the **Gemini 2.5 Flash REST API**, [`TchikoAgentEngine._try_external_llm_with_tools()`](tchiko/agent_engine.py) executes up to **8 autonomous reasoning-and-action turns**:

1. **Reasoning Isolation (`_strip_think_blocks`)**: Extracts `<think>...</think>` blocks (including truncated unclosed blocks) *before* tool parsing. Reasoning summaries are routed to `on_thought()`, preventing internal chain-of-thought examples (such as `<bash>COMMAND</bash>`) from ever leaking into command execution or chat output.
2. **Structured XML Tool Protocol (`_extract_tool_actions`)**:
   - `<view_file path="/path/to/file" start="1" end="120" />` → [`LinuxSystemToolkit.view_file_lines()`](tchiko/system_tools.py)
   - `<grep pattern="ConnectError" path="~/.config/Antigravity/logs" />` → [`LinuxSystemToolkit.grep_files()`](tchiko/system_tools.py) (includes an automatic byte-window fallback for single-line minified JS bundles like `main.js`)
   - `<patch_file path="/path/to/file"><search>...</search><replace>...</replace></patch_file>` → [`LinuxSystemToolkit.patch_file_content()`](tchiko/system_tools.py) (creates an automatic `.bak` backup prior to atomic replacement)
   - `<write_file path="/path/to/file">...</write_file>` → [`LinuxSystemToolkit.write_file_content()`](tchiko/system_tools.py)
   - `<bash>...</bash>` → [`LinuxSystemToolkit.run_shell_command()`](tchiko/system_tools.py)
3. **Closed-Loop Observation Feedback**: After each tool execution, `stdout`/`stderr`, exit codes, and file diffs are fed back into the rolling prompt until the root cause is resolved.

### 4.3. Parametric Cairo Vector & Spring-Jelly Physics Engine
Unlike sprite-based desktop pets that rely on static PNG frames, [`SvgGhostRenderer`](tchiko/svg_ghost_renderer.py) is a pure mathematical vector engine:
- **Damped Harmonic Oscillator Squash & Stretch**:
  $$\ddot{s}_x = -k (s_x - \hat{s}_x) - c \dot{s}_x, \qquad s_y \approx \frac{1}{s_x}$$
  where $k = 18.0$ is the spring stiffness and $c = 0.72$ is the damping factor, preserving cross-sectional area during boops, drags, and hover petting.
- **32-Puff Closed Cubic Bézier Silhouette**: Computes 32 radial anchor points modulated by polar harmonic waves ($\cos(6\theta)$, $\sin(3\theta)$) to form a seamless cloud-soft body with zero sharp vertices.
- **Dual-Surface Pipeline**: The exact same `_draw_scene(ctx, width, height, theme_name, opacity)` method renders to `cairo.ImageSurface` (for 28 FPS GTK3 `GdkPixbuf` animation) and `cairo.SVGSurface` (for lossless `.svg` asset generation).

---

## 6. Desktop Interaction Matrix

| Input / Gesture | Target Surface | System Behavior |
| :--- | :--- | :--- |
| **Middle-Click (Scroll-Wheel Click)** | Floating Tchiko Avatar | Toggles the inline **Quick Input Pill (`Ask Tchiko... ↵`)** directly underneath Tchiko and grabs keyboard focus. |
| **`Enter` (`↵`) in Quick Input** | Quick Input Pill | Dispatches the prompt to `TchikoAgentEngine`, hides the input pill, and streams live tool progress & markdown replies into the **Talking Speech Bubble** above Tchiko. |
| **Single Left-Click** | Floating Tchiko Avatar | Toggles the full **Tchiko Chat & System Studio** window (`💬 Chat`, `⚡ System Studio`, `🧠 Activity`), plus triggers a squishy boop impulse (`squish_x = 1.24, squish_y = 0.78`). |
| **Left-Click + Drag** | Floating Tchiko Avatar | Repositions Tchiko across the X11/XWayland root window with velocity-coupled leg-dangle physics and persists `(position_x, position_y)` to `config/settings.json`. |
| **Cursor Hover / Rubbing** | Floating Tchiko Avatar | Accumulates `_pet_rub_energy`; transitions Tchiko into the `love` state with musical chirp particles (`♪`) once rub threshold is reached. |
| **Scroll Wheel Up / Down** | Floating Tchiko Avatar | Cycles deterministically through all procedural emotion states. |
| **Double Left-Click / Right-Click** | Floating Tchiko Avatar | Opens **Tchiko Settings & System Permissions** (`⚙️`), **Remote Control (Tchiko RC)…**, **Diagnose Clipboard**, or the quick sysadmin context menu. |
| **Drag & Drop (File / Dir / Text)** | Floating Tchiko Avatar | Dropping a `.log`/`.dmp` analyzes crash traces; dropping a script audits it; dropping a directory switches `cwd`. |

---

## 7. Installation, Self-Test & Usage

### 7.1. System Requirements (Ubuntu 22.04 / 24.04 / 25.10)
Tchiko uses Ubuntu's native system `python3-gi` and `python3-cairo` bindings for zero-overhead GTK3 compositing:

```bash
sudo apt update && sudo apt install -y \
    python3 python3-venv python3-gi python3-gi-cairo gir1.2-gtk-3.0 xclip
```

### 7.2. Clone, Verify & Launch

```bash
# 1. Clone the repository
git clone git@github.com:ZYNIQ-SOLUTIONS/Tchiko-Assistant-Sysadmin-companion.git
cd Tchiko-Assistant-Sysadmin-companion

# 2. Run the automated verification suite (ConfigManager, LinuxSystemToolkit, AgentEngine, Cairo SVG pipeline)
python3 main.py --self-test

# 3. Run the unit & integration test suite (including Tchiko RC crypto, sigil & E2E channel tests)
python3 -m unittest discover -s tests -v

# 4. Launch the floating desktop companion
./run_tchiko.sh
```

### 7.3. Command-Line Interface Flags

```bash
python3 main.py --help
# Options:
#   --self-test      Run automated self-tests, verify Linux toolkit, and export canonical SVGs without opening GUI
#   --open-chat      Open the full Tchiko Chat & System Studio window alongside the floating companion on startup
#   --open-settings  Open the Tchiko Settings & RBAC Permissions window on startup
#   --open-remote    Open the Tchiko RC pairing window on startup
#   --remote         Run Tchiko RC in headless server mode without launching the GTK desktop UI
#   --rc-port PORT   TCP port for the Tchiko RC HTTPS/WSS server (default: 8765)
#   --rc-no-tls      Disable TLS in headless --remote mode (only for localhost / reverse-proxy setups)
#   --sigil-out PATH Optional path to write the Tchiko Sigil SVG in --remote mode
```

---

## 8. Built-In Slash Commands & Natural-Language Sysadmin Playbook

| Command / Natural Prompt | Execution Tier | Action Performed |
| :--- | :--- | :--- |
| `/doctor` or *"diagnose my system"* | Tier 1 / Tier 3 | Runs a 5-point Ubuntu health audit (`/proc` CPU/RAM/Disk thresholds, top CPU processes, failed `systemd` units, listening TCP/UDP sockets). |
| *"check why antigravity code ide is crashing and fix it"* | Tier 3 (`diagnose_and_heal_app`) | Runs the 6-step IDE Crash Doctor: resolves binaries/symlinks, inspects `SingletonLock` & `Crashpad`, scans `main.log`/`exthost.log`, audits X.509 `.pem` expiry via `openssl`, and patches `main.js`/`extension.js` with `.bak` backups. |
| *"create an ssh key for my hetzner server in OpenSSH format"* | Tier 3 (SSH Lifecycle) | Generates `~/.ssh/id_ed25519_hetzner` (`-a 100`), sets `0600`/`0644` permissions, backs up any prior key, and auto-copies the `.pub` key to the X11/Wayland clipboard. |
| *"add hetzner server 95.216.10.20 to ssh config user ubuntu"* | Tier 3 (SSH Config) | Appends a `Host hetzner` stanza with `IdentityFile` and `ServerAliveInterval 60` to `~/.ssh/config` (`0600`). |
| *"what is using port 8000"* / *"kill port 3000"* | Tier 3 (Port Doctor) | Inspects listening sockets via `ss -tulnp` / `lsof -i` or reaps processes bound to the target port. |
| *"remember my staging ip is 10.10.0.42"* / `/memory` | Tier 2 (Context Store) | Persists key-value facts into `config/agent_memory.json` and injects them into all subsequent LLM/Antigravity prompts. |
| *"copy it"* / *"retry"* / *"where did you save it?"* | Tier 2 (Follow-Up Resolver) | Copies `last_artifact_content` to clipboard, re-executes `last_command`, or displays `last_artifact_path`. |
| `/sysinfo`, `/procs`, `/files [path]`, `/permissions` | Tier 1 (Slash Router) | Direct zero-latency inspection of `/proc` telemetry, top processes, directory listings, and RBAC state. |
| `/containers [name]`, `/systemd [unit]`, `/net` | Tier 1 (Toolkit) | Inspect Docker/Podman containers & crash logs, failed systemd units & journald logs, listening sockets & UFW/nftables. |
| `/disk`, `/gpu`, `/tls <host>`, `/git [path]` | Tier 1 (Toolkit) | Audit disk/inode usage, NVIDIA/AMD GPU & Ollama/vLLM health, DNS + TLS cert expiry, and Git repo status. |
| `/skills [name]` | Tier 1 (Skills) | List loaded `skills/*.md` runbooks or inspect a specific runbook (auto-matched into ReAct prompts). |
| `/undo`, `/rollback [tx_id\|list]` | Tier 1 (Ledger) | Roll back file patches/writes using pre-edit snapshots stored in `action_ledger.json`. |
| `$ <cmd>` or `/run <cmd>` | Tier 1 (Direct Shell) | Executes `<cmd>` in the agent's persistent working directory (`cwd`) governed by `ConfigManager` policy. |

---

## 9. Security & Permission Governance (`ConfigManager`)

All host interactions in [`LinuxSystemToolkit`](tchiko/system_tools.py) are gated by [`ConfigManager`](tchiko/config_manager.py), which maintains bi-directional synchronization between [`config/settings.json`](config/settings.json) and [`antigravity.yaml`](antigravity.yaml):

- **Master Autonomous Mode (`approve_all_system_permissions: true`)**: Grants full passwordless execution across all 6 capability domains (`bash_execution`, `filesystem_read_write`, `process_management`, `desktop_automation`, `package_management`, `network_requests`) and passes `--dangerously-skip-permissions` to the `agy` CLI bridge.
- **Supervised Review Mode (`tool_execution_policy: "request-review"`)**: Uses `ConfigManager.classify_command()` (`SAFE_READONLY` | `MUTATING_LOCAL` | `PRIVILEGED_DESTRUCTIVE`) so `SAFE_READONLY` diagnostics run smoothly while mutating or privileged commands pause for inline approval (`✅ Run Command` | `🛡️ Always Allow All` | `✖ Cancel`).
- **Snapshot & Rollback Ledger (`/undo`)**: Every `patch_file_content()` and `write_file_content()` records a pre-edit snapshot in `config/snapshots/` and `config/action_ledger.json` for instant `/undo` or `/rollback <tx_id>`.
- **Command Denylist (`command_denylist`)**: Enforces substring & pattern blocking prior to subprocess creation even when autonomous mode is active.

---

## 10. Contributing, Governance & License

Contributions are warmly welcomed! Please review our community & engineering guides before opening a Pull Request:

- **[Contributing Guide (`CONTRIBUTING.md`)](CONTRIBUTING.md)** — Setup, Git workflow, Conventional Commits, and guides for adding tools, emotions, and UI components.
- **[Code of Conduct (`CODE_OF_CONDUCT.md`)](CODE_OF_CONDUCT.md)** — Community standards and enforcement.
- **[Security Policy (`SECURITY.md`)](SECURITY.md)** — RBAC safety model and private vulnerability reporting.
- **[Changelog (`CHANGELOG.md`)](CHANGELOG.md)** — Release history and notable changes.

Released under the **[MIT License](LICENSE)**. Crafted by **ZYNIQ SOLUTIONS** for Linux systems engineers, SREs, and AI agent developers.
