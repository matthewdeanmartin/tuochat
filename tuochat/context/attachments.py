"""File attachment handling — maps, code-maps, include candidates, queue management."""

from __future__ import annotations

import fnmatch
import glob as glob_module
import hashlib
import logging
import re
import sys
from pathlib import Path
from typing import Protocol

from tuochat.constants import DEFAULT_MAP_GLOBS
from tuochat.context.ignore_rules import build_context_ignore_matcher

logger = logging.getLogger(__name__)

DEFAULT_IGNORED_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache", ".uv-cache"}


class AttachmentState(Protocol):
    """Protocol for the state object used in attachment operations."""

    last_candidates: list[Path] | None
    last_include_path: Path | None
    last_include_hash: str | None
    last_include_size: int | None
    last_include_message: str | None
    pending_attachment_messages: list[str]
    pending_attachment_names: list[str]


#
# Binary / text detection
#


def is_probably_binary(raw: bytes) -> bool:
    """Heuristically detect binary content without relying on file extensions."""
    if not raw:
        return False
    if b"\x00" in raw:
        return True
    sample = raw[:1024]
    suspicious = sum(1 for byte in sample if byte < 9 or (13 < byte < 32) or byte == 127)
    return suspicious / max(1, len(sample)) > 0.30


def read_safe_text_file(path: Path) -> tuple[str, str, int] | None:
    """Read UTF-8 text and skip binary or undecodable content."""
    raw = path.read_bytes()
    if is_probably_binary(raw):
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return text, hashlib.sha256(raw).hexdigest(), len(raw)


def read_include_file(path: Path) -> tuple[str, str, int]:
    """Read an include file as UTF-8 text and return content metadata.

    Raises ValueError for binary files, UnicodeDecodeError for non-UTF-8 text.
    """
    raw = path.read_bytes()
    if is_probably_binary(raw):
        raise ValueError(f"Binary files are not supported yet: {path}")
    text = raw.decode("utf-8")
    return text, hashlib.sha256(raw).hexdigest(), len(raw)


def is_context_ignored_path(path: Path, *, ignore_root: Path) -> bool:
    """Return True when supported ignore files exclude this path from context."""
    matcher = build_context_ignore_matcher(ignore_root)
    return matcher.is_ignored(path)


#
# Directory map
#


def split_map_globs(glob_pattern: str | None) -> list[str]:
    """Split a pipe-delimited glob expression into normalized patterns."""
    if not glob_pattern:
        return list(DEFAULT_MAP_GLOBS)
    parts = [part.strip() for part in glob_pattern.split("|")]
    return [part for part in parts if part] or list(DEFAULT_MAP_GLOBS)


def map_candidates(root: Path, glob_pattern: str | None, limit: int) -> list[Path]:
    """Return a recursive file map rooted at the current working directory."""
    matcher = build_context_ignore_matcher(root)
    matches: list[Path] = []
    patterns = split_map_globs(glob_pattern)
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in DEFAULT_IGNORED_DIRS for part in path.parts):
            continue
        if matcher.is_ignored(path):
            continue
        rel = path.relative_to(root).as_posix()
        if any(fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(path.name, pattern) for pattern in patterns):
            matches.append(path)
    return matches[:limit]


def render_map_attachment(root: Path, matches: list[Path], *, glob_pattern: str | None, limit: int) -> str:
    """Render a directory map payload for attachment."""
    lines = [
        f"Directory map for: {root}",
        f"Glob: {glob_pattern or ', '.join(DEFAULT_MAP_GLOBS)}",
        f"Limit: {limit}",
        f"Matched files: {len(matches)}",
        "",
    ]
    for path in matches:
        rel = path.relative_to(root).as_posix()
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        lines.append(f"- {rel} ({size} bytes)")
    return "\n".join(lines)


#
# Code map
#


def code_fence_language(path: Path) -> str:
    """Choose a markdown code fence language from a file suffix."""
    suffix = path.suffix.lower()
    if suffix == ".py":
        return "python"
    if suffix in {".yml", ".yaml"}:
        return "yaml"
    if suffix == ".ps1":
        return "powershell"
    if suffix == ".js":
        return "javascript"
    if suffix == ".ts":
        return "typescript"
    if suffix == ".md":
        return "markdown"
    return suffix.lstrip(".") or "text"


def render_tree_lines(root: Path, matches: list[Path]) -> list[str]:
    """Render file paths with directory indentation similar to a recursive listing."""
    lines: list[str] = []
    seen_dirs: set[str] = set()
    for path in matches:
        parts = path.relative_to(root).parts
        dir_parts = parts[:-1]
    for depth, part in enumerate(dir_parts):
        current = "/".join(dir_parts[: depth + 1])
        if current in seen_dirs:
            continue
        seen_dirs.add(current)
        lines.append(f"{'  ' * depth}{part}/")
        lines.append(f"{'  ' * len(dir_parts)}{parts[-1]}")
    return lines


