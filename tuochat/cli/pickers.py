"""Interactive picker helpers for the CLI.

Picker modes (configured via [picker] in config.toml):

  auto      — adapt based on list size and blind_mode (default)
  paged     — always page through items in chunks
  ask_one   — present one item at a time (screen-reader friendly)

In "auto" mode:
  - <= list_threshold items  → dump all at once
  - <= prefilter_threshold   → dump all, but accept name/number input
  - >  prefilter_threshold   → offer a substring prefilter before paging

Blind mode with "auto" upgrades to "paged" automatically.
"""

# ruff: noqa: E402,F401,F403,F811,F821,B010
from __future__ import annotations

import glob
import logging
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TypeVar, cast

from tuochat.cli.blind_prompt_kit.choices import ChoiceInput
from tuochat.cli.blind_prompt_kit.core import InteractionContext
from tuochat.cli.blind_prompt_kit.exceptions import InteractionCancelled
from tuochat.cli.blind_prompt_kit.models import Choice
from tuochat.cli.models import ReplState
from tuochat.cli.rendering import number_label
from tuochat.cli.session import blind_mode_enabled
from tuochat.config import PickerConfig, TuochatConfig
from tuochat.context.attachments import has_glob_chars, select_include_candidate, select_include_candidates
from tuochat.discovery.custom_instructions import describe_custom_instruction_path, list_available_custom_instructions
from tuochat.discovery.shared import (
    bundled_custom_instructions_dir,
    bundled_skills_dir,
    bundled_templates_dir,
    list_text_files,
)
from tuochat.discovery.skills import describe_skill_path, list_available_skills
from tuochat.discovery.templates import describe_template_path, list_available_templates
from tuochat.models import Conversation, ConversationSearchResult

logger = logging.getLogger("tuochat.cli")

T = TypeVar("T")


def conversation_modified_on_disk(conv: Conversation, cfg: object) -> bool:
    """Return True when the on-disk markdown is newer than the DB's updated_at timestamp."""
    try:
        from datetime import datetime, timezone

        from tuochat.persistence.archive import conversation_markdown_path

        md = conversation_markdown_path(cfg, conv, create=False)  # type: ignore[arg-type]
        if not md.exists():
            return False
        db_time = conv.updated_at
        if not db_time:
            return False
        mtime = md.stat().st_mtime
        db_dt = datetime.fromisoformat(db_time.replace("Z", "+00:00"))
        file_dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
        return file_dt > db_dt
    except Exception:
        return False


#
# Test-only export: glob_module is used by test_pickers.py to monkeypatch glob.
glob_module = glob

#
# Prompt I/O indirection (allows tests to inject responses without monkeypatching builtins)


def prompt(msg: str) -> str:
    from tuochat.cli.prompts import prompt_input

    return prompt_input(msg)


#
# Core: resolved picker config from a state-or-config object


def picker_cfg(obj: ReplState | TuochatConfig) -> PickerConfig:
    """Extract PickerConfig from a ReplState or TuochatConfig."""
    cfg = obj.cfg if isinstance(obj, ReplState) else obj
    return cfg.picker


def effective_picker_mode(obj: ReplState | TuochatConfig) -> str:
    """Return the effective picker mode, upgrading 'auto' to 'paged' in blind mode."""
    mode = picker_cfg(obj).mode
    if mode == "auto" and blind_mode_enabled(obj):
        return "paged"
    return mode


#
# pick_from_list — the single entry point for all interactive picking
#
# Parameters
# ----------
# items        : sequence of (label, value) pairs where value is returned on selection
# heading      : printed before the list
# prompt_text  : text shown at the input prompt
# obj          : ReplState or TuochatConfig (for mode + blind_mode)
#
# Returns the selected value, or None if the user cancelled.


