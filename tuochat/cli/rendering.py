"""Rendering and display helpers for the interactive CLI."""

from __future__ import annotations

import logging
import os
import re
import subprocess  # nosec: B404
import sys
from pathlib import Path

from tuochat.__about__ import __description__, __license__, __title__, __version__
from tuochat.cli.models import ReplState
from tuochat.cli.prompts import submit_key_hint
from tuochat.config import TuochatConfig
from tuochat.constants import (
    CONTEXT_BOX_WIDTH,
    MODEL_LABELS,
    STARTUP_BANNER,
    classification_display_label,
    classification_help_label,
)
from tuochat.context.attachments import list_include_candidates
from tuochat.context.composer import (
    extract_loaded_skill_message,
    extract_loaded_skills,
    extract_personalization_from_conversation,
    extract_used_templates,
)
from tuochat.context.validation import truncate_for_display
from tuochat.discovery.skills import print_startup_skills_summary
from tuochat.estimation import estimate_token_cost, estimate_tokens, format_cost, word_count
from tuochat.models import Conversation
from tuochat.provider.duo import DuoProvider
from tuochat.sandbox.api import code_interpreter_runtime_details
from tuochat.security.masking import display_text, known_secret_values

logger = logging.getLogger("tuochat.cli")


def blind_mode_enabled(obj):
    from tuochat.cli.session import blind_mode_enabled as session_blind_mode_enabled

    return session_blind_mode_enabled(obj)


def python_version_string():
    from tuochat.cli.session import python_version_string as session_python_version_string

    return session_python_version_string()


def local_now():
    from tuochat.cli.session import local_now as session_local_now

    return session_local_now()


def no_write_enabled(cfg):
    from tuochat.cli.session import no_write_enabled as session_no_write_enabled

    return session_no_write_enabled(cfg)


def write_here_mode_enabled(cfg):
    from tuochat.cli.session import write_here_mode_enabled as session_write_here_mode_enabled

    return session_write_here_mode_enabled(cfg)


def approve_writes_enabled(cfg):
    from tuochat.cli.session import approve_writes_enabled as session_approve_writes_enabled

    return session_approve_writes_enabled(cfg)


def provider_timeout_summary(state):
    from tuochat.cli.session import provider_timeout_summary as session_provider_timeout_summary

    return session_provider_timeout_summary(state)


def extract_template_message_metadata(message):
    from tuochat.cli.session import extract_template_message_metadata as session_extract_template_message_metadata

    return session_extract_template_message_metadata(message)


def latest_assistant_message(conv):
    from tuochat.cli.session import latest_assistant_message as session_latest_assistant_message

    return session_latest_assistant_message(conv)


def clear_screen() -> None:
    """Clear the active terminal screen when possible."""
    command = "cls" if os.name == "nt" else "clear"
    try:
        subprocess.run([command], check=False)  # nosec:B404,B603
    except OSError:
        # Fallback ANSI clear for terminals that support it.
        print("\033[2J\033[H", end="")


def announce_screen_transition(label: str) -> None:
    """Render a blind-friendly screen transition marker."""
    print()
    print(label)
    print()


def number_label(index: int, *, blind_mode: bool) -> str:
    """Format a numbered menu label."""
    return f"{index}" if blind_mode else f"[{index}]"


def print_startup_banner(*, gui_mode: bool = False) -> None:
    """Print a startup banner with runtime details."""
    now = local_now()
    print(STARTUP_BANNER.rstrip())
    print(f"Version: {__version__}")
    print(f"Date: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Python: {python_version_string()}")
    if gui_mode:
        print("Help: /help")
    else:
        print("Help: /help in chat, or `tuochat --help` for CLI options")
    print()


def print_session_intro(state: ReplState) -> None:
    """Print the session banner and usage hint unless suppressed."""
    if getattr(state, "gui_mode", False):
        return
    if not state.no_banner:
        print_startup_banner()
        print_startup_skills_summary(state.cfg)
    print_system_prompt_sources(state)
    if not state.quiet:
        print(
            "Paste your message and submit with "
            f"{submit_key_hint()}. Ctrl+C cancels the current draft; use '/quit' or '/exit' to exit. "
            "Use '/include' or '/attach' to attach a local file, '/skills' to list skills, "
            "and '/template' to run a prompt template.\n"
        )
    chat_cfg = getattr(state.cfg, "chat", None)
    no_write = bool(getattr(chat_cfg, "no_write", False))
    write_here = bool(getattr(chat_cfg, "write_here_mode", False))
    if not no_write and not write_here:
        print(
            "Tip: generated files will be saved to the central archive. "
            "Use /write-here-mode on to write them into the current directory instead."
        )


