"""Init command implementation."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from tuochat.cli.command_models import GlobalOptions, InitCommand


def run(
    global_options: GlobalOptions,
    command: InitCommand,
    *,
    run_init_wizard: Callable,
    default_config_file: Path,
) -> int:
    """Interactively create a config file."""
    target = str(global_options.config_path) if global_options.config_path is not None else str(default_config_file)
    try:
        run_init_wizard(config_path=target, force=command.force)
    except FileExistsError as exc:
        print(f"{exc}")
        print("Use `tuochat init --force` to overwrite, or `tuochat config` to view the current config.")
        return 1
    return 0
