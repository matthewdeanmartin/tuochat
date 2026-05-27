"""Live integration tests for leading-response garbling in saved artifacts.

These tests hit the real GitLab Duo API, persist the resulting conversation
markdown to disk through the normal session path, then read the saved file back
to inspect the beginning of the assistant response.

Run explicitly with:
    $env:UV_CACHE_DIR='.uv-cache'; uv run pytest --basetemp=tmp_pytest tests_integration\test_response_garbling_live.py -q
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from tuochat.cli import session
from tuochat.cli.models import ReplState
from tuochat.config import TuochatConfig, load_dotenv
from tuochat.models import Conversation
from tuochat.persistence.store import ConversationStore
from tuochat.provider.duo import DuoProvider

SCENARIOS = [
    {
        "id": "streaming-merge-request",
        "streaming": True,
        "prefix": "Case1:",
        "prompt": (
            "Begin your response with the exact text 'Case1:' and continue in plain English. "
            "Do not use markdown, bullet points, code fences, or quotes around the prefix. "
            "In exactly two short sentences, explain what a merge request is in GitLab."
        ),
    },
    {
        "id": "streaming-branches",
        "streaming": True,
        "prefix": "Case2:",
        "prompt": (
            "Begin your response with the exact text 'Case2:' and continue in plain English. "
            "Do not use markdown, bullet points, code fences, or quotes around the prefix. "
            "In exactly two short sentences, explain when a GitLab branch is useful."
        ),
    },
    {
        "id": "nonstreaming-issues",
        "streaming": False,
        "prefix": "Case3:",
        "prompt": (
            "Begin your response with the exact text 'Case3:' and continue in plain English. "
            "Do not use markdown, bullet points, code fences, or quotes around the prefix. "
            "Write one short paragraph explaining what a GitLab issue is."
        ),
    },
    {
        "id": "nonstreaming-pipeline",
        "streaming": False,
        "prefix": "Case4:",
        "prompt": (
            "Begin your response with the exact text 'Case4:' and continue in plain English. "
            "Do not use markdown, bullet points, code fences, or quotes around the prefix. "
            "In exactly two short sentences, explain what a GitLab pipeline does."
        ),
    },
]


def extract_last_assistant_message(markdown: str) -> str:
    """Return the last assistant section from a saved conversation markdown file."""
    matches = re.findall(r"^## Assistant\s*\n\n(.*?)(?=^## |\Z)", markdown, flags=re.MULTILINE | re.DOTALL)
    if not matches:
        raise AssertionError("Saved markdown did not contain an assistant section.")
    return matches[-1].strip()


def assert_clean_beginning(assistant_text: str, *, expected_prefix: str) -> None:
    """Fail when the saved response begins with suspicious or garbled text."""
    beginning = assistant_text.lstrip()
    excerpt = beginning[:160]
    assert excerpt, "Assistant response was empty in the saved artifact."
    assert beginning.startswith(expected_prefix), f"Expected saved response to start with {expected_prefix!r}, got: {excerpt!r}"
    assert "\ufeff" not in excerpt, f"Saved response began with a BOM: {excerpt!r}"
    assert "\ufffd" not in excerpt, f"Saved response began with replacement characters: {excerpt!r}"
    assert "\x00" not in excerpt, f"Saved response began with a NUL byte: {excerpt!r}"
    assert all(char.isprintable() or char in "\r\n\t" for char in excerpt), f"Saved response began with control characters: {excerpt!r}"

    english_tail = excerpt[len(expected_prefix) :].lstrip()
    assert english_tail, f"Saved response had no text after the expected prefix: {excerpt!r}"
    assert any(char.isalpha() for char in english_tail[:40]), f"Saved response did not look like English near the start: {excerpt!r}"


@pytest.fixture(scope="session")
def live_gitlab_credentials() -> SimpleNamespace:
    """Load live Duo credentials from the environment or repo-local .env."""
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    host = os.environ.get("TUOCHAT_GITLAB_HOST")
    token = os.environ.get("TUOCHAT_GITLAB_TOKEN")
    token_type = os.environ.get("TUOCHAT_GITLAB_TOKEN_TYPE", "pat")

    if not host or not token:
        pytest.skip("Live Duo credentials are not configured in TUOCHAT_GITLAB_HOST/TUOCHAT_GITLAB_TOKEN.")

    provider = DuoProvider(host=host, token=token, token_type=token_type)
    user = provider.get_current_user()
    if not user.duo_chat_available:
        pytest.skip("The configured GitLab account does not have Duo Chat available.")
    provider.reset_conversation()

    return SimpleNamespace(host=host, token=token, token_type=token_type)


@pytest.fixture()
def live_state(tmp_path: Path, live_gitlab_credentials: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> ReplState:
    """Create a fresh live REPL state and hard-reset server-side history."""
    cfg = TuochatConfig(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
    )
    cfg.gitlab.host = live_gitlab_credentials.host
    cfg.gitlab.token = live_gitlab_credentials.token
    cfg.gitlab.token_type = live_gitlab_credentials.token_type
    cfg.notifications.long_request_bell_enabled = False
    cfg.chat.response_footer_warning_enabled = False

    provider = DuoProvider(
        host=cfg.gitlab.host,
        token=cfg.gitlab.token,
        token_type=cfg.gitlab.token_type,
        platform_origin=cfg.chat.platform_origin,
        timeout=cfg.chat.timeout,
        websocket_welcome_timeout=cfg.chat.websocket_welcome_timeout,
        websocket_subscription_timeout=cfg.chat.websocket_subscription_timeout,
    )
    provider.reset_conversation()

    with ConversationStore(cfg.db_path) as store:
        state = ReplState(
            conv=Conversation(resource_id=cfg.chat.default_resource_id),
            store=store,
            provider=provider,
            cfg=cfg,
            streaming=True,
            quiet=True,
            no_banner=True,
            blind_mode=False,
            debug=False,
            mask_output=False,
            dot_timer_enabled=False,
            no_code_mode=False,
            verbose=False,
            local_writes_enabled=True,
        )
        state.pending_attachment_messages = []
        state.pending_attachment_names = []
        state.command_log = []
        monkeypatch.setattr(session, "retry_failure_action", lambda: "abort")

        try:
            yield state
        finally:
            try:
                provider.reset_conversation()
            except Exception:
                pass


def run_turn_and_read_saved_markdown(state: ReplState, prompt: str, *, streaming: bool) -> tuple[Path, str]:
    """Send one live turn, then read back the saved markdown artifact."""
    state.streaming = streaming
    session.send_chat_turn(state, prompt)

    markdown_path = state.last_saved_markdown_path
    assert markdown_path is not None, "No conversation markdown path was recorded after the live turn."
    assert markdown_path.is_file(), f"Conversation markdown was not written: {markdown_path}"

    markdown = markdown_path.read_text(encoding="utf-8")
    assistant_text = extract_last_assistant_message(markdown)
    assert state.conv.messages, "Conversation did not record any messages after the live turn."
    assert state.conv.messages[-1].role == "assistant"
    assert state.conv.messages[-1].content.strip() == assistant_text
    return markdown_path, assistant_text


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[scenario["id"] for scenario in SCENARIOS])
def test_saved_duo_response_begins_cleanly(live_state: ReplState, scenario: dict[str, object]) -> None:
    """Verify saved live Duo responses do not begin with garbled text."""
    markdown_path, assistant_text = run_turn_and_read_saved_markdown(
        live_state,
        str(scenario["prompt"]),
        streaming=bool(scenario["streaming"]),
    )

    assert_clean_beginning(assistant_text, expected_prefix=str(scenario["prefix"]))
    saved_markdown = markdown_path.read_text(encoding="utf-8")
    assert "## Assistant" in saved_markdown
    assert str(scenario["prefix"]) in saved_markdown