def pick_from_list(
    items: Sequence[tuple[str, T]],
    *,
    heading: str,
    prompt_text: str,
    obj: ReplState | TuochatConfig,
) -> T | None:
    if not items:
        return None

    blind = blind_mode_enabled(obj)

    if blind:
        return pick_from_list_blind(items, heading=heading, prompt_text=prompt_text)

    mode = effective_picker_mode(obj)
    pcfg = picker_cfg(obj)

    if mode == "ask_one":
        return pick_ask_one(items, heading=heading, blind=blind)

    if mode == "paged":
        return pick_paged(items, heading=heading, prompt_text=prompt_text, page_size=pcfg.page_size, blind=blind)

    # "auto" — not blind
    n = len(items)
    if n <= pcfg.list_threshold:
        return pick_list_all(items, heading=heading, prompt_text=prompt_text, blind=blind)

    if n <= pcfg.prefilter_threshold:
        return pick_list_all(items, heading=heading, prompt_text=prompt_text, blind=blind)

    # large list: offer prefilter then page
    return pick_prefilter_then_page(
        items, heading=heading, prompt_text=prompt_text, page_size=pcfg.page_size, blind=blind
    )


def pick_from_list_blind(
    items: Sequence[tuple[str, T]],
    *,
    heading: str,
    prompt_text: str,
) -> T | None:
    """Blind-mode picker using blind_prompt_kit.ChoiceInput.

    Small lists (≤9) are shown in full immediately; larger lists announce
    the count and wait for the user to type a name or say 'list'.  Very
    large lists prompt the user to type part of a name to filter first.
    All size-adaptive behaviour is handled by ChoiceInput.announce_start.
    """
    _ = prompt_text
    choices: list[Choice[T]] = [Choice(label=label, value=value) for label, value in items]
    component: ChoiceInput[T] = ChoiceInput(prompt=heading, options=choices)
    context = InteractionContext()
    try:
        return cast("T | None", component.run(context))
    except InteractionCancelled:
        return None


#
# Internal picker strategies


def pick_list_all(
    items: Sequence[tuple[str, T]],
    *,
    heading: str,
    prompt_text: str,
    blind: bool,
) -> T | None:
    """Print everything, accept number or substring."""
    print(heading)
    for idx, (label, _) in enumerate(items, start=1):
        print(f"{number_label(idx, blind_mode=blind)} {label}")
    return resolve_input(items, prompt_text=prompt_text, blind=blind)


def pick_paged(
    items: Sequence[tuple[str, T]],
    *,
    heading: str,
    prompt_text: str,
    page_size: int,
    blind: bool,
) -> T | None:
    """Page through items in chunks of page_size."""
    total = len(items)
    page = 0
    total_pages = (total + page_size - 1) // page_size

    while True:
        start = page * page_size
        end = min(start + page_size, total)
        chunk = items[start:end]

        print(f"{heading} (page {page + 1}/{total_pages}, items {start + 1}–{end} of {total})")
        for idx, (label, _) in enumerate(chunk, start=start + 1):
            print(f"{number_label(idx, blind_mode=blind)} {label}")

        if blind:
            nav_hint = "number, 'n' next, 'p' prev, 'q' cancel"
        else:
            nav_hint = "number, n/p to page, q to cancel"
        raw = prompt(f"{prompt_text} [{nav_hint}]: ").strip().lower()

        if raw in {"q", "quit", "cancel", ""}:
            return None
        if raw == "n":
            if end < total:
                page += 1
            else:
                print("Already on the last page.")
            continue
        if raw == "p":
            if page > 0:
                page -= 1
            else:
                print("Already on the first page.")
            continue

        result = resolve_token(raw, items, blind=blind)
        if result is UNRESOLVED:
            continue
        return result


def pick_prefilter_then_page(
    items: Sequence[tuple[str, T]],
    *,
    heading: str,
    prompt_text: str,
    page_size: int,
    blind: bool,
) -> T | None:
    """Ask for an optional filter string, then page through matches."""
    total = len(items)
    print(f"{heading} ({total} items)")
    raw_filter = prompt("Filter (type part of a name, or Enter to list all): ").strip()

    filtered: Sequence[tuple[str, T]]
    if raw_filter:
        filtered = [(label, val) for label, val in items if raw_filter.lower() in label.lower()]
        if not filtered:
            print(f"No matches for {raw_filter!r}. Showing all.")
            filtered = items
    else:
        filtered = items

    return pick_paged(filtered, heading=heading, prompt_text=prompt_text, page_size=page_size, blind=blind)


