from __future__ import annotations

import urllib.error
import urllib.request
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tuochat.config import default_gitlab_user_agent
from tuochat.provider.duo import DUO_CHAT_MODEL_FIELD_CANDIDATES, ChatDiagnostics, DuoAPIError, DuoProvider
from tuochat.serialization import json_dumps_bytes


@pytest.fixture
def provider():
    return DuoProvider(host="https://gitlab.example.com", token="fake-token")


def test_provider_init(provider):
    assert provider.host == "https://gitlab.example.com"
    assert provider.token == "fake-token"
    assert provider.token_type == "pat"
    summary = provider.timeout_summary()
    assert summary["request_timeout"] == 120.0
    assert summary["websocket_welcome_timeout"] == 20.0
    assert summary["websocket_subscription_timeout"] == 20.0


def test_provider_init_invalid_host():
    with pytest.raises(ValueError, match="GitLab host must use http:// or https://"):
        DuoProvider(host="ftp://gitlab.example.com", token="fake")


def test_auth_headers_pat(provider):
    headers = provider.auth_headers()
    assert headers["PRIVATE-TOKEN"] == "fake-token"


def test_auth_headers_oauth():
    p = DuoProvider(host="https://gitlab.example.com", token="oauth-token", token_type="oauth")
    headers = p.auth_headers()
    assert headers["Authorization"] == "Bearer oauth-token"


def test_request_headers_include_user_agent(provider):
    headers = provider.request_headers({"Content-Type": "application/json"})

    assert headers["PRIVATE-TOKEN"] == "fake-token"
    assert headers["User-Agent"] == default_gitlab_user_agent()
    assert headers["Content-Type"] == "application/json"


def test_new_chat_diagnostics_tracks_provider_timeouts(provider):
    diagnostics = provider.new_chat_diagnostics("streaming")

    assert diagnostics.mode == "streaming"
    assert diagnostics.request_timeout == 120.0
    assert diagnostics.websocket_welcome_timeout == 20.0
    assert diagnostics.websocket_subscription_timeout == 20.0
    assert provider.get_last_chat_diagnostics() is diagnostics


def test_chat_diagnostics_add_event_falls_back_to_repr():
    diagnostics = ChatDiagnostics(
        mode="streaming", request_timeout=1.0, websocket_welcome_timeout=2.0, websocket_subscription_timeout=3.0
    )

    diagnostics.add_event("unserializable", {"value": object()})

    assert diagnostics.raw_events[0].startswith("unserializable: ")
    assert "<object object at" in diagnostics.raw_events[0]


@patch("urllib.request.urlopen")
def test_get_instance_version(mock_urlopen, provider):
    mock_response = MagicMock()
    mock_response.read.return_value = json_dumps_bytes({"version": "16.10.0"})
    mock_response.__enter__.return_value = mock_response
    mock_urlopen.return_value = mock_response

    version = provider.get_instance_version()
    assert version == "16.10.0"
    mock_urlopen.assert_called_once()
    request = mock_urlopen.call_args.args[0]
    assert request.get_header("User-agent") == default_gitlab_user_agent()


@patch("urllib.request.urlopen")
def test_validate_token(mock_urlopen, provider):
    mock_response = MagicMock()
    mock_response.read.return_value = json_dumps_bytes({"id": 1, "name": "test"})
    mock_response.__enter__.return_value = mock_response
    mock_urlopen.return_value = mock_response

    info = provider.validate_token()
    assert info["id"] == 1
    assert info["name"] == "test"


@patch("urllib.request.urlopen")
def test_graphql_error(mock_urlopen, provider):
    mock_error = urllib.error.HTTPError(
        url="https://gitlab.example.com/api/graphql",
        code=401,
        msg="Unauthorized",
        hdrs={},  # type: ignore
        fp=MagicMock(),
    )
    mock_error.fp.read.return_value = b"Unauthorized"  # type: ignore
    mock_urlopen.side_effect = mock_error

    with pytest.raises(DuoAPIError, match=r"GraphQL request failed \(401\)"):
        provider.graphql("query { hello }")


@patch("urllib.request.urlopen")
def test_rest_get_error(mock_urlopen, provider):
    mock_error = urllib.error.HTTPError(
        url="https://gitlab.example.com/api/v4/version",
        code=404,
        msg="Not Found",
        hdrs={},  # type: ignore
        fp=MagicMock(),
    )
    mock_error.fp.read.return_value = b"missing"  # type: ignore
    mock_urlopen.side_effect = mock_error

    with pytest.raises(DuoAPIError, match=r"REST request failed \(404\): missing"):
        provider.rest_get("/api/v4/version")


@patch.object(DuoProvider, "graphql")
def test_get_current_user_caches_result(mock_graphql, provider):
    mock_graphql.return_value = {
        "data": {
            "currentUser": {
                "id": "gid://gitlab/User/1",
                "username": "testuser",
                "duoChatAvailable": True,
            }
        }
    }

    first = provider.get_current_user()
    second = provider.get_current_user()

    assert first is second
    assert first.username == "testuser"
    mock_graphql.assert_called_once()


@patch.object(DuoProvider, "graphql")
def test_get_current_user_raises_when_missing(mock_graphql, provider):
    mock_graphql.return_value = {"errors": [{"message": "Unauthorized"}], "data": {"currentUser": None}}

    with pytest.raises(DuoAPIError, match="Failed to get current user: Unauthorized"):
        provider.get_current_user()


