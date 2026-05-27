"""System prompt composition — AGENTS.md, custom instructions, personalization, templates."""

from __future__ import annotations

import getpass
import platform
import re
import subprocess  # nosec: B404
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from tuochat.constants import DEFAULT_CUSTOM_INSTRUCTION_FILENAME, WORKSPACE_CUSTOM_INSTRUCTION_ROOTS
from tuochat.context.attachments import code_fence_language, list_include_candidates_under, read_include_file
from tuochat.discovery.custom_instructions import describe_custom_instruction_path
from tuochat.discovery.shared import bundled_custom_instructions_dir
from tuochat.patterns import TEMPLATE_VARIABLE_RE
from tuochat.serialization import JSONDecodeError, json_loads

if TYPE_CHECKING:
    from tuochat.config import TuochatConfig
    from tuochat.models import Conversation, Message

AUTO_TEMPLATE_VARIABLE_NAMES = (
    "DATE",
    "TIME",
    "DATE_TIME",
    "USER_NAME",
    "USER_OS",
    "WORKING_DIRECTORY",
    "DIRECTORY_LISTING",
    "GIT_REPO_STATUS",
    "GIT_REPO_NAME",
    "GIT_REPO_ROOT",
)
FILE_TEMPLATE_VARIABLE_NAMES = ("ATTACHED_CODE",)
ATTACHED_CODE_PROMPT = "Attached code file: "
DIRECTORY_LISTING_LIMIT = 50
SKILL_MESSAGE_PREFIX = "Loaded skill: "


#
# AGENTS.md
#


def load_agents_instructions(agent_prompt_path: Path | None = None) -> tuple[str | None, str | None]:
    """Load an agent prompt file (defaults to AGENTS.md from cwd).

    When ``agent_prompt_path`` is given, that file is used instead of the
    default ``AGENTS.md`` lookup.
    """
    path = agent_prompt_path if agent_prompt_path is not None else Path.cwd() / "AGENTS.md"
    if not path.is_file():
        return None, None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except UnicodeDecodeError:
        print(f"Warning: agent prompt file is not valid UTF-8 and was ignored: {path}", file=sys.stderr)
        return None, None
    if not text:
        return None, None
    label = f"cwd:{path.name} ({path})"
    return f"{path.name} instructions:\n" + text, label


def strip_agents_instructions_prefix(system_prompt: str | None, agent_prompt_path: Path | None = None) -> str | None:
    """Remove the agent prompt prefix from a composed system prompt."""
    prompt = system_prompt.strip() if system_prompt else None
    if not prompt:
        return None
    agents_content, _ = load_agents_instructions(agent_prompt_path)
    if not agents_content:
        return prompt
    if prompt == agents_content:
        return None
    prefix = agents_content + "\n\n"
    if prompt.startswith(prefix):
        remainder = prompt[len(prefix) :].strip()
        return remainder or None
    return prompt


def system_prompt_includes_agents_instructions(
    system_prompt: str | None, agent_prompt_path: Path | None = None
) -> bool:
    """Return whether the agent prompt block is present in a system prompt."""
    prompt = system_prompt.strip() if system_prompt else None
    if not prompt:
        return False
    agents_content, _ = load_agents_instructions(agent_prompt_path)
    if not agents_content:
        return False
    return prompt == agents_content or prompt.startswith(agents_content + "\n\n")


#
# Custom instructions
#


def mode_instruction_filename(mode: str | None) -> str:
    """Return the INSTRUCTIONS filename to prefer for the given UI mode."""
    if mode in ("headless", "gui"):
        return f"INSTRUCTIONS_{mode}.md"
    return DEFAULT_CUSTOM_INSTRUCTION_FILENAME


