# Security Policy

## Supported Versions

| Version | Supported |
| :--- | :--- |
| `2.0.x` (latest release & `main`) | ✅ Active support & security fixes |
| `< 2.0.0` | ❌ Please upgrade to the latest release |

---

## Security Architecture & Safe Defaults

**Tchiko Assistant** is an autonomous Linux systems engineering agent capable of executing shell commands, patching files, managing SSH keys, and inspecting `/proc` telemetry. Because of this power, security is enforced across multiple layers:

1. **RBAC Capability Gating (`ConfigManager`)**:
   All host operations in [`LinuxSystemToolkit`](tchiko/system_tools.py) are gated by six explicit capability domains in `config/settings.json` (`bash_execution`, `filesystem_read_write`, `process_management`, `desktop_automation`, `package_management`, `network_requests`).
2. **Supervised vs. Autonomous Mode**:
   - Set `approve_all_system_permissions: false` and `tool_execution_policy: "request-review"` in `config/settings.json` (or via the **Settings** window) to require explicit user confirmation before any shell command or file mutation runs.
   - Autonomous mode (`--dangerously-skip-permissions` when invoking `agy`) should only be enabled on trusted personal workstations.
3. **Command Denylist (`command_denylist`)**:
   Substrings/patterns listed in `permissions.command_denylist` are blocked prior to subprocess execution, even when autonomous mode is enabled.
4. **Atomic `.bak` Backups**:
   File mutations via `patch_file_content()` and `write_file_content()` create `<filename>.bak` backups before writing changes.
5. **Prompt & `<think>` Sanitization**:
   `TchikoAgentEngine._strip_think_blocks()` strips internal `<think>...</think>` reasoning blocks before tool extraction so model reasoning examples never execute as host commands.

---

## Tchiko RC Transport & Pairing Security (`tchiko/remote/`, `rc/`)

When **Tchiko RC** is enabled, remote sessions are protected by a zero-trust, single-device encrypted protocol:

1. **Ephemeral Mutual Handshake (`ECDH P-256 + HKDF-SHA256 + HMAC-SHA256`)**:
   - Every WebSocket connection negotiates fresh ephemeral NIST P-256 keys, validates peer curve points, and derives directional keys via HKDF-SHA256 over the full handshake transcript.
   - Mutual HMAC-SHA256 proofs verify both endpoints before any application payload is accepted.
2. **Authenticated Framing (`AES-256-GCM`)**:
   - Every message is encrypted with AES-256-GCM and bound to a strict monotonic 64-bit per-direction counter. Replayed, reordered, dropped, or tampered frames immediately close the connection.
3. **One-Time Tchiko Sigil & Visual Safety Code**:
   - Optical Sigil sessions carry a 12-byte one-time pairing secret, expire after **120 seconds**, and are burned immediately upon pairing.
   - Both desktop and remote UI display a **6-digit Safety Code** derived from the session transcript to detect MITM attacks on local TLS self-signed certificates.
4. **Single Active Client & Credential Hygiene**:
   - Strictly **one** remote client can be active at a time; authenticating a new session evicts any previous client (`4009`).
   - Paired device credentials in `config/rc_pair.json` and TLS private keys in `~/.config/tchiko/rc-key.pem` are written with `0600` file permissions.
5. **HTTP & Handshake Hardening**:
   - Static web assets are served with `Content-Security-Policy: default-src 'self'`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, WebSocket `Origin` validation, and IP-scoped failure rate limiting (`12` failures per `60s`).
   - Headless `--rc-no-tls` should only be used behind a trusted TLS-terminating reverse proxy or bound to localhost.

---

## Reporting a Vulnerability

**Please do NOT open a public GitHub issue for security vulnerabilities.**

If you discover a security issue (e.g., command-injection bypass, denylist evasion, privilege escalation, or credential leakage), please report it privately:

- **Email:** `contact@zyniq.studio`
- **GitHub Security Advisories:** Use the repository's **Security → Advisories → Report a vulnerability** tab if enabled.

Please include:
1. A clear description of the vulnerability and its potential impact.
2. Step-by-step reproduction instructions or a minimal proof-of-concept.
3. Your environment details (Ubuntu version, Python version, `agy`/LLM backend).

We aim to acknowledge reports within **48 hours** and provide a remediation plan or patch as quickly as possible.
