from __future__ import annotations

import socket
import struct
import time
from unittest.mock import MagicMock, patch

import pytest

from tuochat.provider.duo import DuoProvider
from tuochat.provider.eliza import ElizaProvider
from tuochat.provider.websocket import WebSocketClient
from tuochat.serialization import json_dumps_bytes, json_loads

# --- DuoProvider Extra Tests ---


@pytest.fixture
def duo_provider():
    return DuoProvider(host="https://gitlab.example.com", token="fake-token")


def graphql_msg(content, chunk_id, request_id="req-123"):
    """Build a GraphqlChannel-style WebSocket message."""
    return json_dumps_bytes(
        {
            "message": {
                "result": {
                    "data": {
                        "aiCompletionResponse": {
                            "content": content,
                            "chunkId": chunk_id,
                            "errors": [],
                            "role": "ASSISTANT",
                            "requestId": request_id,
                            "timestamp": "2024-01-01T00:00:00Z",
                        }
                    }
                }
            }
        }
    )


@patch("tuochat.provider.duo.WebSocketClient")
@patch("urllib.request.urlopen")
def test_duo_chat_streaming_out_of_order(mock_urlopen, mock_ws_class, duo_provider):
    # Mock user info and mutation
    mock_resp_user = MagicMock()
    mock_resp_user.read.return_value = json_dumps_bytes(
        {"data": {"currentUser": {"id": "gid://gitlab/User/1", "username": "testuser", "duoChatAvailable": True}}}
    )
    mock_resp_user.__enter__.return_value = mock_resp_user

    mock_resp_mutation = MagicMock()
    mock_resp_mutation.read.return_value = json_dumps_bytes(
        {"data": {"aiAction": {"requestId": "req-123", "errors": []}}}
    )
    mock_resp_mutation.__enter__.return_value = mock_resp_mutation

    mock_urlopen.side_effect = [mock_resp_user, mock_resp_mutation]

    # Mock WebSocket with out-of-order chunks (cumulative)
    mock_ws = mock_ws_class.return_value
    mock_ws.recv.side_effect = [
        json_dumps_bytes({"type": "welcome"}),
        json_dumps_bytes({"type": "confirm_subscription"}),
        graphql_msg("Hello World", 2),  # Arrives early
        graphql_msg("Hello", 1),  # Arrives next
        graphql_msg("Hello World! How", 3),
        graphql_msg("Hello World! How are you?", None),
    ]

    responses = list(duo_provider.chat_streaming("Hi"))
    assert responses == ["Hello", " World", "! How", " are you?"]


@patch("tuochat.provider.duo.WebSocketClient")
@patch("urllib.request.urlopen")
def test_duo_chat_streaming_fragment_chunks(mock_urlopen, mock_ws_class, duo_provider):
    mock_resp_user = MagicMock()
    mock_resp_user.read.return_value = json_dumps_bytes(
        {"data": {"currentUser": {"id": "gid://gitlab/User/1", "username": "testuser", "duoChatAvailable": True}}}
    )
    mock_resp_user.__enter__.return_value = mock_resp_user

    mock_resp_mutation = MagicMock()
    mock_resp_mutation.read.return_value = json_dumps_bytes(
        {"data": {"aiAction": {"requestId": "req-123", "errors": []}}}
    )
    mock_resp_mutation.__enter__.return_value = mock_resp_mutation

    mock_urlopen.side_effect = [mock_resp_user, mock_resp_mutation]

    mock_ws = mock_ws_class.return_value
    mock_ws.recv.side_effect = [
        json_dumps_bytes({"type": "welcome"}),
        json_dumps_bytes({"type": "confirm_subscription"}),
        graphql_msg(": A merge", 2),
        graphql_msg("Alpha", 1),
        graphql_msg(" request", 4),
        graphql_msg(" works.", 5),
        graphql_msg(" is useful", 3),
        graphql_msg("Alpha: A merge is useful request works.", None),
    ]

    responses = list(duo_provider.chat_streaming("Hi"))
    assert responses == ["Alpha", ": A merge", " is useful", " request", " works."]


