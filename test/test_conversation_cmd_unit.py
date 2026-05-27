from __future__ import annotations

from unittest.mock import MagicMock

from tuochat.cli.command_models import (
    ArchiveConversationCommand,
    DeleteConversationCommand,
    ListConversationsCommand,
    UnarchiveConversationCommand,
)
from tuochat.cli.commands.conversation_cmd import (
    conversation_payload,
    resolve_conversation_id,
    run_archive,
    run_delete,
    run_list,
    run_unarchive,
)


def test_resolve_conversation_id_single_match():
    mock_store = MagicMock()
    mock_conv = MagicMock()
    mock_conv.id = "abcdef123456"
    mock_store.list_conversations.return_value = [mock_conv]

    result = resolve_conversation_id(mock_store, "abc")
    assert result == "abcdef123456"


def test_resolve_conversation_id_ambiguous(capsys):
    mock_store = MagicMock()
    c1 = MagicMock()
    c1.id = "abc1"
    c2 = MagicMock()
    c2.id = "abc2"
    mock_store.list_conversations.return_value = [c1, c2]

    result = resolve_conversation_id(mock_store, "abc")
    assert result is None
    err = capsys.readouterr().err
    assert "Ambiguous" in err


def test_resolve_conversation_id_no_match(capsys):
    mock_store = MagicMock()
    mock_store.list_conversations.return_value = []

    result = resolve_conversation_id(mock_store, "abc")
    assert result is None
    err = capsys.readouterr().err
    assert "No conversation found" in err


def test_conversation_payload():
    mock_conv = MagicMock()
    mock_conv.id = "id"
    mock_conv.title = "title"
    mock_conv.archived = True
    mock_conv.resource_id = "res"
    mock_conv.created_at = "created"
    mock_conv.updated_at = "updated"

    payload = conversation_payload(mock_conv)
    assert payload["id"] == "id"
    assert payload["archived"] is True


def test_run_list_no_write(capsys):
    cfg = MagicMock()
    cmd = ListConversationsCommand(format="text", limit=10, archived=False)

    result = run_list(cfg, cmd, build_store=MagicMock(), no_write_enabled=lambda _: True)
    assert result == 0
    out = capsys.readouterr().out
    assert "unavailable" in out


def test_run_list_json(capsys):
    cfg = MagicMock()
    cmd = ListConversationsCommand(format="json", limit=10, archived=False)

    mock_store = MagicMock()
    mock_conv = MagicMock()
    mock_conv.id = "id"
    mock_conv.title = "title"
    mock_conv.archived = False
    mock_conv.resource_id = None
    mock_conv.created_at = None
    mock_conv.updated_at = None
    mock_store.list_conversations.return_value = [mock_conv]

    result = run_list(cfg, cmd, build_store=lambda _: mock_store, no_write_enabled=lambda _: False)
    assert result == 0
    out = capsys.readouterr().out
    assert '"id": "id"' in out
    mock_store.close.assert_called_once()


def test_run_archive_success(capsys):
    cfg = MagicMock()
    cmd = ArchiveConversationCommand(id="abc")

    mock_store = MagicMock()
    mock_conv = MagicMock()
    mock_conv.id = "abcdef"
    mock_store.list_conversations.return_value = [mock_conv]
    mock_store.set_conversation_archived.return_value = True

    result = run_archive(cfg, cmd, build_store=lambda _: mock_store, no_write_enabled=lambda _: False)
    assert result == 0
    out = capsys.readouterr().out
    assert "Archived conversation abcdef" in out
    mock_store.set_conversation_archived.assert_called_with("abcdef", True)


def test_run_unarchive_all(capsys):
    cfg = MagicMock()
    cmd = UnarchiveConversationCommand(all=True)

    mock_store = MagicMock()
    mock_store.unarchive_all_conversations.return_value = 5

    result = run_unarchive(cfg, cmd, build_store=lambda _: mock_store, no_write_enabled=lambda _: False)
    assert result == 0
    out = capsys.readouterr().out
    assert "Unarchived 5" in out


def test_run_delete_success(capsys):
    cfg = MagicMock()
    cmd = DeleteConversationCommand(id="abc")

    mock_store = MagicMock()
    mock_conv = MagicMock()
    mock_conv.id = "abcdef"
    mock_store.list_conversations.return_value = [mock_conv]
    mock_store.delete_conversation.return_value = True

    result = run_delete(cfg, cmd, build_store=lambda _: mock_store, no_write_enabled=lambda _: False)
    assert result == 0
    out = capsys.readouterr().out
    assert "Deleted conversation abcdef" in out