ASK_ONE_HELP = (
    "Commands: Enter or 'y' to select, 'n' next, 'p' prev, "
    "'[text]' to filter (use square brackets), 'q' to cancel"
)


def pick_ask_one(
    items: Sequence[tuple[str, T]],
    *,
    heading: str,
    blind: bool,
) -> T | None:
    """Present one item at a time; bracket syntax for filter."""
    active = list(items)
    idx = 0
    filter_active: str | None = None

    print(heading)
    if blind:
        print(ASK_ONE_HELP)

    while True:
        if not active:
            print("No items match the current filter.")
            return None

        total = len(active)
        label, value = active[idx]
        position = f"Item {idx + 1} of {total}"
        if filter_active:
            position += f" (filter: {filter_active!r})"
        print(f"{position}: {label}")

        raw = prompt("[y/n/p/[filter]/q]: ").strip()

        # empty Enter = select
        if raw in {"", "y", "yes"}:
            return value

        if raw in {"n", "next"}:
            idx = (idx + 1) % total
            continue

        if raw in {"p", "prev", "previous"}:
            idx = (idx - 1) % total
            continue

        if raw in {"q", "quit", "cancel"}:
            return None

        # bracket filter: [text]
        if raw.startswith("[") and raw.endswith("]") and len(raw) >= 2:
            term = raw[1:-1].strip()
            if not term:
                # clear filter
                active = list(items)
                filter_active = None
                idx = 0
                print("Filter cleared.")
            else:
                matched = [(lbl, val) for lbl, val in items if term.lower() in lbl.lower()]
                if not matched:
                    print(f"No items match {term!r}.")
                else:
                    active = matched
                    filter_active = term
                    idx = 0
                    print(f"{len(matched)} item(s) match {term!r}.")
            continue

        print("Type Enter to select, 'n' next, 'p' prev, '[filter]' to narrow, 'q' to cancel.")


#
# Input resolution helpers


UNRESOLVED = object()  # sentinel


def resolve_token(raw: str, items: Sequence[tuple[str, T]], *, blind: bool) -> T | Any:
    """Resolve a raw input token against a list.  Returns UNRESOLVED on failure."""
    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(items):
            return items[idx][1]
        print(f"Selection out of range (1–{len(items)}).", file=sys.stderr)
        return UNRESOLVED

    matches = [(label, val) for label, val in items if raw.lower() in label.lower()]
    if len(matches) == 1:
        return matches[0][1]
    if len(matches) > 1:
        print(f"Ambiguous: {len(matches)} items match {raw!r}. Pick a number:")
        match_labels = {label for label, _val in matches}
        for idx, (label, _val) in enumerate(items, start=1):
            if label in match_labels:
                print(f"  {number_label(idx, blind_mode=blind)} {label}")
        return UNRESOLVED
    print(f"No match for {raw!r}.", file=sys.stderr)
    return UNRESOLVED


def resolve_input(
    items: Sequence[tuple[str, T]],
    *,
    prompt_text: str,
    blind: bool,
) -> T | None:
    """Prompt until the user picks a valid item or cancels."""
    while True:
        raw = prompt(f"{prompt_text}: ").strip()
        if not raw:
            return None
        result = resolve_token(raw, items, blind=blind)
        if result is not UNRESOLVED:
            return result


#
# High-level print-and-pick helpers (used by repl.py and commands)


def print_picker(candidates: list[Path], root: Path, label: str, command_name: str) -> None:
    """Print a numbered picker list (no interactive selection)."""
    if not candidates:
        print(f"No {label} files found in {root}.")
        return
    print(f"Pick a {label} file with {command_name} N:")
    for idx, path in enumerate(candidates, start=1):
        print(f"[{idx}] {path.relative_to(root)}")