@patch("tuochat.provider.duo.WebSocketClient")
@patch("urllib.request.urlopen")
def test_duo_chat_streaming_cancellation(mock_urlopen, mock_ws_class, duo_provider):
    mock_resp_user = MagicMock()
    mock_resp_user.read.return_value = json_dumps_bytes(
        {"data": {"currentUser": {"id": "gid://gitlab/User/1", "username": "testuser", "duoChatAvailable": True}}}
    )
    mock_resp_user.__enter__.return_value = mock_resp_user

    mock_resp_mutation = MagicMock()
    mock_resp_mutation.read.return_value = json_dumps_bytes(
        {"data": {"aiAction": {"requestId": "req-123", "errors": []}}}
    )
    mock_resp_mutation.__enter__.return_value = mock_resp_mutation

    mock_urlopen.side_effect = [mock_resp_user, mock_resp_mutation]

    mock_ws = mock_ws_class.return_value
    mock_ws.recv.side_effect = [
        json_dumps_bytes({"type": "welcome"}),
        json_dumps_bytes({"type": "confirm_subscription"}),
        graphql_msg("Partial", 1),
        socket.timeout("timeout for polling"),
        graphql_msg("Should not be reached", 2),
    ]

    cancel_flag = False

    def cancel_fn():
        return cancel_flag

    gen = duo_provider.chat_streaming("Hi", cancel=cancel_fn)

    first_chunk = next(gen)
    assert first_chunk == "Partial"

    # Now trigger cancellation
    cancel_flag = True

    with pytest.raises(StopIteration):
        next(gen)

    assert duo_provider.get_last_chat_diagnostics().raw_events[-1].startswith("cancelled:")


@patch("urllib.request.urlopen")
def test_duo_reset_conversation(mock_urlopen, duo_provider):
    mock_response = MagicMock()
    mock_response.read.return_value = json_dumps_bytes({"data": {"aiAction": {"requestId": "reset-123", "errors": []}}})
    mock_response.__enter__.return_value = mock_response
    mock_urlopen.return_value = mock_response

    duo_provider.reset_conversation()

    assert mock_urlopen.call_count == 1
    # Check that it sent "/reset"
    args, kwargs = mock_urlopen.call_args
    req = args[0]
    body = json_loads(req.data.decode("utf-8"))
    assert body["variables"]["question"] == "/reset"


@patch("tuochat.provider.duo.WebSocketClient")
def test_duo_cable_wait_welcome_timeout(mock_ws_class):
    mock_ws = mock_ws_class.return_value
    mock_ws.recv.return_value = json_dumps_bytes({"type": "ping"})

    with patch("time.monotonic", side_effect=[0, 11, 11]):  # Simulate timeout
        with pytest.raises(ConnectionError, match="Timed out waiting for Action Cable welcome"):
            DuoProvider.cable_wait_welcome(mock_ws, timeout=10.0)


@patch("tuochat.provider.duo.WebSocketClient")
def test_duo_cable_wait_confirm_reject(mock_ws_class):
    mock_ws = mock_ws_class.return_value
    mock_ws.recv.return_value = json_dumps_bytes({"type": "reject_subscription"})

    with pytest.raises(PermissionError, match="Action Cable subscription rejected"):
        DuoProvider.cable_wait_confirm(mock_ws)


# --- ElizaProvider Extra Tests ---


def test_eliza_reflections_exhaustive():
    assert ElizaProvider.stream_words  # just ensuring it exists
    from tuochat.provider.eliza import reflect

    assert reflect("I was there") == "you were there"
    assert reflect("am I?") == "are you?"
    assert reflect("this is mine") == "this is yours"