def print_system_prompt_sources(state: ReplState) -> None:
    """Show which local files contributed to the active system prompt."""
    sources = state.active_system_prompt_sources or []
    if not sources:
        print("System prompt sources: (none)")
        return
    print("System prompt sources:")
    for source in sources:
        print(f"  - {source}")
    print()


def print_mask_notice(state: ReplState) -> None:
    """Warn that terminal masking occurred and explain how to disable it."""
    print(
        "\n[Masking hid sensitive-looking output on screen. "
        "Use /mask off to disable masking for this session, then "
        f"/resume {state.conv.id[:8]} to reload this conversation unmasked.]",
        file=sys.stderr,
    )


def print_no_code_mode_notice(state: ReplState) -> None:
    """Warn that no-code-mode hid shell-like fenced code on screen."""
    print(
        "\n[No-code-mode hid shell-like fenced code on screen. "
        "Use /no-code-mode off to disable it for this session, then "
        f"/resume {state.conv.id[:8]} to reload this conversation without that filter.]",
        file=sys.stderr,
    )


def print_conversation_transcript(conv: Conversation, *, blind_mode: bool = False) -> None:
    """Render the full saved conversation transcript."""
    print(f"Resumed: {conv.title or 'Untitled'} ({conv.id[:8]})")
    if blind_mode:
        announce_screen_transition("Next conversation")
    else:
        print("-" * 60)
    if not conv.messages:
        print("(conversation is empty)")
    for msg in conv.messages:
        label = "you" if msg.role == "user" else msg.role
        print(f"{label}>")
        print(msg.content or "(empty)")
        print()
    if blind_mode:
        announce_screen_transition("End conversation")
    else:
        print("-" * 60)
    print()


def print_masked_conversation_transcript(state: ReplState) -> None:
    """Render the saved conversation transcript with optional screen-only masking."""
    conv = state.conv
    divider = "" if state.blind_mode else "-" * 60
    print(f"Resumed: {conv.title or 'Untitled'} ({conv.id[:8]})")
    if divider:
        print(divider)
    if not conv.messages:
        print("(conversation is empty)")
    saw_mask = False
    saw_no_code_mode = False
    known_secrets = known_secret_values(state.cfg)
    for msg in conv.messages:
        label = "you" if msg.role == "user" else msg.role
        shown, sensitive_masked, code_masked = display_text(
            msg.content or "(empty)",
            mask_output=state.mask_output,
            no_code_mode=state.no_code_mode,
            known_secrets=known_secrets,
        )
        saw_mask = saw_mask or sensitive_masked
        saw_no_code_mode = saw_no_code_mode or code_masked
        print(f"{label}>")
        print(shown)
        print()
    if divider:
        print(divider)
    print()
    if saw_mask:
        print_mask_notice(state)
    if saw_no_code_mode:
        print_no_code_mode_notice(state)


def one_line_preview(text: str, *, limit: int = 25) -> str:
    """Return a compact one-line preview with normalized whitespace."""
    collapsed = re.sub(r"\s+", " ", text.replace("\r", " ").replace("\n", " ")).strip()
    return truncate_for_display(collapsed, limit=limit) if collapsed else "(empty)"


def print_command_log(state: ReplState) -> None:
    """Print local slash-command and turn summaries for the current conversation."""
    entries = state.command_log or []
    if not entries:
        print("No local log entries for the current conversation yet.")
        return
    print("Conversation log:")
    for idx, entry in enumerate(entries, start=1):
        at = entry.get("at", "--:--:--")
        kind = entry.get("kind", "event")
        if kind == "slash":
            print(f"[{idx}] {at} slash  {entry.get('command', '')}")
            continue
        if kind == "turn":
            print(
                f"[{idx}] {at} turn   in={entry.get('input_tokens', 0)} out={entry.get('output_tokens', 0)} "
                f"req={entry.get('request_preview', '')} resp={entry.get('response_preview', '')}"
            )
            continue
        print(f"[{idx}] {at} {kind} {entry}")