@patch.object(DuoProvider, "chat_streaming", side_effect=ConnectionError("socket failed"))
@patch.object(DuoProvider, "chat_polling", return_value="fallback reply")
def test_chat_falls_back_to_polling_and_records_reason(mock_polling, mock_streaming, provider):
    provider.new_chat_diagnostics("streaming")

    chunks = list(provider.chat("hello", streaming=True))

    assert chunks == ["fallback reply"]
    assert provider.get_last_chat_diagnostics() is not None
    assert provider.get_last_chat_diagnostics().fallback_reason == "socket failed"
    mock_streaming.assert_called_once()
    mock_polling.assert_called_once_with("hello", None, additional_context=None, duo_model=None)


@patch("tuochat.provider.duo.WebSocketClient")
@patch("urllib.request.urlopen")
def test_chat_streaming(mock_urlopen, mock_ws_class, provider):
    # Mock user info
    mock_resp_user = MagicMock()
    mock_resp_user.read.return_value = json_dumps_bytes(
        {"data": {"currentUser": {"id": "gid://gitlab/User/1", "username": "testuser", "duoChatAvailable": True}}}
    )
    mock_resp_user.__enter__.return_value = mock_resp_user

    # Mock mutation response
    mock_resp_mutation = MagicMock()
    mock_resp_mutation.read.return_value = json_dumps_bytes(
        {"data": {"aiAction": {"requestId": "req-123", "errors": []}}}
    )
    mock_resp_mutation.__enter__.return_value = mock_resp_mutation

    mock_urlopen.side_effect = [mock_resp_user, mock_resp_mutation]

    # Mock WebSocket
    mock_ws = mock_ws_class.return_value

    def graphql_msg(content, chunk_id):
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
                                "requestId": "req-123",
                                "timestamp": "2024-01-01T00:00:00Z",
                            }
                        }
                    }
                }
            }
        )

    mock_ws.recv.side_effect = [
        json_dumps_bytes({"type": "welcome"}),
        json_dumps_bytes({"type": "confirm_subscription"}),
        graphql_msg("Hello", 1),  # cumulative: "Hello"
        graphql_msg("Hello world", 2),  # cumulative: "Hello world"
        graphql_msg("Hello world", None),  # final chunk has full text
    ]

    responses = list(provider.chat_streaming("Hi"))

    assert responses == ["Hello", " world"]
    mock_ws.connect.assert_called_once()
    mock_ws.send.assert_called()
    assert mock_ws_class.call_args.kwargs["headers"]["User-Agent"] == default_gitlab_user_agent()


@patch("urllib.request.urlopen")
@patch("time.sleep", return_value=None)
def test_chat_polling(mock_sleep, mock_urlopen, provider):
    # Mock user info
    mock_resp_user = MagicMock()
    mock_resp_user.read.return_value = json_dumps_bytes(
        {"data": {"currentUser": {"id": "gid://gitlab/User/1", "username": "testuser", "duoChatAvailable": True}}}
    )
    mock_resp_user.__enter__.return_value = mock_resp_user

    # Mock mutation response
    mock_resp_mutation = MagicMock()
    mock_resp_mutation.read.return_value = json_dumps_bytes(
        {"data": {"aiAction": {"requestId": "req-123", "errors": []}}}
    )
    mock_resp_mutation.__enter__.return_value = mock_resp_mutation

    # Mock poll response
    mock_resp_poll = MagicMock()
    mock_resp_poll.read.return_value = json_dumps_bytes(
        {"data": {"aiMessages": {"nodes": [{"content": "Full response", "role": "ASSISTANT"}]}}}
    )
    mock_resp_poll.__enter__.return_value = mock_resp_poll

    mock_urlopen.side_effect = [mock_resp_mutation, mock_resp_poll]

    response = provider.chat_polling("Hi")

    assert response == "Full response"
    assert mock_urlopen.call_count == 2


@patch.object(DuoProvider, "graphql")
def test_probe_duo_chat_model_support_reports_unsupported_when_all_candidates_fail(mock_graphql, provider):
    mock_graphql.side_effect = [
        {
            "errors": [
                {
                    "message": f"InputObject 'AiChatInput' doesn't accept argument '{field_name}'",
                    "extensions": {"code": "argumentNotAccepted"},
                }
            ]
        }
        for field_name in DUO_CHAT_MODEL_FIELD_CANDIDATES
    ]

    support = provider.probe_duo_chat_model_support(refresh=True)

    assert support.supported is False
    assert support.request_field is None
    assert [attempt.field_name for attempt in support.attempts] == list(DUO_CHAT_MODEL_FIELD_CANDIDATES)
    assert all(attempt.error_code == "argumentNotAccepted" for attempt in support.attempts)


@patch.object(DuoProvider, "graphql")
def test_probe_duo_chat_model_support_returns_first_supported_field(mock_graphql, provider):
    mock_graphql.side_effect = [
        {
            "errors": [
                {
                    "message": "InputObject 'AiChatInput' doesn't accept argument 'model'",
                    "extensions": {"code": "argumentNotAccepted"},
                }
            ]
        },
        {"data": {"aiAction": {"requestId": "req-123", "errors": []}}},
    ]

    support = provider.probe_duo_chat_model_support(refresh=True)

    assert support.supported is True
    assert support.request_field == "modelId"
    assert [attempt.field_name for attempt in support.attempts] == ["model", "modelId"]
    assert support.attempts[1].accepted is True


@patch.object(DuoProvider, "probe_duo_chat_model_support")
def test_chat_polling_rejects_duo_model_when_backend_does_not_support_it(mock_support, provider):
    mock_support.return_value = SimpleNamespace(supported=False, request_field=None)

    with pytest.raises(DuoAPIError, match="does not support server-side Duo model selection"):
        provider.chat_polling("Hi", duo_model="probe-model")