def pick_skill(candidates: list[Path], cfg: TuochatConfig) -> Path | None:
    """Interactively pick a skill from candidates; returns selected Path or None."""
    if not candidates:
        print("No skill files found.")
        return None
    items = [(describe_skill_path(p, cfg), p) for p in candidates]
    return pick_from_list(
        items,
        heading="Pick a skill:",
        prompt_text="skill",
        obj=cfg,
    )


def pick_template(candidates: list[Path], cfg: TuochatConfig) -> Path | None:
    """Interactively pick a template from candidates; returns selected Path or None."""
    if not candidates:
        print("No template files found.")
        return None
    items = [(describe_template_path(p, cfg), p) for p in candidates]
    return pick_from_list(
        items,
        heading="Pick a template:",
        prompt_text="template",
        obj=cfg,
    )


def pick_custom_instruction(candidates: list[Path], cfg: TuochatConfig) -> Path | None:
    """Interactively pick a custom instruction file; returns selected Path or None."""
    if not candidates:
        print("No custom instruction files found.")
        return None
    items = [(describe_custom_instruction_path(p, cfg), p) for p in candidates]
    return pick_from_list(
        items,
        heading="Pick a custom instruction:",
        prompt_text="custom instruction",
        obj=cfg,
    )


def pick_resume_candidate(state: ReplState, *, limit: int = 20):
    """Interactively pick a conversation to resume; returns Conversation or None."""
    candidates = state.store.list_conversations(limit=limit)
    state.resume_candidates = candidates
    if not candidates:
        print("No saved conversations found.")
        return None

    cfg = getattr(state, "cfg", None)

    def fmt(conv):
        title = (conv.title or "Untitled")[:50]
        updated = conv.updated_at[:19] if conv.updated_at else ""
        modified = " [disk-modified]" if cfg is not None and conversation_modified_on_disk(conv, cfg) else ""
        return f"{conv.id[:8]}  {title}  {updated}{modified}"

    items = [(fmt(c), c) for c in candidates]
    return pick_from_list(items, heading="Pick a conversation to resume:", prompt_text="resume", obj=state)


def pick_archived_candidate(state: ReplState, *, limit: int = 20):
    """Interactively pick an archived conversation; returns Conversation or None."""
    candidates = state.store.list_archived_conversations(limit=limit)
    state.resume_candidates = candidates
    if not candidates:
        print("No archived conversations found.")
        return None

    def fmt(conv):
        title = (conv.title or "Untitled")[:50]
        updated = conv.updated_at[:19] if conv.updated_at else ""
        return f"{conv.id[:8]}  {title}  {updated}"

    items = [(fmt(c), c) for c in candidates]
    return pick_from_list(items, heading="Pick an archived conversation:", prompt_text="unarchive", obj=state)


#
# Legacy print-only helpers (kept for backward compat; callers that only need
# the display half can still use these; new callers should use pick_*)


def print_skill_picker(candidates: list[Path], cfg: TuochatConfig) -> None:
    """Print a numbered picker list for skills (display only, no prompt)."""
    if not candidates:
        print("No skill files found.")
        return
    blind = blind_mode_enabled(cfg)
    print("Pick a skill file with /skill N:")
    for idx, path in enumerate(candidates, start=1):
        print(f"{number_label(idx, blind_mode=blind)} {describe_skill_path(path, cfg)}")


def print_template_picker(candidates: list[Path], cfg: TuochatConfig) -> None:
    """Print a numbered picker list for templates (display only, no prompt)."""
    if not candidates:
        print("No template files found.")
        return
    blind = blind_mode_enabled(cfg)
    print("Pick a template file with /template N:")
    for idx, path in enumerate(candidates, start=1):
        print(f"{number_label(idx, blind_mode=blind)} {describe_template_path(path, cfg)}")


