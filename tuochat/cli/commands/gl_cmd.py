"""GitLab artifact picker and server-context injection commands.

Implements the /gl family of slash commands:

  /gl issue [list|<iid>]   — browse/attach issues from the active project
  /gl mr [list|<iid>]      — browse/attach merge requests from the active project
  /gl file <path> [ref]    — attach a repository file as context
  /gl current              — show currently attached GitLab artifacts
  /gl remove <name>        — remove a named context entry added by /gl
"""

from __future__ import annotations

import sys
import textwrap
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tuochat.cli.models import ReplState


# Context category label used for all /gl-attached items
GL_CATEGORY = "GitLabArtifact"

# Maximum description length kept in the context block
DESC_PREVIEW_CHARS = 300
DESC_CONTEXT_CHARS = 4000


def require_project(state: ReplState) -> str | None:
    """Return the numeric project ID extracted from the active resource GID, or print an error."""
    if state.active_resource is None:
        print(
            "No project selected.  Use /resource list then /resource pick <N> first.",
            file=sys.stderr,
        )
        return None
    resource_id = state.active_resource.resource_id
    # GID format: "gid://gitlab/Project/42"
    if "/Project/" not in resource_id:
        print(
            f"Active resource is not a project (kind={state.active_resource.kind}).",
            file=sys.stderr,
        )
        return None
    return resource_id.rsplit("/", 1)[-1]


def build_client(state: ReplState):
    """Build a GitLabMetaClient from session config, or print an error and return None."""
    from tuochat.gitlab_client import GitLabMetaClient

    cfg = state.cfg
    if not cfg.gitlab.host or not cfg.gitlab.token:
        print("GitLab host and token must be configured before using /gl.", file=sys.stderr)
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


def upsert_context(state: ReplState, name: str, content: str) -> None:
    """Add or replace a GL_CATEGORY entry in state.server_context."""
    for entry in state.server_context:
        if entry["name"] == name and entry["category"] == GL_CATEGORY:
            entry["content"] = content
            print(f"Updated context: {name} ({len(content)} chars)")
            return
    state.server_context.append({"category": GL_CATEGORY, "name": name, "content": content})
    print(f"Attached: {name} ({len(content)} chars)")


# Top-level dispatcher


def handle_gl_command(command: str, argument: str, state: ReplState) -> None:
    # pylint: disable=unused-argument
    """Dispatch /gl sub-commands."""
    arg = argument.strip()
    sub_parts = arg.split(maxsplit=1)
    sub = sub_parts[0].lower() if sub_parts else ""
    sub_rest = sub_parts[1] if len(sub_parts) > 1 else ""

    if sub == "issue":
        handle_issue(state, sub_rest)
    elif sub == "mr":
        handle_mr(state, sub_rest)
    elif sub == "file":
        handle_file(state, sub_rest)
    elif sub == "current":
        show_current(state)
    elif sub == "remove":
        remove_entry(state, sub_rest)
    else:
        print_help()


# /gl issue


def handle_issue(state: ReplState, arg: str) -> None:
    """List issues or attach a single issue by IID."""
    project_id = require_project(state)
    if project_id is None:
        return
    client = build_client(state)
    if client is None:
        return

    # If arg is a number, fetch that specific issue; otherwise list
    if arg and arg.isdigit():
        attach_issue(state, client, project_id, int(arg))
    else:
        list_issues(state, client, project_id, arg or "opened")


def list_issues(state: ReplState, client, project_id: str, state_filter: str) -> None:
    valid_states = {"opened", "closed", "all"}
    if state_filter not in valid_states:
        state_filter = "opened"

    issues = client.list_issues(project_id, state=state_filter)
    if not issues:
        print(f"No {state_filter} issues found.")
        return

    proj_label = state.active_resource.display_label if state.active_resource else project_id
    print(f"{proj_label} — {state_filter} issues ({len(issues)}):")
    for issue in issues:
        preview = truncate(issue["title"], 70)
        print(f"  #{issue['iid']}  {preview}")
    print("Use /gl issue <iid> to attach an issue as context.")


def attach_issue(state: ReplState, client, project_id: str, iid: int) -> None:
    issue = client.get_issue(project_id, iid)
    if issue is None:
        print(f"Issue #{iid} not found.", file=sys.stderr)
        return

    proj_label = state.active_resource.display_label if state.active_resource else project_id
    name = f"{proj_label}#issue-{iid}"
    desc = truncate(issue["description"], DESC_PREVIEW_CHARS)
    print(f"Issue #{iid}: {issue['title']}  [{issue['state']}]")
    if desc:
        print(textwrap.indent(truncate(desc, 200), "  "))

    content = format_issue(proj_label, issue)
    upsert_context(state, name, content)


def format_issue(proj_label: str, issue: dict) -> str:
    lines = [
        f"GitLab Issue: {proj_label}#{issue['iid']}",
        f"Title: {issue['title']}",
        f"State: {issue['state']}",
        f"URL: {issue['url']}",
        "",
    ]
    desc = truncate(issue["description"], DESC_CONTEXT_CHARS)
    if desc:
        lines += ["Description:", desc]
    return "\n".join(lines)


# /gl mr


