"""Resource discovery and selection commands.

Implements the /resource family of slash commands:

  /resource                 — show current resource or prompt to pick
  /resource list [query]    — list available projects (optionally filtered)
  /resource pick <N>        — select item N from the last list
  /resource set <path>      — set by namespace path (e.g. mygroup/myrepo)
  /resource clear           — remove the active resource
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tuochat.cli.models import ReplState


def build_client(state: ReplState):
    """Build a GitLabMetaClient from session config, or print an error and return None."""
    from tuochat.gitlab_client import GitLabMetaClient

    cfg = state.cfg
    if not cfg.gitlab.host or not cfg.gitlab.token:
        print("GitLab host and token must be configured before using /resource.", file=sys.stderr)
        return None
    try:
        return GitLabMetaClient(
            host=cfg.gitlab.host,
            token=cfg.gitlab.token,
            token_type=cfg.gitlab.token_type,
            user_agent=getattr(cfg.gitlab, "user_agent", None),
        )
    except ImportError as exc:
        print(str(exc), file=sys.stderr)
        return None


def handle_resource_command(_command: str, argument: str, state: ReplState) -> None:
    """Dispatch /resource sub-commands.

    The REPL parser gives us ``command="/resource"`` and ``argument=<rest>``.
    We parse the first word of *argument* as the sub-command.
    """
    arg = argument.strip()
    sub_parts = arg.split(maxsplit=1)
    sub = sub_parts[0].lower() if sub_parts else ""
    sub_rest = sub_parts[1] if len(sub_parts) > 1 else ""

    if not sub:
        show_current(state)
        return

    if sub == "list":
        list_resources(state, query=sub_rest or None)
        return

    if sub == "pick":
        pick_resource(state, sub_rest)
        return

    if sub == "set":
        set_resource_by_path(state, sub_rest)
        return

    if sub == "clear":
        clear_resource(state)
        return

    # Unknown sub-command — print help
    print_resource_help()


def show_current(state: ReplState) -> None:
    if state.active_resource is None:
        print("No resource selected.  Use /resource list to browse, or /resource set <path>.")
    else:
        r = state.active_resource
        print(f"Active resource: {r.display_label} ({r.kind})")
        if r.path:
            print(f"  Path: {r.path}")
        if r.url:
            print(f"  URL:  {r.url}")
        print(f"  ID:   {r.resource_id}")
        print("  This ID scopes Duo to this project's code index.")
        print("  Use /gl file to attach README or other project content as context.")


def list_resources(state: ReplState, *, query: str | None = None) -> None:
    client = build_client(state)
    if client is None:
        return

    if query:
        candidates = client.search_projects(query)
        label = f"Projects matching '{query}'"
    else:
        candidates = client.list_projects()
        label = "Your projects"

    if not candidates:
        print("No projects found.")
        return

    state.resource_candidates = candidates
    print(f"{label} ({len(candidates)}):")
    for idx, r in enumerate(candidates):
        marker = "*" if state.active_resource and state.active_resource.resource_id == r.resource_id else " "
        path_str = f"  {r.path}" if r.path else ""
        print(f"  [{idx}]{marker} {r.display_label}{path_str}")
    print("Use /resource pick <N> to select, or /resource set <namespace/path>.")


def pick_resource(state: ReplState, arg: str) -> None:
    if not state.resource_candidates:
        print("No resource list available.  Run /resource list first.", file=sys.stderr)
        return
    if not arg:
        print("Usage: /resource pick <N>", file=sys.stderr)
        return
    try:
        idx = int(arg)
    except ValueError:
        print(f"Expected a number, got: {arg!r}", file=sys.stderr)
        return
    if idx < 0 or idx >= len(state.resource_candidates):
        print(f"Index {idx} out of range (0–{len(state.resource_candidates) - 1}).", file=sys.stderr)
        return
    state.active_resource = state.resource_candidates[idx]
    r = state.active_resource
    print(f"Resource set: {r.display_label} ({r.resource_id})")
    print("Note: the resource ID scopes Duo to this project's code index for code-related answers.")
    print("To give Duo the project description or README, use /gl file to attach it as context.")


def set_resource_by_path(state: ReplState, path: str) -> None:
    if not path:
        print("Usage: /resource set <namespace/path>", file=sys.stderr)
        return
    client = build_client(state)
    if client is None:
        return
    descriptor = client.get_project_by_path(path)
    if descriptor is None:
        print(f"Project not found: {path!r}", file=sys.stderr)
        return
    state.active_resource = descriptor
    print(f"Resource set: {descriptor.display_label} ({descriptor.resource_id})")
    print("Note: the resource ID scopes Duo to this project's code index for code-related answers.")
    print("To give Duo the project description or README, use /gl file to attach it as context.")


def clear_resource(state: ReplState) -> None:
    if state.active_resource is None:
        print("No resource is currently selected.")
        return
    label = state.active_resource.display_label
    state.active_resource = None
    state.resource_candidates = []
    print(f"Resource cleared (was: {label}).")


def print_resource_help() -> None:
    print("Resource commands:")
    print("  /resource                  — show current resource")
    print("  /resource list [query]     — list your projects (optionally filtered)")
    print("  /resource pick <N>         — select item N from the last list")
    print("  /resource set <path>       — set by namespace path (e.g. group/repo)")
    print("  /resource clear            — remove the active resource")
