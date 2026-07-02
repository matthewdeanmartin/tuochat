"""Live integration test for Duo server-side continuity via `headless continue ongoing`.

This test launches two separate headless CLI runs against the real Duo backend.
The second run must recall a nonce from the first run without local transcript
replay, which exercises the `ongoing` reserved conversation target.

Run explicitly with:
    $env:UV_CACHE_DIR='.uv-cache'; uv run pytest --basetemp=tmp_pytest tests_integration\test_headless_ongoing_live.py -q
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from tuochat.config import load_dotenv
from tuochat.persistence.store import ConversationStore
from tuochat.provider.duo import DuoProvider
from tuochat.serialization import json_loads

ONGOING_CONVERSATION_ID = "ongoing"
REPO_ROOT = Path(__file__).resolve().parent.parent


def require_live_gitlab_credentials() -> SimpleNamespace:
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

    return SimpleNamespace(host=host, token=token, token_type=token_type, provider=provider)


@pytest.fixture()
def live_headless_env(tmp_path: Path) -> SimpleNamespace:
    """Prepare isolated config/data dirs while keeping the live Duo credentials."""
    credentials = require_live_gitlab_credentials()
    provider = credentials.provider
    provider.reset_conversation()

    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    config_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["TUOCHAT_GITLAB_HOST"] = credentials.host
    env["TUOCHAT_GITLAB_TOKEN"] = credentials.token
    env["TUOCHAT_GITLAB_TOKEN_TYPE"] = credentials.token_type
    env["TUOCHAT_CONFIG_DIR"] = str(config_dir)
    env["TUOCHAT_DATA_DIR"] = str(data_dir)
    env.setdefault("PYTHONUTF8", "1")

    try:
        yield SimpleNamespace(env=env, data_dir=data_dir, provider=provider)
    finally:
        try:
            provider.reset_conversation()
        except Exception:
            pass


def run_headless_continue_ongoing(env: dict[str, str], prompt: str) -> dict[str, object]:
    """Run one real headless Duo command and return the parsed JSON payload."""
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "tuochat",
            "headless",
            "continue",
            ONGOING_CONVERSATION_ID,
            "--model",
            "duo",
            "--json",
            "--no-stream",
            "--timeout",
            "180",
            prompt,
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        "Headless Duo run failed.\n" f"STDOUT:\n{result.stdout}\n" f"STDERR:\n{result.stderr}"
    )
    assert result.stderr == ""
    return json_loads(result.stdout)


def test_headless_continue_ongoing_recalls_prior_turn_without_local_replay(live_headless_env: SimpleNamespace) -> None:
    """Prove live Duo continuity across separate headless invocations."""
    nonce = f"ongoing-memory-{uuid.uuid4().hex[:12]}"
    first_prompt = (
        f"Memory test. Remember this exact code for a later question in this same conversation: {nonce}. "
        "Reply with exactly STORED."
    )
    second_prompt = (
        "What exact code did I ask you to remember earlier in this same conversation? "
        "Reply with only the code and nothing else."
    )

    first_payload = run_headless_continue_ongoing(live_headless_env.env, first_prompt)
    second_payload = run_headless_continue_ongoing(live_headless_env.env, second_prompt)

    assert first_payload["conversation_id"] == ONGOING_CONVERSATION_ID
    assert second_payload["conversation_id"] == ONGOING_CONVERSATION_ID
    assert "stored" in str(first_payload["response_text"]).strip().casefold()
    assert nonce in str(second_payload["response_text"])

    store = ConversationStore(live_headless_env.data_dir / "tuochat.db")
    try:
        messages = store.get_messages(ONGOING_CONVERSATION_ID)
    finally:
        store.close()

    user_messages = [message.content for message in messages if message.role == "user"]
    assistant_messages = [message.content for message in messages if message.role == "assistant"]

    assert len(user_messages) >= 2
    assert len(assistant_messages) >= 2
    assert user_messages[0] == first_prompt
    assert user_messages[1] == second_prompt
    assert nonce not in user_messages[1]
