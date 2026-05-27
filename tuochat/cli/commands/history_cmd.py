"""History command implementation."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tuochat.cli.command_models import HistoryCommand
    from tuochat.config import TuochatConfig
    from tuochat.persistence import ConversationStore, NullConversationStore


def run(
    cfg: TuochatConfig,
    command: HistoryCommand,
    *,
    build_store: Callable[[TuochatConfig], ConversationStore | NullConversationStore],
    no_write_enabled: Callable[[TuochatConfig], bool],
) -> int:
    """List past conversations."""
    if no_write_enabled(cfg):
        print("History is unavailable while no-write mode is enabled because no local database is used.")
        return 0

    store = build_store(cfg)
    try:
        conversations = store.list_conversations(limit=command.limit)
        if not conversations:
            print("No conversations found.")
            return 0

        print(f"{'ID':<38} {'Title':<40} {'Updated':<20}")
        print("-" * 98)
        for conv in conversations:
            title = (conv.title or "Untitled")[:40]
            updated = conv.updated_at[:19] if conv.updated_at else ""
            print(f"{conv.id[:8]:<38} {title:<40} {updated:<20}")
    finally:
        store.close()

    return 0
