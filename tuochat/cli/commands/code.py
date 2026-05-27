"""Command handlers that accept typed command models instead of argparse namespaces."""

from __future__ import annotations

import argparse
from types import SimpleNamespace
from typing import TYPE_CHECKING

from tuochat.cli.repl import cmd_chat, cmd_config, cmd_export, cmd_gui, cmd_history, cmd_init, cmd_resume, cmd_search

if TYPE_CHECKING:
    from tuochat.cli.command_models import (
        ChatCommand,
        ConfigCommand,
        ExportCommand,
        GlobalOptions,
        GuiCommand,
        HistoryCommand,
        InitCommand,
        ResumeCommand,
        SearchCommand,
    )
    from tuochat.config import TuochatConfig


def run_config(cfg: TuochatConfig, command: ConfigCommand) -> int:
    """Run the config command."""
    return cmd_config(cfg, fmt=command.format)


def run_init(global_options: GlobalOptions, command: InitCommand) -> int:
    """Run the init command."""
    args = argparse.Namespace(
        config=str(global_options.config_path) if global_options.config_path is not None else None,
        force=command.force,
    )
    return cmd_init(args)


def run_chat(cfg: TuochatConfig, global_options: GlobalOptions, command: ChatCommand) -> int:
    """Run the chat command."""
    args = SimpleNamespace(
        config=str(global_options.config_path) if global_options.config_path is not None else None,
        prompt=command.prompt,
        resource_id=command.resource_id,
        no_stream=command.no_stream,
        timeout=command.timeout,
        debug=global_options.debug,
    )
    return cmd_chat(cfg, args)


def run_gui(cfg: TuochatConfig, global_options: GlobalOptions, command: GuiCommand) -> int:
    """Run the minimal Tkinter GUI command."""
    args = SimpleNamespace(
        config=str(global_options.config_path) if global_options.config_path is not None else None,
        prompt=command.prompt,
        resource_id=command.resource_id,
        no_stream=command.no_stream,
        timeout=command.timeout,
        debug=global_options.debug,
    )
    return cmd_gui(cfg, args)


def run_history(cfg: TuochatConfig, command: HistoryCommand) -> int:
    """Run the history command."""
    return cmd_history(cfg, SimpleNamespace(limit=command.limit))


def run_resume(cfg: TuochatConfig, command: ResumeCommand) -> int:
    """Run the resume command."""
    return cmd_resume(cfg, SimpleNamespace(id=command.id))


def run_search(cfg: TuochatConfig, command: SearchCommand) -> int:
    """Run the search command."""
    args = SimpleNamespace(
        query=command.query,
        limit=command.limit,
        title=command.title,
        after=command.after,
        before=command.before,
    )
    return cmd_search(cfg, args)


def run_export(cfg: TuochatConfig, command: ExportCommand) -> int:
    """Run the export command."""
    return cmd_export(cfg, SimpleNamespace(id=command.id, meta=command.meta))