def context_usage_summary(state: ReplState, pending_user_input: str | None = None) -> tuple[int, int]:
    """Estimate used and remaining context tokens."""
    conv = state.conv
    parts = [conv.system_prompt or ""]
    parts.extend(msg.content for msg in conv.messages)
    if pending_user_input:
        parts.append(pending_user_input)
    used = estimate_tokens("\n".join(part for part in parts if part))
    remaining = max(0, state.cfg.chat.context_window_tokens - used)
    return used, remaining


def humanize_report_key(key: str) -> str:
    """Render snake_case keys as terminal-friendly labels."""
    return key.replace("_", " ").title().replace("Id", "ID")


def render_markdown_config(data: object, *, title: str = "Configuration", level: int = 1) -> str:
    """Render a nested config object as Markdown headings and list items."""
    def append_scalar_list(lines: list[str], label: str, values: list[object]) -> None:
        if values:
            lines.append(f"- {label}:")
            for item in values:
                lines.append(f"  - {item}")
            return
        lines.append(f"- {label}: (none)")

    lines = [f"{'#' * level} {title}"]
    if isinstance(data, dict):
        scalar_items = [(key, value) for key, value in data.items() if not isinstance(value, dict)]
        nested_items = [(key, value) for key, value in data.items() if isinstance(value, dict)]
        if scalar_items:
            for key, value in scalar_items:
                label = humanize_report_key(str(key))
                if isinstance(value, list):
                    append_scalar_list(lines, label, value)
                else:
                    lines.append(f"- {label}: {value}")
        else:
            lines.append("- (none)")
        for key, value in nested_items:
            lines.append("")
            lines.append(render_markdown_config(value, title=humanize_report_key(str(key)), level=level + 1))
        return "\n".join(lines)
    if isinstance(data, list):
        if data:
            lines.extend(f"- {item}" for item in data)
        else:
            lines.append("- (none)")
        return "\n".join(lines)
    lines.append(f"- {data}")
    return "\n".join(lines)


def print_report_value(key: str, value: object) -> None:
    """Print a report field using a human-readable label."""
    print(f"  {humanize_report_key(key)}: {value}")


def print_turn_estimate(input_tokens: int, output_tokens: int, *, verbose: bool) -> None:
    """Print estimated token usage and cost for a single turn."""
    input_cost, output_cost, total_cost = estimate_token_cost(input_tokens, output_tokens)
    line = f"Estimate: in={input_tokens} out={output_tokens} cost={format_cost(total_cost)}"
    if verbose:
        line += f" (input={format_cost(input_cost)} output={format_cost(output_cost)})"
    print(line)


def print_expiration_warning(cfg: TuochatConfig) -> None:
    """Explain the active conversation expiration policy."""
    days = cfg.chat.conversation_expiration_days
    if days <= 0:
        return
    print(
        "Warning: conversation expiration is enabled for chats older than "
        f"{days} days. Set [chat].conversation_expiration_days = 0 in {cfg.config_file} to disable it."
    )


def print_verbose_context(state: ReplState, pending_user_input: str | None = None) -> None:
    """Print current context window usage."""
    used, remaining = context_usage_summary(state, pending_user_input)
    print("Verbose:")
    print_report_value("context_used", used)
    print_report_value("context_remaining", remaining)
    print_report_value("context_window", state.cfg.chat.context_window_tokens)


def print_timeout_limits(state: ReplState, *, reason: str | None = None) -> None:
    """Print all active timeout values for the current session."""
    summary = provider_timeout_summary(state)
    print("Timeouts:")
    if reason:
        print_report_value("reason", reason)
    for key, value in summary.items():
        print_report_value(key, f"{value:g}s")
    if state.timeout_override is not None:
        print_report_value("temporary_override", f"{state.timeout_override}s")


def print_chat_diagnostics(
    state: ReplState, *, header: str = "Diagnostics", provider: DuoProvider | None = None
) -> None:
    """Print provider diagnostics gathered during the last chat attempt."""
    target_provider = provider or state.provider
    if not isinstance(target_provider, DuoProvider):
        print(f"{header}: unavailable for the current provider")
        return
    diagnostics = target_provider.get_last_chat_diagnostics()
    if diagnostics is None:
        print(f"{header}: (none)")
        return
    print(f"{header}:")
    print_report_value("mode", diagnostics.mode)
    print_report_value("subscription_id", diagnostics.subscription_id or "(none)")
    print_report_value("request_id", diagnostics.request_id or "(none)")
    print_report_value("fallback_reason", diagnostics.fallback_reason or "(none)")
    print_report_value("poll_attempts", diagnostics.poll_attempts)
    print_report_value("poll_elapsed_seconds", f"{diagnostics.poll_elapsed_seconds:.1f}")
    print_report_value("partial_response_chars", len(diagnostics.partial_response))
    if diagnostics.partial_response:
        print("  partial_response:")
        print(diagnostics.partial_response)
    if diagnostics.raw_events:
        print("  raw_events:")
        for event in diagnostics.raw_events:
            print(f"    {event}")