def default_custom_instruction_paths(cfg: TuochatConfig, mode: str | None = None) -> list[Path]:
    """Return persistent custom-instruction files loaded for every new conversation.

    When *mode* is ``"headless"`` or ``"gui"``, the bundled mode-specific
    ``INSTRUCTIONS_{mode}.md`` replaces the generic bundled ``INSTRUCTIONS.md``.
    The central and workspace slots always use the generic filename so that
    project-local overrides remain mode-agnostic.
    """
    mode_filename = mode_instruction_filename(mode)
    bundled_dir = bundled_custom_instructions_dir()
    mode_specific = bundled_dir / mode_filename
    generic_bundled = bundled_dir / DEFAULT_CUSTOM_INSTRUCTION_FILENAME
    # Use the mode-specific bundled file when it exists; fall back to the generic one.
    bundled_candidate = (
        mode_specific
        if (mode_filename != DEFAULT_CUSTOM_INSTRUCTION_FILENAME and mode_specific.is_file())
        else generic_bundled
    )
    candidates = [
        cfg.custom_instructions_dir / DEFAULT_CUSTOM_INSTRUCTION_FILENAME,
        bundled_candidate,
        *[Path.cwd() / root / DEFAULT_CUSTOM_INSTRUCTION_FILENAME for root in WORKSPACE_CUSTOM_INSTRUCTION_ROOTS],
    ]
    seen: set[Path] = set()
    paths: list[Path] = []
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved in seen or not path.is_file():
            continue
        seen.add(resolved)
        paths.append(path)
    return paths


def load_custom_instruction_sections(
    cfg: TuochatConfig, extra_paths: list[Path] | None = None, *, mode: str | None = None
) -> list[tuple[str, str]]:
    """Load persistent and one-shot custom instructions with source labels.

    Pass *mode* as ``"headless"`` or ``"gui"`` to load the mode-specific
    bundled instructions instead of the generic ``INSTRUCTIONS.md``.
    """
    sections: list[tuple[str, str]] = []
    seen: set[Path] = set()
    for path in [*default_custom_instruction_paths(cfg, mode=mode), *(extra_paths or [])]:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved in seen or not path.is_file():
            continue
        seen.add(resolved)
        try:
            text = path.read_text(encoding="utf-8").strip()
        except UnicodeDecodeError:
            print(
                f"Warning: custom instruction file is not valid UTF-8 and was ignored: {path}",
                file=sys.stderr,
            )
            continue
        if not text:
            continue
        sections.append((f"{describe_custom_instruction_path(path, cfg)} ({path})", text))
    return sections


#
# System prompt composition
#


def compose_system_prompt(
    base_system_prompt: str | None,
    custom_sections: list[tuple[str, str]] | None = None,
    *,
    include_agents: bool = True,
    agent_prompt_path: Path | None = None,
    include_workspace_memory: bool = True,
) -> tuple[str | None, list[str]]:
    """Compose the system prompt for a new conversation and return source labels."""
    from tuochat.workspace_memory import load_pinned_sections

    parts = []
    sources: list[str] = []
    agents_content, agents_source = load_agents_instructions(agent_prompt_path) if include_agents else (None, None)
    base_prompt = base_system_prompt.strip() if base_system_prompt and base_system_prompt.strip() else None
    if (
        agents_content
        and base_prompt != agents_content
        and not (base_prompt and base_prompt.startswith(agents_content + "\n\n"))
    ):
        parts.append(agents_content)
        if agents_source:
            sources.append(agents_source)
    if base_prompt:
        parts.append(base_prompt)
        sources.append("cli/system prompt")
    for label, content in custom_sections or []:
        stripped = content.strip()
        if not stripped:
            continue
        parts.append(f"Custom instructions from {label}:\n{stripped}")
        sources.append(label)
    if include_workspace_memory:
        for label, content in load_pinned_sections():
            stripped = content.strip()
            if not stripped:
                continue
            parts.append(f"{label}:\n{stripped}")
            sources.append(label)
    if not parts:
        return None, []
    return "\n\n".join(parts), sources


#
# Personalization
#


def build_personalization_block(cfg: TuochatConfig) -> str:
    """Return a first-request personalization block from config."""
    if not cfg.personalization.enabled:
        return ""
    entries = []
    if cfg.personalization.name.strip():
        entries.append(f"My name is {cfg.personalization.name.strip()}.")
    if cfg.personalization.profession.strip():
        profession = cfg.personalization.profession.strip()
        lowered = profession.casefold()
        if lowered.startswith(("a ", "an ", "the ")):
            entries.append(f"I work as {profession}.")
        elif lowered in {"doctor", "engineer", "teacher", "lawyer", "nurse"}:
            article = "an" if lowered[0] in "aeiou" else "a"
            entries.append(f"I work as {article} {profession}.")
        else:
            entries.append(f"My profession is {profession}.")
    if not entries:
        return ""
    return "Personalization:\n" + "\n".join(entries) + "\n\n"


#
# Conversation extraction helpers
#


