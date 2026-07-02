"""Unit tests for the observability module and store integration."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tuochat.observability import (
    DailyMetricSummary,
    DailyRollup,
    ObservabilityRow,
    build_daily_rollups,
    compute_metric_summary,
    day_bucket,
    ms_between,
    retention_cutoff_iso,
    rollup_to_dict,
)
from tuochat.persistence.store import ConversationStore, NullConversationStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_row(
    status: str = "completed",
    started_offset_hours: float = 0.0,
    request_tokens: int = 100,
    response_tokens: int | None = 200,
    ttfb_ms: int | None = 300,
    total_ms: int = 1500,
    tpt: float | None = None,
) -> dict:
    """Build a raw row dict for rollup tests."""
    base = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    started = base + timedelta(hours=started_offset_hours)
    return {
        "request_started_at": started.isoformat(),
        "status": status,
        "request_tokens": request_tokens,
        "response_tokens": response_tokens,
        "time_to_first_token_ms": ttfb_ms,
        "total_response_ms": total_ms,
        "time_per_token_ms": tpt,
    }


@pytest.fixture()
def store(tmp_path: Path) -> Iterator[ConversationStore]:
    with ConversationStore(tmp_path / "obs_test.db") as s:
        yield s


# ---------------------------------------------------------------------------
# compute_metric_summary
# ---------------------------------------------------------------------------


def test_compute_metric_summary_empty() -> None:
    assert compute_metric_summary([]) is None


def test_compute_metric_summary_single() -> None:
    result = compute_metric_summary([42.0])
    assert result is not None
    assert result.count == 1
    assert result.average == 42.0
    assert result.median == 42.0
    assert result.p95 == 42.0
    assert result.max == 42.0


def test_compute_metric_summary_multiple() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    result = compute_metric_summary(values)
    assert result is not None
    assert result.count == 10
    assert result.average == 5.5
    assert result.median == pytest.approx(5.5)
    assert result.max == 10.0
    # p95 index = max(0, int(10*0.95)-1) = max(0, 9-1) = 8 => sorted[8] = 9.0
    assert result.p95 == 9.0


def test_compute_metric_summary_p95_small_list() -> None:
    result = compute_metric_summary([1.0, 2.0, 3.0])
    assert result is not None
    # p95 index = max(0, int(3*0.95)-1) = max(0, 2-1) = 1 => sorted[1] = 2.0
    assert result.p95 == 2.0


# ---------------------------------------------------------------------------
# day_bucket
# ---------------------------------------------------------------------------


def test_day_bucket_utc() -> None:
    ts = "2025-03-15T14:30:00+00:00"
    assert day_bucket(ts) == "2025-03-15"


def test_day_bucket_naive_treated_as_utc() -> None:
    ts = "2025-03-15T23:59:59"
    assert day_bucket(ts) == "2025-03-15"


def test_day_bucket_offset_crosses_day() -> None:
    # +10:00 → same moment is 2025-03-14 in UTC
    ts = "2025-03-15T05:00:00+10:00"
    assert day_bucket(ts) == "2025-03-14"


# ---------------------------------------------------------------------------
# ms_between
# ---------------------------------------------------------------------------


def test_ms_between() -> None:
    start = "2025-01-01T00:00:00+00:00"
    end = "2025-01-01T00:00:01.500+00:00"
    assert ms_between(start, end) == 1500


def test_ms_between_same_time() -> None:
    ts = "2025-01-01T00:00:00+00:00"
    assert ms_between(ts, ts) == 0


def test_ms_between_clamps_negative() -> None:
    start = "2025-01-01T00:00:01+00:00"
    end = "2025-01-01T00:00:00+00:00"
    assert ms_between(start, end) == 0


# ---------------------------------------------------------------------------
# retention_cutoff_iso
# ---------------------------------------------------------------------------


def test_retention_cutoff_iso_is_in_past() -> None:
    now = datetime.now(timezone.utc)
    cutoff = datetime.fromisoformat(retention_cutoff_iso(30))
    assert cutoff < now
    delta = now - cutoff
    assert 29 <= delta.days <= 31


# ---------------------------------------------------------------------------
# build_daily_rollups
# ---------------------------------------------------------------------------


def test_build_daily_rollups_empty() -> None:
    assert build_daily_rollups([]) == []


def test_build_daily_rollups_single_completed() -> None:
    rows = [make_row(status="completed", total_ms=1000, response_tokens=100, ttfb_ms=200, tpt=10.0)]
    rollups = build_daily_rollups(rows)
    assert len(rollups) == 1
    r = rollups[0]
    assert r.day == "2025-01-15"
    assert r.completed == 1
    assert r.failed == 0
    assert r.cancelled == 0
    assert r.total_response_ms is not None
    assert r.total_response_ms.count == 1
    assert r.total_response_ms.average == 1000.0


def test_build_daily_rollups_mixed_statuses() -> None:
    rows = [
        make_row(status="completed"),
        make_row(status="failed", response_tokens=None, ttfb_ms=None),
        make_row(status="cancelled", response_tokens=50, ttfb_ms=None),
    ]
    rollups = build_daily_rollups(rows)
    assert len(rollups) == 1
    r = rollups[0]
    assert r.completed == 1
    assert r.failed == 1
    assert r.cancelled == 1
    # Only completed row contributes to metric summaries
    assert r.total_response_ms is not None
    assert r.total_response_ms.count == 1


def test_build_daily_rollups_multiple_days() -> None:
    rows = [
        make_row(status="completed", started_offset_hours=0),  # day 2025-01-15
        make_row(status="completed", started_offset_hours=25),  # day 2025-01-16
        make_row(status="failed", started_offset_hours=26),  # day 2025-01-16
    ]
    rollups = build_daily_rollups(rows)
    assert len(rollups) == 2
    days = [r.day for r in rollups]
    assert "2025-01-15" in days
    assert "2025-01-16" in days
    day16 = next(r for r in rollups if r.day == "2025-01-16")
    assert day16.completed == 1
    assert day16.failed == 1


def test_build_daily_rollups_no_completed_for_day() -> None:
    rows = [make_row(status="failed", response_tokens=None, ttfb_ms=None)]
    rollups = build_daily_rollups(rows)
    assert len(rollups) == 1
    r = rollups[0]
    assert r.failed == 1
    assert r.total_response_ms is None


# ---------------------------------------------------------------------------
# rollup_to_dict
# ---------------------------------------------------------------------------


def test_rollup_to_dict_structure() -> None:
    rollup = DailyRollup(
        day="2025-01-15",
        total_response_ms=DailyMetricSummary(count=1, average=1000.0, median=1000.0, p95=1000.0, max=1000.0),
        completed=1,
    )
    d = rollup_to_dict(rollup)
    assert d["day"] == "2025-01-15"
    assert d["completed"] == 1
    assert d["total_response_ms"] is not None
    assert d["total_response_ms"]["count"] == 1
    assert d["request_tokens"] is None


# ---------------------------------------------------------------------------
# ConversationStore observability integration
# ---------------------------------------------------------------------------


def obs_row(
    status: str = "completed",
    started_iso: str = "2025-01-15T12:00:00+00:00",
    finished_iso: str = "2025-01-15T12:00:01.500+00:00",
    request_tokens: int = 100,
    response_tokens: int | None = 200,
    total_ms: int = 1500,
) -> ObservabilityRow:
    return ObservabilityRow(
        provider="gitlab_duo",
        status=status,
        request_started_at=started_iso,
        finished_at=finished_iso,
        request_tokens=request_tokens,
        total_response_ms=total_ms,
        response_tokens=response_tokens,
        time_to_first_token_ms=300 if status == "completed" else None,
        time_per_token_ms=(total_ms / response_tokens) if (status == "completed" and response_tokens) else None,
    )


def test_store_save_and_get_observability_rows(store: ConversationStore) -> None:
    row = obs_row()
    store.save_observability_row(row)
    rows = store.get_observability_rows("2025-01-01T00:00:00+00:00")
    assert len(rows) == 1
    assert rows[0]["status"] == "completed"
    assert rows[0]["provider"] == "gitlab_duo"
    assert rows[0]["request_tokens"] == 100


def test_store_get_observability_rows_filters_by_date(store: ConversationStore) -> None:
    store.save_observability_row(
        obs_row(started_iso="2025-01-10T00:00:00+00:00", finished_iso="2025-01-10T00:00:01+00:00")
    )
    store.save_observability_row(
        obs_row(started_iso="2025-01-20T00:00:00+00:00", finished_iso="2025-01-20T00:00:01+00:00")
    )
    rows = store.get_observability_rows("2025-01-15T00:00:00+00:00")
    assert len(rows) == 1
    assert "2025-01-20" in rows[0]["request_started_at"]


def test_store_cleanup_observability_retention(store: ConversationStore) -> None:
    old_ts = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    new_ts = datetime.now(timezone.utc).isoformat()
    finished_old = (datetime.now(timezone.utc) - timedelta(days=40) + timedelta(seconds=1)).isoformat()
    finished_new = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
    store.save_observability_row(obs_row(started_iso=old_ts, finished_iso=finished_old))
    store.save_observability_row(obs_row(started_iso=new_ts, finished_iso=finished_new))
    deleted = store.cleanup_observability_retention(days=30)
    assert deleted == 1
    rows = store.get_observability_rows("1970-01-01T00:00:00+00:00")
    assert len(rows) == 1


def test_store_get_observability_rollups_triggers_cleanup(store: ConversationStore) -> None:
    old_ts = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    finished_old = (datetime.now(timezone.utc) - timedelta(days=40) + timedelta(seconds=1)).isoformat()
    store.save_observability_row(obs_row(started_iso=old_ts, finished_iso=finished_old))
    since = retention_cutoff_iso(30)
    rollups = store.get_observability_rollups(since)
    # The old row should be cleaned up during rollup fetch
    remaining = store.get_observability_rows("1970-01-01T00:00:00+00:00")
    assert len(remaining) == 0
    assert rollups == []


def test_null_store_observability_noop() -> None:
    from pathlib import Path

    s = NullConversationStore(Path("/dev/null"))
    row = obs_row()
    s.save_observability_row(row)  # no-op, should not raise
    assert s.get_observability_rows("2025-01-01T00:00:00+00:00") == []
    assert s.get_observability_rollups("2025-01-01T00:00:00+00:00") == []
    assert s.cleanup_observability_retention() == 0
