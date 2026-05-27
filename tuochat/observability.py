"""Observability models and aggregation for Duo response performance tracking.

Records per-response metrics (latency, token counts) in SQLite and computes
daily rollups for CLI and GUI display.  Eliza is excluded entirely.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ObservabilityRow:
    """One Duo response attempt, ready for persistence."""

    provider: str  # always "gitlab_duo"
    status: str  # "completed" | "failed" | "cancelled"
    request_started_at: str  # UTC ISO timestamp
    finished_at: str  # UTC ISO timestamp
    request_tokens: int
    total_response_ms: int

    conversation_id: str | None = None
    message_id: str | None = None
    request_id: str | None = None
    model: str | None = None
    first_token_at: str | None = None
    response_tokens: int | None = None
    time_to_first_token_ms: int | None = None
    time_per_token_ms: float | None = None
    error_kind: str | None = None


@dataclass
class DailyMetricSummary:
    """Statistical summary for one metric over one UTC day."""

    count: int
    average: float
    median: float
    p95: float
    max: float


@dataclass
class DailyOutcomeCounts:
    """Completed / failed / cancelled counts for one UTC day."""

    day: str  # YYYY-MM-DD
    completed: int = 0
    failed: int = 0
    cancelled: int = 0


@dataclass
class DailyRollup:
    """Full daily rollup for the observability surfaces."""

    day: str  # YYYY-MM-DD

    request_tokens: DailyMetricSummary | None = None
    response_tokens: DailyMetricSummary | None = None
    time_to_first_token_ms: DailyMetricSummary | None = None
    time_per_token_ms: DailyMetricSummary | None = None
    total_response_ms: DailyMetricSummary | None = None

    completed: int = 0
    failed: int = 0
    cancelled: int = 0


# ---------------------------------------------------------------------------
# Measurement helpers
# ---------------------------------------------------------------------------


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def ms_between(start_iso: str, end_iso: str) -> int:
    """Compute milliseconds between two UTC ISO timestamps."""
    start = datetime.fromisoformat(start_iso)
    end = datetime.fromisoformat(end_iso)
    delta = end - start
    return max(0, int(delta.total_seconds() * 1000))


def retention_cutoff_iso(days: int = 30) -> str:
    """Return the UTC ISO timestamp for the start of the retention window."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return cutoff.isoformat()


def day_bucket(iso_timestamp: str) -> str:
    """Return the UTC date string (YYYY-MM-DD) for an ISO timestamp."""
    dt = datetime.fromisoformat(iso_timestamp)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def compute_metric_summary(values: list[float]) -> DailyMetricSummary | None:
    """Compute count/average/median/p95/max for a list of values.

    Returns None when the list is empty.
    """
    if not values:
        return None
    sorted_vals = sorted(values)
    count = len(sorted_vals)
    average = sum(sorted_vals) / count
    median = statistics.median(sorted_vals)
    p95_index = max(0, int(count * 0.95) - 1)
    p95 = sorted_vals[p95_index]
    maximum = sorted_vals[-1]
    return DailyMetricSummary(
        count=count,
        average=average,
        median=median,
        p95=p95,
        max=maximum,
    )


def build_daily_rollups(rows: list[dict[str, Any]]) -> list[DailyRollup]:
    """Group raw row dicts by UTC day and compute rollup statistics.

    Completed-response metrics use only rows with status='completed'.
    Outcome counts include all rows.
    """
    # Group by day
    days_all: dict[str, list[dict[str, Any]]] = {}
    days_completed: dict[str, list[dict[str, Any]]] = {}

    for row in rows:
        day = day_bucket(row["request_started_at"])
        days_all.setdefault(day, []).append(row)
        if row["status"] == "completed":
            days_completed.setdefault(day, []).append(row)

    all_days = sorted(set(list(days_all.keys()) + list(days_completed.keys())))

    rollups: list[DailyRollup] = []
    for day in all_days:
        completed_rows = days_completed.get(day, [])
        all_rows = days_all.get(day, [])

        def extract(field_name: str, source: list[dict[str, Any]]) -> list[float]:
            return [float(r[field_name]) for r in source if r.get(field_name) is not None]

        rollup = DailyRollup(
            day=day,
            request_tokens=compute_metric_summary(extract("request_tokens", completed_rows)),
            response_tokens=compute_metric_summary(extract("response_tokens", completed_rows)),
            time_to_first_token_ms=compute_metric_summary(extract("time_to_first_token_ms", completed_rows)),
            time_per_token_ms=compute_metric_summary(extract("time_per_token_ms", completed_rows)),
            total_response_ms=compute_metric_summary(extract("total_response_ms", completed_rows)),
            completed=sum(1 for r in all_rows if r.get("status") == "completed"),
            failed=sum(1 for r in all_rows if r.get("status") == "failed"),
            cancelled=sum(1 for r in all_rows if r.get("status") == "cancelled"),
        )
        rollups.append(rollup)

    return rollups


def rollup_to_dict(rollup: DailyRollup) -> dict[str, Any]:
    """Serialize a DailyRollup to a JSON-compatible dict."""

    def summary_dict(s: DailyMetricSummary | None) -> dict[str, Any] | None:
        if s is None:
            return None
        return {
            "count": s.count,
            "average": s.average,
            "median": s.median,
            "p95": s.p95,
            "max": s.max,
        }

    return {
        "day": rollup.day,
        "request_tokens": summary_dict(rollup.request_tokens),
        "response_tokens": summary_dict(rollup.response_tokens),
        "time_to_first_token_ms": summary_dict(rollup.time_to_first_token_ms),
        "time_per_token_ms": summary_dict(rollup.time_per_token_ms),
        "total_response_ms": summary_dict(rollup.total_response_ms),
        "completed": rollup.completed,
        "failed": rollup.failed,
        "cancelled": rollup.cancelled,
    }
