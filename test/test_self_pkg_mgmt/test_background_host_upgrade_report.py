"""Unit tests for background, host, upgrade, and report modules."""

from __future__ import annotations

import threading

from tuochat.self_pkg_mgmt import background
from tuochat.self_pkg_mgmt.host import GenericHost, TuochatHost, default_host
from tuochat.self_pkg_mgmt.install_method import InstallMethod
from tuochat.self_pkg_mgmt.report import Report, VersionInfo, Vulnerability
from tuochat.self_pkg_mgmt.upgrade import UpgradeResult, perform

# ===========================================================================
# background
# ===========================================================================


def test_spawn_runs_target():
    done = threading.Event()

    def target():
        done.set()

    thread = background.spawn(target)
    thread.join(timeout=2)
    assert done.is_set()


def test_spawn_is_daemon():
    thread = background.spawn(lambda: None)
    assert thread.daemon is True


def test_spawn_swallows_exceptions():
    """A raising target must not propagate."""
    done = threading.Event()

    def bad_target():
        done.set()
        raise RuntimeError("intentional")

    thread = background.spawn(bad_target)
    thread.join(timeout=2)
    assert done.is_set()  # ran before exception


def test_wrap_returns_callable():
    fn = background.wrap(lambda: None)
    assert callable(fn)
    fn()  # must not raise


# ===========================================================================
# host
# ===========================================================================


def test_generic_host_properties(tmp_path):
    host = GenericHost(dist_name="mypkg", cache_dir=tmp_path)
    assert host.dist_name == "mypkg"
    assert host.cache_dir == tmp_path
    assert host.logger.name == "self_pkg_mgmt.mypkg"


def test_tuochat_host_default_dist_name():
    host = TuochatHost()
    assert host.dist_name == "tuochat"


def test_tuochat_host_custom_cache_dir(tmp_path):
    host = TuochatHost(cache_dir=tmp_path)
    assert host.cache_dir == tmp_path


def test_tuochat_host_logger_name():
    host = TuochatHost()
    assert host.logger.name == "tuochat.self_pkg_mgmt"


def test_default_host_returns_host_protocol(tmp_path):
    host = default_host("tuochat")
    assert hasattr(host, "dist_name")
    assert hasattr(host, "cache_dir")
    assert hasattr(host, "logger")


def test_tuochat_host_protocol_conformance():
    from tuochat.self_pkg_mgmt.host import Host

    host = TuochatHost()
    assert isinstance(host, Host)


def test_generic_host_protocol_conformance(tmp_path):
    from tuochat.self_pkg_mgmt.host import Host

    host = GenericHost(dist_name="x", cache_dir=tmp_path)
    assert isinstance(host, Host)


# ===========================================================================
# upgrade.UpgradeResult
# ===========================================================================


def test_upgrade_result_ok_true():
    r = UpgradeResult(
        method=InstallMethod.UV_TOOL,
        argv=["uv", "tool", "upgrade", "pkg"],
        returncode=0,
        stdout="done",
        stderr="",
        attempted=True,
    )
    assert r.ok is True


def test_upgrade_result_ok_false_not_attempted():
    r = UpgradeResult(
        method=InstallMethod.UNKNOWN,
        argv=None,
        returncode=None,
        stdout="",
        stderr="",
        attempted=False,
    )
    assert r.ok is False


def test_upgrade_result_ok_false_nonzero_rc():
    r = UpgradeResult(
        method=InstallMethod.VENV_PIP,
        argv=["pip", "install", "--upgrade", "pkg"],
        returncode=1,
        stdout="",
        stderr="error",
        attempted=True,
    )
    assert r.ok is False


# ===========================================================================
# upgrade.perform
# ===========================================================================


def test_perform_dry_run_does_not_call_subprocess(monkeypatch):
    import tuochat.self_pkg_mgmt.upgrade as upgrade_module

    monkeypatch.setattr(upgrade_module, "detect", lambda name: InstallMethod.UV_TOOL)

    called = []
    import subprocess

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: called.append(1))

    result = perform("fakepkg", dry_run=True)
    assert result.attempted is False
    assert called == []


def test_perform_editable_returns_not_attempted(monkeypatch):
    import tuochat.self_pkg_mgmt.upgrade as upgrade_module

    monkeypatch.setattr(upgrade_module, "detect", lambda name: InstallMethod.EDITABLE)

    result = perform("fakepkg")
    assert result.attempted is False
    assert result.argv is None


def test_perform_unknown_returns_not_attempted(monkeypatch):
    import tuochat.self_pkg_mgmt.upgrade as upgrade_module

    monkeypatch.setattr(upgrade_module, "detect", lambda name: InstallMethod.UNKNOWN)

    result = perform("fakepkg")
    assert result.attempted is False


def test_perform_subprocess_success(monkeypatch):
    import subprocess

    import tuochat.self_pkg_mgmt.upgrade as upgrade_module

    monkeypatch.setattr(upgrade_module, "detect", lambda name: InstallMethod.UV_TOOL)

    fake_proc = type("P", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake_proc)

    result = perform("fakepkg")
    assert result.ok is True
    assert result.stdout == "ok"


