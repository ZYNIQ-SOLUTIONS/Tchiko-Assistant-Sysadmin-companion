"""Minimal HTTPS + WebSocket server for Tchiko RC (`tchiko/remote/server.py`).

Uses only Python's standard library (`asyncio`, `ssl`, `hashlib`, `base64`, `socket`, `subprocess`)
so Tchiko keeps zero mandatory runtime dependencies.

- Serves the pure HTML/CSS/JS app from `rc/` with strict security headers (CSP, nosniff, DENY framing).
- Generates and caches a local self-signed TLS certificate (`~/.config/tchiko/rc-cert.pem` +
  `rc-key.pem`, mode `0600`) with SANs for localhost and the machine's current LAN IPs so mobile
  browsers get a secure context (required for WebCrypto and `getUserMedia`).
- Handles RFC 6455 WebSocket connections on `/ws` with Origin validation and frame-size limits.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import ipaddress
import mimetypes
import os
import socket
import ssl
import struct
import subprocess
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_HTTP_HEADER_BYTES = 16 * 1024
MAX_WS_MESSAGE_BYTES = 5 * 1024 * 1024  # 5 MiB

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".json": "application/json; charset=utf-8",
    ".ico": "image/x-icon",
    ".webmanifest": "application/manifest+json; charset=utf-8",
}

CSP_HEADER = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "connect-src 'self' wss: ws:; "
    "font-src 'self' data:; "
    "media-src 'self' blob:; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'"
)


def detect_lan_ips() -> List[str]:
    """Return non-loopback IPv4 addresses reachable on the local network (primary first)."""
    ips: List[str] = []
    # Primary outbound interface IP (doesn't send packets, just queries routing table).
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 80))
            primary = s.getsockname()[0]
            if primary and not primary.startswith("127."):
                ips.append(primary)
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = str(info[4][0])
            if ip and not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    return ips


def ensure_tls_cert(cert_dir: Path, extra_ips: Optional[List[str]] = None) -> Tuple[Path, Path]:
    """Ensure a valid local self-signed TLS certificate exists for localhost + LAN IPs."""
    cert_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(cert_dir, 0o700)
    except OSError:
        pass

    cert_path = cert_dir / "rc-cert.pem"
    key_path = cert_dir / "rc-key.pem"
    ips_path = cert_dir / "rc-sans.txt"

    lan_ips = sorted(set(["127.0.0.1"] + detect_lan_ips() + (extra_ips or [])))
    san_signature = ",".join(lan_ips)
    if cert_path.exists() and key_path.exists() and ips_path.exists():
        try:
            if ips_path.read_text(encoding="utf-8").strip() == san_signature:
                return cert_path, key_path
        except OSError:
            pass

    if not _generate_cert_with_cryptography(cert_path, key_path, lan_ips):
        _generate_cert_with_openssl(cert_path, key_path, lan_ips)

    try:
        os.chmod(key_path, 0o600)
        os.chmod(cert_path, 0o644)
    except OSError:
        pass
    ips_path.write_text(san_signature + "\n", encoding="utf-8")
    return cert_path, key_path


def _generate_cert_with_cryptography(cert_path: Path, key_path: Path, ips: List[str]) -> bool:
    try:
        import datetime as dt

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID

        key = ec.generate_private_key(ec.SECP256R1())
        subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Tchiko RC Local")])
        san_entries: List[x509.GeneralName] = [
            x509.DNSName("localhost"),
            x509.DNSName(socket.gethostname()),
            x509.IPAddress(ipaddress.IPv6Address("::1")),
        ]
        for raw_ip in ips:
            try:
                san_entries.append(x509.IPAddress(ipaddress.ip_address(raw_ip)))
            except ValueError:
                pass

        now = dt.datetime.now(dt.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=365))
            .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(key, hashes.SHA256())
        )
        key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        return True
    except Exception:
        return False


def _generate_cert_with_openssl(cert_path: Path, key_path: Path, ips: List[str]) -> None:
    san_parts = ["DNS:localhost", f"DNS:{socket.gethostname()}", "IP:::1"] + [f"IP:{ip}" for ip in ips]
    cmd = [
        "openssl",
        "req",
        "-x509",
        "-newkey",
        "ec",
        "-pkeyopt",
        "ec_paramgen_curve:prime256v1",
        "-nodes",
        "-keyout",
        str(key_path),
        "-out",
        str(cert_path),
        "-days",
        "365",
        "-subj",
        "/CN=Tchiko RC Local",
        "-addext",
        "subjectAltName=" + ",".join(san_parts),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=15)


class WebSocketClosed(Exception):
    """Raised when a WebSocket connection closes cleanly or abruptly."""

    def __init__(self, code: int = 1000, reason: str = "") -> None:
        super().__init__(f"WebSocket closed ({code}): {reason}")
        self.code = code
        self.reason = reason


class WebSocketConnection:
    """RFC 6455 WebSocket wrapper over an asyncio stream pair."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        peer: Tuple[str, int],
    ) -> None:
        self._reader = reader
        self._writer = writer
        self.peer = peer
        self._closed = False
        self._send_lock = asyncio.Lock()

    @property
    def closed(self) -> bool:
        return self._closed

    async def recv(self) -> Tuple[str, bytes | str]:
        """Receive one complete WebSocket message: `('text', str)` or `('binary', bytes)`."""
        msg_opcode: Optional[int] = None
        chunks: List[bytes] = []
        total = 0

        while True:
            try:
                header = await self._reader.readexactly(2)
            except (asyncio.IncompleteReadError, ConnectionError, OSError) as exc:
                self._closed = True
                raise WebSocketClosed(1006, "connection lost") from exc

            b0, b1 = header[0], header[1]
            fin = bool(b0 & 0x80)
            rsv = b0 & 0x70
            opcode = b0 & 0x0F
            masked = bool(b1 & 0x80)
            length = b1 & 0x7F

            if rsv != 0 or not masked:
                await self.close(1002, "protocol error")
                raise WebSocketClosed(1002, "protocol error")

            if length == 126:
                (length,) = struct.unpack(">H", await self._reader.readexactly(2))
            elif length == 127:
                (length,) = struct.unpack(">Q", await self._reader.readexactly(8))

            if length > MAX_WS_MESSAGE_BYTES or total + length > MAX_WS_MESSAGE_BYTES:
                await self.close(1009, "message too large")
                raise WebSocketClosed(1009, "message too large")

            mask = await self._reader.readexactly(4)
            payload = bytearray(await self._reader.readexactly(length)) if length else bytearray()
            for i in range(length):
                payload[i] ^= mask[i & 3]
            data = bytes(payload)

            # Control frames (may appear between fragmented data frames).
            if opcode == 0x8:  # Close
                code = struct.unpack(">H", data[:2])[0] if len(data) >= 2 else 1000
                reason = data[2:].decode("utf-8", errors="replace") if len(data) > 2 else ""
                if not self._closed:
                    await self.close(code, "")
                raise WebSocketClosed(code, reason)
            if opcode == 0x9:  # Ping
                await self._write_frame(0xA, data)
                continue
            if opcode == 0xA:  # Pong
                continue

            if opcode in (0x1, 0x2):
                if msg_opcode is not None:
                    await self.close(1002, "interleaved data frame")
                    raise WebSocketClosed(1002, "interleaved data frame")
                msg_opcode = opcode
                chunks = [data]
                total = len(data)
            elif opcode == 0x0:
                if msg_opcode is None:
                    await self.close(1002, "unexpected continuation")
                    raise WebSocketClosed(1002, "unexpected continuation")
                chunks.append(data)
                total += len(data)
            else:
                await self.close(1002, "unsupported opcode")
                raise WebSocketClosed(1002, "unsupported opcode")

            if fin:
                full = b"".join(chunks)
                if msg_opcode == 0x1:
                    try:
                        return "text", full.decode("utf-8")
                    except UnicodeDecodeError as exc:
                        await self.close(1007, "invalid utf-8")
                        raise WebSocketClosed(1007, "invalid utf-8") from exc
                return "binary", full

    async def send_text(self, text: str) -> None:
        await self._write_frame(0x1, text.encode("utf-8"))

    async def send_binary(self, data: bytes) -> None:
        await self._write_frame(0x2, data)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        if self._closed:
            return
        self._closed = True
        payload = struct.pack(">H", code) + reason.encode("utf-8")[:120]
        try:
            await self._write_frame(0x8, payload, allow_closed=True)
        except Exception:
            pass
        try:
            self._writer.close()
            await self._writer.wait_closed()
        except Exception:
            pass

    async def _write_frame(self, opcode: int, payload: bytes, allow_closed: bool = False) -> None:
        if self._closed and not allow_closed:
            raise WebSocketClosed(1006, "already closed")
        n = len(payload)
        if n < 126:
            header = struct.pack(">BB", 0x80 | opcode, n)
        elif n < 65536:
            header = struct.pack(">BBH", 0x80 | opcode, 126, n)
        else:
            header = struct.pack(">BBQ", 0x80 | opcode, 127, n)
        async with self._send_lock:
            try:
                self._writer.write(header + payload)
                await self._writer.drain()
            except (ConnectionError, OSError) as exc:
                self._closed = True
                if not allow_closed:
                    raise WebSocketClosed(1006, "write failed") from exc


