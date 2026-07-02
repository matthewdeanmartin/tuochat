"""Session state and chat-turn helpers for the interactive CLI."""

# ruff: noqa: E402,F401,F403,F811,F821,B010
from __future__ import annotations

import logging
import os
import signal
import subprocess  # nosec: B404
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from tuochat.cli.models import ReplState
from tuochat.cli.prompts import prompt_input
from tuochat.cli.rendering import (
    announce_screen_transition,
    clear_screen,
    number_label,
    one_line_preview,
    print_mask_notice,
    print_masked_conversation_transcript,
    print_no_code_mode_notice,
    print_report_value,
    print_system_prompt_sources,
)
from tuochat.cli.setup import prompt_classification
from tuochat.config import TuochatConfig
from tuochat.constants import MODEL_LABELS, NO_CODE_MODE_REPLACEMENT, classification_help_label
from tuochat.context.attachments import consume_pending_attachments
from tuochat.context.composer import (
    build_personalization_block,
    compose_system_prompt,
    load_custom_instruction_sections,
)
from tuochat.context.validation import validate_user_request as context_validate_user_request
from tuochat.estimation import estimate_tokens
from tuochat.models import Conversation, ConversationSearchResult, Message
from tuochat.observability import ObservabilityRow, utc_now_iso
from tuochat.persistence import ConversationStore, NullConversationStore
from tuochat.persistence.archive import sync_conversation_artifacts as archive_sync_conversation_artifacts
from tuochat.provider.duo import DuoProvider
from tuochat.provider.eliza import ElizaProvider
from tuochat.provider.openrouter import OpenRouterAPIError, OpenRouterProvider, OpenRouterUnavailableError
from tuochat.security.masking import display_text, known_secret_values
from tuochat.serialization import json_dumps, json_loads

logger = logging.getLogger("tuochat.cli")


def clear_screen_adapter():
    return clear_screen()


def announce_screen_transition_adapter(label: str):
    return announce_screen_transition(label)


def print_turn_estimate(input_tokens: int, output_tokens: int, *, verbose: bool):
    from tuochat.cli.rendering import print_turn_estimate as rendering_print_turn_estimate

    return rendering_print_turn_estimate(input_tokens, output_tokens, verbose=verbose)


def print_verbose_context(state: ReplState, pending_user_input: str | None = None):
    from tuochat.cli.rendering import print_verbose_context as rendering_print_verbose_context

    return rendering_print_verbose_context(state, pending_user_input)


def print_timeout_limits(state: ReplState, *, reason: str | None = None):
    from tuochat.cli.rendering import print_timeout_limits as rendering_print_timeout_limits

    return rendering_print_timeout_limits(state, reason=reason)


def print_chat_diagnostics(state: ReplState, *, header: str = "Diagnostics", provider: Any | None = None):
    from tuochat.cli.rendering import print_chat_diagnostics as rendering_print_chat_diagnostics

    return rendering_print_chat_diagnostics(state, header=header, provider=provider)


def print_response_footer(state: ReplState, *, elapsed_seconds: float | None = None):
    from tuochat.cli.rendering import print_response_footer as rendering_print_response_footer

    return rendering_print_response_footer(state, elapsed_seconds=elapsed_seconds)


def print_chat_summary(conv: Conversation, state: ReplState | None = None):
    from tuochat.cli.rendering import print_chat_summary as rendering_print_chat_summary

    return rendering_print_chat_summary(conv, state)


def print_saved_conversation_files(state: ReplState):
    from tuochat.cli.rendering import print_saved_conversation_files as rendering_print_saved_conversation_files

    return rendering_print_saved_conversation_files(state)


COMMAND_LOG_MAX = 250

SERVER_CONTEXT_CATEGORIES = {"FILE", "SNIPPET", "ISSUE", "MERGE_REQUEST", "DEPENDENCY", "TERMINAL", "LOCAL_GIT"}


def blind_mode_enabled(obj: ReplState | TuochatConfig) -> bool:
    """Return whether blind mode is enabled on a config or state object."""
    if isinstance(obj, ReplState):
        return obj.blind_mode
    return bool(getattr(getattr(obj, "chat", None), "blind", getattr(obj, "blind_mode", False)))


def python_version_string() -> str:
    """Return the active Python runtime version."""
    return sys.version.split()[0]


def local_now() -> datetime:
    """Return the current local datetime."""
    return datetime.now().astimezone()


def sync_conversation_artifacts(
    cfg: TuochatConfig,
    conv: Conversation,
    *,
    classification: str | None = None,
    approve_write: Any | None = None,
) -> tuple[Path | None, Path | None, list[Path]]:
    """Persist a conversation as markdown plus extracted fenced files."""
    if no_write_enabled(cfg):
        return None, None, []
    if approve_write is None and approve_writes_enabled(cfg) and write_here_mode_enabled(cfg):
        approve_write = prompt_write_here_approval
    return archive_sync_conversation_artifacts(cfg, conv, classification=classification, approve_write=approve_write)


def no_stream_mode_enabled(cfg: TuochatConfig) -> bool:
    """Return whether non-streaming mode has been explicitly re-enabled."""
    return bool(getattr(getattr(cfg, "chat", None), "enable_no_stream", False))


def no_stream_hold_message() -> str:
    """Explain why non-streaming mode is currently feature-flagged off."""
    return (
        "Non-streaming mode is disabled unless chat.enable_no_stream = true. "
        "There may be a real 5000-token truncation bug here, or it may be a rarer backend behavior we do not "
        "fully understand yet, but it is not worth the risk right now."
    )


def resolve_streaming_enabled(cfg: TuochatConfig, *, no_stream_requested: bool = False) -> bool:
    """Return the safe streaming mode for the current config and CLI request."""
    # We do not know yet whether the 5000-token truncation on the polling path is a real backend bug
    # or a rare edge case in how we exercise it, but either way we should keep the non-streaming path
    # behind an explicit feature flag until it is understood well enough to trust.
    if no_stream_requested and no_stream_mode_enabled(cfg):
        return False
    if no_stream_requested:
        logger.warning(no_stream_hold_message())
        return True
    if not cfg.chat.streaming and not no_stream_mode_enabled(cfg):
        logger.warning(no_stream_hold_message())
        return True
    return cfg.chat.streaming