def test_perform_subprocess_file_not_found(monkeypatch):
    import subprocess

    import tuochat.self_pkg_mgmt.upgrade as upgrade_module

    monkeypatch.setattr(upgrade_module, "detect", lambda name: InstallMethod.UV_TOOL)
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError("not found")))

    result = perform("fakepkg")
    assert result.attempted is True
    assert result.returncode is None
    assert "not found" in result.stderr


def test_perform_subprocess_timeout(monkeypatch):
    import subprocess

    import tuochat.self_pkg_mgmt.upgrade as upgrade_module

    monkeypatch.setattr(upgrade_module, "detect", lambda name: InstallMethod.VENV_PIP)
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd="pip", timeout=300))
    )

    result = perform("fakepkg")
    assert result.attempted is True
    assert result.returncode is None


# ===========================================================================
# report
# ===========================================================================


def test_version_info_actionable_true():
    vi = VersionInfo(
        name="pkg",
        installed="1.0",
        latest="2.0",
        latest_published=None,
        age_days=None,
        is_upgrade_available=True,
        is_in_cooloff=False,
    )
    assert vi.actionable is True


def test_version_info_actionable_false_cooloff():
    vi = VersionInfo(
        name="pkg",
        installed="1.0",
        latest="2.0",
        latest_published=None,
        age_days=None,
        is_upgrade_available=True,
        is_in_cooloff=True,
    )
    assert vi.actionable is False


def test_version_info_actionable_false_no_upgrade():
    vi = VersionInfo(
        name="pkg",
        installed="1.0",
        latest="1.0",
        latest_published=None,
        age_days=None,
        is_upgrade_available=False,
        is_in_cooloff=False,
    )
    assert vi.actionable is False


def test_vulnerability_actionable_with_fix():
    v = Vulnerability(
        name="pkg", installed="1.0", advisory_id="CVE-1", severity="high", fix_versions=("2.0",), source="pip-audit"
    )
    assert v.actionable is True


def test_vulnerability_actionable_no_fix():
    v = Vulnerability(
        name="pkg", installed="1.0", advisory_id="CVE-1", severity="high", fix_versions=(), source="pip-audit"
    )
    assert v.actionable is False


def test_report_is_empty_default():
    assert Report().is_empty is True


def test_report_is_empty_with_actionable_host():
    vi = VersionInfo(
        name="pkg",
        installed="1.0",
        latest="2.0",
        latest_published=None,
        age_days=None,
        is_upgrade_available=True,
        is_in_cooloff=False,
    )
    assert Report(host_dist=vi).is_empty is False


def test_report_is_empty_with_actionable_dep():
    vi = VersionInfo(
        name="dep",
        installed="1.0",
        latest="2.0",
        latest_published=None,
        age_days=None,
        is_upgrade_available=True,
        is_in_cooloff=False,
    )
    assert Report(dependencies=(vi,)).is_empty is False


def test_report_is_empty_with_actionable_vuln():
    v = Vulnerability(
        name="pkg", installed="1.0", advisory_id="CVE-1", severity="high", fix_versions=("2.0",), source="pip-audit"
    )
    assert Report(vulnerabilities=(v,)).is_empty is False


def test_report_render_text_empty():
    assert Report().render_text() == ""


def test_report_render_text_host_upgrade():
    vi = VersionInfo(
        name="mypkg",
        installed="1.0",
        latest="2.0",
        latest_published=None,
        age_days=None,
        is_upgrade_available=True,
        is_in_cooloff=False,
    )
    text = Report(host_dist=vi).render_text()
    assert "mypkg 1.0 -> 2.0" in text


def test_report_render_text_deps():
    vi = VersionInfo(
        name="dep",
        installed="0.9",
        latest="1.0",
        latest_published=None,
        age_days=None,
        is_upgrade_available=True,
        is_in_cooloff=False,
    )
    text = Report(dependencies=(vi,)).render_text()
    assert "dep 0.9 -> 1.0" in text


def test_report_render_text_vulnerability():
    v = Vulnerability(
        name="pkg", installed="1.0", advisory_id="CVE-1", severity="high", fix_versions=("2.0",), source="pip-audit"
    )
    text = Report(vulnerabilities=(v,)).render_text()
    assert "CVE-1" in text
    assert "high" in text
    assert "2.0" in text


def test_report_render_text_notes_and_errors():
    text = Report(notes=("a note",), errors=("an error",)).render_text()
    assert "[note] a note" in text
    assert "[warn] an error" in text


def test_report_render_text_vuln_no_severity():
    v = Vulnerability(
        name="pkg", installed="1.0", advisory_id="CVE-2", severity=None, fix_versions=("1.1",), source="safety"
    )
    text = Report(vulnerabilities=(v,)).render_text()
    assert "unknown" in text
