"""Lightweight CLI entrypoint focused on fast parser startup."""

# pylint: disable=import-outside-toplevel
from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from tuochat.__about__ import __version__
from tuochat.cli.utils.cli_suggestions import SmartParser

if TYPE_CHECKING:
    from tuochat.cli.command_models import GlobalOptions
    from tuochat.config import TuochatConfig


def build_parser() -> SmartParser:
    """Build the root argparse parser without importing the full REPL stack."""
    parser = SmartParser(
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

    def add_auto_format_argument(command_parser: argparse.ArgumentParser) -> None:
        """Add --format for automation commands (markdown default)."""
        command_parser.add_argument(
            "--format",
            choices=("markdown", "json"),
            default="markdown",
            help="Output format: markdown (default, LLM-friendly) or json (machine-readable)",
        )

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
        command_parser.add_argument(
            "--web", action="append", default=[], metavar="URL", help="Fetch a web page and attach it"
        )
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

    def add_automation_send_arguments(command_parser: argparse.ArgumentParser, *, include_system_prompt: bool) -> None:
        """Add the shared attachment + prompt-building flags for chat new / chat send."""
        command_parser.add_argument("message", nargs="?", help="Prompt text (positional)")
        command_parser.add_argument("--file", type=Path, dest="prompt_file", help="Read the prompt from a file")
        command_parser.add_argument("--stdin", action="store_true", help="Read the prompt from stdin")
        command_parser.add_argument(
            "--include", action="append", type=Path, default=[], help="Attach a local file to this turn"
        )
        command_parser.add_argument(
            "--web", action="append", default=[], metavar="URL", help="Fetch a web page and attach it"
        )
        command_parser.add_argument("--skill", help="Attach a discovered skill by name or path")
        command_parser.add_argument("--template", help="Render a discovered template by name or path")
        command_parser.add_argument("--var", action="append", default=[], help="Template variable as NAME=value")
        command_parser.add_argument("--output-file", type=Path, help="Write the response text to a file")
        command_parser.add_argument("--no-stream", action="store_true", help="Disable stdout streaming")
        command_parser.add_argument("--timeout", type=int, help="Override the provider timeout")
        command_parser.add_argument(
            "--model",
            choices=("duo", "eliza", "openrouter"),
            default="duo",
            help="Model to use (default: duo)",
        )
        command_parser.add_argument(
            "--cwd", type=Path, help="Override the working directory for this turn (saved back to conversation)"
        )
        add_auto_format_argument(command_parser)
        if include_system_prompt:
            command_parser.add_argument("--system-prompt", help="System prompt for the new conversation")
            command_parser.add_argument("--resource-id", help="GitLab project/group GID for context")

    subparsers = parser.add_subparsers(dest="command", title="commands")

    # ---------------------------------------------------------------------------
    # `chat` — automation namespace (new primary surface for LLM-driven workflows)
    # ---------------------------------------------------------------------------
    chat_parser = subparsers.add_parser(
        "chat",
        help="Automation-friendly non-interactive chat (use `repl` for the interactive REPL)",
        description=(
            "Non-interactive automation commands. "
            "Each subcommand runs one action and exits. "
            "Use `tuochat repl` for the interactive REPL."
        ),
    )
    chat_subparsers = chat_parser.add_subparsers(dest="chat_command")
    chat_parser.set_defaults(command_key="chat-help", help_parser=chat_parser)

    chat_new_parser = chat_subparsers.add_parser(
        "new",
        help="Create a new conversation and optionally send the first message",
    )
    chat_new_parser.set_defaults(command_key="chat-new")
    add_automation_send_arguments(chat_new_parser, include_system_prompt=True)

    chat_send_parser = chat_subparsers.add_parser(
        "send",
        help="Send one message to an existing conversation and exit",
    )
    chat_send_parser.set_defaults(command_key="chat-send")
    chat_send_parser.add_argument(
        "--conversation",
        "-c",
        default="latest",
        metavar="ID_OR_LATEST",
        help='Conversation ID prefix or "latest" (default: latest)',
    )
    chat_send_parser.add_argument(
        "--restore-cwd",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Restore the saved conversation cwd before resolving relative paths (default: on)",
    )
    chat_send_parser.add_argument(
        "--fail-if-missing",
        action="store_true",
        help="Exit with error if the conversation does not exist instead of creating a new one",
    )
    add_automation_send_arguments(chat_send_parser, include_system_prompt=False)

    chat_show_parser = chat_subparsers.add_parser(
        "show",
        help="Show conversation metadata and current state",
    )
    chat_show_parser.set_defaults(command_key="chat-show")
    chat_show_parser.add_argument(
        "--conversation",
        "-c",
        default="latest",
        metavar="ID_OR_LATEST",
        help='Conversation ID prefix or "latest" (default: latest)',
    )
    chat_show_parser.add_argument("--fail-if-missing", action="store_true")
    add_auto_format_argument(chat_show_parser)

    chat_latest_parser = chat_subparsers.add_parser(
        "latest",
        help="Show the most recent active conversation",
    )
    chat_latest_parser.set_defaults(command_key="chat-latest")
    add_auto_format_argument(chat_latest_parser)

    # ---------------------------------------------------------------------------
    # `repl` and `interactive` — explicit names for the interactive REPL
    # ---------------------------------------------------------------------------
    for repl_name in ("repl", "interactive"):
        repl_p = subparsers.add_parser(
            repl_name,
            help="Start the interactive REPL",
            description="Interactive GitLab Duo Chat REPL",
        )
        repl_p.set_defaults(command_key="repl")
        add_chat_session_arguments(repl_p)

    gui_parser = subparsers.add_parser("gui", help="Start the minimal Tkinter chat window")
    gui_parser.set_defaults(command_key="gui")
    add_chat_session_arguments(gui_parser)

    config_parser = subparsers.add_parser("config", help="Show active configuration")
    config_parser.set_defaults(command_key="config")
    config_parser.add_argument(
        "format",
        nargs="?",
        default="markdown",
        choices=("markdown", "json"),
        help="Output format",
    )

    init_parser = subparsers.add_parser("init", help="Create a starter config file")
    init_parser.set_defaults(command_key="init")
    init_parser.add_argument("--force", action="store_true", help="Overwrite an existing config file")

    auth_parser = subparsers.add_parser("auth", help="Manage GitLab credentials (PAT or OAuth)")
    auth_subparsers = auth_parser.add_subparsers(dest="auth_action")
    for action, helptext in (
        ("login", "Sign in via PAT or OAuth, store credentials in keyring or config"),
        ("status", "Show the credential type, expiry, and storage location"),
        ("logout", "Remove stored credentials for the active GitLab host"),
        ("refresh", "Trade the stored OAuth refresh token for a fresh access token"),
    ):
        sub = auth_subparsers.add_parser(action, help=helptext)
        sub.set_defaults(command_key="auth", auth_action=action)
    auth_parser.set_defaults(command_key="auth", auth_action="login")

    openrouter_parser = subparsers.add_parser(
        "openrouter", help="Manage the OpenRouter API key (alternative to Duo)"
    )
    openrouter_subparsers = openrouter_parser.add_subparsers(dest="openrouter_action")
    for action, helptext in (
        ("login", "Prompt for an OpenRouter API key and store it in keyring or config"),
        ("status", "Show whether an OpenRouter API key is on file and where"),
        ("logout", "Remove the stored OpenRouter API key"),
    ):
        sub = openrouter_subparsers.add_parser(action, help=helptext)
        sub.set_defaults(command_key="openrouter", openrouter_action=action)
    openrouter_parser.set_defaults(command_key="openrouter", openrouter_action="status")

    doctor_parser = subparsers.add_parser("doctor", help="Run local config and path checks")
    doctor_parser.set_defaults(command_key="doctor")
    add_format_argument(doctor_parser)

    diff_parser = subparsers.add_parser("diff", help="Show diffs for adjacent .check files in the current workspace")
    diff_parser.set_defaults(command_key="diff")

    usage_parser = subparsers.add_parser("usage", help="Show weekly token and cost usage")
    usage_parser.set_defaults(command_key="usage")
    add_format_argument(usage_parser)

    observability_parser = subparsers.add_parser(
        "observability",
        help="Show 30-day Duo response performance and outcome data",
    )
    observability_parser.set_defaults(command_key="observability")
    add_format_argument(observability_parser)

    convo_parser = subparsers.add_parser("convo", help="Manage saved conversations")
    convo_subparsers = convo_parser.add_subparsers(dest="convo_command")

    convo_list_parser = convo_subparsers.add_parser("list", help="List saved conversations")
    convo_list_parser.set_defaults(command_key="convo-list")
    convo_list_parser.add_argument("--limit", "-n", type=int, default=20, help="Max conversations to show")
    convo_list_parser.add_argument("--archived", action="store_true", help="Show archived conversations")
    add_format_argument(convo_list_parser)

    convo_resume_parser = convo_subparsers.add_parser("resume", help="Resume a saved conversation")
    convo_resume_parser.set_defaults(command_key="convo-resume")
    convo_resume_parser.add_argument("id", nargs="?", help="Conversation ID (or prefix)")

    convo_search_parser = convo_subparsers.add_parser("search", help="Search saved conversations")
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

    convo_export_parser = convo_subparsers.add_parser("export", help="Export a conversation")
    convo_export_parser.set_defaults(command_key="convo-export")
    convo_export_parser.add_argument("id", nargs="?", help="Conversation ID (or prefix)")
    convo_export_parser.add_argument(
        "--meta", action="store_true", help="Print archive path and file list instead of conversation text"
    )

    convo_open_parser = convo_subparsers.add_parser("open", help="Open a conversation export path")
    convo_open_parser.set_defaults(command_key="convo-open")
    convo_open_parser.add_argument("id", nargs="?", help="Conversation ID (or prefix)")

    convo_archive_parser = convo_subparsers.add_parser("archive", help="Archive a saved conversation")
    convo_archive_parser.set_defaults(command_key="convo-archive")
    convo_archive_parser.add_argument("id", nargs="?", help="Conversation ID (or prefix)")

    convo_unarchive_parser = convo_subparsers.add_parser("unarchive", help="Unarchive one or all conversations")
    convo_unarchive_parser.set_defaults(command_key="convo-unarchive")
    convo_unarchive_parser.add_argument("id", nargs="?", help="Conversation ID (or prefix)")
    convo_unarchive_parser.add_argument("--all", action="store_true", help="Unarchive every archived conversation")

    convo_delete_parser = convo_subparsers.add_parser("delete", help="Delete a saved conversation")
    convo_delete_parser.set_defaults(command_key="convo-delete")
    convo_delete_parser.add_argument("id", nargs="?", help="Conversation ID (or prefix)")

    archive_parser = subparsers.add_parser("archive", help="Manage saved archive metadata")
    archive_subparsers = archive_parser.add_subparsers(dest="archive_command")

    archive_bagit_update = archive_subparsers.add_parser(
        "bagit-update", help="Refresh archive-change hashes and metadata"
    )
    archive_bagit_update.set_defaults(command_key="archive-bagit-update")

    archive_bagit_check = archive_subparsers.add_parser(
        "bagit-check", help="Check whether archives changed since the last BagIt update"
    )
    archive_bagit_check.set_defaults(command_key="archive-bagit-check")
    add_format_argument(archive_bagit_check)

    context_parser = subparsers.add_parser("context", help="Discover local context sources")
    context_subparsers = context_parser.add_subparsers(dest="context_command")

    context_files = context_subparsers.add_parser("files", help="List include-able local files")
    context_files.set_defaults(command_key="context-files")
    add_format_argument(context_files)

    context_skills = context_subparsers.add_parser("skills", help="List discovered skills")
    context_skills.set_defaults(command_key="context-skills")
    add_format_argument(context_skills)

    context_templates = context_subparsers.add_parser("templates", help="List discovered templates")
    context_templates.set_defaults(command_key="context-templates")
    add_format_argument(context_templates)

    context_custom = context_subparsers.add_parser("custom-instructions", help="List discovered custom instructions")
    context_custom.set_defaults(command_key="context-custom-instructions")
    add_format_argument(context_custom)

    files_parser = subparsers.add_parser("files", help="Manage local .check files in the current workspace")
    files_subparsers = files_parser.add_subparsers(dest="files_command")
    files_parser.set_defaults(command_key="files-help", help_parser=files_parser)

    files_approve = files_subparsers.add_parser(
        "approve",
        help="Rename .check files by stripping the suffix when there is no name clash",
    )
    files_approve.set_defaults(command_key="files-approve")

    files_delete = files_subparsers.add_parser("delete", help="Delete .check files in the current workspace")
    files_delete.set_defaults(command_key="files-delete")
    files_delete.add_argument("--yes", action="store_true", help="Delete without asking for confirmation")

    headless_parser = subparsers.add_parser("headless", help="Run non-interactive chat flows")
    headless_subparsers = headless_parser.add_subparsers(dest="headless_command")

    headless_ask = headless_subparsers.add_parser("ask", help="Start a new non-interactive conversation")
    headless_ask.set_defaults(command_key="headless-ask")
    add_headless_arguments(headless_ask, include_system_prompt=True)

    headless_continue = headless_subparsers.add_parser("continue", help="Continue a saved conversation")
    headless_continue.set_defaults(command_key="headless-continue")
    headless_continue.add_argument(
        "id",
        help='Conversation ID (or prefix), or "ongoing" to keep Duo server-side continuity',
    )
    add_headless_arguments(headless_continue, include_system_prompt=False)

    history_parser = subparsers.add_parser("history", help="Alias for `convo list`")
    history_parser.set_defaults(command_key="history")
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
    export_parser.add_argument(
        "--meta", action="store_true", help="Print archive path and file list instead of conversation text"
    )

    selfcheck_parser = subparsers.add_parser(
        "selfcheck",
        help="Supply-chain safety: check for updates, audit, self-upgrade",
    )
    selfcheck_parser.set_defaults(command_key="selfcheck")
    selfcheck_parser.add_argument(
        "selfcheck_argv",
        nargs=argparse.REMAINDER,
        help="Arguments passed through to tuochat.self_pkg_mgmt CLI",
    )
    return parser


def global_options_from_args(args: argparse.Namespace) -> GlobalOptions:
    """Translate argparse output into global options."""
    # Keep bootstrap imports lazy so --help/--version avoid the full CLI stack.
    from tuochat.cli import bootstrap  # noqa: E402
    from tuochat.cli.command_models import GlobalOptions  # noqa: E402

    return GlobalOptions(
        debug=getattr(args, "debug", False),
        config_path=bootstrap.config_path_for(args),
        no_banner=getattr(args, "no_banner", False),
        quiet=getattr(args, "quiet", False),
        blind=getattr(args, "blind", False),
    )


def load_config(config_path: Path | str | None = None) -> TuochatConfig:
    """Load config from the requested path or default locations."""
    # Delay config loading helpers until a real command needs configuration.
    from tuochat.config import load_config as config_load_config  # noqa: E402

    return config_load_config(str(config_path) if config_path is not None else None)


def load_config_with_cli_overrides(config_path: Path | str | GlobalOptions | None = None) -> TuochatConfig:
    """Load config from the requested path or default locations."""
    # Logging and config overrides are only needed after argument parsing succeeds.
    from tuochat.cli import bootstrap  # noqa: E402
    from tuochat.cli.command_models import GlobalOptions  # noqa: E402
    from tuochat.logging_config import setup_logging  # noqa: E402

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
    parser = build_parser()
    args = parser.parse_args(argv)
    global_options = global_options_from_args(args)
    cfg = load_config_with_cli_overrides(global_options)

    command_key = getattr(args, "command_key", None)

    help_parser = getattr(args, "help_parser", None)

    if command_key == "chat-help":
        # `tuochat chat` with no subcommand — print the chat subparser help
        if help_parser is not None:
            help_parser.print_help()
            return 0
        parser.print_help()
        return 0

    if command_key == "files-help":
        if help_parser is not None:
            help_parser.print_help()
            return 0
        parser.print_help()
        return 0

    if command_key is None:
        # First-run helpers are only needed for the bare interactive entrypoint.
        from tuochat.cli.setup import is_first_run, run_init_wizard  # noqa: E402

        if is_first_run(
            cfg, config_path=str(global_options.config_path) if global_options.config_path is not None else None
        ):
            run_init_wizard(
                config_path=str(global_options.config_path) if global_options.config_path is not None else None,
                force=True,
            )
            print("Setup complete. Start chatting with `tuochat repl` or use `tuochat chat new`.")
            return 0
        parser.print_help()
        return 0

    # Delay command dispatch imports until we know which command is actually running.
    from tuochat.cli import dispatch as cli_dispatch  # noqa: E402

    command = cli_dispatch.command_from_args(args)
    if command is None:
        parser.print_help()
        return 0

    from tuochat.security.startup_audit import run_startup_audit  # noqa: E402

    if not run_startup_audit(cfg):
        return 1

    return cli_dispatch.dispatch_command(cfg, global_options, command)