def print_response_footer(state: ReplState, *, elapsed_seconds: float | None = None) -> None:
    """Print the compact post-response footer line when there is anything to say."""
    parts: list[str] = []
    if elapsed_seconds is not None and not state.quiet:
        parts.append(f"Elapsed: {elapsed_seconds:.2f}s")
    if state.cfg.chat.response_footer_warning_enabled:
        text = state.cfg.chat.response_footer_warning_text.strip()
        if text:
            parts.append(text)
    if parts:
        print(" | ".join(parts))


def print_status(state: ReplState) -> None:
    """Show current conversation status — ephemeral session state only."""
    conv = state.conv
    print(f"Conversation: {conv.id[:8]}  title={conv.title or '(auto/unset)'}")
    active_resource = getattr(state, "active_resource", None)
    effective_resource_id = active_resource.resource_id if active_resource is not None else conv.resource_id
    if active_resource is not None:
        resource_label = f"{active_resource.display_label} ({effective_resource_id})"
    else:
        resource_label = effective_resource_id or "(none)"
    print(f"Resource: {resource_label}")
    print(f"Model: {MODEL_LABELS.get(state.active_model, state.active_model)}")
    print(f"Duo model: {getattr(state, 'active_duo_model', None) or '(auto/default)'}")
    print(f"Classification: {classification_help_label(state.active_classification)}")
    print(f"Messages: {len(conv.messages)}")
    print(f"System prompt: {'set' if conv.system_prompt else 'unset'}")
    for idx, source in enumerate(state.active_system_prompt_sources or [], start=1):
        print(f"  source[{idx}]: {source}")
    print(f"Pending custom: {state.pending_custom_name or '(none)'}")
    pending_count = len(state.pending_attachment_messages or [])
    print(f"Pending attachments: {pending_count}")
    blind_mode = blind_mode_enabled(state)
    for idx, name in enumerate((state.pending_attachment_names or [])[:5], start=1):
        print(f"  {number_label(idx, blind_mode=blind_mode)} {name}")
    if pending_count > 5:
        print(f"  ... and {pending_count - 5} more")
    if state.last_include_path is not None:
        print(f"Last include: {state.last_include_path} ({state.last_include_size or 0} bytes)")
    else:
        print("Last include: (none)")


def print_about() -> None:
    """Print app identity, version, and license."""
    app_name = __title__.title()
    print(f"{app_name}  version {__version__}")
    print(__description__)
    print(f"License: {__license__}")
    print()
    print("Author: Matthew Dean Martin")
    print(
        "Tuochat is about 99% written by ChatGPT, Codex, Copilot, Gemini, Claude Code.\n"
        "As such, the copyrightability of the code is indeterminate and if the law says it is not\n"
        "copyrightable, then the code is Public Domain. Anything that is not public domain is MIT."
    )
    print()
    print("GitLab is a trademark of GitLab.")
    print("ChatGPT is a trademark of OpenAI.")
    print("Claude Code is a trademark of Anthropic.")
    print("Tuochat is not endorsed or related to GitLab, OpenAI, Anthropic, or any person or organization.")


def title_case_key(value: str) -> str:
    """Convert underscored config keys into title case labels."""
    return value.replace("_", " ").title()


def print_doctor_table(rows: list[tuple[str, str, str]]) -> None:
    """Render doctor details as aligned rows with descriptions."""
    key_width = max(len(key) for key, _, _ in rows)
    label_width = max(len(title_case_key(key)) for key, _, _ in rows)
    value_width = max(len(value) for _, value, _ in rows)
    for key, value, description in rows:
        label = title_case_key(key)
        print(f"  {key:<{key_width}}  {label:<{label_width}}  {value:<{value_width}}  {description}")


