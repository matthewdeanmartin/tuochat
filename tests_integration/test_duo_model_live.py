"""Live provider probe for GitLab Duo server-side model selection support.

Run explicitly with:
    $env:UV_CACHE_DIR='.uv-cache'; uv run pytest --basetemp=tmp_pytest tests_integration\test_duo_model_live.py -q
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from tuochat.config import load_dotenv
from tuochat.provider.duo import DUO_CHAT_MODEL_FIELD_CANDIDATES, DuoProvider

REPO_ROOT = Path(__file__).resolve().parent.parent
DUO_MODEL_DEFINITION_PATH_CANDIDATES = (
    "/api/v4/ai_gateway/v1/models/definitions",
    "/api/v4/ai_gateway/v1/models/definitions/",
    "/-/ai_gateway/v1/models/definitions",
    "/-/ai_gateway/v1/models/definitions/",
    "/api/v1/models/definitions",
)


def require_live_duo_provider() -> SimpleNamespace:
    """Load live Duo credentials from the environment or repo-local .env."""
    load_dotenv(REPO_ROOT / ".env")
    host = os.environ.get("TUOCHAT_GITLAB_HOST")
    token = os.environ.get("TUOCHAT_GITLAB_TOKEN")
    token_type = os.environ.get("TUOCHAT_GITLAB_TOKEN_TYPE", "pat")

    if not host or not token:
        pytest.skip("Live Duo credentials are not configured in TUOCHAT_GITLAB_HOST/TUOCHAT_GITLAB_TOKEN.")

    provider = DuoProvider(host=host, token=token, token_type=token_type)
    user = provider.get_current_user()
    if not user.duo_chat_available:
        pytest.skip("The configured GitLab account does not have Duo Chat available.")

    return SimpleNamespace(provider=provider)


def live_get(provider: DuoProvider, path: str) -> tuple[int, str]:
    """Return the raw status code and body for a live GitLab GET request."""
    request = urllib.request.Request(f"{provider.host}{path}", headers=provider.request_headers())
    try:
        with provider.urlopen(request, 30) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def test_live_duo_model_probe_reports_supported_field_or_explicit_rejection() -> None:
    """Exercise the real GitLab Duo endpoint to discover chat-model support."""
    live = require_live_duo_provider()

    support = live.provider.probe_duo_chat_model_support(refresh=True)

    attempted_fields = [attempt.field_name for attempt in support.attempts]
    assert attempted_fields == list(DUO_CHAT_MODEL_FIELD_CANDIDATES[: len(attempted_fields)])

    if support.supported:
        assert support.request_field in DUO_CHAT_MODEL_FIELD_CANDIDATES
        assert support.attempts[-1].accepted is True
    else:
        assert support.reason
        assert attempted_fields == list(DUO_CHAT_MODEL_FIELD_CANDIDATES)
        assert all(attempt.error_code == "argumentNotAccepted" for attempt in support.attempts)
        assert all("AiChatInput" in (attempt.error_message or "") for attempt in support.attempts)


@pytest.mark.parametrize(
    ("query", "input_name", "argument_name"),
    [
        (
            """mutation probe {
              aiAction(
                input: {
                  chat: { content: "/reset" }
                  modelMetadata: { provider: "gitlab", identifier: "probe" }
                  platformOrigin: "tuochat-model-probe"
                }
              ) {
                requestId
                errors
              }
            }""",
            "AiActionInput",
            "modelMetadata",
        ),
        (
            """mutation probe {
              aiAction(
                input: {
                  chat: {
                    content: "/reset"
                    modelMetadata: { provider: "gitlab", identifier: "probe" }
                  }
                  platformOrigin: "tuochat-model-probe"
                }
              ) {
                requestId
                errors
              }
            }""",
            "AiChatInput",
            "modelMetadata",
        ),
    ],
)
def test_live_gitlab_graphql_rejects_model_metadata_override(
    query: str, input_name: str, argument_name: str
) -> None:
    """Confirm the public GitLab GraphQL entrypoint does not expose ai-assist model_metadata."""
    live = require_live_duo_provider()

    result = live.provider.graphql(query)

    errors = result.get("errors", [])
    assert errors
    error = errors[0]
    assert error["extensions"]["code"] == "argumentNotAccepted"
    assert error["extensions"]["name"] == input_name
    assert error["extensions"]["argumentName"] == argument_name


def test_live_gitlab_host_does_not_expose_model_definitions_catalog() -> None:
    """Record whether the current GitLab host exposes the ai-assist model catalog."""
    live = require_live_duo_provider()

    results = [live_get(live.provider, path) for path in DUO_MODEL_DEFINITION_PATH_CANDIDATES]

    assert all(status != 200 for status, _body in results)
    assert any(status in {403, 404} for status, _body in results)
