"""Custom instruction file discovery."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from tuochat.constants import WORKSPACE_CUSTOM_INSTRUCTION_ROOTS
from tuochat.discovery.shared import bundled_custom_instructions_dir, list_text_files

if TYPE_CHECKING:
    from tuochat.config import TuochatConfig

# GitLab Duo user-level custom instruction files
GITLAB_DUO_USER_CUSTOM_INSTRUCTIONS = ("~/.gitlab/duo/chat-rules.md",)
# GitLab Duo workspace-level custom instruction files (relative to cwd)
GITLAB_DUO_WORKSPACE_CUSTOM_INSTRUCTIONS = (".gitlab/duo/chat-rules.md",)


def custom_instruction_source_for_path(path: Path, cfg: TuochatConfig) -> str:
    """Classify a discovered custom-instruction path by source."""
    resolved = path.resolve()
    if resolved.is_relative_to(cfg.custom_instructions_dir.resolve()):
        return "central"
    if resolved.is_relative_to(bundled_custom_instructions_dir().resolve()):
        return "bundled"
    return "workspace"


def list_workspace_custom_instruction_files(root: Path) -> list[Path]:
    """List workspace custom instructions from standard well-known locations."""
    candidates: list[Path] = []
    for relative_root in WORKSPACE_CUSTOM_INSTRUCTION_ROOTS:
        candidates.extend(list_text_files(root / relative_root))
    return candidates


def list_gitlab_duo_custom_instruction_files(root: Path | None = None) -> list[Path]:
    """List GitLab Duo custom instruction files from user-level and workspace locations."""
    cwd = root or Path.cwd()
    candidates: list[Path] = []
    for pattern in GITLAB_DUO_USER_CUSTOM_INSTRUCTIONS:
        path = Path(pattern).expanduser()
        if path.is_file():
            candidates.append(path)
    for pattern in GITLAB_DUO_WORKSPACE_CUSTOM_INSTRUCTIONS:
        path = cwd / pattern
        if path.is_file():
            candidates.append(path)
    return candidates


def list_available_custom_instructions(cfg: TuochatConfig) -> list[Path]:
    """List centralized, bundled, cwd-relative, and GitLab Duo custom instruction files."""
    seen: set[Path] = set()
    candidates: list[Path] = []
    roots = [
        *list_text_files(cfg.custom_instructions_dir),
        *list_text_files(bundled_custom_instructions_dir()),
        *list_workspace_custom_instruction_files(Path.cwd()),
        *list_gitlab_duo_custom_instruction_files(),
    ]
    for path in roots:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        candidates.append(path)
    return candidates


def describe_custom_instruction_path(path: Path, cfg: TuochatConfig) -> str:
    """Return a friendly custom-instruction label for display and loading."""
    source = custom_instruction_source_for_path(path, cfg)
    gitlab_duo_user_dir = Path("~/.gitlab/duo").expanduser()
    try:
        relative = path.relative_to(gitlab_duo_user_dir)
        return f"gitlab-duo-user:{relative.as_posix()}"
    except ValueError:
        pass
    try:
        relative = path.relative_to(cfg.custom_instructions_dir)
        return f"central:{relative.as_posix()}"
    except ValueError:
        pass
    try:
        relative = path.relative_to(bundled_custom_instructions_dir())
        return f"bundled:{relative.as_posix()}"
    except ValueError:
        pass
    try:
        relative = path.relative_to(Path.cwd())
        if relative.as_posix().startswith(".gitlab/duo/"):
            return f"gitlab-duo-workspace:{relative.as_posix()}"
        return f"cwd:{relative.as_posix()}"
    except ValueError:
        return f"{source}:{path.name}"