def print_doctor(cfg: TuochatConfig, *, streaming: bool) -> None:
    """Run basic local diagnostics including environment variables."""
    warnings = cfg.validate()
    from collections.abc import Iterable
    from typing import cast

    runtime_details = code_interpreter_runtime_details()
    installed_runtimes = ", ".join(cast(Iterable[str], runtime_details["installed_runtimes"])) or "(none)"
    rows = [
        ("host", cfg.gitlab.host or "(unset)", "Domain for API Calls"),
        ("token", "set" if cfg.gitlab.token else "missing", "Authentication Token Status"),
        (
            "config_file",
            f"{cfg.config_file} ({'exists' if cfg.config_file.is_file() else 'missing'})",
            "Path to the Active Config File",
        ),
        ("db_path", str(cfg.db_path), "Path to the Local Chat Database"),
        (
            "db_dir_writable",
            "yes" if cfg.db_path.parent.exists() or cfg.db_path.parent.parent.exists() else "unknown",
            "Whether the Database Directory Looks Writable",
        ),
        ("streaming", "on" if streaming else "off", "Streaming Response Mode"),
        (
            "code_interpreter_ready",
            "yes" if runtime_details["code_interpreter_ready"] else "no",
            "Whether Any Sandbox Runtime Is Installed",
        ),
        ("code_interpreter_runtimes", installed_runtimes, "Installed Sandbox Runtimes"),
        (
            "preferred_javascript_runtime",
            str(runtime_details["preferred_javascript_runtime"]),
            "Preferred JavaScript Sandbox Runtime",
        ),
        ("lua_runtime", str(runtime_details["lua_runtime"]), "Lua Sandbox Runtime"),
    ]
    print("Doctor:")
    print_doctor_table(rows)
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"  - {warning}")
    else:
        print("No obvious configuration issues found.")

    # Environment variables — merged from former /env command
    env_keys = [
        "TUOCHAT_GITLAB_HOST",
        "TUOCHAT_GITLAB_TOKEN",
        "TUOCHAT_GITLAB_TOKEN_TYPE",
        "TUOCHAT_CONFIG",
        "TUOCHAT_CONFIG_DIR",
        "TUOCHAT_DATA_DIR",
    ]
    print("Environment:")
    for key in env_keys:
        value = os.environ.get(key)
        if value is None:
            print(f"  {key}=(unset)")
            continue
        if "TOKEN" in key:
            shown = value[:8] + "***" if len(value) > 8 else "***"
        else:
            shown = value
        print(f"  {key}={shown}")
    proxy_keys_upper = ["HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY"]
    print("Proxy:")
    any_proxy = False
    for key in proxy_keys_upper:
        value = os.environ.get(key) or os.environ.get(key.lower())
        if value is not None:
            print(f"  {key}={value}")
            any_proxy = True
    if not any_proxy:
        print("  (no proxy variables set — direct connection assumed)")
    dotenv_path = Path.cwd() / ".env"
    print(f".env file: {dotenv_path if dotenv_path.is_file() else '(not found in cwd)'}")


def print_files(state: ReplState) -> None:
    """List include-able files and remember the numbered candidates."""
    candidates = list_include_candidates()
    state.last_candidates = candidates
    if not candidates:
        print("No include-able files found in the current working directory.")
        return
    print("Pick a file with /include or /attach N:")
    blind_mode = blind_mode_enabled(state)
    for idx, path in enumerate(candidates, start=1):
        print(f"{number_label(idx, blind_mode=blind_mode)} {path.relative_to(Path.cwd())}")


def text_size_lines(text: str) -> list[str]:
    """Return human-readable size lines for a text block."""
    encoded = text.encode("utf-8")
    return [
        f"tokens(est): {estimate_tokens(text)}",
        f"words: {word_count(text)}",
        f"chars: {len(text)}",
        f"kilobytes: {len(encoded) / 1024:.2f}",
    ]


def ascii_box(title: str, lines: list[str], *, width: int = 52) -> list[str]:
    """Render a simple stacked ASCII box."""
    inner_width = max(width - 4, 12)
    box = [
        "+" + "-" * (inner_width + 2) + "+",
        f"| {title[:inner_width].ljust(inner_width)} |",
    ]
    for line in lines:
        wrapped = [line[i : i + inner_width] for i in range(0, len(line), inner_width)] or [""]
        for segment in wrapped:
            box.append(f"| {segment.ljust(inner_width)} |")
    box.append("+" + "-" * (inner_width + 2) + "+")
    return box


