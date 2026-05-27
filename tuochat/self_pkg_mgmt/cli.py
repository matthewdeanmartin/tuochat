"""Standalone argparse entrypoint for self_pkg_mgmt."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from tuochat.self_pkg_mgmt import api
from tuochat.self_pkg_mgmt.cache import Cache
from tuochat.self_pkg_mgmt.host import Host, default_host


def json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")


def dump_report(report: api.Report, as_json: bool) -> None:
    if as_json:
        print(json.dumps(dataclasses.asdict(report), default=json_default, indent=2))
        return
    text = report.render_text()
    if text:
        print(text)
    else:
        print("No upgrades or vulnerabilities to report.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tuochat.self_pkg_mgmt",
        description="Supply-chain safety and self-management for tuochat.",
    )
    parser.add_argument("--dist", default="tuochat", help="Distribution name (default: tuochat)")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    parser.add_argument("--no-network", action="store_true", help="Use cache only, no PyPI fetches")

    subparsers = parser.add_subparsers(dest="command", required=False)

    subparsers.add_parser("status", help="Show cached state (no network, no subprocess)")
    subparsers.add_parser("check", help="Refresh update info for host + direct deps")
    audit_parser = subparsers.add_parser("audit", help="Run vulnerability audit (if tool is installed)")
    audit_parser.add_argument("--force", action="store_true", help="Audit even if no upgrades are pending")

    upgrade_parser = subparsers.add_parser("upgrade", help="Self-upgrade via detected install method")
    upgrade_parser.add_argument("--dry-run", action="store_true", help="Print the argv, do not run")

    subparsers.add_parser("self-check", help="Verify installed dists and report tuochat file tampering")
    subparsers.add_parser("clear-cache", help="Delete the sidecar cache")

    snooze_parser = subparsers.add_parser("snooze", help="Snooze a specific upgrade suggestion")
    snooze_parser.add_argument("target", help="e.g. package==1.2.3")
    snooze_parser.add_argument("--days", type=int, default=14, help="Snooze duration (default: 14)")

    return parser


def cmd_status(host: Host, as_json: bool) -> int:
    cache = Cache.load(host.cache_dir)
    if as_json:
        print(json.dumps(cache.data, indent=2, sort_keys=True))
        return 0
    pypi_entries = cache.data.get("pypi", {})
    print(f"Cache: {cache.path}")
    print(f"Tracked packages: {len(pypi_entries)}")
    for name, entry in sorted(pypi_entries.items()):
        print(f"  {name}: latest={entry.get('latest')} published={entry.get('published')}")
    audit_summary = cache.data.get("audit_summary")
    if audit_summary:
        print(f"Last audit: {cache.data.get('last_audit_utc')} {audit_summary}")
    snoozes = cache.data.get("suppressed_until", {})
    if snoozes:
        print(f"Snoozes: {snoozes}")
    return 0


def cmd_check(host: Host, as_json: bool, no_network: bool) -> int:
    position: Literal["start", "end"] = "start" if no_network else "end"
    report = api.check_for_updates(host=host, position=position, allow_network=not no_network)
    dump_report(report, as_json=as_json)
    return 0 if report.is_empty else 0


def cmd_audit(host: Host, as_json: bool, force: bool) -> int:
    report = api.run_audit(host=host, force=force)
    dump_report(report, as_json=as_json)
    return 0 if not any(v.actionable for v in report.vulnerabilities) else 1


def cmd_upgrade(host: Host, dry_run: bool, as_json: bool) -> int:
    result = api.self_upgrade(host=host, dry_run=dry_run)
    if as_json:
        print(
            json.dumps(
                {
                    "method": result.method.value,
                    "argv": result.argv,
                    "returncode": result.returncode,
                    "attempted": result.attempted,
                    "ok": result.ok,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                },
                indent=2,
            )
        )
        return 0 if result.ok or dry_run else 1
    if result.argv is None:
        print(f"No upgrade path for install method: {result.method.value}")
        return 1
    if dry_run or not result.attempted:
        print(f"Would run: {' '.join(result.argv)} (method={result.method.value})")
        return 0
    print(f"Ran: {' '.join(result.argv)}")
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return 0 if result.ok else 1


def cmd_self_check(as_json: bool) -> int:
    problems = api.self_check()
    tamper_problems = api.tamper_check()
    if as_json:
        print(json.dumps({"problems": problems, "tamper_problems": tamper_problems}, indent=2))
    else:
        if not problems:
            print("OK: all installed distributions satisfy their Requires-Dist.")
        else:
            print(f"Found {len(problems)} integrity problem(s):")
            for problem in problems:
                print(f"  - {problem}")
        if not tamper_problems:
            print("Tamper report: no modified tuochat package files found.")
        else:
            print(f"Tamper report found {len(tamper_problems)} problem(s):")
            for problem in tamper_problems:
                print(f"  - {problem}")
    return 0 if not problems and not tamper_problems else 1


def cmd_clear_cache(host: Host) -> int:
    api.clear_cache(host=host)
    print("Cache cleared.")
    return 0


def cmd_snooze(host: Host, target: str, days: int) -> int:
    api.snooze(target=target, days=days, host=host)
    print(f"Snoozed {target} for {days} day(s).")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    host = default_host(dist_name=args.dist)
    command = args.command or "check"

    if command == "status":
        return cmd_status(host, as_json=args.json)
    if command == "check":
        return cmd_check(host, as_json=args.json, no_network=args.no_network)
    if command == "audit":
        return cmd_audit(host, as_json=args.json, force=getattr(args, "force", False))
    if command == "upgrade":
        return cmd_upgrade(host, dry_run=getattr(args, "dry_run", False), as_json=args.json)
    if command == "self-check":
        return cmd_self_check(as_json=args.json)
    if command == "clear-cache":
        return cmd_clear_cache(host)
    if command == "snooze":
        return cmd_snooze(host, target=args.target, days=args.days)
    parser.print_help()
    return 2
