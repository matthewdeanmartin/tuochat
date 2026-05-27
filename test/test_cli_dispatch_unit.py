"""Unit tests for CLI dispatch wrappers and split command modules."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tuochat.cli.command_models import (
    ChatCommand,
    ConfigCommand,
    DoctorCommand,
    ExportCommand,
    GlobalOptions,
    GuiCommand,
    HeadlessAskCommand,
    HistoryCommand,
    InitCommand,
    ListConversationsCommand,
    ResumeCommand,
    SearchCommand,
)
from tuochat.cli.commands import code, export_cmd, init_cmd, search_cmd
from tuochat.cli.repl import main
from tuochat.config import TuochatConfig
from tuochat.models import Conversation, ConversationSearchResult
from tuochat.provider.duo import DuoProvider


class StoreStub:
    """Tiny store stub for command-module unit tests."""

    def __init__(self, *, conversation: Conversation | None = None, messages: list | None = None) -> None:
        self.conversation = conversation
        self.messages = list(messages or [])
        self.closed = False
        self.requested_id: str | None = None
        self.messages_id: str | None = None

    def close(self) -> None:
        self.closed = True

    def get_conversation(self, conversation_id: str) -> Conversation | None:
        self.requested_id = conversation_id
        return self.conversation

    def get_messages(self, conversation_id: str) -> list:
        self.messages_id = conversation_id
        return list(self.messages)


def test_run_config_delegates_to_cmd_config():
    cfg = TuochatConfig()

    with patch("tuochat.cli.commands.code.cmd_config", return_value=17) as cmd_config:
        result = code.run_config(cfg, ConfigCommand(format="json"))

    assert result == 17
    assert cmd_config.call_args.args == (cfg,)
    assert cmd_config.call_args.kwargs == {"fmt": "json"}


def test_run_init_builds_namespace_from_global_options():
    global_options = GlobalOptions(config_path=Path("config.toml"))

    with patch("tuochat.cli.commands.code.cmd_init", return_value=5) as cmd_init:
        result = code.run_init(global_options, InitCommand(force=True))

    assert result == 5
    args = cmd_init.call_args.args[0]
    assert args.config == "config.toml"
    assert args.force is True


def test_run_chat_builds_namespace_with_debug_override():
    cfg = TuochatConfig()
    global_options = GlobalOptions(config_path=Path("chat.toml"), debug=True)
    command = ChatCommand(prompt="system", resource_id="gid://1", no_stream=True, timeout=9)

    with patch("tuochat.cli.commands.code.cmd_chat", return_value=3) as cmd_chat:
        result = code.run_chat(cfg, global_options, command)

    assert result == 3
    args = cmd_chat.call_args.args[1]
    assert cmd_chat.call_args.args[0] is cfg
    assert args.config == "chat.toml"
    assert args.prompt == "system"
    assert args.resource_id == "gid://1"
    assert args.no_stream is True
    assert args.timeout == 9
    assert args.debug is True


def test_run_gui_builds_namespace_with_debug_override():
    cfg = TuochatConfig()
    global_options = GlobalOptions(config_path=Path("gui.toml"), debug=True)
    command = GuiCommand(prompt="system", resource_id="gid://2", no_stream=True, timeout=11)

    with patch("tuochat.cli.commands.code.cmd_gui", return_value=7) as cmd_gui:
        result = code.run_gui(cfg, global_options, command)

    assert result == 7
    args = cmd_gui.call_args.args[1]
    assert cmd_gui.call_args.args[0] is cfg
    assert args.config == "gui.toml"
    assert args.prompt == "system"
    assert args.resource_id == "gid://2"
    assert args.no_stream is True
    assert args.timeout == 11
    assert args.debug is True


def test_run_history_wraps_limit_only():
    cfg = TuochatConfig()

    with patch("tuochat.cli.commands.code.cmd_history", return_value=11) as cmd_history:
        result = code.run_history(cfg, HistoryCommand(limit=7))

    assert result == 11
    assert cmd_history.call_args.args[0] is cfg
    assert cmd_history.call_args.args[1].limit == 7


def test_run_resume_wraps_resume_id():
    cfg = TuochatConfig()

    with patch("tuochat.cli.commands.code.cmd_resume", return_value=13) as cmd_resume:
        result = code.run_resume(cfg, ResumeCommand(id="abc123"))

    assert result == 13
    assert cmd_resume.call_args.args[0] is cfg
    assert cmd_resume.call_args.args[1].id == "abc123"


def test_cmd_chat_resets_duo_conversation_on_fresh_start(tmp_path):
    cfg = TuochatConfig()
    cfg.gitlab.host = "https://gitlab.com"
    cfg.gitlab.token = "glpat-test"
    cfg.config_dir = tmp_path / "config"
    cfg.data_dir = tmp_path / "data"
    cfg.log_dir = tmp_path / "logs"
    _args = SimpleNamespace(config=None, prompt=None, resource_id=None, no_stream=False, timeout=None, debug=False)
    provider = MagicMock(spec=DuoProvider)
    store = MagicMock()

    with (
        patch("tuochat.cli.repl.maybe_run_first_run_setup", return_value=cfg),
        patch("tuochat.cli.repl.build_provider", return_value=provider),
        patch("tuochat.cli.repl.build_store", return_value=store),
        patch("tuochat.cli.repl.print_expiration_warning"),
        patch("tuochat.cli.repl.maybe_prune_expired_conversations"),
        patch("tuochat.cli.repl.compose_system_prompt", return_value=(None, [])),
        patch("tuochat.cli.repl.load_custom_instruction_sections", return_value=[]),
        patch("tuochat.cli.repl.print_session_intro"),
        patch("tuochat.cli.repl.should_offer_first_run_tutorial", return_value=False),
        patch("tuochat.cli.repl.run_repl_loop"),
        patch("tuochat.cli.repl.finalize_repl_session"),
    ):
        assert main(["chat"]) == 0

    provider.reset_conversation.assert_called_once_with()


def test_cmd_resume_does_not_reset_duo_conversation_on_startup(tmp_path):
    cfg = TuochatConfig()
    cfg.gitlab.host = "https://gitlab.com"
    cfg.gitlab.token = "glpat-test"
    cfg.config_dir = tmp_path / "config"
    cfg.data_dir = tmp_path / "data"
    cfg.log_dir = tmp_path / "logs"
    conv = Conversation(id="conv-1", title="Resume")
    provider = MagicMock(spec=DuoProvider)
    store = StoreStub(conversation=conv, messages=[])

    with (
        patch("tuochat.cli.repl.maybe_run_first_run_setup", return_value=cfg),
        patch("tuochat.cli.repl.build_provider", return_value=provider),
        patch("tuochat.cli.repl.build_store", return_value=store),
        patch("tuochat.cli.repl.print_expiration_warning"),
        patch("tuochat.cli.repl.maybe_prune_expired_conversations"),
        patch("tuochat.cli.repl.pick_conversation_id", return_value="conv-1"),
        patch("tuochat.cli.repl.sync_conversation_artifacts", return_value=(None, None, [])),
        patch("tuochat.cli.repl.clear_screen"),
        patch("tuochat.cli.repl.print_session_intro"),
        patch("tuochat.cli.repl.print_masked_conversation_transcript"),
        patch("tuochat.cli.repl.run_repl_loop"),
        patch("tuochat.cli.repl.finalize_repl_session"),
    ):
        assert main(["resume"]) == 0

    provider.reset_conversation.assert_not_called()


def test_run_search_builds_namespace_from_typed_command():
    cfg = TuochatConfig()
    command = SearchCommand(
        query=["terraform", "drift"],
        limit=4,
        title="Prod",
        after="2025-01-01",
        before="2025-01-31",
    )

    with patch("tuochat.cli.commands.code.cmd_search", return_value=19) as cmd_search:
        result = code.run_search(cfg, command)

    assert result == 19
    args = cmd_search.call_args.args[1]
    assert cmd_search.call_args.args[0] is cfg
    assert args.query == ["terraform", "drift"]
    assert args.limit == 4
    assert args.title == "Prod"
    assert args.after == "2025-01-01"
    assert args.before == "2025-01-31"


def test_run_export_wraps_optional_id():
    cfg = TuochatConfig()

    with patch("tuochat.cli.commands.code.cmd_export", return_value=23) as cmd_export:
        result = code.run_export(cfg, ExportCommand(id="conv-1"))

    assert result == 23
    assert cmd_export.call_args.args[0] is cfg
    assert cmd_export.call_args.args[1].id == "conv-1"


def test_search_cmd_no_write_returns_without_building_store(capsys):
    cfg = object()

    result = search_cmd.run(
        cfg,
        SearchCommand(query=["terraform"]),
        build_store=lambda config: (_ for _ in ()).throw(AssertionError("build_store should not be called")),
        no_write_enabled=lambda config: True,
        run_conversation_search=lambda *args, **kwargs: [],
    )

    assert result == 0
    captured = capsys.readouterr()
    assert "Search is unavailable while no-write mode is enabled" in captured.out


def test_search_cmd_passes_filters_prints_matches_and_closes_store(capsys):
    cfg = object()
    store = StoreStub()
    seen: dict[str, object] = {}

    def fake_search(store_arg, query, **kwargs):
        seen["store"] = store_arg
        seen["query"] = query
        seen["kwargs"] = kwargs
        return [
            ConversationSearchResult(
                conversation_id="12345678-abcd",
                message_id="m1",
                role="assistant",
                title="Terraform Drift",
                updated_at="2025-01-02T03:04:05+00:00",
                snippet="  drift\n   found\tin prod  ",
            )
        ]

    result = search_cmd.run(
        cfg,
        SearchCommand(
            query=["terraform", "drift"],
            limit=3,
            title="Terraform",
            after="2025-01-01",
            before="2025-01-31",
        ),
        build_store=lambda config: store,
        no_write_enabled=lambda config: False,
        run_conversation_search=fake_search,
    )

    assert result == 0
    assert store.closed is True
    assert seen["store"] is store
    assert seen["query"] == "terraform drift"
    assert seen["kwargs"] == {
        "limit": 3,
        "title_filter": "Terraform",
        "updated_after": "2025-01-01",
        "updated_before": "2025-01-31",
    }
    captured = capsys.readouterr()
    assert "Terraform Drift" in captured.out
    assert "drift found in prod" in captured.out


def test_search_cmd_closes_store_when_search_raises():
    store = StoreStub()

    with pytest.raises(RuntimeError, match="boom"):
        search_cmd.run(
            object(),
            SearchCommand(query=["broken"]),
            build_store=lambda config: store,
            no_write_enabled=lambda config: False,
            run_conversation_search=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

    assert store.closed is True


def test_export_cmd_no_write_returns_error_without_building_store(capsys):
    cfg = object()

    result = export_cmd.run(
        cfg,
        ExportCommand(id=None),
        build_store=lambda config: (_ for _ in ()).throw(AssertionError("build_store should not be called")),
        no_write_enabled=lambda config: True,
        pick_conversation_id=lambda *args: "unused",
        resolve_conversation_id=lambda *args: "unused",
        sync_conversation_artifacts=lambda *args: (None, None, []),
    )

    assert result == 1
    captured = capsys.readouterr()
    assert "Export is unavailable while no-write mode is enabled" in captured.err


def test_export_cmd_uses_picker_prints_outputs_and_closes_store(capsys, tmp_path):
    conv = Conversation(id="conv-full-id", title="Export me")
    store = StoreStub(conversation=conv, messages=["message-1"])
    archive_dir = tmp_path / "archive"
    markdown_path = archive_dir / "conversation.md"
    extracted = [tmp_path / "one.py", tmp_path / "two.py"]

    result = export_cmd.run(
        object(),
        ExportCommand(id=None, meta=True),
        build_store=lambda config: store,
        no_write_enabled=lambda config: False,
        pick_conversation_id=lambda store_arg, prompt_label: "conv-full-id" if prompt_label == "export" else None,
        resolve_conversation_id=lambda *args: (_ for _ in ()).throw(AssertionError("resolve should not be called")),
        sync_conversation_artifacts=lambda cfg, conv_arg: (archive_dir, markdown_path, extracted),
    )

    assert result == 0
    assert store.closed is True
    assert store.requested_id == "conv-full-id"
    assert store.messages_id == "conv-full-id"
    assert conv.messages == ["message-1"]
    captured = capsys.readouterr()
    assert f"Archive dir: {archive_dir}" in captured.out
    assert f"Markdown: {markdown_path}" in captured.out
    assert "Extracted files:" in captured.out
    assert "one.py" in captured.out
    assert "two.py" in captured.out


def test_export_cmd_default_prints_markdown_to_stdout(capsys, tmp_path):
    """Default export (no --meta) reads and prints the markdown file to stdout."""
    conv = Conversation(id="conv-full-id", title="Export me")
    store = StoreStub(conversation=conv, messages=["message-1"])
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()
    markdown_path = archive_dir / "conversation.md"
    markdown_path.write_text("# Conversation\n\nHello world.\n", encoding="utf-8")

    result = export_cmd.run(
        object(),
        ExportCommand(id=None, meta=False),
        build_store=lambda config: store,
        no_write_enabled=lambda config: False,
        pick_conversation_id=lambda store_arg, prompt_label: "conv-full-id" if prompt_label == "export" else None,
        resolve_conversation_id=lambda *args: (_ for _ in ()).throw(AssertionError("resolve should not be called")),
        sync_conversation_artifacts=lambda cfg, conv_arg: (archive_dir, markdown_path, []),
    )

    assert result == 0
    captured = capsys.readouterr()
    assert "# Conversation" in captured.out
    assert "Hello world." in captured.out
    assert "Archive dir:" not in captured.out


def test_export_cmd_resolves_explicit_id_and_reports_missing_conversation(capsys):
    store = StoreStub(conversation=None)

    result = export_cmd.run(
        object(),
        ExportCommand(id="partial-id"),
        build_store=lambda config: store,
        no_write_enabled=lambda config: False,
        pick_conversation_id=lambda *args: (_ for _ in ()).throw(AssertionError("picker should not be called")),
        resolve_conversation_id=lambda store_arg, partial_id: "resolved-id" if partial_id == "partial-id" else None,
        sync_conversation_artifacts=lambda *args: (None, None, []),
    )

    assert result == 1
    assert store.closed is True
    captured = capsys.readouterr()
    assert "Conversation resolved-id not found." in captured.err


def test_export_cmd_closes_store_when_selection_is_cancelled():
    store = StoreStub()

    result = export_cmd.run(
        object(),
        ExportCommand(id=None),
        build_store=lambda config: store,
        no_write_enabled=lambda config: False,
        pick_conversation_id=lambda store_arg, prompt_label: None,
        resolve_conversation_id=lambda *args: "unused",
        sync_conversation_artifacts=lambda *args: (None, None, []),
    )

    assert result == 1
    assert store.closed is True


def test_init_cmd_uses_default_config_file_when_global_path_missing():
    global_options = GlobalOptions()
    run_init_wizard = MagicMock()

    result = init_cmd.run(
        global_options,
        InitCommand(force=False),
        run_init_wizard=run_init_wizard,
        default_config_file=Path("default.toml"),
    )

    assert result == 0
    run_init_wizard.assert_called_once_with(config_path="default.toml", force=False)


def test_init_cmd_uses_global_config_path_and_force_flag():
    global_options = GlobalOptions(config_path=Path("custom.toml"))
    run_init_wizard = MagicMock()

    result = init_cmd.run(
        global_options,
        InitCommand(force=True),
        run_init_wizard=run_init_wizard,
        default_config_file=Path("unused.toml"),
    )

    assert result == 0
    run_init_wizard.assert_called_once_with(config_path="custom.toml", force=True)


def test_main_dispatches_chat_command_model():
    cfg = TuochatConfig()

    with (
        patch("tuochat.cli.repl.load_config", return_value=cfg),
        patch("tuochat.cli.commands.code.run_chat", return_value=29) as run_chat,
    ):
        result = main(
            [
                "--debug",
                "--config",
                "chat.toml",
                "chat",
                "--prompt",
                "system prompt",
                "--resource-id",
                "gid://gitlab/Project/1",
                "--no-stream",
                "--timeout",
                "7",
            ]
        )

    assert result == 29
    assert run_chat.call_args.args[0] is cfg
    assert run_chat.call_args.args[1] == GlobalOptions(debug=True, config_path=Path("chat.toml"))
    assert run_chat.call_args.args[2] == ChatCommand(
        prompt="system prompt",
        resource_id="gid://gitlab/Project/1",
        no_stream=True,
        timeout=7,
    )


def test_main_dispatches_gui_command_model():
    cfg = TuochatConfig()

    with (
        patch("tuochat.cli.repl.load_config", return_value=cfg),
        patch("tuochat.cli.commands.code.run_gui", return_value=43) as run_gui,
    ):
        result = main(
            [
                "--debug",
                "--config",
                "gui.toml",
                "gui",
                "--prompt",
                "system prompt",
                "--resource-id",
                "gid://gitlab/Project/2",
                "--no-stream",
                "--timeout",
                "11",
            ]
        )

    assert result == 43
    assert run_gui.call_args.args[0] is cfg
    assert run_gui.call_args.args[1] == GlobalOptions(debug=True, config_path=Path("gui.toml"))
    assert run_gui.call_args.args[2] == GuiCommand(
        prompt="system prompt",
        resource_id="gid://gitlab/Project/2",
        no_stream=True,
        timeout=11,
    )


def test_main_dispatches_search_command_model():
    cfg = TuochatConfig()

    with (
        patch("tuochat.cli.repl.load_config", return_value=cfg),
        patch("tuochat.cli.commands.code.run_search", return_value=31) as run_search,
    ):
        result = main(
            [
                "search",
                "terraform",
                "drift",
                "--limit",
                "4",
                "--title",
                "Prod",
                "--after",
                "2025-01-01",
                "--before",
                "2025-01-31",
            ]
        )

    assert result == 31
    assert run_search.call_args.args[0] is cfg
    assert run_search.call_args.args[1] == SearchCommand(
        query=["terraform", "drift"],
        limit=4,
        title="Prod",
        after="2025-01-01",
        before="2025-01-31",
    )


def test_main_dispatches_export_command_model():
    cfg = TuochatConfig()

    with (
        patch("tuochat.cli.repl.load_config", return_value=cfg),
        patch("tuochat.cli.commands.code.run_export", return_value=37) as run_export,
    ):
        result = main(["export", "abc123"])

    assert result == 37
    assert run_export.call_args.args[0] is cfg
    assert run_export.call_args.args[1] == ExportCommand(id="abc123")


def test_main_dispatches_init_command_model():
    cfg = TuochatConfig()

    with (
        patch("tuochat.cli.repl.load_config", return_value=cfg),
        patch("tuochat.cli.commands.code.run_init", return_value=41) as run_init,
    ):
        result = main(["--config", "setup.toml", "init", "--force"])

    assert result == 41
    assert run_init.call_args.args[0] == GlobalOptions(config_path=Path("setup.toml"))
    assert run_init.call_args.args[1] == InitCommand(force=True)


def test_main_dispatches_doctor_command_model():
    cfg = TuochatConfig()

    with (
        patch("tuochat.cli.repl.load_config", return_value=cfg),
        patch("tuochat.cli.commands.local_cmd.run_doctor", return_value=47) as run_doctor,
    ):
        result = main(["doctor", "--format", "json"])

    assert result == 47
    assert run_doctor.call_args.args[0] is cfg
    assert run_doctor.call_args.args[1] == DoctorCommand(format="json")


def test_main_dispatches_grouped_conversation_list_command_model():
    cfg = TuochatConfig()

    with (
        patch("tuochat.cli.repl.load_config", return_value=cfg),
        patch("tuochat.cli.commands.conversation_cmd.run_list", return_value=53) as run_list,
    ):
        result = main(["convo", "list", "--archived", "--format", "json", "--limit", "5"])

    assert result == 53
    assert run_list.call_args.args[0] is cfg
    assert run_list.call_args.args[1] == ListConversationsCommand(limit=5, archived=True, format="json")


def test_main_dispatches_headless_ask_command_model():
    cfg = TuochatConfig()

    with (
        patch("tuochat.cli.repl.load_config", return_value=cfg),
        patch("tuochat.cli.dispatch.run_headless_ask", return_value=59) as run_headless_ask,
    ):
        result = main(
            [
                "headless",
                "ask",
                "--model",
                "eliza",
                "--json",
                "--include",
                "README.md",
                "--var",
                "NAME=value",
                "--template",
                "starter",
            ]
        )

    assert result == 59
    assert run_headless_ask.call_args.args[0] is cfg
    assert run_headless_ask.call_args.args[1] == HeadlessAskCommand(
        includes=(Path("README.md"),),
        template="starter",
        variables=("NAME=value",),
        json_output=True,
        model="eliza",
    )
