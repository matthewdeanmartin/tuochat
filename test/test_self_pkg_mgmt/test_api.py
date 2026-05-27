"""Unit tests for tuochat.self_pkg_mgmt.api."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from tuochat.self_pkg_mgmt import api
from tuochat.self_pkg_mgmt.cache import Cache
from tuochat.self_pkg_mgmt.host import GenericHost
from tuochat.self_pkg_mgmt.install_method import InstallMethod
from tuochat.self_pkg_mgmt.report import VersionInfo, Vulnerability
from tuochat.self_pkg_mgmt.upgrade import UpgradeResult


def make_host(tmp_path: Path) -> GenericHost:
    return GenericHost(dist_name="fakepkg", cache_dir=tmp_path)


def version_info(
    name: str = "fakepkg",
    installed: str = "1.0",
    latest: str | None = "2.0",
    is_upgrade_available: bool = True,
    is_in_cooloff: bool = False,
) -> VersionInfo:
    return VersionInfo(
        name=name,
        installed=installed,
        latest=latest,
        latest_published=None,
        age_days=None,
        is_upgrade_available=is_upgrade_available,
        is_in_cooloff=is_in_cooloff,
    )


# ---------------------------------------------------------------------------
# build_version_info
# ---------------------------------------------------------------------------


def test_build_version_info_no_cache_entry(tmp_path):
    cache = Cache.load(tmp_path)
    info = api.build_version_info("mypkg", "1.0", cache)
    assert info.name == "mypkg"
    assert info.installed == "1.0"
    assert info.latest is None
    assert info.is_upgrade_available is False


def test_build_version_info_with_cache_entry(tmp_path):
    cache = Cache.load(tmp_path)
    old = datetime(2025, 1, 1, tzinfo=timezone.utc)
    cache.put_package("mypkg", "2.0", old)
    info = api.build_version_info("mypkg", "1.0", cache)
    assert info.latest == "2.0"
    assert info.is_upgrade_available is True
    assert info.is_in_cooloff is False
    assert info.age_days is not None
    assert info.age_days > 0


def test_build_version_info_same_version_no_upgrade(tmp_path):
    cache = Cache.load(tmp_path)
    cache.put_package("mypkg", "1.0", None)
    info = api.build_version_info("mypkg", "1.0", cache)
    assert info.is_upgrade_available is False


def test_build_version_info_snoozed(tmp_path):
    cache = Cache.load(tmp_path)
    cache.put_package("mypkg", "2.0", None)
    cache.snooze("mypkg==2.0", days=7)
    info = api.build_version_info("mypkg", "1.0", cache)
    assert info.is_upgrade_available is False


def test_build_version_info_cooloff(tmp_path):
    from datetime import timedelta

    cache = Cache.load(tmp_path)
    recent = datetime.now(timezone.utc) - timedelta(days=1)
    cache.put_package("mypkg", "2.0", recent)
    info = api.build_version_info("mypkg", "1.0", cache)
    assert info.is_in_cooloff is True
    assert info.age_days is not None


def test_build_version_info_no_published(tmp_path):
    cache = Cache.load(tmp_path)
    cache.put_package("mypkg", "2.0", None)
    info = api.build_version_info("mypkg", "1.0", cache)
    assert info.age_days is None
    assert info.is_in_cooloff is False


# ---------------------------------------------------------------------------
# refresh_pypi
# ---------------------------------------------------------------------------


def test_refresh_pypi_skips_fresh(tmp_path, monkeypatch):
    host = make_host(tmp_path)
    cache = Cache.load(tmp_path)
    cache.put_package("fakepkg", "1.0", None)
    cache.save()

    calls = []
    monkeypatch.setattr(api.pypi, "get_latest", lambda name: calls.append(name) or ("2.0", None))
    errors = api.refresh_pypi(host, ["fakepkg"])
    assert errors == []
    assert calls == []  # skipped because fresh


def test_refresh_pypi_fetches_stale(tmp_path, monkeypatch):
    host = make_host(tmp_path)
    monkeypatch.setattr(api.pypi, "get_latest", lambda name: ("2.0", None))
    errors = api.refresh_pypi(host, ["fakepkg"])
    assert errors == []
    cache = Cache.load(tmp_path)
    assert cache.get_package("fakepkg") is not None


def test_refresh_pypi_handles_pypi_error(tmp_path, monkeypatch):
    host = make_host(tmp_path)

    def bad_get_latest(name):
        raise api.pypi.PypiError("network down")

    monkeypatch.setattr(api.pypi, "get_latest", bad_get_latest)
    errors = api.refresh_pypi(host, ["fakepkg"])
    assert len(errors) == 1
    assert "network down" in errors[0]


def test_refresh_pypi_no_save_if_unchanged(tmp_path, monkeypatch):
    host = make_host(tmp_path)
    # All packages fresh → no save needed
    cache = Cache.load(tmp_path)
    cache.put_package("fakepkg", "1.0", None)
    cache.save()

    save_calls = []
    original_save = Cache.save

    def spy_save(self):
        save_calls.append(1)
        original_save(self)

    monkeypatch.setattr(Cache, "save", spy_save)
    api.refresh_pypi(host, ["fakepkg"])
    assert save_calls == []


# ---------------------------------------------------------------------------
# check_for_updates
# ---------------------------------------------------------------------------


def test_check_for_updates_off(tmp_path):
    host = make_host(tmp_path)
    report = api.check_for_updates(host=host, position="off")
    assert report.host_dist is None
    assert report.dependencies == ()


def test_check_for_updates_missing_host_dist(tmp_path, monkeypatch):
    host = make_host(tmp_path)
    monkeypatch.setattr(api.installed, "host_version", lambda name: None)
    report = api.check_for_updates(host=host, position="start", allow_network=False)
    assert len(report.errors) == 1
    assert "fakepkg" in report.errors[0]


def test_check_for_updates_start_no_network(tmp_path, monkeypatch):
    host = make_host(tmp_path)
    monkeypatch.setattr(api.installed, "host_version", lambda name: "1.0")
    monkeypatch.setattr(api.installed, "direct_dependencies", lambda name: [])
    monkeypatch.setattr(api.background, "spawn", lambda fn: None)

    cache = Cache.load(tmp_path)
    cache.put_package("fakepkg", "2.0", None)
    cache.save()

    report = api.check_for_updates(host=host, position="start", allow_network=False)
    assert report.host_dist is not None
    assert report.host_dist.installed == "1.0"


def test_check_for_updates_start_spawns_background(tmp_path, monkeypatch):
    host = make_host(tmp_path)
    monkeypatch.setattr(api.installed, "host_version", lambda name: "1.0")
    monkeypatch.setattr(api.installed, "direct_dependencies", lambda name: [])

    spawned = []
    monkeypatch.setattr(api.background, "spawn", lambda fn: spawned.append(fn))

    _ = api.check_for_updates(host=host, position="start", allow_network=True)
    assert len(spawned) == 1


def test_check_for_updates_start_no_spawn_when_all_fresh(tmp_path, monkeypatch):
    host = make_host(tmp_path)
    monkeypatch.setattr(api.installed, "host_version", lambda name: "1.0")
    monkeypatch.setattr(api.installed, "direct_dependencies", lambda name: [])

    cache = Cache.load(tmp_path)
    cache.put_package("fakepkg", "1.0", None)
    cache.save()

    spawned = []
    monkeypatch.setattr(api.background, "spawn", lambda fn: spawned.append(fn))

    api.check_for_updates(host=host, position="start", allow_network=True)
    assert spawned == []


def test_check_for_updates_end_refreshes_synchronously(tmp_path, monkeypatch):
    host = make_host(tmp_path)
    monkeypatch.setattr(api.installed, "host_version", lambda name: "1.0")
    monkeypatch.setattr(api.installed, "direct_dependencies", lambda name: [])
    monkeypatch.setattr(api.pypi, "get_latest", lambda name: ("2.0", None))

    report = api.check_for_updates(host=host, position="end")
    assert report.host_dist is not None


def test_check_for_updates_both_runs_refresh_and_returns(tmp_path, monkeypatch):
    host = make_host(tmp_path)
    monkeypatch.setattr(api.installed, "host_version", lambda name: "1.0")
    monkeypatch.setattr(api.installed, "direct_dependencies", lambda name: [])
    monkeypatch.setattr(api.pypi, "get_latest", lambda name: ("2.0", None))

    report = api.check_for_updates(host=host, position="both")
    assert report.host_dist is not None
    assert report.host_dist.latest == "2.0"


def test_check_for_updates_cooloff_note(tmp_path, monkeypatch):
    from datetime import timedelta

    host = make_host(tmp_path)
    monkeypatch.setattr(api.installed, "host_version", lambda name: "1.0")
    monkeypatch.setattr(api.installed, "direct_dependencies", lambda name: [])

    cache = Cache.load(tmp_path)
    recent = datetime.now(timezone.utc) - timedelta(days=1)
    cache.put_package("fakepkg", "2.0", recent)
    cache.save()

    report = api.check_for_updates(host=host, position="start", allow_network=False)
    assert any("cooloff" in n for n in report.notes)


# ---------------------------------------------------------------------------
# run_audit
# ---------------------------------------------------------------------------


def test_run_audit_skips_when_nothing_actionable(tmp_path, monkeypatch):
    host = make_host(tmp_path)
    monkeypatch.setattr(api.installed, "host_version", lambda name: "1.0")
    monkeypatch.setattr(api.installed, "direct_dependencies", lambda name: [])
    cache = Cache.load(tmp_path)
    cache.put_package("fakepkg", "1.0", None)  # same version → no upgrade
    cache.save()

    report = api.run_audit(host=host, force=False)
    assert any("skipped" in n for n in report.notes)


def test_run_audit_force_runs_even_if_no_upgrade(tmp_path, monkeypatch):
    host = make_host(tmp_path)
    monkeypatch.setattr(api.installed, "host_version", lambda name: "1.0")
    monkeypatch.setattr(api.installed, "direct_dependencies", lambda name: [])
    cache = Cache.load(tmp_path)
    cache.put_package("fakepkg", "1.0", None)
    cache.save()
    monkeypatch.setattr(api.audit, "run_available_audit", lambda: ([], "pip-audit"))

    report = api.run_audit(host=host, force=True)
    assert any("pip-audit" in n for n in report.notes)


def test_run_audit_no_tool_available(tmp_path, monkeypatch):
    host = make_host(tmp_path)
    monkeypatch.setattr(api.installed, "host_version", lambda name: "1.0")
    monkeypatch.setattr(api.installed, "direct_dependencies", lambda name: [])
    cache = Cache.load(tmp_path)
    cache.put_package("fakepkg", "2.0", None)  # upgrade available → actionable
    cache.save()
    monkeypatch.setattr(api.audit, "run_available_audit", lambda: ([], None))

    report = api.run_audit(host=host, force=False)
    assert any("no audit tool" in n for n in report.notes)


def test_run_audit_returns_vulnerabilities(tmp_path, monkeypatch):
    host = make_host(tmp_path)
    monkeypatch.setattr(api.installed, "host_version", lambda name: "1.0")
    monkeypatch.setattr(api.installed, "direct_dependencies", lambda name: [])
    cache = Cache.load(tmp_path)
    cache.put_package("fakepkg", "2.0", None)
    cache.save()

    vuln = Vulnerability(
        name="fakepkg", installed="1.0", advisory_id="CVE-1", severity="high", fix_versions=("2.0",), source="pip-audit"
    )
    monkeypatch.setattr(api.audit, "run_available_audit", lambda: ([vuln], "pip-audit"))

    report = api.run_audit(host=host, force=False)
    assert len(report.vulnerabilities) == 1
    assert report.vulnerabilities[0].advisory_id == "CVE-1"


# ---------------------------------------------------------------------------
# self_upgrade
# ---------------------------------------------------------------------------


def test_self_upgrade_dry_run(tmp_path, monkeypatch):
    host = make_host(tmp_path)
    monkeypatch.setattr(
        api.upgrade,
        "perform",
        lambda dist_name, dry_run: UpgradeResult(
            method=InstallMethod.UV_TOOL,
            argv=["uv", "tool", "upgrade", dist_name],
            returncode=None,
            stdout="",
            stderr="",
            attempted=False,
        ),
    )
    result = api.self_upgrade(host=host, dry_run=True)
    assert result.attempted is False


# ---------------------------------------------------------------------------
# self_check
# ---------------------------------------------------------------------------


def test_self_check_returns_list(tmp_path):
    host = make_host(tmp_path)
    result = api.self_check(host=host)
    assert isinstance(result, list)


def test_tamper_check_uses_manifest_in_source_checkout(tmp_path, monkeypatch):
    host = make_host(tmp_path)
    monkeypatch.setattr(api.tamper, "is_source_checkout", lambda package_name: True)
    monkeypatch.setattr(
        api.tamper,
        "verify_files_against_embedded_manifest",
        lambda package_name: ["hash mismatch: sample.py"],
    )

    result = api.tamper_check(host=host)

    assert result == ["hash mismatch: sample.py"]


def test_tamper_check_accepts_manifest_fallback_when_record_fails(tmp_path, monkeypatch):
    host = make_host(tmp_path)
    monkeypatch.setattr(api.tamper, "is_source_checkout", lambda package_name: False)
    monkeypatch.setattr(api.tamper, "verify_files_against_record", lambda package_name: ["record mismatch"])
    monkeypatch.setattr(api.tamper, "verify_files_against_embedded_manifest", lambda package_name: [])

    result = api.tamper_check(host=host)

    assert result == []


# ---------------------------------------------------------------------------
# clear_cache / snooze
# ---------------------------------------------------------------------------


def test_clear_cache(tmp_path):
    host = make_host(tmp_path)
    cache = Cache.load(tmp_path)
    cache.put_package("fakepkg", "1.0", None)
    cache.save()

    api.clear_cache(host=host)

    reloaded = Cache.load(tmp_path)
    assert reloaded.data["pypi"] == {}


def test_snooze(tmp_path):
    host = make_host(tmp_path)
    api.snooze("fakepkg==2.0", days=3, host=host)
    assert Cache.load(tmp_path).is_snoozed("fakepkg==2.0") is True
