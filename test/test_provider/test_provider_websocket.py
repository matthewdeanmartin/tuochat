from __future__ import annotations

import socket
import ssl
from unittest.mock import MagicMock, patch

import pytest

from tuochat.provider.websocket import WebSocketClient


@pytest.fixture
def mock_socket():
    with patch("socket.create_connection") as mock_create:
        mock_sock = MagicMock(spec=socket.socket)
        mock_create.return_value = mock_sock
        yield mock_sock


@pytest.fixture
def ws_client():
    return WebSocketClient("ws://example.com/chat", headers={"X-Test": "Value"})


def test_ws_init(ws_client):
    assert ws_client.url == "ws://example.com/chat"
    assert ws_client.headers == {"X-Test": "Value"}
    assert not ws_client.connected


def test_ws_connect_http(mock_socket, ws_client):
    # Mock handshake response
    mock_socket.recv.return_value = (
        b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n"
    )

    ws_client.connect()

    assert ws_client.connected
    # Check that it sent the upgrade request
    sent_data = b"".join(call.args[0] for call in mock_socket.sendall.call_args_list)
    assert b"GET /chat HTTP/1.1" in sent_data
    assert b"Host: example.com" in sent_data
    assert b"Upgrade: websocket" in sent_data
    assert b"X-Test: Value" in sent_data


@patch("tuochat.provider.websocket.create_ssl_context")
def test_ws_connect_https(mock_ssl_context, mock_socket):
    mock_ctx = MagicMock(spec=ssl.SSLContext)
    mock_ssl_context.return_value = mock_ctx
    mock_wrapped_sock = MagicMock(spec=socket.socket)
    mock_ctx.wrap_socket.return_value = mock_wrapped_sock
    mock_wrapped_sock.recv.return_value = b"HTTP/1.1 101 Switching Protocols\r\n\r\n"

    ws = WebSocketClient("wss://example.com/chat")
    ws.connect()

    assert ws.connected
    mock_ctx.wrap_socket.assert_called_once()


def test_ws_connect_failure(mock_socket, ws_client):
    mock_socket.recv.return_value = b"HTTP/1.1 403 Forbidden\r\n\r\n"

    with pytest.raises(ConnectionError, match="WebSocket upgrade failed"):
        ws_client.connect()


def test_ws_send_text(mock_socket, ws_client):
    mock_socket.recv.return_value = b"HTTP/1.1 101 Switching Protocols\r\n\r\n"
    ws_client.connect()

    ws_client.send("hello")

    # Capture what was sent
    # WebSocket frames for "hello" (5 bytes)
    # Header: 0x81 (FIN + text), 0x85 (MASK + 5 length)
    # Mask: 4 bytes
    # Payload: 5 bytes (XORed)
    calls = mock_socket.sendall.call_args_list
    # The first call was the handshake, the second should be the frame
    frame_data = calls[-1].args[0]
    assert frame_data[0] == 0x81
    assert frame_data[1] & 0x80  # Mask bit set
    assert (frame_data[1] & 0x7F) == 5  # Length 5


def test_ws_recv_text(mock_socket, ws_client):
    mock_socket.recv.return_value = b"HTTP/1.1 101 Switching Protocols\r\n\r\n"
    ws_client.connect()

    # Mock a text frame response: "hi"
    # 0x81 (FIN + text), 0x02 (No mask, length 2), b'hi'
    mock_socket.recv.side_effect = [
        b"\x81\x02",  # Header
        b"hi",  # Payload
    ]

    msg = ws_client.recv()
    assert msg == "hi"


def test_ws_recv_ping_pong(mock_socket, ws_client):
    mock_socket.recv.return_value = b"HTTP/1.1 101 Switching Protocols\r\n\r\n"
    ws_client.connect()

    # Mock: Ping frame, then Text frame "data"
    # Ping: 0x89 (FIN + ping), 0x00 (length 0)
    # Text: 0x81 (FIN + text), 0x04 (length 4), b'data'
    mock_socket.recv.side_effect = [
        b"\x89\x00",  # Ping header
        b"\x81\x04",  # Text header
        b"data",  # Text payload
    ]

    msg = ws_client.recv()
    assert msg == "data"
    # Verify pong was sent
    sent_data = b"".join(call.args[0] for call in mock_socket.sendall.call_args_list)
    assert b"\x8a" in sent_data  # Pong opcode


def test_ws_close(mock_socket, ws_client):
    mock_socket.recv.return_value = b"HTTP/1.1 101 Switching Protocols\r\n\r\n"
    ws_client.connect()
    ws_client.close()

    assert not ws_client.connected
    mock_socket.close.assert_called_once()
    # Should have sent a close frame: 0x88
    sent_data = b"".join(call.args[0] for call in mock_socket.sendall.call_args_list)
    assert b"\x88" in sent_data
