"""Tests for the CLI."""

from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tuochat.__about__ import __version__
from tuochat.cli import bootstrap
from tuochat.cli.command_models import ConfigCommand, HistoryCommand
from tuochat.cli.commands import config_cmd, history_cmd
from tuochat.cli.prompts import prompt_input, read_user_message
from tuochat.cli.rendering import (
    print_context,
    print_conversation_transcript,
    print_files,
    print_session_intro,
    print_turn_estimate,
)
from tuochat.cli.repl import cmd_search, handle_slash_command, main, print_help_menu, print_help_menu_section
from tuochat.cli.session import ReplState, send_chat_turn, stream_safe_display_length, sync_conversation_artifacts
from tuochat.config import TuochatConfig
from tuochat.constants import ARCHIVE_ID_MARKER
from tuochat.context.recipes import Recipe, RecipeMatch
from tuochat.models import Conversation, Message, Role
from tuochat.persistence.archive import check_archive_bagit_status, extract_code_files, refresh_archive_bagit_metadata
from tuochat.persistence.store import ConversationStore, NullConversationStore
from tuochat.provider.duo import DuoChatModelSupport, DuoProvider
from tuochat.provider.eliza import ElizaProvider
from tuochat.security.masking import display_text
from tuochat.serialization import json_dumps, json_loads


def test_cli_help(capsys):
    """Test that the CLI help message is displayed."""
    with patch.object(sys, "argv", ["tuochat", "--help"]):
        try:
            main()
        except SystemExit:
            pass
    captured = capsys.readouterr()
    assert "usage: tuochat" in captured.out
    assert "GitLab Duo Chat client" in captured.out


def test_cli_version(capsys):
    """Test that the CLI version message is displayed."""
    with patch.object(sys, "argv", ["tuochat", "--version"]):
        try:
            main()
        except SystemExit:
            pass
    captured = capsys.readouterr()
    assert __version__ in captured.out or __version__ in captured.err


def test_cli_no_args(capsys):
    """Test that no args prints help."""
    with (
        patch.object(sys, "argv", ["tuochat"]),
        patch("tuochat.cli.repl.is_first_run", return_value=False),
    ):
        result = main()
    assert result == 0
    captured = capsys.readouterr()
    assert "usage: tuochat" in captured.out


def test_cli_help_mentions_grouped_local_commands(capsys):
    """Test that help advertises the grouped local command surface."""
    with patch.object(sys, "argv", ["tuochat", "--help"]):
        try:
            main()
        except SystemExit:
            pass
    captured = capsys.readouterr()
    assert "convo" in captured.out
    assert "archive" in captured.out
    assert "context" in captured.out
    assert "headless" in captured.out


def test_headless_ask_eliza_json_supports_includes_and_persists(capsys, tmp_path, monkeypatch):
    """Test a happy-path headless Eliza request with JSON output and file includes."""
    monkeypatch.chdir(tmp_path)
    include_path = tmp_path / "prompt.txt"
    include_path.write_text("attached context", encoding="utf-8")
    cfg = TuochatConfig()
    cfg.data_dir = tmp_path / "data"
    cfg.config_dir = tmp_path / "config"
    cfg.log_dir = tmp_path / "logs"

    class DeterministicHeadlessElizaProvider:
        """Simple deterministic provider for headless tests."""

        def chat(self, question, streaming=True, **kwargs):
            _ = (question, kwargs)
            response = "Deterministic headless response."
            if streaming:
                yield "Deterministic"
                yield " headless response."
            else:
                yield response

    with (
        patch("tuochat.cli.repl.load_config", return_value=cfg),
        patch("tuochat.cli.commands.headless_cmd.ElizaProvider", DeterministicHeadlessElizaProvider),
    ):
        result = main(
            [
                "headless",
                "ask",
                "--model",
                "eliza",
                "--json",
                "--include",
                "prompt.txt",
                "Please summarize the attached context for me.",
            ]
        )

    assert result == 0
    captured = capsys.readouterr()
    payload = json_loads(captured.out)
    assert payload["model"] == "eliza"
    assert payload["response_text"] == "Deterministic headless response."
    assert payload["conversation_id"]
    assert payload["saved_markdown_path"] is not None
    assert Path(payload["saved_markdown_path"]).is_file()
    assert captured.err == ""


def test_config_json_keeps_stdout_valid_json_and_sends_warnings_to_stderr(capsys):
    """Test JSON config output remains parseable when validation emits warnings."""
    cfg = TuochatConfig()

    result = config_cmd.run(
        cfg,
        ConfigCommand(format="json"),
        render_markdown_config=lambda data: "unused",
    )

    assert result == 0
    captured = capsys.readouterr()
    payload = json_loads(captured.out)
    assert payload["gitlab"]["token"] == "(not set)"
    assert "GitLab host is not configured" in captured.err
    assert "GitLab token is not configured" in captured.err


def test_config_markdown_prints_warnings_to_stdout(capsys):
    """Test markdown config output still includes warnings in stdout."""
    cfg = TuochatConfig()

    result = config_cmd.run(
        cfg,
        ConfigCommand(format="markdown"),
        render_markdown_config=lambda data: "# Config",
    )

    assert result == 0
    captured = capsys.readouterr()
    assert "# Config" in captured.out
    assert "Warnings:" in captured.out
    assert captured.err == ""


def test_cli_history_empty(capsys, tmp_path):
    """Test history subcommand with no conversations."""
    config_file = tmp_path / "config.toml"
    config_file.write_text('[gitlab]\nhost = "https://gitlab.com"\ntoken = "glpat-test"\n')

    with (
        patch.object(sys, "argv", ["tuochat", "--config", str(config_file), "history"]),
        patch.dict(os.environ, {"TUOCHAT_DATA_DIR": str(tmp_path)}),
    ):
        result = main()
    assert result == 0
    captured = capsys.readouterr()
    assert "No conversations" in captured.out


def test_history_command_no_write_mode_skips_store(capsys):
    """Test typed history command reports no-write mode without building a store."""
    cfg = SimpleNamespace(chat=SimpleNamespace(no_write=True))

    result = history_cmd.run(
        cfg,
        HistoryCommand(limit=5),
        build_store=lambda: (_ for _ in ()).throw(AssertionError("build_store should not be called")),
        no_write_enabled=bootstrap.no_write_enabled,
    )

    assert result == 0
    captured = capsys.readouterr()
    assert "History is unavailable while no-write mode is enabled" in captured.out


def test_bootstrap_build_store_uses_null_store_for_no_write(tmp_path):
    """Test bootstrap returns a NullConversationStore when no-write is enabled."""
    cfg = TuochatConfig()
    cfg.data_dir = tmp_path
    cfg.chat.no_write = True

    with bootstrap.build_store(cfg) as store:
        assert isinstance(store, NullConversationStore)


def test_search_subcommand_prints_matches(capsys, tmp_path):
    """Test the search subcommand prints full-text matches."""
    with ConversationStore(tmp_path / "tuochat.db") as store:
        conv = Conversation(title="Terraform Drift")
        store.save_conversation(conv)
        store.save_message(Message(conversation_id=conv.id, role=Role.USER.value, content="terraform drift in prod"))

    cfg = SimpleNamespace(db_path=tmp_path / "tuochat.db")
    args = SimpleNamespace(
        query=["terraform", "drift"],
        limit=10,
        title=None,
        after=None,
        before=None,
    )

    result = cmd_search(cfg, args)

    assert result == 0


def test_slash_search_resumes_selected_conversation(capsys, tmp_path):
    """Test /search lets the user pick and resume a matching conversation."""
    with ConversationStore(tmp_path / "tuochat.db") as store:
        old_conv = Conversation(title="Old Search Target")
        current_conv = Conversation(title="Current Conversation")
        store.save_conversation(old_conv)
        store.save_conversation(current_conv)
        store.save_message(
            Message(conversation_id=old_conv.id, role=Role.USER.value, content="terraform drift in staging")
        )
        store.save_message(
            Message(conversation_id=old_conv.id, role=Role.ASSISTANT.value, content="Let's fix the terraform drift")
        )

        state = ReplState(
            conv=current_conv,
            store=store,
            provider=object(),
            cfg=SimpleNamespace(data_dir=tmp_path),
            streaming=True,
        )

        with patch("builtins.input", side_effect=["terraform drift", "1"]):
            message, should_exit = handle_slash_command("/search", state)

        assert message is None
        assert should_exit is False
        assert state.conv.id == old_conv.id
        captured = capsys.readouterr()
        assert "Search results for 'terraform drift'" in captured.out
        assert "Resumed: Old Search Target" in captured.out


def test_slash_no_write_prompts_and_enables(capsys, tmp_path):
    """Test /no-write without an argument explains choices and enables the mode."""
    with ConversationStore(tmp_path / "tuochat.db") as store:
        state = ReplState(
            conv=Conversation(title="Toggle Test"),
            store=store,
            provider=object(),
            cfg=SimpleNamespace(
                chat=SimpleNamespace(no_write=False), db_path=tmp_path / "tuochat.db", data_dir=tmp_path
            ),
            streaming=True,
            local_writes_enabled=True,
        )

        with patch("builtins.input", return_value="1"):
            message, should_exit = handle_slash_command("/no-write", state)

        assert message is None
        assert should_exit is False
        assert state.cfg.chat.no_write is True
        assert state.local_writes_enabled is False
        captured = capsys.readouterr()
        assert "Disable local database writes, filesystem writes, and file logging." in captured.out
        assert "Local writes disabled for this session." in captured.out


def test_slash_write_here_mode_prompts_and_enables(capsys, tmp_path, monkeypatch):
    """Test /write-here-mode without an argument explains choices and enables the mode."""
    monkeypatch.chdir(tmp_path)
    with ConversationStore(tmp_path / "tuochat.db") as store:
        state = ReplState(
            conv=Conversation(title="Write Here"),
            store=store,
            provider=object(),
            cfg=SimpleNamespace(
                chat=SimpleNamespace(no_write=False), db_path=tmp_path / "tuochat.db", data_dir=tmp_path
            ),
            streaming=True,
            local_writes_enabled=True,
        )

        with patch("builtins.input", return_value="1"):
            message, should_exit = handle_slash_command("/write-here-mode", state)

        assert message is None
        assert should_exit is False
        assert state.cfg.chat.write_here_mode is True
        captured = capsys.readouterr()
        assert "Named generated files will be written into the current working directory." in captured.out


def test_slash_write_here_mode_rejects_filesystem_root(capsys, tmp_path, monkeypatch):
    """Test /write-here-mode refuses to enable at a filesystem root."""
    root = tmp_path.anchor
    monkeypatch.chdir(root)
    state = ReplState(
        conv=Conversation(title="Root"),
        store=object(),
        provider=object(),
        cfg=SimpleNamespace(chat=SimpleNamespace(no_write=False), data_dir=tmp_path),
        streaming=True,
    )

    message, should_exit = handle_slash_command("/write-here-mode on", state)

    assert message is None
    assert should_exit is False
    assert not getattr(state.cfg.chat, "write_here_mode", False)
    captured = capsys.readouterr()
    assert "cannot be enabled when the current working directory is a filesystem root" in captured.err


def test_slash_approve_writes_toggles(capsys, tmp_path):
    """Test /approve-writes on toggles per-file approval for write-here mode."""
    with ConversationStore(tmp_path / "tuochat.db") as store:
        state = ReplState(
            conv=Conversation(title="Approve"),
            store=store,
            provider=object(),
            cfg=SimpleNamespace(chat=SimpleNamespace(no_write=False), data_dir=tmp_path),
            streaming=True,
        )

        message, should_exit = handle_slash_command("/approve-writes on", state)

        assert message is None
        assert should_exit is False
        assert state.cfg.chat.approve_writes is True
        captured = capsys.readouterr()
        assert "Approve-writes enabled for this session." in captured.out


