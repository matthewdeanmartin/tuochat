"""Public API for self_pkg_mgmt.

This module orchestrates the cache, PyPI client, installed-dep walker, and
audit runner into the small public surface documented in __init__.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

import tuochat.self_pkg_mgmt.self_check as self_check_module
from tuochat.security import tamper
from tuochat.self_pkg_mgmt import audit, background, installed, pypi, upgrade
from tuochat.self_pkg_mgmt.cache import COOLOFF, Cache, parse_iso, utcnow
from tuochat.self_pkg_mgmt.host import Host, default_host
from tuochat.self_pkg_mgmt.report import Report, VersionInfo, Vulnerability

Position = Literal["start", "end", "both", "off"]


def build_version_info(name: str, installed_version: str, cache: Cache) -> VersionInfo:
    entry = cache.get_package(name)
    if not entry:
        return VersionInfo(
            name=name,
            installed=installed_version,
            latest=None,
            latest_published=None,
            age_days=None,
            is_upgrade_available=False,
            is_in_cooloff=False,
        )
    latest = entry.get("latest")
    published = parse_iso(entry.get("published"))
    age_days: float | None = None
    is_cooloff = False
    if published:
        age = utcnow() - published
        age_days = age.total_seconds() / 86400.0
        is_cooloff = age < COOLOFF
    target_key = f"{name}=={latest}" if latest else None
    snoozed = cache.is_snoozed(target_key) if target_key else False
    upgrade_available = bool(latest and latest != installed_version and not snoozed)
    return VersionInfo(
        name=name,
        installed=installed_version,
        latest=latest,
        latest_published=published,
        age_days=age_days,
        is_upgrade_available=upgrade_available,
        is_in_cooloff=is_cooloff,
    )


def refresh_pypi(host: Host, names: list[str]) -> list[str]:
    """Fetch missing/stale entries for the given package names. Returns errors."""
    cache = Cache.load(host.cache_dir)
    errors: list[str] = []
    changed = False
    for name in names:
        if cache.is_fresh(name):
            continue
        try:
            latest, published = pypi.get_latest(name)
        except pypi.PypiError as exc:
            errors.append(str(exc))
            host.logger.debug("pypi fetch failed: %s", exc)
            continue
        cache.put_package(name, latest, published)
        changed = True
    if changed:
        cache.save()
    return errors


def check_for_updates(
    host: Host | None = None,
    position: Position = "start",
    allow_network: bool = True,
) -> Report:
    """Return a cached-then-refreshed freshness report.

    position="start" runs cache-only in the foreground and (if allow_network)
    schedules a background refresh. position="end" refreshes synchronously so
    the next start is instant. position="both" does both. position="off"
    returns an empty report.
    """
    active_host = host or default_host()
    if position == "off":
        return Report()

    cache = Cache.load(active_host.cache_dir)
    cache.prune_snoozes()
    host_installed = installed.host_version(active_host.dist_name)
    if host_installed is None:
        return Report(
            errors=(f"host distribution {active_host.dist_name!r} is not installed",),
        )
    deps = installed.direct_dependencies(active_host.dist_name)
    names_to_track = [active_host.dist_name] + [name for name, _ in deps]

    if position in {"end", "both"}:
        errors = refresh_pypi(active_host, names_to_track)
        cache = Cache.load(active_host.cache_dir)
    elif allow_network:
        stale = [n for n in names_to_track if not cache.is_fresh(n)]
        if stale:

            def run_refresh() -> None:
                refresh_pypi(active_host, stale)

            background.spawn(run_refresh)
        errors = []
    else:
        errors = []

    host_info = build_version_info(active_host.dist_name, host_installed, cache)
    dep_infos = tuple(build_version_info(name, version, cache) for name, version in deps)

    notes: list[str] = []
    if any(info.is_in_cooloff for info in (host_info, *dep_infos) if info):
        notes.append("some upgrades are suppressed during a 14-day cooloff window")

    return Report(
        host_dist=host_info,
        dependencies=dep_infos,
        notes=tuple(notes),
        errors=tuple(errors),
    )


def run_audit(host: Host | None = None, force: bool = False) -> Report:
    """Run an opportunistic vulnerability audit.

    Only runs if at least one upgrade is actionable (i.e., there is something
    the user can do about a finding), unless force=True.
    """
    active_host = host or default_host()
    report = check_for_updates(host=active_host, position="start", allow_network=False)

    any_actionable = bool(report.host_dist and report.host_dist.actionable) or any(
        dep.actionable for dep in report.dependencies
    )
    if not any_actionable and not force:
        return Report(
            host_dist=report.host_dist,
            dependencies=report.dependencies,
            notes=("audit skipped: nothing to upgrade, no actionable fix possible",),
        )

    vulns, tool = audit.run_available_audit()
    if tool is None:
        return Report(
            host_dist=report.host_dist,
            dependencies=report.dependencies,
            notes=("audit skipped: no audit tool available on PATH (pip-audit, safety, uv)",),
        )

    cache = Cache.load(active_host.cache_dir)
    cache.set_audit(tool=tool, summary={"vuln_count": len(vulns)})
    cache.save()

    return Report(
        generated_at=datetime.now(timezone.utc),
        host_dist=report.host_dist,
        dependencies=report.dependencies,
        vulnerabilities=tuple(vulns),
        notes=(f"audit tool: {tool}",),
    )


def self_upgrade(host: Host | None = None, dry_run: bool = False) -> upgrade.UpgradeResult:
    active_host = host or default_host()
    return upgrade.perform(active_host.dist_name, dry_run=dry_run)


def self_check(host: Host | None = None) -> list[str]:
    _ = host
    return self_check_module.run()


def tamper_check(host: Host | None = None) -> list[str]:
    active_host = host or default_host()
    package_name = active_host.dist_name
    if tamper.is_source_checkout(package_name):
        return tamper.verify_files_against_embedded_manifest(package_name)

    record_problems = tamper.verify_files_against_record(package_name)
    if not record_problems:
        return []

    manifest_problems = tamper.verify_files_against_embedded_manifest(package_name)
    if not manifest_problems:
        return []

    return [f"RECORD: {problem}" for problem in record_problems] + [
        f"Embedded manifest: {problem}" for problem in manifest_problems
    ]


def clear_cache(host: Host | None = None) -> None:
    active_host = host or default_host()
    cache = Cache.load(active_host.cache_dir)
    cache.clear()
    cache.save()


def snooze(target: str, days: int, host: Host | None = None) -> None:
    active_host = host or default_host()
    cache = Cache.load(active_host.cache_dir)
    cache.snooze(target, days)
    cache.save()


__all__ = [
    "Position",
    "check_for_updates",
    "run_audit",
    "self_upgrade",
    "self_check",
    "tamper_check",
    "clear_cache",
    "snooze",
    "Report",
    "VersionInfo",
    "Vulnerability",
]