def open_path(path: Path) -> tuple[bool, str]:
    """Open a file or directory in the platform default handler."""
    try:
        resolved = path.resolve()
        if sys.platform == "win32":
            os.startfile(str(resolved))  # type: ignore[attr-defined]
            return True, f"opened {path}"
        opener = ["open", str(resolved)] if sys.platform == "darwin" else ["xdg-open", str(resolved)]
        result = subprocess.run(  # nosec: B603
            opener,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode == 0:
            return True, f"opened {path}"
    except Exception as exc:
        return False, str(exc)
    return False, f"unable to open {path}"


def emit_long_request_notification() -> None:
    """Emit a one-shot audible notification for a long-running request."""
    try:
        if sys.platform == "win32":
            import winsound  # noqa: PLC0415

            winsound.MessageBeep()
        else:
            print("\a", end="", flush=True)
    except Exception:
        print("\a", end="", flush=True)


def start_long_request_notifier(
    cfg: TuochatConfig,
    *,
    should_warn: Callable[[], bool] | None = None,
) -> tuple[threading.Event, threading.Thread | None]:
    """Start a timer that emits a notification if a request runs too long."""
    stop_event = threading.Event()
    if not cfg.notifications.long_request_bell_enabled:
        return stop_event, None

    delay = max(1, cfg.notifications.long_request_bell_seconds)
    should_warn = should_warn or (lambda: True)

    def notify_later() -> None:
        if not stop_event.wait(delay) and should_warn():
            emit_long_request_notification()
            print(
                f"\n[Still waiting after {delay} seconds...]",
                file=sys.stderr,
                flush=True,
            )

    thread = threading.Thread(target=notify_later, name="long-request-notifier", daemon=True)
    thread.start()
    return stop_event, thread


def start_dot_timer(enabled: bool) -> tuple[threading.Event, threading.Thread | None]:
    """Print one dot per second until the first response text arrives."""
    stop_event = threading.Event()
    if not enabled:
        return stop_event, None

    def emit_dots() -> None:
        while not stop_event.wait(1.0):
            print(".", end="", flush=True)

    thread = threading.Thread(target=emit_dots, name="dot-timer", daemon=True)
    thread.start()
    return stop_event, thread


def write_here_mode_enabled(cfg: TuochatConfig) -> bool:
    """Return whether write-here mode is enabled on a config-like object."""
    return bool(getattr(getattr(cfg, "chat", None), "write_here_mode", False))


def approve_writes_enabled(cfg: TuochatConfig) -> bool:
    """Return whether write-here mode requires approval before cwd writes."""
    return bool(getattr(getattr(cfg, "chat", None), "approve_writes", False))


def cwd_is_filesystem_root() -> bool:
    """Return whether the current working directory is a filesystem root."""
    cwd = Path.cwd().resolve()
    return cwd.parent == cwd


def apply_git_repo_write_here_default(cfg: TuochatConfig) -> bool:
    """Enable write-here mode automatically when running inside a git repo.

    Only activates when write-here mode is still at its config default (off)
    and the session is not in no-write mode.  The cwd must not be a filesystem
    root.  Returns True if write-here mode was enabled by this call.
    """
    from tuochat.context.composer import inspect_git_repository  # noqa: PLC0415

    if write_here_mode_enabled(cfg):
        return False
    if bool(getattr(getattr(cfg, "chat", None), "no_write", False)):
        return False
    if cwd_is_filesystem_root():
        return False
    repo_root, _ = inspect_git_repository()
    if repo_root is None:
        return False
    cfg.chat.write_here_mode = True
    return True


def set_session_write_here_mode(cfg: TuochatConfig, enabled: bool) -> None:
    """Store the session-only write-here toggle on the config object."""
    cfg.chat.write_here_mode = enabled


def set_session_approve_writes(cfg: TuochatConfig, enabled: bool) -> None:
    """Store the session-only approve-writes toggle on the config object."""
    cfg.chat.approve_writes = enabled


def print_write_here_help(cfg: TuochatConfig, *, blind_mode: bool = False) -> None:
    """Explain the /write-here-mode toggle and show the current setting."""
    current = "on" if write_here_mode_enabled(cfg) else "off"
    print(f"Current /write-here-mode setting: {current}")
    print(f"{number_label(1, blind_mode=blind_mode)} on")
    print("    Write named generated files into the current working directory.")
    print("    Conversation transcripts and unnamed extracted files stay under .tuochat\\conversations.")
    print(f"{number_label(2, blind_mode=blind_mode)} off")
    print("    Keep generated files with the conversation archive instead of the cwd.")
    if cwd_is_filesystem_root():
        print("    Unavailable here because the current working directory is a filesystem root.")


def print_approve_writes_help(cfg: TuochatConfig, *, blind_mode: bool = False) -> None:
    """Explain the /approve-writes toggle and show the current setting."""
    current = "on" if approve_writes_enabled(cfg) else "off"
    print(f"Current /approve-writes setting: {current}")
    print(f"{number_label(1, blind_mode=blind_mode)} on")
    print("    Ask before /write-here-mode writes a named file into the current working directory.")
    print(f"{number_label(2, blind_mode=blind_mode)} off")
    print("    Allow /write-here-mode to write named files without per-file confirmation.")


def toggle_write_here_mode(state: ReplState, enabled: bool) -> None:
    """Toggle cwd writes for named generated files for the active REPL session."""
    previous = write_here_mode_enabled(state.cfg)
    if previous == enabled:
        print(f"Write-here mode is already {'enabled' if enabled else 'disabled'}.")
        return
    if enabled and cwd_is_filesystem_root():
        print(
            "Write-here mode cannot be enabled when the current working directory is a filesystem root.",
            file=sys.stderr,
        )
        return
    if enabled:
        from tuochat.git_info import get_git_status  # noqa: E402

        git = state.git_status or get_git_status()
        state.git_status = git
        if git is not None and git.dirty:
            if getattr(state.cfg.chat, "refuse_writes_on_dirty_tree", False):
                print(
                    f"Write-here mode blocked: git tree is dirty ({git.summary()}).",
                    file=sys.stderr,
                )
                print("Clean or stash your changes, or disable chat.refuse_writes_on_dirty_tree in config.")
                return
            print(f"Warning: git tree is dirty — {git.summary()}")
            print("This mixes your manual edits with LLM-generated files in the same working tree.")
            print("Consider stashing first, or enable chat.refuse_writes_on_dirty_tree to block this.")
    set_session_write_here_mode(state.cfg, enabled)
    if enabled:
        print("Write-here mode enabled for this session.")
        print("Named generated files will be written into the current working directory.")
        print(
            "Conversation transcripts and other conversation artifacts will be written under .tuochat\\conversations."
        )
        return
    print("Write-here mode disabled for this session.")
    print("Generated files will stay with the conversation archive again.")


def toggle_approve_writes(state: ReplState, enabled: bool) -> None:
    """Toggle per-file approval for cwd writes in write-here mode."""
    previous = approve_writes_enabled(state.cfg)
    if previous == enabled:
        print(f"Approve-writes is already {'enabled' if enabled else 'disabled'}.")
        return
    set_session_approve_writes(state.cfg, enabled)
    if enabled:
        print("Approve-writes enabled for this session.")
        print("Write-here mode will ask before writing each named file into the current working directory.")
        return
    print("Approve-writes disabled for this session.")
    print("Write-here mode will write named files without extra prompts.")


def prompt_write_here_approval(path: Path) -> bool:
    """Ask whether a named generated file may be written into the current working directory."""
    choice = prompt_input(f"Write named file into cwd: {path.name}? [y/N] ").strip().lower()
    return choice in {"y", "yes"}


def record_log_event(state: ReplState, kind: str, **details: object) -> None:
    """Append a local log entry for the current conversation (capped at 250)."""
    if state.command_log is None:
        state.command_log = []
    entry: dict[str, object] = {"at": local_now().strftime("%H:%M:%S"), "kind": kind}
    entry.update(details)
    state.command_log.append(entry)
    if len(state.command_log) > COMMAND_LOG_MAX:
        state.command_log = state.command_log[-COMMAND_LOG_MAX:]


def provider_timeout_summary(state: ReplState) -> dict[str, float]:
    """Return the current provider timeout settings."""
    if isinstance(state.provider, DuoProvider):
        return state.provider.timeout_summary()
    return {
        "request_timeout": float(state.cfg.chat.timeout),
        "websocket_welcome_timeout": float(state.cfg.chat.websocket_welcome_timeout),
        "websocket_subscription_timeout": float(state.cfg.chat.websocket_subscription_timeout),
    }


def is_timeout_error(exc: BaseException) -> bool:
    """Return True when an exception appears timeout-related."""
    message = str(exc).casefold()
    return "timed out" in message or "timeout" in message


def build_openrouter_provider(cfg: TuochatConfig, *, model_override: str | None = None) -> OpenRouterProvider:
    """Construct an OpenRouter provider from the active config."""
    if not cfg.openrouter.api_key:
        raise OpenRouterAPIError(
            "OpenRouter API key is not configured. Set OPENROUTER_API_KEY or run `tuochat openrouter login`."
        )
    models: list[str]
    if model_override:
        models = [model_override]
    else:
        models = cfg.openrouter.effective_models()
    if not models:
        raise OpenRouterAPIError("No OpenRouter model configured. Set OPENROUTER_MODEL or OPENROUTER_MODELS.")
    return OpenRouterProvider(
        api_key=cfg.openrouter.api_key,
        models=models,
        rotate_models=cfg.openrouter.rotate_models and model_override is None,
        base_url=cfg.openrouter.base_url,
        http_referer=cfg.openrouter.http_referer or None,
        x_title=cfg.openrouter.x_title or None,
        timeout=cfg.chat.timeout,
    )


def conversation_history_for_openrouter(state: ReplState) -> list[dict[str, str]]:
    """Render the saved conversation messages into OpenAI-style chat turns."""
    history: list[dict[str, str]] = []
    for message in state.conv.messages:
        role = message.role
        content = message.content or ""
        if role in {"user", "assistant", "system"} and content:
            history.append({"role": role, "content": content})
    return history


def build_provider(cfg: TuochatConfig, *, timeout_override: int | None = None) -> DuoProvider:
    """Construct a Duo provider from config."""
    effective_timeout = timeout_override if timeout_override is not None else cfg.chat.timeout
    return DuoProvider(
        host=cfg.gitlab.host,
        token=cfg.gitlab.token,
        token_type=cfg.gitlab.token_type,
        platform_origin=cfg.chat.platform_origin,
        user_agent=getattr(cfg.gitlab, "user_agent", None),
        timeout=effective_timeout,
        websocket_welcome_timeout=cfg.chat.websocket_welcome_timeout,
        websocket_subscription_timeout=cfg.chat.websocket_subscription_timeout,
    )


def persist_chat_preferences(state: ReplState) -> None:
    """Persist selected chat preferences to the config file when possible."""
    from tuochat.config import save_config

    if no_write_enabled(state.cfg):
        return
    required_root_attrs = (
        "setup_version",
        "gitlab",
        "notifications",
        "personalization",
        "classification",
        "warn_words",
        "config_dir",
        "log_dir",
    )
    required_chat_attrs = (
        "platform_origin",
        "default_resource_id",
        "timeout",
        "websocket_welcome_timeout",
        "websocket_subscription_timeout",
        "streaming",
        "mask_output",
        "dot_timer",
        "quiet",
        "no_banner",
        "blind",
        "response_footer_warning_enabled",
        "response_footer_warning_text",
        "generated_file_header_enabled",
        "generated_file_header_text",
        "max_request_chars",
        "context_window_tokens",
        "conversation_expiration_days",
        "no_write",
        "tutorial_completed",
        "safety_check_extension_for_executable_files",
    )
    if not all(hasattr(state.cfg, attr) for attr in required_root_attrs):
        return
    if not all(hasattr(state.cfg.chat, attr) for attr in required_chat_attrs):
        return
    state.cfg.chat.dot_timer = state.dot_timer_enabled
    state.cfg.chat.quiet = state.quiet
    state.cfg.chat.no_banner = state.no_banner
    state.cfg.chat.blind = state.blind_mode
    save_config(state.cfg, state.config_path)


def build_store(cfg: TuochatConfig) -> ConversationStore | NullConversationStore:
    """Build the appropriate conversation store for the current config."""
    if no_write_enabled(cfg):
        return NullConversationStore(cfg.db_path)
    return ConversationStore(cfg.db_path)


def no_write_enabled(cfg: TuochatConfig) -> bool:
    """Return whether local writes are disabled in the config object."""
    return bool(getattr(getattr(cfg, "chat", None), "no_write", False))


def print_no_write_help(current_enabled: bool, *, blind_mode: bool = False) -> None:
    """Explain the /no-write toggle and show the current setting."""
    current = "on" if current_enabled else "off"
    print(f"Current /no-write setting: {current}")
    print(f"{number_label(1, blind_mode=blind_mode)} on")
    print("    Disable local database writes, filesystem writes, and file logging.")
    print("    Use this when tuochat should behave like it is on a read-only filesystem.")
    print(f"{number_label(2, blind_mode=blind_mode)} off")
    print("    Re-enable normal local persistence: sqlite history, conversation files, and file logging.")
    print("    This is the default behavior.")


def toggle_blind_mode(state: ReplState, enabled: bool) -> None:
    """Toggle blind-friendly mode for the active session."""
    state.blind_mode = enabled
    state.no_banner = enabled or state.no_banner
    state.cfg.chat.blind = enabled
    if enabled:
        state.cfg.chat.no_banner = True
        print("Blind mode enabled for this session.")
        print("Help now defaults to /help-menu, screen clears become announcements, and context output is simplified.")
    else:
        print("Blind mode disabled for this session.")
    persist_chat_preferences(state)


def toggle_no_write(state: ReplState, enabled: bool) -> None:
    """Toggle local-write behavior for the active REPL session."""
    previous = no_write_enabled(state.cfg)
    if previous == enabled:
        print(f"Local writes are already {'disabled' if enabled else 'enabled'}.")
        return

    old_store = state.store
    state.cfg.chat.no_write = enabled
    state.local_writes_enabled = not enabled
    state.store = build_store(state.cfg)
    old_store.close()

    if not enabled and state.conv.messages:
        state.store.save_conversation(state.conv)
        for msg in state.conv.messages:
            state.store.save_message(msg)

    if enabled:
        state.last_saved_markdown_path = None
        state.last_saved_extracted_count = 0
        state.last_saved_virtual_file_notice = False
        print("Local writes disabled for this session.")
        print("Tuochat will stop writing sqlite history, conversation files, and file logs.")
        print("This setting is not saved because saving it would require writing to disk.")
        return

    print("Local writes enabled for this session.")
    print("Tuochat will write sqlite history, conversation files, and file logs again.")
    print("Restart the app to restore file logging to disk.")


def validate_user_request(state: ReplState, user_input: str, outbound_input: str) -> bool:
    """Validate a request before sending; delegates to context.validation."""
    return context_validate_user_request(
        user_input,
        outbound_input,
        state.cfg.chat.max_request_chars,
        state.cfg,
        prompt_input,
    )


def build_resumed_context_block(conv: Conversation) -> str:
    """Build a conversation history prefix for resumed sessions.

    Injects the saved transcript so the LLM has the correct prior context
    instead of whatever was active in its server-side session.
    """
    lines = [
        "The following is the prior conversation history for context.",
        "Please treat this as the conversation so far and continue from it.",
        "",
    ]
    for msg in conv.messages:
        role_label = msg.role.upper()
        lines.append(f"[{role_label}]: {msg.content}")
        lines.append("")
    lines.append("--- End of prior context ---")
    lines.append("")
    return "\n".join(lines)


def build_outbound_input(state: ReplState, user_input: str) -> str:
    """Attach any queued files to a request without mutating session state."""
    personalization = ""
    if not state.conv.messages:
        personalization = build_personalization_block(state.cfg)

    resume_context = ""
    if state.resumed_context_pending:
        resume_context = build_resumed_context_block(state.conv)
        state.resumed_context_pending = False
        logger.debug("build_outbound_input: injecting resumed context (%d messages)", len(state.conv.messages))

    attachments = state.pending_attachment_messages or []
    names = state.pending_attachment_names or []
    if not attachments:
        return personalization + resume_context + user_input

    header = "These files are related to the upcoming request:\n"
    if names:
        header += "\n".join(f"- {name}" for name in names)
        header += "\n\n"
    combined = (
        personalization + resume_context + header + "\n\n".join(attachments) + "\n\nUpcoming request:\n" + user_input
    )
    return combined


def handle_server_context_command(command: str, argument: str, state: ReplState) -> None:
    """Handle /server-* commands for managing additionalContext sent to the Duo API.

    These mirror the AIContextEndpoints from the GitLab LSP. Items in
    state.server_context are injected into every aiAction call as
    additionalContext until cleared or removed.

    Categories: FILE, SNIPPET, ISSUE, MERGE_REQUEST, DEPENDENCY, TERMINAL, LOCAL_GIT
    """
    if command == "/server-current-items":
        if not state.server_context:
            print("No server context items.")
        else:
            for idx, item in enumerate(state.server_context):
                print(f"[{idx}] {item['category']} — {item['name']}")
                if item.get("content"):
                    preview = item["content"][:80].replace("\n", " ")
                    print(f"     {preview}{'...' if len(item['content']) > 80 else ''}")
        return

    if command == "/server-clear":
        count = len(state.server_context)
        state.server_context = []
        print(f"Cleared {count} server context item(s).")
        return

    if command == "/server-query":
        # Search by name substring
        query = argument.strip().lower()
        if not query:
            print("Usage: /server-query <name-substring>", file=sys.stderr)
            return
        matches = [item for item in state.server_context if query in item["name"].lower()]
        if not matches:
            print(f"No context items matching '{argument}'.")
        else:
            for item in matches:
                print(f"  {item['category']} — {item['name']}")
        return

    if command == "/server-retrieve":
        # Alias for /server-current-items
        if not state.server_context:
            print("No server context items.")
        else:
            for idx, item in enumerate(state.server_context):
                print(f"[{idx}] {item['category']} — {item['name']}")
        return

    if command == "/server-get-item-content":
        # Show full content for a named item
        name = argument.strip()
        if not name:
            print("Usage: /server-get-item-content <name>", file=sys.stderr)
            return
        matches = [item for item in state.server_context if item["name"] == name]
        if not matches:
            print(f"No context item named '{name}'.", file=sys.stderr)
        else:
            print(matches[0]["content"])
        return

    if command == "/server-add":
        # Usage: /server-add <CATEGORY> <name> [content...]
        # Content may be a file path (read it) or inline text
        parts = argument.split(maxsplit=2)
        if len(parts) < 2:
            print("Usage: /server-add <CATEGORY> <name> [content-or-filepath]", file=sys.stderr)
            print(f"Categories: {', '.join(sorted(SERVER_CONTEXT_CATEGORIES))}", file=sys.stderr)
            return
        category = parts[0].upper()
        if category not in SERVER_CONTEXT_CATEGORIES:
            print(
                f"Unknown category '{parts[0]}'. Valid: {', '.join(sorted(SERVER_CONTEXT_CATEGORIES))}",
                file=sys.stderr,
            )
            return
        name = parts[1]
        content_arg = parts[2] if len(parts) > 2 else ""
        # If content_arg looks like an existing file path, read it
        content = ""
        if content_arg:
            candidate = Path(content_arg).expanduser()
            if candidate.is_file():
                try:
                    content = candidate.read_text(encoding="utf-8", errors="replace")
                    print(f"Read {len(content)} chars from {candidate}")
                except OSError as exc:
                    print(f"Could not read file: {exc}", file=sys.stderr)
                    return
            else:
                content = content_arg
        # Replace existing item with the same name, or append
        for existing in state.server_context:
            if existing["name"] == name and existing["category"] == category:
                existing["content"] = content
                print(f"Updated {category} context item: {name}")
                return
        state.server_context.append({"category": category, "name": name, "content": content})
        print(f"Added {category} context item: {name} ({len(content)} chars)")
        return

    if command == "/server-remove":
        name = argument.strip()
        if not name:
            print("Usage: /server-remove <name>", file=sys.stderr)
            return
        before = len(state.server_context)
        state.server_context = [item for item in state.server_context if item["name"] != name]
        removed = before - len(state.server_context)
        if removed:
            print(f"Removed {removed} context item(s) named '{name}'.")
        else:
            print(f"No context item named '{name}'.", file=sys.stderr)
        return


def update_saved_conversation_artifacts(state: ReplState, md_path: Path, extracted: list[Path]) -> None:
    """Remember the latest saved conversation artifacts for end-of-conversation reporting."""
    state.last_saved_markdown_path = md_path
    state.last_saved_extracted_count = len(extracted)
    state.last_saved_virtual_file_notice = bool(extracted) and not write_here_mode_enabled(state.cfg)


def print_virtual_file_notice(state: ReplState) -> None:
    """Explain when fenced files were saved to the archive instead of the cwd."""
    if state.last_saved_virtual_file_notice:
        print("Named files written to central archive (write-here mode is off).")
        print("  To write files into the current directory next time:")
        print("    /write-here-mode on          (toggle for this session)")
        print("    tuochat chat --cwd .          (pin the working directory for headless use)")


def latest_assistant_message(conv: Conversation) -> str | None:
    """Return the most recent assistant message content."""
    for message in reversed(conv.messages):
        if message.role == "assistant" and message.content:
            return message.content
    return None


def copy_to_clipboard(text: str) -> tuple[bool, str]:
    """Copy text to the system clipboard using only stdlib facilities."""
    try:
        import tkinter  # noqa: PLC0415

        root = tkinter.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        root.destroy()
        return True, "clipboard updated with tkinter"
    except Exception as exc:
        logger.debug("tkinter clipboard failed: %s", exc)

    commands: list[list[str]]
    if sys.platform == "win32":
        commands = [["clip"]]
    elif sys.platform == "darwin":
        commands = [["pbcopy"]]
    else:
        commands = [["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]

    for command in commands:
        try:
            completed = subprocess.run(  # nosec:B404,B603
                command,
                input=text,
                text=True,
                capture_output=True,
                check=True,
            )
            if completed.returncode == 0:
                return True, f"clipboard updated with {' '.join(command)}"
        except (FileNotFoundError, subprocess.CalledProcessError, OSError):
            continue

    return False, "no supported clipboard mechanism was available"


def extract_template_message_metadata(message: Message) -> dict[str, object] | None:
    """Return parsed template metadata from a stored message when present."""
    if not message.extras_json:
        return None
    try:
        extras = json_loads(message.extras_json)
    except (TypeError, ValueError):
        return None
    template = extras.get("template")
    return template if isinstance(template, dict) else None


def reset_repl_state(state: ReplState, *, preserve_resource: bool = True, preserve_prompt: bool = True) -> None:
    """Start a new in-memory conversation for the current REPL session."""
    # Tell the Duo backend to clear its server-side conversation history so
    # the new local conversation isn't contaminated by the previous thread.
    if isinstance(state.provider, DuoProvider):
        state.provider.reset_conversation()

    old_conv = state.conv
    if old_conv.messages:
        print_chat_summary(old_conv)
        print(f"Conversation saved: {old_conv.id}")
        print_saved_conversation_files(state)

    extra_custom_paths = [state.pending_custom_path] if state.pending_custom_path is not None else []
    system_prompt, sources = compose_system_prompt(
        state.base_system_prompt if preserve_prompt else None,
        load_custom_instruction_sections(state.cfg, extra_paths=extra_custom_paths),
        include_agents=state.include_agents_file,
    )
    state.conv = Conversation(
        resource_id=state.base_resource_id if preserve_resource else None,
        system_prompt=system_prompt,
        cwd=str(Path.cwd()),
    )
    state.active_system_prompt_sources = sources
    state.last_user_input = None
    state.last_include_path = None
    state.last_include_hash = None
    state.last_include_size = None
    state.last_include_message = None
    state.pending_attachment_messages = []
    state.pending_attachment_names = []
    state.pending_template_metadata = None
    state.last_candidates = None
    state.command_log = []
    state.last_saved_markdown_path = None
    state.last_saved_extracted_count = 0
    state.last_saved_virtual_file_notice = False
    state.server_context = []
    # Reset classification for the new conversation
    state.active_classification = None
    if state.cfg.classification.enabled and state.cfg.classification.ask_per_conversation:
        chosen = prompt_classification(state.cfg, upcoming=True, default=state.last_classification)
        if chosen:
            state.active_classification = chosen
            state.last_classification = chosen
    print("\n\n")
    if state.blind_mode:
        announce_screen_transition("New conversation")
    else:
        print("=" * 24)
        print("New Conversation")
    print_system_prompt_sources(state)
    if state.active_classification:
        print(f"Classification: {classification_help_label(state.active_classification)}")
    if not state.blind_mode:
        print("=" * 24)
    print(f"Started new conversation: {state.conv.id[:8]}")
    print("\n")


def switch_to_conversation(state: ReplState, target: Conversation | ConversationSearchResult) -> None:
    """Swap the current REPL session onto a saved conversation."""
    conversation_id = target.conversation_id if isinstance(target, ConversationSearchResult) else target.id
    conv = state.store.get_conversation(conversation_id)
    if conv is None:
        raise ValueError(f"Conversation {conversation_id} not found")
    conv.messages = state.store.get_messages(conv.id)
    state.conv = conv
    state.base_system_prompt = conv.system_prompt
    state.base_resource_id = conv.resource_id
    state.last_user_input = next(
        (msg.content for msg in reversed(conv.messages) if msg.role == "user" and msg.content),
        None,
    )
    state.last_include_path = None
    state.last_include_hash = None
    state.last_include_size = None
    state.last_include_message = None
    state.pending_attachment_messages = []
    state.pending_attachment_names = []
    state.pending_template_metadata = None
    state.last_candidates = None
    state.command_log = []
    state.resume_candidates = None
    state.search_candidates = None
    state.resumed_context_pending = bool(conv.messages)
    conv_dir, md_path, extracted = sync_conversation_artifacts(
        state.cfg, conv, classification=state.active_classification
    )
    if md_path is not None:
        update_saved_conversation_artifacts(state, md_path, extracted)
    if blind_mode_enabled(state):
        announce_screen_transition("New conversation")
    else:
        clear_screen()
    print_masked_conversation_transcript(state)
    if conv_dir is not None and md_path is not None:
        print(f"Archive dir: {conv_dir}")
        print(f"Markdown: {md_path}")
        print(f"Extracted files: {len(extracted)}")
    if state.resumed_context_pending:
        print()
        print("[Resumed conversation — prior context will be replayed to the LLM on your next message.]")
    print()


def stream_safe_display_length(
    full_response: str,
    *,
    mask_output: bool,
    no_code_mode: bool,
    known_secrets: list[str] | None = None,
) -> str:
    """Return the stream-safe display text for the current partial response."""
    safe_source = full_response
    if no_code_mode:
        fence_positions = [idx for idx in range(len(full_response)) if full_response.startswith("```", idx)]
        if len(fence_positions) % 2 == 1:
            safe_source = full_response[: fence_positions[-1]] + NO_CODE_MODE_REPLACEMENT
    safe_display, _, _ = display_text(
        safe_source,
        mask_output=mask_output,
        no_code_mode=no_code_mode,
        known_secrets=known_secrets,
    )
    if mask_output:
        holdback = 32
        if known_secrets:
            holdback = max(holdback, min(max(len(secret) for secret in known_secrets if secret), 128))
        return safe_display[: max(0, len(safe_display) - holdback)]
    return safe_display


def retry_failure_action() -> str:
    """Prompt for post-failure handling."""
    while True:
        choice = prompt_input("Failure action: [R]etry, [A]bort, Retry with [P]atience? ").strip().lower()
        if choice in {"r", "retry"}:
            return "retry"
        if choice in {"a", "abort"}:
            return "abort"
        if choice in {"p", "patience", "retry with patience"}:
            return "patience"
        print("Please choose R, A, or P.", file=sys.stderr)


def provider_for_attempt(state: ReplState, *, timeout_multiplier: int = 1) -> DuoProvider:
    """Build a provider for the current attempt, optionally with more patience."""
    base_timeout = state.timeout_override if state.timeout_override is not None else state.cfg.chat.timeout
    effective_timeout = max(1, int(base_timeout) * max(1, timeout_multiplier))
    return build_provider(state.cfg, timeout_override=effective_timeout)


def send_chat_turn(state: ReplState, user_input: str, *, original_handler=None, sigint_handler=None) -> None:
    """Send one user turn to the provider and persist the result."""
    from tuochat.models import MessageStatus, Role, Usage
    from tuochat.provider.duo import DuoAPIError

    conv = state.conv
    state.last_turn_elapsed_seconds = None
    sent_attachment_count = len(state.pending_attachment_messages or [])
    outbound_input = build_outbound_input(state, user_input)
    if not validate_user_request(state, user_input, outbound_input):
        return
    if state.verbose or state.debug:
        print_verbose_context(state, outbound_input)
        print_timeout_limits(state, reason="preflight")

    if state.active_model == "openrouter":
        started_at = time.perf_counter()
        try:
            openrouter_provider = build_openrouter_provider(state.cfg, model_override=state.active_openrouter_model)
        except (OpenRouterAPIError, OpenRouterUnavailableError, ValueError) as exc:
            print(f"\n[OpenRouter unavailable: {exc}]", file=sys.stderr)
            return

        history = conversation_history_for_openrouter(state)
        chunks: list[str] = []
        label = MODEL_LABELS.get(state.active_model, state.active_model)
        print(f"\n{label}> ", end="", flush=True)
        try:
            for chunk in openrouter_provider.chat(
                outbound_input,
                streaming=state.streaming,
                additional_context=state.server_context or None,
                history=history,
                system_prompt=conv.system_prompt,
            ):
                print(chunk, end="", flush=True)
                chunks.append(chunk)
        except OpenRouterAPIError as exc:
            print(f"\n[OpenRouter error: {exc}]", file=sys.stderr)
            return
        print()
        print()
        full_response = "".join(chunks)

        input_tokens = estimate_tokens(outbound_input)
        output_tokens = estimate_tokens(full_response)
        state.session_input_tokens += input_tokens
        state.session_output_tokens += output_tokens
        state.session_turns += 1
        elapsed_seconds = time.perf_counter() - started_at
        state.last_turn_elapsed_seconds = elapsed_seconds
        record_log_event(
            state,
            "turn",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            request_preview=one_line_preview(user_input),
            response_preview=one_line_preview(full_response),
        )
        if not state.gui_mode:
            print("Estimate:")
            print_report_value("input_tokens", input_tokens)
            print_report_value("output_tokens", output_tokens)
            print_report_value("model", openrouter_provider.last_model_used or "(unknown)")

        message_extras_json: str | None = None
        if state.pending_template_metadata is not None:
            message_extras_json = json_dumps({"template": state.pending_template_metadata}, ensure_ascii=True)

        user_msg = conv.add_message(Role.USER.value, outbound_input, extras_json=message_extras_json)
        assistant_msg = conv.add_message(Role.ASSISTANT.value, full_response, status=MessageStatus.COMPLETE.value)
        if conv.title is None:
            conv.title = conv.auto_title(user_input)
        state.last_user_input = user_input
        state.pending_template_metadata = None
        consume_pending_attachments(state, sent_attachment_count)
        conv.cwd = str(Path.cwd())
        state.store.save_conversation(conv)
        state.store.save_message(user_msg)
        state.store.save_message(assistant_msg)
        state.store.save_usage(
            Usage(
                conversation_id=conv.id,
                message_id=assistant_msg.id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                model=openrouter_provider.last_model_used or "openrouter",
            )
        )
        _, md_path, extracted = sync_conversation_artifacts(state.cfg, conv, classification=state.active_classification)
        if md_path is not None:
            update_saved_conversation_artifacts(state, md_path, extracted)
            print_virtual_file_notice(state)
        if not state.gui_mode:
            print_response_footer(state, elapsed_seconds=elapsed_seconds)
        if state.verbose or state.debug:
            print_verbose_context(state)
        return

    if state.active_model == "eliza":
        started_at = time.perf_counter()
        eliza = ElizaProvider()
        chunks = []
        print(f"\n{MODEL_LABELS.get(state.active_model, state.active_model)}> ", end="", flush=True)
        for chunk in eliza.chat(outbound_input, streaming=state.streaming):
            print(chunk, end="", flush=True)
            chunks.append(chunk)
        print()
        print()
        full_response = "".join(chunks)

        input_tokens = estimate_tokens(outbound_input)
        output_tokens = estimate_tokens(full_response)
        state.session_input_tokens += input_tokens
        state.session_output_tokens += output_tokens
        state.session_turns += 1
        elapsed_seconds = time.perf_counter() - started_at
        state.last_turn_elapsed_seconds = elapsed_seconds
        record_log_event(
            state,
            "turn",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            request_preview=one_line_preview(user_input),
            response_preview=one_line_preview(full_response),
        )
        if not state.gui_mode:
            print("Estimate:")
            print_report_value("input_tokens", input_tokens)
            print_report_value("output_tokens", output_tokens)
            print_report_value("approx_cost", "$0.00 (Eliza is free)")

        message_extras_json = None
        if state.pending_template_metadata is not None:
            message_extras_json = json_dumps({"template": state.pending_template_metadata}, ensure_ascii=True)

        user_msg = conv.add_message(Role.USER.value, outbound_input, extras_json=message_extras_json)
        assistant_msg = conv.add_message(Role.ASSISTANT.value, full_response, status=MessageStatus.COMPLETE.value)
        if conv.title is None:
            conv.title = conv.auto_title(user_input)
        state.last_user_input = user_input
        state.pending_template_metadata = None
        consume_pending_attachments(state, sent_attachment_count)
        conv.cwd = str(Path.cwd())
        state.store.save_conversation(conv)
        state.store.save_message(user_msg)
        state.store.save_message(assistant_msg)
        state.store.save_usage(
            Usage(
                conversation_id=conv.id,
                message_id=assistant_msg.id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                model="eliza",
            )
        )
        _, md_path, extracted = sync_conversation_artifacts(state.cfg, conv, classification=state.active_classification)
        if md_path is not None:
            update_saved_conversation_artifacts(state, md_path, extracted)
            print_virtual_file_notice(state)
        if not state.gui_mode:
            print_response_footer(state, elapsed_seconds=elapsed_seconds)
        if state.verbose or state.debug:
            print_verbose_context(state)
        return

    timeout_multiplier = 1
    while True:
        started_at = time.perf_counter()
        request_started_at_iso = utc_now_iso()
        first_token_at_iso: str | None = None
        obs_error_kind: str | None = None
        attempt_provider = (
            provider_for_attempt(state, timeout_multiplier=1)
            if timeout_multiplier == 1
            else provider_for_attempt(state, timeout_multiplier=timeout_multiplier)
        )

        print(f"\n{MODEL_LABELS.get(state.active_model, state.active_model)}> ", end="", flush=True)
        interrupt_event = threading.Event()
        saw_masked_output = False
        saw_no_code_output = False
        known_secrets = known_secret_values(state.cfg)
        full_response = ""
        displayed_text = ""
        notifier_stop, notifier_thread = start_long_request_notifier(
            state.cfg,
            should_warn=lambda: not first_output_seen,  # noqa: B023
        )
        dot_stop, dot_thread = start_dot_timer(state.dot_timer_enabled)
        first_output_seen = False
        error: BaseException | None = None

        if sigint_handler is not None:

            def wrapper(signum, frame, interrupt_event=interrupt_event):
                interrupt_event.set()
                sigint_handler(signum, frame)

            signal.signal(signal.SIGINT, wrapper)

        def is_interrupted(interrupt_event=interrupt_event) -> bool:
            return interrupt_event.is_set()

        # Prefer the interactively selected resource over the conversation-level one
        effective_resource_id = (
            state.active_resource.resource_id if state.active_resource is not None else conv.resource_id
        )
        try:
            active_duo_model = getattr(state, "active_duo_model", None)
            if active_duo_model is not None:
                delta_stream = attempt_provider.chat(
                    outbound_input,
                    resource_id=effective_resource_id,
                    streaming=state.streaming,
                    cancel=is_interrupted,
                    additional_context=state.server_context or None,
                    duo_model=active_duo_model,
                )
            else:
                delta_stream = attempt_provider.chat(
                    outbound_input,
                    resource_id=effective_resource_id,
                    streaming=state.streaming,
                    cancel=is_interrupted,
                    additional_context=state.server_context or None,
                )
            for delta in delta_stream:
                if is_interrupted():
                    break
                if delta and not first_output_seen:
                    first_output_seen = True
                    first_token_at_iso = utc_now_iso()
                    dot_stop.set()
                    if state.dot_timer_enabled:
                        print()
                full_response += delta
                _, sensitive_masked, code_masked = display_text(
                    full_response,
                    mask_output=state.mask_output,
                    no_code_mode=state.no_code_mode,
                    known_secrets=known_secrets,
                )
                saw_masked_output = saw_masked_output or sensitive_masked
                saw_no_code_output = saw_no_code_output or code_masked
                safe_display = stream_safe_display_length(
                    full_response,
                    mask_output=state.mask_output,
                    no_code_mode=state.no_code_mode,
                    known_secrets=known_secrets,
                )
                if len(safe_display) > len(displayed_text):
                    print(safe_display[len(displayed_text) :], end="", flush=True)
                    displayed_text = safe_display
        except DuoAPIError as exc:
            error = exc
            obs_error_kind = "duo_api_error"
            print(f"\n[Error: {exc}]", file=sys.stderr)
        except (ConnectionError, OSError) as exc:
            error = exc
            obs_error_kind = "connection_error"
            print(f"\n[Connection error: {exc}]", file=sys.stderr)
        finally:
            notifier_stop.set()
            dot_stop.set()
            if notifier_thread is not None:
                notifier_thread.join(timeout=0.1)
            if dot_thread is not None:
                dot_thread.join(timeout=0.1)
            if original_handler is not None:
                signal.signal(signal.SIGINT, original_handler)

        shown_full, sensitive_masked, code_masked = display_text(
            full_response,
            mask_output=state.mask_output,
            no_code_mode=state.no_code_mode,
            known_secrets=known_secrets,
        )
        saw_masked_output = saw_masked_output or sensitive_masked
        saw_no_code_output = saw_no_code_output or code_masked
        if len(shown_full) > len(displayed_text):
            print(shown_full[len(displayed_text) :], end="", flush=True)
        print("\n")
        if saw_masked_output:
            print_mask_notice(state)
        if saw_no_code_output:
            print_no_code_mode_notice(state)

        # Sandbox: detect executable code blocks in the response
        if getattr(state, "code_interpreter_enabled", True):
            try:
                from tuochat.sandbox.integration import handle_sandbox_response

                handle_sandbox_response(full_response, state)
            except ImportError:
                pass  # sandbox extras not installed

        elapsed_seconds = time.perf_counter() - started_at
        state.last_turn_elapsed_seconds = elapsed_seconds
        if error is not None:
            if not state.quiet:
                print(f"Elapsed: {elapsed_seconds:.2f}s")
            finished_at_iso = utc_now_iso()
            partial_tokens = estimate_tokens(full_response) if full_response else None
            total_ms = int(elapsed_seconds * 1000)
            ttfb_ms = None
            if first_token_at_iso is not None:
                from tuochat.observability import ms_between as obs_ms_between

                ttfb_ms = obs_ms_between(request_started_at_iso, first_token_at_iso)
            diagnostics = (
                attempt_provider.get_last_chat_diagnostics()
                if hasattr(attempt_provider, "get_last_chat_diagnostics")
                else None
            )
            req_id = diagnostics.request_id if diagnostics is not None else None
            obs_row = ObservabilityRow(
                provider="gitlab_duo",
                status="failed",
                request_started_at=request_started_at_iso,
                finished_at=finished_at_iso,
                request_tokens=estimate_tokens(outbound_input),
                total_response_ms=total_ms,
                conversation_id=conv.id,
                request_id=req_id,
                response_tokens=partial_tokens,
                time_to_first_token_ms=ttfb_ms,
                first_token_at=first_token_at_iso,
                error_kind=obs_error_kind or ("timeout" if is_timeout_error(error) else "unknown"),
            )
            state.store.save_observability_row(obs_row)
            if is_timeout_error(error):
                print_timeout_limits(state, reason=str(error))
            print_chat_diagnostics(state, header="Failure diagnostics", provider=attempt_provider)
            action = retry_failure_action()
            if action == "abort":
                print("Request aborted. Conversation state was left unchanged.")
                return
            timeout_multiplier = timeout_multiplier * 2 if action == "patience" else 1
            if action == "patience":
                print(f"Retrying with patience at {timeout_multiplier}x timeout.")
            else:
                print("Retrying request without adding a duplicate conversation turn.")
            continue

        input_tokens = estimate_tokens(outbound_input)
        output_tokens = estimate_tokens(full_response)
        interrupted = is_interrupted()

        # --- Observability recording for completed/cancelled Duo turns ---
        obs_finished_at_iso = utc_now_iso()
        obs_total_ms = int(elapsed_seconds * 1000)
        obs_ttfb_ms: int | None = None
        if first_token_at_iso is not None:
            from tuochat.observability import ms_between as obs_ms_between

            obs_ttfb_ms = obs_ms_between(request_started_at_iso, first_token_at_iso)
        obs_time_per_token: float | None = None
        if not interrupted and output_tokens > 0:
            obs_time_per_token = obs_total_ms / output_tokens
        obs_diagnostics = (
            attempt_provider.get_last_chat_diagnostics()
            if hasattr(attempt_provider, "get_last_chat_diagnostics")
            else None
        )
        obs_req_id = obs_diagnostics.request_id if obs_diagnostics is not None else None
        obs_status = "cancelled" if interrupted else "completed"
        state.store.save_observability_row(
            ObservabilityRow(
                provider="gitlab_duo",
                status=obs_status,
                request_started_at=request_started_at_iso,
                finished_at=obs_finished_at_iso,
                request_tokens=input_tokens,
                total_response_ms=obs_total_ms,
                conversation_id=conv.id,
                request_id=obs_req_id,
                response_tokens=output_tokens if output_tokens > 0 else None,
                first_token_at=first_token_at_iso,
                time_to_first_token_ms=obs_ttfb_ms,
                time_per_token_ms=obs_time_per_token,
            )
        )
        # --- End observability recording ---

        state.session_input_tokens += input_tokens
        state.session_output_tokens += output_tokens
        state.session_turns += 1
        state.last_turn_elapsed_seconds = elapsed_seconds
        record_log_event(
            state,
            "turn",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            request_preview=one_line_preview(user_input),
            response_preview=one_line_preview(full_response),
        )
        if not state.gui_mode:
            print_turn_estimate(input_tokens, output_tokens, verbose=state.verbose)

        message_extras_json = None
        if state.pending_template_metadata is not None:
            message_extras_json = json_dumps({"template": state.pending_template_metadata}, ensure_ascii=True)

        user_msg = conv.add_message(Role.USER.value, outbound_input, extras_json=message_extras_json)
        assistant_msg = conv.add_message(
            Role.ASSISTANT.value,
            full_response,
            status=MessageStatus.PARTIAL.value if interrupted else MessageStatus.COMPLETE.value,
        )

        if conv.title is None:
            conv.title = conv.auto_title(user_input)

        state.last_user_input = user_input
        state.pending_template_metadata = None
        consume_pending_attachments(state, sent_attachment_count)
        conv.cwd = str(Path.cwd())
        state.store.save_conversation(conv)
        state.store.save_message(user_msg)
        state.store.save_message(assistant_msg)
        state.store.save_usage(
            Usage(
                conversation_id=conv.id,
                message_id=assistant_msg.id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                model="estimated",
            )
        )
        _, md_path, extracted = sync_conversation_artifacts(state.cfg, conv, classification=state.active_classification)
        if md_path is not None:
            update_saved_conversation_artifacts(state, md_path, extracted)
            print_virtual_file_notice(state)
        if not state.gui_mode:
            print_response_footer(state, elapsed_seconds=elapsed_seconds)
        if state.verbose or state.debug:
            print_chat_diagnostics(state, header="Attempt diagnostics", provider=attempt_provider)
            print_verbose_context(state)
        return


__all__ = [
    "ReplState",
    "blind_mode_enabled",
    "python_version_string",
    "local_now",
    "sync_conversation_artifacts",
    "no_stream_hold_message",
    "no_stream_mode_enabled",
    "resolve_streaming_enabled",
    "open_path",
    "emit_long_request_notification",
    "start_long_request_notifier",
    "start_dot_timer",
    "write_here_mode_enabled",
    "approve_writes_enabled",
    "cwd_is_filesystem_root",
    "apply_git_repo_write_here_default",
    "set_session_write_here_mode",
    "set_session_approve_writes",
    "print_write_here_help",
    "print_approve_writes_help",
    "toggle_write_here_mode",
    "toggle_approve_writes",
    "prompt_write_here_approval",
    "record_log_event",
    "provider_timeout_summary",
    "is_timeout_error",
    "build_openrouter_provider",
    "build_provider",
    "conversation_history_for_openrouter",
    "persist_chat_preferences",
    "build_store",
    "no_write_enabled",
    "print_no_write_help",
    "toggle_blind_mode",
    "toggle_no_write",
    "validate_user_request",
    "build_resumed_context_block",
    "build_outbound_input",
    "handle_server_context_command",
    "update_saved_conversation_artifacts",
    "latest_assistant_message",
    "copy_to_clipboard",
    "extract_template_message_metadata",
    "reset_repl_state",
    "switch_to_conversation",
    "stream_safe_display_length",
    "retry_failure_action",
    "provider_for_attempt",
    "send_chat_turn",
]
