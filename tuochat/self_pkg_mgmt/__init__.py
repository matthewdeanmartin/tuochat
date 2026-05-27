"""Supply-chain safety and self-management for tuochat.

This package is designed to be extractable as a standalone library. It depends
on nothing outside the Python stdlib. External tools (pip-audit, safety, uv)
are used opportunistically when present on PATH but never required.

Public API:
    check_for_updates(host, position="start") -> Report
    run_audit(host) -> Report
    self_upgrade(host, dry_run=False) -> UpgradeResult
    self_check(host) -> list[str]
    tamper_check(host) -> list[str]

Standalone CLI:
    python -m tuochat.self_pkg_mgmt --help
"""

from __future__ import annotations

from tuochat.self_pkg_mgmt.api import check_for_updates, run_audit, self_check, self_upgrade, tamper_check
from tuochat.self_pkg_mgmt.host import Host, TuochatHost, default_host
from tuochat.self_pkg_mgmt.report import Report, VersionInfo, Vulnerability

__all__ = [
    "Host",
    "TuochatHost",
    "default_host",
    "Report",
    "Vulnerability",
    "VersionInfo",
    "check_for_updates",
    "run_audit",
    "self_check",
    "tamper_check",
    "self_upgrade",
]
