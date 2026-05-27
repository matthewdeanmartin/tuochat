"""Local workspace memory: per-cwd pinned files that are injected into every conversation.

Files live under .tuochat/ in the current working directory:
  .tuochat/memory.md  — persisted memory notes
  .tuochat/todo.md    — task list
  .tuochat/compact.md — conversation summary

Each file is optional. When present its contents are injected into the
system prompt for every new conversation (pinned), giving the LLM persistent
context across sessions without any server-side memory.
"""

from __future__ import annotations

import re
from pathlib import Path

TUOCHAT_DIR = ".tuochat"
MEMORY_FILE = "memory.md"
TODO_FILE = "todo.md"
COMPACT_FILE = "compact.md"

MEMORY_FENCE_LANG = "MEMORY"
COMPACT_FENCE_LANG = "COMPACT"
TODO_FENCE_LANG = "TODO"
NESTED_MARKDOWN_FENCE_GUIDANCE = (
    "If your markdown document needs fenced examples inside it, use tildes (`~~~`) for those inner fences "
    "instead of triple backticks so the outer extractable fence stays parseable.\n\n"
)

MEMORY_PROMPT = (
    "Hey, is there anything from our conversation you'd like me to remember for future sessions? "
    "If so, please write it as a markdown document inside a fenced code block like this:\n\n"
    "```MEMORY\n"
    "Your memory notes here.\n"
    "```\n\n"
    + NESTED_MARKDOWN_FENCE_GUIDANCE
    + "If there is nothing worth remembering, just say so and omit the fence."
)

COMPACT_PROMPT = (
    "Please summarize our conversation so far into a compact briefing that captures the key "
    "context, decisions, open questions, and any important details. "
    "Put the summary inside a fenced code block like this:\n\n"
    "```COMPACT\n"
    "Summary here.\n"
    "```\n\n" + NESTED_MARKDOWN_FENCE_GUIDANCE
)

TODO_PROMPT = (
    "Based on our conversation, what tasks are pending and which have been completed? "
    "Write a concise task list inside a fenced code block like this:\n\n"
    "```TODO\n"
    "- [ ] Pending task\n"
    "- [x] Completed task\n"
    "```\n\n"
    + NESTED_MARKDOWN_FENCE_GUIDANCE
    + "Only include tasks that are meaningful to track. "
    + "If there are none, say so and omit the fence."
)


def workspace_memory_dir(cwd: Path | None = None) -> Path:
    """Return the .tuochat directory for the given cwd (defaults to Path.cwd())."""
    return (cwd or Path.cwd()) / TUOCHAT_DIR


def memory_path(cwd: Path | None = None) -> Path:
    return workspace_memory_dir(cwd) / MEMORY_FILE


def todo_path(cwd: Path | None = None) -> Path:
    return workspace_memory_dir(cwd) / TODO_FILE


def compact_path(cwd: Path | None = None) -> Path:
    return workspace_memory_dir(cwd) / COMPACT_FILE


def read_pinned_file(path: Path) -> str | None:
    """Return file contents if the file exists and is non-empty, else None."""
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return text or None


def write_pinned_file(path: Path, content: str) -> None:
    """Write content to a pinned file, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def delete_pinned_file(path: Path) -> bool:
    """Delete a pinned file. Returns True if it existed and was removed."""
    if path.is_file():
        path.unlink()
        return True
    return False


def extract_fence_content(text: str, lang: str) -> str | None:
    """Extract the body of the first fenced block with the given language tag.

    Accepts both exact-case and case-insensitive matches, e.g. ```MEMORY or ```memory.
    """
    pattern = re.compile(
        r"```" + re.escape(lang) + r"\s*\n(.*?)```",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(text)
    if match:
        return match.group(1).strip()
    return None


def load_pinned_sections(cwd: Path | None = None) -> list[tuple[str, str]]:
    """Return (label, content) pairs for all non-empty pinned workspace files.

    These are injected into the system prompt for every conversation.
    """
    sections: list[tuple[str, str]] = []
    for label, path in [
        ("Workspace compact summary", compact_path(cwd)),
        ("Workspace memory notes", memory_path(cwd)),
        ("Workspace task list", todo_path(cwd)),
    ]:
        content = read_pinned_file(path)
        if content:
            sections.append((label, content))
    return sections
