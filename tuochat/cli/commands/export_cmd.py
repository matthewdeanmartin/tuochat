"""Export command implementation."""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from tuochat.cli.command_models import ExportCommand
    from tuochat.config import TuochatConfig
    from tuochat.models import Conversation
    from tuochat.persistence import ConversationStore, NullConversationStore


def run(
    cfg: TuochatConfig,
    command: ExportCommand,
    *,
    build_store: Callable[[TuochatConfig], ConversationStore | NullConversationStore],
    no_write_enabled: Callable[[TuochatConfig], bool],
    pick_conversation_id: Callable[[ConversationStore | NullConversationStore, str], str | None],
    resolve_conversation_id: Callable[[ConversationStore | NullConversationStore, str], str | None],
    sync_conversation_artifacts: Callable[[TuochatConfig, Conversation], tuple[Path | None, Path | None, list[Path]]],
) -> int:
    """Export a conversation. By default prints the conversation markdown to stdout.

    With --meta, prints archive path and extracted file list instead.
    """
    if no_write_enabled(cfg):
        print(
            "Export is unavailable while no-write mode is enabled because filesystem writes are disabled.",
            file=sys.stderr,
        )
        return 1

    store = build_store(cfg)
    try:
        conv_id = (
            pick_conversation_id(store, "export") if not command.id else resolve_conversation_id(store, command.id)
        )
        if conv_id is None:
            return 1

        conv = store.get_conversation(conv_id)
        if conv is None:
            print(f"Conversation {conv_id} not found.", file=sys.stderr, flush=True)
            return 1
        conv.messages = store.get_messages(conv_id)
        conv_dir, md_path, extracted = sync_conversation_artifacts(cfg, conv)

        if command.meta:
            print(f"Archive dir: {conv_dir}")
            print(f"Markdown: {md_path}")
            if extracted:
                print("Extracted files:")
                for path in extracted:
                    print(f"  {path}")
            else:
                print("Extracted files: (none)")
        else:
            if md_path is not None and md_path.exists():
                sys.stdout.write(md_path.read_text(encoding="utf-8"))
            else:
                print(f"Conversation {conv_id} has no markdown export available.", file=sys.stderr)
                return 1
    finally:
        store.close()

    return 0
