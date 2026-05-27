"""Unit tests for REPL helper functions."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tuochat.cli import repl
from tuochat.cli.command_models import GlobalOptions
from tuochat.config import TuochatConfig
from tuochat.models import Conversation


class ConversationStoreStub:
    """Minimal store stub for REPL helper tests."""

    def __init__(self, *, conversations: list[Conversation] | None = None, expired: list[Conversation] | None = None):
        self.conversations = list(conversations or [])
        self.expired = list(expired or [])
        self.deleted: list[str] = []
        self.cutoff: str | None = None

    def list_conversations(self, limit: int) -> list[Conversation]:
        return list(self.conversations[:limit])

    def list_expired_conversations(self, cutoff_iso: str) -> list[Conversation]:
        self.cutoff = cutoff_iso
        return list(self.expired)

    def delete_conversation(self, conversation_id: str) -> bool:
        self.deleted.append(conversation_id)
        return True


def test_global_options_from_args_reads_all_flags():
    args = SimpleNamespace(debug=True, config="settings.toml", no_banner=True, quiet=True, blind=True)

    options = repl.global_options_from_args(args)

    assert options == GlobalOptions(
        debug=True,
        config_path=Path("settings.toml"),
        no_banner=True,
        quiet=True,
        blind=True,
    )


def test_load_config_applies_overrides_and_disables_file_logging_in_no_write_mode():
    cfg = TuochatConfig()
    cfg.chat.no_write = True

    with (
        patch("tuochat.config.load_config", return_value=cfg) as load_config,
        patch("tuochat.logging_config.setup_logging") as setup_logging,
    ):
        loaded = repl.load_config_with_cli_overrides(
            GlobalOptions(debug=True, config_path=Path("cli.toml"), blind=True)
        )

    assert loaded is cfg
    assert cfg.chat.blind is True
    assert cfg.chat.no_banner is True
    load_config.assert_called_once_with("cli.toml")
    setup_logging.assert_called_once_with(log_dir=cfg.log_dir, debug=True, enable_file_logging=False)


@pytest.mark.parametrize(
    ("raw_input", "expected"),
    [
        ("quit", True),
        (" /exit ", True),
        ("continue", False),
    ],
)
def test_is_exit_command_only_matches_explicit_exit_words(raw_input, expected):
    assert repl.is_exit_command(raw_input) is expected


def test_normalize_command_candidate_strips_only_leading_whitespace():
    assert repl.normalize_command_candidate("   /help  now") == "/help  now"


def test_maybe_prune_expired_conversations_keeps_items_when_user_declines(capsys):
    expired = [
        Conversation(id="expired-1", title="Old 1", updated_at="2024-01-02T03:04:05+00:00"),
        Conversation(id="expired-2", title="Old 2", updated_at="2024-01-03T03:04:05+00:00"),
    ]
    store = ConversationStoreStub(expired=expired)
    cfg = SimpleNamespace(chat=SimpleNamespace(conversation_expiration_days=30), config_file=Path("config.toml"))

    with patch("tuochat.cli.repl.prompt_input", return_value="n"):
        repl.maybe_prune_expired_conversations(store, cfg)

    assert store.cutoff is not None
    assert store.deleted == []
    captured = capsys.readouterr()
    assert "eligible for deletion" in captured.out
    assert "Expired conversations were kept." in captured.out


def test_maybe_prune_expired_conversations_deletes_confirmed_items(capsys):
    expired = [
        Conversation(id="expired-1", title="Old 1", updated_at="2024-01-02T03:04:05+00:00"),
        Conversation(id="expired-2", title="Old 2", updated_at="2024-01-03T03:04:05+00:00"),
    ]
    store = ConversationStoreStub(expired=expired)
    cfg = SimpleNamespace(chat=SimpleNamespace(conversation_expiration_days=7), config_file=Path("config.toml"))

    with patch("tuochat.cli.repl.prompt_input", return_value="yes"):
        repl.maybe_prune_expired_conversations(store, cfg)

    assert store.deleted == ["expired-1", "expired-2"]
    captured = capsys.readouterr()
    assert "Deleted 2 expired conversation(s)." in captured.out


def test_nuke_targets_deduplicates_log_dir_when_it_is_inside_data_dir(tmp_path):
    nested_log_dir = tmp_path / "logs"
    nested_log_dir.mkdir()
    cache_file = tmp_path / "cache.db"
    cache_file.write_text("data", encoding="utf-8")
    cfg = SimpleNamespace(data_dir=tmp_path, log_dir=nested_log_dir)

    targets = repl.nuke_targets(cfg)

    assert [path.name for path in targets] == ["cache.db", "logs"]


def test_delete_path_removes_files_and_directories(tmp_path):
    file_path = tmp_path / "file.txt"
    file_path.write_text("hello", encoding="utf-8")
    dir_path = tmp_path / "dir"
    dir_path.mkdir()
    (dir_path / "nested.txt").write_text("world", encoding="utf-8")

    repl.delete_path(file_path)
    repl.delete_path(dir_path)

    assert file_path.exists() is False
    assert dir_path.exists() is False


def test_execute_pending_nuke_reports_partial_failures(capsys, tmp_path):
    path_one = tmp_path / "one"
    path_one.mkdir()
    path_two = tmp_path / "two.txt"
    path_two.write_text("x", encoding="utf-8")
    state = SimpleNamespace(
        pending_nuke=True,
        cfg=SimpleNamespace(data_dir=tmp_path, log_dir=tmp_path / "logs", config_dir=tmp_path / "config"),
    )

    with (
        patch("tuochat.cli.repl.nuke_targets", return_value=[path_one, path_two]),
        patch("tuochat.cli.repl.delete_path", side_effect=[None, OSError("denied")]),
    ):
        repl.execute_pending_nuke(state)

    captured = capsys.readouterr()
    assert "Nuke partial: deleted 1 path(s), failed to delete 1 path(s)." in captured.out
    assert f"Config kept: {state.cfg.config_dir}" in captured.out
    assert "Nuke failed to delete" in captured.err


def test_execute_pending_nuke_reports_when_nothing_is_present(capsys, tmp_path):
    state = SimpleNamespace(
        pending_nuke=True,
        cfg=SimpleNamespace(data_dir=tmp_path, log_dir=tmp_path / "logs", config_dir=tmp_path / "config"),
    )

    with patch("tuochat.cli.repl.nuke_targets", return_value=[]):
        repl.execute_pending_nuke(state)

    captured = capsys.readouterr()
    assert "Nuke complete: no centralized app data was present." in captured.out


def test_resolve_conversation_id_returns_single_match():
    match = Conversation(id="alpha-1234", title="Alpha")
    store = ConversationStoreStub(conversations=[match, Conversation(id="beta-9999", title="Beta")])

    resolved = repl.resolve_conversation_id(store, "alpha")

    assert resolved == "alpha-1234"


def test_resolve_conversation_id_reports_ambiguous_matches(capsys):
    store = ConversationStoreStub(
        conversations=[
            Conversation(id="alpha-1234", title="Alpha"),
            Conversation(id="alpha-5678", title="Alpha 2"),
        ]
    )

    resolved = repl.resolve_conversation_id(store, "alpha")

    assert resolved is None
    captured = capsys.readouterr()
    assert "Ambiguous ID 'alpha'" in captured.err
    assert "alpha-1234  Alpha" in captured.err


def test_pick_conversation_id_returns_numbered_selection():
    conversations = [
        Conversation(id="conv-1", title="One", updated_at="2025-01-01T00:00:00+00:00"),
        Conversation(id="conv-2", title="Two", updated_at="2025-01-02T00:00:00+00:00"),
    ]
    store = ConversationStoreStub(conversations=conversations)

    with patch("tuochat.cli.repl.prompt_input", return_value="2"):
        picked = repl.pick_conversation_id(store, "resume")

    assert picked == "conv-2"


def test_pick_conversation_id_rejects_out_of_range_selection(capsys):
    store = ConversationStoreStub(conversations=[Conversation(id="conv-1", title="One")])

    with patch("tuochat.cli.repl.prompt_input", return_value="3"):
        picked = repl.pick_conversation_id(store, "resume")

    assert picked is None
    captured = capsys.readouterr()
    assert "Selection out of range." in captured.err


def test_pick_conversation_id_delegates_partial_lookup():
    store = ConversationStoreStub(conversations=[Conversation(id="conv-1", title="One")])

    with (
        patch("tuochat.cli.repl.prompt_input", return_value="conv"),
        patch("tuochat.cli.repl.resolve_conversation_id", return_value="conv-1") as resolve_conversation_id,
    ):
        picked = repl.pick_conversation_id(store, "resume")

    assert picked == "conv-1"
    resolve_conversation_id.assert_called_once_with(store, "conv")


# ---------------------------------------------------------------------------
# Bang command tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw_input", "expected_command"),
    [
        ("!ls", "ls"),
        ("! ls", "ls"),
        ("  !ls", "ls"),
        ("\n  !git status", "git status"),
        ("!echo hello world", "echo hello world"),
    ],
)
def test_extract_bang_command_recognises_bang_prefix(raw_input, expected_command):
    result = repl.extract_bang_command(raw_input)
    assert result is not None
    assert result.strip() == expected_command


@pytest.mark.parametrize(
    "raw_input",
    [
        "ls",
        "/help",
        "hello world",
        "",
        "   ",
    ],
)
def test_extract_bang_command_returns_none_for_non_bang_input(raw_input):
    assert repl.extract_bang_command(raw_input) is None


def test_extract_bang_command_returns_empty_string_for_bare_bang():
    result = repl.extract_bang_command("!")
    assert result is not None
    assert result.strip() == ""


def make_state():
    """Return a minimal ReplState-like SimpleNamespace for bang command tests."""
    return SimpleNamespace(
        pending_attachment_messages=[],
        pending_attachment_names=[],
    )


def test_handle_bang_command_runs_command_and_prints_output(capsys):
    state = make_state()

    with patch("tuochat.cli.repl.subprocess.run") as mock_run:
        mock_run.return_value = SimpleNamespace(stdout="file1\nfile2\n", stderr="", returncode=0)
        with patch("tuochat.cli.repl.prompt_bool", return_value=False):
            handled = repl.handle_bang_command("!ls", state)

    assert handled is True
    captured = capsys.readouterr()
    assert "$ ls" in captured.out
    assert "file1" in captured.out


def test_handle_bang_command_returns_false_for_non_bang_input():
    state = make_state()
    handled = repl.handle_bang_command("hello", state)
    assert handled is False


def test_handle_bang_command_prints_usage_for_bare_bang(capsys):
    state = make_state()
    handled = repl.handle_bang_command("!", state)
    assert handled is True
    captured = capsys.readouterr()
    assert "Usage" in captured.err


def test_handle_bang_command_queues_attachment_when_user_confirms(capsys):
    state = make_state()

    with patch("tuochat.cli.repl.subprocess.run") as mock_run:
        mock_run.return_value = SimpleNamespace(stdout="output\n", stderr="", returncode=0)
        with patch("tuochat.cli.repl.prompt_bool", return_value=True):
            repl.handle_bang_command("!ls", state)

    assert len(state.pending_attachment_messages) == 1
    assert len(state.pending_attachment_names) == 1
    attachment = state.pending_attachment_messages[0]
    assert "$ ls" in attachment
    assert "output" in attachment
    assert "```" in attachment


def test_handle_bang_command_does_not_queue_when_user_declines():
    state = make_state()

    with patch("tuochat.cli.repl.subprocess.run") as mock_run:
        mock_run.return_value = SimpleNamespace(stdout="output\n", stderr="", returncode=0)
        with patch("tuochat.cli.repl.prompt_bool", return_value=False):
            repl.handle_bang_command("!ls", state)

    assert state.pending_attachment_messages == []


def test_handle_bang_command_merges_stderr_into_output(capsys):
    state = make_state()

    with patch("tuochat.cli.repl.subprocess.run") as mock_run:
        mock_run.return_value = SimpleNamespace(stdout="", stderr="error text\n", returncode=1)
        with patch("tuochat.cli.repl.prompt_bool", return_value=False):
            repl.handle_bang_command("!badcmd", state)

    captured = capsys.readouterr()
    assert "error text" in captured.out
    assert "[exit 1]" in captured.err


def test_handle_bang_command_handles_oserror_gracefully(capsys):
    state = make_state()

    with patch("tuochat.cli.repl.subprocess.run", side_effect=OSError("not found")):
        handled = repl.handle_bang_command("!ls", state)

    assert handled is True
    captured = capsys.readouterr()
    assert "not found" in captured.err
    assert state.pending_attachment_messages == []


def test_handle_bang_command_attachment_contains_command_label():
    state = make_state()

    with patch("tuochat.cli.repl.subprocess.run") as mock_run:
        mock_run.return_value = SimpleNamespace(stdout="result\n", stderr="", returncode=0)
        with patch("tuochat.cli.repl.prompt_bool", return_value=True):
            repl.handle_bang_command("!git log --oneline", state)

    name = state.pending_attachment_names[0]
    assert "git log --oneline" in str(name)


def test_process_repl_submission_bang_command_is_handled_without_chat_turn():
    state = make_state()

    with (
        patch("tuochat.cli.repl.handle_bang_command", return_value=True) as mock_bang,
        patch("tuochat.cli.repl.send_chat_turn") as mock_send,
    ):
        result = repl.process_repl_submission(state, "!ls")

    assert result is False
    mock_bang.assert_called_once_with("!ls", state)
    mock_send.assert_not_called()


def test_process_repl_submission_non_bang_reaches_slash_command_dispatch():
    state = make_state()

    with (
        patch("tuochat.cli.repl.handle_bang_command", return_value=False),
        patch("tuochat.cli.repl.handle_slash_command", return_value=(None, False)) as mock_slash,
    ):
        repl.process_repl_submission(state, "/help")

    mock_slash.assert_called_once()


# ---------------------------------------------------------------------------
# Original process_repl_submission tests
# ---------------------------------------------------------------------------


def test_process_repl_submission_exits_for_slash_quit(tmp_path):
    state = SimpleNamespace()

    with patch("tuochat.cli.repl.handle_slash_command", return_value=(None, True)):
        assert repl.process_repl_submission(state, "/quit") is True


def test_process_repl_submission_sends_chat_turn_for_non_command(tmp_path):
    state = SimpleNamespace()

    with (
        patch("tuochat.cli.repl.handle_slash_command", return_value=("hello", False)),
        patch("tuochat.cli.repl.send_chat_turn") as send_chat_turn,
    ):
        assert repl.process_repl_submission(state, "hello", original_handler="orig", sigint_handler="sig") is False

    send_chat_turn.assert_called_once_with(state, "hello", original_handler="orig", sigint_handler="sig")