def context_preview(text: str, *, limit: int = 25) -> str:
    """Return a compact one-line preview for context summaries."""
    normalized = re.sub(r"\s+", " ", text.strip())
    if not normalized:
        return "(empty)"
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit] + "..."


def context_stats_line(text: str, *, context_window: int) -> str:
    """Return compact stats for a context block."""
    encoded = text.encode("utf-8")
    tokens = estimate_tokens(text)
    percent = int(round((tokens / context_window) * 100)) if context_window > 0 else 0
    return (
        f"tokens {tokens} / words {word_count(text)} / chars {len(text)} / "
        f"kb {len(encoded) / 1024:.1f} / {percent} %"
    )


def context_box(title: str, text: str, *, context_window: int, width: int = CONTEXT_BOX_WIDTH) -> list[str]:
    """Render a compact context summary box."""
    return ascii_box(
        title, [context_preview(text, limit=75), context_stats_line(text, context_window=context_window)], width=width
    )


def remaining_context_box(*, used_tokens: int, remaining_tokens: int, context_window: int) -> list[str]:
    """Render a compact summary of the estimated remaining context window."""
    percent_left = int(round((remaining_tokens / context_window) * 100)) if context_window > 0 else 0
    return ascii_box(
        "Context Remaining",
        [
            "Estimated remaining context...",
            f"tokens {remaining_tokens} left / used {used_tokens} / window {context_window} / {percent_left} % left",
        ],
        width=CONTEXT_BOX_WIDTH,
    )


