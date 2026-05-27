"""Skill file discovery, rendering, and metadata parsing."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from tuochat.constants import SKILL_SOURCE_LABELS, WORKSPACE_SKILL_ROOTS
from tuochat.context.attachments import read_include_file
from tuochat.discovery.shared import bundled_skills_dir, parse_frontmatter_metadata

if TYPE_CHECKING:
    from tuochat.config import TuochatConfig

# Matches {identifier} placeholders in skill bodies.
SKILL_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def sandbox_prompts_dir() -> Path:
    """Return the bundled sandbox prompts directory."""
    return Path(__file__).resolve().parent.parent / "sandbox" / "prompts"


def expand_skill_body(body: str, skill_path: Path) -> str:
    """Expand {placeholder} variables in a skill body.

    Placeholder resolution order:
    1. A file named ``<placeholder>.md`` next to the SKILL.md itself.
    2. A file named ``<placeholder>.md`` in the bundled sandbox prompts directory.

    Unknown placeholders are left as-is.
    """
    search_dirs = [skill_path.parent, sandbox_prompts_dir()]

    def replace(match: re.Match[str]) -> str:  # type: ignore[type-arg]
        name = match.group(1)
        for directory in search_dirs:
            candidate = directory / f"{name}.md"
            if candidate.is_file():
                try:
                    return candidate.read_text(encoding="utf-8").strip()
                except (OSError, UnicodeDecodeError):
                    pass
        return match.group(0)  # leave unchanged

    return SKILL_PLACEHOLDER_RE.sub(replace, body)


def parse_skill_metadata(path: Path) -> tuple[str, str]:
    """Return the skill name and description from SKILL.md frontmatter when present."""
    default_name = path.parent.name
    default_description = ""
    metadata, _body = parse_frontmatter_metadata(path)
    name = metadata.get("name") or default_name
    description = metadata.get("description") or default_description
    return name, description


def render_skill_message(path: Path, cfg: TuochatConfig) -> tuple[str, str]:
    """Return the rendered label and conversation payload for a skill file."""
    content, _fingerprint, _size = read_include_file(path)
    content = expand_skill_body(content, path)
    label = describe_skill_path(path, cfg)
    return label, f"Loaded skill: {label}\n```text\n{content}\n```"


def list_skill_files_in_root(root: Path) -> list[Path]:
    """List Anthropic-style skills stored as <root>/<skill-name>/SKILL.md."""
    if not root.is_dir():
        return []
    candidates: list[Path] = []
    for path in sorted(root.glob("*/SKILL.md")):
        if path.is_file():
            candidates.append(path)
    return candidates


def list_workspace_skill_files(root: Path) -> list[Path]:
    """List workspace skills from standard .agents/.claude/.augment locations."""
    candidates: list[Path] = []
    for relative_root in WORKSPACE_SKILL_ROOTS:
        candidates.extend(list_skill_files_in_root(root / relative_root))
    return candidates


def skill_source_for_path(path: Path, cfg: TuochatConfig) -> str:
    """Classify a discovered skill path by source."""
    resolved = path.resolve()
    if resolved.is_relative_to(cfg.skills_dir.resolve()):
        return "central"
    if resolved.is_relative_to(bundled_skills_dir().resolve()):
        return "bundled"
    gitlab_duo_user = Path("~/.gitlab/duo/skills").expanduser().resolve()
    if resolved.is_relative_to(gitlab_duo_user):
        return "gitlab-duo-user"
    return "workspace"


def list_gitlab_duo_user_skill_files() -> list[Path]:
    """List GitLab Duo user-level skills from ~/.gitlab/duo/skills/."""
    return list_skill_files_in_root(Path("~/.gitlab/duo/skills").expanduser())


def list_available_skills(cfg: TuochatConfig) -> list[Path]:
    """List centralized, bundled, cwd-relative, and GitLab Duo Anthropic-style skills."""
    seen: set[Path] = set()
    candidates: list[Path] = []
    roots = [
        *list_skill_files_in_root(cfg.skills_dir),
        *list_skill_files_in_root(bundled_skills_dir()),
        *list_workspace_skill_files(Path.cwd()),
        *list_gitlab_duo_user_skill_files(),
    ]
    for path in roots:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        candidates.append(path)
    return candidates


def describe_skill_path(path: Path, cfg: TuochatConfig) -> str:
    """Return a friendly skill label for display and loading."""
    name, _description = parse_skill_metadata(path)
    source = skill_source_for_path(path, cfg)
    try:
        relative = path.relative_to(cfg.skills_dir)
        return f"central:{relative.parent.as_posix()} ({name})"
    except ValueError:
        pass
    try:
        relative = path.relative_to(bundled_skills_dir())
        return f"bundled:{relative.parent.as_posix()} ({name})"
    except ValueError:
        pass
    gitlab_duo_user = Path("~/.gitlab/duo/skills").expanduser()
    try:
        relative = path.relative_to(gitlab_duo_user)
        return f"gitlab-duo-user:{relative.parent.as_posix()} ({name})"
    except ValueError:
        pass
    try:
        relative = path.relative_to(Path.cwd())
        return f"cwd:{relative.parent.as_posix()} ({name})"
    except ValueError:
        return f"{source}:{path.parent.name} ({name})"


def group_skills_by_source(paths: list[Path], cfg: TuochatConfig) -> dict[str, list[Path]]:
    """Group skill files by source category."""
    grouped: dict[str, list[Path]] = {key: [] for key in SKILL_SOURCE_LABELS}
    for path in paths:
        grouped[skill_source_for_path(path, cfg)].append(path)
    return grouped


def print_skills_listing(cfg: TuochatConfig, *, limit_per_source: int | None = None) -> None:
    """Print the available skills grouped by source."""
    candidates = list_available_skills(cfg)
    if not candidates:
        print("No skill files found.")
        return

    grouped = group_skills_by_source(candidates, cfg)
    print("Available skills:")
    total_hidden = 0
    for source in ("central", "bundled", "workspace"):
        items = grouped[source]
        print(f"  {SKILL_SOURCE_LABELS[source]} ({len(items)}):")
        if not items:
            print("    none")
            continue
        visible_items = items if limit_per_source is None else items[:limit_per_source]
        for path in visible_items:
            name, description = parse_skill_metadata(path)
            line = f"    - {name}"
            if description:
                line += f": {description}"
            print(line)
        if limit_per_source is not None and len(items) > limit_per_source:
            hidden = len(items) - limit_per_source
            total_hidden += hidden
            print(f"    ... and {hidden} more")
    if total_hidden:
        print("Use /skills to browse all available skills.")


def print_startup_skills_summary(cfg: TuochatConfig) -> None:
    """Print a short startup summary of discovered skills."""
    print_skills_listing(cfg, limit_per_source=5)
    print()
