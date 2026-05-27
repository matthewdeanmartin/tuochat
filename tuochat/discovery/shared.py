"""Shared helpers for all discovery modules."""

from __future__ import annotations

from pathlib import Path

from tuochat.patterns import SKILL_FRONTMATTER_RE


def bundled_skills_dir() -> Path:
    """Return the bundled skills directory within the installed package."""
    return Path(__file__).resolve().parent.parent / "skills"


def bundled_custom_instructions_dir() -> Path:
    """Return the bundled custom-instructions directory within the installed package."""
    return Path(__file__).resolve().parent.parent / "custom_instructions"


def bundled_templates_dir() -> Path:
    """Return the bundled templates directory within the installed package."""
    return Path(__file__).resolve().parent.parent / "templates"


def list_text_files(root: Path) -> list[Path]:
    """List text-like files from a specific root directory."""
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
    }
    if not root.is_dir():
        return []
    candidates: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in allowed_suffixes:
            candidates.append(path)
    return candidates


def parse_frontmatter_metadata(path: Path) -> tuple[dict[str, str], str]:
    """Return parsed frontmatter metadata and content body from a text file."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}, ""

    match = SKILL_FRONTMATTER_RE.match(text)
    if not match:
        return {}, text

    metadata: dict[str, str] = {}
    for raw_line in match.group(1).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip().lower()] = value.strip().strip("'\"")
    return metadata, text[match.end() :]
