"""Render Jira issue details as plain-text attachment content."""

from __future__ import annotations

from tuochat.jira_models import JiraIssueDetail

DESCRIPTION_MAX_CHARS = 4000
TRUNCATION_NOTE = "\n[Description truncated]"


def format_issue_attachment(issue: JiraIssueDetail) -> str:
    """Render a JiraIssueDetail as an LLM-friendly plain-text attachment block."""
    lines = [
        f"Jira issue: {issue.key}",
        f"URL: {issue.url}",
    ]

    if issue.project_key:
        lines.append(f"Project: {issue.project_key}")

    lines.append(f"Summary: {issue.summary}")

    if issue.issue_type:
        lines.append(f"Type: {issue.issue_type}")
    if issue.status:
        lines.append(f"Status: {issue.status}")
    if issue.priority:
        lines.append(f"Priority: {issue.priority}")
    if issue.assignee:
        lines.append(f"Assignee: {issue.assignee}")
    if issue.reporter:
        lines.append(f"Reporter: {issue.reporter}")
    if issue.updated:
        lines.append(f"Updated: {issue.updated}")
    if issue.created:
        lines.append(f"Created: {issue.created}")
    if issue.labels:
        lines.append(f"Labels: {', '.join(issue.labels)}")
    if issue.fix_versions:
        lines.append(f"Fix Versions: {', '.join(issue.fix_versions)}")
    if issue.components:
        lines.append(f"Components: {', '.join(issue.components)}")

    if issue.description:
        desc = issue.description
        truncated = False
        if len(desc) > DESCRIPTION_MAX_CHARS:
            desc = desc[:DESCRIPTION_MAX_CHARS].rstrip()
            truncated = True
        lines.append("")
        lines.append("Description:")
        lines.append(desc)
        if truncated:
            lines.append(TRUNCATION_NOTE)

    return "\n".join(lines)


def attachment_name(issue_key: str, summary: str) -> str:
    """Return a short human-readable attachment name for display."""
    short = summary[:60].rstrip() if summary else ""
    if short:
        return f"[jira] {issue_key} {short}"
    return f"[jira] {issue_key}"
