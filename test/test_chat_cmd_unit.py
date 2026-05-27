"""Unit and smoke tests for the chat automation commands (chat new, send, show, latest).

Uses the Eliza provider for dry-run testing — no live API keys needed.
Uses tmp_path (pytest fixture) for isolated conversation stores.
"""

from __future__ import annotations

import json
from pathlib import Path

from tuochat.cli.command_models import ChatLatestCommand, ChatNewCommand, ChatSendCommand, ChatShowCommand
from tuochat.cli.commands.chat_cmd import (
    apply_cwd_override,
    conversation_envelope,
    err_envelope,
    ok_envelope,
    resolve_target_conversation,
    run_chat_latest,
    run_chat_new,
    run_chat_send,
    run_chat_show,
)
from tuochat.config import TuochatConfig
from tuochat.models import Conversation
from tuochat.persistence.store import ConversationStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_config(tmp_path: Path) -> TuochatConfig:
    cfg = TuochatConfig()
    cfg.data_dir = tmp_path
    return cfg


def build_store_factory(tmp_path: Path):
    """Return a store factory that uses tmp_path for isolation."""

    def factory(cfg: TuochatConfig) -> ConversationStore:
        return ConversationStore(tmp_path / "test.db")

    return factory


def fake_provider(cfg, timeout=None):
    """Stub provider factory — never called because model=eliza."""
    raise AssertionError("Should not be called for eliza model")


def no_write_false(cfg):
    return False


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------


def test_conversation_envelope_fields():
    conv = Conversation(title="hello", cwd="/tmp", resource_id="gid://1")
    env = conversation_envelope(conv)
    assert env["id"] == conv.id
    assert env["title"] == "hello"
    assert env["cwd"] == "/tmp"
    assert env["resource_id"] == "gid://1"
    assert "model" in env


def test_ok_envelope_structure():
    conv = Conversation(title="T")
    result = {"model": "eliza", "response_text": "hi"}
    env = ok_envelope("chat new", conv, result, [])
    assert env["ok"] is True
    assert env["command"] == "chat new"
    assert env["errors"] == []
    assert env["warnings"] == []
    assert "conversation" in env
    assert env["result"]["response_text"] == "hi"


def test_err_envelope_structure():
    env = err_envelope("chat send", ["Something went wrong"])
    assert env["ok"] is False
    assert env["errors"] == ["Something went wrong"]
    assert env["conversation"] is None


# ---------------------------------------------------------------------------
# resolve_target_conversation
# ---------------------------------------------------------------------------


def test_resolve_target_latest_returns_first_conversation(tmp_path):
    store = ConversationStore(tmp_path / "resolve.db")
    c1 = Conversation(title="first")
    c2 = Conversation(title="second")
    store.save_conversation(c1)
    store.save_conversation(c2)

    def noop_resolve(store, partial):
        return None

    conv_id, warnings = resolve_target_conversation(store, "latest", noop_resolve)
    assert conv_id is not None
    store.close()


def test_resolve_target_latest_empty_store(tmp_path):
    store = ConversationStore(tmp_path / "empty.db")
    conv_id, warnings = resolve_target_conversation(store, "latest", lambda s, p: None)
    assert conv_id is None
    store.close()


def test_resolve_target_prefix_delegates(tmp_path):
    store = ConversationStore(tmp_path / "prefix.db")
    conv = Conversation(title="prefix test")
    store.save_conversation(conv)

    def resolver(s, partial):
        convs = s.list_conversations(limit=1000)
        matches = [c for c in convs if c.id.startswith(partial)]
        return matches[0].id if len(matches) == 1 else None

    conv_id, warnings = resolve_target_conversation(store, conv.id[:8], resolver)
    assert conv_id == conv.id
    store.close()


# ---------------------------------------------------------------------------
# apply_cwd_override
# ---------------------------------------------------------------------------


