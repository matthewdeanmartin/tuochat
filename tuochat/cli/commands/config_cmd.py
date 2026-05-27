"""Config command implementation."""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import TYPE_CHECKING

from tuochat.serialization import json_dumps

if TYPE_CHECKING:
    from tuochat.cli.command_models import ConfigCommand
    from tuochat.config import TuochatConfig


def run(
    cfg: TuochatConfig,
    command: ConfigCommand,
    *,
    render_markdown_config: Callable[[dict], str],
) -> int:
    """Show active configuration in markdown or JSON."""
    redacted = cfg.redacted()
    warnings = cfg.validate()
    if command.format == "json":
        print(json_dumps(redacted, indent=True))
        if warnings:
            for warning in warnings:
                print(warning, file=sys.stderr)
    else:
        print(render_markdown_config(redacted))
        if warnings:
            print("\nWarnings:")
            for warning in warnings:
                print(f"  - {warning}")
    return 0
