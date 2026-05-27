from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from tuochat.cli.command_models import HeadlessContinueCommand
from tuochat.cli.commands.headless_cmd import ONGOING_CONVERSATION_ID, run_headless_continue
from tuochat.config import TuochatConfig
from tuochat.persistence.store import ConversationStore
from tuochat.provider.duo import DuoProvider


class RecordingDuoProvider(DuoProvider):
    def __init__(self) -> None:
        self.questions: list[str] = []
        self.reset_calls = 0

    def chat(self, question, resource_id=None, streaming=True, cancel=None, additional_context=None):
        _ = (resource_id, streaming, cancel, additional_context)
        self.questions.append(question)
        yield "ok"

    def get_last_chat_diagnostics(self):
        return SimpleNamespace(request_id=None)

    def reset_conversation(self) -> None:
        self.reset_calls += 1


def make_config(tmp_path):
    cfg = TuochatConfig()
    cfg.data_dir = tmp_path / "data"
    cfg.config_dir = tmp_path / "config"
    cfg.log_dir = tmp_path / "logs"
    cfg.gitlab.host = "https://gitlab.example.com"
    cfg.gitlab.token = "glpat-test"
    return cfg


def build_store_factory(db_path):
    def factory(cfg):
        _ = cfg
        return ConversationStore(db_path)

    return factory


def test_run_headless_continue_ongoing_preserves_server_context_without_replay(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = make_config(tmp_path)
    provider = RecordingDuoProvider()
    resolve_conversation_id = MagicMock(side_effect=AssertionError("ongoing should bypass local ID resolution"))
    build_store = build_store_factory(tmp_path / "ongoing.db")

    first_command = HeadlessContinueCommand(
        id=ONGOING_CONVERSATION_ID,
        prompt="First prompt",
        json_output=True,
        model="duo",
    )
    second_command = HeadlessContinueCommand(
        id=ONGOING_CONVERSATION_ID,
        prompt="Second prompt",
        json_output=True,
        model="duo",
    )

    first_result = run_headless_continue(
        cfg,
        first_command,
        build_provider=lambda cfg, timeout: provider,
        build_store=build_store,
        resolve_conversation_id=resolve_conversation_id,
    )
    first_output = capsys.readouterr()

    second_result = run_headless_continue(
        cfg,
        second_command,
        build_provider=lambda cfg, timeout: provider,
        build_store=build_store,
        resolve_conversation_id=resolve_conversation_id,
    )
    second_output = capsys.readouterr()

    assert first_result == 0
    assert second_result == 0
    assert first_output.err == ""
    assert second_output.err == ""
    assert provider.questions == ["First prompt", "Second prompt"]
    assert provider.reset_calls == 0
    resolve_conversation_id.assert_not_called()

    store = ConversationStore(tmp_path / "ongoing.db")
    try:
        conversation = store.get_conversation(ONGOING_CONVERSATION_ID)
        messages = store.get_messages(ONGOING_CONVERSATION_ID)
    finally:
        store.close()

    assert conversation is not None
    assert len(messages) == 4
