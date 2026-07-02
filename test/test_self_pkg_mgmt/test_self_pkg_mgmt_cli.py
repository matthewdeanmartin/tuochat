from __future__ import annotations

import json
import runpy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tuochat.self_pkg_mgmt import cli
from tuochat.self_pkg_mgmt.cache import Cache
from tuochat.self_pkg_mgmt.host import GenericHost
from tuochat.self_pkg_mgmt.install_method import InstallMethod
from tuochat.self_pkg_mgmt.report import Report, VersionInfo, Vulnerability
from tuochat.self_pkg_mgmt.upgrade import UpgradeResult


@dataclass
class TinyDataclass:
    value: int


def make_host(tmp_path: Path) -> GenericHost:
    return GenericHost(dist_name="tuochat", cache_dir=tmp_path)


def sample_report(*, actionable: bool = True, vulnerability_fix: bool = False) -> Report:
    host_info = VersionInfo(
        name="tuochat",
        installed="0.5.0",
        latest="0.6.0",
        latest_published=datetime(2026, 4, 1, tzinfo=timezone.utc),
        age_days=9.0,
        is_upgrade_available=actionable,
        is_in_cooloff=False,
    )
    vulnerabilities: tuple[Vulnerability, ...] = ()
    if vulnerability_fix:
        vulnerabilities = (
            Vulnerability(
                name="requests",
                installed="2.0.0",
                advisory_id="GHSA-1234",
                severity="high",
                fix_versions=("2.1.0",),
                source="pip-audit",
            ),
        )
    return Report(host_dist=host_info, vulnerabilities=vulnerabilities)


def test_json_default_serializes_datetime_and_dataclass():
    now = datetime(2026, 4, 10, tzinfo=timezone.utc)

    assert cli.json_default(now) == now.isoformat()
    assert cli.json_default(TinyDataclass(3)) == {"value": 3}

    with pytest.raises(TypeError, match="cannot serialize"):
        cli.json_default(object())


def test_dump_report_outputs_text_or_empty_message(capsys):
    cli.dump_report(Report(notes=("hello",)), as_json=False)
    assert "[note] hello" in capsys.readouterr().out

    cli.dump_report(Report(), as_json=False)
    assert "No upgrades or vulnerabilities to report." in capsys.readouterr().out

    cli.dump_report(Report(notes=("json note",)), as_json=True)
    rendered = json.loads(capsys.readouterr().out)
    assert rendered["notes"] == ["json note"]


def test_cmd_status_reads_cache_and_renders_text_and_json(tmp_path, capsys):
    host = make_host(tmp_path)
    cache = Cache.load(tmp_path)
    cache.put_package("tuochat", "0.6.0", None)
    cache.set_audit("pip-audit", {"vuln_count": 0})
    cache.snooze("tuochat==0.6.0", days=3)
    cache.save()

    assert cli.cmd_status(host, as_json=False) == 0
    out = capsys.readouterr().out
    assert "Tracked packages: 1" in out
    assert "Snoozes:" in out

    assert cli.cmd_status(host, as_json=True) == 0
    rendered = json.loads(capsys.readouterr().out)
    assert rendered["pypi"]["tuochat"]["latest"] == "0.6.0"


def test_cmd_check_uses_api_report(monkeypatch, tmp_path, capsys):
    host = make_host(tmp_path)
    seen: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        cli.api,
        "check_for_updates",
        lambda host, position, allow_network: seen.append((position, allow_network)) or sample_report(),
    )

    result = cli.cmd_check(host, as_json=False, no_network=True)

    assert result == 0
    assert seen == [("start", False)]
    assert "[update] tuochat 0.5.0 -> 0.6.0 is available" in capsys.readouterr().out


def test_cmd_audit_returns_nonzero_for_actionable_vulnerability(monkeypatch, tmp_path, capsys):
    host = make_host(tmp_path)
    monkeypatch.setattr(
        cli.api, "run_audit", lambda host, force: sample_report(actionable=False, vulnerability_fix=True)
    )

    result = cli.cmd_audit(host, as_json=False, force=True)

    out = capsys.readouterr().out
    assert result == 1
    assert "[security] 1 vulnerabilities with available fixes:" in out


def test_cmd_upgrade_renders_json_and_text(monkeypatch, tmp_path, capsys):
    host = make_host(tmp_path)
    result = UpgradeResult(
        method=InstallMethod.UV_TOOL,
        argv=["uv", "tool", "upgrade", "tuochat"],
        returncode=0,
        stdout="ok",
        stderr="",
        attempted=True,
    )
    monkeypatch.setattr(cli.api, "self_upgrade", lambda host, dry_run: result)

    assert cli.cmd_upgrade(host, dry_run=False, as_json=False) == 0
    out = capsys.readouterr().out
    assert "Ran: uv tool upgrade tuochat" in out
    assert "ok" in out

    assert cli.cmd_upgrade(host, dry_run=False, as_json=True) == 0
    rendered = json.loads(capsys.readouterr().out)
    assert rendered["method"] == "uv-tool"
    assert rendered["ok"] is True


