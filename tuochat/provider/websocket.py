"""Minimal RFC 6455 WebSocket client using only stdlib.

Supports text frames, ping/pong, and close frames.
No external dependencies — uses socket + ssl.
"""

from __future__ import annotations

import base64
import logging
import os
import socket
import ssl
import struct
from urllib.parse import urlparse

logger = logging.getLogger("tuochat.provider.websocket")

# WebSocket opcodes
OP_TEXT = 0x1
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA


class WebSocketClient:
    """Minimal WebSocket client using only stdlib (socket + ssl).

    When *proxy* is provided as ``(host, port)``, the connection is tunnelled
    through an HTTP CONNECT proxy (standard for WSS over corporate proxies).
    """

    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
        proxy: tuple[str, int] | None = None,
    ) -> None:
        self.url = url
        self.headers = headers or {}
        self.timeout = timeout
        self.proxy = proxy  # (host, port) or None
        self.sock: socket.socket | None = None
        self.recv_buffer = bytearray()

    @property
    def connected(self) -> bool:
        """Check if the WebSocket is connected."""
        return self.sock is not None

    def connect(self) -> None:
        """Open WebSocket connection with HTTP upgrade handshake.

        When a proxy is configured, opens a TCP connection to the proxy and
        issues an HTTP CONNECT request to tunnel through to the target host
        before the TLS handshake.
        """
        parsed = urlparse(self.url)
        host = parsed.hostname
        if not host:
            raise ValueError(f"Invalid WebSocket URL: {self.url}")
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path += f"?{parsed.query}"

        if self.proxy:
            proxy_host, proxy_port = self.proxy
            logger.debug("Connecting via proxy %s:%d -> %s:%d%s", proxy_host, proxy_port, host, port, path)
            raw_sock = socket.create_connection((proxy_host, proxy_port), timeout=self.timeout)
            # HTTP CONNECT tunnel
            connect_req = f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n"
            raw_sock.sendall(connect_req.encode("ascii"))
            tunnel_resp = b""
            while b"\r\n\r\n" not in tunnel_resp:
                chunk = raw_sock.recv(4096)
                if not chunk:
                    raise ConnectionError("Proxy closed connection during CONNECT tunnel")
                tunnel_resp += chunk
            status_line = tunnel_resp.split(b"\r\n")[0].decode("utf-8", errors="replace")
            if "200" not in status_line:
                raise ConnectionError(f"Proxy CONNECT failed: {status_line}")
            logger.debug("Proxy tunnel established: %s", status_line)
        else:
            logger.debug("Connecting to %s:%d%s", host, port, path)
            raw_sock = socket.create_connection((host, port), timeout=self.timeout)

        # TLS if wss://
        if parsed.scheme == "wss":
            ctx = create_ssl_context()
            self.sock = ctx.wrap_socket(raw_sock, server_hostname=host)
        else:
            self.sock = raw_sock

        self.sock.settimeout(self.timeout)

        # WebSocket upgrade handshake
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        lines = [
            f"GET {path} HTTP/1.1",
            f"Host: {host}",
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Sec-WebSocket-Key: {key}",
            "Sec-WebSocket-Version: 13",
        ]
        for k, v in self.headers.items():
            lines.append(f"{k}: {v}")
        lines.append("")
        lines.append("")

        self.sock.sendall("\r\n".join(lines).encode("utf-8"))

        # Read upgrade response headers
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("Connection closed during WebSocket handshake")
            response += chunk

        status_line = response.split(b"\r\n")[0].decode("utf-8", errors="replace")
        if "101" not in status_line:
            raise ConnectionError(f"WebSocket upgrade failed: {status_line}")

        # Any bytes past the \r\n\r\n boundary are the start of the first
        # WebSocket frame — save them so recv_exact doesn't lose them.
        header_end = response.index(b"\r\n\r\n") + 4
        if header_end < len(response):
            self.recv_buffer.extend(response[header_end:])

        logger.debug("WebSocket connected to %s", self.url)

    def send(self, data: str) -> None:
        """Send a text frame (masked, per RFC 6455 client requirement)."""
        if not self.sock:
            raise ConnectionError("WebSocket is not connected")

        payload = data.encode("utf-8")
        mask = os.urandom(4)

        header = bytearray()
        header.append(0x81)  # FIN + text opcode

        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))

        header.extend(mask)

        # XOR-mask the payload
        masked = bytearray(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + bytes(masked))

    def set_recv_timeout(self, timeout: float) -> None:
        """Change the socket receive timeout (seconds).

        Useful for making recv() return quickly so the caller can check a
        cancellation flag between reads.
        """
        if self.sock:
            self.sock.settimeout(timeout)

    def recv(self) -> str | None:
        """Receive a text frame. Returns None on close frame or connection end."""
        while True:
            if not self.sock:
                return None

            try:
                header = self.recv_exact(2)
            except socket.timeout:
                raise  # let caller handle short-timeout polling
            except (ConnectionError, OSError):
                return None

            if not header or len(header) < 2:
                return None

            opcode = header[0] & 0x0F
            is_masked = bool(header[1] & 0x80)
            length = header[1] & 0x7F

            if length == 126:
                length = struct.unpack("!H", self.recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self.recv_exact(8))[0]

            mask_key = self.recv_exact(4) if is_masked else None
            payload = self.recv_exact(length)

            if is_masked and mask_key:
                payload = bytearray(b ^ mask_key[i % 4] for i, b in enumerate(payload))

            if opcode == OP_CLOSE:
                logger.debug("Received WebSocket close frame")
                return None

            if opcode == OP_PING:
                self.send_pong(payload)
                continue

            if opcode == OP_PONG:
                continue

            if opcode == OP_TEXT:
                return bytes(payload).decode("utf-8")

            # Skip unknown opcodes
            logger.debug("Skipping unknown WebSocket opcode: %d", opcode)

    def close(self) -> None:
        """Send close frame and close the socket."""
        if self.sock:
            try:
                # Close frame: opcode 0x8, masked, zero-length
                mask = os.urandom(4)
                self.sock.sendall(b"\x88\x80" + mask)
            except OSError:
                pass
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None
            self.recv_buffer.clear()
            logger.debug("WebSocket closed")

    def recv_exact(self, n: int) -> bytearray:
        """Read exactly n bytes from the socket."""
        if not self.sock:
            raise ConnectionError("WebSocket is not connected")

        data = bytearray()
        # Drain the read-ahead buffer first (may contain bytes from the HTTP
        # upgrade response that arrived in the same TCP segment as the first
        # WebSocket frame).
        if self.recv_buffer:
            take = min(n, len(self.recv_buffer))
            data.extend(self.recv_buffer[:take])
            del self.recv_buffer[:take]

        while len(data) < n:
            chunk = self.sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError("Connection closed while reading")
            data.extend(chunk)
        return data

    def send_pong(self, payload: bytes | bytearray) -> None:
        """Send a pong frame in response to a ping."""
        if not self.sock:
            return

        mask = os.urandom(4)
        header = bytearray([0x80 | OP_PONG])
        plen = len(payload)
        if plen < 126:
            header.append(0x80 | plen)
        else:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", plen))

        header.extend(mask)
        masked = bytearray(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + bytes(masked))


def create_ssl_context() -> ssl.SSLContext:
    """Create a WSS client context, preferring TLS 1.3 when available."""
    ctx = ssl.create_default_context()
    tls_version = getattr(ssl, "TLSVersion", None)
    if tls_version is not None and hasattr(tls_version, "TLSv1_3"):
        try:
            ctx.maximum_version = tls_version.TLSv1_3
        except (AttributeError, ValueError):
            pass
    return ctx
