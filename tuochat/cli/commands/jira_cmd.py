"""Jira browse-and-attach slash commands.

Implements the /jira command family:

  /jira              — interactive project + issue picker, queue selected issues
  /jira status       — show Jira config state and connectivity
  /jira auth         — validate auth and show current user
  /jira clear        — clear session caches
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tuochat.cli.models import ReplState

# Session-level client cache; keyed by (host, deployment, email, token hash)
SESSION_CLIENT: object | None = None
SESSION_CLIENT_KEY: tuple | None = None


def client_cache_key(cfg) -> tuple:
    import hashlib  # noqa: PLC0415

    token_hash = hashlib.sha256(cfg.jira.token.encode()).hexdigest()[:16]
    return (cfg.jira.host, cfg.jira.deployment, cfg.jira.email, token_hash)


def get_or_build_client(state: ReplState):
    """Return a session-cached JiraMetaClient, building one if needed."""
    global SESSION_CLIENT, SESSION_CLIENT_KEY  # noqa: PLW0603

    cfg = state.cfg
    if not cfg.jira.host or not cfg.jira.token:
        print(
            "Jira is not configured.  Add [jira] host/token to your config or set\n"
            "TUOCHAT_JIRA_HOST and TUOCHAT_JIRA_TOKEN environment variables.",
            file=sys.stderr,
        )
        return None

    key = client_cache_key(cfg)
    if SESSION_CLIENT is not None and SESSION_CLIENT_KEY == key:
        return SESSION_CLIENT

    try:
        from tuochat.jira_client import JiraMetaClient  # noqa: PLC0415

        client = JiraMetaClient(
            host=cfg.jira.host,
            deployment=cfg.jira.deployment,
            email=cfg.jira.email,
            token=cfg.jira.token,
            ssl_ca_cert=cfg.jira.ssl_ca_cert,
        )
        SESSION_CLIENT = client
        SESSION_CLIENT_KEY = key
        return client
    except ImportError as exc:
        print(str(exc), file=sys.stderr)
        return None
    except Exception as exc:  # noqa: BLE001
        print(f"Jira connection error: {exc}", file=sys.stderr)
        return None


def clear_session_cache() -> None:
    """Drop the session-level client cache."""
    global SESSION_CLIENT, SESSION_CLIENT_KEY  # noqa: PLW0603

    SESSION_CLIENT = None
    SESSION_CLIENT_KEY = None


# Top-level dispatcher


def handle_jira_command(command: str, argument: str, state: ReplState) -> None:
    """Dispatch /jira sub-commands."""
    arg = argument.strip()
    parts = arg.split(maxsplit=1)
    sub = parts[0].lower() if parts else ""

    if sub == "status":
        handle_status(state)
    elif sub == "auth":
        handle_auth(state)
    elif sub == "clear":
        handle_clear(state)
    elif sub == "":
        handle_picker(state)
    else:
        print_help()


# /jira status


def handle_status(state: ReplState) -> None:
    """Show whether Jira is configured and whether the extra is installed."""
    import importlib.util  # noqa: PLC0415

    jira_installed = importlib.util.find_spec("jira") is not None
    cfg = state.cfg

    print(f"Jira extra installed:  {'yes' if jira_installed else 'no'}")
    print(f"Jira host:             {cfg.jira.host or '(not set)'}")
    print(f"Jira deployment:       {cfg.jira.deployment}")

    if cfg.jira.deployment == "cloud":
        print(f"Jira email:            {cfg.jira.email or '(not set)'}")

    if cfg.jira.token:
        masked = cfg.jira.token[:8] + "***" if len(cfg.jira.token) > 8 else "***"
        print(f"Jira token:            {masked}")
    else:
        print("Jira token:            (not set)")

    if cfg.jira.project:
        print(f"Last project:          {cfg.jira.project}")

    if not jira_installed:
        print("\nInstall Jira support:  uv sync --extra jira")
    elif not cfg.jira.host or not cfg.jira.token:
        print("\nConfigure Jira in your config.toml under [jira].")


# /jira auth


def handle_auth(state: ReplState) -> None:
    """Validate credentials and print the authenticated user."""
    client = get_or_build_client(state)
    if client is None:
        return

    try:
        display_name = client.validate_auth()
        print(f"Jira authenticated as: {display_name}")
        print(f"Host: {state.cfg.jira.host}")
    except Exception as exc:  # noqa: BLE001
        print(f"Jira authentication failed: {exc}", file=sys.stderr)
        print(f"Host: {state.cfg.jira.host}  Deployment: {state.cfg.jira.deployment}", file=sys.stderr)


# /jira clear


def handle_clear(state: ReplState) -> None:
    """Clear session caches."""
    clear_session_cache()
    print("Jira session cache cleared.")


# /jira (interactive picker)


def handle_picker(state: ReplState) -> None:
    """Interactive project + issue picker; queues selected issues as attachments."""
    client = get_or_build_client(state)
    if client is None:
        return

    # Verify credentials on first use
    try:
        client.validate_auth()
    except Exception as exc:  # noqa: BLE001
        print(f"Jira authentication failed: {exc}", file=sys.stderr)
        print(f"Host: {state.cfg.jira.host}  Deployment: {state.cfg.jira.deployment}", file=sys.stderr)
        return

    # Step 1: pick a project
    project_key = pick_project(client, state)
    if project_key is None:
        return

    # Step 2: pick one or more issues
    selected_keys = pick_issues(client, project_key, state)
    if not selected_keys:
        return

    # Step 3: fetch full detail and queue each as an attachment
    queued = 0
    for issue_key in selected_keys:
        attach_issue(client, issue_key, state)
        queued += 1

    if queued:
        print(f"Queued {queued} Jira issue(s) for the next message.")


def pick_project(client, state: ReplState) -> str | None:
    """Prompt the user to pick a project; return the project key or None."""
    print("Fetching Jira projects…")
    try:
        projects = client.list_projects()
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to list projects: {exc}", file=sys.stderr)
        return None

    if not projects:
        print("No Jira projects found (you may not have access to any projects).")
        return None

    print(f"Jira projects ({len(projects)}):")
    for i, proj in enumerate(projects, 1):
        print(f"  {i:3}.  {proj.display_label}")

    default_key = state.cfg.jira.project
    prompt = f"Select project [key or #]{' [' + default_key + ']' if default_key else ''}: "

    from tuochat.cli.prompts import prompt_input  # noqa: PLC0415

    raw = prompt_input(prompt).strip()

    if not raw and default_key:
        return default_key

    if not raw:
        print("No project selected.")
        return None

    # Accept a number or a key
    if raw.isdigit():
        index = int(raw) - 1
        if 0 <= index < len(projects):
            return projects[index].key
        print(f"Invalid selection: {raw}", file=sys.stderr)
        return None

    # Accept project key directly (case-insensitive)
    upper = raw.upper()
    for proj in projects:
        if proj.key.upper() == upper:
            return proj.key

    print(f"Project not found: {raw!r}", file=sys.stderr)
    return None


def pick_issues(client, project_key: str, state: ReplState) -> list[str]:
    """Prompt the user to pick one or more issues; return a list of issue keys."""
    print(f"Fetching issues for {project_key}…")
    try:
        issues = client.list_issues(project_key)
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to list issues for {project_key}: {exc}", file=sys.stderr)
        return []

    if not issues:
        print(f"No issues found for project {project_key}.")
        return []

    print(f"{project_key} issues ({len(issues)}):")
    for i, issue in enumerate(issues, 1):
        print(f"  {i:3}.  {issue.display_label}")

    from tuochat.cli.prompts import prompt_input  # noqa: PLC0415

    raw = prompt_input("Select issues to attach [key, #, or comma-separated list; empty to cancel]: ").strip()
    if not raw:
        print("No issues selected.")
        return []

    # Build lookup maps
    by_number: dict[int, str] = {i: issue.key for i, issue in enumerate(issues, 1)}
    by_key: dict[str, str] = {issue.key.upper(): issue.key for issue in issues}

    selected: list[str] = []
    for token in raw.replace(",", " ").split():
        token = token.strip()
        if not token:
            continue
        if token.isdigit():
            idx = int(token)
            if idx in by_number:
                key = by_number[idx]
                if key not in selected:
                    selected.append(key)
            else:
                print(f"  Skipping unknown selection: {token}")
        else:
            upper = token.upper()
            if upper in by_key:
                key = by_key[upper]
                if key not in selected:
                    selected.append(key)
            else:
                print(f"  Skipping unknown issue key: {token}")

    return selected


def attach_issue(client, issue_key: str, state: ReplState) -> None:
    """Fetch full issue detail and queue it as a pending attachment."""
    from tuochat.jira_formatting import attachment_name, format_issue_attachment  # noqa: PLC0415

    print(f"Fetching {issue_key}…")
    try:
        detail = client.get_issue(issue_key)
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to fetch {issue_key}: {exc}", file=sys.stderr)
        return

    content = format_issue_attachment(detail)
    name = attachment_name(detail.key, detail.summary)

    state.pending_attachment_messages.append(content)
    state.pending_attachment_names.append(name)

    preview_summary = detail.summary[:70] if detail.summary else ""
    print(f"  Queued: {name}")
    if preview_summary:
        print(f"  {preview_summary}")


# Help


def print_help() -> None:
    print("Jira commands:")
    print("  /jira              — browse projects and issues, queue selected issues as context")
    print("  /jira status       — show Jira configuration and install state")
    print("  /jira auth         — validate credentials and show current user")
    print("  /jira clear        — clear session cache")
    print()
    print("Configuration (config.toml):")
    print("  [jira]")
    print('  host = "https://yourcompany.atlassian.net"')
    print('  deployment = "cloud"   # cloud or server')
    print('  email = "you@example.com"  # cloud only')
    print('  token = "..."')
    print()
    print("Environment variables:")
    print("  TUOCHAT_JIRA_HOST, TUOCHAT_JIRA_DEPLOYMENT, TUOCHAT_JIRA_EMAIL, TUOCHAT_JIRA_TOKEN")
