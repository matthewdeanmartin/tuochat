"""Unit tests for tuochat.self_pkg_mgmt.cache."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from tuochat.self_pkg_mgmt.cache import COOLOFF, Cache, format_iso, parse_iso

# ---------------------------------------------------------------------------
# parse_iso / format_iso
# ---------------------------------------------------------------------------


def test_parse_iso_z_suffix():
    dt = parse_iso("2026-04-08T12:00:00Z")
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.year == 2026


def test_parse_iso_plus00():
    dt = parse_iso("2026-04-08T12:00:00+00:00")
    assert dt is not None


def test_parse_iso_naive_gets_utc():
    dt = parse_iso("2026-04-08T12:00:00")
    assert dt is not None
    assert dt.tzinfo == timezone.utc


def test_parse_iso_none():
    assert parse_iso(None) is None


def test_parse_iso_empty():
    assert parse_iso("") is None


def test_parse_iso_bad():
    assert parse_iso("not-a-date") is None


def test_format_iso_roundtrip():
    dt = datetime(2026, 4, 8, 12, 0, 0, tzinfo=timezone.utc)
    result = format_iso(dt)
    assert result.endswith("Z")
    assert parse_iso(result) == dt


def test_format_iso_naive_assumes_utc():
    dt = datetime(2026, 4, 8, 12, 0, 0)
    result = format_iso(dt)
    assert "Z" in result or "+00" in result


# ---------------------------------------------------------------------------
# Cache.load — missing and corrupt files
# ---------------------------------------------------------------------------


def test_load_missing_file(tmp_path):
    cache = Cache.load(tmp_path)
    assert cache.data["schema"] == 1
    assert cache.data["pypi"] == {}


def test_load_corrupt_json(tmp_path):
    (tmp_path / "self_pkg_mgmt.json").write_text("not json", encoding="utf-8")
    cache = Cache.load(tmp_path)
    assert cache.data["pypi"] == {}


def test_load_wrong_schema(tmp_path):
    (tmp_path / "self_pkg_mgmt.json").write_text(json.dumps({"schema": 99, "pypi": {"foo": "bar"}}), encoding="utf-8")
    cache = Cache.load(tmp_path)
    # wrong schema → data not merged, pypi stays empty
    assert cache.data["pypi"] == {}


def test_load_valid_file(tmp_path):
    data = {"schema": 1, "pypi": {"tuochat": {"latest": "0.4.0", "published": None, "fetched": "2026-04-08T00:00:00Z"}}}
    (tmp_path / "self_pkg_mgmt.json").write_text(json.dumps(data), encoding="utf-8")
    cache = Cache.load(tmp_path)
    assert cache.data["pypi"]["tuochat"]["latest"] == "0.4.0"


# ---------------------------------------------------------------------------
# Cache.save — atomic write, permissions
# ---------------------------------------------------------------------------


def test_save_creates_file(tmp_path):
    cache = Cache.load(tmp_path)
    cache.put_package("example", "1.0.0", None)
    cache.save()
    saved = json.loads((tmp_path / "self_pkg_mgmt.json").read_text(encoding="utf-8"))
    assert saved["pypi"]["example"]["latest"] == "1.0.0"


def test_save_roundtrip(tmp_path):
    cache = Cache.load(tmp_path)
    cache.put_package("mylib", "2.3.4", datetime(2026, 1, 1, tzinfo=timezone.utc))
    cache.save()

    cache2 = Cache.load(tmp_path)
    assert cache2.data["pypi"]["mylib"]["latest"] == "2.3.4"


# ---------------------------------------------------------------------------
# TTL / freshness
# ---------------------------------------------------------------------------


def test_is_fresh_new_entry(tmp_path):
    cache = Cache.load(tmp_path)
    cache.put_package("fresh", "1.0", None)
    assert cache.is_fresh("fresh") is True


def test_is_fresh_old_entry(tmp_path, monkeypatch):
    cache = Cache.load(tmp_path)
    # Plant a fetched timestamp 25 hours ago
    old_time = datetime.now(timezone.utc) - timedelta(hours=25)
    cache.data.setdefault("pypi", {})["stale"] = {
        "latest": "1.0",
        "published": None,
        "fetched": format_iso(old_time),
    }
    assert cache.is_fresh("stale") is False


def test_is_fresh_missing_package(tmp_path):
    cache = Cache.load(tmp_path)
    assert cache.is_fresh("nonexistent") is False


def test_is_fresh_custom_ttl(tmp_path):
    cache = Cache.load(tmp_path)
    cache.put_package("pkg", "1.0", None)
    # Zero TTL → always stale
    assert cache.is_fresh("pkg", ttl=timedelta(seconds=0)) is False


# ---------------------------------------------------------------------------
# Cooloff
# ---------------------------------------------------------------------------


def test_cooloff_recent_package(tmp_path):
    cache = Cache.load(tmp_path)
    # published 1 day ago → inside 14-day cooloff
    recent = datetime.now(timezone.utc) - timedelta(days=1)
    cache.put_package("newpkg", "0.1", recent)
    assert cache.is_in_cooloff("newpkg") is True


def test_cooloff_old_package(tmp_path):
    cache = Cache.load(tmp_path)
    # published 20 days ago → outside cooloff
    old = datetime.now(timezone.utc) - timedelta(days=20)
    cache.put_package("oldpkg", "1.0", old)
    assert cache.is_in_cooloff("oldpkg") is False


def test_cooloff_boundary_exactly_14_days(tmp_path):
    cache = Cache.load(tmp_path)
    # exactly at boundary → just outside cooloff (age == COOLOFF is not < COOLOFF)
    boundary = datetime.now(timezone.utc) - COOLOFF
    cache.put_package("boundary", "1.0", boundary)
    assert cache.is_in_cooloff("boundary") is False


def test_cooloff_no_published(tmp_path):
    cache = Cache.load(tmp_path)
    cache.put_package("nopub", "1.0", None)
    assert cache.is_in_cooloff("nopub") is False


def test_cooloff_missing_package(tmp_path):
    cache = Cache.load(tmp_path)
    assert cache.is_in_cooloff("ghost") is False


# ---------------------------------------------------------------------------
# Snooze
# ---------------------------------------------------------------------------


def test_snooze_active(tmp_path):
    cache = Cache.load(tmp_path)
    cache.snooze("tuochat==0.5.0", days=7)
    assert cache.is_snoozed("tuochat==0.5.0") is True


def test_snooze_not_snoozed(tmp_path):
    cache = Cache.load(tmp_path)
    assert cache.is_snoozed("tuochat==0.5.0") is False


def test_snooze_expired(tmp_path):
    cache = Cache.load(tmp_path)
    past = datetime.now(timezone.utc) - timedelta(days=1)
    cache.data.setdefault("suppressed_until", {})["tuochat==0.5.0"] = format_iso(past)
    assert cache.is_snoozed("tuochat==0.5.0") is False


def test_prune_snoozes_removes_expired(tmp_path):
    cache = Cache.load(tmp_path)
    past = datetime.now(timezone.utc) - timedelta(days=1)
    future = datetime.now(timezone.utc) + timedelta(days=7)
    cache.data["suppressed_until"] = {
        "old==1.0": format_iso(past),
        "current==2.0": format_iso(future),
    }
    cache.prune_snoozes()
    assert "old==1.0" not in cache.data["suppressed_until"]
    assert "current==2.0" in cache.data["suppressed_until"]


def test_prune_snoozes_empty(tmp_path):
    cache = Cache.load(tmp_path)
    cache.prune_snoozes()  # must not raise


# ---------------------------------------------------------------------------
# Audit summary
# ---------------------------------------------------------------------------


def test_audit_is_fresh_after_set(tmp_path):
    cache = Cache.load(tmp_path)
    cache.set_audit("pip-audit", {"vuln_count": 0})
    assert cache.audit_is_fresh() is True


def test_audit_is_fresh_missing(tmp_path):
    cache = Cache.load(tmp_path)
    assert cache.audit_is_fresh() is False


def test_audit_is_fresh_stale(tmp_path):
    cache = Cache.load(tmp_path)
    old = datetime.now(timezone.utc) - timedelta(hours=25)
    cache.data["last_audit_utc"] = format_iso(old)
    assert cache.audit_is_fresh() is False


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


def test_clear_resets_data(tmp_path):
    cache = Cache.load(tmp_path)
    cache.put_package("x", "1.0", None)
    cache.snooze("x==1.0", days=3)
    cache.clear()
    assert cache.data["pypi"] == {}
    assert cache.data["suppressed_until"] == {}
    assert cache.data["schema"] == 1
