"""Context Artifact model — a unified representation of any prompt-bearing context item."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from tuochat.estimation import estimate_tokens

if TYPE_CHECKING:
    from tuochat.config import TuochatConfig


class ArtifactKind(str, Enum):
    AGENT_PROMPT = "agent_prompt"
    SKILL = "skill"
    TEMPLATE = "template"
    CUSTOM_INSTRUCTION = "custom_instruction"
    FILE_ATTACHMENT = "file_attachment"
    RECIPE = "recipe"
    WORKSPACE_MEMORY = "workspace_memory"


class AppliesTo(str, Enum):
    CURRENT_TURN = "current_turn"
    NEXT_TURN = "next_turn"
    NEXT_CONVERSATION = "next_conversation"
    SESSION_PROMPT = "session_prompt"


@dataclass
class ContextArtifact:
    """A unified representation of any prompt-bearing context item."""

    kind: ArtifactKind
    display_name: str
    source_label: str
    path: Path | None = None

    # Content
    raw_content: str = ""
    resolved_content: str = ""

    # State
    is_active: bool = False
    applies_to: AppliesTo = AppliesTo.NEXT_TURN

    # Provenance
    variables_applied: dict[str, str] = field(default_factory=dict)
    was_resolved: bool = False

    @property
    def size_chars(self) -> int:
        content = self.resolved_content or self.raw_content
        return len(content)

    @property
    def estimated_tokens(self) -> int:
        content = self.resolved_content or self.raw_content
        return estimate_tokens(content)


def discover_agent_prompt_artifacts(cfg: TuochatConfig) -> list[ContextArtifact]:  # pylint: disable=unused-argument
    """Discover all available agent prompt files and return them as artifacts."""
    from tuochat.discovery.agent_prompts import describe_agent_prompt_path, list_available_agent_prompts

    artifacts: list[ContextArtifact] = []
    for path in list_available_agent_prompts():
        label = describe_agent_prompt_path(path)
        try:
            raw = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            raw = ""
        artifacts.append(
            ContextArtifact(
                kind=ArtifactKind.AGENT_PROMPT,
                display_name=path.name,
                source_label=label,
                path=path,
                raw_content=raw,
                resolved_content=raw,
                applies_to=AppliesTo.SESSION_PROMPT,
            )
        )
    return artifacts


def discover_skill_artifacts(cfg: TuochatConfig) -> list[ContextArtifact]:
    """Discover all available skills and return them as artifacts."""
    from tuochat.discovery.shared import parse_frontmatter_metadata
    from tuochat.discovery.skills import (
        describe_skill_path,
        expand_skill_body,
        list_available_skills,
        parse_skill_metadata,
    )

    artifacts: list[ContextArtifact] = []
    for path in list_available_skills(cfg):
        label = describe_skill_path(path, cfg)
        name, _ = parse_skill_metadata(path)
        _, raw = parse_frontmatter_metadata(path)
        raw = raw.strip()
        resolved = expand_skill_body(raw, path)
        artifacts.append(
            ContextArtifact(
                kind=ArtifactKind.SKILL,
                display_name=name,
                source_label=label,
                path=path,
                raw_content=raw,
                resolved_content=resolved,
                was_resolved=resolved != raw,
                applies_to=AppliesTo.NEXT_TURN,
            )
        )
    return artifacts


def discover_template_artifacts(cfg: TuochatConfig) -> list[ContextArtifact]:
    """Discover all available templates and return them as artifacts."""
    from tuochat.discovery.templates import (
        describe_template_path,
        list_available_templates,
        parse_template_metadata,
        template_body,
    )

    artifacts: list[ContextArtifact] = []
    for path in list_available_templates(cfg):
        label = describe_template_path(path, cfg)
        name, _ = parse_template_metadata(path)
        raw = template_body(path)
        artifacts.append(
            ContextArtifact(
                kind=ArtifactKind.TEMPLATE,
                display_name=name,
                source_label=label,
                path=path,
                raw_content=raw,
                resolved_content=raw,
                applies_to=AppliesTo.NEXT_TURN,
            )
        )
    return artifacts


def discover_custom_instruction_artifacts(cfg: TuochatConfig) -> list[ContextArtifact]:
    """Discover all available custom instruction files and return them as artifacts."""
    from tuochat.discovery.custom_instructions import (
        describe_custom_instruction_path,
        list_available_custom_instructions,
    )

    artifacts: list[ContextArtifact] = []
    for path in list_available_custom_instructions(cfg):
        label = describe_custom_instruction_path(path, cfg)
        try:
            raw = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            raw = ""
        artifacts.append(
            ContextArtifact(
                kind=ArtifactKind.CUSTOM_INSTRUCTION,
                display_name=path.name,
                source_label=label,
                path=path,
                raw_content=raw,
                resolved_content=raw,
                applies_to=AppliesTo.NEXT_CONVERSATION,
            )
        )
    return artifacts


def discover_workspace_memory_artifacts() -> list[ContextArtifact]:
    """Discover workspace-pinned memory/todo/compact files and return them as artifacts."""
    from tuochat.workspace_memory import compact_path, memory_path, todo_path

    entries = [
        ("memory.md", "Workspace memory notes", memory_path()),
        ("todo.md", "Workspace task list", todo_path()),
        ("compact.md", "Workspace compact summary", compact_path()),
    ]
    artifacts: list[ContextArtifact] = []
    for display_name, source_label, path in entries:
        if not path.is_file():
            continue
        try:
            raw = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            raw = ""
        if not raw:
            continue
        artifacts.append(
            ContextArtifact(
                kind=ArtifactKind.WORKSPACE_MEMORY,
                display_name=display_name,
                source_label=source_label,
                path=path,
                raw_content=raw,
                resolved_content=raw,
                is_active=True,
                applies_to=AppliesTo.SESSION_PROMPT,
            )
        )
    return artifacts


def discover_all_artifacts(cfg: TuochatConfig) -> list[ContextArtifact]:
    """Discover all context artifacts grouped by kind."""
    artifacts: list[ContextArtifact] = []
    artifacts.extend(discover_agent_prompt_artifacts(cfg))
    artifacts.extend(discover_skill_artifacts(cfg))
    artifacts.extend(discover_template_artifacts(cfg))
    artifacts.extend(discover_custom_instruction_artifacts(cfg))
    artifacts.extend(discover_workspace_memory_artifacts())
    return artifacts
