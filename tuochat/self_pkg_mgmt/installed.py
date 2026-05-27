"""Installed distribution walker (direct deps only, no graph resolution)."""

from __future__ import annotations

import re
from importlib import metadata

REQ_NAME_PATTERN = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def host_version(dist_name: str) -> str | None:
    try:
        return metadata.version(dist_name)
    except metadata.PackageNotFoundError:
        return None


def parse_requirement_name(requirement: str) -> str | None:
    """Return the bare distribution name from a Requires-Dist line.

    Strips extras markers and environment markers. Does not parse specifiers.
    """
    head = requirement.split(";", 1)[0].strip()
    if not head:
        return None
    match = REQ_NAME_PATTERN.match(head)
    if not match:
        return None
    return match.group(1)


def direct_dependencies(dist_name: str) -> list[tuple[str, str]]:
    """Return (name, installed_version) for each direct dep of dist_name.

    Drops deps that are not currently installed and drops extras markers.
    Does not walk the transitive graph.
    """
    try:
        dist = metadata.distribution(dist_name)
    except metadata.PackageNotFoundError:
        return []
    requires = dist.requires or []
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for req in requires:
        if "extra ==" in req:
            continue
        name = parse_requirement_name(req)
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            version = metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
        result.append((name, version))
    return result


def all_installed() -> list[tuple[str, str]]:
    """Return (name, version) for every installed distribution."""
    result: list[tuple[str, str]] = []
    for dist in metadata.distributions():
        name = dist.metadata["Name"] if dist.metadata else None
        if not name:
            continue
        version = dist.version
        result.append((name, version))
    return result
