"""Shared context-discovery commands for CLI and REPL dispatch."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from tuochat.constants import CUSTOM_INSTRUCTION_SOURCE_LABELS, SKILL_SOURCE_LABELS
from tuochat.context.attachments import list_include_candidates
from tuochat.discovery.custom_instructions import describe_custom_instruction_path, list_available_custom_instructions
from tuochat.discovery.skills import (
    describe_skill_path,
    group_skills_by_source,
    list_available_skills,
    parse_skill_metadata,
)
from tuochat.discovery.templates import describe_template_path, list_available_templates, parse_template_metadata
from tuochat.serialization import json_dumps

if TYPE_CHECKING:
    from tuochat.cli.command_models import (
        ListCustomInstructionsCommand,
        ListFilesCommand,
        ListSkillsCommand,
        ListTemplatesCommand,
    )
    from tuochat.config import TuochatConfig


def run_files(command: ListFilesCommand) -> int:
    """List likely include-able files in the current working directory."""
    candidates = list_include_candidates()
    payload = [str(path.relative_to(Path.cwd())) for path in candidates]
    if command.format == "json":
        print(json_dumps(payload, indent=True))
        return 0
    if not candidates:
        print("No include-able files found in the current working directory.")
        return 0
    print("Include-able files:")
    for path in candidates:
        print(f"- {path.relative_to(Path.cwd())}")
    return 0


def run_skills(cfg: TuochatConfig, command: ListSkillsCommand) -> int:
    """List discovered skills."""
    candidates = list_available_skills(cfg)
    payload = [
        {
            "path": str(path),
            "label": describe_skill_path(path, cfg),
            "name": parse_skill_metadata(path)[0],
            "description": parse_skill_metadata(path)[1],
        }
        for path in candidates
    ]
    if command.format == "json":
        print(json_dumps(payload, indent=True))
        return 0
    if not payload:
        print("No skill files found.")
        return 0
    print("Available skills:")
    grouped = group_skills_by_source(candidates, cfg)
    for source in ("central", "bundled", "workspace"):
        items = grouped[source]
        print(f"  {SKILL_SOURCE_LABELS[source]} ({len(items)}):")
        if not items:
            print("    none")
            continue
        for path in items:
            name, description = parse_skill_metadata(path)
            line = f"    - {name}"
            if description:
                line += f": {description}"
            print(line)
    return 0


def run_templates(cfg: TuochatConfig, command: ListTemplatesCommand) -> int:
    """List discovered templates."""
    candidates = list_available_templates(cfg)
    payload = [
        {
            "path": str(path),
            "label": describe_template_path(path, cfg),
            "name": parse_template_metadata(path)[0],
            "description": parse_template_metadata(path)[1],
        }
        for path in candidates
    ]
    if command.format == "json":
        print(json_dumps(payload, indent=True))
        return 0
    if not payload:
        print("No template files found.")
        return 0
    print("Available templates:")
    for item in payload:
        line = f"- {item['label']}"
        if item["description"]:
            line += f": {item['description']}"
        print(line)
    return 0


def run_custom_instructions(cfg: TuochatConfig, command: ListCustomInstructionsCommand) -> int:
    """List discovered custom-instruction files."""
    candidates = list_available_custom_instructions(cfg)
    payload = [
        {
            "path": str(path),
            "label": describe_custom_instruction_path(path, cfg),
        }
        for path in candidates
    ]
    if command.format == "json":
        print(json_dumps(payload, indent=True))
        return 0
    if not payload:
        print("No custom instruction files found.")
        return 0
    print("Available custom instructions:")
    grouped: dict[str, list[dict[str, str]]] = {key: [] for key in CUSTOM_INSTRUCTION_SOURCE_LABELS}
    for item in payload:
        source = "workspace"
        label = item["label"]
        if label.startswith("central:"):
            source = "central"
        elif label.startswith("bundled:"):
            source = "bundled"
        grouped[source].append(item)
    for source in ("central", "bundled", "workspace"):
        items = grouped[source]
        print(f"  {CUSTOM_INSTRUCTION_SOURCE_LABELS[source]} ({len(items)}):")
        if not items:
            print("    none")
            continue
        for item in items:
            print(f"    - {item['label']}")
    return 0
