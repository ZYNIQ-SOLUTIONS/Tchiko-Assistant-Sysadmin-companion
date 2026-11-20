"""Tchiko RC service (`tchiko/remote/service.py`).

Runs the encrypted single-connection remote-control bridge on a dedicated asyncio thread:

- Generates short-lived, single-use Tchiko Sigil pairing sessions (120 s TTL, burned on pair).
- Persists at most one paired device credential in `config/rc_pair.json` (mode `0600`) so the
  paired browser reconnects automatically without re-scanning. Pairing a new device revokes the old.
- Enforces **strictly one active authenticated connection** at a time.
- Bridges every Tchiko Desktop capability over the AES-256-GCM `SecureChannel`:
  chat streaming, inline command approvals, live CPU/RAM/Disk telemetry, activity timeline,
  all Settings (access, capabilities, policies, model, companion coat/size/opacity/behaviour),
  and mascot moods.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import socket
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

from ..agent_engine import TchikoAgentEngine
from ..config_manager import ConfigManager, PROJECT_ROOT
from ..system_tools import LinuxSystemToolkit
from . import PROTOCOL_VERSION
from .crypto import (
    CryptoError,
    DIR_CLIENT_TO_SERVER,
    DIR_SERVER_TO_CLIENT,
    EcdhKeyPair,
    SecureChannel,
    b64u_decode,
    b64u_encode,
    derive_session_keys,
    proof,
    safety_code,
    transcript_hash,
)
from .server import RemoteHttpWsServer, WebSocketClosed, WebSocketConnection
from .sigil import SigilPayload, render_svg

PAIR_TTL_SEC = 120.0
MAX_PENDING_HANDSHAKES = 4
HANDSHAKE_TIMEOUT_SEC = 15.0
RATE_WINDOW_SEC = 60.0
RATE_MAX_FAILURES = 12
MAX_ACTIVITY_LOG = 300
DEFAULT_RC_PORT = 8765


@dataclass
class PairingSession:
    payload: SigilPayload
    created_at: float
    expires_at: float
    used: bool = False

    @property
    def remaining_sec(self) -> float:
        return max(0.0, self.expires_at - time.monotonic())

    @property
    def active(self) -> bool:
        return not self.used and time.monotonic() < self.expires_at

    def svg(self, size: int = 340) -> str:
        return render_svg(self.payload.codeword(), size=size, with_card=True)

    def pair_fragment(self) -> str:
        return b64u_encode(self.payload.payload_bytes())


@dataclass
class ActiveClient:
    ws: WebSocketConnection
    channel: SecureChannel
    device_id: str
    device_name: str
    safety_code: str
    connected_at: float
    peer_ip: str
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class RemoteControlService:
    """Thread-safe controller owning the HTTPS/WSS server, pairing state, and engine bridge."""

    def __init__(
        self,
        config: ConfigManager,
        toolkit: LinuxSystemToolkit,
        engine: TchikoAgentEngine,
        host: str = "0.0.0.0",
        port: int = DEFAULT_RC_PORT,
        use_tls: bool = True,
        static_dir: Optional[Path] = None,
        pair_store_path: Optional[Path] = None,
        cert_dir: Optional[Path] = None,
        on_status_change: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_remote_mood: Optional[Callable[[str], None]] = None,
        on_remote_prompt_mirror: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self.config = config
        self.toolkit = toolkit
        self.engine = engine
        self.host = host
        self.port = port
        self.use_tls = use_tls
        self.static_dir = static_dir or (PROJECT_ROOT / "rc")
        self.pair_store_path = pair_store_path or (PROJECT_ROOT / "config" / "rc_pair.json")
        self.cert_dir = cert_dir or (Path.home() / ".config" / "tchiko")

        self._on_status_change = on_status_change
        self._on_remote_mood = on_remote_mood
        self._on_remote_prompt_mirror = on_remote_prompt_mirror

        self._lock = threading.RLock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready_event = threading.Event()
        self._start_error: Optional[BaseException] = None
        self._server: Optional[RemoteHttpWsServer] = None

        self._pairing: Optional[PairingSession] = None
        self._paired_device: Optional[Dict[str, Any]] = self._load_paired_device()
        self._active: Optional[ActiveClient] = None
        self._pending_handshakes = 0
        self._auth_failures: Dict[str, List[float]] = {}

        # Shared agent runtime state visible to the remote client.
        self._agent_status = "idle"
        self._agent_mood = "idle"
        self._activity: Deque[Dict[str, str]] = deque(maxlen=MAX_ACTIVITY_LOG)
        self._pending_approvals: Dict[str, Tuple[str, Callable[[], None], Callable[[], None]]] = {}
        self._busy = False
        self._reply_started = 0.0
        self._reply_tools = 0
        self._telemetry_task: Optional[asyncio.Task[Any]] = None

        self.config.subscribe(self._on_config_changed)

    # ── Lifecycle ────────────────────────────────────────────────────────────
    def start(self) -> int:
        """Start the HTTPS/WSS server in a background daemon thread; returns the bound port."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return self.bound_port
            self._ready_event.clear()
            self._start_error = None
            self._thread = threading.Thread(target=self._run_loop, name="tchiko-rc", daemon=True)
            self._thread.start()

        self._ready_event.wait(timeout=15.0)
        if self._start_error is not None:
            raise self._start_error
        return self.bound_port

    def stop(self) -> None:
        """Cleanly shut down active connection, tasks, and the asyncio loop."""
        loop = self._loop
        if loop is not None and loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(self._shutdown_async(), loop)
            try:
                fut.result(timeout=5.0)
            except Exception:
                pass
            loop.call_soon_threadsafe(loop.stop)
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._loop = None
        self._thread = None

    @property
    def bound_port(self) -> int:
        return self._server.bound_port if self._server is not None else self.port

    def urls(self) -> List[str]:
        if self._server is not None:
            return self._server.urls()
        scheme = "https" if self.use_tls else "http"
        return [f"{scheme}://localhost:{self.port}"]

    def primary_url(self) -> str:
        all_urls = self.urls()
        return all_urls[0] if all_urls else f"https://localhost:{self.bound_port}"

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            self._server = RemoteHttpWsServer(
                static_dir=self.static_dir,
                ws_handler=self._handle_ws,
                host=self.host,
                port=self.port,
                cert_dir=self.cert_dir,
                use_tls=self.use_tls,
            )
            loop.run_until_complete(self._server.start())
            self._telemetry_task = loop.create_task(self._telemetry_loop())
        except BaseException as exc:
            self._start_error = exc
            self._ready_event.set()
            loop.close()
            return
        self._ready_event.set()
        try:
            loop.run_forever()
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()

    async def _shutdown_async(self) -> None:
        if self._telemetry_task is not None:
            self._telemetry_task.cancel()
            self._telemetry_task = None
        active = self._active
        self._active = None
        if active is not None:
            await active.ws.close(1001, "Server shutting down")
        if self._server is not None:
            await self._server.stop()

    # ── Pairing state ────────────────────────────────────────────────────────
    def new_pairing_session(self, ttl_sec: float = PAIR_TTL_SEC) -> PairingSession:
        """Create a fresh one-time Tchiko Sigil pairing session."""
        now = time.monotonic()
        session = PairingSession(
            payload=SigilPayload.generate(),
            created_at=now,
            expires_at=now + ttl_sec,
            used=False,
        )
        with self._lock:
            self._pairing = session
        self._emit_status()
        return session

    def get_or_create_pairing(self) -> PairingSession:
        with self._lock:
            if self._pairing is not None and self._pairing.active:
                return self._pairing
        return self.new_pairing_session()

    def status_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            active = self._active
            paired = self._paired_device
            pairing = self._pairing
            return {
                "running": self._server is not None,
                "urls": self.urls(),
                "primary_url": self.primary_url(),
                "connected": active is not None,
                "device_name": active.device_name if active else (paired.get("device_name") if paired else ""),
                "device_id": active.device_id if active else (paired.get("device_id") if paired else ""),
                "peer_ip": active.peer_ip if active else "",
                "safety_code": active.safety_code if active else "",
                "paired": paired is not None,
                "pairing_active": bool(pairing and pairing.active),
                "pairing_remaining": round(pairing.remaining_sec, 1) if pairing else 0.0,
            }

    def disconnect_active(self, reason: str = "Disconnected by desktop") -> None:
        """Disconnect the currently connected remote client (keeps paired credential)."""
        loop = self._loop
        if loop is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(self._disconnect_active_async(reason), loop)

    def revoke_pairing(self) -> None:
        """Revoke the paired device credential and terminate any active remote connection."""
        with self._lock:
            self._paired_device = None
            self._pairing = None
            try:
                if self.pair_store_path.exists():
                    self.pair_store_path.unlink()
            except OSError:
                pass
        self.disconnect_active("Device unpaired from desktop")
        self._emit_status()

    async def _disconnect_active_async(self, reason: str) -> None:
        with self._lock:
            active = self._active
            self._active = None
        if active is not None:
            try:
                await self._send_encrypted(active, {"type": "kicked", "reason": reason})
            except Exception:
                pass
            await active.ws.close(4008, reason)
            self._emit_status()

    def _load_paired_device(self) -> Optional[Dict[str, Any]]:
        if not self.pair_store_path.exists():
            return None
        try:
            data = json.loads(self.pair_store_path.read_text(encoding="utf-8"))
            if (
                isinstance(data, dict)
                and isinstance(data.get("device_id"), str)
                and isinstance(data.get("resume_secret"), str)
            ):
                return data
        except Exception:
            pass
        return None

    def _save_paired_device(self, record: Dict[str, Any]) -> None:
        self.pair_store_path.parent.mkdir(parents=True, exist_ok=True)
        self.pair_store_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        try:
            os.chmod(self.pair_store_path, 0o600)
        except OSError:
            pass

    def _emit_status(self) -> None:
        if self._on_status_change is not None:
            try:
                self._on_status_change(self.status_snapshot())
            except Exception:
                pass

    # ── Desktop -> RC event mirroring ────────────────────────────────────────
    def notify_watchdog_alert(self, message: str) -> None:
        self._schedule_send({"type": "watchdog_alert", "message": message})

    def notify_desktop_prompt(self, prompt: str) -> None:
        self._schedule_send({"type": "chat_user", "text": prompt, "source": "desktop", "ts": _now_hm()})

    def notify_desktop_event(self, payload: Dict[str, Any]) -> None:
        self._schedule_send(payload)

    def _on_config_changed(self, data: Dict[str, Any]) -> None:
        self._schedule_send({"type": "config_updated", "config": self._public_config(data)})

    def _schedule_send(self, message: Dict[str, Any]) -> None:
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        with self._lock:
            active = self._active
        if active is None:
            return
        asyncio.run_coroutine_threadsafe(self._send_encrypted(active, message), loop)

    # ── Rate limiting ────────────────────────────────────────────────────────
    def _is_rate_limited(self, ip: str) -> bool:
        now = time.monotonic()
        with self._lock:
            times = [t for t in self._auth_failures.get(ip, []) if now - t < RATE_WINDOW_SEC]
            self._auth_failures[ip] = times
            return len(times) >= RATE_MAX_FAILURES

    def _record_failure(self, ip: str) -> None:
        now = time.monotonic()
        with self._lock:
            times = [t for t in self._auth_failures.get(ip, []) if now - t < RATE_WINDOW_SEC]
            times.append(now)
            self._auth_failures[ip] = times

    # ── WebSocket handshake & session loop ───────────────────────────────────
    async def _handle_ws(self, ws: WebSocketConnection) -> None:
        peer_ip = ws.peer[0]
        if self._is_rate_limited(peer_ip):
            await ws.close(4029, "Too many authentication attempts")
            return

        with self._lock:
            if self._pending_handshakes >= MAX_PENDING_HANDSHAKES:
                await ws.close(4029, "Server busy")
                return
            self._pending_handshakes += 1

        client: Optional[ActiveClient] = None
        try:
            client = await self._authenticate(ws, peer_ip)
        except WebSocketClosed:
            return
        except Exception:
            await ws.close(4001, "Handshake error")
            return
        finally:
            with self._lock:
                self._pending_handshakes = max(0, self._pending_handshakes - 1)

        if client is None:
            return

        # Enforce strictly ONE active connection: evict any previous session cleanly.
        previous: Optional[ActiveClient] = None
        with self._lock:
            previous = self._active
            self._active = client
        if previous is not None and previous is not client:
            try:
                await self._send_encrypted(
                    previous,
                    {"type": "replaced", "reason": f"Replaced by new connection from {client.device_name}"},
                )
            except Exception:
                pass
            await previous.ws.close(4009, "Replaced by new connection")

        self._emit_status()

        try:
            await self._send_encrypted(client, self._build_state_sync(client))
            while not ws.closed:
                kind, raw = await ws.recv()
                if kind != "binary" or not isinstance(raw, bytes):
                    await ws.close(1003, "Encrypted binary frames required")
                    break
                try:
                    plain = client.channel.open(raw)
                    msg = json.loads(plain.decode("utf-8"))
                except (CryptoError, ValueError, UnicodeDecodeError):
                    await ws.close(4002, "Channel integrity failure")
                    break
                if isinstance(msg, dict):
                    await self._dispatch_client_message(client, msg)
        except WebSocketClosed:
            pass
        finally:
            with self._lock:
                if self._active is client:
                    self._active = None
            self._emit_status()

    async def _authenticate(self, ws: WebSocketConnection, peer_ip: str) -> Optional[ActiveClient]:
        server_kp = EcdhKeyPair()
        server_nonce = secrets.token_bytes(16)
        hostname = socket.gethostname()

        await ws.send_text(
            json.dumps(
                {
                    "type": "hello",
                    "v": PROTOCOL_VERSION,
                    "host": hostname,
                    "server_pub": b64u_encode(server_kp.public_raw),
                    "server_nonce": b64u_encode(server_nonce),
                }
            )
        )

        try:
            kind, raw = await asyncio.wait_for(ws.recv(), timeout=HANDSHAKE_TIMEOUT_SEC)
        except asyncio.TimeoutError:
            await ws.close(4008, "Handshake timed out")
            return None

        if kind != "text" or not isinstance(raw, str):
            self._record_failure(peer_ip)
            await ws.close(4001, "Expected JSON auth frame")
            return None

        try:
            auth = json.loads(raw)
            if not isinstance(auth, dict) or auth.get("type") != "auth":
                raise CryptoError("invalid auth message")
            mode = auth.get("mode")
            client_pub = b64u_decode(auth.get("client_pub", ""))
            client_nonce = b64u_decode(auth.get("client_nonce", ""))
            client_proof = b64u_decode(auth.get("proof", ""))
            if len(client_nonce) != 16 or len(client_proof) != 32:
                raise CryptoError("invalid nonce or proof size")
            device_name = str(auth.get("device_name") or "Remote Browser").strip()[:60] or "Remote Browser"
        except (ValueError, CryptoError):
            self._record_failure(peer_ip)
            await ws.send_text(json.dumps({"type": "auth_error", "code": "malformed", "message": "Malformed auth request"}))
            await ws.close(4001, "Malformed auth")
            return None

        new_pair_record: Optional[Dict[str, Any]] = None
        if mode == "pair":
            try:
                session_bytes = b64u_decode(auth.get("session_id", ""))
            except CryptoError:
                session_bytes = b""

            with self._lock:
                pairing = self._pairing
                valid_pairing = (
                    pairing is not None
                    and pairing.active
                    and len(session_bytes) == 3
                    and pairing.payload.session_bytes == session_bytes
                )
                secret = pairing.payload.secret if valid_pairing and pairing is not None else b""

            if not valid_pairing:
                self._record_failure(peer_ip)
                await ws.send_text(
                    json.dumps(
                        {
                            "type": "auth_error",
                            "code": "expired",
                            "message": "This Tchiko Sigil has expired or was already used. Refresh it on the desktop.",
                        }
                    )
                )
                await ws.close(4003, "Sigil expired")
                return None

            context = b"pair:" + session_bytes
            try:
                shared = server_kp.shared_secret(client_pub)
            except CryptoError:
                self._record_failure(peer_ip)
                await ws.send_text(json.dumps({"type": "auth_error", "code": "bad_key", "message": "Invalid client key"}))
                await ws.close(4001, "Invalid key")
                return None

            th = transcript_hash(context, client_pub, server_kp.public_raw, client_nonce, server_nonce)
            c2s_key, s2c_key, confirm_key = derive_session_keys(shared, secret, th)
            expected = proof(confirm_key, b"client", th)
            if not secrets.compare_digest(client_proof, expected):
                self._record_failure(peer_ip)
                await ws.send_text(json.dumps({"type": "auth_error", "code": "invalid_proof", "message": "Invalid pairing proof"}))
                await ws.close(4003, "Invalid proof")
                return None

            # Burn the one-time sigil atomically and mint a fresh resume credential.
            with self._lock:
                if self._pairing is None or not self._pairing.active or self._pairing.payload.session_bytes != session_bytes:
                    await ws.send_text(json.dumps({"type": "auth_error", "code": "expired", "message": "Sigil already used"}))
                    await ws.close(4003, "Sigil used")
                    return None
                self._pairing.used = True
                device_id_bytes = secrets.token_bytes(8)
                resume_secret_bytes = secrets.token_bytes(32)
                device_id = b64u_encode(device_id_bytes)
                new_pair_record = {
                    "device_id": device_id,
                    "device_name": device_name,
                    "resume_secret": b64u_encode(resume_secret_bytes),
                    "paired_at": time.time(),
                    "last_seen": time.time(),
                }
                self._paired_device = new_pair_record
                self._save_paired_device(new_pair_record)

        elif mode == "resume":
            try:
                device_id_raw = str(auth.get("device_id", ""))
                device_id_bytes = b64u_decode(device_id_raw)
            except CryptoError:
                device_id_raw = ""
                device_id_bytes = b""

            with self._lock:
                paired = self._paired_device
                valid_device = (
                    paired is not None
                    and secrets.compare_digest(str(paired.get("device_id", "")), device_id_raw)
                    and len(device_id_bytes) == 8
                )
                secret = b64u_decode(paired["resume_secret"]) if valid_device and paired is not None else b""

            if not valid_device:
                self._record_failure(peer_ip)
                await ws.send_text(
                    json.dumps(
                        {
                            "type": "auth_error",
                            "code": "unpaired",
                            "message": "This device is no longer paired. Scan a new Tchiko Sigil on the desktop.",
                        }
                    )
                )
                await ws.close(4003, "Device unpaired")
                return None

            context = b"resume:" + device_id_bytes
            try:
                shared = server_kp.shared_secret(client_pub)
            except CryptoError:
                self._record_failure(peer_ip)
                await ws.send_text(json.dumps({"type": "auth_error", "code": "bad_key", "message": "Invalid client key"}))
                await ws.close(4001, "Invalid key")
                return None

            th = transcript_hash(context, client_pub, server_kp.public_raw, client_nonce, server_nonce)
            c2s_key, s2c_key, confirm_key = derive_session_keys(shared, secret, th)
            expected = proof(confirm_key, b"client", th)
            if not secrets.compare_digest(client_proof, expected):
                self._record_failure(peer_ip)
                await ws.send_text(
                    json.dumps(
                        {
                            "type": "auth_error",
                            "code": "unpaired",
                            "message": "Saved pairing credentials no longer match. Scan a new Tchiko Sigil.",
                        }
                    )
                )
                await ws.close(4003, "Resume proof failed")
                return None

            device_id = device_id_raw
            with self._lock:
                if self._paired_device is not None:
                    self._paired_device["last_seen"] = time.time()
                    self._paired_device["device_name"] = device_name
                    self._save_paired_device(self._paired_device)
        else:
            self._record_failure(peer_ip)
            await ws.send_text(json.dumps({"type": "auth_error", "code": "bad_mode", "message": "Unknown auth mode"}))
            await ws.close(4001, "Unknown mode")
            return None

        srv_proof = proof(confirm_key, b"server", th)
        code = safety_code(th)
        await ws.send_text(
            json.dumps(
                {
                    "type": "auth_ok",
                    "proof": b64u_encode(srv_proof),
                    "safety_code": code,
                    "host": hostname,
                }
            )
        )

        channel = SecureChannel(
            send_key=s2c_key,
            recv_key=c2s_key,
            send_dir=DIR_SERVER_TO_CLIENT,
            recv_dir=DIR_CLIENT_TO_SERVER,
        )
        client = ActiveClient(
            ws=ws,
            channel=channel,
            device_id=device_id,
            device_name=device_name,
            safety_code=code,
            connected_at=time.time(),
            peer_ip=peer_ip,
        )

        if new_pair_record is not None:
            await self._send_encrypted(
                client,
                {
                    "type": "paired",
                    "device_id": new_pair_record["device_id"],
                    "resume_secret": new_pair_record["resume_secret"],
                    "host": hostname,
                    "safety_code": code,
                },
            )
        return client

    async def _send_encrypted(self, client: ActiveClient, message: Dict[str, Any]) -> None:
        if client.ws.closed:
            return
        payload = json.dumps(message, ensure_ascii=False).encode("utf-8")
        async with client.send_lock:
            if client.ws.closed:
                return
            frame = client.channel.seal(payload)
            await client.ws.send_binary(frame)

    # ── Periodic telemetry loop ──────────────────────────────────────────────
    async def _telemetry_loop(self) -> None:
        while True:
            await asyncio.sleep(3.0)
            with self._lock:
                client = self._active
            if client is None or client.ws.closed:
                continue
            try:
                telemetry = await asyncio.to_thread(self.toolkit.get_system_telemetry)
                await self._send_encrypted(
                    client,
                    {
                        "type": "telemetry",
                        "telemetry": telemetry,
                        "cwd": self._display_cwd(),
                    },
                )
            except Exception:
                pass

    # ── Client command handlers ──────────────────────────────────────────────
    async def _dispatch_client_message(self, client: ActiveClient, msg: Dict[str, Any]) -> None:
        mtype = msg.get("type")
        if mtype == "ping":
            await self._send_encrypted(client, {"type": "pong", "t": msg.get("t", 0)})
            return

        if mtype == "request_telemetry":
            telemetry = await asyncio.to_thread(self.toolkit.get_system_telemetry)
            await self._send_encrypted(client, {"type": "telemetry", "telemetry": telemetry, "cwd": self._display_cwd()})
            return

        if mtype == "prompt":
            text = str(msg.get("text") or "").strip()
            if not text:
                return
            await self._handle_remote_prompt(client, text)
            return

        if mtype == "approval_response":
            req_id = str(msg.get("id") or "")
            decision = str(msg.get("decision") or "deny")
            entry = self._pending_approvals.pop(req_id, None)
            if entry is None:
                return
            _cmd, approve_cb, deny_cb = entry
            approved = decision in ("allow", "always")
            if decision == "always":
                self.config.set_all_permissions(True)
            await self._send_encrypted(client, {"type": "approval_resolved", "id": req_id, "approved": approved})
            # Run approval callback in a worker thread because direct bash execution is synchronous.
            threading.Thread(target=(approve_cb if approved else deny_cb), daemon=True).start()
            return

        if mtype == "new_chat":
            if self._busy:
                await self._send_encrypted(client, {"type": "error", "message": "Tchiko is busy — wait for the current reply to finish."})
                return
            self.engine.reset_conversation()
            await self._send_encrypted(client, {"type": "chat_reset"})
            return

        if mtype == "clear_activity":
            self._activity.clear()
            await self._send_encrypted(client, {"type": "activity_cleared"})
            return

        if mtype == "trigger_mood":
            mood = str(msg.get("mood") or "idle")
            self._agent_mood = mood
            if self._on_remote_mood is not None:
                try:
                    self._on_remote_mood(mood)
                except Exception:
                    pass
            await self._send_encrypted(client, {"type": "agent_state", "state": self._agent_status, "mood": mood})
            return

        if mtype == "update_config":
            patch = msg.get("patch")
            if isinstance(patch, dict):
                self._apply_config_patch(patch)
            return

        if mtype == "unpair":
            self.revoke_pairing()
            return

    async def _handle_remote_prompt(self, client: ActiveClient, prompt: str) -> None:
        if self._busy:
            await self._send_encrypted(
                client,
                {"type": "error", "message": "Tchiko is still working on the previous request."},
            )
            return

        self._busy = True
        self._reply_started = time.monotonic()
        self._reply_tools = 0
        self._agent_status = "thinking"

        await self._send_encrypted(client, {"type": "chat_user", "text": prompt, "source": "remote", "ts": _now_hm()})
        await self._send_encrypted(client, {"type": "reply_start", "ts": _now_hm()})

        if self._on_remote_prompt_mirror is not None:
            try:
                self._on_remote_prompt_mirror("prompt", prompt)
            except Exception:
                pass

        def on_thought(thought: str) -> None:
            ts = _now_hms()
            self._activity.append({"ts": ts, "kind": "think", "text": thought})
            self._schedule_send({"type": "thought", "text": thought, "ts": ts})

        def on_tool_call(name: str, args: str) -> None:
            ts = _now_hms()
            self._reply_tools += 1
            self._activity.append({"ts": ts, "kind": "tool", "text": f"{name}  {args}"})
            self._schedule_send({"type": "tool_call", "name": name, "args": args, "ts": ts})

        def on_token(tok: str) -> None:
            self._schedule_send({"type": "token", "text": tok})

        def on_state(st: str) -> None:
            self._agent_status = st
            self._agent_mood = st
            if self._on_remote_mood is not None:
                try:
                    self._on_remote_mood(st)
                except Exception:
                    pass
            self._schedule_send({"type": "agent_state", "state": st, "mood": st})

        def on_approval(cmd: str, approve_cb: Callable[[], None], deny_cb: Callable[[], None]) -> None:
            req_id = secrets.token_hex(6)
            self._pending_approvals[req_id] = (cmd, approve_cb, deny_cb)
            self._agent_status = "alert"
            self._schedule_send({"type": "approval_needed", "id": req_id, "command": cmd})

        def on_complete(full_text: str) -> None:
            elapsed = round(time.monotonic() - self._reply_started, 2)
            self._busy = False
            self._agent_status = "idle"
            self._agent_mood = "happy"
            if self._on_remote_mood is not None:
                try:
                    self._on_remote_mood("happy")
                except Exception:
                    pass
            self._schedule_send(
                {
                    "type": "reply_complete",
                    "text": full_text,
                    "tools": self._reply_tools,
                    "elapsed_sec": elapsed,
                    "cwd": self._display_cwd(),
                    "ts": _now_hm(),
                }
            )

        self.engine.process_prompt_async(
            prompt=prompt,
            on_thought=on_thought,
            on_tool_call=on_tool_call,
            on_token=on_token,
            on_complete=on_complete,
            on_state_change=on_state,
            on_approval_needed=on_approval,
        )

    def _apply_config_patch(self, patch: Dict[str, Any]) -> None:
        if "approve_all_system_permissions" in patch:
            self.config.set_all_permissions(bool(patch["approve_all_system_permissions"]))
            return

        perms = self.config.data.setdefault("permissions", {})
        if isinstance(patch.get("permissions"), dict):
            p = patch["permissions"]
            for key in ("tool_execution_policy", "non_workspace_file_access", "internet_access_policy"):
                if key in p and isinstance(p[key], str):
                    perms[key] = p[key]
            if "terminal_sandbox" in p:
                perms["terminal_sandbox"] = bool(p["terminal_sandbox"])
            if isinstance(p.get("capabilities"), dict):
                caps = perms.setdefault("capabilities", {})
                for ck, cv in p["capabilities"].items():
                    if ck in (
                        "bash_execution",
                        "filesystem_read_write",
                        "process_management",
                        "desktop_automation",
                        "package_management",
                        "network_requests",
                    ):
                        caps[ck] = bool(cv)
            caps_now = perms.get("capabilities", {})
            perms["approve_all_system_permissions"] = (
                bool(caps_now)
                and all(caps_now.values())
                and perms.get("tool_execution_policy") == "always-proceed"
            )

        if isinstance(patch.get("agent"), dict):
            model = patch["agent"].get("model")
            if isinstance(model, str) and model:
                self.config.data.setdefault("agent", {})["model"] = model

        if isinstance(patch.get("ghost_widget"), dict):
            gw = self.config.data.setdefault("ghost_widget", {})
            gp = patch["ghost_widget"]
            if gp.get("theme") in ("phantom_cyan", "astral_violet", "emerald_matrix", "solar_gold"):
                gw["theme"] = gp["theme"]
            if "size" in gp:
                gw["size"] = max(90, min(220, int(gp["size"])))
            if "opacity" in gp:
                gw["opacity"] = round(max(0.4, min(1.0, float(gp["opacity"]))), 2)
            if "always_on_top" in gp:
                gw["always_on_top"] = bool(gp["always_on_top"])
            if "show_speech_bubble" in gp:
                gw["show_speech_bubble"] = bool(gp["show_speech_bubble"])

        self.config.save(notify=True)

    # ── State snapshot helpers ───────────────────────────────────────────────
    def _build_state_sync(self, client: ActiveClient) -> Dict[str, Any]:
        telemetry = self.toolkit.get_system_telemetry()
        skills = [
            {"name": s.name, "description": s.description, "triggers": s.triggers}
            for s in self.engine.skills.list_skills()
        ]
        pending = [
            {"id": rid, "command": cmd}
            for rid, (cmd, _a, _d) in self._pending_approvals.items()
        ]
        return {
            "type": "state_sync",
            "host": socket.gethostname(),
            "safety_code": client.safety_code,
            "device_name": client.device_name,
            "engine_label": self.engine.get_engine_status_label(),
            "status": self._agent_status,
            "mood": self._agent_mood,
            "busy": self._busy,
            "cwd": self._display_cwd(),
            "telemetry": telemetry,
            "config": self._public_config(self.config.data),
            "history": list(self.engine.memory.get("history", []))[-24:],
            "activity": list(self._activity),
            "skills": skills,
            "pending_approvals": pending,
        }

    def _display_cwd(self) -> str:
        cwd = str(self.engine.memory.get("cwd", str(Path.home())))
        home = os.path.expanduser("~")
        return "~" + cwd[len(home):] if cwd.startswith(home) else cwd

    @staticmethod
    def _public_config(data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "permissions": data.get("permissions", {}),
            "agent": {"model": data.get("agent", {}).get("model", "gemini-2.5-pro")},
            "ghost_widget": data.get("ghost_widget", {}),
        }


def _now_hm() -> str:
    return datetime.now().strftime("%H:%M")


def _now_hms() -> str:
    return datetime.now().strftime("%H:%M:%S")