def print_context(state: ReplState) -> None:
    """Show a compact ASCII summary of the current conversation context."""
    conv = state.conv
    combined_parts = [conv.system_prompt or ""]
    combined_parts.extend(msg.content for msg in conv.messages if msg.content)
    combined = "\n".join(part for part in combined_parts if part)
    context_window = state.cfg.chat.context_window_tokens
    encoded = combined.encode("utf-8")
    tokens = estimate_tokens(combined)
    words = word_count(combined)
    chars = len(combined)
    kb = len(encoded) / 1024
    mode = "tokens" if blind_mode_enabled(state) else "all"
    if getattr(state, "context_view_mode", None):
        mode = str(state.context_view_mode)
    if mode == "kb":
        print(f"Context kb: {kb:.2f}")
        return
    if mode == "chars":
        print(f"Context chars: {chars}")
        return
    if mode == "words":
        print(f"Context words: {words}")
        return
    if mode == "tokens":
        if getattr(state, "context_view_mode", None) == "tokens":
            print(f"Context tokens: {tokens}")
            return
    from tuochat.workspace_memory import load_pinned_sections

    personalization = extract_personalization_from_conversation(conv)
    loaded_skills = extract_loaded_skills(conv)
    used_templates = extract_used_templates(conv)
    pinned_sections = load_pinned_sections()
    used_tokens, remaining_tokens = context_usage_summary(state)
    if blind_mode_enabled(state):
        print("Context:")
        print("Server System Prompt (invisible): set by the GitLab Duo service")
        if conv.system_prompt:
            print(f"Local System Prompt: {context_preview(conv.system_prompt, limit=100)}")
            print(
                f"  tokens {estimate_tokens(conv.system_prompt)} / words {word_count(conv.system_prompt)} / chars {len(conv.system_prompt)}"
            )
        else:
            print("Local System Prompt: (unset)")
        if personalization:
            print(f"Personalization: {context_preview(personalization, limit=100)}")
            print(
                f"  tokens {estimate_tokens(personalization)} / words {word_count(personalization)} / chars {len(personalization)}"
            )
        for label, content in pinned_sections:
            print(f"Pinned: {label}: {context_preview(content, limit=100)}")
            print(f"  tokens {estimate_tokens(content)} / words {word_count(content)} / chars {len(content)}")
        if loaded_skills:
            for label, skill_content in loaded_skills:
                print(f"Skill: {label}")
                print(f"  {context_preview(skill_content, limit=100)}")
                print(
                    f"  tokens {estimate_tokens(skill_content)} / words {word_count(skill_content)} / chars {len(skill_content)}"
                )
        if used_templates:
            for label, template_content, _metadata in used_templates:
                print(f"Template: {label}")
                print(f"  {context_preview(template_content, limit=100)}")
                print(
                    f"  tokens {estimate_tokens(template_content)} / words {word_count(template_content)} / chars {len(template_content)}"
                )
        prompt_index = 0
        response_index = 0
        skip_first_user = personalization is not None
        for msg in conv.messages:
            if msg.role == "user":
                if skip_first_user:
                    skip_first_user = False
                    continue
                if extract_loaded_skill_message(msg) is not None:
                    continue
                prompt_index += 1
                title = f"Prompt #{prompt_index}"
                metadata = extract_template_message_metadata(msg)
                if metadata:
                    title += f" (Template: {metadata.get('name') or metadata.get('label') or 'unnamed'})"
            else:
                response_index += 1
                title = f"Response #{response_index}"
            content = msg.content or ""
            print(f"{title}: {context_preview(content, limit=100)}")
            print(f"  tokens {estimate_tokens(content)} / words {word_count(content)} / chars {len(content)}")
        pending_attachment_names = getattr(state, "pending_attachment_names", []) or []
        if pending_attachment_names:
            print("Pending Attachments:")
            for idx, name in enumerate(pending_attachment_names, start=1):
                print(f"  [{idx}] {name}")
        print(f"Totals: tokens {tokens} / words {words} / chars {chars} / kb {kb:.2f}")
        print(f"Context window: {context_window}")
        print(f"Context remaining: {remaining_tokens}")
        return

    print("Context:")

    sections: list[list[str]] = []
    sections.append(
        ascii_box(
            "Server System Prompt (invisible)",
            ["Set by the GitLab Duo service — not visible or editable here"],
            width=CONTEXT_BOX_WIDTH,
        )
    )
    if conv.system_prompt:
        sections.append(context_box("Local System Prompt", conv.system_prompt, context_window=context_window))
    if personalization:
        sections.append(context_box("Personalization", personalization, context_window=context_window))
    for label, content in pinned_sections:
        sections.append(context_box(f"Pinned: {label}", content, context_window=context_window))
    for label, skill_content in loaded_skills:
        sections.append(context_box(f"Skill: {label}", skill_content, context_window=context_window))
    for label, template_content, _metadata in used_templates:
        sections.append(context_box(f"Template: {label}", template_content, context_window=context_window))
    prompt_index = 0
    response_index = 0
    skip_first_user = personalization is not None
    for msg in conv.messages:
        if msg.role == "user":
            if skip_first_user:
                skip_first_user = False
                continue
            if extract_loaded_skill_message(msg) is not None:
                continue
            prompt_index += 1
            title = f"Prompt #{prompt_index}"
            metadata = extract_template_message_metadata(msg)
            if metadata:
                title += f" (Template: {metadata.get('name') or metadata.get('label') or 'unnamed'})"
        else:
            response_index += 1
            title = f"Response #{response_index}"
        sections.append(context_box(title, msg.content or "", context_window=context_window))

    pending_attachment_names = getattr(state, "pending_attachment_names", []) or []
    if pending_attachment_names:
        sections.append(
            ascii_box(
                "Pending Attachments",
                [f"[{idx}] {name}" for idx, name in enumerate(pending_attachment_names, start=1)],
                width=CONTEXT_BOX_WIDTH,
            )
        )

    if not sections:
        sections.append(
            ascii_box(
                "Conversation", ["(empty)", "tokens 0 / words 0 / chars 0 / kb 0.0 / 0 %"], width=CONTEXT_BOX_WIDTH
            )
        )

    sections.append(
        remaining_context_box(
            used_tokens=used_tokens,
            remaining_tokens=remaining_tokens,
            context_window=context_window,
        )
    )

    for box in sections:
        for line in box:
            print(line)


def print_token_check(state: ReplState) -> None:
    """Estimate context size heuristically."""
    conv = state.conv
    parts = [conv.system_prompt or ""]
    parts.extend(msg.content for msg in conv.messages)
    combined = "\n".join(part for part in parts if part)
    print("Token estimate:")
    print_report_value("approx_tokens", estimate_tokens(combined))
    print_report_value("approx_chars", len(combined))
    print_report_value("context_window_tokens", state.cfg.chat.context_window_tokens)
    print_report_value("context_remaining", max(0, state.cfg.chat.context_window_tokens - estimate_tokens(combined)))
    if state.last_include_message:
        print_report_value("last_include_tokens", estimate_tokens(state.last_include_message))
    attachments = state.pending_attachment_messages or []
    if attachments:
        attachment_blob = "\n\n".join(attachments)
        attachment_tokens = estimate_tokens(attachment_blob)
        input_cost, _, _ = estimate_token_cost(attachment_tokens, 0)
        print_report_value("pending_attachments", len(attachments))
        print_report_value("pending_attachment_tokens", attachment_tokens)
        print_report_value("pending_attachment_chars", len(attachment_blob))
        print_report_value("pending_attachment_cost", format_cost(input_cost))