def render_code_map_attachment(root: Path, matches: list[Path], *, glob_pattern: str | None, limit: int) -> str:
    """Render a single attachment containing a file tree plus fenced file contents."""
    lines = [
        f"Code map for: {root}",
        f"Glob: {glob_pattern or '|'.join(DEFAULT_MAP_GLOBS)}",
        f"Limit: {limit}",
        f"Matched files: {len(matches)}",
        "",
        "Tree:",
    ]
    tree_lines = render_tree_lines(root, matches)
    lines.extend(tree_lines or ["(no matching text files)"])
    for path in matches:
        rel = path.relative_to(root).as_posix()
        safe_text = read_safe_text_file(path)
        if safe_text is None:
            continue
        text, _, _ = safe_text
        lines.extend(
            [
                "",
                f"Path: {rel}",
                f"```{code_fence_language(path)}",
                text,
                "```",
            ]
        )
    return "\n".join(lines)


def code_map_candidates(root: Path, glob_pattern: str | None, limit: int) -> list[Path]:
    """Return matching non-binary text files that are not excluded by ignore rules."""
    candidates = map_candidates(root, glob_pattern, max(limit * 3, limit))
    matches: list[Path] = []
    for path in candidates:
        try:
            safe_text = read_safe_text_file(path)
        except OSError:
            continue
        if safe_text is None:
            continue
        matches.append(path)
        if len(matches) >= limit:
            break
    return matches


#
# Include candidates
#


def list_include_candidates() -> list[Path]:
    """Return likely include-able files from the current working directory."""
    return list_include_candidates_under(Path.cwd(), limit=25)


def list_include_candidates_under(
    root: Path, *, limit: int | None = None, ignore_root: Path | None = None
) -> list[Path]:
    """Return likely include-able files rooted under the supplied directory."""
    allowed_suffixes = {
        ".md",
        ".txt",
        ".py",
        ".toml",
        ".json",
        ".yaml",
        ".yml",
        ".ini",
        ".cfg",
        ".sh",
        ".ps1",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".css",
        ".html",
        ".sql",
    }
    effective_ignore_root = (ignore_root or root).resolve()
    matcher = build_context_ignore_matcher(effective_ignore_root)
    candidates: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in DEFAULT_IGNORED_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in allowed_suffixes:
            continue
        if matcher.is_ignored(path):
            continue
        candidates.append(path)
        if limit is not None and len(candidates) >= limit:
            break
    return candidates


def has_glob_chars(text: str) -> bool:
    """Return True if text contains glob wildcard characters."""
    return any(c in text for c in ("*", "?", "["))


def select_include_candidate(argument: str, state: AttachmentState) -> Path | None:
    """Resolve an include argument as either a list index or a plain file path.

    Returns a single Path for numeric selections or plain paths.
    For glob patterns use select_include_candidates (plural).
    """
    if argument.isdigit():
        candidates = state.last_candidates or list_include_candidates()
        state.last_candidates = candidates
        index = int(argument) - 1
        if index < 0 or index >= len(candidates):
            print("Selection out of range.", file=sys.stderr)
            return None
        return candidates[index]

    path = Path(argument).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        path.resolve().relative_to(Path.cwd().resolve())
    except ValueError:
        print(f"Path is outside the working directory: {path}", file=sys.stderr)
        return None
    return path


def select_include_candidates(argument: str, state: AttachmentState) -> list[Path] | None:
    """Resolve an include argument to one or more Paths.

    Handles:
    - Numeric index (e.g. "3")
    - Plain file path (e.g. "README.md")
    - Glob pattern with optional limit (e.g. "tuochat/**/*.py" or "tuochat/**/*.py 25")

    Returns a list of Paths, or None on error.
    """
    parts = argument.rsplit(None, 1)
    glob_pattern = argument
    limit: int | None = None
    if len(parts) == 2 and parts[1].isdigit():
        glob_pattern = parts[0]
        limit = int(parts[1])
        logger.debug("/include: parsed glob=%r limit=%d", glob_pattern, limit)

    # Numeric index into the most-recently listed candidates
    if glob_pattern.isdigit():
        candidates = state.last_candidates or list_include_candidates()
        state.last_candidates = candidates
        index = int(glob_pattern) - 1
        if index < 0 or index >= len(candidates):
            print("Selection out of range.", file=sys.stderr)
            return None
        selected_path = candidates[index]
        if is_context_ignored_path(selected_path, ignore_root=Path.cwd()):
            print(f"Include file is excluded by ignore rules: {selected_path}", file=sys.stderr)
            return None
        logger.debug("/include: index selection -> %s", selected_path)
        return [selected_path]

    if has_glob_chars(glob_pattern):
        logger.debug("/include: expanding glob %r from cwd %s", glob_pattern, Path.cwd())
        root = Path.cwd()
        raw_matches = glob_module.glob(glob_pattern, recursive=True)
        if not raw_matches:
            raw_matches = glob_module.glob(str(root / glob_pattern), recursive=True)
        logger.debug("/include: glob raw matches (%d): %s", len(raw_matches), raw_matches[:10])
        matches: list[Path] = []
        matcher = build_context_ignore_matcher(root)
        for m in sorted(raw_matches):
            p = Path(m)
            if not p.is_file():
                continue
            if any(part in DEFAULT_IGNORED_DIRS for part in p.parts):
                continue
            try:
                p.resolve().relative_to(root.resolve())
            except ValueError:
                logger.debug("/include: skipping out-of-cwd match %s", p)
                continue
            if matcher.is_ignored(p):
                logger.debug("/include: skipping ignored match %s", p)
                continue
            matches.append(p)
        if limit is not None:
            matches = matches[:limit]
        if not matches:
            print(f"No files matched: {glob_pattern}", file=sys.stderr)
            logger.debug("/include: no files matched glob %r", glob_pattern)
            return None
        logger.debug("/include: %d file(s) matched glob %r", len(matches), glob_pattern)
        return matches

    # Plain path
    path = Path(glob_pattern).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        path.resolve().relative_to(Path.cwd().resolve())
    except ValueError:
        print(f"Path is outside the working directory: {path}", file=sys.stderr)
        return None
    if is_context_ignored_path(path, ignore_root=Path.cwd()):
        print(f"Include file is excluded by ignore rules: {path}", file=sys.stderr)
        return None
    logger.debug("/include: plain path -> %s", path)
    return [path]