def print_custom_instruction_picker(candidates: list[Path], cfg: TuochatConfig) -> None:
    """Print a numbered picker list for custom instructions (display only, no prompt)."""
    if not candidates:
        print("No custom instruction files found.")
        return
    blind = blind_mode_enabled(cfg)
    print("Pick a custom instruction file with /custom N:")
    for idx, path in enumerate(candidates, start=1):
        print(f"{number_label(idx, blind_mode=blind)} {describe_custom_instruction_path(path, cfg)}")


def print_resume_candidates(state: ReplState, *, limit: int = 20) -> None:
    """Print recent conversations for /resume selection (display only, no prompt)."""
    candidates = state.store.list_conversations(limit=limit)
    state.resume_candidates = candidates
    if not candidates:
        print("No saved conversations found.")
        return
    blind = blind_mode_enabled(state)
    cfg = getattr(state, "cfg", None)
    print("Pick a conversation with /resume N:")
    for idx, conv in enumerate(candidates, start=1):
        title = (conv.title or "Untitled")[:50]
        updated = conv.updated_at[:19] if conv.updated_at else ""
        modified = " [disk-modified]" if cfg is not None and conversation_modified_on_disk(conv, cfg) else ""
        print(f"{number_label(idx, blind_mode=blind)} {conv.id[:8]}  {title}  {updated}{modified}")


def print_archived_candidates(state: ReplState, *, limit: int = 20) -> None:
    """Print archived conversations for /unarchive selection (display only, no prompt)."""
    candidates = state.store.list_archived_conversations(limit=limit)
    state.resume_candidates = candidates
    if not candidates:
        print("No archived conversations found.")
        return
    blind = blind_mode_enabled(state)
    print("Pick an archived conversation with /unarchive N:")
    for idx, conv in enumerate(candidates, start=1):
        title = (conv.title or "Untitled")[:50]
        updated = conv.updated_at[:19] if conv.updated_at else ""
        print(f"{number_label(idx, blind_mode=blind)} {conv.id[:8]}  {title}  {updated}")


#
# Conversation search


def run_conversation_search(
    store,
    query: str,
    *,
    limit: int = 20,
    title_filter: str | None = None,
    updated_after: str | None = None,
    updated_before: str | None = None,
) -> list[ConversationSearchResult]:
    """Execute a conversation search with the store defaults centralized."""
    return store.search_conversations(
        query,
        limit=limit,
        title_filter=title_filter,
        updated_after=updated_after,
        updated_before=updated_before,
    )


def print_search_candidates(state: ReplState, query: str, *, limit: int = 20) -> None:
    """Print search matches for /search selection (display only, no prompt)."""
    candidates = run_conversation_search(state.store, query, limit=limit)
    state.search_candidates = candidates
    if not candidates:
        print(f"No saved conversations matched {query!r}.")
        return
    blind = blind_mode_enabled(state)
    print(f"Search results for {query!r}:")
    for idx, match in enumerate(candidates, start=1):
        title = (match.title or "Untitled")[:40]
        updated = match.updated_at[:19] if match.updated_at else ""
        role = match.role[:9]
        snippet = re.sub(r"\s+", " ", (match.snippet or "").strip())
        print(f"{number_label(idx, blind_mode=blind)} {match.conversation_id[:8]}  {title}  {updated}  {role}")
        print(f"     {snippet}")


#
# Path resolution helpers (unchanged)


def resolve_picker_path(argument: str, *, root: Path, candidates: list[Path] | None) -> Path | None:
    """Resolve a picker argument as either an index or a file path."""
    if argument.isdigit():
        current = candidates or list_text_files(root)
        index = int(argument) - 1
        if index < 0 or index >= len(current):
            print("Selection out of range.", file=sys.stderr)
            return None
        return current[index]

    path = Path(argument.replace("\\", "/")).expanduser()
    if not path.is_absolute():
        path = root / path
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        print(f"Path is outside the working directory: {path}", file=sys.stderr)
        return None
    return path