def handle_mr(state: ReplState, arg: str) -> None:
    """List MRs or attach a single MR by IID."""
    project_id = require_project(state)
    if project_id is None:
        return
    client = build_client(state)
    if client is None:
        return

    if arg and arg.isdigit():
        attach_mr(state, client, project_id, int(arg))
    else:
        list_mrs(state, client, project_id, arg or "opened")


def list_mrs(state: ReplState, client, project_id: str, state_filter: str) -> None:
    valid_states = {"opened", "closed", "merged", "all"}
    if state_filter not in valid_states:
        state_filter = "opened"

    mrs = client.list_mrs(project_id, state=state_filter)
    if not mrs:
        print(f"No {state_filter} merge requests found.")
        return

    proj_label = state.active_resource.display_label if state.active_resource else project_id
    print(f"{proj_label} — {state_filter} merge requests ({len(mrs)}):")
    for mr in mrs:
        preview = truncate(mr["title"], 70)
        print(f"  !{mr['iid']}  {preview}  ({mr['source_branch']} -> {mr['target_branch']})")
    print("Use /gl mr <iid> to attach an MR as context.")


def attach_mr(state: ReplState, client, project_id: str, iid: int) -> None:
    mr = client.get_mr(project_id, iid)
    if mr is None:
        print(f"MR !{iid} not found.", file=sys.stderr)
        return

    proj_label = state.active_resource.display_label if state.active_resource else project_id
    name = f"{proj_label}!mr-{iid}"
    desc = truncate(mr["description"], DESC_PREVIEW_CHARS)
    print(f"MR !{iid}: {mr['title']}  [{mr['state']}]  {mr['source_branch']} -> {mr['target_branch']}")
    if desc:
        print(textwrap.indent(truncate(desc, 200), "  "))

    content = format_mr(proj_label, mr)
    upsert_context(state, name, content)


def format_mr(proj_label: str, mr: dict) -> str:
    lines = [
        f"GitLab Merge Request: {proj_label}!{mr['iid']}",
        f"Title: {mr['title']}",
        f"State: {mr['state']}",
        f"Branches: {mr['source_branch']} -> {mr['target_branch']}",
        f"URL: {mr['url']}",
        "",
    ]
    desc = truncate(mr["description"], DESC_CONTEXT_CHARS)
    if desc:
        lines += ["Description:", desc]
    return "\n".join(lines)


# /gl file


def handle_file(state: ReplState, arg: str) -> None:
    """Attach a repository file as server context.

    Usage: /gl file <path> [ref]
    """
    if not arg:
        print("Usage: /gl file <path> [ref]", file=sys.stderr)
        return

    project_id = require_project(state)
    if project_id is None:
        return
    client = build_client(state)
    if client is None:
        return

    parts = arg.split(maxsplit=1)
    file_path = parts[0]
    ref = parts[1] if len(parts) > 1 else "HEAD"

    content = client.get_file_content(project_id, file_path, ref)
    if content is None:
        print(f"File not found: {file_path!r} at ref {ref!r}", file=sys.stderr)
        return

    proj_label = state.active_resource.display_label if state.active_resource else project_id
    name = f"{proj_label}:{file_path}"
    preview_len = min(len(content), 200)
    print(f"File: {file_path}  ({len(content)} chars)")
    if preview_len:
        preview = content[:preview_len].rstrip()
        print(textwrap.indent(preview + ("…" if len(content) > preview_len else ""), "  "))

    wrapped = f"Repository file: {proj_label}/{file_path} (ref: {ref})\n\n{content}"
    upsert_context(state, name, wrapped)


# /gl current


def show_current(state: ReplState) -> None:
    gl_items = [item for item in state.server_context if item.get("category") == GL_CATEGORY]
    if not gl_items:
        print("No GitLab artifacts attached.  Use /gl issue, /gl mr, or /gl file.")
        return
    print(f"Attached GitLab artifacts ({len(gl_items)}):")
    for item in gl_items:
        size = len(item.get("content", ""))
        print(f"  {item['name']}  ({size} chars)")
    print("Use /gl remove <name> to detach an artifact.")


# /gl remove


def remove_entry(state: ReplState, name: str) -> None:
    if not name:
        print("Usage: /gl remove <name>", file=sys.stderr)
        return
    before = len(state.server_context)
    state.server_context = [
        item for item in state.server_context if not (item["name"] == name and item["category"] == GL_CATEGORY)
    ]
    removed = before - len(state.server_context)
    if removed:
        print(f"Removed: {name}")
    else:
        print(f"No attached artifact named '{name}'.", file=sys.stderr)


# Helpers


def truncate(text: str, limit: int) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def print_help() -> None:
    print("GitLab artifact commands:")
    print("  /gl issue [list|closed|all]    — list issues for the active project")
    print("  /gl issue <iid>                — attach an issue as context")
    print("  /gl mr [list|closed|merged]    — list merge requests")
    print("  /gl mr <iid>                   — attach an MR as context")
    print("  /gl file <path> [ref]          — attach a repository file as context")
    print("  /gl current                    — show attached GitLab artifacts")
    print("  /gl remove <name>              — detach an artifact by name")
    print("Requires an active project — use /resource to set one.")
