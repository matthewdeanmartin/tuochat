"""Stdout capture and truncation utilities."""

from __future__ import annotations

from tuochat.sandbox.limits import STDOUT_MAX_BYTES, STDOUT_MAX_LINES, TRUNCATION_MARKER


def truncate_stdout(lines: list[str]) -> list[str]:
    """Enforce line count and byte size limits on captured stdout."""
    truncated = False
    if len(lines) > STDOUT_MAX_LINES:
        lines = lines[:STDOUT_MAX_LINES]
        truncated = True

    total = 0
    kept: list[str] = []
    for line in lines:
        size = len(line.encode("utf-8"))
        if total + size > STDOUT_MAX_BYTES:
            truncated = True
            break
        kept.append(line)
        total += size

    if truncated:
        kept.append(TRUNCATION_MARKER)
    return kept