#
# Include file preparation
#


def format_included_file(path: Path, text: str) -> str:
    """Return a message fragment for a selected include file."""
    return f"Included file: {path}\n```text\n{text}\n```"


def prepare_include(path: Path, state: AttachmentState) -> str | None:
    """Prepare an include payload and update session tracking."""
    logger.debug("prepare_include: path=%s", path)
    if not path.is_file():
        print(f"Include file not found: {path}", file=sys.stderr)
        logger.debug("prepare_include: not a file: %s", path)
        return None
    if is_context_ignored_path(path, ignore_root=Path.cwd()):
        print(f"Include file is excluded by ignore rules: {path}", file=sys.stderr)
        logger.debug("prepare_include: ignored by context rules: %s", path)
        return None
    try:
        text, fingerprint, size = read_include_file(path)
    except UnicodeDecodeError:
        print(f"Include file is not valid UTF-8 text: {path}", file=sys.stderr)
        logger.debug("prepare_include: unicode error for %s", path)
        return None
    except ValueError as e:
        print(str(e), file=sys.stderr)
        logger.debug("prepare_include: read error for %s: %s", path, e)
        return None

    message = format_included_file(path, text)
    logger.debug("prepare_include: prepared %s (%d bytes, fingerprint=%s)", path, size, fingerprint)
    state.last_include_path = path
    state.last_include_hash = fingerprint
    state.last_include_size = size
    state.last_include_message = message
    return message


#
# Attachment queue
#


def queue_attachment(state: AttachmentState, path: Path, message: str) -> None:
    """Queue an attachment for the next real user request only."""
    if state.pending_attachment_messages is None:
        state.pending_attachment_messages = []
    if state.pending_attachment_names is None:
        state.pending_attachment_names = []
    state.pending_attachment_messages.append(message)
    state.pending_attachment_names.append(str(path))


def clear_pending_attachments(state: AttachmentState) -> None:
    """Clear queued attachments after a successful send."""
    state.pending_attachment_messages = []
    state.pending_attachment_names = []


def consume_pending_attachments(state: AttachmentState, sent_count: int) -> None:
    """Drop the attachments already sent while preserving anything queued later."""
    if sent_count <= 0:
        return
    state.pending_attachment_messages = list(state.pending_attachment_messages or [])[sent_count:]
    state.pending_attachment_names = list(state.pending_attachment_names or [])[sent_count:]


def detach_pending_attachment(state: AttachmentState, argument: str) -> bool:
    """Detach one or all queued attachments by index or path."""
    names = state.pending_attachment_names or []
    messages = state.pending_attachment_messages or []
    if not names or not messages:
        print("No pending attachments to detach.")
        return False

    target = argument.strip()
    if target.lower() == "all":
        removed = len(names)
        clear_pending_attachments(state)
        print(f"Detached {removed} pending attachment(s).")
        return True

    index: int | None = None
    if target.isdigit():
        selected = int(target) - 1
        if 0 <= selected < len(names):
            index = selected
    else:
        normalized = target.replace("\\", "/")
        cwd = Path.cwd()
        for idx, name in enumerate(names):
            full = str(Path(name))
            rel = full
            try:
                rel = Path(full).relative_to(cwd).as_posix()
            except ValueError:
                rel = Path(full).as_posix()
            candidates = {full, Path(full).as_posix(), rel, Path(full).name}
            if normalized in candidates:
                index = idx
                break

    if index is None:
        print(f"Pending attachment not found: {argument}", file=sys.stderr)
        return False

    removed_name = names.pop(index)
    messages.pop(index)
    state.pending_attachment_names = names
    state.pending_attachment_messages = messages
    print(f"Detached pending attachment: {removed_name}")
    return True


#
# Attachment stub naming
#


def attachment_stub_name(prefix: str, glob_pattern: str | None, suffix: str) -> Path:
    """Return a printable synthetic attachment path with a sanitized label."""
    label = glob_pattern or "default"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip("-") or "default"
    return Path.cwd() / f"{prefix}-{safe}{suffix}"
