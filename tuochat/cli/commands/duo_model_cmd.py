"""Server-side Duo model probing and session-level selection commands."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from tuochat.provider.duo import DuoProvider

if TYPE_CHECKING:
    from tuochat.cli.models import ReplState


def handle_duo_model_command(command_name: str, argument: str, state: ReplState) -> None:
    """Dispatch the /duo-model command family."""
    _ = command_name
    provider = state.provider
    if not isinstance(provider, DuoProvider):
        print("Duo is not configured for this session.", file=sys.stderr)
        return

    arg = argument.strip()
    parts = arg.split(maxsplit=1)
    subcommand = parts[0].lower() if parts else ""
    sub_rest = parts[1] if len(parts) > 1 else ""

    if subcommand in {"", "status"}:
        show_duo_model_status(state, provider, refresh=False)
        return

    if subcommand in {"probe", "refresh"}:
        show_duo_model_status(state, provider, refresh=True)
        return

    if subcommand == "set":
        set_duo_model(state, provider, sub_rest)
        return

    if subcommand == "clear":
        clear_duo_model(state)
        return

    if subcommand == "list":
        list_duo_models(state, provider)
        return

    print_duo_model_help()


def show_duo_model_status(state: ReplState, provider: DuoProvider, *, refresh: bool) -> None:
    """Show the current session selection and backend support status."""
    support = provider.probe_duo_chat_model_support(refresh=refresh)
    print(f"Selected Duo model: {state.active_duo_model or '(auto/default)'}")
    if support.supported:
        print(f"Server-side Duo model field: {support.request_field}")
        print("Use /duo-model set <backend-model-id> to pin a specific server-side model.")
    else:
        print("Server-side Duo model selection is not supported by this GitLab instance.")
        if support.reason:
            print(f"Reason: {support.reason}")


def set_duo_model(state: ReplState, provider: DuoProvider, value: str) -> None:
    """Set the session-level server-side Duo model value."""
    if not value.strip():
        print("Usage: /duo-model set <backend-model-id>", file=sys.stderr)
        return

    support = provider.probe_duo_chat_model_support()
    if not support.supported:
        print("This GitLab instance does not support server-side Duo model selection.", file=sys.stderr)
        return

    state.active_duo_model = value.strip()
    print(f"Selected Duo model: {state.active_duo_model}")


def clear_duo_model(state: ReplState) -> None:
    """Clear any session-level server-side Duo model override."""
    if state.active_duo_model is None:
        print("No Duo model override is currently set.")
        return

    cleared = state.active_duo_model
    state.active_duo_model = None
    print(f"Cleared Duo model override (was: {cleared}).")


def list_duo_models(state: ReplState, provider: DuoProvider) -> None:
    """Report whether a discoverable backend model list is available."""
    _ = state
    support = provider.probe_duo_chat_model_support()
    if not support.supported:
        print("This GitLab instance does not support server-side Duo model selection.", file=sys.stderr)
        return

    print("GitLab accepted a server-side Duo model field, but does not expose a discoverable model list here.")
    print("Use /duo-model set <backend-model-id> if you already know the backend identifier.")


def print_duo_model_help() -> None:
    """Print /duo-model usage."""
    print("Duo model commands:")
    print("  /duo-model               — show current Duo model support and selection")
    print("  /duo-model probe         — refresh the backend capability probe")
    print("  /duo-model set <id>      — set a session-level Duo model override")
    print("  /duo-model clear         — clear the Duo model override")
    print("  /duo-model list          — explain whether GitLab exposes a model list")
