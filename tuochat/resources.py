"""GitLab resource descriptor — normalized representation of a selectable resource.

A ResourceDescriptor is the single shared type for anything a user can pick
and attach to a Duo chat session as the active ``resource_id``.  It carries
just enough display metadata so the REPL can render it cleanly without
making additional API calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ResourceKind = Literal["project", "group", "unknown"]


@dataclass
class ResourceDescriptor:
    """A normalized resource that can be passed to Duo as ``resource_id``."""

    resource_id: str  # The opaque GID Duo expects, e.g. "gid://gitlab/Project/42"
    kind: ResourceKind  # "project" | "group" | "unknown"
    display_label: str  # Human-readable name shown in the REPL
    path: str | None = None  # Namespace path, e.g. "mygroup/myproject"
    url: str | None = None  # Web URL for reference

    def __str__(self) -> str:
        parts = [f"{self.kind}:{self.display_label}"]
        if self.path:
            parts.append(f"({self.path})")
        return " ".join(parts)


def resource_descriptor_from_project(project: object) -> ResourceDescriptor:
    """Build a ResourceDescriptor from a python-gitlab Project object."""
    pid: int = getattr(project, "id", 0)
    return ResourceDescriptor(
        resource_id=f"gid://gitlab/Project/{pid}",
        kind="project",
        display_label=getattr(project, "name", str(pid)),
        path=getattr(project, "path_with_namespace", None),
        url=getattr(project, "web_url", None),
    )


def resource_descriptor_from_group(group: object) -> ResourceDescriptor:
    """Build a ResourceDescriptor from a python-gitlab Group object."""
    gid: int = getattr(group, "id", 0)
    return ResourceDescriptor(
        resource_id=f"gid://gitlab/Group/{gid}",
        kind="group",
        display_label=getattr(group, "name", str(gid)),
        path=getattr(group, "full_path", None),
        url=getattr(group, "web_url", None),
    )
