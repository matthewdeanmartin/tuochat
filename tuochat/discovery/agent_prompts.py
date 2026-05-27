"""Agent prompt file discovery — AGENTS.md, CLAUDE.md, and workspace prompt roots."""

from __future__ import annotations

import sys
from pathlib import Path

AGENT_PROMPT_FILENAMES = (
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    "COPILOT.md",
    "SYSTEM.md",
)

WORKSPACE_PROMPT_ROOTS = (
    ".agents/prompts",
    ".claude/prompts",
    ".augment/prompts",
)

# GitLab Duo user-level agent prompt location
GITLAB_DUO_USER_AGENT_PROMPTS = ("~/.gitlab/duo/AGENTS.md",)
# GitLab Duo workspace-level agent prompt location (relative to cwd)
GITLAB_DUO_WORKSPACE_AGENT_PROMPTS = (".gitlab/duo/AGENTS.md",)


def list_cwd_agent_prompt_files(root: Path | None = None) -> list[Path]:
    """List known agent prompt files in priority order from the cwd root."""
    cwd = root or Path.cwd()
    candidates: list[Path] = []
    for name in AGENT_PROMPT_FILENAMES:
        path = cwd / name
        if path.is_file():
            candidates.append(path)
    return candidates


def list_workspace_agent_prompt_files(root: Path | None = None) -> list[Path]:
    """List .md files from workspace prompt roots (.agents/prompts, etc.)."""
    cwd = root or Path.cwd()
    candidates: list[Path] = []
    for relative_root in WORKSPACE_PROMPT_ROOTS:
        prompt_dir = cwd / relative_root
        if not prompt_dir.is_dir():
            continue
        for path in sorted(prompt_dir.glob("*.md")):
            if path.is_file():
                candidates.append(path)
    return candidates


def list_gitlab_duo_agent_prompt_files(root: Path | None = None) -> list[Path]:
    """List GitLab Duo agent prompt files from user-level and workspace locations."""
    cwd = root or Path.cwd()
    candidates: list[Path] = []
    for pattern in GITLAB_DUO_USER_AGENT_PROMPTS:
        path = Path(pattern).expanduser()
        if path.is_file():
            candidates.append(path)
    for pattern in GITLAB_DUO_WORKSPACE_AGENT_PROMPTS:
        path = cwd / pattern
        if path.is_file():
            candidates.append(path)
    return candidates


def list_available_agent_prompts(root: Path | None = None) -> list[Path]:
    """List all discoverable agent prompt files in priority order.

    Order:
    1. cwd root prompt files (AGENTS.md, CLAUDE.md, etc.) in priority order
    2. workspace prompt roots (.agents/prompts/, .claude/prompts/, etc.)
    3. GitLab Duo user-level and workspace agent prompt files
    """
    seen: set[Path] = set()
    candidates: list[Path] = []
    for path in [
        *list_cwd_agent_prompt_files(root),
        *list_workspace_agent_prompt_files(root),
        *list_gitlab_duo_agent_prompt_files(root),
    ]:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        candidates.append(path)
    return candidates


def describe_agent_prompt_path(path: Path) -> str:
    """Return a friendly label for an agent prompt file."""
    gitlab_duo_user_dir = Path("~/.gitlab/duo").expanduser()
    try:
        relative = path.relative_to(gitlab_duo_user_dir)
        return f"gitlab-duo-user:{relative.as_posix()}"
    except ValueError:
        pass
    try:
        relative = path.relative_to(Path.cwd())
        if relative.as_posix().startswith(".gitlab/duo/"):
            return f"gitlab-duo-workspace:{relative.as_posix()}"
        return f"cwd:{relative.as_posix()}"
    except ValueError:
        pass
    for relative_root in WORKSPACE_PROMPT_ROOTS:
        workspace_dir = Path.cwd() / relative_root
        try:
            relative = path.relative_to(workspace_dir)
            return f"workspace:{relative_root}/{relative.as_posix()}"
        except ValueError:
            pass
    return f"file:{path.name}"


def load_agent_prompt_content(path: Path) -> str | None:
    """Load and return agent prompt file content, or None on failure."""
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except UnicodeDecodeError:
        print(f"Warning: agent prompt file is not valid UTF-8 and was ignored: {path}", file=sys.stderr)
        return None
    return text or None


def auto_select_agent_prompt(root: Path | None = None) -> tuple[Path | None, str | None]:
    """Select the highest-priority agent prompt file.

    Returns (path, label) or (None, None) if none found.
    """
    candidates = list_available_agent_prompts(root)
    if not candidates:
        return None, None
    path = candidates[0]
    label = describe_agent_prompt_path(path)
    return path, label