def test_slash_approve_checks_does_not_touch_approve_writes(capsys, monkeypatch, tmp_path):
    draft_path = tmp_path / "draft.py.check"
    draft_path.write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    with ConversationStore(tmp_path / "tuochat.db") as store:
        state = ReplState(
            conv=Conversation(title="Approve Checks"),
            store=store,
            provider=object(),
            cfg=SimpleNamespace(chat=SimpleNamespace(no_write=False, approve_writes=False), data_dir=tmp_path),
            streaming=True,
        )

        message, should_exit = handle_slash_command("/approve-checks", state)

        assert message is None
        assert should_exit is False
        assert getattr(state.cfg.chat, "approve_writes", False) is False
        assert draft_path.exists() is False
        assert (tmp_path / "draft.py").is_file()
        captured = capsys.readouterr()
        assert "Approved 1 .check file(s)." in captured.out


def test_print_conversation_transcript_uses_blind_transitions(capsys):
    """Test blind transcript rendering avoids dash dividers."""
    conv = Conversation(title="Resume Test")
    conv.add_message(Role.USER.value, "hello")

    print_conversation_transcript(conv, blind_mode=True)

    captured = capsys.readouterr()
    assert "Next conversation" in captured.out
    assert "End conversation" in captured.out
    assert "-" * 60 not in captured.out


def test_slash_no_write_off_persists_buffered_conversation(tmp_path):
    """Test turning no-write off persists the current in-memory conversation."""
    db_path = tmp_path / "tuochat.db"
    conv = Conversation(title="Buffered")
    conv.add_message(Role.USER.value, "hello")
    conv.add_message(Role.ASSISTANT.value, "world")
    with NullConversationStore(db_path) as store:
        state = ReplState(
            conv=conv,
            store=store,
            provider=object(),
            cfg=SimpleNamespace(chat=SimpleNamespace(no_write=True), db_path=db_path, data_dir=tmp_path),
            streaming=True,
            local_writes_enabled=False,
        )

        message, should_exit = handle_slash_command("/no-write off", state)

        assert message is None
        assert should_exit is False
        assert state.cfg.chat.no_write is False
        assert state.local_writes_enabled is True
        if state.store is not store:
            state.store.close()

    with ConversationStore(db_path) as persisted:
        loaded = persisted.get_conversation(conv.id)
        assert loaded is not None
        messages = persisted.get_messages(conv.id)
        assert [msg.content for msg in messages] == ["hello", "world"]


def test_send_chat_turn_no_write_skips_db_and_files(tmp_path):
    """Test no-write mode prevents local DB and filesystem persistence."""
    db_path = tmp_path / "tuochat.db"

    class FakeProvider:
        def chat(self, outbound_input, resource_id=None, streaming=True):
            yield "reply"

    with NullConversationStore(db_path) as store:
        state = ReplState(
            conv=Conversation(title="No Write"),
            store=store,
            provider=FakeProvider(),
            cfg=SimpleNamespace(
                chat=SimpleNamespace(
                    no_write=True,
                    max_request_chars=32000,
                    generated_file_header_enabled=False,
                    generated_file_header_text="",
                    timeout=120,
                    quiet=False,
                    no_banner=False,
                    streaming=True,
                    mask_output=True,
                    dot_timer=False,
                    response_footer_warning_enabled=False,
                ),
                gitlab=SimpleNamespace(token=""),
                data_dir=tmp_path,
                log_dir=tmp_path / "logs",
                db_path=db_path,
                notifications=SimpleNamespace(long_request_bell_enabled=False, long_request_bell_seconds=20),
                personalization=SimpleNamespace(enabled=False, name="", profession=""),
                classification=SimpleNamespace(
                    enabled=False, ask_per_conversation=False, organizations=[], markings=[]
                ),
                warn_words=SimpleNamespace(enabled=False, phrases=[]),
            ),
            streaming=True,
            mask_output=True,
            dot_timer_enabled=False,
            quiet=False,
            no_banner=False,
            local_writes_enabled=False,
            command_log=[],
            active_model="eliza",
        )

        with (
            patch("tuochat.cli.session.validate_user_request", return_value=True),
            patch("tuochat.cli.session.provider_for_attempt", return_value=FakeProvider()),
        ):
            send_chat_turn(state, "hello")

    assert not db_path.exists()
    assert not (tmp_path / "conversations").exists()


class DeterministicElizaProvider(ElizaProvider):
    """Eliza-backed provider with deterministic output for CLI streaming tests."""

    def __init__(self, *, response: str | None = None, chunks: list[str] | None = None):
        super().__init__()
        self.forced_response = response
        self.forced_chunks = chunks

    def chat(
        self,
        outbound_input,
        resource_id=None,
        streaming=True,
        cancel=None,
        additional_context=None,
    ):
        _ = resource_id, cancel, additional_context
        response = self.forced_response
        if response is None:
            response = "".join(self.forced_chunks or []) or self.respond(outbound_input.strip())
        if not streaming:
            yield response
            return
        if self.forced_chunks is not None:
            yield from self.forced_chunks
            return
        words = response.split()
        for idx, word in enumerate(words):
            yield word if idx == 0 else f" {word}"


def extract_streamed_assistant_line(output: str) -> str:
    """Return the exact assistant text that was rendered on the streamed response line."""
    return output.split("Duo> ", 1)[1].split("\n\n", 1)[0]


@contextlib.contextmanager
def make_send_chat_turn_state(
    tmp_path,
    provider,
    *,
    mask_output=False,
    no_code_mode=False,
    gitlab_token="",
):
    db_path = tmp_path / "tuochat.db"
    with NullConversationStore(db_path) as store:
        yield ReplState(
            conv=Conversation(title="Streaming Test"),
            store=store,
            provider=provider,
            cfg=SimpleNamespace(
                chat=SimpleNamespace(
                    no_write=True,
                    max_request_chars=32000,
                    generated_file_header_enabled=False,
                    generated_file_header_text="",
                    timeout=120,
                    quiet=False,
                    no_banner=False,
                    streaming=True,
                    mask_output=mask_output,
                    dot_timer=False,
                    response_footer_warning_enabled=False,
                    response_footer_warning_text="",
                    context_window_tokens=200000,
                    blind=False,
                ),
                gitlab=SimpleNamespace(token=gitlab_token),
                data_dir=tmp_path,
                log_dir=tmp_path / "logs",
                db_path=db_path,
                notifications=SimpleNamespace(long_request_bell_enabled=False, long_request_bell_seconds=20),
                personalization=SimpleNamespace(enabled=False, name="", profession=""),
                classification=SimpleNamespace(
                    enabled=False, ask_per_conversation=False, organizations=[], markings=[]
                ),
                warn_words=SimpleNamespace(enabled=False, phrases=[]),
            ),
            streaming=True,
            mask_output=mask_output,
            no_code_mode=no_code_mode,
            dot_timer_enabled=False,
            quiet=False,
            no_banner=False,
            local_writes_enabled=False,
            command_log=[],
            active_model="duo",
        )


@pytest.mark.parametrize(
    ("response", "expected_mask", "gitlab_token"),
    [
        (
            "Reply start glpat-1234567890abcdefghij and " + ("safe " * 16),
            "[MASKED:GITLAB_PAT]",
            "",
        ),
        (
            "Reply start top-secret-token and " + ("safe " * 16),
            "[MASKED:KNOWN_SECRET]",
            "top-secret-token",
        ),
    ],
)
def test_send_chat_turn_masked_chunked_eliza_stream_keeps_first_line_clean(
    capsys,
    tmp_path,
    response,
    expected_mask,
    gitlab_token,
):
    provider = DeterministicElizaProvider(
        chunks=[
            "Reply ",
            "start ",
            response[12:19],
            response[19:31],
            response[31:70],
            response[70:190],
            response[190:],
        ]
    )
    with make_send_chat_turn_state(tmp_path, provider, mask_output=True, gitlab_token=gitlab_token) as state:
        with (
            patch("tuochat.cli.session.validate_user_request", return_value=True),
            patch("tuochat.cli.session.provider_for_attempt", return_value=provider),
            patch("tuochat.cli.session.sync_conversation_artifacts", return_value=(None, None, [])),
        ):
            send_chat_turn(state, "hello")

        captured = capsys.readouterr()
        assert expected_mask in captured.out
        assert f"Duo> Reply start {expected_mask} and safe" in captured.out
        assert state.conv.messages[-1].content == response


def test_send_chat_turn_word_chunked_eliza_stream_keeps_first_line_readable(capsys, tmp_path):
    provider = DeterministicElizaProvider(response="First line stays intact across word chunks.")
    with make_send_chat_turn_state(tmp_path, provider) as state:
        with (
            patch("tuochat.cli.session.validate_user_request", return_value=True),
            patch("tuochat.cli.session.provider_for_attempt", return_value=provider),
            patch("tuochat.cli.session.sync_conversation_artifacts", return_value=(None, None, [])),
        ):
            send_chat_turn(state, "hello")

        captured = capsys.readouterr()
        assert "Duo> First line stays intact across word chunks." in captured.out
        assert state.conv.messages[-1].content == "First line stays intact across word chunks."


def test_stream_safe_display_length_deltas_reconstruct_clean_masked_stream():
    response = "0123456789abcdefghijklmnopqrstuvwxYZ streamed text stays ordered all the way through."
    chunks = [
        "0123",
        "456",
        "789ab",
        "cdef",
        "ghijk",
        "lmnop",
        "qrst",
        "uvwx",
        "YZ st",
        "reamed ",
        "text stays ordered all the way through.",
    ]
    expected, _, _ = display_text(
        response,
        mask_output=True,
        no_code_mode=False,
        known_secrets=[],
    )

    visible = ""
    full_response = ""
    for chunk in chunks:
        full_response += chunk
        safe_display = stream_safe_display_length(
            full_response,
            mask_output=True,
            no_code_mode=False,
            known_secrets=[],
        )
        assert expected.startswith(safe_display)
        assert len(safe_display) >= len(visible)
        visible += safe_display[len(visible) :]

    rendered = visible + expected[len(visible) :]
    assert rendered == expected


def test_skills_command_lists_central_bundled_and_workspace_sources(capsys, tmp_path, monkeypatch):
    """Test /skills groups skills by central, bundled, and cwd-relative sources."""
    central_skill = tmp_path / "central-skills" / "central-guide" / "SKILL.md"
    bundled_skill = tmp_path / "bundled-skills" / "how-to-use-tuochat" / "SKILL.md"
    workspace_skill = tmp_path / ".agents" / "skills" / "repo-guide" / "SKILL.md"

    central_skill.parent.mkdir(parents=True)
    bundled_skill.parent.mkdir(parents=True)
    workspace_skill.parent.mkdir(parents=True)

    central_skill.write_text("---\nname: central-guide\ndescription: Central instructions\n---\n")
    bundled_skill.write_text("---\nname: how-to-use-tuochat\ndescription: Bundled instructions\n---\n")
    workspace_skill.write_text("---\nname: repo-guide\ndescription: Workspace instructions\n---\n")

    monkeypatch.chdir(tmp_path)
    state = ReplState(
        conv=Conversation(title="Skill Listing"),
        store=object(),
        provider=object(),
        cfg=SimpleNamespace(skills_dir=tmp_path / "central-skills"),
        streaming=True,
    )

    with patch("tuochat.discovery.skills.bundled_skills_dir", return_value=tmp_path / "bundled-skills"):
        message, should_exit = handle_slash_command("/skills", state)

    assert message is None
    assert should_exit is False
    captured = capsys.readouterr()
    assert "Available skills:" in captured.out
    assert "Central (1):" in captured.out
    assert "Bundled (1):" in captured.out
    assert "Cwd-relative (1):" in captured.out
    assert "central-guide: Central instructions" in captured.out
    assert "how-to-use-tuochat: Bundled instructions" in captured.out
    assert "repo-guide: Workspace instructions" in captured.out