def extract_personalization_from_conversation(conv: Conversation) -> str | None:
    """Extract the first-turn personalization block if present."""
    for msg in conv.messages:
        if msg.role != "user" or not msg.content:
            continue
        if not msg.content.startswith("Personalization:\n"):
            return None
        marker = "\n\n"
        end = msg.content.find(marker)
        return msg.content if end == -1 else msg.content[:end]
    return None


def extract_loaded_skills(conv: Conversation) -> list[tuple[str, str]]:
    """Return skill labels and payloads loaded into the conversation."""
    skills: list[tuple[str, str]] = []
    for msg in conv.messages:
        loaded_skill = extract_loaded_skill_message(msg)
        if loaded_skill is None:
            continue
        skills.append(loaded_skill)
    return skills


def extract_loaded_skill_message(message: Message) -> tuple[str, str] | None:
    """Parse a stored skill-loading message into its label and rendered body."""
    if message.role != "user" or not message.content:
        return None
    lines = message.content.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith(SKILL_MESSAGE_PREFIX):
            continue
        label = line[len(SKILL_MESSAGE_PREFIX) :].strip() or "(unnamed)"
        if index + 1 < len(lines) and re.fullmatch(r"```(?:\w+)?", lines[index + 1]):
            body_lines: list[str] = []
            for fence_line in lines[index + 2 :]:
                if fence_line.strip() == "```":
                    break
                body_lines.append(fence_line)
            body = "\n".join(body_lines).strip()
            return label, body or message.content
        return label, message.content
    return None


def extract_used_templates(conv: Conversation) -> list[tuple[str, str, dict[str, object]]]:
    """Return rendered template prompts stored in the conversation."""

    def parse_template_meta(message: Message) -> dict[str, object] | None:
        if not message.extras_json:
            return None
        try:
            extras = json_loads(message.extras_json)
        except (TypeError, ValueError, JSONDecodeError):
            return None
        template = extras.get("template")
        return template if isinstance(template, dict) else None

    templates: list[tuple[str, str, dict[str, object]]] = []
    for msg in conv.messages:
        if msg.role != "user" or not msg.content:
            continue
        metadata = parse_template_meta(msg)
        if not metadata:
            continue
        label = str(metadata.get("label") or "(unnamed)")
        templates.append((label, msg.content, metadata))
    return templates


#
# Template variable substitution
#


def extract_template_variables(text: str) -> list[str]:
    """Return unique template variable names in first-seen order."""
    variables: list[str] = []
    seen: set[str] = set()
    for match in TEMPLATE_VARIABLE_RE.finditer(text):
        name = match.group(1)
        if name in seen:
            continue
        seen.add(name)
        variables.append(name)
    return variables


def fill_template_variables(text: str, values: dict[str, str]) -> str:
    """Render a template by replacing {VARIABLE} placeholders."""
    rendered = text
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", value)
    return rendered


