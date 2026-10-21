"""Automated Unit & Integration Test Suite for Tchiko Assistant.

Run with:
    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

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