def test_skill_command_loads_bundled_skill_by_name(tmp_path, monkeypatch):
    """Test /skill loads a bundled skill into conversation state without sending a turn."""
    bundled_root = tmp_path / "bundled-skills"
    bundled_skill = bundled_root / "how-to-use-tuochat" / "SKILL.md"
    bundled_skill.parent.mkdir(parents=True)
    bundled_skill.write_text(
        "---\nname: how-to-use-tuochat\ndescription: Teach tuochat usage\n---\n\n# How To Use Tuochat\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    with NullConversationStore(tmp_path / "skill-load.db") as store:
        state = ReplState(
            conv=Conversation(title="Skill Load"),
            store=store,
            provider=object(),
            cfg=SimpleNamespace(skills_dir=tmp_path / "central-skills"),
            streaming=True,
        )

        with patch("tuochat.discovery.skills.bundled_skills_dir", return_value=bundled_root):
            message, should_exit = handle_slash_command("/skill how-to-use-tuochat", state)

        assert should_exit is False
        assert message is None
        assert len(state.conv.messages) == 1
        assert state.conv.messages[0].role == Role.USER.value
        assert "Loaded skill: bundled:how-to-use-tuochat (how-to-use-tuochat)" in state.conv.messages[0].content
        assert "# How To Use Tuochat" in state.conv.messages[0].content


def test_session_intro_shows_skill_summary_and_skills_hint(capsys, tmp_path, monkeypatch):
    """Test startup intro prints the skill summary and points to /skills."""
    bundled_root = tmp_path / "bundled-skills"
    bundled_skill = bundled_root / "how-to-use-tuochat" / "SKILL.md"
    bundled_skill.parent.mkdir(parents=True)
    bundled_skill.write_text(
        "---\nname: how-to-use-tuochat\ndescription: Teach tuochat usage\n---\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    state = ReplState(
        conv=Conversation(title="Intro"),
        store=object(),
        provider=object(),
        cfg=SimpleNamespace(skills_dir=tmp_path / "central-skills"),
        streaming=True,
        quiet=False,
        no_banner=False,
    )

    with patch("tuochat.discovery.skills.bundled_skills_dir", return_value=bundled_root):
        print_session_intro(state)

    captured = capsys.readouterr()
    assert "Available skills:" in captured.out
    assert "Bundled (1):" in captured.out
    assert "how-to-use-tuochat: Teach tuochat usage" in captured.out
    assert "'/skills' to list skills" in captured.out
    assert "'/template' to run a prompt template" in captured.out


def test_help_menu_prints_accessible_linear_view(capsys):
    """Test help-menu prints a simpler linear view."""
    print_help_menu()
    captured = capsys.readouterr()
    assert "Help menu" in captured.out
    assert "1. Session and setup" in captured.out
    assert "5. Exit and cleanup" in captured.out
    assert "Select 1-5 to open that section." in captured.out


def test_slash_help_menu_command_prints_accessible_view(capsys, tmp_path):
    """Test /help-menu routes through slash-command handling."""
    with ConversationStore(tmp_path / "tuochat.db") as store:
        state = ReplState(
            conv=Conversation(title="Help Menu"),
            store=store,
            provider=object(),
            cfg=SimpleNamespace(chat=SimpleNamespace(no_write=False), data_dir=tmp_path),
            streaming=True,
        )

        with patch("builtins.input", return_value="3"):
            message, should_exit = handle_slash_command("/help-menu", state)

        assert message is None
        assert should_exit is False
        captured = capsys.readouterr()
        assert "Help menu" in captured.out
        assert "Conversation history:" in captured.out
        assert "/resume [id|n] - Resume a saved conversation" in captured.out


def test_slash_help_uses_help_menu_in_blind_mode(capsys, tmp_path):
    """Test /help falls back to help-menu when blind mode is enabled."""
    with ConversationStore(tmp_path / "tuochat.db") as store:
        state = ReplState(
            conv=Conversation(title="Blind Help"),
            store=store,
            provider=object(),
            cfg=SimpleNamespace(chat=SimpleNamespace(no_write=False, blind=True), data_dir=tmp_path),
            streaming=True,
            blind_mode=True,
            no_banner=True,
        )

        with patch("builtins.input", return_value="3"):
            message, should_exit = handle_slash_command("/help", state)

        assert message is None
        assert should_exit is False
        captured = capsys.readouterr()
        assert "Help menu" in captured.out
        assert "3. Conversation history" in captured.out
        assert "/resume [id|n] - Resume a saved conversation" in captured.out


def test_slash_help_space_menu_prints_accessible_view(capsys, tmp_path):
    """Test `/help menu` routes to the accessible menu view."""
    with ConversationStore(tmp_path / "tuochat.db") as store:
        state = ReplState(
            conv=Conversation(title="Help Topic"),
            store=store,
            provider=object(),
            cfg=SimpleNamespace(chat=SimpleNamespace(no_write=False), data_dir=tmp_path),
            streaming=True,
        )

        with patch("builtins.input", return_value="3"):
            message, should_exit = handle_slash_command("/help menu", state)

        assert message is None
        assert should_exit is False
        captured = capsys.readouterr()
        assert "Help menu" in captured.out
        assert "Select 1-5 to open that section." in captured.out
        assert "Conversation history:" in captured.out
        assert "/resume [id|n] - Resume a saved conversation" in captured.out
        assert "/update-bagit - Refresh archive-change hashes and metadata for saved archives" in captured.out
        assert "/check-bagit - Check whether saved archives changed since the last BagIt update" in captured.out


def test_slash_duo_model_reports_unsupported_backend(capsys, tmp_path, monkeypatch):
    with ConversationStore(tmp_path / "tuochat.db") as store:
        provider = DuoProvider(host="https://gitlab.example.com", token="fake-token")
        monkeypatch.setattr(
            provider,
            "probe_duo_chat_model_support",
            lambda refresh=False: DuoChatModelSupport(  # noqa: ARG005
                supported=False,
                reason="GitLab rejected every known Duo chat model field on AiChatInput.",
            ),
        )
        state = ReplState(
            conv=Conversation(title="Duo model"),
            store=store,
            provider=provider,
            cfg=SimpleNamespace(chat=SimpleNamespace(no_write=False), data_dir=tmp_path),
            streaming=True,
        )

        message, should_exit = handle_slash_command("/duo-model", state)

    assert message is None
    assert should_exit is False
    captured = capsys.readouterr()
    assert "Selected Duo model: (auto/default)" in captured.out
    assert "Server-side Duo model selection is not supported" in captured.out


def test_slash_duo_model_set_stores_session_override(capsys, tmp_path, monkeypatch):
    with ConversationStore(tmp_path / "tuochat.db") as store:
        provider = DuoProvider(host="https://gitlab.example.com", token="fake-token")
        monkeypatch.setattr(
            provider,
            "probe_duo_chat_model_support",
            lambda refresh=False: DuoChatModelSupport(supported=True, request_field="modelId"),  # noqa: ARG005
        )
        state = ReplState(
            conv=Conversation(title="Duo model set"),
            store=store,
            provider=provider,
            cfg=SimpleNamespace(chat=SimpleNamespace(no_write=False), data_dir=tmp_path),
            streaming=True,
        )

        message, should_exit = handle_slash_command("/duo-model set claude-3-opus", state)

    assert message is None
    assert should_exit is False
    assert state.active_duo_model == "claude-3-opus"
    captured = capsys.readouterr()
    assert "Selected Duo model: claude-3-opus" in captured.out


def test_help_menu_section_selector_rejects_invalid_choice(capsys):
    assert print_help_menu_section("9") is False
    captured = capsys.readouterr()
    assert captured.out == ""


def test_slash_help_output_prints_only_output_section(capsys, tmp_path):
    """Test `/help output` narrows help to the output section."""
    with ConversationStore(tmp_path / "tuochat.db") as store:
        state = ReplState(
            conv=Conversation(title="Help Output"),
            store=store,
            provider=object(),
            cfg=SimpleNamespace(chat=SimpleNamespace(no_write=False), data_dir=tmp_path),
            streaming=True,
        )

        message, should_exit = handle_slash_command("/help output", state)

        assert message is None
        assert should_exit is False
        captured = capsys.readouterr()
        assert "Output and Safety:" in captured.out
        assert "/mask on|off" in captured.out
        assert "Conversation History:" not in captured.out


def test_prompt_input_treats_inline_ctrl_z_as_blank_submit():
    """Test single-line prompts accept inline Ctrl+Z submit on Windows."""
    with patch("builtins.input", return_value="\x1a"):
        assert prompt_input("prompt> ") == ""


def test_read_user_message_handles_inline_ctrl_z_submission():
    """Test multiline input submits cleanly when Ctrl+Z appears inline."""
    with patch("builtins.input", side_effect=["hello\x1a"]):
        message, should_exit = read_user_message(quiet=True)

    assert message == "hello"
    assert should_exit is False


def test_slash_tutorial_pick_runs_selected_lesson(capsys, tmp_path):
    """Test /tutorial pick shows the picker and renders the chosen lesson."""
    with ConversationStore(tmp_path / "tuochat.db") as store:
        config_file = tmp_path / "config.toml"
        state = ReplState(
            conv=Conversation(title="Tutorial"),
            store=store,
            provider=object(),
            cfg=SimpleNamespace(chat=SimpleNamespace(no_write=False, tutorial_completed=False), data_dir=tmp_path),
            streaming=True,
            config_path=config_file,
        )

        with patch("tuochat.cli.rendering.clear_screen"), patch("builtins.input", side_effect=["2", "n"]):
            message, should_exit = handle_slash_command("/tutorial pick", state)

        assert message is None
        assert should_exit is False
        captured = capsys.readouterr()
        assert "Tutorial lessons:" in captured.out
        assert "Model selection" in captured.out
        assert "/model duo" in captured.out
        assert state.cfg.chat.tutorial_completed is True


def test_slash_tutorial_multiline_practice_requires_submission(capsys, tmp_path):
    """Test the first tutorial lesson requires a real multiline submission before continuing."""
    with ConversationStore(tmp_path / "tuochat.db") as store:
        config_file = tmp_path / "config.toml"
        state = ReplState(
            conv=Conversation(title="Tutorial Practice"),
            store=store,
            provider=object(),
            cfg=SimpleNamespace(chat=SimpleNamespace(no_write=False, tutorial_completed=False), data_dir=tmp_path),
            streaming=True,
            config_path=config_file,
        )

        with (
            patch(
                "builtins.input",
                side_effect=[
                    "\x1a",
                    "Practice line\x1a",
                    "n",
                ],
            ),
            patch("tuochat.cli.rendering.clear_screen"),
        ):
            message, should_exit = handle_slash_command("/tutorial multiline-input", state)

        assert message is None
        assert should_exit is False
        captured = capsys.readouterr()
        assert "No practice text received yet." in captured.out
        assert "Captured practice input:" in captured.out
        assert "Practice line" in captured.out
        assert "Tutorial paused." in captured.out
        assert state.cfg.chat.tutorial_completed is True


def test_slash_tutorial_pause_persists_completed_flag(capsys, tmp_path):
    """Test pausing the tutorial still marks it complete for future starts."""
    with ConversationStore(tmp_path / "tuochat.db") as store:
        config_file = tmp_path / "config.toml"
        cfg = TuochatConfig()
        cfg.config_dir = tmp_path
        cfg.data_dir = tmp_path
        cfg.log_dir = tmp_path / "logs"
        cfg.chat.tutorial_completed = False
        state = ReplState(
            conv=Conversation(title="Tutorial Pause"),
            store=store,
            provider=object(),
            cfg=cfg,
            streaming=True,
            config_path=config_file,
        )

        with (
            patch("tuochat.cli.rendering.clear_screen"),
            patch("builtins.input", side_effect=["Practice line\x1a", "n"]),
        ):
            message, should_exit = handle_slash_command("/tutorial", state)

        assert message is None
        assert should_exit is False
        assert state.cfg.chat.tutorial_completed is True
        assert config_file.exists()
        assert "tutorial_completed = true" in config_file.read_text(encoding="utf-8")
        assert "Tutorial paused." in capsys.readouterr().out


def test_slash_tutorial_full_run_marks_completed(capsys, tmp_path):
    """Test completing /tutorial persists the tutorial-completed flag."""
    with ConversationStore(tmp_path / "tuochat.db") as store:
        config_file = tmp_path / "config.toml"
        cfg = TuochatConfig()
        cfg.config_dir = tmp_path
        cfg.data_dir = tmp_path
        cfg.log_dir = tmp_path / "logs"
        cfg.chat.tutorial_completed = False
        state = ReplState(
            conv=Conversation(title="Tutorial Complete"),
            store=store,
            provider=object(),
            cfg=cfg,
            streaming=True,
            config_path=config_file,
        )

        with (
            patch("tuochat.cli.rendering.clear_screen"),
            patch(
                "builtins.input", side_effect=["Practice line\x1a", "", "", "\x1a", "", "", "", "", "", "", "", "", "x"]
            ),
        ):
            message, should_exit = handle_slash_command("/tutorial", state)

        assert message is None
        assert should_exit is False
        assert state.cfg.chat.tutorial_completed is True
        captured = capsys.readouterr()
        assert "You can narrow help to one area at a time" in captured.out
        assert "Maps and code maps" in captured.out
        assert "Tutorial complete." in captured.out
        assert config_file.exists()
        assert "tutorial_completed = true" in config_file.read_text(encoding="utf-8")


def test_extract_code_files_appends_check_for_non_whitelisted_extensions(tmp_path):
    """Test extracted code files keep only markdown/text extensions directly."""
    conv = Conversation(title="Extracted Files")
    conv.add_message(
        Role.ASSISTANT.value,
        "path: rm-rf-lol.sh\n```bash\necho hi\n```\n\npath: README.md\n```markdown\n# hello\n```",
    )
    cfg = SimpleNamespace(chat=SimpleNamespace(generated_file_header_enabled=False, generated_file_header_text=""))

    extracted = extract_code_files(tmp_path, conv, cfg)

    extracted_names = sorted(path.name for path in extracted)
    assert "README.md" in extracted_names
    assert "rm-rf-lol.sh.check" in extracted_names


def test_extract_code_files_write_here_mode_writes_named_files_in_cwd(tmp_path, monkeypatch):
    """Test write-here mode writes safe named files into cwd and numbers collisions."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "hello.py").write_text("old", encoding="utf-8")
    conv_dir = tmp_path / ".tuochat" / "conversations" / "conv"
    conv = Conversation(title="Write Here")
    conv.add_message(
        Role.ASSISTANT.value,
        "path: hello.py\n```python\nprint('new')\n```\n\n```text\nuntitled\n```",
    )
    cfg = SimpleNamespace(
        chat=SimpleNamespace(generated_file_header_enabled=False, generated_file_header_text="", write_here_mode=True)
    )

    extracted = extract_code_files(conv_dir, conv, cfg)

    extracted_names = sorted(path.name for path in extracted)
    assert "hello.py.check" in extracted_names
    assert "file1.txt" in extracted_names
    assert (tmp_path / "hello.py.check").read_text(encoding="utf-8") == "print('new')"
    assert (conv_dir / "file1.txt").read_text(encoding="utf-8") == "untitled"


def test_extract_code_files_write_here_mode_rejects_path_shenanigans(tmp_path, monkeypatch):
    """Test write-here mode rejects unsafe paths but allows safe cwd-relative folders."""
    monkeypatch.chdir(tmp_path)
    conv_dir = tmp_path / ".tuochat" / "conversations" / "conv"
    conv = Conversation(title="Unsafe Names")
    conv.add_message(
        Role.ASSISTANT.value,
        "path: ../oops.py\n```python\nprint('x')\n```\n\npath: nested/file.py\n```python\nprint('y')\n```",
    )
    cfg = SimpleNamespace(
        chat=SimpleNamespace(generated_file_header_enabled=False, generated_file_header_text="", write_here_mode=True)
    )

    extracted = extract_code_files(conv_dir, conv, cfg)

    extracted_paths = sorted(path.relative_to(tmp_path).as_posix() for path in extracted)
    assert extracted_paths == [".tuochat/conversations/conv/oops.py.check", "nested/file.py.check"]
    assert not (tmp_path / "oops.py").exists()
    assert (tmp_path / "nested" / "file.py.check").exists()
    assert (conv_dir / "oops.py.check").exists()
    assert not (conv_dir / "nested" / "file.py").exists()


def test_extract_code_files_write_here_mode_writes_safe_nested_relative_paths(tmp_path, monkeypatch):
    """Test write-here mode writes safe relative paths under the cwd."""
    monkeypatch.chdir(tmp_path)
    conv_dir = tmp_path / ".tuochat" / "conversations" / "conv"
    conv = Conversation(title="Nested Write Here")
    conv.add_message(
        Role.ASSISTANT.value,
        "**tests/security/test_masking.py**\n\n```python\nprint('ok')\n```",
    )
    cfg = SimpleNamespace(
        chat=SimpleNamespace(generated_file_header_enabled=False, generated_file_header_text="", write_here_mode=True)
    )

    extracted = extract_code_files(conv_dir, conv, cfg)

    assert [path.relative_to(tmp_path).as_posix() for path in extracted] == ["tests/security/test_masking.py.check"]
    assert (tmp_path / "tests" / "security" / "test_masking.py.check").read_text(encoding="utf-8") == "print('ok')"


def test_extract_code_files_detects_formatted_bare_filenames_with_blank_lines(tmp_path):
    """Test formatted nearby filenames still drive extraction for extensionless names."""
    conv = Conversation(title="Formatted Names")
    conv.add_message(
        Role.ASSISTANT.value,
        "**Dockerfile**\n \n```dockerfile\nFROM python:3.11-slim\n```\n\n__Justfile__\n\n```just\nbuild:\n  uv run pytest\n```",
    )
    cfg = SimpleNamespace(chat=SimpleNamespace(generated_file_header_enabled=False, generated_file_header_text=""))

    extracted = extract_code_files(tmp_path, conv, cfg)

    extracted_names = sorted(path.name for path in extracted)
    assert extracted_names == ["Dockerfile.check", "Justfile.check"]
    assert (tmp_path / "Dockerfile.check").read_text(encoding="utf-8") == "FROM python:3.11-slim"
    assert (tmp_path / "Justfile.check").read_text(encoding="utf-8") == "build:\n  uv run pytest"


def test_extract_code_files_detects_markdown_wrapped_paths_with_extensions(tmp_path):
    """Test formatted nearby paths with known extensions are extracted instead of falling back."""
    conv = Conversation(title="Formatted Path")
    conv.add_message(
        Role.ASSISTANT.value,
        "`src/app.py`\n   \n```python\nprint('hi')\n```\n\n[README.md](https://example.com)\n\n```markdown\n# Hello\n```",
    )
    cfg = SimpleNamespace(chat=SimpleNamespace(generated_file_header_enabled=False, generated_file_header_text=""))

    extracted = extract_code_files(tmp_path, conv, cfg)

    extracted_paths = sorted(path.relative_to(tmp_path).as_posix() for path in extracted)
    assert extracted_paths == ["README.md", "src/app.py.check"]
    assert (tmp_path / "src" / "app.py.check").read_text(encoding="utf-8") == "print('hi')"
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "# Hello"


def test_extract_code_files_restores_markdown_documents_with_tilde_inner_fences(tmp_path):
    """Markdown extraction should restore the inner-fence workaround back to triple backticks."""
    conv = Conversation(title="Nested Markdown")
    conv.add_message(
        Role.ASSISTANT.value,
        "path: README.md\n```markdown\n# Hello\n\nExample:\n\n~~~bash\ncurl https://example.com\n~~~\n\n~~~markdown\n## Nested\n~~~\n```",
    )
    cfg = SimpleNamespace(chat=SimpleNamespace(generated_file_header_enabled=False, generated_file_header_text=""))

    extracted = extract_code_files(tmp_path, conv, cfg)

    assert [path.relative_to(tmp_path).as_posix() for path in extracted] == ["README.md"]
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == (
        "# Hello\n\nExample:\n\n```bash\ncurl https://example.com\n```\n\n```markdown\n## Nested\n```"
    )


def test_extract_code_files_leaves_tilde_fences_alone_for_non_markdown_files(tmp_path):
    """Only markdown outputs should have the workaround restored back to triple backticks."""
    conv = Conversation(title="Tilde Text")
    conv.add_message(
        Role.ASSISTANT.value,
        "path: note.txt\n```text\nExample:\n\n~~~bash\ncurl https://example.com\n~~~\n```",
    )
    cfg = SimpleNamespace(chat=SimpleNamespace(generated_file_header_enabled=False, generated_file_header_text=""))

    extracted = extract_code_files(tmp_path, conv, cfg)

    assert [path.relative_to(tmp_path).as_posix() for path in extracted] == ["note.txt"]
    assert (tmp_path / "note.txt").read_text(encoding="utf-8") == "Example:\n\n~~~bash\ncurl https://example.com\n~~~"


def test_extract_code_files_supports_wrapped_labels_headings_and_backslash_paths(tmp_path, monkeypatch):
    """Test nearby filename hints accept wrapped labels, heading markers, and Windows separators."""
    monkeypatch.chdir(tmp_path)
    conv_dir = tmp_path / ".tuochat" / "conversations" / "conv"
    conv = Conversation(title="Flexible Path Hints")
    conv.add_message(
        Role.ASSISTANT.value,
        "** Path: foo\\bar.py **\n```python\nprint('wrapped')\n```\n\n## baz\\qux.txt\n```\nplain\n```\n\nfoo\\zap.py\n```python\nprint('bare')\n```",
    )
    cfg = SimpleNamespace(
        chat=SimpleNamespace(generated_file_header_enabled=False, generated_file_header_text="", write_here_mode=True)
    )

    extracted = extract_code_files(conv_dir, conv, cfg)

    extracted_paths = sorted(path.relative_to(tmp_path).as_posix() for path in extracted)
    assert extracted_paths == ["baz/qux.txt", "foo/bar.py.check", "foo/zap.py.check"]
    assert (tmp_path / "foo" / "bar.py.check").read_text(encoding="utf-8") == "print('wrapped')"
    assert (tmp_path / "baz" / "qux.txt").read_text(encoding="utf-8") == "plain"
    assert (tmp_path / "foo" / "zap.py.check").read_text(encoding="utf-8") == "print('bare')"


def test_extract_code_files_can_disable_safety_check_extension(tmp_path, monkeypatch):
    """Test disabling safety check writes raw extracted extensions into cwd."""
    monkeypatch.chdir(tmp_path)
    conv_dir = tmp_path / ".tuochat" / "conversations" / "conv"
    conv = Conversation(title="Unsafe Opt Out")
    conv.add_message(
        Role.ASSISTANT.value,
        "path: script.sh\n```bash\necho hi\n```\n\n**Dockerfile**\n\n```dockerfile\nFROM busybox\n```",
    )
    cfg = SimpleNamespace(
        chat=SimpleNamespace(
            generated_file_header_enabled=False,
            generated_file_header_text="",
            write_here_mode=True,
            safety_check_extension_for_executable_files=False,
        )
    )

    extracted = extract_code_files(conv_dir, conv, cfg)

    assert sorted(path.relative_to(tmp_path).as_posix() for path in extracted) == ["Dockerfile", "script.sh"]
    assert (tmp_path / "script.sh").read_text(encoding="utf-8") == "echo hi"
    assert (tmp_path / "Dockerfile").read_text(encoding="utf-8") == "FROM busybox"


def test_extract_code_files_colon_info_style(tmp_path):
    """Test ```lang:filename.ext info string extracts the correct filename."""
    conv = Conversation(title="Colon Info Style")
    conv.add_message(
        Role.ASSISTANT.value,
        "```python:password_manager.py\nprint('hello')\n```",
    )
    cfg = SimpleNamespace(chat=SimpleNamespace(generated_file_header_enabled=False, generated_file_header_text=""))

    extracted = extract_code_files(tmp_path, conv, cfg)

    extracted_names = [path.name for path in extracted]
    assert "password_manager.py.check" in extracted_names


def test_extract_code_files_title_attribute_style(tmp_path):
    """Test ```python title="file.py" info string extracts the correct filename."""
    conv = Conversation(title="Attribute Style")
    conv.add_message(
        Role.ASSISTANT.value,
        '```python title="app.py"\nprint("hi")\n```',
    )
    cfg = SimpleNamespace(chat=SimpleNamespace(generated_file_header_enabled=False, generated_file_header_text=""))

    extracted = extract_code_files(tmp_path, conv, cfg)

    extracted_names = [path.name for path in extracted]
    assert "app.py.check" in extracted_names


def test_extract_code_files_filename_attribute_style(tmp_path):
    """Test ```python filename="file.py" info string extracts the correct filename."""
    conv = Conversation(title="Filename Attribute Style")
    conv.add_message(
        Role.ASSISTANT.value,
        '```python filename="utils.py"\npass\n```',
    )
    cfg = SimpleNamespace(chat=SimpleNamespace(generated_file_header_enabled=False, generated_file_header_text=""))

    extracted = extract_code_files(tmp_path, conv, cfg)

    extracted_names = [path.name for path in extracted]
    assert "utils.py.check" in extracted_names


def test_extract_code_files_bare_path_info_style(tmp_path):
    """Test ``` path/to/file.py as the entire info string extracts the filename."""
    conv = Conversation(title="Bare Path Info")
    conv.add_message(
        Role.ASSISTANT.value,
        "```src/config.py\nVALUE = 1\n```",
    )
    cfg = SimpleNamespace(chat=SimpleNamespace(generated_file_header_enabled=False, generated_file_header_text=""))

    extracted = extract_code_files(tmp_path, conv, cfg)

    extracted_names = [path.name for path in extracted]
    assert "config.py.check" in extracted_names


def test_sync_conversation_artifacts_writes_payload_into_data_subdir(tmp_path):
    conv = Conversation(title="Archive Layout", created_at="2026-04-04T12:00:00+00:00")
    conv.add_message(Role.ASSISTANT.value, "path: README.md\n```markdown\n# hi\n```")
    cfg = SimpleNamespace(
        data_dir=tmp_path,
        chat=SimpleNamespace(
            generated_file_header_enabled=False,
            generated_file_header_text="",
            write_here_mode=False,
            safety_check_extension_for_executable_files=True,
        ),
        personalization=SimpleNamespace(name=""),
    )

    archive_dir, md_path, extracted = sync_conversation_artifacts(cfg, conv)

    assert archive_dir.name == "2026-04-04-001"
    assert (archive_dir / ARCHIVE_ID_MARKER).read_text(encoding="utf-8") == conv.id
    assert md_path == archive_dir / "data" / "2026-04-04-001.md"
    assert extracted == [archive_dir / "data" / "README.md"]
    assert "- `README.md`" in md_path.read_text(encoding="utf-8")


def test_sync_conversation_artifacts_migrates_legacy_flat_archives(tmp_path):
    conv = Conversation(title="Legacy Archive", created_at="2026-04-04T12:00:00+00:00")
    cfg = SimpleNamespace(
        data_dir=tmp_path,
        chat=SimpleNamespace(
            generated_file_header_enabled=False,
            generated_file_header_text="",
            write_here_mode=False,
            safety_check_extension_for_executable_files=True,
        ),
        personalization=SimpleNamespace(name=""),
    )
    archive_dir = tmp_path / "conversations" / "2026-04-04-001"
    archive_dir.mkdir(parents=True)
    (archive_dir / ARCHIVE_ID_MARKER).write_text(conv.id, encoding="utf-8")
    (archive_dir / "2026-04-04-001.md").write_text("legacy transcript", encoding="utf-8")

    result_dir, md_path, extracted = sync_conversation_artifacts(cfg, conv)

    assert result_dir == archive_dir
    assert md_path == archive_dir / "data" / "2026-04-04-001.md"
    assert not (archive_dir / "2026-04-04-001.md").exists()
    assert extracted == []


def test_sync_conversation_artifacts_updates_bagit_when_available(tmp_path, monkeypatch):
    calls: list[tuple[str, object, object]] = []

    class FakeBag:
        def __init__(self, archive_path: str, initial_info: dict[str, str] | None = None) -> None:
            self.archive_dir = Path(archive_path)
            self.info = dict(initial_info or {})

        def save(self, processes: int = 1, manifests: bool = False) -> None:
            calls.append(("save", self.archive_dir, manifests))

    class FakeBagit:
        DEFAULT_CHECKSUMS = ["sha256", "sha512"]

        @staticmethod
        def make_manifests(data_dir: str, processes: int, algorithms=None, encoding: str = "utf-8"):
            _ = (processes, encoding)
            calls.append(("make_manifests", Path.cwd() / data_dir, tuple(algorithms or ())))
            return 123, 4

        @staticmethod
        def Bag(archive_path: str):
            calls.append(("Bag", Path(archive_path), "opened"))
            return FakeBag(archive_path)

    monkeypatch.setattr("tuochat.persistence.archive.load_bagit_module", lambda: FakeBagit)
    conv = Conversation(title="Bagged", created_at="2026-04-04T12:00:00+00:00")
    cfg = SimpleNamespace(
        data_dir=tmp_path,
        chat=SimpleNamespace(
            generated_file_header_enabled=False,
            generated_file_header_text="",
            write_here_mode=False,
            safety_check_extension_for_executable_files=True,
        ),
        personalization=SimpleNamespace(name="Ada"),
    )

    archive_dir, md_path, _ = sync_conversation_artifacts(cfg, conv, classification="SECRET")

    assert archive_dir == tmp_path / "conversations" / "2026-04-04-001"
    assert md_path == archive_dir / "data" / "2026-04-04-001.md"
    assert calls[0] == ("make_manifests", archive_dir / "data", ("sha256", "sha512"))
    assert ("Bag", archive_dir, "opened") in calls
    assert ("save", archive_dir, True) in calls


def test_refresh_archive_bagit_metadata_updates_existing_archives(tmp_path):
    calls: list[tuple[str, object, object]] = []

    class FakeBag:
        def __init__(self, archive_path: str, initial_info: dict[str, str] | None = None) -> None:
            self.archive_dir = Path(archive_path)
            self.info = dict(initial_info or {})

        def save(self, processes: int = 1, manifests: bool = False) -> None:
            calls.append(("save", self.archive_dir, manifests))

    class FakeBagit:
        DEFAULT_CHECKSUMS = ["sha256", "sha512"]

        @staticmethod
        def make_manifests(data_dir: str, processes: int, algorithms=None, encoding: str = "utf-8"):
            _ = (processes, encoding)
            calls.append(("make_manifests", Path.cwd() / data_dir, tuple(algorithms or ())))
            return 123, 4

        @staticmethod
        def Bag(archive_path: str):
            calls.append(("Bag", Path(archive_path), "opened"))
            return FakeBag(archive_path)

    conv = Conversation(title="Legacy Archive", created_at="2026-04-04T12:00:00+00:00")
    cfg = SimpleNamespace(data_dir=tmp_path, chat=SimpleNamespace(write_here_mode=False))
    archive_dir = tmp_path / "conversations" / "2026-04-04-001"
    archive_dir.mkdir(parents=True)
    (archive_dir / ARCHIVE_ID_MARKER).write_text(conv.id, encoding="utf-8")
    (archive_dir / "2026-04-04-001.md").write_text("legacy transcript", encoding="utf-8")

    updated, skipped = refresh_archive_bagit_metadata(
        cfg,
        {conv.id: conv},
        user="Ada",
        bagit_module=FakeBagit,
    )

    assert (updated, skipped) == (1, 0)
    assert (archive_dir / "data" / "2026-04-04-001.md").read_text(encoding="utf-8") == "legacy transcript"
    assert calls[0] == ("make_manifests", archive_dir / "data", ("sha256", "sha512"))
    assert ("save", archive_dir, True) in calls


def test_refresh_archive_bagit_metadata_handles_existing_data_dir_without_staging(tmp_path):
    calls: list[tuple[str, object, object]] = []

    class FakeBag:
        def __init__(self, archive_path: str, initial_info: dict[str, str] | None = None) -> None:
            self.archive_dir = Path(archive_path)
            self.info = dict(initial_info or {})

        def save(self, processes: int = 1, manifests: bool = False) -> None:
            calls.append(("save", self.archive_dir, manifests))

    class FakeBagit:
        DEFAULT_CHECKSUMS = ["sha256", "sha512"]

        @staticmethod
        def make_manifests(data_dir: str, processes: int, algorithms=None, encoding: str = "utf-8"):
            _ = (processes, encoding)
            calls.append(("make_manifests", Path.cwd() / data_dir, tuple(algorithms or ())))
            return 999, 3

        @staticmethod
        def Bag(archive_path: str):
            calls.append(("Bag", Path(archive_path), "opened"))
            return FakeBag(archive_path)

    conv = Conversation(title="Data Layout", created_at="2026-04-04T12:00:00+00:00")
    cfg = SimpleNamespace(data_dir=tmp_path, chat=SimpleNamespace(write_here_mode=False))
    archive_dir = tmp_path / "conversations" / "2026-04-04-001"
    payload_dir = archive_dir / "data"
    payload_dir.mkdir(parents=True)
    (archive_dir / ARCHIVE_ID_MARKER).write_text(conv.id, encoding="utf-8")
    (payload_dir / "2026-04-04-001.md").write_text("already nested", encoding="utf-8")

    updated, skipped = refresh_archive_bagit_metadata(
        cfg,
        {conv.id: conv},
        user="Ada",
        bagit_module=FakeBagit,
    )

    assert (updated, skipped) == (1, 0)
    assert (payload_dir / "2026-04-04-001.md").read_text(encoding="utf-8") == "already nested"
    assert not (archive_dir.parent / "2026-04-04-001.bagit-staging").exists()
    assert calls[0] == ("make_manifests", payload_dir, ("sha256", "sha512"))
    assert ("save", archive_dir, True) in calls


def test_check_archive_bagit_status_reports_valid_changed_and_missing(tmp_path):
    class FakeBag:
        def __init__(self, archive_path: str) -> None:
            self.archive_dir = Path(archive_path)

        def validate(self, processes: int = 1) -> None:
            assert processes == 1
            if self.archive_dir.name == "changed":
                raise FakeBagit.BagValidationError("manifest mismatch")

    class FakeBagit:
        class BagError(Exception):
            pass

        class BagValidationError(BagError):
            pass

        @staticmethod
        def Bag(archive_path: str):
            return FakeBag(archive_path)

    cfg = SimpleNamespace(data_dir=tmp_path, chat=SimpleNamespace(write_here_mode=False))
    root = tmp_path / "conversations"
    valid_dir = root / "valid"
    changed_dir = root / "changed"
    missing_dir = root / "missing"
    skipped_dir = root / "skipped"
    for archive_dir, conversation_id in (
        (valid_dir, "conv-valid"),
        (changed_dir, "conv-changed"),
        (missing_dir, "conv-missing"),
    ):
        archive_dir.mkdir(parents=True)
        (archive_dir / ARCHIVE_ID_MARKER).write_text(conversation_id, encoding="utf-8")
    (valid_dir / "bagit.txt").write_text("bagit", encoding="utf-8")
    (changed_dir / "bagit.txt").write_text("bagit", encoding="utf-8")
    skipped_dir.mkdir(parents=True)

    results, skipped = check_archive_bagit_status(cfg, bagit_module=FakeBagit)

    assert skipped == 1
    assert [(result.archive_dir.name, result.status, result.detail) for result in results] == [
        ("changed", "changed", "manifest mismatch"),
        ("missing", "missing", None),
        ("valid", "valid", None),
    ]


def test_slash_update_bagit_refreshes_saved_archives(capsys, tmp_path, monkeypatch):
    with ConversationStore(tmp_path / "tuochat.db") as store:
        conv = Conversation(title="Saved Conversation")
        store.save_conversation(conv)
        state = ReplState(
            conv=Conversation(title="Current"),
            store=store,
            provider=object(),
            cfg=SimpleNamespace(
                chat=SimpleNamespace(no_write=False),
                data_dir=tmp_path,
                personalization=SimpleNamespace(name="Ada"),
            ),
            streaming=True,
        )
        (tmp_path / "conversations").mkdir(parents=True)
        seen: dict[str, object] = {}

        def fake_refresh(cfg, conversations_by_id, *, user=None, bagit_module=None):
            seen["cfg"] = cfg
            seen["ids"] = sorted(conversations_by_id)
            seen["user"] = user
            seen["bagit_module"] = bagit_module
            return 1, 0

        monkeypatch.setattr("tuochat.cli.repl.load_bagit_module", lambda: object())
        monkeypatch.setattr("tuochat.cli.repl.refresh_archive_bagit_metadata", fake_refresh)

        message, should_exit = handle_slash_command("/update-bagit", state)

        assert message is None
        assert should_exit is False
        assert seen["ids"] == sorted([conv.id, state.conv.id])
        assert seen["user"] == "Ada"
        captured = capsys.readouterr()
        assert "Updated BagIt metadata for 1 conversation(s)" in captured.out
        assert "BagIt here is only a diagnostic aid" in captured.out
        assert "renaming a `.check` file" in captured.out
        assert "not intended to protect against malicious attack" in captured.out


def test_slash_update_bagit_requires_optional_dependency(capsys, tmp_path, monkeypatch):
    with ConversationStore(tmp_path / "tuochat.db") as store:
        state = ReplState(
            conv=Conversation(title="Current"),
            store=store,
            provider=object(),
            cfg=SimpleNamespace(chat=SimpleNamespace(no_write=False), data_dir=tmp_path),
            streaming=True,
        )

        monkeypatch.setattr("tuochat.cli.repl.load_bagit_module", lambda: None)

        message, should_exit = handle_slash_command("/update-bagit", state)

        assert message is None
        assert should_exit is False
        captured = capsys.readouterr()
        assert "tuochat[antitamper]" in captured.err


def test_slash_check_bagit_reports_changed_archives(capsys, tmp_path, monkeypatch):
    with ConversationStore(tmp_path / "tuochat.db") as store:
        changed_conv = Conversation(title="Edited Archive")
        store.save_conversation(changed_conv)
        state = ReplState(
            conv=Conversation(title="Current"),
            store=store,
            provider=object(),
            cfg=SimpleNamespace(chat=SimpleNamespace(no_write=False), data_dir=tmp_path),
            streaming=True,
        )
        (tmp_path / "conversations").mkdir(parents=True)

        class Result:
            def __init__(self, archive_name: str, conversation_id: str, status: str, detail: str | None = None) -> None:
                self.archive_dir = tmp_path / "conversations" / archive_name
                self.conversation_id = conversation_id
                self.status = status
                self.detail = detail

        monkeypatch.setattr("tuochat.cli.repl.load_bagit_module", lambda: object())
        monkeypatch.setattr(
            "tuochat.cli.repl.check_archive_bagit_status",
            lambda cfg, *, bagit_module=None: (
                [
                    Result("2026-04-04-001", changed_conv.id, "changed", "manifest mismatch"),
                    Result("2026-04-04-002", "conv-valid", "valid"),
                    Result("2026-04-04-003", "conv-missing", "missing"),
                ],
                1,
            ),
        )

        message, should_exit = handle_slash_command("/check-bagit", state)

        assert message is None
        assert should_exit is False
        captured = capsys.readouterr()
        assert "Checked BagIt status for 3 conversation(s)" in captured.out
        assert "diagnostic aid" in captured.out
        assert "renaming a `.check` file" in captured.out
        assert "not intended to protect against malicious attack" in captured.out
        assert "1 archive(s) still validate." in captured.out
        assert "1 archive(s) do not have BagIt files yet." in captured.out
        assert "1 archive(s) no longer validate." in captured.out
        assert "Edited Archive" in captured.out
        assert "manifest mismatch" in captured.out
        assert "Skipped 1 archive(s) missing a readable conversation ID." in captured.err


def test_slash_check_bagit_requires_optional_dependency(capsys, tmp_path, monkeypatch):
    with ConversationStore(tmp_path / "tuochat.db") as store:
        state = ReplState(
            conv=Conversation(title="Current"),
            store=store,
            provider=object(),
            cfg=SimpleNamespace(chat=SimpleNamespace(no_write=False), data_dir=tmp_path),
            streaming=True,
        )

        monkeypatch.setattr("tuochat.cli.repl.load_bagit_module", lambda: None)

        message, should_exit = handle_slash_command("/check-bagit", state)

        assert message is None
        assert should_exit is False
        captured = capsys.readouterr()
        assert "tuochat[antitamper]" in captured.err


def test_sync_conversation_artifacts_write_here_mode_uses_workspace_archive_and_gitignore(tmp_path, monkeypatch):
    """Test write-here mode keeps transcripts under cwd-local .tuochat and creates a nested gitignore."""
    monkeypatch.chdir(tmp_path)
    conv = Conversation(title="Artifacts")
    conv.add_message(Role.USER.value, "hello")
    conv.add_message(Role.ASSISTANT.value, "path: note.md\n```markdown\n# hi\n```")
    cfg = SimpleNamespace(
        chat=SimpleNamespace(
            generated_file_header_enabled=False,
            generated_file_header_text="",
            write_here_mode=True,
        ),
        data_dir=tmp_path / "central-data",
        personalization=SimpleNamespace(name=""),
    )

    conv_dir, md_path, extracted = sync_conversation_artifacts(cfg, conv)

    assert conv_dir == tmp_path / ".tuochat" / "conversations" / conv_dir.name
    assert md_path == conv_dir / "data" / f"{conv_dir.name}.md"
    assert (tmp_path / ".tuochat" / ".gitignore").read_text(encoding="utf-8") == "*\n!.gitignore\n"
    assert extracted[0].parent == tmp_path
    assert md_path.read_text(encoding="utf-8")


def test_sync_conversation_artifacts_write_here_mode_can_require_approval(tmp_path, monkeypatch):
    """Test unapproved cwd writes fall back to the conversation archive."""
    monkeypatch.chdir(tmp_path)
    conv = Conversation(title="Approval")
    conv.add_message(Role.ASSISTANT.value, "path: app.py\n```python\nprint('ok')\n```")
    cfg = SimpleNamespace(
        chat=SimpleNamespace(
            generated_file_header_enabled=False,
            generated_file_header_text="",
            write_here_mode=True,
        ),
        data_dir=tmp_path / "central-data",
        personalization=SimpleNamespace(name=""),
    )

    conv_dir, md_path, extracted = sync_conversation_artifacts(cfg, conv, approve_write=lambda path: False)

    assert md_path == conv_dir / "data" / f"{conv_dir.name}.md"
    assert extracted == [conv_dir / "data" / "app.py.check"]
    assert not (tmp_path / "app.py").exists()
    assert (conv_dir / "data" / "app.py.check").exists()


def test_send_chat_turn_write_here_mode_saves_extracted_files_after_response(tmp_path, monkeypatch):
    """Test a completed response writes named generated files into the cwd immediately."""
    monkeypatch.chdir(tmp_path)

    class FakeProvider:
        def chat(self, outbound_input, resource_id=None, streaming=True, cancel=None, additional_context=None):
            _ = outbound_input, resource_id, streaming, cancel, additional_context
            yield "**tests/security/test_masking.py**\n\n```python\nprint('ok')\n```"

    with ConversationStore(tmp_path / "tuochat.db") as store:
        state = ReplState(
            conv=Conversation(title="Immediate Save"),
            store=store,
            provider=FakeProvider(),
            cfg=SimpleNamespace(
                chat=SimpleNamespace(
                    no_write=False,
                    write_here_mode=True,
                    approve_writes=False,
                    max_request_chars=32000,
                    generated_file_header_enabled=False,
                    generated_file_header_text="",
                    timeout=120,
                    quiet=False,
                    no_banner=False,
                    streaming=True,
                    mask_output=False,
                    dot_timer=False,
                    response_footer_warning_enabled=False,
                    response_footer_warning_text="",
                    context_window_tokens=200000,
                    blind=False,
                ),
                gitlab=SimpleNamespace(token=""),
                data_dir=tmp_path / "data",
                log_dir=tmp_path / "logs",
                notifications=SimpleNamespace(long_request_bell_enabled=False, long_request_bell_seconds=20),
                personalization=SimpleNamespace(enabled=False, name="", profession=""),
                classification=SimpleNamespace(
                    enabled=False, ask_per_conversation=False, organizations=[], markings=[]
                ),
                warn_words=SimpleNamespace(enabled=False, phrases=[]),
            ),
            streaming=True,
            mask_output=False,
            dot_timer_enabled=False,
            quiet=False,
            no_banner=False,
            local_writes_enabled=True,
            command_log=[],
            active_model="duo",
        )

        with (
            patch("tuochat.cli.session.validate_user_request", return_value=True),
            patch("tuochat.cli.session.provider_for_attempt", return_value=state.provider),
        ):
            send_chat_turn(state, "hello")

    saved_file = tmp_path / "tests" / "security" / "test_masking.py.check"
    assert saved_file.read_text(encoding="utf-8") == "print('ok')"
    assert state.last_saved_markdown_path is not None
    assert state.last_saved_markdown_path.exists()


def test_send_chat_turn_warns_when_virtual_files_stay_in_archive(capsys, tmp_path):
    """Test fenced files mention write-here mode when they stay in the archive."""

    class FakeProvider:
        def chat(self, outbound_input, resource_id=None, streaming=True, cancel=None, additional_context=None):
            _ = outbound_input, resource_id, streaming, cancel, additional_context
            yield "path: app.py\n```python\nprint('ok')\n```"

    with ConversationStore(tmp_path / "tuochat.db") as store:
        state = ReplState(
            conv=Conversation(title="Virtual Files"),
            store=store,
            provider=FakeProvider(),
            cfg=SimpleNamespace(
                chat=SimpleNamespace(
                    no_write=False,
                    write_here_mode=False,
                    approve_writes=False,
                    max_request_chars=32000,
                    generated_file_header_enabled=False,
                    generated_file_header_text="",
                    timeout=120,
                    quiet=False,
                    no_banner=False,
                    streaming=True,
                    mask_output=False,
                    dot_timer=False,
                    response_footer_warning_enabled=False,
                    response_footer_warning_text="",
                    context_window_tokens=200000,
                    blind=False,
                ),
                gitlab=SimpleNamespace(token=""),
                data_dir=tmp_path / "data",
                log_dir=tmp_path / "logs",
                notifications=SimpleNamespace(long_request_bell_enabled=False, long_request_bell_seconds=20),
                personalization=SimpleNamespace(enabled=False, name="", profession=""),
                classification=SimpleNamespace(
                    enabled=False, ask_per_conversation=False, organizations=[], markings=[]
                ),
                warn_words=SimpleNamespace(enabled=False, phrases=[]),
            ),
            streaming=True,
            mask_output=False,
            dot_timer_enabled=False,
            quiet=False,
            no_banner=False,
            local_writes_enabled=True,
            command_log=[],
            active_model="duo",
        )

        with (
            patch("tuochat.cli.session.validate_user_request", return_value=True),
            patch("tuochat.cli.session.provider_for_attempt", return_value=state.provider),
        ):
            send_chat_turn(state, "hello")

    output = capsys.readouterr().out
    assert "Named files written to central archive (write-here mode is off)." in output


def test_slash_blind_toggles_mode(capsys, tmp_path):
    """Test /blind on turns on blind mode and suppresses the banner."""
    with ConversationStore(tmp_path / "tuochat.db") as store:
        state = ReplState(
            conv=Conversation(title="Blind Toggle"),
            store=store,
            provider=object(),
            cfg=SimpleNamespace(chat=SimpleNamespace(no_write=False, blind=False), data_dir=tmp_path),
            streaming=True,
            blind_mode=False,
            no_banner=False,
        )

        message, should_exit = handle_slash_command("/blind on", state)

        assert message is None
        assert should_exit is False
        assert state.blind_mode is True
        assert state.no_banner is True
        captured = capsys.readouterr()
        assert "Blind mode enabled for this session." in captured.out


def test_files_picker_uses_plain_numbers_in_blind_mode(capsys, tmp_path, monkeypatch):
    """Test blind mode removes brackets from file picker numbering."""
    (tmp_path / "alpha.txt").write_text("a", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    state = ReplState(
        conv=Conversation(title="Blind Files"),
        store=object(),
        provider=object(),
        cfg=SimpleNamespace(chat=SimpleNamespace(blind=True), data_dir=tmp_path),
        streaming=True,
        blind_mode=True,
    )

    print_files(state)

    captured = capsys.readouterr()
    assert "1 alpha.txt" in captured.out
    assert "[1]" not in captured.out


def test_context_tokens_shortcut_in_blind_mode(capsys, tmp_path):
    """Test blind mode defaults /context to a simple token summary."""
    conv = Conversation(title="Blind Context")
    conv.add_message(Role.USER.value, "hello world")
    state = ReplState(
        conv=conv,
        store=object(),
        provider=object(),
        cfg=SimpleNamespace(data_dir=tmp_path, chat=SimpleNamespace(context_window_tokens=200000, blind=True)),
        streaming=True,
        blind_mode=True,
    )

    message, should_exit = handle_slash_command("/context", state)

    assert message is None
    assert should_exit is False
    captured = capsys.readouterr()
    assert "Prompt #1:" in captured.out
    assert "+" not in captured.out


def test_context_defaults_to_all_when_not_blind(capsys, tmp_path):
    """Test non-blind /context keeps the full summary view by default."""
    conv = Conversation(title="Default Context")
    conv.add_message(Role.USER.value, "hello world")
    state = ReplState(
        conv=conv,
        store=object(),
        provider=object(),
        cfg=SimpleNamespace(data_dir=tmp_path, chat=SimpleNamespace(context_window_tokens=200000, blind=False)),
        streaming=True,
        blind_mode=False,
    )

    message, should_exit = handle_slash_command("/context", state)

    assert message is None
    assert should_exit is False
    captured = capsys.readouterr()
    assert "Context:" in captured.out
    assert "Context tokens:" not in captured.out


def test_context_all_mode_prints_full_summary_in_blind_mode(capsys, tmp_path):
    """Test /context all forces the full blind-friendly summary."""
    conv = Conversation(title="Blind Context All")
    conv.add_message(Role.USER.value, "hello world")
    state = ReplState(
        conv=conv,
        store=object(),
        provider=object(),
        cfg=SimpleNamespace(data_dir=tmp_path, chat=SimpleNamespace(context_window_tokens=200000, blind=True)),
        streaming=True,
        blind_mode=True,
    )

    message, should_exit = handle_slash_command("/context all", state)

    assert message is None
    assert should_exit is False
    captured = capsys.readouterr()
    assert "Context:" in captured.out
    assert "Prompt #1:" in captured.out
    assert "Context tokens:" not in captured.out


def test_send_chat_turn_uses_active_model_label(capsys, tmp_path):
    class FakeProvider:
        def chat(self, outbound_input, resource_id=None, streaming=True, cancel=None, additional_context=None):
            yield "Hello"

    with ConversationStore(tmp_path / "tuochat.db") as store:
        state = ReplState(
            conv=Conversation(title="Model Label"),
            store=store,
            provider=FakeProvider(),
            cfg=SimpleNamespace(
                data_dir=tmp_path,
                chat=SimpleNamespace(
                    context_window_tokens=200000,
                    generated_file_header_enabled=False,
                    generated_file_header_text="",
                    response_footer_warning_enabled=False,
                    response_footer_warning_text="",
                    quiet=False,
                    blind=False,
                    no_write=False,
                    mask_output=False,
                    dot_timer=False,
                    max_request_chars=32000,
                ),
                gitlab=SimpleNamespace(token=""),
                notifications=SimpleNamespace(long_request_bell_enabled=False, long_request_bell_seconds=20),
                personalization=SimpleNamespace(enabled=False, name="", profession=""),
                classification=SimpleNamespace(
                    enabled=False, ask_per_conversation=False, markings=[], organizations=[], max_markings=[]
                ),
                warn_words=SimpleNamespace(enabled=False, phrases=[]),
            ),
            streaming=True,
            active_model="duo",
        )
        with (
            patch("tuochat.cli.session.validate_user_request", return_value=True),
            patch("tuochat.cli.session.provider_for_attempt", return_value=FakeProvider()),
        ):
            send_chat_turn(state, "hello")
    captured = capsys.readouterr()
    assert "Duo> Hello" in captured.out


def test_context_kb_mode_prints_kb_only(capsys, tmp_path):
    """Test /context kb prints only the kb summary."""
    conv = Conversation(title="KB Context")
    conv.add_message(Role.USER.value, "hello world")
    state = ReplState(
        conv=conv,
        store=object(),
        provider=object(),
        cfg=SimpleNamespace(data_dir=tmp_path, chat=SimpleNamespace(context_window_tokens=200000, blind=False)),
        streaming=True,
        blind_mode=False,
    )

    message, should_exit = handle_slash_command("/context kb", state)

    assert message is None
    assert should_exit is False
    captured = capsys.readouterr()
    assert "Context kb:" in captured.out
    assert "Context:" not in captured.out


def test_blind_flag_enables_no_banner(capsys, tmp_path):
    """Test --blind suppresses the startup banner in CLI startup."""
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        '[gitlab]\nhost = "https://gitlab.com"\ntoken = "glpat-test"\n\n[chat]\nblind = false\n',
        encoding="utf-8",
    )

    with (
        patch.object(sys, "argv", ["tuochat", "--blind", "--config", str(config_file), "config"]),
        patch("tuochat.cli.commands.code.run_config", return_value=0) as run_config,
    ):
        result = main()

    assert result == 0
    passed_cfg = run_config.call_args.args[0]
    assert passed_cfg.chat.blind is True
    assert passed_cfg.chat.no_banner is True


def test_skill_command_loads_bundled_blind_accessibility_skill(tmp_path, monkeypatch):
    """Test the bundled blind-accessibility skill is loadable by name."""
    monkeypatch.chdir(tmp_path)
    with NullConversationStore(tmp_path / "blind-skill.db") as store:
        state = ReplState(
            conv=Conversation(title="Accessibility Skill"),
            store=store,
            provider=object(),
            cfg=SimpleNamespace(skills_dir=tmp_path / "central-skills"),
            streaming=True,
        )

        message, should_exit = handle_slash_command("/skill blind-accessibility", state)

        assert should_exit is False
        assert message is None
        assert state.conv.messages
        assert state.conv.messages[0].content.startswith("Loaded skill: bundled:blind-accessibility")


def test_template_command_renders_template_and_records_metadata(tmp_path, monkeypatch):
    """Test /template fills variables and stores template metadata for the next send."""
    template_path = tmp_path / "central-templates" / "recipe" / "TEMPLATE.md"
    template_path.parent.mkdir(parents=True)
    template_path.write_text(
        "---\nname: recipe\ndescription: Recipe helper\n---\n"
        "I have too many {INGREDIENT} and want a recipe in style of {CUISINE} for {PEOPLE_COUNT}.",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    state = ReplState(
        conv=Conversation(title="Template Load"),
        store=object(),
        provider=object(),
        cfg=SimpleNamespace(skills_dir=tmp_path / "central-skills", templates_dir=tmp_path / "central-templates"),
        streaming=True,
    )

    with patch("builtins.input", side_effect=["tomatoes", "Italian", "4"]):
        message, should_exit = handle_slash_command("/template recipe", state)

    assert should_exit is False
    assert message == "I have too many tomatoes and want a recipe in style of Italian for 4."
    assert state.pending_template_metadata is not None
    assert state.pending_template_metadata["name"] == "recipe"
    assert state.pending_template_metadata["variables"] == {
        "INGREDIENT": "tomatoes",
        "CUISINE": "Italian",
        "PEOPLE_COUNT": "4",
    }


def test_template_command_supports_attached_code_and_auto_tokens(tmp_path, monkeypatch):
    """The built-in template flow should prompt for ATTACHED_CODE as a file path in the TUI."""
    template_path = tmp_path / "central-templates" / "explain" / "TEMPLATE.md"
    code_path = tmp_path / "sample.py"
    template_path.parent.mkdir(parents=True)
    template_path.write_text(
        "---\nname: explain\ndescription: Explain helper\n---\n"
        "Repo: {GIT_REPO_NAME}\nWhen: {DATE}\nCode:\n{ATTACHED_CODE}",
        encoding="utf-8",
    )
    code_path.write_text("print('hello')\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("tuochat.context.composer.inspect_git_repository", lambda cwd: (tmp_path, "demo-repo"))
    state = ReplState(
        conv=Conversation(title="Template Load"),
        store=object(),
        provider=object(),
        cfg=SimpleNamespace(skills_dir=tmp_path / "central-skills", templates_dir=tmp_path / "central-templates"),
        streaming=True,
    )

    with patch("builtins.input", side_effect=["sample.py"]):
        message, should_exit = handle_slash_command("/template explain", state)

    assert should_exit is False
    assert message is not None
    assert "Repo: demo-repo" in message
    assert "Attached code from sample.py:" in message
    assert "```python" in message
    assert state.pending_template_metadata is not None
    assert state.pending_template_metadata["variables"] == {"ATTACHED_CODE": str(code_path)}
    assert state.pending_template_metadata["auto_variables"] == ["GIT_REPO_NAME", "DATE"]


def test_context_mentions_template_origin(capsys, tmp_path):
    """Test /context reports when a prompt came from a template."""
    conv = Conversation(title="Template Context")
    conv.add_message(
        Role.USER.value,
        "Rendered prompt",
        extras_json=json_dumps(
            {
                "template": {
                    "label": "central:recipe (recipe)",
                    "name": "recipe",
                    "variables": {"INGREDIENT": "tomatoes"},
                }
            }
        ),
    )
    conv.add_message(Role.ASSISTANT.value, "Rendered response")

    state = ReplState(
        conv=conv,
        store=object(),
        provider=object(),
        cfg=SimpleNamespace(
            data_dir=tmp_path,
            chat=SimpleNamespace(context_window_tokens=200000),
        ),
        streaming=True,
    )

    print_context(state)

    captured = capsys.readouterr()
    assert "Template: central:recipe (recipe)" in captured.out
    assert "Prompt #1 (Template: recipe)" in captured.out


def test_context_mentions_loaded_skill_block_and_skips_skill_prompt(capsys, tmp_path):
    """Loaded skills should render as their own context blocks, not numbered prompts."""
    conv = Conversation(title="Skill Context")
    conv.add_message(
        Role.USER.value,
        "Loaded skill: bundled:sandbox-helper (sandbox-helper)\n```text\nUse the sandbox when evaluating JavaScript.\n```",
    )
    conv.add_message(Role.USER.value, "Explain this code.")
    conv.add_message(Role.ASSISTANT.value, "Here is the explanation.")

    state = ReplState(
        conv=conv,
        store=object(),
        provider=object(),
        cfg=SimpleNamespace(
            data_dir=tmp_path,
            chat=SimpleNamespace(context_window_tokens=200000),
        ),
        streaming=True,
    )

    print_context(state)

    captured = capsys.readouterr()
    assert "Skill: bundled:sandbox-helper (sandbox-helper)" in captured.out
    assert "Use the sandbox when evaluating JavaScript." in captured.out
    assert "Prompt #1" in captured.out
    assert "Explain this code." in captured.out
    assert "Prompt #2" not in captured.out


def test_turn_estimate_uses_human_readable_labels(capsys):
    """Test post-turn estimates stay on one compact line."""
    print_turn_estimate(123, 45, verbose=False)
    captured = capsys.readouterr()
    assert captured.out.strip().startswith("Estimate: in=123 out=45 cost=$0.00")


def make_slash_command_state(tmp_path, *, system_prompt: str | None = None) -> ReplState:
    cfg = TuochatConfig()
    cfg.data_dir = tmp_path / "data"
    cfg.config_dir = tmp_path / "config"
    cfg.log_dir = tmp_path / "logs"
    return ReplState(
        conv=Conversation(title="Slash Command Test", system_prompt=system_prompt),
        store=NullConversationStore(tmp_path / "null.db"),
        provider=ElizaProvider(),
        cfg=cfg,
        streaming=True,
    )


@pytest.mark.parametrize("command", ["/files", "/dir", "/ls"])
def test_file_listing_aliases_delegate_to_print_files(monkeypatch, tmp_path, command):
    state = make_slash_command_state(tmp_path)
    calls: list[ReplState] = []

    monkeypatch.setattr("tuochat.cli.repl.print_files", lambda current_state: calls.append(current_state))

    message, should_exit = handle_slash_command(command, state)

    assert message is None
    assert should_exit is False
    assert calls == [state]


def test_agent_prompts_command_lists_candidates_and_marks_active(capsys, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    agents = tmp_path / "AGENTS.md"
    claude = tmp_path / "CLAUDE.md"
    agents.write_text("Agent instructions", encoding="utf-8")
    claude.write_text("Claude instructions", encoding="utf-8")
    state = make_slash_command_state(tmp_path)
    state.active_agent_prompt_path = agents

    message, should_exit = handle_slash_command("/agent-prompts", state)

    assert message is None
    assert should_exit is False
    captured = capsys.readouterr()
    assert "Available agent prompt files:" in captured.out
    assert "cwd:AGENTS.md (active)" in captured.out
    assert "cwd:CLAUDE.md" in captured.out


def test_agent_prompt_none_removes_agent_block(capsys, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    agents = tmp_path / "AGENTS.md"
    agents.write_text("Use careful reasoning.", encoding="utf-8")
    (tmp_path / "bundled-custom").mkdir()
    monkeypatch.setattr("tuochat.context.composer.bundled_custom_instructions_dir", lambda: tmp_path / "bundled-custom")
    state = make_slash_command_state(
        tmp_path,
        system_prompt="AGENTS.md instructions:\nUse careful reasoning.\n\nBase prompt",
    )
    state.base_system_prompt = "Base prompt"
    state.active_agent_prompt_path = agents
    state.active_agent_prompt_mode = "selected"

    message, should_exit = handle_slash_command("/agent-prompt none", state)

    assert message is None
    assert should_exit is False
    assert state.include_agents_file is False
    assert state.active_agent_prompt_mode == "none"
    assert state.conv.system_prompt == "Base prompt"
    assert "Agent prompt: off" in capsys.readouterr().out


def test_agent_prompt_auto_rebuilds_prompt_with_highest_priority_file(capsys, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "AGENTS.md").write_text("Use careful reasoning.", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("Be concise.", encoding="utf-8")
    (tmp_path / "bundled-custom").mkdir()
    monkeypatch.setattr("tuochat.context.composer.bundled_custom_instructions_dir", lambda: tmp_path / "bundled-custom")
    state = make_slash_command_state(tmp_path, system_prompt="Base prompt")
    state.base_system_prompt = "Base prompt"
    state.active_agent_prompt_path = tmp_path / "CLAUDE.md"
    state.active_agent_prompt_mode = "selected"

    message, should_exit = handle_slash_command("/agent-prompt auto", state)

    assert message is None
    assert should_exit is False
    assert state.include_agents_file is True
    assert state.active_agent_prompt_mode == "auto"
    assert state.active_agent_prompt_path is None
    assert state.conv.system_prompt is not None
    assert "AGENTS.md instructions:\nUse careful reasoning." in state.conv.system_prompt
    assert state.conv.system_prompt.endswith("Base prompt")
    assert "Agent prompt: auto (selected: AGENTS.md)" in capsys.readouterr().out


def test_agent_prompt_named_selection_matches_discovered_filename(capsys, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    claude = tmp_path / "CLAUDE.md"
    claude.write_text("Be concise.", encoding="utf-8")
    (tmp_path / "bundled-custom").mkdir()
    monkeypatch.setattr("tuochat.context.composer.bundled_custom_instructions_dir", lambda: tmp_path / "bundled-custom")
    state = make_slash_command_state(tmp_path, system_prompt="Base prompt")
    state.base_system_prompt = "Base prompt"

    message, should_exit = handle_slash_command("/agent-prompt CLAUDE", state)

    assert message is None
    assert should_exit is False
    assert state.active_agent_prompt_path == claude
    assert state.active_agent_prompt_mode == "selected"
    assert state.conv.system_prompt is not None
    assert "CLAUDE.md instructions:\nBe concise." in state.conv.system_prompt
    assert "Agent prompt set to: cwd:CLAUDE.md" in capsys.readouterr().out


def test_recipes_command_lists_available_entries(capsys, monkeypatch, tmp_path):
    recipe = Recipe(name="demo", display_name="Demo Recipe", description="Test recipe", globs=["*.txt"])
    state = make_slash_command_state(tmp_path)

    monkeypatch.setattr("tuochat.context.recipes.list_recipes", lambda: [recipe])

    message, should_exit = handle_slash_command("/recipes", state)

    assert message is None
    assert should_exit is False
    captured = capsys.readouterr()
    assert "Available recipes:" in captured.out
    assert "demo  —  Demo Recipe: Test recipe" in captured.out


def test_recipe_command_lists_usage_when_name_missing(capsys, monkeypatch, tmp_path):
    recipe = Recipe(name="demo", display_name="Demo Recipe", description="Test recipe", globs=["*.txt"])
    state = make_slash_command_state(tmp_path)

    monkeypatch.setattr("tuochat.context.recipes.list_recipes", lambda: [recipe])

    message, should_exit = handle_slash_command("/recipe", state)

    assert message is None
    assert should_exit is False
    captured = capsys.readouterr()
    assert "Available recipes:" in captured.out
    assert "Usage: /recipe <name>" in captured.out


def test_recipe_command_reports_unknown_recipe(capsys, monkeypatch, tmp_path):
    state = make_slash_command_state(tmp_path)

    monkeypatch.setattr("tuochat.context.recipes.get_recipe", lambda name: None)

    message, should_exit = handle_slash_command("/recipe missing", state)

    assert message is None
    assert should_exit is False
    captured = capsys.readouterr()
    assert "Unknown recipe: 'missing'" in captured.err
    assert "Use /recipes to list available recipes." in captured.out


def test_recipe_command_queues_attachment_after_confirmation(capsys, monkeypatch, tmp_path):
    recipe = Recipe(name="demo", display_name="Demo Recipe", description="Test recipe", globs=["*.txt"])
    matched = tmp_path / "notes.txt"
    matched.write_text("hello", encoding="utf-8")
    match = RecipeMatch(
        recipe=recipe,
        matched_paths=[matched],
        skipped_paths=[],
        rendered="# notes.txt\n```txt\nhello\n```",
        estimated_tokens=42,
    )
    state = make_slash_command_state(tmp_path)

    monkeypatch.setattr("tuochat.context.recipes.get_recipe", lambda name: recipe if name == "demo" else None)
    monkeypatch.setattr("tuochat.context.recipes.expand_recipe", lambda selected_recipe: match)
    monkeypatch.setattr("tuochat.cli.repl.prompt_input", lambda prompt: "yes")

    message, should_exit = handle_slash_command("/recipe demo", state)

    assert message is None
    assert should_exit is False
    assert state.pending_attachment_names == ["[recipe] Demo Recipe"]
    assert state.pending_attachment_messages == [
        "Recipe attachment: Demo Recipe\n(1 files, ~42 tokens)\n\n# notes.txt\n```txt\nhello\n```"
    ]
    captured = capsys.readouterr()
    assert "Recipe: Demo Recipe" in captured.out
    assert "Queued recipe 'Demo Recipe' for next request." in captured.out


def test_recipe_command_cancels_attachment_when_not_confirmed(capsys, monkeypatch, tmp_path):
    recipe = Recipe(name="demo", display_name="Demo Recipe", description="Test recipe", globs=["*.txt"])
    match = RecipeMatch(
        recipe=recipe, matched_paths=[tmp_path / "notes.txt"], skipped_paths=[], rendered="payload", estimated_tokens=5
    )
    state = make_slash_command_state(tmp_path)

    monkeypatch.setattr("tuochat.context.recipes.get_recipe", lambda name: recipe if name == "demo" else None)
    monkeypatch.setattr("tuochat.context.recipes.expand_recipe", lambda selected_recipe: match)
    monkeypatch.setattr("tuochat.cli.repl.prompt_input", lambda prompt: "n")

    message, should_exit = handle_slash_command("/recipe demo", state)

    assert message is None
    assert should_exit is False
    assert state.pending_attachment_names == []
    assert state.pending_attachment_messages == []
    assert "Recipe attachment cancelled." in capsys.readouterr().out
