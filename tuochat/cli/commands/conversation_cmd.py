"""Shared conversation-management commands for CLI and REPL dispatch."""

from __future__ import annotations

import re
import sys
from typing import TYPE_CHECKING

from tuochat.serialization import json_dumps

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from tuochat.cli.command_models import (
        ArchiveConversationCommand,
        DeleteConversationCommand,
        ListConversationsCommand,
        OpenConversationCommand,
        UnarchiveConversationCommand,
    )
    from tuochat.config import TuochatConfig
    from tuochat.models import Conversation, ConversationSearchResult
    from tuochat.persistence import ConversationStore, NullConversationStore


def resolve_conversation_id(
    store: ConversationStore | NullConversationStore,
    partial_id: str,
    *,
    archived: bool = False,
) -> str | None:
    """Resolve a partial conversation ID to a full one."""
    conversations = store.list_archived_conversations(limit=1000) if archived else store.list_conversations(limit=1000)
    matches = [conversation for conversation in conversations if conversation.id.startswith(partial_id)]
    if len(matches) == 1:
        return matches[0].id
    if len(matches) > 1:
        qualifier = "archived " if archived else ""
        print(f"Ambiguous {qualifier}ID '{partial_id}' — matches {len(matches)} conversations.", file=sys.stderr)
        for conversation in matches[:5]:
            print(f"  {conversation.id}  {conversation.title or 'Untitled'}", file=sys.stderr)
        return None
    qualifier = "archived " if archived else ""
    print(f"No {qualifier}conversation found matching '{partial_id}'.", file=sys.stderr)
    return None


def conversation_payload(conversation: Conversation) -> dict[str, object]:
    """Return a JSON-friendly conversation summary."""
    return {
        "id": conversation.id,
        "title": conversation.title or "Untitled",
        "archived": bool(conversation.archived),
        "resource_id": conversation.resource_id,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
    }


def print_conversation_table(conversations: list[Conversation]) -> None:
    """Render a conversation summary table."""
    print(f"{'ID':<10} {'Title':<40} {'Updated':<20} {'Archived':<8}")
    print("-" * 84)
    for conversation in conversations:
        title = (conversation.title or "Untitled")[:40]
        updated = conversation.updated_at[:19] if conversation.updated_at else ""
        archived = "yes" if conversation.archived else "no"
        print(f"{conversation.id[:8]:<10} {title:<40} {updated:<20} {archived:<8}")


def run_list(
    cfg: TuochatConfig,
    command: ListConversationsCommand,
    *,
    build_store: Callable[[TuochatConfig], ConversationStore | NullConversationStore],
    no_write_enabled: Callable[[TuochatConfig], bool],
) -> int:
    """List active or archived conversations."""
    if no_write_enabled(cfg):
        print("Conversation listing is unavailable while no-write mode is enabled because no local database is used.")
        return 0
    store = build_store(cfg)
    try:
        conversations = store.list_conversations(limit=command.limit, archived=command.archived)
    finally:
        store.close()
    if command.format == "json":
        print(json_dumps([conversation_payload(conversation) for conversation in conversations], indent=True))
        return 0
    if not conversations:
        print("No conversations found.")
        return 0
    print_conversation_table(conversations)
    return 0


def run_archive(
    cfg: TuochatConfig,
    command: ArchiveConversationCommand,
    *,
    build_store: Callable[[TuochatConfig], ConversationStore | NullConversationStore],
    no_write_enabled: Callable[[TuochatConfig], bool],
) -> int:
    """Archive a saved conversation."""
    if no_write_enabled(cfg):
        print(
            "Archive is unavailable while no-write mode is enabled because no local conversations are stored.",
            file=sys.stderr,
        )
        return 1
    if not command.id:
        print("Conversation ID is required.", file=sys.stderr)
        return 1
    store = build_store(cfg)
    try:
        conversation_id = resolve_conversation_id(store, command.id)
        if conversation_id is None:
            return 1
        if not store.set_conversation_archived(conversation_id, True):
            print(f"Conversation {conversation_id} could not be archived.", file=sys.stderr)
            return 1
    finally:
        store.close()
    print(f"Archived conversation {conversation_id[:8]}.")
    return 0