class RemoteHttpWsServer:
    """Async HTTPS (or plain HTTP for local tests) static server + `/ws` WebSocket endpoint."""

    def __init__(
        self,
        static_dir: Path,
        ws_handler: Callable[[WebSocketConnection], Awaitable[None]],
        host: str = "0.0.0.0",
        port: int = 8765,
        cert_dir: Optional[Path] = None,
        use_tls: bool = True,
    ) -> None:
        self.static_dir = static_dir.resolve()
        self.ws_handler = ws_handler
        self.host = host
        self.port = port
        self.cert_dir = cert_dir or (Path.home() / ".config" / "tchiko")
        self.use_tls = use_tls
        self._server: Optional[asyncio.base_events.Server] = None
        self.bound_port: int = port

    async def start(self) -> int:
        ssl_ctx: Optional[ssl.SSLContext] = None
        if self.use_tls:
            cert_path, key_path = ensure_tls_cert(self.cert_dir)
            ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ssl_ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ssl_ctx.load_cert_chain(str(cert_path), str(key_path))

        try:
            self._server = await asyncio.start_server(
                self._handle_client,
                self.host,
                self.port,
                ssl=ssl_ctx,
            )
        except OSError:
            # Requested port in use: bind an ephemeral free port instead of failing startup.
            self._server = await asyncio.start_server(
                self._handle_client,
                self.host,
                0,
                ssl=ssl_ctx,
            )
        sock = self._server.sockets[0]
        self.bound_port = int(sock.getsockname()[1])
        return self.bound_port

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    def urls(self) -> List[str]:
        scheme = "https" if self.use_tls else "http"
        ips = detect_lan_ips()
        out = [f"{scheme}://{ip}:{self.bound_port}" for ip in ips]
        out.append(f"{scheme}://localhost:{self.bound_port}")
        return out

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername") or ("unknown", 0)
        peer_tuple = (str(peer[0]), int(peer[1])) if isinstance(peer, tuple) and len(peer) >= 2 else ("unknown", 0)
        upgraded = False
        try:
            raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10.0)
            if len(raw) > MAX_HTTP_HEADER_BYTES:
                await self._send_http(writer, 431, "Headers Too Large", b"Headers Too Large")
                return
            lines = raw.decode("iso-8859-1").split("\r\n")
            req_parts = lines[0].split(" ")
            if len(req_parts) != 3:
                await self._send_http(writer, 400, "Bad Request", b"Bad Request")
                return
            method, target, _version = req_parts
            headers: Dict[str, str] = {}
            for line in lines[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip().lower()] = v.strip()

            parsed = urlparse(target)
            req_path = parsed.path or "/"

            if req_path == "/ws" and headers.get("upgrade", "").lower() == "websocket":
                if not self._origin_allowed(headers):
                    await self._send_http(writer, 403, "Forbidden", b"Origin not allowed")
                    return
                ws_key = headers.get("sec-websocket-key", "")
                if not ws_key:
                    await self._send_http(writer, 400, "Bad Request", b"Missing Sec-WebSocket-Key")
                    return
                accept = base64.b64encode(hashlib.sha1((ws_key + WS_GUID).encode("ascii")).digest()).decode("ascii")
                resp = (
                    "HTTP/1.1 101 Switching Protocols\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
                )
                writer.write(resp.encode("ascii"))
                await writer.drain()
                upgraded = True
                ws = WebSocketConnection(reader, writer, peer_tuple)
                await self.ws_handler(ws)
                return

            if method not in ("GET", "HEAD"):
                await self._send_http(writer, 405, "Method Not Allowed", b"Method Not Allowed")
                return

            if req_path == "/health":
                await self._send_http(writer, 200, "OK", b'{"ok":true}', "application/json; charset=utf-8", head=(method == "HEAD"))
                return

            await self._serve_static(writer, req_path, head=(method == "HEAD"))
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError, OSError):
            pass
        finally:
            if not upgraded:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass

    @staticmethod
    def _origin_allowed(headers: Dict[str, str]) -> bool:
        origin = headers.get("origin", "")
        if not origin:
            return True  # non-browser client
        host = headers.get("host", "")
        if not host:
            return False
        parsed = urlparse(origin)
        return parsed.netloc.lower() == host.lower()

    async def _serve_static(self, writer: asyncio.StreamWriter, req_path: str, head: bool = False) -> None:
        rel = "index.html" if req_path in ("/", "") else req_path.lstrip("/")
        candidate = (self.static_dir / rel).resolve()
        try:
            candidate.relative_to(self.static_dir)
        except ValueError:
            await self._send_http(writer, 403, "Forbidden", b"Forbidden")
            return

        if candidate.is_dir():
            candidate = candidate / "index.html"
        if not candidate.is_file():
            await self._send_http(writer, 404, "Not Found", b"Not Found")
            return

        ctype = CONTENT_TYPES.get(candidate.suffix.lower()) or mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        data = candidate.read_bytes()
        await self._send_http(writer, 200, "OK", data, ctype, head=head)

    @staticmethod
    async def _send_http(
        writer: asyncio.StreamWriter,
        status: int,
        reason: str,
        body: bytes,
        content_type: str = "text/plain; charset=utf-8",
        head: bool = False,
    ) -> None:
        header = (
            f"HTTP/1.1 {status} {reason}\r\n"
            f"Content-Type: {content_type}\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Content-Security-Policy: {CSP_HEADER}\r\n"
            "X-Content-Type-Options: nosniff\r\n"
            "X-Frame-Options: DENY\r\n"
            "Referrer-Policy: no-referrer\r\n"
            "Permissions-Policy: camera=(self)\r\n"
            "Cache-Control: no-store\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii")
        writer.write(header if head else header + body)
        await writer.drain()