def test_cmd_upgrade_handles_missing_upgrade_path(monkeypatch, tmp_path, capsys):
    host = make_host(tmp_path)
    monkeypatch.setattr(
        cli.api,
        "self_upgrade",
        lambda host, dry_run: UpgradeResult(
            method=InstallMethod.UNKNOWN,
            argv=None,
            returncode=None,
            stdout="",
            stderr="",
            attempted=False,
        ),
    )

    result = cli.cmd_upgrade(host, dry_run=False, as_json=False)

    assert result == 1
    assert "No upgrade path for install method: unknown" in capsys.readouterr().out


def test_cmd_self_check_reports_ok_and_problems(monkeypatch, capsys):
    monkeypatch.setattr(cli.api, "self_check", lambda: [])
    monkeypatch.setattr(cli.api, "tamper_check", lambda: [])
    assert cli.cmd_self_check(as_json=False) == 0
    out = capsys.readouterr().out
    assert "OK: all installed distributions satisfy their Requires-Dist." in out
    assert "Tamper report: no modified tuochat package files found." in out

    monkeypatch.setattr(cli.api, "self_check", lambda: ["missing dependency"])
    monkeypatch.setattr(cli.api, "tamper_check", lambda: ["hash mismatch"])
    assert cli.cmd_self_check(as_json=True) == 1
    rendered = json.loads(capsys.readouterr().out)
    assert rendered["problems"] == ["missing dependency"]
    assert rendered["tamper_problems"] == ["hash mismatch"]


def test_cmd_clear_cache_and_snooze_use_real_cache(tmp_path, capsys):
    host = make_host(tmp_path)
    cache = Cache.load(tmp_path)
    cache.put_package("tuochat", "0.6.0", None)
    cache.save()

    assert cli.cmd_snooze(host, "tuochat==0.6.0", 5) == 0
    assert "Snoozed tuochat==0.6.0 for 5 day(s)." in capsys.readouterr().out
    assert Cache.load(tmp_path).is_snoozed("tuochat==0.6.0") is True

    assert cli.cmd_clear_cache(host) == 0
    assert "Cache cleared." in capsys.readouterr().out
    assert Cache.load(tmp_path).data["pypi"] == {}


def test_main_dispatches_commands(monkeypatch, tmp_path):
    host = make_host(tmp_path)
    monkeypatch.setattr(cli, "default_host", lambda dist_name="tuochat": host)
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(cli, "cmd_check", lambda host, as_json, no_network: calls.append(("check", no_network)) or 11)
    monkeypatch.setattr(cli, "cmd_status", lambda host, as_json: calls.append(("status", as_json)) or 12)
    monkeypatch.setattr(cli, "cmd_audit", lambda host, as_json, force: calls.append(("audit", force)) or 13)
    monkeypatch.setattr(cli, "cmd_upgrade", lambda host, dry_run, as_json: calls.append(("upgrade", dry_run)) or 14)
    monkeypatch.setattr(cli, "cmd_self_check", lambda as_json: calls.append(("self-check", as_json)) or 15)
    monkeypatch.setattr(cli, "cmd_clear_cache", lambda host: calls.append(("clear-cache", None)) or 16)
    monkeypatch.setattr(cli, "cmd_snooze", lambda host, target, days: calls.append(("snooze", (target, days))) or 17)

    assert cli.main(["--no-network"]) == 11
    assert cli.main(["--json", "status"]) == 12
    assert cli.main(["audit", "--force"]) == 13
    assert cli.main(["upgrade", "--dry-run"]) == 14
    assert cli.main(["self-check"]) == 15
    assert cli.main(["clear-cache"]) == 16
    assert cli.main(["snooze", "tuochat==0.6.0", "--days", "7"]) == 17
    assert calls == [
        ("check", True),
        ("status", True),
        ("audit", True),
        ("upgrade", True),
        ("self-check", False),
        ("clear-cache", None),
        ("snooze", ("tuochat==0.6.0", 7)),
    ]


def test_python_m_entrypoint_exits_with_cli_main_result(monkeypatch):
    monkeypatch.setattr(cli, "main", lambda argv=None: 23)

    with pytest.raises(SystemExit, match="23"):
        runpy.run_module("tuochat.self_pkg_mgmt.__main__", run_name="__main__")
