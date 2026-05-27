"""Template file discovery, rendering, and metadata parsing."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from tuochat.constants import WORKSPACE_TEMPLATE_ROOTS
from tuochat.discovery.shared import bundled_templates_dir, parse_frontmatter_metadata

if TYPE_CHECKING:
    from tuochat.config import TuochatConfig


def parse_template_metadata(path: Path) -> tuple[str, str]:
    """Return the template name and description from TEMPLATE.md frontmatter when present."""
    default_name = path.parent.name
    default_description = ""
    metadata, _body = parse_frontmatter_metadata(path)
    name = metadata.get("name") or default_name
    description = metadata.get("description") or default_description
    return name, description


def template_body(path: Path) -> str:
    """Return the template body without frontmatter metadata."""
    _metadata, body = parse_frontmatter_metadata(path)
    return body.strip()


def render_template_prompt_from_path(
    path: Path,
    cfg: TuochatConfig,
    *,
    provided_values: dict[str, str] | None = None,
    prompt_for_value=None,
    cwd: Path | None = None,
) -> tuple[str, str, dict[str, object]]:
    """Render a template file into a ready-to-attach prompt plus metadata."""
    from tuochat.context.composer import resolve_template_prompt

    label = describe_template_path(path, cfg)
    rendered_prompt, metadata = resolve_template_prompt(
        template_body(path),
        provided_values=provided_values,
        prompt_for_value=prompt_for_value,
        cwd=cwd,
    )
    metadata = {
        "label": label,
        "name": parse_template_metadata(path)[0],
        **metadata,
    }
    return label, rendered_prompt, metadata


def list_template_files_in_root(root: Path) -> list[Path]:
    """List prompt templates stored as <root>/<template-name>/TEMPLATE.md."""
    if not root.is_dir():
        return []
    candidates: list[Path] = []
    for path in sorted(root.glob("*/TEMPLATE.md")):
        if path.is_file():
            candidates.append(path)
    return candidates


def list_workspace_template_files(root: Path) -> list[Path]:
    """List workspace templates from standard .agents/.claude/.augment locations."""
    candidates: list[Path] = []
    for relative_root in WORKSPACE_TEMPLATE_ROOTS:
        candidates.extend(list_template_files_in_root(root / relative_root))
    return candidates


def template_source_for_path(path: Path, cfg: TuochatConfig) -> str:
    """Classify a discovered template path by source."""
    resolved = path.resolve()
    if resolved.is_relative_to(cfg.templates_dir.resolve()):
        return "central"
    if resolved.is_relative_to(bundled_templates_dir().resolve()):
        return "bundled"
    return "workspace"


def list_available_templates(cfg: TuochatConfig) -> list[Path]:
    """List centralized, bundled, and cwd-relative prompt templates."""
    seen: set[Path] = set()
    candidates: list[Path] = []
    roots = [
        *list_template_files_in_root(cfg.templates_dir),
        *list_template_files_in_root(bundled_templates_dir()),
        *list_workspace_template_files(Path.cwd()),
    ]
    for path in roots:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        candidates.append(path)
    return candidates


def describe_template_path(path: Path, cfg: TuochatConfig) -> str:
    """Return a friendly template label for display and loading."""
    name, _description = parse_template_metadata(path)
    source = template_source_for_path(path, cfg)
    try:
        relative = path.relative_to(cfg.templates_dir)
        return f"central:{relative.parent.as_posix()} ({name})"
    except ValueError:
        pass
    try:
        relative = path.relative_to(bundled_templates_dir())
        return f"bundled:{relative.parent.as_posix()} ({name})"
    except ValueError:
        pass
    try:
        relative = path.relative_to(Path.cwd())
        return f"cwd:{relative.parent.as_posix()} ({name})"
    except ValueError:
        return f"{source}:{path.parent.name} ({name})"