def resolve_skill_path(argument: str, *, cfg, candidates: list[Path] | None) -> Path | None:
    """Resolve a skill selection as an index, workspace path, or discovered skill name."""
    path = resolve_picker_path(argument, root=Path.cwd(), candidates=candidates)
    if path is not None and path.is_file():
        return path

    current = candidates or list_available_skills(cfg)
    normalized = argument.strip().replace("\\", "/").rstrip("/")
    for candidate in current:
        aliases = {
            candidate.parent.name,
            candidate.name,
            describe_skill_path(candidate, cfg),
        }
        try:
            aliases.add(candidate.relative_to(cfg.skills_dir).as_posix())
            aliases.add(candidate.relative_to(cfg.skills_dir).parent.as_posix())
        except ValueError:
            pass
        try:
            aliases.add(candidate.relative_to(bundled_skills_dir()).as_posix())
            aliases.add(candidate.relative_to(bundled_skills_dir()).parent.as_posix())
        except ValueError:
            pass
        try:
            aliases.add(candidate.relative_to(Path.cwd()).as_posix())
            aliases.add(candidate.relative_to(Path.cwd()).parent.as_posix())
        except ValueError:
            pass
        if normalized in aliases:
            return candidate
    return None


def resolve_custom_instruction_path(argument: str, *, cfg, candidates: list[Path] | None) -> Path | None:
    """Resolve a custom-instruction selection as an index, workspace path, or discovered file name."""
    path = resolve_picker_path(argument, root=Path.cwd(), candidates=candidates)
    if path is not None and path.is_file():
        return path

    current = candidates or list_available_custom_instructions(cfg)
    normalized = argument.strip().replace("\\", "/").rstrip("/")
    for candidate in current:
        aliases = {
            candidate.name,
            describe_custom_instruction_path(candidate, cfg),
        }
        try:
            aliases.add(candidate.relative_to(cfg.custom_instructions_dir).as_posix())
        except ValueError:
            pass
        try:
            aliases.add(candidate.relative_to(bundled_custom_instructions_dir()).as_posix())
        except ValueError:
            pass
        try:
            aliases.add(candidate.relative_to(Path.cwd()).as_posix())
        except ValueError:
            pass
        if normalized in aliases:
            return candidate
    return None


def resolve_template_path(argument: str, *, cfg, candidates: list[Path] | None) -> Path | None:
    """Resolve a template selection as an index, workspace path, or discovered template name."""
    path = resolve_picker_path(argument, root=Path.cwd(), candidates=candidates)
    if path is not None and path.is_file():
        return path

    current = candidates or list_available_templates(cfg)
    normalized = argument.strip().replace("\\", "/").rstrip("/")
    for candidate in current:
        aliases = {
            candidate.parent.name,
            candidate.name,
            describe_template_path(candidate, cfg),
        }
        try:
            aliases.add(candidate.relative_to(cfg.templates_dir).as_posix())
            aliases.add(candidate.relative_to(cfg.templates_dir).parent.as_posix())
        except ValueError:
            pass
        try:
            aliases.add(candidate.relative_to(bundled_templates_dir()).as_posix())
            aliases.add(candidate.relative_to(bundled_templates_dir()).parent.as_posix())
        except ValueError:
            pass
        try:
            aliases.add(candidate.relative_to(Path.cwd()).as_posix())
            aliases.add(candidate.relative_to(Path.cwd()).parent.as_posix())
        except ValueError:
            pass
        if normalized in aliases:
            return candidate
    return None


__all__ = [
    "pick_from_list",
    "pick_skill",
    "pick_template",
    "pick_custom_instruction",
    "pick_resume_candidate",
    "pick_archived_candidate",
    "picker_cfg",
    "effective_picker_mode",
    # legacy display-only helpers
    "print_picker",
    "print_skill_picker",
    "print_template_picker",
    "print_custom_instruction_picker",
    "print_resume_candidates",
    "print_archived_candidates",
    "run_conversation_search",
    "print_search_candidates",
    "resolve_picker_path",
    "resolve_skill_path",
    "resolve_custom_instruction_path",
    "resolve_template_path",
    "select_include_candidate",
    "has_glob_chars",
    "select_include_candidates",
]
