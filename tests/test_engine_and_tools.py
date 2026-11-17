"""Automated Unit & Integration Test Suite for Tchiko Assistant.

Run with:
    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tchiko.agent_engine import TchikoAgentEngine
from tchiko.config_manager import ConfigManager
from tchiko.svg_ghost_renderer import EMOTION_LIST, SvgGhostRenderer, THEMES
from tchiko.system_tools import LinuxSystemToolkit


class TestTchikoEngineAndTools(unittest.TestCase):
    """Verifies RBAC permissions, LinuxSystemToolkit, ReAct parsing, and Cairo SVG rendering."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.cfg_path = Path(self.tmp_dir.name) / "settings.json"
        self.config = ConfigManager(config_path=self.cfg_path)
        self.config.set_all_permissions(True)
        self.toolkit = LinuxSystemToolkit(self.config)
        self.engine = TchikoAgentEngine(self.config, self.toolkit)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_config_manager_permissions_and_denylist(self) -> None:
        """Verify master permission toggle and denylist enforcement."""
        self.assertTrue(self.config.is_all_permissions_approved())
        ok, _ = self.config.is_command_allowed("echo hello")
        self.assertTrue(ok)

        self.config.data["permissions"]["command_denylist"] = ["rm -rf /"]
        ok_denied, reason = self.config.is_command_allowed("sudo rm -rf /")
        self.assertFalse(ok_denied)
        self.assertIn("denylist", reason)

    def test_view_patch_and_grep_files(self) -> None:
        """Verify file creation, line-numbered viewing, grep search, and atomic .bak patching."""
        sample_file = Path(self.tmp_dir.name) / "sample.js"
        w_res = self.toolkit.write_file_content(
            str(sample_file),
            "const cfg = {nodeOptions:{ca:n}};\nconsole.log('ready');\n",
            create_backup=False,
        )
        self.assertTrue(w_res.ok)

        # 1. View file lines
        v_res = self.toolkit.view_file_lines(str(sample_file), 1, 2)
        self.assertTrue(v_res.ok)
        self.assertIn("1: const cfg = {nodeOptions:{ca:n}};", v_res.output)

        # 2. Grep pattern
        g_res = self.toolkit.grep_files("nodeOptions:{ca:n}", str(sample_file))
        self.assertTrue(g_res.ok)
        self.assertIn("nodeOptions:{ca:n}", g_res.output)

        # 3. Patch file content with .bak backup
        p_res = self.toolkit.patch_file_content(
            str(sample_file),
            "nodeOptions:{ca:n}",
            "nodeOptions:{ca:n,rejectUnauthorized:!1}",
            create_backup=True,
        )
        self.assertTrue(p_res.ok)
        self.assertTrue(Path(str(sample_file) + ".bak").exists())
        self.assertIn("rejectUnauthorized:!1", sample_file.read_text(encoding="utf-8"))

        # 4. Idempotent re-patch check
        p_res2 = self.toolkit.patch_file_content(
            str(sample_file),
            "nodeOptions:{ca:n}",
            "nodeOptions:{ca:n,rejectUnauthorized:!1}",
            create_backup=True,
        )
        self.assertTrue(p_res2.ok)
        self.assertIn("already", p_res2.output.lower())

    def test_think_stripping_and_multi_tool_extraction(self) -> None:
        """Verify <think> blocks and placeholder <bash>COMMAND</bash> tags never leak into execution."""
        raw_llm = (
            "<think>\n"
            "The prompt says to wrap commands in <bash>COMMAND</bash>.\n"
            "Let's first read the log file.\n"
            "</think>\n"
            "Inspecting the log file and checking kernel version:\n"
            '<view_file path="/var/log/syslog" start="1" end="40" />\n'
            '<grep pattern="ConnectError" path="/tmp" />\n'
            '<patch_file path="/tmp/a.js"><search>old()</search><replace>new()</replace></patch_file>\n'
            "<bash>COMMAND</bash>\n"
            "<bash>uname -s</bash>"
        )
        clean, thoughts = self.engine._strip_think_blocks(raw_llm)
        self.assertEqual(len(thoughts), 1)
        self.assertNotIn("<think>", clean)

        actions = self.engine._extract_tool_actions(clean)
        self.assertEqual([a["tool"] for a in actions], ["view_file", "grep", "patch_file", "bash"])
        self.assertEqual(actions[-1]["command"], "uname -s")

    def test_first_turn_briefing_and_path_resolution(self) -> None:
        """The first request carries persona, machine facts, notes, rules; paths expand $HOME and anchor to cwd."""
        import os

        self.config.data.setdefault("agent", {})["system_instructions"] = "You are Tchiko."
        self.engine.memory["notes"] = {"hetzner ip": "95.216.10.20"}
        self.engine.memory["cwd"] = self.tmp_dir.name
        self.engine.memory["history"] = [
            {"role": "user", "content": "earlier question"},
            {"role": "user", "content": "current request"},
        ]
        brief = self.engine._build_context_brief()
        self.assertIn("You are Tchiko.", brief)
        self.assertIn("This machine:", brief)
        self.assertIn("95.216.10.20", brief)
        self.assertIn("earlier question", brief)
        self.assertNotIn("current request", brief)
        self.assertIn("never invent", brief)

        self.assertEqual(self.engine._resolve_user_path("$HOME/.zshrc"), os.path.expanduser("~/.zshrc"))
        self.assertEqual(self.engine._resolve_user_path("notes.txt"), os.path.join(self.tmp_dir.name, "notes.txt"))

    def test_direct_shell_detection_and_model_choice(self) -> None:
        """Only unmistakable commands skip the AI; model choice ignores embedding/speech-first listings."""
        looks = TchikoAgentEngine._looks_like_direct_shell_command
        for cmd in ("df -h", "git status", "ls", "docker ps -a", "ping 1.1.1.1", "cat /etc/os-release"):
            self.assertTrue(looks(cmd), cmd)
        for text in (
            "find me a good text editor",
            "which python version should I use?",
            "git is broken please help",
            "free up some disk space",
            "install vllm",
        ):
            self.assertFalse(looks(text), text)

        gb = 1024**3
        models = [
            {"name": "tiny-audio:2b", "size": 2 * gb, "capabilities": ["completion", "audio"]},
            {"name": "nomic-embed-text:latest", "size": gb // 4, "capabilities": ["embedding"]},
            {"name": "huge:70b", "size": 45 * gb, "capabilities": ["completion", "tools"]},
            {"name": "mid:14b", "size": 9 * gb, "capabilities": ["completion", "tools"]},
        ]
        pick = TchikoAgentEngine._pick_ollama_model
        self.assertEqual(pick(models), "mid:14b")
        self.assertEqual(pick(models, "huge:70b"), "huge:70b")
        self.assertEqual(pick(models + [{"name": "gemma4:e4b", "size": 8 * gb}]), "gemma4:e4b")
        self.assertIsNone(pick([models[1]]))

    def test_keyword_routes_do_not_hijack_agent_requests(self) -> None:
        """Requests that merely mention ssh/claude/diagnose must fall through to the AI agent untouched."""
        import asyncio

        calls = []
        noop = lambda *a, **k: None  # noqa: E731
        self.engine.toolkit.run_shell_command = lambda cmd, *a, **k: calls.append(cmd) or type(  # type: ignore
            "R", (), {"ok": False, "output": "", "title": "", "exit_code": 1, "duration_ms": 0}
        )()
        for text in (
            "why can't I ssh into my new hetzner server",
            "update my claude code config to use the new model",
            "diagnose why nginx keeps returning 502 on the staging box after deploys today",
            "update the readme",
        ):
            handled = asyncio.run(
                self.engine._try_autonomous_linux_action(text, noop, noop, noop, noop, noop, None)
            )
            self.assertFalse(handled, text)
        self.assertFalse(any("ssh-keygen" in c or "apt-get" in c for c in calls))

    def test_markdown_rendering_is_always_valid_pango(self) -> None:
        """Replies (even half-streamed or hostile ones) must render to parseable Pango markup."""
        import gi

        gi.require_version("Pango", "1.0")
        from gi.repository import Pango

        from tchiko import ui_theme as ui

        reply = (
            "<think>secret plan</think>## Done & dusted\n- **bold** and `code <tag>` and *soft*\n"
            "1. [docs](https://example.com/a?b=1&c=2)\n> note\n\n```bash\necho \"<hi>\" && ls\n```\ntail **unclosed"
        )
        blocks = ui.split_markdown_blocks(reply)
        self.assertEqual([kind for kind, _c, _l in blocks], ["text", "code", "text"])
        self.assertEqual(blocks[1][1], 'echo "<hi>" && ls')
        self.assertEqual(blocks[1][2], "bash")
        self.assertEqual(ui.first_code_block(reply), 'echo "<hi>" && ls')

        for partial in (reply, reply[:40], reply[:95], "```python\nprint(1", "plain <b>not markup</b> & more"):
            for markup in (ui.streaming_markup(partial), ui.streaming_markup(partial, compact=True)):
                # <a href> is a GtkLabel extension on top of Pango markup; check the rest strictly.
                pango_only = re.sub(r"</?a\b[^>]*>", "", markup)
                ok, _attrs, text, _accel = Pango.parse_markup(pango_only, -1, "\x00")
                self.assertTrue(ok)
                self.assertNotIn("secret plan", text)
        self.assertIn("<b>bold</b>", ui.markdown_to_pango(reply))
        self.assertIn('href="https://example.com/a?b=1&amp;c=2"', ui.markdown_to_pango(reply))

    def test_svg_ghost_renderer_physics_and_svg_export(self) -> None:
        """Verify procedural Cairo rendering across emotions and themes."""
        renderer = SvgGhostRenderer()
        for emotion in EMOTION_LIST:
            renderer.set_emotion(emotion, duration=2.0)
            renderer.step(0.1)
        for theme_key in THEMES:
            svg_out = Path(self.tmp_dir.name) / f"test_{theme_key}.svg"
            renderer.export_to_svg(str(svg_out), width=240, height=240, theme_name=theme_key)
            self.assertTrue(svg_out.exists())
            self.assertGreater(svg_out.stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