def run_unarchive(
    cfg: TuochatConfig,
    command: UnarchiveConversationCommand,
    *,
    build_store: Callable[[TuochatConfig], ConversationStore | NullConversationStore],
    no_write_enabled: Callable[[TuochatConfig], bool],
) -> int:
    """Unarchive one or all conversations."""
    if no_write_enabled(cfg):
        print(
            "Unarchive is unavailable while no-write mode is enabled because no local conversations are stored.",
            file=sys.stderr,
        )
        return 1
    store = build_store(cfg)
    try:
        if command.all:
            restored = store.unarchive_all_conversations()
            print(f"Unarchived {restored} conversation(s).")
            return 0
        if not command.id:
            print("Conversation ID or --all is required.", file=sys.stderr)
            return 1
        conversation_id = resolve_conversation_id(store, command.id, archived=True)
        if conversation_id is None:
            return 1
        if not store.set_conversation_archived(conversation_id, False):
            print(f"Conversation {conversation_id} could not be unarchived.", file=sys.stderr)
            return 1
    finally:
        store.close()
    print(f"Unarchived conversation {conversation_id[:8]}.")
    return 0


def run_delete(
    cfg: TuochatConfig,
    command: DeleteConversationCommand,
    *,
    build_store: Callable[[TuochatConfig], ConversationStore | NullConversationStore],
    no_write_enabled: Callable[[TuochatConfig], bool],
) -> int:
    """Delete a saved conversation."""
    if no_write_enabled(cfg):
        print(
            "Delete is unavailable while no-write mode is enabled because no local conversations are stored.",
            file=sys.stderr,
        )
        return 1
    if not command.id:
        print("Conversation ID is required.", file=sys.stderr)
        return 1
    store = build_store(cfg)
    try:
        conversation_id = resolve_conversation_id(store, command.id)
        if conversation_id is None:
            return 1
        if not store.delete_conversation(conversation_id):
            print(f"Conversation {conversation_id} could not be deleted.", file=sys.stderr)
            return 1
    finally:
        store.close()
    print(f"Deleted conversation {conversation_id[:8]}.")
    return 0


def run_open(
    cfg: TuochatConfig,
    command: OpenConversationCommand,
    *,
    build_store: Callable[[TuochatConfig], ConversationStore | NullConversationStore],
    no_write_enabled: Callable[[TuochatConfig], bool],
    sync_conversation_artifacts: Callable[[TuochatConfig, Conversation], tuple[Path | None, Path | None, list[Path]]],
    open_path: Callable[[Path], tuple[bool, str]],
) -> int:
    """Open the filesystem archive for a saved conversation."""
    if no_write_enabled(cfg):
        print(
            "Open is unavailable while no-write mode is enabled because conversation files are not being written.",
            file=sys.stderr,
        )
        return 1
    if not command.id:
        print("Conversation ID is required.", file=sys.stderr)
        return 1
    store = build_store(cfg)
    try:
        conversation_id = resolve_conversation_id(store, command.id)
        if conversation_id is None:
            return 1
        conversation = store.get_conversation(conversation_id)
        if conversation is None:
            print(f"Conversation {conversation_id} not found.", file=sys.stderr)
            return 1
        conversation.messages = store.get_messages(conversation_id)
        archive_dir, markdown_path, extracted = sync_conversation_artifacts(cfg, conversation)
    finally:
        store.close()
    if archive_dir is None:
        print("Open failed: conversation archive is unavailable.", file=sys.stderr)
        return 1
    opened, detail = open_path(archive_dir)
    if not opened:
        print(f"Open failed: {detail}", file=sys.stderr)
        return 1
    print(f"Opened conversation archive: {detail}")
    print(f"Markdown: {markdown_path}")
    print(f"Extracted files: {len(extracted)} in {archive_dir}")
    return 0


def print_search_results(matches: list[ConversationSearchResult]) -> None:
    """Render conversation search results."""
    print(f"{'ID':<10} {'Title':<40} {'Updated':<20} {'Role':<10} Snippet")
    print("-" * 120)
    for match in matches:
        title = (match.title or "Untitled")[:40]
        updated = match.updated_at[:19] if match.updated_at else ""
        snippet = re.sub(r"\s+", " ", (match.snippet or "").strip())
        print(f"{match.conversation_id[:8]:<10} {title:<40} {updated:<20} {match.role:<10} {snippet}")