def inspect_git_repository(cwd: Path | None = None) -> tuple[Path | None, str | None]:
    """Return the current git repo root and name, when the cwd is inside one."""
    working_directory = cwd or Path.cwd()
    try:
        completed = subprocess.run(  # nosec: B603,B404
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=working_directory,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return None, None
    if completed.returncode != 0:
        return None, None
    root_text = completed.stdout.strip()
    if not root_text:
        return None, None
    root = Path(root_text)
    return root, root.name


def render_directory_listing(cwd: Path | None = None, *, limit: int = DIRECTORY_LISTING_LIMIT) -> str:
    """Return a bounded, text-only directory listing rooted at the cwd."""
    working_directory = cwd or Path.cwd()
    paths = list_include_candidates_under(working_directory, limit=limit)
    if not paths:
        return f"Working directory: {working_directory}\n(no include-able text files found)"
    lines = [
        f"Working directory: {working_directory}",
        f"Include-able files (up to {limit}):",
    ]
    for path in paths:
        lines.append(f"- {path.relative_to(working_directory)}")
    return "\n".join(lines)


def resolve_user_name(user_name: str | None = None) -> str:
    """Return a display-safe username for template auto-fill."""
    if user_name is not None:
        return user_name.strip() or "unknown"
    try:
        resolved_user_name = getpass.getuser()
    except (ImportError, KeyError, OSError):
        resolved_user_name = ""
    return resolved_user_name.strip() or "unknown"


def build_auto_template_values(
    *, now: datetime | None = None, cwd: Path | None = None, user_name: str | None = None, user_os: str | None = None
) -> dict[str, str]:
    """Return built-in safe template token values."""
    current_time = now or datetime.now().astimezone()
    working_directory = cwd or Path.cwd()
    repo_root, repo_name = inspect_git_repository(working_directory)
    resolved_user_name = resolve_user_name(user_name)
    resolved_user_os = (
        user_os or platform.platform(aliased=True, terse=True) or platform.system()
    ).strip() or "unknown"
    if repo_root is None or repo_name is None:
        git_repo_status = "Not in a git repository."
        git_repo_name = "(not in a git repository)"
        git_repo_root = "(not in a git repository)"
    else:
        git_repo_status = f"In git repository {repo_name} at {repo_root}."
        git_repo_name = repo_name
        git_repo_root = str(repo_root)
    return {
        "DATE": current_time.date().isoformat(),
        "TIME": current_time.strftime("%H:%M:%S"),
        "DATE_TIME": current_time.isoformat(timespec="seconds"),
        "USER_NAME": resolved_user_name,
        "USER_OS": resolved_user_os,
        "WORKING_DIRECTORY": str(working_directory),
        "DIRECTORY_LISTING": render_directory_listing(working_directory),
        "GIT_REPO_STATUS": git_repo_status,
        "GIT_REPO_NAME": git_repo_name,
        "GIT_REPO_ROOT": git_repo_root,
    }


def resolve_path_within_cwd(raw_path: str | Path, *, cwd: Path | None = None) -> Path:
    """Resolve a path and ensure it stays within the working directory."""
    working_directory = cwd or Path.cwd()
    path = raw_path if isinstance(raw_path, Path) else Path(raw_path).expanduser()
    if not path.is_absolute():
        path = working_directory / path
    try:
        path.resolve().relative_to(working_directory.resolve())
    except ValueError as exc:
        raise ValueError(f"Path is outside the working directory: {path}") from exc
    return path


def render_attached_code_value(raw_path: str | Path, *, cwd: Path | None = None) -> tuple[str, str]:
    """Render ATTACHED_CODE from a file path as fenced code plus path metadata."""
    path = resolve_path_within_cwd(raw_path, cwd=cwd)
    if not path.is_file():
        raise ValueError(f"Attached code file not found: {path}")
    try:
        text, _, _ = read_include_file(path)
    except UnicodeDecodeError as exc:
        raise ValueError(f"Attached code file is not valid UTF-8 text: {path}") from exc
    relative_path = path.relative_to(cwd or Path.cwd())
    rendered = "\n".join(
        [
            f"Attached code from {relative_path}:",
            f"```{code_fence_language(path)}",
            text,
            "```",
        ]
    )
    return rendered, str(path)


def resolve_template_prompt(
    body: str,
    *,
    provided_values: dict[str, str] | None = None,
    prompt_for_value: Callable[[str], str] | None = None,
    cwd: Path | None = None,
) -> tuple[str, dict[str, object]]:
    """Render a template body with automatic tokens and interactive fallback."""
    values = dict(provided_values or {})
    auto_values = build_auto_template_values(cwd=cwd)
    resolved_values = dict(auto_values)
    used_auto_variables: list[str] = []
    recorded_variables: dict[str, str] = {}
    missing: list[str] = []

    for variable in extract_template_variables(body):
        if variable in auto_values:
            used_auto_variables.append(variable)
            continue
        if variable == "ATTACHED_CODE":
            raw_value = values.get(variable)
            if raw_value is None:
                if prompt_for_value is None:
                    missing.append(variable)
                    continue
                raw_value = prompt_for_value(ATTACHED_CODE_PROMPT)
            if not raw_value.strip():
                raise ValueError("A file path is required for ATTACHED_CODE.")
            rendered_code, selected_path = render_attached_code_value(raw_value, cwd=cwd)
            resolved_values[variable] = rendered_code
            recorded_variables[variable] = selected_path
            continue
        if variable in values:
            chosen_value = values[variable]
        elif prompt_for_value is not None:
            chosen_value = prompt_for_value(variable)
        else:
            missing.append(variable)
            continue
        resolved_values[variable] = chosen_value
        recorded_variables[variable] = chosen_value

    if missing:
        raise ValueError(f"Missing template variables: {', '.join(missing)}")

    metadata: dict[str, object] = {"variables": recorded_variables}
    if used_auto_variables:
        metadata["auto_variables"] = used_auto_variables
    return fill_template_variables(body, resolved_values), metadata
