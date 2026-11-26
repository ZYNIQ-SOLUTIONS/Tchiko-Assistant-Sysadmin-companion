"""Integration tests for Tchiko RC Experiences, Clarification, and Learning settings protocol."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List

from tchiko.agent_engine import TchikoAgentEngine
from tchiko.config_manager import ConfigManager
from tchiko.remote.service import RemoteControlService
from tchiko.system_tools import LinuxSystemToolkit


class _FakeClient:
    """Minimal ActiveClient double for testing RemoteControlService message dispatch."""

    def __init__(self) -> None:
        self.safety_code = "123-456"
        self.device_name = "Test Browser"


class TestRemoteExperiencesProtocol(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmp_dir.name)
        self.cfg_path = self.tmp / "settings.json"
        self.exp_dir = self.tmp / "experiences"
        self.config = ConfigManager(config_path=self.cfg_path)
        self.config.set_all_permissions(True)
        self.toolkit = LinuxSystemToolkit(self.config)
        self.engine = TchikoAgentEngine(self.config, self.toolkit, experiences_dir=self.exp_dir)
        self.service = RemoteControlService(
            config=self.config,
            toolkit=self.toolkit,
            engine=self.engine,
            host="127.0.0.1",
            port=0,
            use_tls=False,
            pair_store_path=self.tmp / "rc_pair.json",
            cert_dir=self.tmp / "certs",
        )
        self.sent: List[Dict[str, Any]] = []

        async def _capture_send(_client: Any, msg: Dict[str, Any]) -> None:
            self.sent.append(msg)

        self.service._send_encrypted = _capture_send  # type: ignore[method-assign]
        self.client = _FakeClient()

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_state_sync_includes_experiences_learning_metrics_and_learning_config(self) -> None:
        sync = self.service._build_state_sync(self.client)  # type: ignore[arg-type]
        self.assertIn("experiences", sync)
        self.assertIn("learning_metrics", sync)
        self.assertGreaterEqual(len(sync["experiences"]), 3)
        self.assertIn("learning", sync["config"])
        self.assertTrue(sync["config"]["learning"].get("auto_learn_experiences", True))
        # Ensure script source & history are bundled for inspector
        first = sync["experiences"][0]
        self.assertIn("title", first)
        self.assertIn("code", first)
        self.assertTrue(len(first["code"]) > 50)

    def test_experiences_list_test_toggle_learn_and_delete_commands(self) -> None:
        async def _run() -> None:
            # 1. experiences_list
            await self.service._dispatch_client_message(self.client, {"type": "experiences_list"})  # type: ignore[arg-type]
            self.assertEqual(self.sent[-1]["type"], "experiences_sync")
            self.assertGreaterEqual(len(self.sent[-1]["experiences"]), 3)

            # 2. experience_test (dry-run)
            await self.service._dispatch_client_message(
                self.client,  # type: ignore[arg-type]
                {"type": "experience_test", "slug": "disk-space-auditor"},
            )
            results = [m for m in self.sent if m["type"] == "experience_result"]
            self.assertTrue(results and results[-1]["ok"] is True)
            self.assertTrue(results[-1]["dry_run"] is True)

            # 3. experience_toggle
            await self.service._dispatch_client_message(
                self.client,  # type: ignore[arg-type]
                {"type": "experience_toggle", "slug": "disk-space-auditor", "enabled": False},
            )
            exp = self.engine.experiences.get_experience("disk-space-auditor")
            assert exp is not None
            self.assertFalse(exp.enabled)

            # 4. experience_learn from last_episode
            self.engine.last_episode = {
                "prompt": "inspect hostname and kernel release",
                "steps": [
                    {"tool": "bash", "args_summary": "hostname", "ok": True},
                    {"tool": "bash", "args_summary": "uname -r", "ok": True},
                ],
                "succeeded": True,
                "verified": True,
                "recoveries_succeeded": 0,
            }
            await self.service._dispatch_client_message(
                self.client,  # type: ignore[arg-type]
                {"type": "experience_learn", "name": "rc-host-probe"},
            )
            self.assertIsNotNone(self.engine.experiences.get_experience("rc-host-probe"))

            # 5. experience_delete
            await self.service._dispatch_client_message(
                self.client,  # type: ignore[arg-type]
                {"type": "experience_delete", "slug": "rc-host-probe"},
            )
            self.assertIsNone(self.engine.experiences.get_experience("rc-host-probe"))

        asyncio.run(_run())

    def test_update_config_learning_patch_persists(self) -> None:
        async def _run() -> None:
            await self.service._dispatch_client_message(
                self.client,  # type: ignore[arg-type]
                {
                    "type": "update_config",
                    "patch": {
                        "learning": {
                            "ask_before_ambiguous": False,
                            "auto_learn_experiences": False,
                            "auto_promote_verified": True,
                            "auto_rollback_on_failure": False,
                        }
                    },
                },
            )

        asyncio.run(_run())
        learn = self.config.data.get("learning", {})
        self.assertFalse(learn["ask_before_ambiguous"])
        self.assertFalse(learn["auto_learn_experiences"])
        self.assertTrue(learn["auto_promote_verified"])
        self.assertFalse(learn["auto_rollback_on_failure"])


if __name__ == "__main__":
    unittest.main()