def print_chat_summary(conv: Conversation, state: ReplState | None = None) -> None:
    """Print a compact local summary for a finished conversation."""
    if not conv.messages:
        print("Chat summary: no messages were sent.")
        return

    user_messages = sum(1 for msg in conv.messages if msg.role == "user")
    assistant_messages = sum(1 for msg in conv.messages if msg.role == "assistant")
    total_chars = sum(len(msg.content) for msg in conv.messages)
    print("Chat summary:")
    print_report_value("id", conv.id)
    print_report_value("title", conv.title or "(auto/unset)")
    print_report_value("user_messages", user_messages)
    print_report_value("assistant_messages", assistant_messages)
    print_report_value("total_messages", len(conv.messages))
    print_report_value("approx_tokens", estimate_tokens(" ".join(msg.content for msg in conv.messages)))
    print_report_value("total_chars", total_chars)
    if state is not None and state.session_turns > 0:
        _, _, total_cost = estimate_token_cost(state.session_input_tokens, state.session_output_tokens)
        print("Session totals:")
        print_report_value("turns", state.session_turns)
        print_report_value("session_input_tokens", state.session_input_tokens)
        print_report_value("session_output_tokens", state.session_output_tokens)
        print_report_value("session_approx_cost", format_cost(total_cost))


def print_pending_attachments(state: ReplState) -> None:
    """Print pending attachment paths with numbered selections."""
    names = state.pending_attachment_names or []
    if not names:
        print("No pending attachments.")
        return
    print("Pending attachments:")
    for idx, name in enumerate(names, start=1):
        print(f"[{idx}] {name}")


def print_attachment_estimate(label: str, text: str, *, file_count: int | None = None) -> None:
    """Print size and approximate input cost for a generated attachment payload."""
    tokens = estimate_tokens(text)
    input_cost, _, _ = estimate_token_cost(tokens, 0)
    print(f"{label}:")
    if file_count is not None:
        print_report_value("files", file_count)
    print_report_value("tokens", tokens)
    print_report_value("words", word_count(text))
    print_report_value("chars", len(text))
    print_report_value("kilobytes", f"{len(text.encode('utf-8')) / 1024:.2f}")
    print_report_value("approx_input_cost", format_cost(input_cost))


def print_saved_conversation_files(state: ReplState) -> None:
    """Print the latest saved conversation artifact summary when available."""
    if state.last_saved_markdown_path is None:
        return
    classification_info = (
        f" [{classification_display_label(state.active_classification)}]" if state.active_classification else ""
    )
    print(
        f"Saved conversation files{classification_info}: "
        f"{state.last_saved_markdown_path} ({state.last_saved_extracted_count} extracted file(s))"
    )
    if getattr(state, "last_saved_virtual_file_notice", False):
        print("Named files written to central archive (write-here mode is off).")
        print("  To write files into the current directory next time:")
        print("    /write-here-mode on          (toggle for this session)")
        print("    tuochat chat --cwd .          (pin the working directory for headless use)")


__all__ = [
    "clear_screen",
    "announce_screen_transition",
    "number_label",
    "print_startup_banner",
    "print_session_intro",
    "print_system_prompt_sources",
    "print_mask_notice",
    "print_no_code_mode_notice",
    "print_conversation_transcript",
    "print_masked_conversation_transcript",
    "one_line_preview",
    "print_command_log",
    "context_usage_summary",
    "humanize_report_key",
    "render_markdown_config",
    "print_report_value",
    "print_turn_estimate",
    "print_expiration_warning",
    "print_verbose_context",
    "print_timeout_limits",
    "print_chat_diagnostics",
    "print_response_footer",
    "print_status",
    "print_about",
    "title_case_key",
    "print_doctor_table",
    "print_doctor",
    "print_files",
    "text_size_lines",
    "ascii_box",
    "context_preview",
    "context_stats_line",
    "context_box",
    "remaining_context_box",
    "print_context",
    "print_token_check",
    "print_chat_summary",
    "print_pending_attachments",
    "print_attachment_estimate",
    "print_saved_conversation_files",
]
