"""Top-level REPL orchestration and slash-command dispatch for the CLI."""

# ruff: noqa: E402,F401,F403,F811,F821,B010
from __future__ import annotations

import argparse
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tuochat.__about__ import __version__
from tuochat.cli import bootstrap
from tuochat.cli.command_models import ConfigCommand, GlobalOptions
from tuochat.cli.commands.config_cmd import run
from tuochat.cli.io import configure_interactive_io, shutdown_interactive_io
from tuochat.cli.pickers import (
    pick_archived_candidate,
    pick_custom_instruction,
    pick_resume_candidate,
    pick_skill,
    pick_template,
    print_search_candidates,
    resolve_custom_instruction_path,
    resolve_skill_path,
    resolve_template_path,
    run_conversation_search,
    select_include_candidates,
)
from tuochat.cli.prompts import prompt_bool, prompt_input, prompt_missing_slash_command, read_user_message
from tuochat.cli.rendering import (
    announce_screen_transition,
    clear_screen,
    humanize_report_key,
    number_label,
    print_attachment_estimate,
    print_chat_summary,
    print_command_log,
    print_context,
    print_expiration_warning,
    print_files,
    print_masked_conversation_transcript,
    print_pending_attachments,
    print_saved_conversation_files,
    print_session_intro,
    print_status,
    print_timeout_limits,
    print_token_check,
    print_verbose_context,
    render_markdown_config,
)
from tuochat.cli.session import (
    ReplState,
    apply_git_repo_write_here_default,
    blind_mode_enabled,
    build_provider,
    build_store,
    copy_to_clipboard,
    handle_server_context_command,
    latest_assistant_message,
    no_stream_hold_message,
    no_stream_mode_enabled,
    no_write_enabled,
    open_path,
    persist_chat_preferences,
    print_approve_writes_help,
    print_no_write_help,
    print_write_here_help,
    record_log_event,
    reset_repl_state,
    resolve_streaming_enabled,
    send_chat_turn,
    switch_to_conversation,
    sync_conversation_artifacts,
    toggle_approve_writes,
    toggle_blind_mode,
    toggle_no_write,
    toggle_write_here_mode,
    update_saved_conversation_artifacts,
)
from tuochat.cli.setup import (
    classification_limit_message,
    classification_within_max,
    is_first_run,
    maybe_run_first_run_setup,
    prompt_classification,
    resolve_classification_choice,
    run_init_wizard,
    should_offer_first_run_tutorial,
)
from tuochat.cli.tutorial import run_tutorial
from tuochat.config import TuochatConfig
from tuochat.constants import KNOWN_BARE_COMMANDS, KNOWN_SLASH_COMMANDS, MODEL_LABELS, classification_help_label
from tuochat.context.attachments import (
    attachment_stub_name,
    code_map_candidates,
    detach_pending_attachment,
    format_included_file,
    is_context_ignored_path,
    map_candidates,
    prepare_include,
    queue_attachment,
    read_include_file,
    render_code_map_attachment,
    render_map_attachment,
)
from tuochat.context.composer import compose_system_prompt, load_custom_instruction_sections, resolve_template_prompt
from tuochat.discovery.custom_instructions import describe_custom_instruction_path, list_available_custom_instructions
from tuochat.discovery.shared import bundled_custom_instructions_dir, bundled_skills_dir, bundled_templates_dir
from tuochat.discovery.skills import list_available_skills, render_skill_message
from tuochat.discovery.templates import (
    describe_template_path,
    list_available_templates,
    parse_template_metadata,
    template_body,
)
from tuochat.estimation import word_count_limited
from tuochat.help_data import HELP_SECTION_LOOKUP, HELP_SECTIONS, HELP_TOPIC_ALIASES
from tuochat.models import Conversation
from tuochat.persistence import ConversationStore, NullConversationStore
from tuochat.persistence.archive import check_archive_bagit_status, load_bagit_module, refresh_archive_bagit_metadata
from tuochat.provider.duo import DuoProvider

logger = logging.getLogger("tuochat.cli")

SLASH_COMMAND_ALIASES = {
    "/attach": "/include",
    "/history": "/log",
    "/done": "/quit",
}


