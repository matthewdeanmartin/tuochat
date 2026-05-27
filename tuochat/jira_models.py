"""Normalized Jira data descriptors for rendering and UI."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class JiraProjectDescriptor:
    """Minimal project info used for listing and selection."""

    key: str
    name: str
    project_type: str = ""
    project_id: str = ""

    @property
    def display_label(self) -> str:
        """Short label for list views."""
        return f"{self.key}  {self.name}"


@dataclass
class JiraIssueDescriptor:
    """Minimal issue info used for listing and selection."""

    key: str
    summary: str
    status: str = ""
    issue_type: str = ""
    updated: str = ""
    assignee: str = ""

    @property
    def display_label(self) -> str:
        """Short label for list views."""
        parts = [self.key, self.summary[:70]]
        if self.status:
            parts.append(f"[{self.status}]")
        return "  ".join(parts)


@dataclass
class JiraIssueDetail:
    """Full issue detail used for attachment formatting."""

    key: str
    summary: str
    url: str
    project_key: str = ""
    status: str = ""
    issue_type: str = ""
    priority: str = ""
    assignee: str = ""
    reporter: str = ""
    created: str = ""
    updated: str = ""
    labels: list[str] = field(default_factory=list)
    fix_versions: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    description: str = ""
