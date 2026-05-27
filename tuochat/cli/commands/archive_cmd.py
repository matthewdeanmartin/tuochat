"""Shared archive-management commands for CLI and REPL dispatch."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from tuochat.persistence.archive import conversation_archive_root
from tuochat.serialization import json_dumps

if TYPE_CHECKING:
    from collections.abc import Callable

    from tuochat.cli.command_models import BagitCheckCommand, BagitUpdateCommand
    from tuochat.config import TuochatConfig
    from tuochat.models import Conversation
    from tuochat.persistence import ConversationStore, NullConversationStore
    from tuochat.persistence.archive import BagitCheckResult


def collect_conversations_by_id(
    cfg: TuochatConfig,
    *,
    build_store: Callable[[TuochatConfig], ConversationStore | NullConversationStore],
    current_conversation: Conversation | None = None,
    current_store: ConversationStore | NullConversationStore | None = None,
) -> dict[str, Conversation]:
    """Return active and archived conversations indexed by id."""
    store = current_store or build_store(cfg)
    try:
        conversations = {
            conversation.id: conversation
            for conversation in [*store.list_conversations(limit=1000), *store.list_archived_conversations(limit=1000)]
        }
    finally:
        if current_store is None:
            store.close()
    if current_conversation is not None:
        conversations[current_conversation.id] = current_conversation
    return conversations


def run_bagit_update(
    cfg: TuochatConfig,
    command: BagitUpdateCommand,
    *,
    build_store: Callable[[TuochatConfig], ConversationStore | NullConversationStore],
    no_write_enabled: Callable[[TuochatConfig], bool],
    load_bagit_module: Callable[[], object | None],
    refresh_archive_bagit_metadata: Callable[..., tuple[int, int]],
    current_conversation: Conversation | None = None,
    current_store: ConversationStore | NullConversationStore | None = None,
) -> int:
    """Refresh BagIt metadata across saved archives."""
    _ = command
    if no_write_enabled(cfg):
        print("BagIt updates are unavailable while no-write mode is enabled.", file=sys.stderr)
        return 1
    bagit_module = load_bagit_module()
    if bagit_module is None:
        print("BagIt support is not installed. Install tuochat[antitamper] or tuochat[all].", file=sys.stderr)
        return 1
    archive_root = conversation_archive_root(cfg)
    if not archive_root.exists():
        print("No conversation archives found.")
        return 0
    conversations = collect_conversations_by_id(
        cfg,
        build_store=build_store,
        current_conversation=current_conversation,
        current_store=current_store,
    )
    personalization = getattr(cfg, "personalization", None)
    user = personalization.name.strip() or None if personalization is not None else None
    updated, skipped = refresh_archive_bagit_metadata(
        cfg,
        conversations,
        user=user,
        bagit_module=bagit_module,
    )
    if updated == 0 and skipped == 0:
        print("No conversation archives found.")
        return 0
    print(f"Updated BagIt metadata for {updated} conversation(s) in {archive_root}.")
    print(
        "BagIt here is only a diagnostic aid: it writes hash and metadata files so you can later check whether "
        "conversation archives changed since the last BagIt update."
    )
    print(
        "The practical purpose is to show when a person edited saved output, including renaming a `.check` file "
        "to an executable extension before use."
    )
    print("It is not intended to protect against malicious attack.")
    if skipped:
        print(f"Skipped {skipped} archive(s) missing a readable conversation ID.", file=sys.stderr)
    return 0


def run_bagit_check(
    cfg: TuochatConfig,
    command: BagitCheckCommand,
    *,
    build_store: Callable[[TuochatConfig], ConversationStore | NullConversationStore],
    load_bagit_module: Callable[[], object | None],
    check_archive_bagit_status: Callable[..., tuple[list[BagitCheckResult], int]],
    current_conversation: Conversation | None = None,
    current_store: ConversationStore | NullConversationStore | None = None,
) -> int:
    """Check saved archives against BagIt manifests."""
    bagit_module = load_bagit_module()
    if bagit_module is None:
        print("BagIt support is not installed. Install tuochat[antitamper] or tuochat[all].", file=sys.stderr)
        return 1
    archive_root = conversation_archive_root(cfg)
    if not archive_root.exists():
        print("No conversation archives found.")
        return 0
    conversations = collect_conversations_by_id(
        cfg,
        build_store=build_store,
        current_conversation=current_conversation,
        current_store=current_store,
    )
    results, skipped = check_archive_bagit_status(cfg, bagit_module=bagit_module)
    valid = [result for result in results if result.status == "valid"]
    changed = [result for result in results if result.status == "changed"]
    missing = [result for result in results if result.status == "missing"]
    if command.format == "json":
        json_results = []
        for result in results:
            conv = conversations.get(result.conversation_id)
            json_results.append(
                {
                    "archive_dir": str(result.archive_dir),
                    "conversation_id": result.conversation_id,
                    "status": result.status,
                    "detail": result.detail,
                    "title": conv.title if conv else None,
                }
            )
        payload = {
            "archive_root": str(archive_root),
            "checked": len(results),
            "skipped": skipped,
            "valid": len(valid),
            "changed": len(changed),
            "missing": len(missing),
            "results": json_results,
        }
        print(json_dumps(payload, indent=True))
        return 0
    if not results and skipped == 0:
        print("No conversation archives found.")
        return 0
    print(f"Checked BagIt status for {len(results)} conversation(s) in {archive_root}.")
    print(
        "BagIt here is only a diagnostic aid: it checks whether conversation archive files changed since the "
        "last time `/update-bagit` wrote hash and metadata files."
    )
    print(
        "The practical purpose is to show when a person edited saved output, including renaming a `.check` file "
        "to an executable extension before use."
    )
    print("It is not intended to protect against malicious attack.")
    print(f"{len(valid)} archive(s) still validate.")
    if missing:
        print(
            f"{len(missing)} archive(s) do not have BagIt files yet. Run `tuochat archive bagit-update` to write the "
            "diagnostic hash and metadata files first."
        )
    if changed:
        print(
            f"{len(changed)} archive(s) no longer validate. This suggests the archive was edited by a human, "
            "including cases where a `.check` file was renamed or otherwise changed, and a human is now "
            "responsible for its content."
        )
        for result in changed:
            conversation = conversations.get(result.conversation_id)
            title = conversation.title.strip() if conversation is not None and conversation.title else ""
            label = f"{result.archive_dir.name} ({result.conversation_id})"
            if title:
                label = f"{result.archive_dir.name} ({title}, {result.conversation_id})"
            detail = f": {result.detail}" if result.detail else ""
            print(f"- {label}{detail}")
    else:
        print("No BagIt changes detected.")
    if skipped:
        print(f"Skipped {skipped} archive(s) missing a readable conversation ID.", file=sys.stderr)
    return 0
