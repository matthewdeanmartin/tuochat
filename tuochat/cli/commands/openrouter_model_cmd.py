"""Session-level OpenRouter model commands.

`/openrouter-model` lets the user inspect the configured rotation list,
pin a single model for the current session, clear the override, or
toggle rotation.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tuochat.cli.models import ReplState


def handle_openrouter_model_command(command_name: str, argument: str, state: ReplState) -> None:
    """Dispatch the /openrouter-model command family."""
    _ = command_name
    arg = argument.strip()
    parts = arg.split(maxsplit=1)
    subcommand = parts[0].lower() if parts else ""
    sub_rest = parts[1] if len(parts) > 1 else ""

    if subcommand in {"", "status"}:
        show_openrouter_model_status(state)
        return

    if subcommand == "list":
        list_openrouter_models(state)
        return

    if subcommand == "set":
        set_openrouter_model(state, sub_rest)
        return

    if subcommand == "clear":
        clear_openrouter_model(state)
        return

    if subcommand == "rotate":
        toggle_openrouter_rotation(state, sub_rest)
        return

    print_openrouter_model_help()


def show_openrouter_model_status(state: ReplState) -> None:
    """Show the current session selection and configured rotation list."""
    cfg = state.cfg.openrouter
    print(f"Selected OpenRouter model: {state.active_openrouter_model or '(use config rotation)'}")
    print(f"Default model: {cfg.model or '(none)'}")
    models = cfg.effective_models()
    if models:
        print("Rotation list:")
        for idx, model in enumerate(models, start=1):
            print(f"  {idx}. {model}")
    else:
        print("Rotation list: (empty — set OPENROUTER_MODELS or [openrouter].models)")
    print(f"Rotate models: {'on' if cfg.rotate_models else 'off'}")
    if not cfg.api_key:
        print("API key: (not set — run `tuochat openrouter login` or set OPENROUTER_API_KEY)")
    else:
        print(f"API key: ***{cfg.api_key[-4:]}")


def list_openrouter_models(state: ReplState) -> None:
    """List the configured rotation models."""
    models = state.cfg.openrouter.effective_models()
    if not models:
        print("No OpenRouter models configured. Set OPENROUTER_MODELS or OPENROUTER_MODEL.")
        return
    for idx, model in enumerate(models, start=1):
        marker = " *" if model == state.active_openrouter_model else ""
        print(f"  {idx}. {model}{marker}")


def set_openrouter_model(state: ReplState, value: str) -> None:
    """Pin a single model for the current session."""
    if not value.strip():
        print("Usage: /openrouter-model set <model-id>", file=sys.stderr)
        return
    state.active_openrouter_model = value.strip()
    print(f"Selected OpenRouter model: {state.active_openrouter_model}")


def clear_openrouter_model(state: ReplState) -> None:
    """Clear any session-level OpenRouter model override."""
    if state.active_openrouter_model is None:
        print("No OpenRouter model override is currently set.")
        return
    cleared = state.active_openrouter_model
    state.active_openrouter_model = None
    print(f"Cleared OpenRouter model override (was: {cleared}).")


def toggle_openrouter_rotation(state: ReplState, value: str) -> None:
    """Enable or disable rotation across the configured model list."""
    arg = value.strip().lower()
    if arg in {"on", "true", "1", "yes"}:
        state.cfg.openrouter.rotate_models = True
    elif arg in {"off", "false", "0", "no"}:
        state.cfg.openrouter.rotate_models = False
    elif arg == "":
        state.cfg.openrouter.rotate_models = not state.cfg.openrouter.rotate_models
    else:
        print("Usage: /openrouter-model rotate [on|off]", file=sys.stderr)
        return
    print(f"OpenRouter rotation: {'on' if state.cfg.openrouter.rotate_models else 'off'}")


def print_openrouter_model_help() -> None:
    """Print /openrouter-model usage."""
    print("OpenRouter model commands:")
    print("  /openrouter-model               — show current OpenRouter selection and config")
    print("  /openrouter-model list          — list configured rotation models")
    print("  /openrouter-model set <id>      — pin a session-level model override")
    print("  /openrouter-model clear         — clear the session model override")
    print("  /openrouter-model rotate [on|off] — toggle rotation across the configured list")