def build_parser() -> argparse.ArgumentParser:
    """Build the root argparse parser."""
    parser = argparse.ArgumentParser(
        prog="tuochat",
        description="GitLab Duo Chat client with local conversation tools",
        epilog=(
            "Many REPL slash commands also have top-level equivalents. "
            "Use `tuochat convo ...`, `tuochat archive ...`, `tuochat context ...`, and `tuochat headless ...`."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        help="Path to config file",
    )
    parser.add_argument(
        "--no-banner",
        "--no-logo",
        action="store_true",
        dest="no_banner",
        help="Suppress the startup banner",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress repeated interactive instructions and use terse prompts",
    )
    parser.add_argument(
        "--blind",
        action="store_true",
        help="Enable blind-friendly mode: suppress logo, simplify help/context, and avoid clear-screen behavior",
    )

    def add_format_argument(command_parser: argparse.ArgumentParser, *, markdown: bool = False) -> None:
        choices = ("text", "json", "markdown") if markdown else ("text", "json")
        command_parser.add_argument("--format", choices=choices, default="text", help="Output format")

    def add_chat_session_arguments(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument("--prompt", "-p", help="System prompt for this conversation")
        command_parser.add_argument("--resource-id", "-r", help="GitLab project/group GID for context")
        command_parser.add_argument("--no-stream", action="store_true", help="Use polling instead of streaming")
        command_parser.add_argument("--timeout", type=int, help="Override request timeout for this chat session")

    def add_headless_arguments(command_parser: argparse.ArgumentParser, *, include_system_prompt: bool) -> None:
        command_parser.add_argument("message", nargs="?", help="Prompt text")
        command_parser.add_argument("--file", type=Path, help="Read the prompt body from a file")
        command_parser.add_argument("--stdin", action="store_true", help="Read the prompt body from stdin")
        command_parser.add_argument("--include", action="append", type=Path, default=[], help="Attach a local file")
        command_parser.add_argument("--skill", help="Attach a discovered skill by name or path")
        command_parser.add_argument("--template", help="Render a discovered template by name or path")
        command_parser.add_argument("--var", action="append", default=[], help="Template variable as NAME=value")
        command_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
        command_parser.add_argument("--output-file", type=Path, help="Write the final response text to a file")
        command_parser.add_argument("--no-stream", action="store_true", help="Disable stdout streaming")
        command_parser.add_argument("--timeout", type=int, help="Override the provider timeout")
        command_parser.add_argument(
            "--model", choices=("duo", "eliza", "openrouter"), default="duo", help="Model to use"
        )
        if include_system_prompt:
            command_parser.add_argument("--system-prompt", help="System prompt for the new conversation")
            command_parser.add_argument("--resource-id", help="GitLab project/group GID for context")

    subparsers = parser.add_subparsers(dest="command", title="commands")

    chat_parser = subparsers.add_parser(
        "chat",
        help="Start an interactive chat",
        description="Chat and local tools",
    )
    chat_parser.set_defaults(command_key="chat")
    add_chat_session_arguments(chat_parser)

    gui_parser = subparsers.add_parser("gui", help="Start the minimal Tkinter chat window")
    gui_parser.set_defaults(command_key="gui")
    add_chat_session_arguments(gui_parser)

    config_parser = subparsers.add_parser("config", help="Show active configuration")
    config_parser.set_defaults(command_key="config")
    config_parser.add_argument(
        "format",
        nargs="?",
        choices=("markdown", "json"),
        default="markdown",
        help="Output format (default: markdown)",
    )

    init_parser = subparsers.add_parser("init", help="Create a starter config file")
    init_parser.set_defaults(command_key="init")
    init_parser.add_argument("--force", action="store_true", help="Overwrite an existing config file")

    doctor_parser = subparsers.add_parser("doctor", help="Run local config and path checks")
    doctor_parser.set_defaults(command_key="doctor")
    add_format_argument(doctor_parser)

    usage_parser = subparsers.add_parser("usage", help="Show weekly token and cost usage")
    usage_parser.set_defaults(command_key="usage")
    add_format_argument(usage_parser)

    convo_parser = subparsers.add_parser("convo", help="Manage saved conversations")
    convo_subparsers = convo_parser.add_subparsers(dest="convo_command", required=True, title="conversation commands")

    convo_list_parser = convo_subparsers.add_parser("list", help="List saved conversations")
    convo_list_parser.set_defaults(command_key="convo-list")
    convo_list_parser.add_argument("--limit", "-n", type=int, default=20, help="Max conversations to show")
    convo_list_parser.add_argument("--archived", action="store_true", help="Show archived conversations instead")
    add_format_argument(convo_list_parser)

    convo_resume_parser = convo_subparsers.add_parser("resume", help="Resume a past conversation")
    convo_resume_parser.set_defaults(command_key="convo-resume")
    convo_resume_parser.add_argument("id", nargs="?", help="Conversation ID (or prefix)")

    convo_archive_parser = convo_subparsers.add_parser("archive", help="Archive a saved conversation")
    convo_archive_parser.set_defaults(command_key="convo-archive")
    convo_archive_parser.add_argument("id", help="Conversation ID (or prefix)")

    convo_unarchive_parser = convo_subparsers.add_parser("unarchive", help="Restore archived conversations")
    convo_unarchive_parser.set_defaults(command_key="convo-unarchive")
    convo_unarchive_parser.add_argument("id", nargs="?", help="Conversation ID (or prefix)")
    convo_unarchive_parser.add_argument("--all", action="store_true", help="Restore every archived conversation")

    convo_delete_parser = convo_subparsers.add_parser("delete", help="Delete a saved conversation")
    convo_delete_parser.set_defaults(command_key="convo-delete")
    convo_delete_parser.add_argument("id", help="Conversation ID (or prefix)")

    convo_search_parser = convo_subparsers.add_parser("search", help="Search past conversations")
    convo_search_parser.set_defaults(command_key="convo-search")
    convo_search_parser.add_argument("query", nargs="+", help="Full-text search query")
    convo_search_parser.add_argument("--limit", "-n", type=int, default=20, help="Max search results to show")
    convo_search_parser.add_argument("--title", help="Filter results by conversation title")
    convo_search_parser.add_argument(
        "--after", help="Only include conversations updated on or after this ISO timestamp"
    )
    convo_search_parser.add_argument(
        "--before", help="Only include conversations updated on or before this ISO timestamp"
    )

    convo_export_parser = convo_subparsers.add_parser("export", help="Export a conversation as markdown")
    convo_export_parser.set_defaults(command_key="convo-export")
    convo_export_parser.add_argument("id", help="Conversation ID (or prefix)")

    convo_open_parser = convo_subparsers.add_parser("open", help="Open a conversation archive directory")
    convo_open_parser.set_defaults(command_key="convo-open")
    convo_open_parser.add_argument("id", help="Conversation ID (or prefix)")

    archive_parser = subparsers.add_parser("archive", help="Manage saved archive metadata")
    archive_subparsers = archive_parser.add_subparsers(dest="archive_command", required=True, title="archive commands")

    archive_update_parser = archive_subparsers.add_parser(
        "bagit-update", help="Refresh archive-change hashes and metadata"
    )
    archive_update_parser.set_defaults(command_key="archive-bagit-update")

    archive_check_parser = archive_subparsers.add_parser(
        "bagit-check", help="Check whether archives changed since the last BagIt update"
    )
    archive_check_parser.set_defaults(command_key="archive-bagit-check")
    add_format_argument(archive_check_parser)

    context_parser = subparsers.add_parser("context", help="Discover local context sources")
    context_subparsers = context_parser.add_subparsers(dest="context_command", required=True, title="context commands")

    context_files_parser = context_subparsers.add_parser("files", help="List include-able local files")
    context_files_parser.set_defaults(command_key="context-files")
    add_format_argument(context_files_parser)

    context_skills_parser = context_subparsers.add_parser("skills", help="List discovered skills")
    context_skills_parser.set_defaults(command_key="context-skills")
    add_format_argument(context_skills_parser)

    context_templates_parser = context_subparsers.add_parser("templates", help="List discovered templates")
    context_templates_parser.set_defaults(command_key="context-templates")
    add_format_argument(context_templates_parser)

    context_custom_parser = context_subparsers.add_parser(
        "custom-instructions",
        help="List discovered custom instructions",
    )
    context_custom_parser.set_defaults(command_key="context-custom-instructions")
    add_format_argument(context_custom_parser)

    headless_parser = subparsers.add_parser("headless", help="Run non-interactive chat flows")
    headless_subparsers = headless_parser.add_subparsers(
        dest="headless_command", required=True, title="headless commands"
    )

    headless_ask_parser = headless_subparsers.add_parser("ask", help="Start a new non-interactive conversation")
    headless_ask_parser.set_defaults(command_key="headless-ask")
    add_headless_arguments(headless_ask_parser, include_system_prompt=True)

    headless_continue_parser = headless_subparsers.add_parser("continue", help="Continue a saved conversation")
    headless_continue_parser.set_defaults(command_key="headless-continue")
    headless_continue_parser.add_argument(
        "id",
        help='Conversation ID (or prefix), or "ongoing" to keep Duo server-side continuity',
    )
    add_headless_arguments(headless_continue_parser, include_system_prompt=False)

    history_parser = subparsers.add_parser("history", help="Alias for `convo list`")
    history_parser.set_defaults(command_key="history", archived=False, format="text")
    history_parser.add_argument("--limit", "-n", type=int, default=20, help="Max conversations to show")
    add_format_argument(history_parser)

    resume_parser = subparsers.add_parser("resume", help="Alias for `convo resume`")
    resume_parser.set_defaults(command_key="resume")
    resume_parser.add_argument("id", nargs="?", help="Conversation ID (or prefix)")

    search_parser = subparsers.add_parser("search", help="Alias for `convo search`")
    search_parser.set_defaults(command_key="search")
    search_parser.add_argument("query", nargs="+", help="Full-text search query")
    search_parser.add_argument("--limit", "-n", type=int, default=20, help="Max search results to show")
    search_parser.add_argument("--title", help="Filter results by conversation title")
    search_parser.add_argument("--after", help="Only include conversations updated on or after this ISO timestamp")
    search_parser.add_argument("--before", help="Only include conversations updated on or before this ISO timestamp")

    export_parser = subparsers.add_parser("export", help="Alias for `convo export`")
    export_parser.set_defaults(command_key="export")
    export_parser.add_argument("id", nargs="?", help="Conversation ID (or prefix)")
    return parser


def global_options_from_args(args: argparse.Namespace) -> GlobalOptions:
    """Translate argparse output into global options."""
    return GlobalOptions(
        debug=getattr(args, "debug", False),
        config_path=bootstrap.config_path_for(args),
        no_banner=getattr(args, "no_banner", False),
        quiet=getattr(args, "quiet", False),
        blind=getattr(args, "blind", False),
    )


def load_config(config_path: Path | str | None = None) -> TuochatConfig:
    """Load config from the requested path or default locations."""
    from tuochat.config import load_config as config_load_config

    return config_load_config(str(config_path) if config_path is not None else None)


def load_config_with_cli_overrides(config_path: Path | str | GlobalOptions | None = None) -> TuochatConfig:
    """Load config from the requested path or default locations."""
    from tuochat.logging_config import setup_logging

    if isinstance(config_path, GlobalOptions):
        global_options = config_path
    else:
        global_options = GlobalOptions(config_path=Path(config_path) if config_path else None)

    cfg = load_config(global_options.config_path)
    cfg = bootstrap.apply_global_overrides(cfg, global_options)
    setup_logging(
        log_dir=cfg.log_dir,
        debug=global_options.debug,
        enable_file_logging=not bootstrap.no_write_enabled(cfg),
    )
    return cfg


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint."""
    from tuochat.cli import dispatch as cli_dispatch

    parser = build_parser()
    args = parser.parse_args(argv)
    global_options = global_options_from_args(args)
    cfg = load_config_with_cli_overrides(global_options)

    if getattr(args, "command_key", None) is None:
        if is_first_run(
            cfg, config_path=str(global_options.config_path) if global_options.config_path is not None else None
        ):
            run_init_wizard(
                config_path=str(global_options.config_path) if global_options.config_path is not None else None,
                force=True,
            )
            print("Setup complete. Start chatting with `tuochat chat`.")
            return 0
        parser.print_help()
        return 0

    command = cli_dispatch.command_from_args(args)
    if command is None:
        parser.print_help()
        return 0
    return cli_dispatch.dispatch_command(cfg, global_options, command)


def week_start_iso() -> str:
    """Return the ISO timestamp for the most recent Sunday 00:00:00 UTC."""
    now = datetime.now(timezone.utc)
    # weekday(): Mon=0 … Sun=6.  We want the preceding Sunday.
    days_since_sunday = (now.weekday() + 1) % 7
    sunday = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_since_sunday)
    return sunday.isoformat()


def cmd_config(cfg: TuochatConfig, *, fmt: str = "markdown") -> int:
    """Show active configuration (redacted)."""
    return run(
        cfg,
        ConfigCommand(format=fmt),
        render_markdown_config=render_markdown_config,
    )


def cmd_init(args: argparse.Namespace) -> int:
    """Interactively create a config file at the default or requested path."""
    from tuochat.cli.command_models import InitCommand
    from tuochat.cli.commands import init_cmd

    global_options = GlobalOptions(
        config_path=Path(args.config).expanduser() if getattr(args, "config", None) else None,
        debug=getattr(args, "debug", False),
        no_banner=getattr(args, "no_banner", False),
        quiet=getattr(args, "quiet", False),
        blind=getattr(args, "blind", False),
    )
    return init_cmd.run(
        global_options,
        InitCommand(force=getattr(args, "force", False)),
        run_init_wizard=run_init_wizard,
        default_config_file=TuochatConfig().config_file,
    )


def is_exit_command(user_input: str) -> bool:
    """Return True only for explicit exit commands after trimming whitespace."""
    return user_input.strip().lower() in {"quit", "exit", "/quit", "/exit"}


def extract_bang_command(raw_input: str) -> str | None:
    """Return the shell command text if raw_input is a bang command, else None.

    Leading whitespace and newlines are ignored. A single ``!`` followed by
    optional whitespace and then the command body is recognised. Both ``!ls``
    and ``! ls`` (with a space) and ``  !ls`` (with leading whitespace) work.
    Multiline input is treated as a single shell invocation passed to the
    shell; each line is joined to form the command string.
    """
    stripped = raw_input.lstrip()
    if not stripped.startswith("!"):
        return None
    command = stripped[1:]
    return command


def handle_bang_command(raw_input: str, state: ReplState) -> bool:
    """Run a shell bang command and optionally queue its output as an attachment.

    Returns True when the input was a bang command (caller should not process
    it further), False when it was not a bang command.
    """
    command = extract_bang_command(raw_input)
    if command is None:
        return False

    command = command.strip()
    if not command:
        print("Usage: !<shell command>", file=sys.stderr)
        return True

    print(f"$ {command}")
    try:
        if os.name == "nt":
            shell_path = os.environ.get("COMSPEC") or shutil.which("cmd.exe")
            if not shell_path:
                raise OSError("Could not find cmd.exe to run the bang command.")
            command_argv = [shell_path, "/d", "/s", "/c", command]
        else:
            shell_path = shutil.which("sh") or "/bin/sh"
            command_argv = [shell_path, "-lc", command]
        result = subprocess.run(
            command_argv,
            capture_output=True,
            text=True,
            check=False,
        )
        output = result.stdout
        if result.stderr:
            output = output + result.stderr if output else result.stderr
        if result.returncode != 0:
            print(f"[exit {result.returncode}]", file=sys.stderr)
    except OSError as exc:
        print(f"Error running command: {exc}", file=sys.stderr)
        return True

    print(output, end="" if output.endswith("\n") else "\n")

    if prompt_bool("Attach output to next request?", default=False):
        attachment = f"Shell command output:\n\n```\n$ {command}\n{output}```"
        queue_attachment(state, Path(f"[shell] {command[:60]}"), attachment)
        print("Output queued for next request.")

    return True


def normalize_command_candidate(raw_input: str) -> str:
    """Normalize leading whitespace before slash-command detection."""
    return raw_input.lstrip()


def expiration_cutoff_iso(expiration_days: int) -> str:
    """Return the ISO timestamp cutoff for expired conversations."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=expiration_days)
    return cutoff.isoformat()


def maybe_prune_expired_conversations(store: ConversationStore | NullConversationStore, cfg: TuochatConfig) -> None:
    """Offer to delete expired conversations at interactive chat startup."""
    days = cfg.chat.conversation_expiration_days
    if days <= 0:
        return

    expired = store.list_expired_conversations(expiration_cutoff_iso(days))
    if not expired:
        return

    print(f"{len(expired)} conversation(s) are older than {days} days and are eligible for deletion.")
    for idx, conv in enumerate(expired[:5], start=1):
        print(f"  [{idx}] {conv.id[:8]}  {conv.title or 'Untitled'}  last_updated={conv.updated_at[:19]}")
    if len(expired) > 5:
        print(f"  ... and {len(expired) - 5} more")
    print(f"To turn this off, set [chat].conversation_expiration_days = 0 in {cfg.config_file}.")
    choice = prompt_input("Delete these expired conversations now? [y/N] ").strip().lower()
    if choice not in {"y", "yes"}:
        print("Expired conversations were kept.")
        return

    deleted = 0
    for conv in expired:
        if store.delete_conversation(conv.id):
            deleted += 1
    print(f"Deleted {deleted} expired conversation(s).")


def nuke_targets(cfg: TuochatConfig) -> list[Path]:
    """Return centralized app-state paths that can be safely nuked."""
    targets: list[Path] = []
    data_dir = cfg.data_dir.resolve()
    log_dir = cfg.log_dir.resolve()

    if data_dir.is_dir():
        targets.extend(sorted(data_dir.iterdir(), key=lambda path: path.name.lower()))
    elif data_dir.exists():
        targets.append(data_dir)

    if log_dir != data_dir and log_dir.exists():
        targets.append(log_dir)

    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in targets:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(path)
    return deduped


def delete_path(path: Path) -> None:
    """Delete a file or directory tree."""
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def execute_pending_nuke(state: ReplState | None) -> None:
    """Delete centralized app state after stores are closed."""
    from tuochat import winlog  # noqa: PLC0415

    if state is None or not state.pending_nuke:
        return
    targets = nuke_targets(state.cfg)
    if not targets:
        print("Nuke complete: no centralized app data was present.")
        return
    deleted = 0
    failed = 0
    for path in targets:
        if not path.exists():
            continue
        try:
            delete_path(path)
            deleted += 1
        except OSError as e:
            print(f"Nuke failed to delete {path}: {e}", file=sys.stderr)
            failed += 1
    if failed:
        print(f"Nuke partial: deleted {deleted} path(s), failed to delete {failed} path(s).")
    else:
        print(f"Nuke complete: deleted {deleted} centralized path(s).")
    print(f"Config kept: {state.cfg.config_dir}")
    print(f"Workspace kept: {Path.cwd()}")
    winlog.report_event(
        winlog.EV_ADMIN_NUKE,
        f"tuochat nuke executed: {deleted} path(s) deleted, {failed} failed.",
        logging.WARNING,
    )


def print_help_section(section: str | None = None) -> None:
    """Print all help sections or one named section."""
    if section is None:
        print("Available commands:")
        print()
        for _key, title, lines in HELP_SECTIONS:
            print(f"{title}:")
            for line in lines:
                print(line)
            print()
        return
    title, lines = HELP_SECTION_LOOKUP[section]
    print(f"{title}:")
    for line in lines:
        print(line)


def print_help() -> None:
    """Show interactive slash commands."""
    print_help_section()


def print_shortcut_help() -> None:
    """Print active keyboard shortcuts for the current input backend."""
    from tuochat.cli.io import PromptToolkitBackend, get_backend, prompt_handler_var

    handler = prompt_handler_var.get()
    if handler is not None:
        print("Input backend: injected handler (GUI or test mode)")
        print("  Shortcuts are managed by the host application.")
        print()
        print("GUI (Tkinter) shortcuts:")
        print("  Alt+S       Submit message")
        print("  Ctrl+Z      Submit message")
        print("  Ctrl+D      Delete next character")
        print("  Ctrl+O      Insert newline")
        return

    backend = get_backend()
    if isinstance(backend, PromptToolkitBackend):
        print("Input backend: prompt-toolkit (rich terminal editing)")
        print()
        print("Submitting a message:")
        print("  Alt+S       Submit message")
        print("  Ctrl+Z      Submit message (or EOF when empty)")
        print()
        print("Editing (emacs-style):")
        print("  Ctrl+O      Insert newline")
        print("  Ctrl+A      Move to start of line")
        print("  Ctrl+E      Move to end of line")
        print("  Ctrl+K      Delete to end of line")
        print("  Ctrl+D      Delete next character (or EOF when empty)")
        print("  Ctrl+W      Delete previous word")
        print("  Alt+F       Move forward one word")
        print("  Alt+B       Move back one word")
        print()
        print("History:")
        print("  Up/Down     Cycle through history")
        print("  Ctrl+R      Reverse history search")
        print()
        print("Completion:")
        print("  Tab         Complete slash commands")
    else:
        print("Input backend: readline / input()")
        print()
        print("Submitting a message:")
        if sys.platform == "win32":
            print("  Ctrl+Z, Enter   Submit message (EOF)")
        else:
            print("  Ctrl+D          Submit message (EOF)")
        print()
        print("  Ctrl+C      Cancel current draft")
        print()
        if backend.supports_history:
            print("History:")
            print("  Up/Down     Cycle through history")
            print()
        if backend.supports_completion:
            print("Completion:")
            print("  Tab         Complete slash commands")
            print()
        if not backend.supports_history and not backend.supports_completion:
            print("(No readline module found — history and completion unavailable.)")


def print_help_menu() -> None:
    """Show the numbered top-level help menu."""
    sections = [
        (
            "Session and setup",
            [
                "/help - Show grouped help",
                "/help menu - Show the menu-style accessible help view",
                "/help-menu - Show this menu-style accessible help",
                "/tutorial - Run the tutorial",
                "/tutorial pick - Pick a lesson",
                "/status - Show current conversation status",
                "/config [json] - Show active configuration",
                "/doctor - Run diagnostics and connectivity checks",
                "/about - Show version, author, and license",
                "/setup - Re-run setup",
                "/shortcuts - Show keyboard shortcuts",
                "/model [duo|eliza|openrouter] - Choose the active model",
                "/duo-model - Probe or set the server-side Duo model",
                "/openrouter-model - List, set, or rotate OpenRouter models",
            ],
        ),
        (
            "Attachments and context",
            [
                "/files, /dir, /ls - List include-able files in cwd",
                "/approve-checks - Strip .check from safe draft files in cwd",
                "/diff - Show diffs for adjacent .check files in cwd",
                "/include, /attach [path|n] - Attach one file or a glob match",
                "/include-last - Re-include the last changed file",
                "/map [glob] [limit] - Build a recursive file map",
                "/code-map [glob] [limit] - Attach matching text files as one bundle",
                "/detach [path|n|all] - Remove pending attachments",
                "/skills - List discovered skills",
                "/skill [path|n] - Load a skill into the conversation",
                "/template [path|n] - Run a prompt template",
                "/custom - Pick custom instructions for the next conversation",
                "/agent-prompts - List discovered agent prompt files",
                "/agent-prompt [path|auto|none] - Select agent prompt mode",
                "/recipes - List available attachment recipes",
                "/recipe [name] - Preview and attach a recipe",
                "/context - Show current chat context summary",
                "/token-check - Estimate prompt size",
            ],
        ),
        (
            "Conversation history",
            [
                "/new - Start a fresh conversation",
                "/clear - Clear and start fresh",
                "/classify [marking] - Set document classification",
                "/usage - Show weekly token and cost usage",
                "/observability - Show 30-day Duo response performance data",
                "/update-bagit - Refresh archive-change hashes and metadata for saved archives",
                "/check-bagit - Check whether saved archives changed since the last BagIt update",
                "/title [new title] - Show or set the title",
                "/archive - Archive the current conversation",
                "/unarchive [n|all] - Restore archived conversations",
                "/resume [id|n] - Resume a saved conversation",
                "/delete [id|n] - Delete a saved conversation",
                "/search [query] - Search saved conversations",
                "/open - Open the conversation archive folder",
                "/log - Show the local command log",
            ],
        ),
        (
            "Output and safety",
            [
                "/stream on|off - Toggle streaming",
                "/mask on|off - Toggle sensitive-data masking",
                "/dot-timer on|off - Toggle dot timer",
                "/no-write on|off - Toggle local persistence",
                "/write-here-mode on|off - Write named generated files into cwd",
                "/approve-writes on|off - Ask before cwd writes in write-here mode",
                "/no-code-mode on|off - Hide shell-like code fences on screen",
                "/retry - Re-send the last user message",
                "/copy - Copy the latest assistant response",
            ],
        ),
        (
            "Exit and cleanup",
            [
                "/nuke - Delete centralized app data after double confirmation",
                "/exit - Exit the REPL",
            ],
        ),
    ]
    print("Help menu")
    print()
    for index, (title, _items) in enumerate(sections, start=1):
        print(f"{index}. {title}")
    print()
    print("Select 1-5 to open that section.")


def print_help_menu_section(selection: str) -> bool:
    """Print one help-menu section selected by number."""
    sections = [
        (
            "Session and setup",
            [
                "/help - Show grouped help",
                "/help menu - Show the menu-style accessible help view",
                "/help-menu - Show this menu-style accessible help",
                "/tutorial - Run the tutorial",
                "/tutorial pick - Pick a lesson",
                "/status - Show current conversation status",
                "/config [json] - Show active configuration",
                "/doctor - Run diagnostics and connectivity checks",
                "/about - Show version, author, and license",
                "/setup - Re-run setup",
                "/shortcuts - Show keyboard shortcuts",
                "/model [duo|eliza|openrouter] - Choose the active model",
                "/duo-model - Probe or set the server-side Duo model",
                "/openrouter-model - List, set, or rotate OpenRouter models",
            ],
        ),
        (
            "Attachments and context",
            [
                "/files, /dir, /ls - List include-able files in cwd",
                "/approve-checks - Strip .check from safe draft files in cwd",
                "/diff - Show diffs for adjacent .check files in cwd",
                "/include, /attach [path|n] - Attach one file or a glob match",
                "/include-last - Re-include the last changed file",
                "/map [glob] [limit] - Build a recursive file map",
                "/code-map [glob] [limit] - Attach matching text files as one bundle",
                "/detach [path|n|all] - Remove pending attachments",
                "/skills - List discovered skills",
                "/skill [path|n] - Load a skill into the conversation",
                "/template [path|n] - Run a prompt template",
                "/custom - Pick custom instructions for the next conversation",
                "/agent-prompts - List discovered agent prompt files",
                "/agent-prompt [path|auto|none] - Select agent prompt mode",
                "/recipes - List available attachment recipes",
                "/recipe [name] - Preview and attach a recipe",
                "/context - Show current chat context summary",
                "/token-check - Estimate prompt size",
            ],
        ),
        (
            "Conversation history",
            [
                "/new - Start a fresh conversation",
                "/clear - Clear and start fresh",
                "/classify [marking] - Set document classification",
                "/usage - Show weekly token and cost usage",
                "/observability - Show 30-day Duo response performance data",
                "/update-bagit - Refresh archive-change hashes and metadata for saved archives",
                "/check-bagit - Check whether saved archives changed since the last BagIt update",
                "/title [new title] - Show or set the title",
                "/archive - Archive the current conversation",
                "/unarchive [n|all] - Restore archived conversations",
                "/resume [id|n] - Resume a saved conversation",
                "/delete [id|n] - Delete a saved conversation",
                "/search [query] - Search saved conversations",
                "/open - Open the conversation archive folder",
                "/log - Show the local command log",
            ],
        ),
        (
            "Output and safety",
            [
                "/stream on|off - Toggle streaming",
                "/mask on|off - Toggle sensitive-data masking",
                "/dot-timer on|off - Toggle dot timer",
                "/no-write on|off - Toggle local persistence",
                "/write-here-mode on|off - Write named generated files into cwd",
                "/approve-writes on|off - Ask before cwd writes in write-here mode",
                "/no-code-mode on|off - Hide shell-like code fences on screen",
                "/retry - Re-send the last user message",
                "/copy - Copy the latest assistant response",
            ],
        ),
        (
            "Exit and cleanup",
            [
                "/nuke - Delete centralized app data after double confirmation",
                "/exit - Exit the REPL",
            ],
        ),
    ]
    if not selection.isdigit():
        return False
    index = int(selection) - 1
    if index < 0 or index >= len(sections):
        return False
    title, items = sections[index]
    print(f"{title}:")
    for item in items:
        print(item)
    return True


def resolve_help_topic(argument: str) -> str | None:
    """Resolve `/help` arguments to a known help topic."""
    topic = argument.strip().lower().replace("_", "-")
    if not topic:
        return None
    topic = re.sub(r"\s+", "-", topic)
    return HELP_TOPIC_ALIASES.get(topic)


def handle_slash_command(raw_input: str, state: ReplState) -> tuple[str | None, bool]:
    """Handle local slash commands.

    Returns (message_to_send, should_exit). A None message means no chat request
    should be sent.
    """
    normalized = normalize_command_candidate(raw_input)
    stripped = normalized.strip()
    bare_candidate = stripped.casefold()
    if bare_candidate in KNOWN_BARE_COMMANDS and "\n" not in stripped:
        execute = prompt_missing_slash_command(bare_candidate)
        if execute is None:
            print("Command cancelled.")
            return None, False
        if execute:
            normalized = "/" + bare_candidate
            stripped = normalized
        else:
            return raw_input, False
    if not stripped.startswith("/"):
        return raw_input, False

    parts = stripped.split(maxsplit=1)
    command = parts[0].lower()
    argument = parts[1] if len(parts) > 1 else ""
    command = SLASH_COMMAND_ALIASES.get(command, command)
    if command not in KNOWN_SLASH_COMMANDS:
        if word_count_limited(stripped) <= 3:
            print(f"Unknown slash command: {command}", file=sys.stderr)
            return None, False
        return raw_input, False
    if command != "/log":
        record_log_event(state, "slash", command=stripped)

    if command in {"/quit", "/exit"}:
        return None, True

    if command == "/help":
        topic = resolve_help_topic(argument)
        if topic == "menu":
            print_help_menu()
            selection = prompt_input("help> ").strip()
            if selection and not print_help_menu_section(selection):
                print("Selection out of range.", file=sys.stderr)
            return None, False
        if topic is not None:
            print_help_section(topic)
            return None, False
        if argument.strip():
            print("Usage: /help [menu|session|files|history|output|safety|exit]", file=sys.stderr)
            return None, False
        if blind_mode_enabled(state):
            print_help_menu()
            selection = prompt_input("help> ").strip()
            if selection and not print_help_menu_section(selection):
                print("Selection out of range.", file=sys.stderr)
        else:
            print_help()
        return None, False

    if command == "/help-menu":
        print_help_menu()
        selection = prompt_input("help> ").strip()
        if selection and not print_help_menu_section(selection):
            print("Selection out of range.", file=sys.stderr)
        return None, False

    if command == "/status":
        print_status(state)
        return None, False

    if command == "/config":
        fmt = "json" if argument.strip().lower() == "json" else "markdown"
        if argument.strip() and fmt != "json":
            print("Usage: /config [json]", file=sys.stderr)
            return None, False
        cmd_config(state.cfg, fmt=fmt)
        return None, False

    if command == "/doctor":
        from tuochat.cli.command_models import DoctorCommand
        from tuochat.cli.commands import local_cmd

        local_cmd.run_doctor_with_state(state.cfg, DoctorCommand(format="text"), streaming=state.streaming)
        return None, False

    if command == "/about":
        from tuochat.cli.rendering import print_about

        print_about()
        return None, False

    if command == "/setup":
        path = state.config_path or state.cfg.config_file
        choice = prompt_input(f"Update setup in {path}? [Y/n] ").strip().lower()
        if choice not in {"", "y", "yes"}:
            print("Setup cancelled.")
            return None, False
        new_path = run_init_wizard(config_path=path, force=True)
        state.cfg = load_config(str(new_path))
        state.provider = build_provider(state.cfg, timeout_override=state.timeout_override)
        state.config_path = new_path
        state.dot_timer_enabled = state.cfg.chat.dot_timer
        state.quiet = state.cfg.chat.quiet
        state.no_banner = state.cfg.chat.no_banner
        print("Setup updated for this session.")
        return None, False

    if command == "/model":
        selected = argument.strip().lower()
        blind_mode = blind_mode_enabled(state)
        if not selected:
            print(f"Current model: {MODEL_LABELS.get(state.active_model, state.active_model)}")
            print(f"{number_label(1, blind_mode=blind_mode)} Duo")
            print(f"{number_label(2, blind_mode=blind_mode)} Eliza")
            print(f"{number_label(3, blind_mode=blind_mode)} OpenRouter")
            selected = prompt_input("model> ").strip().lower()
            if not selected:
                print("Model selection cancelled.")
                return None, False
        if selected == "1":
            selected = "duo"
        elif selected == "2":
            selected = "eliza"
        elif selected == "3":
            selected = "openrouter"
        if selected not in MODEL_LABELS:
            print("Usage: /model [duo|eliza|openrouter]", file=sys.stderr)
            return None, False
        state.active_model = selected
        print(f"Active model: {MODEL_LABELS[selected]}")
        return None, False

    if command == "/openrouter-model":
        from tuochat.cli.commands.openrouter_model_cmd import handle_openrouter_model_command  # noqa: E402

        handle_openrouter_model_command(command, argument, state)
        return None, False

    if command == "/duo-model":
        from tuochat.cli.commands.duo_model_cmd import handle_duo_model_command  # noqa: E402

        handle_duo_model_command(command, argument, state)
        return None, False

    if command == "/tutorial":
        run_tutorial(state, argument.strip())
        return None, False

    if command == "/custom":
        custom_arg = argument.strip()
        if custom_arg.lower() in {"off", "none", "clear"}:
            state.pending_custom_path = None
            state.pending_custom_name = None
            print("Cleared pending custom instructions.")
            return None, False
        if custom_arg.lower() == "status":
            print(f"Pending custom instructions: {state.pending_custom_name or '(none)'}")
            return None, False

        candidates = list_available_custom_instructions(state.cfg)
        state.custom_candidates = candidates
        if not candidates:
            print(
                "No custom instruction files found in "
                f"{state.cfg.custom_instructions_dir}, {bundled_custom_instructions_dir()}, "
                f"or the workspace custom-instruction roots under {Path.cwd()}.",
                file=sys.stderr,
            )
            return None, False

        if not custom_arg:
            selected_path = pick_custom_instruction(candidates, state.cfg)
            if selected_path is None:
                print("Custom instruction selection cancelled.", file=sys.stderr)
                return None, False
        else:
            selected_path = resolve_custom_instruction_path(
                custom_arg, cfg=state.cfg, candidates=state.custom_candidates
            )
        if selected_path is None or not selected_path.is_file():
            print(f"Custom instruction file not found: {custom_arg}", file=sys.stderr)
            return None, False
        try:
            read_include_file(selected_path)
        except UnicodeDecodeError:
            print(f"Custom instruction file is not valid UTF-8 text: {selected_path}", file=sys.stderr)
            return None, False
        state.pending_custom_path = selected_path
        state.pending_custom_name = describe_custom_instruction_path(selected_path, state.cfg)
        print("Selected custom instructions for the next new conversation: " f"{state.pending_custom_name}")
        return None, False

    if command in ("/files", "/dir", "/ls"):
        print_files(state)
        return None, False

    if command == "/approve-checks":
        if argument.strip():
            print("Usage: /approve-checks", file=sys.stderr)
            return None, False
        from tuochat.cli.commands import files_cmd

        files_cmd.run_files_approve()
        return None, False

    if command == "/diff":
        if argument.strip():
            print("Usage: /diff", file=sys.stderr)
            return None, False
        from tuochat.cli.commands import files_cmd

        files_cmd.run_diff(prompt_continue=prompt_input)
        return None, False

    if command == "/agent-prompts":
        from tuochat.discovery.agent_prompts import describe_agent_prompt_path, list_available_agent_prompts

        candidates = list_available_agent_prompts()
        if not candidates:
            print("No agent prompt files found in the current directory.")
        else:
            print("Available agent prompt files:")
            for path in candidates:
                active_marker = " (active)" if path == state.active_agent_prompt_path else ""
                print(f"  - {describe_agent_prompt_path(path)}{active_marker}")
        return None, False

    if command == "/agent-prompt":
        from tuochat.context.composer import strip_agents_instructions_prefix
        from tuochat.discovery.agent_prompts import (
            auto_select_agent_prompt,
            describe_agent_prompt_path,
            list_available_agent_prompts,
        )

        if argument in (None, ""):
            current = state.active_agent_prompt_path
            mode = state.active_agent_prompt_mode
            if current:
                print(f"Agent prompt mode: {mode}  ({describe_agent_prompt_path(current)})")
            else:
                print(f"Agent prompt mode: {mode}")
            return None, False

        if argument == "none":
            state.include_agents_file = False
            state.active_agent_prompt_mode = "none"
            extra_custom_paths = [state.pending_custom_path] if state.pending_custom_path is not None else []
            prompt_without_agents = strip_agents_instructions_prefix(
                state.conv.system_prompt, state.active_agent_prompt_path
            )
            base = state.base_system_prompt if state.base_system_prompt is not None else prompt_without_agents
            state.conv.system_prompt, state.active_system_prompt_sources = compose_system_prompt(
                base,
                load_custom_instruction_sections(state.cfg, extra_paths=extra_custom_paths),
                include_agents=False,
            )
            print("Agent prompt: off")
            return None, False

        if argument == "auto":
            state.include_agents_file = True
            state.active_agent_prompt_mode = "auto"
            state.active_agent_prompt_path = None
            extra_custom_paths = [state.pending_custom_path] if state.pending_custom_path is not None else []
            prompt_without_agents = strip_agents_instructions_prefix(state.conv.system_prompt, None)
            base = state.base_system_prompt if state.base_system_prompt is not None else prompt_without_agents
            state.conv.system_prompt, state.active_system_prompt_sources = compose_system_prompt(
                base,
                load_custom_instruction_sections(state.cfg, extra_paths=extra_custom_paths),
                include_agents=True,
            )
            auto_path, _ = auto_select_agent_prompt()
            print(f"Agent prompt: auto (selected: {auto_path.name if auto_path else 'none found'})")
            return None, False

        # Try to match by path or filename
        selected_path = Path(argument)
        if not selected_path.is_absolute():
            selected_path = Path.cwd() / argument
        if not selected_path.is_file():
            # Try matching by name against discovered candidates
            candidates = list_available_agent_prompts()
            matches = [p for p in candidates if p.name in (argument, argument + ".md")]
            if not matches:
                print(f"Agent prompt file not found: {argument}", file=sys.stderr)
                return None, False
            selected_path = matches[0]
        state.active_agent_prompt_path = selected_path
        state.active_agent_prompt_mode = "selected"
        state.include_agents_file = True
        extra_custom_paths = [state.pending_custom_path] if state.pending_custom_path is not None else []
        prompt_without_agents = strip_agents_instructions_prefix(state.conv.system_prompt, selected_path)
        base = state.base_system_prompt if state.base_system_prompt is not None else prompt_without_agents
        state.conv.system_prompt, state.active_system_prompt_sources = compose_system_prompt(
            base,
            load_custom_instruction_sections(state.cfg, extra_paths=extra_custom_paths),
            include_agents=True,
            agent_prompt_path=selected_path,
        )
        print(f"Agent prompt set to: {describe_agent_prompt_path(selected_path)}")
        return None, False

    if command in ("/recipes", "/recipe"):
        from tuochat.context.recipes import expand_recipe, get_recipe, list_recipes

        if command == "/recipes" or not argument:
            recipes = list_recipes()
            print("Available recipes:")
            for recipe in recipes:
                print(f"  {recipe.name}  —  {recipe.display_name}: {recipe.description}")
            if command == "/recipe":
                print("Usage: /recipe <name>")
            return None, False

        found_recipe = get_recipe(argument)
        if found_recipe is None:
            print(f"Unknown recipe: {argument!r}", file=sys.stderr)
            print("Use /recipes to list available recipes.")
            return None, False

        match = expand_recipe(found_recipe)
        if not match.matched_paths:
            print(f"Recipe '{found_recipe.display_name}' matched no files in the current directory.")
            return None, False

        print(f"Recipe: {found_recipe.display_name}")
        print(
            f"  Matched: {len(match.matched_paths)} files  |  Skipped: {len(match.skipped_paths)}  |  ~{match.estimated_tokens:,} tokens"
        )
        if match.requires_preview:
            print("  Warning: large attachment")
        for path in match.matched_paths[:20]:
            print(f"    - {path}")
        if len(match.matched_paths) > 20:
            print(f"    ... and {len(match.matched_paths) - 20} more")

        choice = prompt_input("Attach this recipe? [y/N] ").strip().lower()
        if choice not in ("y", "yes"):
            print("Recipe attachment cancelled.")
            return None, False

        label = found_recipe.display_name
        payload = (
            f"Recipe attachment: {label}\n"
            f"({len(match.matched_paths)} files, ~{match.estimated_tokens:,} tokens)\n\n"
            f"{match.rendered}"
        )
        queue_attachment(state, Path(f"[recipe] {label}"), payload)
        print(f"Queued recipe '{label}' for next request.")
        return None, False

    if command == "/include":
        if argument:
            logger.debug("/include: argument=%r", argument)
            paths = select_include_candidates(argument, state)
            if paths is None:
                return None, False
            queued = 0
            for path in paths:
                message = prepare_include(path, state)
                if message is None:
                    logger.debug("/include: skipping unreadable file %s", path)
                    continue
                queue_attachment(state, path, message)
                print(f"Attached for next request: {path}")
                logger.debug("/include: queued %s", path)
                queued += 1
            if queued == 0:
                print("No files could be attached.", file=sys.stderr)
            elif queued > 1:
                print(f"({queued} files queued)")
            return None, False

        print_files(state)
        choice = prompt_input("include> ").strip()
        if not choice:
            print("Include cancelled.", file=sys.stderr)
            return None, False
        logger.debug("/include: interactive choice=%r", choice)
        paths = select_include_candidates(choice, state)
        if paths is None:
            return None, False
        queued = 0
        for path in paths:
            message = prepare_include(path, state)
            if message is None:
                continue
            queue_attachment(state, path, message)
            print(f"Attached for next request: {path}")
            queued += 1
        if queued == 0:
            print("No files could be attached.", file=sys.stderr)
        elif queued > 1:
            print(f"({queued} files queued)")
        return None, False

    if command == "/include-last":
        if state.last_include_path is None:
            print("No previous include to reuse.", file=sys.stderr)
            return None, False
        if is_context_ignored_path(state.last_include_path, ignore_root=Path.cwd()):
            print(f"Include file is excluded by ignore rules: {state.last_include_path}", file=sys.stderr)
            return None, False
        try:
            text, fingerprint, size = read_include_file(state.last_include_path)
        except UnicodeDecodeError:
            print(f"Include file is not valid UTF-8 text: {state.last_include_path}", file=sys.stderr)
            return None, False
        if fingerprint == state.last_include_hash:
            print("Last included file is unchanged; not re-including it.")
            return None, False
        state.last_include_hash = fingerprint
        state.last_include_size = size
        state.last_include_message = format_included_file(state.last_include_path, text)
        queue_attachment(state, state.last_include_path, state.last_include_message)
        print(f"Re-attached changed file for next request: {state.last_include_path}")
        return None, False

    if command == "/detach":
        if not (state.pending_attachment_names or []):
            print("No pending attachments to detach.")
            return None, False
        detach_arg = argument.strip()
        if not detach_arg:
            print_pending_attachments(state)
            detach_arg = prompt_input("detach> ").strip()
            if not detach_arg:
                print("Detach cancelled.")
                return None, False
        detach_pending_attachment(state, detach_arg)
        return None, False

    if command in {"/web", "/web-preview"}:
        from tuochat.web.attach import WebAttachError, fetch_and_render, format_preview

        web_cfg = state.cfg.web_attach
        if not web_cfg.enabled:
            print("Web attachments are disabled. Set web_attach.enabled = true in config.", file=sys.stderr)
            return None, False

        # Parse optional --engine <name> from the argument string
        engine_override: str | None = None
        raw_arg = argument.strip()
        engine_prefix = "--engine "
        if engine_prefix in raw_arg:
            before, _, after = raw_arg.partition(engine_prefix)
            engine_token, _, rest = after.partition(" ")
            engine_override = engine_token.strip() or None
            raw_arg = (before + rest).strip()

        url = raw_arg
        if not url:
            url = prompt_input("web> ").strip()
        if not url:
            print("Web fetch cancelled.", file=sys.stderr)
            return None, False

        engine_label = f" (engine: {engine_override})" if engine_override else ""
        print(f"Fetching {url}{engine_label} …")
        try:
            web_attachment = fetch_and_render(url, web_cfg, engine_override=engine_override)
        except WebAttachError as exc:
            print(f"Web fetch failed: {exc}", file=sys.stderr)
            return None, False

        if command == "/web-preview":
            preview_text = format_preview(
                url,
                web_attachment.fetch,
                web_attachment.page,
                web_cfg.preview_chars,
            )
            print(preview_text)
            choice = prompt_input("Attach this page to the next request? [y/N] ").strip().lower()
            if choice not in {"y", "yes"}:
                print("Web attachment cancelled.")
                return None, False

        synthetic = attachment_stub_name("web", url, ".md")
        queue_attachment(state, synthetic, web_attachment.attachment_text)
        title = web_attachment.page.metadata.title.strip() or url
        print(f"Attached for next request: {title}")
        return None, False

    if command == "/map":
        raw_parts = argument.split()
        map_limit = 100
        map_glob = None
        if raw_parts:
            if raw_parts[-1].isdigit():
                map_limit = max(1, int(raw_parts[-1]))
                raw_parts = raw_parts[:-1]
            if raw_parts:
                map_glob = raw_parts[0]
        matches = map_candidates(Path.cwd(), map_glob, map_limit)
        payload = render_map_attachment(Path.cwd(), matches, glob_pattern=map_glob, limit=map_limit)
        print(payload)
        choice = prompt_input("Attach this map to the next request? [y/N] ").strip().lower()
        if choice not in {"y", "yes"}:
            print("Map attachment cancelled.")
            return None, False
        synthetic = attachment_stub_name("workspace-map", map_glob, ".txt")
        queue_attachment(state, synthetic, payload)
        print("Map queued for the next request.")
        return None, False

    if command == "/code-map":
        raw_parts = argument.split()
        map_limit = 100
        map_glob = None
        if raw_parts:
            if raw_parts[-1].isdigit():
                map_limit = max(1, int(raw_parts[-1]))
                raw_parts = raw_parts[:-1]
            if raw_parts:
                map_glob = raw_parts[0]
        matches = code_map_candidates(Path.cwd(), map_glob, map_limit)
        payload = render_code_map_attachment(Path.cwd(), matches, glob_pattern=map_glob, limit=map_limit)
        print_attachment_estimate("Code map estimate", payload, file_count=len(matches))
        choice = prompt_input("Attach this code map to the next request? [y/N] ").strip().lower()
        if choice not in {"y", "yes"}:
            print("Code map attachment cancelled.")
            return None, False
        synthetic = attachment_stub_name("workspace-code-map", map_glob, ".md")
        queue_attachment(state, synthetic, payload)
        print("Code map queued for the next request.")
        return None, False

    if command in {"/new", "/reset"}:
        reset_repl_state(state)
        return None, False

    if command == "/clear":
        reset_repl_state(state)
        if not state.blind_mode:
            clear_screen()
        return None, False

    if command in {
        "/server-add",
        "/server-remove",
        "/server-current-items",
        "/server-query",
        "/server-retrieve",
        "/server-clear",
        "/server-get-item-content",
    }:
        handle_server_context_command(command, argument, state)
        return None, False

    if command == "/resource":
        from tuochat.cli.commands.resource_cmd import handle_resource_command  # noqa: E402

        handle_resource_command(command, argument, state)
        return None, False

    if command == "/git":
        from tuochat.git_info import get_git_status  # noqa: E402

        git = get_git_status()
        state.git_status = git
        if git is None:
            print("Not inside a git repository.")
        else:
            print(f"Git: {git.summary()}")
            print(f"  Root: {git.root}")
        return None, False

    if command == "/gl":
        from tuochat.cli.commands.gl_cmd import handle_gl_command  # noqa: E402

        handle_gl_command(command, argument, state)
        return None, False

    if command == "/jira":
        from tuochat.cli.commands.jira_cmd import handle_jira_command  # noqa: E402

        handle_jira_command(command, argument, state)
        return None, False

    if command == "/archive":
        if not state.conv.messages:
            print("Current conversation is empty; nothing to archive.", file=sys.stderr)
            return None, False
        choice = (
            prompt_input(f"Archive current conversation {state.conv.id[:8]} ({state.conv.title or 'Untitled'})? [y/N] ")
            .strip()
            .lower()
        )
        if choice not in {"y", "yes"}:
            print("Archive cancelled.")
            return None, False
        state.conv.archived = True
        state.store.save_conversation(state.conv)
        print(f"Archived conversation {state.conv.id[:8]}.")
        reset_repl_state(state)
        return None, False

    if command == "/unarchive":
        unarchive_arg = argument.strip().lower()
        if unarchive_arg == "all":
            restored = state.store.unarchive_all_conversations()
            print(f"Unarchived {restored} conversation(s).")
            return None, False

        if not unarchive_arg:
            target = pick_archived_candidate(state)
            if target is None:
                print("Unarchive cancelled.", file=sys.stderr)
                return None, False
        elif unarchive_arg.isdigit():
            archived_candidates = state.resume_candidates or state.store.list_archived_conversations(limit=20)
            state.resume_candidates = archived_candidates
            index = int(unarchive_arg) - 1
            if index < 0 or index >= len(archived_candidates):
                print("Selection out of range.", file=sys.stderr)
                return None, False
            target = archived_candidates[index]
        else:
            conv_id = resolve_archived_conversation_id(state.store, unarchive_arg)
            if conv_id is None:
                return None, False
            target_conv = state.store.get_conversation(conv_id)
            if target_conv is None:
                print(f"Conversation {conv_id} not found.", file=sys.stderr)
                return None, False
            target = target_conv

        if not state.store.set_conversation_archived(target.id, False):
            print(f"Conversation {target.id} could not be unarchived.", file=sys.stderr)
            return None, False
        print(f"Unarchived conversation {target.id[:8]}.")
        if state.conv.id == target.id:
            state.conv.archived = False
        return None, False

    if command == "/resume":
        resume_arg = argument.strip()
        if not resume_arg:
            target = pick_resume_candidate(state)
            if target is None:
                print("Resume cancelled.", file=sys.stderr)
                return None, False
        elif resume_arg.isdigit():
            recent_candidates = state.resume_candidates or state.store.list_conversations(limit=20)
            state.resume_candidates = recent_candidates
            index = int(resume_arg) - 1
            if index < 0 or index >= len(recent_candidates):
                print("Selection out of range.", file=sys.stderr)
                return None, False
            target = recent_candidates[index]
        else:
            conv_id = resolve_conversation_id(state.store, resume_arg)
            if conv_id is None:
                return None, False
            target_conv = state.store.get_conversation(conv_id)
            if target_conv is None:
                print(f"Conversation {conv_id} not found.", file=sys.stderr)
                return None, False
            target = target_conv

        if isinstance(state.provider, DuoProvider):
            state.provider.reset_conversation()
        switch_to_conversation(state, target)
        return None, False

    if command == "/delete":
        delete_arg = argument.strip()
        if not delete_arg:
            target = pick_resume_candidate(state)
            if target is None:
                print("Delete cancelled.", file=sys.stderr)
                return None, False
        elif delete_arg.isdigit():
            recent_candidates = state.resume_candidates or state.store.list_conversations(limit=20)
            state.resume_candidates = recent_candidates
            index = int(delete_arg) - 1
            if index < 0 or index >= len(recent_candidates):
                print("Selection out of range.", file=sys.stderr)
                return None, False
            target = recent_candidates[index]
        else:
            conv_id = resolve_conversation_id(state.store, delete_arg)
            if conv_id is None:
                return None, False
            target_conv = state.store.get_conversation(conv_id)
            if target_conv is None:
                print(f"Conversation {conv_id} not found.", file=sys.stderr)
                return None, False
            target = target_conv

        choice = (
            prompt_input(f"Delete conversation {target.id[:8]} ({target.title or 'Untitled'})? [y/N] ").strip().lower()
        )
        if choice not in {"y", "yes"}:
            print("Delete cancelled.")
            return None, False
        if not state.store.delete_conversation(target.id):
            print(f"Conversation {target.id} could not be deleted.", file=sys.stderr)
            return None, False
        print(f"Deleted conversation {target.id[:8]}.")
        if state.conv.id == target.id:
            reset_repl_state(state)
        return None, False

    if command == "/search":
        search_arg = argument.strip()
        if not search_arg:
            search_arg = prompt_input("search> ").strip()
            if not search_arg:
                print("Search cancelled.", file=sys.stderr)
                return None, False

        print_search_candidates(state, search_arg)
        search_results = state.search_candidates or []
        if not search_results:
            return None, False

        choice = prompt_input("resume result> ").strip()
        if not choice:
            print("Search selection cancelled.")
            return None, False
        if not choice.isdigit():
            print("Pick a numbered result to resume.", file=sys.stderr)
            return None, False

        index = int(choice) - 1
        if index < 0 or index >= len(search_results):
            print("Selection out of range.", file=sys.stderr)
            return None, False

        selected_result = search_results[index]
        selected_conv = state.store.get_conversation(selected_result.conversation_id)
        if selected_conv is None:
            print(f"Conversation {selected_result.conversation_id} not found.", file=sys.stderr)
            return None, False
        switch_to_conversation(state, selected_conv)
        return None, False

    if command == "/skills":
        from tuochat.cli.command_models import ListSkillsCommand
        from tuochat.cli.commands import context_cmd

        context_cmd.run_skills(state.cfg, ListSkillsCommand(format="text"))
        return None, False

    if command == "/skill":
        skill_arg = argument.strip()
        candidates = list_available_skills(state.cfg)
        state.skill_candidates = candidates
        if not candidates:
            print(
                (
                    f"No skill files found in {state.cfg.skills_dir}, "
                    f"{bundled_skills_dir()}, or the workspace skill roots under {Path.cwd()}."
                ),
                file=sys.stderr,
            )
            return None, False

        if not skill_arg:
            skill_path = pick_skill(candidates, state.cfg)
            if skill_path is None:
                print("Skill selection cancelled.", file=sys.stderr)
                return None, False
        else:
            skill_path = resolve_skill_path(skill_arg, cfg=state.cfg, candidates=state.skill_candidates)
        if skill_path is None or not skill_path.is_file():
            print(f"Skill file not found: {skill_arg}", file=sys.stderr)
            return None, False
        try:
            label, payload = render_skill_message(skill_path, state.cfg)
        except UnicodeDecodeError:
            print(f"Skill file is not valid UTF-8 text: {skill_path}", file=sys.stderr)
            return None, False
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return None, False
        new_msg = state.conv.add_message("user", payload)
        state.store.save_conversation(state.conv)
        state.store.save_message(new_msg)
        print(f"Loaded skill into the current conversation: {label}")
        return None, False

    if command == "/template":
        template_arg = argument.strip()
        candidates = list_available_templates(state.cfg)
        state.template_candidates = candidates
        if not candidates:
            print(
                (
                    f"No template files found in {state.cfg.templates_dir}, "
                    f"{bundled_templates_dir()}, or the workspace template roots under {Path.cwd()}."
                ),
                file=sys.stderr,
            )
            return None, False

        if not template_arg:
            template_path = pick_template(candidates, state.cfg)
            if template_path is None:
                print("Template selection cancelled.", file=sys.stderr)
                return None, False
        else:
            template_path = resolve_template_path(template_arg, cfg=state.cfg, candidates=state.template_candidates)
        if template_path is None or not template_path.is_file():
            print(f"Template file not found: {template_arg}", file=sys.stderr)
            return None, False

        body = template_body(template_path)
        if not body:
            print(f"Template file is empty: {template_path}", file=sys.stderr)
            return None, False

        def prompt_for_template_value(prompt_or_variable: str) -> str:
            prompt = (
                prompt_or_variable
                if prompt_or_variable.endswith(": ")
                else f"{humanize_report_key(prompt_or_variable)}: "
            )
            return prompt_input(prompt)

        try:
            rendered_prompt, template_values = resolve_template_prompt(
                body,
                prompt_for_value=prompt_for_template_value,
                cwd=Path.cwd(),
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return None, False

        state.pending_template_metadata = {
            "path": str(template_path),
            "label": describe_template_path(template_path, state.cfg),
            "name": parse_template_metadata(template_path)[0],
            **template_values,
        }
        return rendered_prompt, False

    if command == "/context":
        state.context_view_mode = argument.strip().lower() or None
        if state.context_view_mode not in {None, "all", "kb", "chars", "words", "tokens"}:
            print("Usage: /context [all|kb|chars|words|tokens]", file=sys.stderr)
            state.context_view_mode = None
            return None, False
        print_context(state)
        state.context_view_mode = None
        return None, False

    if command == "/token-check":
        print_token_check(state)
        return None, False

    if command == "/timeout":
        raw = argument.strip()
        if not raw:
            print_timeout_limits(state, reason="current session")
            print("This override is temporary for the current REPL session only.")
            return None, False
        if not raw.isdigit():
            print("Usage: /timeout [seconds]", file=sys.stderr)
            return None, False
        state.timeout_override = max(1, int(raw))
        state.provider = build_provider(state.cfg, timeout_override=state.timeout_override)
        print(f"Temporary timeout override set to {state.timeout_override}s for this session.")
        print_timeout_limits(state, reason="temporary override applied")
        return None, False

    if command == "/verbose":
        mode = argument.strip().lower()
        if not mode:
            state.verbose = not state.verbose
        elif mode in {"on", "off"}:
            state.verbose = mode == "on"
        else:
            print("Usage: /verbose [on|off]", file=sys.stderr)
            return None, False
        print(f"Verbose context reporting {'enabled' if state.verbose else 'disabled'}.")
        print_verbose_context(state)
        if state.verbose:
            print_timeout_limits(state, reason="verbose mode")
        return None, False

    if command == "/stream":
        mode = argument.strip().lower()
        if mode not in {"on", "off"}:
            print("Usage: /stream on|off", file=sys.stderr)
            return None, False
        if mode == "off" and not no_stream_mode_enabled(state.cfg):
            print(no_stream_hold_message(), file=sys.stderr)
            state.streaming = True
            return None, False
        state.streaming = mode == "on"
        print(f"Streaming {'enabled' if state.streaming else 'disabled'} for this session.")
        return None, False

    if command == "/mask":
        mode = argument.strip().lower()
        if mode not in {"on", "off"}:
            print("Usage: /mask on|off", file=sys.stderr)
            return None, False
        state.mask_output = mode == "on"
        print(f"On-screen masking {'enabled' if state.mask_output else 'disabled'} for this session.")
        if not state.mask_output:
            print(f"Reload with /resume {state.conv.id[:8]} to view this conversation without screen masking.")
        return None, False

    if command == "/dot-timer":
        mode = argument.strip().lower()
        if mode not in {"on", "off"}:
            print("Usage: /dot-timer on|off", file=sys.stderr)
            return None, False
        state.dot_timer_enabled = mode == "on"
        persist_chat_preferences(state)
        print(f"Dot timer {'enabled' if state.dot_timer_enabled else 'disabled'}.")
        return None, False

    if command == "/blind":
        mode = argument.strip().lower()
        if mode not in {"on", "off"}:
            print("Usage: /blind on|off", file=sys.stderr)
            return None, False
        toggle_blind_mode(state, mode == "on")
        return None, False

    if command == "/no-write":
        mode = argument.strip().lower()
        if not mode:
            print_no_write_help(not state.local_writes_enabled, blind_mode=blind_mode_enabled(state))
            mode = prompt_input("no-write> ").strip().lower()
            if not mode:
                print("No-write selection cancelled.")
                return None, False
        if mode == "1":
            mode = "on"
        elif mode == "2":
            mode = "off"
        if mode not in {"on", "off"}:
            print("Usage: /no-write on|off", file=sys.stderr)
            return None, False
        toggle_no_write(state, mode == "on")
        return None, False

    if command == "/write-here-mode":
        mode = argument.strip().lower()
        if not mode:
            print_write_here_help(state.cfg, blind_mode=blind_mode_enabled(state))
            mode = prompt_input("write-here-mode> ").strip().lower()
            if not mode:
                print("Write-here-mode selection cancelled.")
                return None, False
        if mode == "1":
            mode = "on"
        elif mode == "2":
            mode = "off"
        if mode not in {"on", "off"}:
            print("Usage: /write-here-mode on|off", file=sys.stderr)
            return None, False
        toggle_write_here_mode(state, mode == "on")
        return None, False

    if command == "/approve-writes":
        mode = argument.strip().lower()
        if not mode:
            print_approve_writes_help(state.cfg, blind_mode=blind_mode_enabled(state))
            mode = prompt_input("approve-writes> ").strip().lower()
            if not mode:
                print("Approve-writes selection cancelled.")
                return None, False
        if mode == "1":
            mode = "on"
        elif mode == "2":
            mode = "off"
        if mode not in {"on", "off"}:
            print("Usage: /approve-writes on|off", file=sys.stderr)
            return None, False
        toggle_approve_writes(state, mode == "on")
        return None, False

    if command == "/no-code-mode":
        mode = argument.strip().lower()
        if mode not in {"on", "off"}:
            print("Usage: /no-code-mode on|off", file=sys.stderr)
            return None, False
        state.no_code_mode = mode == "on"
        print(f"No-code-mode {'enabled' if state.no_code_mode else 'disabled'} for this session.")
        if state.no_code_mode:
            print("Shell-like fenced code will be replaced on screen with a safety placeholder.")
        else:
            print(f"Reload with /resume {state.conv.id[:8]} to view this conversation without no-code-mode.")
        return None, False

    if command == "/memory":
        from tuochat.workspace_memory import (
            MEMORY_FENCE_LANG,
            MEMORY_PROMPT,
            delete_pinned_file,
            extract_fence_content,
            memory_path,
            write_pinned_file,
        )

        mem_arg = argument.strip()

        if mem_arg.lower() == "clear":
            if delete_pinned_file(memory_path()):
                print("Workspace memory cleared.")
            else:
                print("No workspace memory file found.")
            return None, False

        if mem_arg:
            write_pinned_file(memory_path(), mem_arg)
            print(f"Workspace memory saved to {memory_path()}.")
            print("It will be included in all future conversations.")
            return None, False

        send_chat_turn(state, MEMORY_PROMPT)
        latest = latest_assistant_message(state.conv)
        if not latest:
            return None, False
        content = extract_fence_content(latest, MEMORY_FENCE_LANG)
        if content:
            write_pinned_file(memory_path(), content)
            print(f"\nWorkspace memory saved to {memory_path()}.")
            print("It will be included in all future conversations.")
        else:
            print("\nNo MEMORY block found in the response — nothing was saved.")
        return None, False

    if command == "/compact":
        from tuochat.workspace_memory import (
            COMPACT_FENCE_LANG,
            COMPACT_PROMPT,
            compact_path,
            extract_fence_content,
            write_pinned_file,
        )

        if not state.conv.messages:
            print("Nothing to compact — the conversation is empty.", file=sys.stderr)
            return None, False

        send_chat_turn(state, COMPACT_PROMPT)
        latest = latest_assistant_message(state.conv)
        if not latest:
            return None, False
        content = extract_fence_content(latest, COMPACT_FENCE_LANG)
        if not content:
            print("\nNo COMPACT block found in the response — nothing was saved.", file=sys.stderr)
            return None, False
        write_pinned_file(compact_path(), content)
        print(f"\nCompact summary saved to {compact_path()}.")
        print("Starting a new conversation with the summary pinned...")
        reset_repl_state(state)
        return None, False

    if command == "/todo":
        from tuochat.workspace_memory import (
            TODO_FENCE_LANG,
            TODO_PROMPT,
            delete_pinned_file,
            extract_fence_content,
            todo_path,
            write_pinned_file,
        )

        todo_arg = argument.strip()

        if todo_arg.lower() == "clear":
            if delete_pinned_file(todo_path()):
                print("Workspace todo list cleared.")
            else:
                print("No workspace todo file found.")
            return None, False

        send_chat_turn(state, TODO_PROMPT)
        latest = latest_assistant_message(state.conv)
        if not latest:
            return None, False
        content = extract_fence_content(latest, TODO_FENCE_LANG)
        if content:
            write_pinned_file(todo_path(), content)
            print(f"\nWorkspace todo list saved to {todo_path()}.")
            print("It will be included in all future conversations.")
        else:
            print("\nNo TODO block found in the response — nothing was saved.")
        return None, False

    if command == "/retry":
        if not state.last_user_input:
            print("There is no prior user message to retry.", file=sys.stderr)
            return None, False
        print("Retrying last user message...")
        return state.last_user_input, False

    if command == "/copy":
        latest = latest_assistant_message(state.conv)
        if latest is None:
            print("There is no assistant response to copy yet.", file=sys.stderr)
            return None, False
        copied, detail = copy_to_clipboard(latest)
        if copied:
            print(f"Copied latest assistant response: {detail}")
        else:
            print(f"Copy failed: {detail}", file=sys.stderr)
        return None, False

    if command == "/log":
        record_log_event(state, "slash", command=stripped)
        print_command_log(state)
        return None, False

    if command == "/open":
        if no_write_enabled(state.cfg):
            print(
                "Open is unavailable while /no-write is on because conversation files are not being written.",
                file=sys.stderr,
            )
            return None, False
        conv_dir, md_path, extracted = sync_conversation_artifacts(
            state.cfg, state.conv, classification=state.active_classification
        )
        if md_path is not None:
            update_saved_conversation_artifacts(state, md_path, extracted)
        if conv_dir is None:
            print("Open failed: conversation archive is unavailable.", file=sys.stderr)
            return None, False
        opened, detail = open_path(conv_dir)
        if opened:
            print(f"Opened conversation archive: {detail}")
            print(f"Markdown: {md_path}")
            print(f"Extracted files: {len(extracted)} in {conv_dir}")
        else:
            print(f"Open failed: {detail}", file=sys.stderr)
        return None, False

    if command == "/nuke":
        first = prompt_input("Really nuke centralized tuochat data? [y/N] ").strip().lower()
        if first not in {"y", "yes"}:
            print("Nuke cancelled.")
            return None, False
        targets = nuke_targets(state.cfg)
        print("This will delete the following centralized paths:")
        if targets:
            for path in targets:
                print(f"  {path}")
        else:
            print("  (nothing found to delete)")
        print(f"Config will be kept: {state.cfg.config_dir}")
        print(f"Current workspace will be kept: {Path.cwd()}")
        second = prompt_input("Really delete these paths? [y/N] ").strip().lower()
        if second not in {"y", "yes"}:
            print("Nuke cancelled.")
            return None, False
        state.pending_nuke = True
        print("Nuke scheduled. Closing this session first so files can be deleted cleanly...")
        return None, True

    if command == "/title":
        title = argument.strip()
        if not title:
            print(f"Current title: {state.conv.title or '(auto/unset)'}")
            return None, False
        state.conv.title = title
        state.store.save_conversation(state.conv)
        conv_dir, md_path, extracted = sync_conversation_artifacts(
            state.cfg, state.conv, classification=state.active_classification
        )
        if md_path is not None:
            update_saved_conversation_artifacts(state, md_path, extracted)
        print(f"Updated title: {state.conv.title}")
        if conv_dir is None or md_path is None:
            print("Conversation files: disabled (/no-write on)")
        else:
            print(f"Archive dir: {conv_dir}")
            print(f"Markdown: {md_path}")
            print(f"Extracted files: {len(extracted)}")
        return None, False

    if command == "/classify":
        classify_arg = argument.strip()
        if not classify_arg:
            chosen = prompt_classification(
                state.cfg, current=state.active_classification, default=state.last_classification
            )
            if chosen is None:
                print("Classification unchanged.", file=sys.stderr)
                return None, False
        else:
            chosen = resolve_classification_choice(state.cfg, classify_arg)
            if chosen is None:
                print(f"Unknown classification '{classify_arg}'. Pick from the list.", file=sys.stderr)
                return None, False
            if not classification_within_max(state.cfg, chosen):
                print(classification_limit_message(state.cfg), file=sys.stderr)
                return None, False
        state.active_classification = chosen
        state.last_classification = chosen
        print(f"Classification set to: {classification_help_label(chosen)}")
        return None, False

    if command == "/usage":
        from tuochat.cli.command_models import UsageCommand
        from tuochat.cli.commands import local_cmd

        local_cmd.run_usage(
            state.cfg,
            UsageCommand(format="text"),
            build_store=build_store,
            no_write_enabled=no_write_enabled,
            current_store=state.store,
        )
        return None, False

    if command == "/observability":
        from tuochat.cli.command_models import ObservabilityCommand
        from tuochat.cli.commands import local_cmd

        fmt = argument.strip() if argument.strip() in {"text", "json"} else "text"
        local_cmd.run_observability(
            state.cfg,
            ObservabilityCommand(format=fmt),
            build_store=build_store,
            no_write_enabled=no_write_enabled,
            current_store=state.store,
        )
        return None, False

    if command == "/update-bagit":
        from tuochat.cli.command_models import BagitUpdateCommand
        from tuochat.cli.commands import archive_cmd

        archive_cmd.run_bagit_update(
            state.cfg,
            BagitUpdateCommand(),
            build_store=build_store,
            no_write_enabled=no_write_enabled,
            load_bagit_module=load_bagit_module,
            refresh_archive_bagit_metadata=refresh_archive_bagit_metadata,
            current_conversation=state.conv,
            current_store=state.store,
        )
        return None, False

    if command == "/check-bagit":
        from tuochat.cli.command_models import BagitCheckCommand
        from tuochat.cli.commands import archive_cmd

        archive_cmd.run_bagit_check(
            state.cfg,
            BagitCheckCommand(format="text"),
            build_store=build_store,
            load_bagit_module=load_bagit_module,
            check_archive_bagit_status=check_archive_bagit_status,
            current_conversation=state.conv,
            current_store=state.store,
        )
        return None, False

    if command in ("/shortcut", "/shortcuts"):
        print_shortcut_help()
        return None, False

    return raw_input, False


def run_repl_loop(
    state: ReplState,
    *,
    resumed: bool,
    original_handler=None,
    sigint_handler=None,
) -> None:
    """Run the shared interactive REPL loop for new and resumed sessions."""
    while True:
        try:
            user_input, should_exit = read_user_message(quiet=state.quiet)
        except KeyboardInterrupt:
            if resumed:
                raise
            print()
            break
        if should_exit:
            break
        if user_input is None:
            continue
        if process_repl_submission(
            state,
            user_input,
            resumed=resumed,
            original_handler=original_handler,
            sigint_handler=sigint_handler,
        ):
            break


def process_repl_submission(
    state: ReplState,
    raw_input: str,
    *,
    resumed: bool = False,
    original_handler=None,
    sigint_handler=None,
) -> bool:
    """Process one submitted message or slash command.

    Returns True when the caller should exit the session loop.
    """
    if handle_bang_command(raw_input, state):
        return False

    user_input, should_exit = handle_slash_command(raw_input, state)
    if should_exit:
        return True
    if user_input is None or not user_input.strip():
        return False

    if resumed:
        send_chat_turn(state, user_input)
    else:
        send_chat_turn(
            state,
            user_input,
            original_handler=original_handler,
            sigint_handler=sigint_handler,
        )
    return False


def finalize_repl_session(state: ReplState | None, store, *, include_session_totals: bool) -> None:
    """Print the closing summary, close the store, and run pending cleanup."""
    print()
    if state is not None and not state.pending_nuke:
        print_chat_summary(state.conv, state if include_session_totals else None)
        if state.conv.messages:
            print(f"Conversation saved: {state.conv.id}")
            print_saved_conversation_files(state)
    store.close()
    execute_pending_nuke(state)


def cmd_chat(cfg: TuochatConfig, args: Any) -> int:
    """Interactive chat REPL."""
    from tuochat import winlog  # noqa: PLC0415

    cfg = maybe_run_first_run_setup(cfg, config_path=args.config if hasattr(args, "config") else None)
    warnings = cfg.validate()
    if warnings:
        for w in warnings:
            print(f"Warning: {w}", file=sys.stderr)

    if not cfg.gitlab.host or not cfg.gitlab.token:
        print("Error: GitLab host and token must be configured.", file=sys.stderr)
        print("  Set TUOCHAT_GITLAB_HOST and TUOCHAT_GITLAB_TOKEN env vars,", file=sys.stderr)
        print(f"  or create {cfg.config_file}", file=sys.stderr)
        winlog.report_event(
            winlog.EV_CONFIG_MISSING_REQUIRED,
            "tuochat CLI startup aborted: GitLab host or token not configured.",
            logging.ERROR,
        )
        return 1

    timeout_override = getattr(args, "timeout", None)
    provider = build_provider(cfg, timeout_override=timeout_override)

    state: ReplState | None = None
    store = build_store(cfg)
    print_expiration_warning(cfg)
    maybe_prune_expired_conversations(store, cfg)
    base_system_prompt = args.prompt
    base_resource_id = args.resource_id or cfg.chat.default_resource_id
    system_prompt, prompt_sources = compose_system_prompt(
        base_system_prompt,
        load_custom_instruction_sections(cfg),
    )
    conv = Conversation(
        resource_id=base_resource_id,
        system_prompt=system_prompt,
    )
    state = ReplState(
        conv=conv,
        store=store,
        provider=provider,
        cfg=cfg,
        streaming=resolve_streaming_enabled(cfg, no_stream_requested=args.no_stream),
        config_path=Path(args.config).expanduser() if getattr(args, "config", None) else None,
        timeout_override=timeout_override,
        quiet=cfg.chat.quiet,
        no_banner=cfg.chat.no_banner,
        blind_mode=cfg.chat.blind,
        debug=getattr(args, "debug", False),
        base_system_prompt=base_system_prompt,
        base_resource_id=base_resource_id,
        mask_output=cfg.chat.mask_output,
        dot_timer_enabled=cfg.chat.dot_timer,
        no_code_mode=False,
        active_model="duo",
        active_system_prompt_sources=prompt_sources,
        command_log=[],
        local_writes_enabled=not no_write_enabled(cfg),
    )
    apply_git_repo_write_here_default(cfg)

    if isinstance(provider, DuoProvider):
        provider.reset_conversation()

    # Ctrl+C during a streaming turn — cancel just that turn, stay in REPL
    def sigint_handler(_signum, _frame):
        return None

    original_handler = signal.getsignal(signal.SIGINT)

    configure_interactive_io(cfg)

    winlog.report_event(winlog.EV_STARTUP, f"tuochat CLI session started (host={cfg.gitlab.host!r}).")

    print_session_intro(state)
    if should_offer_first_run_tutorial(cfg):
        run_tutorial(state)

    # Prompt for classification on session start when enabled
    if getattr(getattr(cfg, "classification", None), "enabled", False) and getattr(
        getattr(cfg, "classification", None), "ask_per_conversation", True
    ):
        chosen = prompt_classification(cfg, upcoming=True)
        if chosen:
            state.active_classification = chosen
            print(f"Classification: {classification_help_label(chosen)}")

    try:
        run_repl_loop(
            state,
            resumed=False,
            original_handler=original_handler,
            sigint_handler=sigint_handler,
        )

    finally:
        shutdown_interactive_io()
        finalize_repl_session(state, store, include_session_totals=True)
        winlog.report_event(winlog.EV_SHUTDOWN, "tuochat CLI session ended.")

    return 0


def cmd_gui(cfg: TuochatConfig, args: Any) -> int:
    """Start the minimal Tkinter GUI front end."""
    from tuochat.gui.app import run_gui_app

    return run_gui_app(cfg, args)


def cmd_history(cfg, args) -> int:
    """List past conversations."""
    from tuochat.cli.command_models import HistoryCommand
    from tuochat.cli.commands import history_cmd

    return history_cmd.run(
        cfg,
        HistoryCommand(limit=args.limit),
        build_store=build_store,
        no_write_enabled=no_write_enabled,
    )


def resolve_conversation_id(store: ConversationStore | NullConversationStore, partial_id: str) -> str | None:
    """Resolve a partial conversation ID to a full one."""
    from tuochat.cli.commands.conversation_cmd import resolve_conversation_id as resolve_typed_conversation_id

    return resolve_typed_conversation_id(store, partial_id)


def resolve_archived_conversation_id(store: ConversationStore | NullConversationStore, partial_id: str) -> str | None:
    """Resolve a partial archived conversation ID to a full one."""
    from tuochat.cli.commands.conversation_cmd import resolve_conversation_id as resolve_typed_conversation_id

    return resolve_typed_conversation_id(store, partial_id, archived=True)


def pick_conversation_id(store: ConversationStore | NullConversationStore, prompt_label: str) -> str | None:
    """Prompt the user to select a conversation from recent history."""
    conversations = store.list_conversations(limit=20)
    if not conversations:
        print("No conversations found.", file=sys.stderr)
        return None

    print("Available conversations:")
    for idx, conv in enumerate(conversations, start=1):
        title = (conv.title or "Untitled")[:50]
        updated = conv.updated_at[:19] if conv.updated_at else ""
        print(f"[{idx}] {conv.id[:8]}  {title}  {updated}")

    choice = prompt_input(f"{prompt_label}> ").strip()
    if not choice:
        print("Selection cancelled.", file=sys.stderr)
        return None
    if choice.isdigit():
        index = int(choice) - 1
        if index < 0 or index >= len(conversations):
            print("Selection out of range.", file=sys.stderr)
            return None
        return conversations[index].id
    return resolve_conversation_id(store, choice)


def cmd_resume(cfg, args) -> int:
    """Resume a past conversation."""
    cfg = maybe_run_first_run_setup(cfg, config_path=args.config if hasattr(args, "config") else None)
    if not cfg.gitlab.host or not cfg.gitlab.token:
        print("Error: GitLab host and token must be configured.", file=sys.stderr)
        return 1

    state: ReplState | None = None
    if no_write_enabled(cfg):
        print(
            "Resume is unavailable while no-write mode is enabled because no local conversations are stored.",
            file=sys.stderr,
        )
        return 1
    store = build_store(cfg)
    try:
        print_expiration_warning(cfg)
        maybe_prune_expired_conversations(store, cfg)
        conv_id = pick_conversation_id(store, "resume") if not args.id else resolve_conversation_id(store, args.id)
        if conv_id is None:
            return 1

        conv = store.get_conversation(conv_id)
        if conv is None:
            print(f"Conversation {conv_id} not found.", file=sys.stderr)
            return 1

        # Load messages
        conv.messages = store.get_messages(conv_id)

        provider = build_provider(cfg)
        state = ReplState(
            conv=conv,
            store=store,
            provider=provider,
            cfg=cfg,
            streaming=resolve_streaming_enabled(cfg),
            config_path=Path(args.config).expanduser() if getattr(args, "config", None) else None,
            timeout_override=None,
            quiet=cfg.chat.quiet,
            no_banner=cfg.chat.no_banner,
            blind_mode=cfg.chat.blind,
            debug=getattr(args, "debug", False),
            base_system_prompt=conv.system_prompt,
            base_resource_id=conv.resource_id,
            mask_output=cfg.chat.mask_output,
            dot_timer_enabled=cfg.chat.dot_timer,
            no_code_mode=False,
            active_model="duo",
            active_system_prompt_sources=(
                ["saved conversation prompt (embedded in transcript)"] if conv.system_prompt else []
            ),
            command_log=[],
            resumed_context_pending=bool(conv.messages),
            local_writes_enabled=not no_write_enabled(cfg),
        )

        # Show conversation history
        conv_dir, md_path, extracted = sync_conversation_artifacts(
            cfg, conv, classification=state.active_classification
        )
        if state.blind_mode:
            announce_screen_transition("New conversation")
        else:
            clear_screen()
        print_session_intro(state)
        print_masked_conversation_transcript(state)
        if conv_dir is not None and md_path is not None:
            print(f"Archive dir: {conv_dir}")
            print(f"Markdown: {md_path}")
            print(f"Extracted files: {len(extracted)}")
        if state.resumed_context_pending:
            print()
            print("[Resumed conversation — prior context will be replayed to the LLM on your next message.]")
        print()

        configure_interactive_io(cfg)
        run_repl_loop(state, resumed=True)

    finally:
        shutdown_interactive_io()
        finalize_repl_session(state, store, include_session_totals=False)

    return 0


def cmd_search(cfg: TuochatConfig, args: Any) -> int:
    """Search saved conversations by message content."""
    from tuochat.cli.command_models import SearchCommand
    from tuochat.cli.commands import search_cmd

    return search_cmd.run(
        cfg,
        SearchCommand(
            query=list(args.query),
            limit=args.limit,
            title=args.title,
            after=args.after,
            before=args.before,
        ),
        build_store=build_store,
        no_write_enabled=no_write_enabled,
        run_conversation_search=run_conversation_search,
    )


def cmd_export(cfg: TuochatConfig, args: Any) -> int:
    """Export a conversation to filesystem artifacts and print their location."""
    from tuochat.cli.command_models import ExportCommand
    from tuochat.cli.commands import export_cmd

    return export_cmd.run(
        cfg,
        ExportCommand(id=args.id, meta=getattr(args, "meta", False)),
        build_store=build_store,
        no_write_enabled=no_write_enabled,
        pick_conversation_id=pick_conversation_id,
        resolve_conversation_id=resolve_conversation_id,
        sync_conversation_artifacts=sync_conversation_artifacts,
    )


__all__ = [
    "build_parser",
    "main",
    "week_start_iso",
    "cmd_config",
    "cmd_init",
    "is_exit_command",
    "normalize_command_candidate",
    "expiration_cutoff_iso",
    "maybe_prune_expired_conversations",
    "nuke_targets",
    "delete_path",
    "execute_pending_nuke",
    "format_included_file",
    "print_help_section",
    "print_help",
    "print_help_menu",
    "print_help_menu_section",
    "resolve_help_topic",
    "handle_slash_command",
    "process_repl_submission",
    "cmd_chat",
    "cmd_gui",
    "cmd_history",
    "resolve_conversation_id",
    "resolve_archived_conversation_id",
    "pick_conversation_id",
    "cmd_resume",
    "cmd_search",
    "cmd_export",
]