def test_eliza_chat_word_by_word_delay():
    eliza = ElizaProvider()
    start = time.monotonic()
    _chunks = list(eliza.chat("I am happy", streaming=True))
    duration = time.monotonic() - start

    # Each word should have ~0.04s delay. "Why do you say you're happy?" is ~7 words.
    # We just check it took at least some time.
    assert duration > 0.04


def test_eliza_no_match_fallback():
    eliza = ElizaProvider()
    # Something that won't match any pattern
    response = eliza.respond("xyzzy123")
    from tuochat.provider.eliza import FALLBACKS

    assert response in FALLBACKS


# --- WebSocketClient Extra Tests ---


@pytest.fixture
def mock_sock():
    return MagicMock(spec=socket.socket)


def test_ws_recv_exact_drains_buffer(mock_sock):
    ws = WebSocketClient("ws://example.com")
    ws.sock = mock_sock
    ws.recv_buffer.extend(b"hello")

    # Request 3 bytes
    data = ws.recv_exact(3)
    assert data == b"hel"
    assert ws.recv_buffer == b"lo"
    mock_sock.recv.assert_not_called()


def test_ws_recv_large_frame_126(mock_sock):
    ws = WebSocketClient("ws://example.com")
    ws.sock = mock_sock

    # 0x81 (FIN+text), 0x7E (126 length follows), then 200 bytes
    payload = b"x" * 200
    mock_sock.recv.side_effect = [b"\x81\x7e", struct.pack("!H", 200), payload]  # Header  # Extended length

    msg = ws.recv()
    assert msg == "x" * 200


def test_ws_recv_large_frame_127(mock_sock):
    ws = WebSocketClient("ws://example.com")
    ws.sock = mock_sock

    # Extended length 127
    payload = b"y" * 1000
    mock_sock.recv.side_effect = [b"\x81\x7f", struct.pack("!Q", 1000), payload]  # Header  # Extended length

    msg = ws.recv()
    assert msg == "y" * 1000


def test_ws_recv_close_frame(mock_sock):
    ws = WebSocketClient("ws://example.com")
    ws.sock = mock_sock
    mock_sock.recv.return_value = b"\x88\x00"  # Close frame header

    msg = ws.recv()
    assert msg is None


def test_ws_send_masked_large_payload(mock_sock):
    ws = WebSocketClient("ws://example.com")
    ws.sock = mock_sock

    payload = "A" * 1000
    ws.send(payload)

    sent_data = b"".join(call.args[0] for call in mock_sock.sendall.call_args_list)
    assert sent_data[0] == 0x81
    assert sent_data[1] == 0xFE  # Masked (0x80) | 126 (0x7E)
    length_field = struct.unpack("!H", sent_data[2:4])[0]
    assert length_field == 1000


def test_ws_recv_fragmented_frame_is_ignored(mock_sock):
    ws = WebSocketClient("ws://example.com")
    ws.sock = mock_sock

    # Fragment 1: FIN=0, Opcode=1 (Text), Length=2, Payload="hi"
    # Fragment 2: FIN=1, Opcode=0 (Cont), Length=3, Payload="bye"
    mock_sock.recv.side_effect = [
        b"\x01\x02",  # Fragment 1 header (FIN=0)
        b"hi",
        b"\x81\x04",  # Some other frame "data" to unblock the loop
        b"data",
    ]

    # Current implementation:
    # Opcode 1 (Text) is processed, but it doesn't check FIN bit.
    # So it yields "hi".
    msg = ws.recv()
    assert msg == "hi"  # It doesn't know it's a fragment!

    # Now for Opcode 0 (Continuation)
    mock_sock.recv.side_effect = [
        b"\x80\x03",  # Fragment 2 header (FIN=1, Opcode=0)
        b"bye",
        b"\x81\x04",  # Another frame
        b"test",
    ]

    msg = ws.recv()
    # Opcode 0 will be skipped because it's "unknown" (not 1, 8, 9, 10)
    assert msg == "test"
