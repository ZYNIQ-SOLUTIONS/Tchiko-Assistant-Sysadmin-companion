"""Full-stack end-to-end tests for Tchiko RC (HTTP/HTTPS, WebSocket, E2E encryption, single-connection)."""

from __future__ import annotations

import http.client
import os
import shutil
import ssl
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from tchiko.agent_engine import TchikoAgentEngine
from tchiko.config_manager import ConfigManager
from tchiko.remote.service import RemoteControlService
from tchiko.system_tools import LinuxSystemToolkit

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestRemoteControlE2E(unittest.TestCase):
    """Spins up a real RemoteControlService and exercises HTTP security + live JS TchikoChannel."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmp_dir.name)
        self.cfg_path = self.tmp / "settings.json"
        self.pair_path = self.tmp / "rc_pair.json"
        self.cert_dir = self.tmp / "certs"
        self.config = ConfigManager(config_path=self.cfg_path)
        self.config.set_all_permissions(True)
        self.toolkit = LinuxSystemToolkit(self.config)
        self.engine = TchikoAgentEngine(self.config, self.toolkit)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_http_static_serving_headers_and_path_traversal_protection(self) -> None:
        service = RemoteControlService(
            config=self.config,
            toolkit=self.toolkit,
            engine=self.engine,
            host="127.0.0.1",
            port=0,
            use_tls=False,
            pair_store_path=self.pair_path,
            cert_dir=self.cert_dir,
        )
        port = service.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)

            # Root serves rc/index.html with strict CSP + nosniff + XFO headers
            conn.request("GET", "/")
            resp = conn.getresponse()
            body = resp.read().decode("utf-8")
            self.assertEqual(resp.status, 200)
            self.assertIn("Tchiko RC", body)
            self.assertEqual(resp.getheader("X-Content-Type-Options"), "nosniff")
            self.assertEqual(resp.getheader("X-Frame-Options"), "DENY")
            csp = resp.getheader("Content-Security-Policy") or ""
            self.assertIn("default-src 'self'", csp)
            self.assertIn("frame-ancestors 'none'", csp)

            # JS module served with application/javascript
            conn.request("GET", "/js/app.js")
            resp = conn.getresponse()
            _ = resp.read()
            self.assertEqual(resp.status, 200)
            self.assertIn("javascript", (resp.getheader("Content-Type") or "").lower())

            # Path traversal attempts must be blocked
            for bad_path in ("/../main.py", "/%2e%2e/main.py", "/js/../../main.py"):
                conn.request("GET", bad_path)
                resp = conn.getresponse()
                _ = resp.read()
                self.assertIn(resp.status, (400, 403, 404), f"Expected traversal blocked for {bad_path}, got {resp.status}")

            conn.close()
        finally:
            service.stop()

    def test_tls_self_signed_certificate_and_https_serving(self) -> None:
        service = RemoteControlService(
            config=self.config,
            toolkit=self.toolkit,
            engine=self.engine,
            host="127.0.0.1",
            port=0,
            use_tls=True,
            pair_store_path=self.pair_path,
            cert_dir=self.cert_dir,
        )
        port = service.start()
        try:
            key_path = self.cert_dir / "rc-key.pem"
            cert_path = self.cert_dir / "rc-cert.pem"
            self.assertTrue(key_path.exists())
            self.assertTrue(cert_path.exists())
            # Private key must be owner-only (0600)
            mode = stat.S_IMODE(os.stat(key_path).st_mode)
            self.assertEqual(mode, 0o600)

            ctx = ssl._create_unverified_context()
            conn = http.client.HTTPSConnection("127.0.0.1", port, context=ctx, timeout=5)
            conn.request("GET", "/")
            resp = conn.getresponse()
            body = resp.read().decode("utf-8")
            self.assertEqual(resp.status, 200)
            self.assertIn("Tchiko RC", body)
            conn.close()
        finally:
            service.stop()

    def test_full_stack_js_channel_pairing_encryption_and_single_connection(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")

        moods_received: list[str] = []
        statuses_seen: list[dict] = []

        service = RemoteControlService(
            config=self.config,
            toolkit=self.toolkit,
            engine=self.engine,
            host="127.0.0.1",
            port=0,
            use_tls=False,
            pair_store_path=self.pair_path,
            cert_dir=self.cert_dir,
            on_status_change=lambda snap: statuses_seen.append(dict(snap)),
            on_remote_mood=lambda mood: moods_received.append(mood),
        )
        port = service.start()
        try:
            session = service.new_pairing_session()
            ws_url = f"ws://127.0.0.1:{port}/ws"
            fragment = session.pair_fragment()

            proc = subprocess.run(
                [node, str(PROJECT_ROOT / "tests" / "rc" / "e2e_channel.test.mjs"), ws_url, fragment],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(
                proc.returncode,
                0,
                msg=f"e2e_channel.test.mjs failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
            )
            self.assertIn("ALL E2E CHANNEL TESTS PASSED", proc.stdout)

            # Verify server observed the exact same safety code printed by Client 1
            safety_line = [ln for ln in proc.stdout.splitlines() if ln.startswith("SAFETY_CODE=")]
            self.assertEqual(len(safety_line), 1)
            client_code = safety_line[0].split("=", 1)[1].strip()
            server_codes = {s.get("safety_code") for s in statuses_seen if s.get("connected")}
            self.assertIn(client_code, server_codes)

            # Verify desktop config & mood callbacks received the encrypted remote updates
            self.assertEqual(self.config.data["ghost_widget"]["theme"], "emerald_matrix")
            self.assertEqual(self.config.data["ghost_widget"]["size"], 175)
            self.assertEqual(self.config.data["permissions"]["tool_execution_policy"], "request-review")
            self.assertIn("excited", moods_received)

            # Verify unpair deleted rc_pair.json and disconnected client
            self.assertFalse(self.pair_path.exists())
            snap = service.status_snapshot()
            self.assertFalse(snap["connected"])
            self.assertFalse(snap["paired"])
        finally:
            service.stop()


if __name__ == "__main__":
    unittest.main()
