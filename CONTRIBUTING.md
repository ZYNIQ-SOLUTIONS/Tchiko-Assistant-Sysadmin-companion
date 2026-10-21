# Contributing to Tchiko Assistant

Thank you for contributing to **Tchiko Assistant (`Tchiko-Assistant-Sysadmin-companion`)**! This guide covers the engineering workflow for extending Tchiko's autonomous tools, ReAct capabilities, and procedural Cairo animations.

---

## 1. Development Environment Setup

```bash
# 1. Clone the repository
git clone git@github.com:ZYNIQ-SOLUTIONS/Tchiko-Assistant-Sysadmin-companion.git
cd Tchiko-Assistant-Sysadmin-companion

# 2. Run the subsystem self-test
make self-test

# 3. Run the unit & integration test suite
make test
```

---

## 2. Adding a New Autonomous Linux Tool

All host-level capabilities reside in [`tchiko/system_tools.py`](tchiko/system_tools.py) inside [`LinuxSystemToolkit`](tchiko/system_tools.py) and return a strongly-typed [`ToolResult`](tchiko/system_tools.py):

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

### Checklist for Adding a Tool:
1. **Enforce RBAC Permission Gating:** Check `self.config.can_execute_capability("<capability_domain>")` at the top of the method (`bash_execution`, `filesystem_read_write`, `process_management`, `desktop_automation`, `package_management`, or `network_requests`).
2. **Create `.bak` Backups Before Mutating Files:** If modifying existing files, follow the pattern in `patch_file_content()` (`shutil.copy2(target, str(target) + ".bak")`).
3. **Expose in the Multi-Tool ReAct Parser (Optional):** Register the XML tag in `TchikoAgentEngine._extract_tool_actions()` and dispatch it in `TchikoAgentEngine._try_external_llm_with_tools()`.
4. **Add Unit Tests:** Add a test case in [`tests/test_engine_and_tools.py`](tests/test_engine_and_tools.py).

---

## 3. Adding a New Procedural Emotion or Coat Palette

All vector rendering is in [`tchiko/svg_ghost_renderer.py`](tchiko/svg_ghost_renderer.py):
- **New Coat Theme:** Add an RGB tuple dictionary to `THEMES` in `tchiko/svg_ghost_renderer.py`.
- **New Emotion State:** Add the state name to `EMOTION_LIST`, define its spring-jelly target `(target_sx, target_sy)` in `SvgGhostRenderer.step()`, and add any custom particle/aura effects in `_draw_emotion_fx()`.
- **Export Canonical SVGs:** Run `make export-svg` (`python3 main.py --self-test`) to regenerate `assets/tchiko-*.svg` and `landing/assets/tchiko-*.svg`.

---

## 4. Code Style & Documentation Standards

- **Type Annotations:** All functions and methods must include full Python `3.10+` type annotations (`from __future__ import annotations`).
- **Docstrings:** Document module architecture, class responsibilities, thread-safety guarantees, and return types.
- **Verification:** Always verify that both `make self-test` and `make test` pass with exit code `0` before opening a Pull Request.
