"""Shared local command implementations for CLI and REPL dispatch."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tuochat.cli.rendering import print_doctor, print_report_value
from tuochat.estimation import estimate_token_cost, format_cost, format_quantity
from tuochat.observability import DailyRollup, retention_cutoff_iso, rollup_to_dict
from tuochat.sandbox.api import code_interpreter_runtime_details
from tuochat.serialization import json_dumps

if TYPE_CHECKING:
    from collections.abc import Callable

    from tuochat.cli.command_models import DoctorCommand, ObservabilityCommand, UsageCommand
    from tuochat.config import TuochatConfig
    from tuochat.persistence import ConversationStore, NullConversationStore


def week_start_iso() -> str:
    """Return the ISO timestamp for the most recent Sunday 00:00:00 UTC."""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    days_since_sunday = (now.weekday() + 1) % 7
    sunday = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_since_sunday)
    return sunday.isoformat()


def collect_doctor_data(cfg: TuochatConfig, *, streaming: bool) -> dict[str, Any]:
    """Return doctor information as structured data."""
    runtime_details = code_interpreter_runtime_details()
    return {
        "host": cfg.gitlab.host or "(unset)",
        "token": "set" if cfg.gitlab.token else "missing",
        "config_file": {
            "path": str(cfg.config_file),
            "exists": cfg.config_file.is_file(),
        },
        "db_path": str(cfg.db_path),
        "db_dir_writable": cfg.db_path.parent.exists() or cfg.db_path.parent.parent.exists(),
        "streaming": streaming,
        "code_interpreter": runtime_details,
        "warnings": cfg.validate(),
    }


def run_doctor(cfg: TuochatConfig, command: DoctorCommand) -> int:
    """Run local diagnostics."""
    return run_doctor_with_state(cfg, command, streaming=cfg.chat.streaming)


def run_doctor_with_state(cfg: TuochatConfig, command: DoctorCommand, *, streaming: bool) -> int:
    """Run local diagnostics with an explicit streaming state."""
    payload = collect_doctor_data(cfg, streaming=streaming)
    if command.format == "json":
        print(json_dumps(payload, indent=True))
        return 0
    print_doctor(cfg, streaming=streaming)
    return 0


def collect_usage_data(
    cfg: TuochatConfig,
    *,
    build_store: Callable[[TuochatConfig], ConversationStore | NullConversationStore],
    no_write_enabled: Callable[[TuochatConfig], bool],
    current_store: ConversationStore | NullConversationStore | None = None,
) -> dict[str, Any]:
    """Return weekly usage totals as structured data."""
    if no_write_enabled(cfg):
        return {
            "available": False,
            "reason": "Usage is unavailable while no-write mode is enabled because no local database is used.",
        }
    store = current_store or build_store(cfg)
    try:
        week_start = week_start_iso()
        totals = store.get_weekly_usage(week_start)
    finally:
        if current_store is None:
            store.close()

    input_tokens = totals["input_tokens"]
    output_tokens = totals["output_tokens"]
    total_tokens = totals["total_tokens"]
    turns = totals["turns"]
    input_cost, output_cost, total_cost = estimate_token_cost(input_tokens, output_tokens)
    return {
        "available": True,
        "week_start": week_start,
        "turns": turns,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "approximate_words": int(total_tokens / 1.3),
        "approximate_characters": total_tokens * 4,
        "approximate_kilobytes": round((total_tokens * 4) / 1024, 1),
        "input_cost": input_cost,
        "output_cost": output_cost,
        "total_cost": total_cost,
    }


def run_usage(
    cfg: TuochatConfig,
    command: UsageCommand,
    *,
    build_store: Callable[[TuochatConfig], ConversationStore | NullConversationStore],
    no_write_enabled: Callable[[TuochatConfig], bool],
    current_store: ConversationStore | NullConversationStore | None = None,
) -> int:
    """Show weekly token usage."""
    payload = collect_usage_data(
        cfg,
        build_store=build_store,
        no_write_enabled=no_write_enabled,
        current_store=current_store,
    )
    if command.format == "json":
        print(json_dumps(payload, indent=True))
        return 0
    if not payload["available"]:
        print(payload["reason"])
        return 0
    print(f"Weekly usage (since {str(payload['week_start'])[:10]}, resets Sunday):")
    print_report_value("turns", format_quantity(payload["turns"]))
    print_report_value("input_tokens", format_quantity(payload["input_tokens"]))
    print_report_value("output_tokens", format_quantity(payload["output_tokens"]))
    print_report_value("total_tokens", format_quantity(payload["total_tokens"]))
    print_report_value("approximate_words", format_quantity(payload["approximate_words"]))
    print_report_value("approximate_characters", format_quantity(payload["approximate_characters"]))
    print_report_value("approximate_kilobytes", format_quantity(payload["approximate_kilobytes"], decimals=1))
    print_report_value("input_cost", format_cost(payload["input_cost"]))
    print_report_value("output_cost", format_cost(payload["output_cost"]))
    print_report_value("total_cost", format_cost(payload["total_cost"]))
    return 0


def collect_observability_data(
    cfg: TuochatConfig,
    *,
    build_store: Callable[[TuochatConfig], ConversationStore | NullConversationStore],
    no_write_enabled: Callable[[TuochatConfig], bool],
    current_store: ConversationStore | NullConversationStore | None = None,
) -> dict[str, Any]:
    """Return 30-day observability rollups as structured data."""
    if no_write_enabled(cfg):
        return {
            "available": False,
            "reason": "Observability is unavailable while no-write mode is enabled.",
        }
    store = current_store or build_store(cfg)
    try:
        since = retention_cutoff_iso(30)
        rollups = store.get_observability_rollups(since)
    finally:
        if current_store is None:
            store.close()
    return {
        "available": True,
        "retention_days": 30,
        "since": since,
        "rollups": [rollup_to_dict(r) for r in rollups],
    }


def format_optional(value: float | None, decimals: int = 1) -> str:
    """Format an optional float for CLI table display."""
    if value is None:
        return "-"
    return f"{value:,.{decimals}f}"


def print_observability_text(rollups: list[DailyRollup]) -> None:
    """Print human-readable observability tables."""
    if not rollups:
        print("No observability data recorded yet.")
        print("Observability rows are written for every Duo response attempt.")
        return

    # Table 1: Completed response performance
    print("Completed response performance (last 30 days):")
    header = (
        f"{'day':<12} {'completed':>9} "
        f"{'avg_ttfb':>9} {'med_ttfb':>9} {'p95_ttfb':>9} {'max_ttfb':>9} "
        f"{'avg_ms/tok':>10} {'p95_ms/tok':>10} "
        f"{'avg_total':>10} {'p95_total':>10} "
        f"{'avg_req_tok':>11} {'avg_res_tok':>11} {'max_res_tok':>11}"
    )
    print(header)
    print("-" * len(header))
    for r in rollups:
        ttfb = r.time_to_first_token_ms
        tpt = r.time_per_token_ms
        tot = r.total_response_ms
        req = r.request_tokens
        res = r.response_tokens
        print(
            f"{r.day:<12} {r.completed:>9} "
            f"{format_optional(ttfb.average if ttfb else None):>9} "
            f"{format_optional(ttfb.median if ttfb else None):>9} "
            f"{format_optional(ttfb.p95 if ttfb else None):>9} "
            f"{format_optional(ttfb.max if ttfb else None, 0):>9} "
            f"{format_optional(tpt.average if tpt else None, 2):>10} "
            f"{format_optional(tpt.p95 if tpt else None, 2):>10} "
            f"{format_optional(tot.average if tot else None, 0):>10} "
            f"{format_optional(tot.p95 if tot else None, 0):>10} "
            f"{format_optional(req.average if req else None, 0):>11} "
            f"{format_optional(res.average if res else None, 0):>11} "
            f"{format_optional(res.max if res else None, 0):>11}"
        )

    print()

    # Table 2: Outcome counts
    print("Outcome counts (last 30 days):")
    print(f"{'day':<12} {'completed':>9} {'failed':>7} {'cancelled':>9}")
    print("-" * 42)
    for r in rollups:
        print(f"{r.day:<12} {r.completed:>9} {r.failed:>7} {r.cancelled:>9}")


def run_observability(
    cfg: TuochatConfig,
    command: ObservabilityCommand,
    *,
    build_store: Callable[[TuochatConfig], ConversationStore | NullConversationStore],
    no_write_enabled: Callable[[TuochatConfig], bool],
    current_store: ConversationStore | NullConversationStore | None = None,
) -> int:
    """Show 30-day Duo response observability data."""
    if no_write_enabled(cfg):
        msg = "Observability is unavailable while no-write mode is enabled."
        if command.format == "json":
            print(json_dumps({"available": False, "reason": msg}))
        else:
            print(msg)
        return 0

    store = current_store or build_store(cfg)
    try:
        since = retention_cutoff_iso(30)
        rollups = store.get_observability_rollups(since)
    finally:
        if current_store is None:
            store.close()

    if command.format == "json":
        payload = {
            "available": True,
            "retention_days": 30,
            "since": since,
            "rollups": [rollup_to_dict(r) for r in rollups],
        }
        print(json_dumps(payload, indent=True))
        return 0

    print_observability_text(rollups)
    return 0
