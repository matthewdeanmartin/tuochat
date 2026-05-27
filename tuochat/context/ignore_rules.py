"""Shared ignore-file support for context discovery and attachment flows."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from functools import cache
from pathlib import Path, PurePosixPath

SUPPORTED_CONTEXT_IGNORE_FILES = (
    ".gitignore",
    ".agentignore",
    ".claudeignore",
    ".copilotignore",
)

IGNORE_FILE_PRIORITY = {name: index for index, name in enumerate(SUPPORTED_CONTEXT_IGNORE_FILES)}
DEFAULT_CONTEXT_IGNORE_PRUNE_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".uv-cache",
}


@dataclass(frozen=True)
class IgnoreRule:
    """One gitignore-style rule sourced from a supported ignore file."""

    source_path: Path
    base_directory: PurePosixPath
    pattern: str
    negated: bool
    directory_only: bool
    basename_only: bool

    @property
    def pattern_segments(self) -> tuple[str, ...]:
        return tuple(segment for segment in self.pattern.split("/") if segment)


class ContextIgnoreMatcher:
    """Evaluate gitignore-style rules for files under a workspace root."""

    def __init__(self, root: Path, rules: list[IgnoreRule]) -> None:
        self.root = root.resolve()
        self.rules = rules

    def is_ignored(self, path: Path) -> bool:
        """Return True when the path is excluded from context by ignore files."""
        try:
            rel = path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return False
        if not rel:
            return False

        ignored = False
        rel_parts = tuple(part for part in rel.split("/") if part)
        for rule in self.rules:
            if rule_matches_path(rule, rel_parts):
                ignored = not rule.negated
        return ignored


def build_context_ignore_matcher(root: Path) -> ContextIgnoreMatcher:
    """Load supported ignore files under root and return a matcher."""
    resolved_root = root.resolve()
    rules: list[IgnoreRule] = []
    for ignore_path in discover_ignore_files(resolved_root):
        rules.extend(parse_ignore_file(ignore_path, resolved_root))
    return ContextIgnoreMatcher(resolved_root, rules)


def discover_ignore_files(root: Path) -> list[Path]:
    """Return supported ignore files in precedence order."""
    files: list[Path] = []
    pending = [root]
    while pending:
        current = pending.pop()
        for name in SUPPORTED_CONTEXT_IGNORE_FILES:
            candidate = current / name
            if candidate.is_file():
                files.append(candidate)
        try:
            children = sorted(current.iterdir(), key=lambda child: child.name, reverse=True)
        except OSError:
            continue
        for child in children:
            if not child.is_dir():
                continue
            if child.name in DEFAULT_CONTEXT_IGNORE_PRUNE_DIRS:
                continue
            pending.append(child)
    unique: dict[Path, Path] = {}
    for path in files:
        unique[path.resolve()] = path
    return sorted(
        unique.values(),
        key=lambda path: (
            len(path.resolve().relative_to(root).parts),
            path.resolve().relative_to(root).parent.as_posix(),
            IGNORE_FILE_PRIORITY.get(path.name, len(IGNORE_FILE_PRIORITY)),
        ),
    )


def parse_ignore_file(path: Path, root: Path) -> list[IgnoreRule]:
    """Parse a supported ignore file into ordered gitignore-style rules."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []

    base_directory = PurePosixPath(path.resolve().parent.relative_to(root).as_posix())
    rules: list[IgnoreRule] = []
    for line in lines:
        parsed = parse_ignore_line(line)
        if parsed is None:
            continue
        pattern, negated, directory_only = parsed
        rules.append(
            IgnoreRule(
                source_path=path,
                base_directory=base_directory,
                pattern=pattern,
                negated=negated,
                directory_only=directory_only,
                basename_only="/" not in pattern,
            )
        )
    return rules


def parse_ignore_line(line: str) -> tuple[str, bool, bool] | None:
    """Parse one gitignore-style line."""
    raw = line.rstrip()
    if not raw:
        return None
    if raw.startswith("\\#"):
        raw = raw[1:]
    elif raw.startswith("#"):
        return None

    negated = False
    if raw.startswith("\\!"):
        raw = raw[1:]
    elif raw.startswith("!"):
        negated = True
        raw = raw[1:]

    if raw.startswith("/"):
        raw = raw[1:]

    directory_only = raw.endswith("/")
    if directory_only:
        raw = raw[:-1]

    pattern = raw.replace("\\ ", " ").replace("\\#", "#").replace("\\!", "!")
    if not pattern:
        return None
    return pattern, negated, directory_only


def rule_matches_path(rule: IgnoreRule, rel_parts: tuple[str, ...]) -> bool:
    """Return True when a parsed rule applies to a path relative to the workspace root."""
    base_parts = tuple(part for part in rule.base_directory.parts if part not in {"", "."})
    if len(rel_parts) < len(base_parts) or rel_parts[: len(base_parts)] != base_parts:
        return False
    candidate_parts = rel_parts[len(base_parts) :]
    if not candidate_parts:
        return False

    if rule.basename_only:
        return any(fnmatch.fnmatchcase(part, rule.pattern) for part in candidate_parts)

    pattern_segments = rule.pattern_segments
    if rule.directory_only:
        return any(
            path_matches_pattern(tuple(candidate_parts[:end]), pattern_segments)
            for end in range(1, len(candidate_parts) + 1)
        )
    return path_matches_pattern(candidate_parts, pattern_segments)


@cache
def path_matches_pattern(path_parts: tuple[str, ...], pattern_parts: tuple[str, ...]) -> bool:
    """Match slash-separated gitignore path segments with support for **."""

    @cache
    def matches(pattern_index: int, path_index: int) -> bool:
        if pattern_index == len(pattern_parts):
            return path_index == len(path_parts)
        if path_index > len(path_parts):
            return False

        token = pattern_parts[pattern_index]
        if token == "**":
            return matches(pattern_index + 1, path_index) or (
                path_index < len(path_parts) and matches(pattern_index, path_index + 1)
            )
        if path_index >= len(path_parts):
            return False
        if not fnmatch.fnmatchcase(path_parts[path_index], token):
            return False
        return matches(pattern_index + 1, path_index + 1)

    return matches(0, 0)
