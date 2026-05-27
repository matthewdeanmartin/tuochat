"""Search command implementation."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from tuochat.cli.command_models import SearchCommand
    from tuochat.config import TuochatConfig
    from tuochat.models import ConversationSearchResult
    from tuochat.persistence import ConversationStore, NullConversationStore


class SearchFunc(Protocol):
    """Protocol for conversation search function."""

    def __call__(
        self,
        store: ConversationStore | NullConversationStore,
        query: str,
        *,
        limit: int = 20,
        title_filter: str | None = None,
        updated_after: str | None = None,
        updated_before: str | None = None,
    ) -> list[ConversationSearchResult]:
        """Execute a conversation search."""


def run(
    cfg: TuochatConfig,
    command: SearchCommand,
    *,
    build_store: Callable[[TuochatConfig], ConversationStore | NullConversationStore],
    no_write_enabled: Callable[[TuochatConfig], bool],
    run_conversation_search: SearchFunc,
) -> int:
    """Search saved conversations by message content."""
    if no_write_enabled(cfg):
        print("Search is unavailable while no-write mode is enabled because no local database is used.")
        return 0

    store = build_store(cfg)
    try:
        query = " ".join(command.query).strip()
        matches = run_conversation_search(
            store,
            query,
            limit=command.limit,
            title_filter=command.title,
            updated_after=command.after,
            updated_before=command.before,
        )
        if not matches:
            print(f"No conversations matched {query!r}.")
            return 0

        print(f"{'ID':<10} {'Title':<40} {'Updated':<20} {'Role':<10} Snippet")
        print("-" * 120)
        for match in matches:
            title = (match.title or "Untitled")[:40]
            updated = match.updated_at[:19] if match.updated_at else ""
            snippet = re.sub(r"\s+", " ", (match.snippet or "").strip())
            print(f"{match.conversation_id[:8]:<10} {title:<40} {updated:<20} {match.role:<10} {snippet}")
    finally:
        store.close()

    return 0