def test_apply_cwd_override_with_valid_dir(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("os.chdir", lambda p: calls.append(str(p)))
    conv = Conversation(cwd=str(tmp_path))
    warnings = apply_cwd_override(conv, tmp_path, restore_cwd=False)
    assert len(warnings) == 0
    assert len(calls) == 1


def test_apply_cwd_override_invalid_dir_warns(tmp_path, monkeypatch):
    monkeypatch.setattr("os.chdir", lambda p: None)
    conv = Conversation()
    bad = tmp_path / "does_not_exist"
    warnings = apply_cwd_override(conv, bad, restore_cwd=False)
    assert len(warnings) == 1
    assert "not a valid directory" in warnings[0]


def test_apply_cwd_override_restore_cwd(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("os.chdir", lambda p: calls.append(str(p)))
    conv = Conversation(cwd=str(tmp_path))
    warnings = apply_cwd_override(conv, None, restore_cwd=True)
    assert len(warnings) == 0
    assert len(calls) == 1


def test_apply_cwd_override_restore_cwd_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("os.chdir", lambda p: None)
    monkeypatch.setattr("os.getcwd", lambda: "/current")
    conv = Conversation(cwd=str(tmp_path / "gone"))
    warnings = apply_cwd_override(conv, None, restore_cwd=True)
    assert len(warnings) == 1
    assert "no longer exists" in warnings[0]


# ---------------------------------------------------------------------------
# run_chat_new — smoke tests with Eliza
# ---------------------------------------------------------------------------


def test_run_chat_new_markdown_output(tmp_path, capsys):
    cfg = make_config(tmp_path)
    command = ChatNewCommand(
        prompt="Hello from test",
        model="eliza",
        format="markdown",
    )
    result = run_chat_new(cfg, command, build_provider=fake_provider, build_store=build_store_factory(tmp_path))
    assert result == 0
    out = capsys.readouterr().out
    assert "chat new" in out
    assert "## Conversation" in out
    assert "## Result" in out
    assert "### Response" in out


def test_run_chat_new_json_output(tmp_path, capsys):
    cfg = make_config(tmp_path)
    command = ChatNewCommand(
        prompt="Hello from test",
        model="eliza",
        format="json",
    )
    result = run_chat_new(cfg, command, build_provider=fake_provider, build_store=build_store_factory(tmp_path))
    assert result == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["command"] == "chat new"
    assert "id" in payload["conversation"]
    assert "response_text" in payload["result"]
    assert payload["result"]["response_text"]


def test_run_chat_new_no_prompt_creates_conversation(tmp_path, capsys):
    """Chat new with no message just creates the conversation without sending."""
    cfg = make_config(tmp_path)
    command = ChatNewCommand(model="eliza", format="json")
    result = run_chat_new(cfg, command, build_provider=fake_provider, build_store=build_store_factory(tmp_path))
    assert result == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["result"]["response_text"] is None


def test_run_chat_new_saves_cwd(tmp_path, capsys):
    cfg = make_config(tmp_path)
    command = ChatNewCommand(
        prompt="Please summarize the working directory structure for this project",
        model="eliza",
        format="json",
        cwd=tmp_path,
    )
    result = run_chat_new(cfg, command, build_provider=fake_provider, build_store=build_store_factory(tmp_path))
    assert result == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["conversation"]["cwd"] is not None


# ---------------------------------------------------------------------------
# run_chat_send — smoke tests with Eliza
# ---------------------------------------------------------------------------


def make_resolver(store):
    """Return a simple resolve_conversation_id that searches the given store."""
    from tuochat.cli.commands.conversation_cmd import resolve_conversation_id

    return resolve_conversation_id


def test_run_chat_send_latest_creates_if_missing(tmp_path, capsys):
    """Chat send --conversation latest with no conversations falls back to new."""
    cfg = make_config(tmp_path)
    command = ChatSendCommand(
        conversation="latest",
        prompt="test fallback",
        model="eliza",
        format="json",
    )
    result = run_chat_send(
        cfg,
        command,
        build_provider=fake_provider,
        build_store=build_store_factory(tmp_path),
        resolve_conversation_id=make_resolver(None),
    )
    assert result == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["ok"] is True
    assert "No conversation found" in payload["warnings"][0]


def test_run_chat_send_to_existing_conversation(tmp_path, capsys):
    """Chat send resumes an existing conversation correctly."""
    cfg = make_config(tmp_path)
    store_factory = build_store_factory(tmp_path)

    # First create a conversation via chat new
    new_cmd = ChatNewCommand(
        prompt="Please describe the overall structure of this software project in detail",
        model="eliza",
        format="json",
    )
    run_chat_new(cfg, new_cmd, build_provider=fake_provider, build_store=store_factory)
    out1 = capsys.readouterr().out
    conv_id = json.loads(out1)["conversation"]["id"]

    # Now send to it
    send_cmd = ChatSendCommand(
        conversation=conv_id[:8],
        prompt="Now explain the testing strategy and how the tests are organized in this project",
        model="eliza",
        format="json",
    )
    result = run_chat_send(
        cfg,
        send_cmd,
        build_provider=fake_provider,
        build_store=store_factory,
        resolve_conversation_id=make_resolver(None),
    )
    assert result == 0
    out2 = capsys.readouterr().out
    payload = json.loads(out2)
    assert payload["ok"] is True
    assert payload["conversation"]["id"] == conv_id


def test_run_chat_send_fail_if_missing(tmp_path, capsys):
    """Chat send --fail-if-missing exits 1 when no conversation exists."""
    cfg = make_config(tmp_path)
    command = ChatSendCommand(
        conversation="deadbeef",
        prompt="should fail",
        model="eliza",
        format="json",
        fail_if_missing=True,
    )
    result = run_chat_send(
        cfg,
        command,
        build_provider=fake_provider,
        build_store=build_store_factory(tmp_path),
        resolve_conversation_id=make_resolver(None),
    )
    assert result == 1


def test_run_chat_send_restores_cwd(tmp_path, monkeypatch, capsys):
    """Chat send --restore-cwd changes to the saved conversation directory."""
    cfg = make_config(tmp_path)
    store_factory = build_store_factory(tmp_path)
    chdir_calls: list[str] = []
    monkeypatch.setattr("os.chdir", lambda p: chdir_calls.append(str(p)))

    # Create a conversation with a specific cwd
    store = ConversationStore(tmp_path / "test.db")
    conv = Conversation(title="cwd test", cwd=str(tmp_path))
    store.save_conversation(conv)
    store.close()

    send_cmd = ChatSendCommand(
        conversation="latest",
        prompt="Please describe the working directory structure and list the main source files",
        model="eliza",
        format="json",
        restore_cwd=True,
    )
    result = run_chat_send(
        cfg,
        send_cmd,
        build_provider=fake_provider,
        build_store=store_factory,
        resolve_conversation_id=make_resolver(None),
    )
    assert result == 0
    # chdir should have been called with the saved cwd
    assert any(str(tmp_path) in c for c in chdir_calls)


# ---------------------------------------------------------------------------
# run_chat_show
# ---------------------------------------------------------------------------


def test_run_chat_show_markdown(tmp_path, capsys):
    cfg = make_config(tmp_path)
    store_factory = build_store_factory(tmp_path)

    # Create a conversation first
    new_cmd = ChatNewCommand(prompt="Setup conversation", model="eliza", format="json")
    run_chat_new(cfg, new_cmd, build_provider=fake_provider, build_store=store_factory)
    capsys.readouterr()  # discard

    show_cmd = ChatShowCommand(conversation="latest", format="markdown")
    result = run_chat_show(
        cfg,
        show_cmd,
        build_store=store_factory,
        no_write_enabled=no_write_false,
        resolve_conversation_id=make_resolver(None),
    )
    assert result == 0
    out = capsys.readouterr().out
    assert "## Conversation" in out
    assert "message_count" in out


def test_run_chat_show_json(tmp_path, capsys):
    cfg = make_config(tmp_path)
    store_factory = build_store_factory(tmp_path)

    new_cmd = ChatNewCommand(prompt="JSON show test", model="eliza", format="json")
    run_chat_new(cfg, new_cmd, build_provider=fake_provider, build_store=store_factory)
    capsys.readouterr()

    show_cmd = ChatShowCommand(conversation="latest", format="json")
    result = run_chat_show(
        cfg,
        show_cmd,
        build_store=store_factory,
        no_write_enabled=no_write_false,
        resolve_conversation_id=make_resolver(None),
    )
    assert result == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["ok"] is True
    assert "message_count" in payload["result"]


def test_run_chat_show_fail_if_missing(tmp_path, capsys):
    cfg = make_config(tmp_path)
    show_cmd = ChatShowCommand(conversation="deadbeef", format="json", fail_if_missing=True)
    result = run_chat_show(
        cfg,
        show_cmd,
        build_store=build_store_factory(tmp_path),
        no_write_enabled=no_write_false,
        resolve_conversation_id=make_resolver(None),
    )
    assert result == 1


# ---------------------------------------------------------------------------
# run_chat_latest
# ---------------------------------------------------------------------------


def test_run_chat_latest_markdown(tmp_path, capsys):
    cfg = make_config(tmp_path)
    store_factory = build_store_factory(tmp_path)

    new_cmd = ChatNewCommand(prompt="Latest test", model="eliza", format="json")
    run_chat_new(cfg, new_cmd, build_provider=fake_provider, build_store=store_factory)
    capsys.readouterr()

    result = run_chat_latest(
        cfg, ChatLatestCommand(format="markdown"), build_store=store_factory, no_write_enabled=no_write_false
    )
    assert result == 0
    out = capsys.readouterr().out
    assert "Latest Conversation" in out
    assert "id:" in out


def test_run_chat_latest_json(tmp_path, capsys):
    cfg = make_config(tmp_path)
    store_factory = build_store_factory(tmp_path)

    new_cmd = ChatNewCommand(prompt="Latest JSON test", model="eliza", format="json")
    run_chat_new(cfg, new_cmd, build_provider=fake_provider, build_store=store_factory)
    capsys.readouterr()

    result = run_chat_latest(
        cfg, ChatLatestCommand(format="json"), build_store=store_factory, no_write_enabled=no_write_false
    )
    assert result == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["ok"] is True
    assert "id" in payload["conversation"]


def test_run_chat_latest_empty_store(tmp_path, capsys):
    cfg = make_config(tmp_path)
    result = run_chat_latest(
        cfg,
        ChatLatestCommand(format="markdown"),
        build_store=build_store_factory(tmp_path),
        no_write_enabled=no_write_false,
    )
    assert result == 0
    out = capsys.readouterr().out
    assert "No conversations found" in out


# ---------------------------------------------------------------------------
# Parser integration: verify new commands appear in --help
# ---------------------------------------------------------------------------


def test_parser_chat_subcommands():
    from tuochat.cli.entrypoint import build_parser

    parser = build_parser()
    # Collect all subparser choices
    choices = set()
    for action in parser._subparsers._group_actions:
        choices.update(action.choices.keys())
    assert "chat" in choices
    assert "repl" in choices
    assert "interactive" in choices


def test_parser_chat_new_has_format():
    """Chat new exposes --format with markdown default."""
    from tuochat.cli.entrypoint import build_parser

    parser = build_parser()
    args = parser.parse_args(["chat", "new", "hello", "--format", "json", "--model", "eliza"])
    assert args.format == "json"
    assert args.model == "eliza"
    assert args.message == "hello"


def test_parser_chat_send_defaults():
    """Chat send defaults: conversation=latest, restore_cwd=True."""
    from tuochat.cli.entrypoint import build_parser

    parser = build_parser()
    args = parser.parse_args(["chat", "send", "hello"])
    assert args.conversation == "latest"
    assert args.restore_cwd is True
    assert args.fail_if_missing is False


def test_parser_repl_key():
    """Tuochat repl sets command_key=repl."""
    from tuochat.cli.entrypoint import build_parser

    parser = build_parser()
    args = parser.parse_args(["repl"])
    assert args.command_key == "repl"


def test_dispatch_chat_new_builds_command():
    """command_from_args produces ChatNewCommand for chat new."""
    from types import SimpleNamespace

    from tuochat.cli.command_models import ChatNewCommand
    from tuochat.cli.dispatch import command_from_args

    args = SimpleNamespace(
        command_key="chat-new",
        message="hello",
        prompt_file=None,
        stdin=False,
        include=[],
        web=[],
        skill=None,
        template=None,
        var=[],
        output_file=None,
        format="json",
        no_stream=False,
        system_prompt=None,
        resource_id=None,
        timeout=None,
        model="eliza",
        cwd=None,
    )
    cmd = command_from_args(args)
    assert isinstance(cmd, ChatNewCommand)
    assert cmd.prompt == "hello"
    assert cmd.format == "json"
    assert cmd.model == "eliza"


def test_dispatch_chat_send_builds_command():
    from types import SimpleNamespace

    from tuochat.cli.command_models import ChatSendCommand
    from tuochat.cli.dispatch import command_from_args

    args = SimpleNamespace(
        command_key="chat-send",
        conversation="latest",
        message="continue",
        prompt_file=None,
        stdin=False,
        include=[],
        web=[],
        skill=None,
        template=None,
        var=[],
        output_file=None,
        format="markdown",
        no_stream=False,
        timeout=None,
        model="eliza",
        cwd=None,
        restore_cwd=True,
        fail_if_missing=False,
    )
    cmd = command_from_args(args)
    assert isinstance(cmd, ChatSendCommand)
    assert cmd.conversation == "latest"
    assert cmd.restore_cwd is True
