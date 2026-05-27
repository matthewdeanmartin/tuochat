"""Tests for tuochat.security.startup_audit."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

from tuochat.config import TuochatConfig
from tuochat.security.startup_audit import (
    already_ran_today,
    extract_json_payload,
    filter_high_critical,
    has_any_vulnerability_text,
    load_sidecar,
    parse_findings,
    run_startup_audit,
    save_sidecar,
    sidecar_path,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_cfg(tmp_path: Path) -> TuochatConfig:
    cfg = TuochatConfig()
    cfg.data_dir = tmp_path
    cfg.features.startup_audit = True
    cfg.security.audit_enabled = True
    return cfg


CLEAN_JSON = json.dumps([{"name": "requests", "version": "2.28.0", "vulns": []}])

VULN_JSON = json.dumps(
    [
        {
            "name": "flask",
            "version": "0.5",
            "vulns": [
                {
                    "id": "PYSEC-2019-179",
                    "fix_versions": ["1.0"],
                    "aliases": ["CVE-2019-1010083", "GHSA-5wv5-4vpf-pj6m"],
                    "description": "XSS vulnerability",
                    "severity": None,
                }
            ],
        }
    ]
)

HIGH_VULN_JSON = json.dumps(
    [
        {
            "name": "pillow",
            "version": "8.0.0",
            "vulns": [
                {
                    "id": "CVE-2021-34552",
                    "fix_versions": ["8.3.0"],
                    "aliases": [],
                    "description": "Buffer overflow",
                    "severity": "HIGH",
                }
            ],
        }
    ]
)

CRITICAL_VULN_JSON = json.dumps(
    [
        {
            "name": "werkzeug",
            "version": "0.15.0",
            "vulns": [
                {
                    "id": "CVE-2023-25577",
                    "fix_versions": ["2.2.3"],
                    "aliases": [],
                    "description": "Denial of service",
                    "severity": "CRITICAL",
                }
            ],
        }
    ]
)

MIXED_OUTPUT = "Found 1 known vulnerability in 1 package\n" + HIGH_VULN_JSON

WRAPPED_VULN_JSON = json.dumps(
    {
        "dependencies": [
            {
                "name": "flask",
                "version": "0.5",
                "vulns": [
                    {
                        "id": "PYSEC-2019-179",
                        "fix_versions": ["1.0"],
                        "aliases": ["CVE-2019-1010083", "GHSA-5wv5-4vpf-pj6m"],
                        "description": "XSS vulnerability",
                    }
                ],
            }
        ],
        "fixes": [],
    }
)


# ---------------------------------------------------------------------------
# Sidecar / scheduling
# ---------------------------------------------------------------------------


def test_sidecar_path(tmp_path):
    cfg = make_cfg(tmp_path)
    assert sidecar_path(cfg) == tmp_path / "audit_state.json"


def test_load_sidecar_missing(tmp_path):
    assert load_sidecar(tmp_path / "nonexistent.json") == {}


def test_load_sidecar_corrupt(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("not json", encoding="utf-8")
    assert load_sidecar(p) == {}


def test_save_and_load_sidecar(tmp_path):
    p = tmp_path / "audit_state.json"
    save_sidecar(p, {"last_run_date": "2026-04-05", "status": "clean"})
    assert load_sidecar(p) == {"last_run_date": "2026-04-05", "status": "clean"}


def test_already_ran_today_true(tmp_path):
    p = tmp_path / "audit_state.json"
    save_sidecar(p, {"last_run_date": date.today().isoformat()})
    assert already_ran_today(p) is True


def test_already_ran_today_false_yesterday(tmp_path):
    p = tmp_path / "audit_state.json"
    save_sidecar(p, {"last_run_date": "2020-01-01"})
    assert already_ran_today(p) is False


def test_already_ran_today_missing(tmp_path):
    assert already_ran_today(tmp_path / "missing.json") is False


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------


def test_extract_json_payload_plain():
    assert extract_json_payload(CLEAN_JSON) is not None


def test_extract_json_payload_with_summary_prefix():
    text = "Found 1 known vulnerability in 1 package\n" + VULN_JSON
    result = extract_json_payload(text)
    assert result is not None
    assert isinstance(result, list)


def test_extract_json_payload_wrapped_with_summary_prefix():
    text = "Found 1 known vulnerability in 1 package\n" + WRAPPED_VULN_JSON
    result = extract_json_payload(text)
    assert result is not None
    assert isinstance(result, dict)


def test_extract_json_payload_no_json():
    assert extract_json_payload("nothing here") is None


def test_parse_findings_clean():
    findings = parse_findings(CLEAN_JSON)
    assert findings == []


def test_parse_findings_with_vuln():
    findings = parse_findings(VULN_JSON)
    assert len(findings) == 1
    f = findings[0]
    assert f["name"] == "flask"
    assert f["id"] == "PYSEC-2019-179"
    assert "CVE-2019-1010083" in f["aliases"]
    assert f["severity"] is None


def test_parse_findings_none_on_bad_input():
    assert parse_findings("garbage") is None


def test_parse_findings_mixed_output():
    findings = parse_findings(MIXED_OUTPUT)
    assert findings is not None
    assert len(findings) == 1
    assert findings[0]["name"] == "pillow"


def test_parse_findings_wrapped_output():
    findings = parse_findings(WRAPPED_VULN_JSON)
    assert findings is not None
    assert len(findings) == 1
    finding = findings[0]
    assert finding["name"] == "flask"
    assert finding["id"] == "PYSEC-2019-179"
    assert finding["severity"] is None


# ---------------------------------------------------------------------------
# Text fallback
# ---------------------------------------------------------------------------


def test_has_any_vulnerability_text_true():
    assert has_any_vulnerability_text("Found 2 known vulnerabilities in 1 package", "") is True


def test_has_any_vulnerability_text_false():
    assert has_any_vulnerability_text("No issues", "") is False


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


def test_filter_high_critical():
    findings = [
        {"id": "A", "severity": "HIGH"},
        {"id": "B", "severity": "CRITICAL"},
        {"id": "C", "severity": "MEDIUM"},
        {"id": "D", "severity": None},
    ]
    result = filter_high_critical(findings)
    assert [f["id"] for f in result] == ["A", "B"]


# ---------------------------------------------------------------------------
# run_startup_audit integration
# ---------------------------------------------------------------------------


def test_audit_disabled(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg.security.audit_enabled = False
    assert run_startup_audit(cfg) is True
    # sidecar should not be written
    assert not sidecar_path(cfg).exists()


def test_audit_feature_disabled(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg.features.startup_audit = False
    assert run_startup_audit(cfg) is True
    assert not sidecar_path(cfg).exists()


def test_audit_skips_when_already_ran_today(tmp_path):
    cfg = make_cfg(tmp_path)
    save_sidecar(sidecar_path(cfg), {"last_run_date": date.today().isoformat(), "status": "clean"})
    with patch("tuochat.security.startup_audit.run_pip_audit") as mock_run:
        result = run_startup_audit(cfg)
    mock_run.assert_not_called()
    assert result is True


def test_audit_clean(tmp_path):
    cfg = make_cfg(tmp_path)
    with patch("tuochat.security.startup_audit.run_pip_audit", return_value=(CLEAN_JSON, "", 0)):
        result = run_startup_audit(cfg)
    assert result is True
    sidecar = load_sidecar(sidecar_path(cfg))
    assert sidecar["status"] == "clean"


def test_audit_json_with_vulns_none_high_critical(tmp_path):
    cfg = make_cfg(tmp_path)
    with (
        patch("tuochat.security.startup_audit.run_pip_audit", return_value=(WRAPPED_VULN_JSON, "", 1)),
        patch("tuochat.security.startup_audit.prompt_continue_despite_vulns") as mock_prompt,
    ):
        result = run_startup_audit(cfg)
    assert result is True
    mock_prompt.assert_not_called()
    sidecar = load_sidecar(sidecar_path(cfg))
    assert sidecar["high_critical_count"] == 0


def test_audit_high_critical_user_accepts(tmp_path):
    cfg = make_cfg(tmp_path)
    with (
        patch("tuochat.security.startup_audit.run_pip_audit", return_value=(HIGH_VULN_JSON, "", 1)),
        patch("tuochat.security.startup_audit.prompt_continue_despite_vulns", return_value=True),
    ):
        result = run_startup_audit(cfg)
    assert result is True


def test_audit_high_critical_user_declines(tmp_path):
    cfg = make_cfg(tmp_path)
    with (
        patch("tuochat.security.startup_audit.run_pip_audit", return_value=(HIGH_VULN_JSON, "", 1)),
        patch("tuochat.security.startup_audit.prompt_continue_despite_vulns", return_value=False),
    ):
        result = run_startup_audit(cfg)
    assert result is False


def test_audit_execution_failure(tmp_path):
    cfg = make_cfg(tmp_path)
    with patch("tuochat.security.startup_audit.run_pip_audit", return_value=("", "command not found", None)):
        result = run_startup_audit(cfg)
    assert result is True
    sidecar = load_sidecar(sidecar_path(cfg))
    assert sidecar["status"] == "error"


def test_audit_malformed_json_with_text_fallback(tmp_path, capsys):
    cfg = make_cfg(tmp_path)
    bad_output = "Found 3 known vulnerabilities in 2 packages\nnot valid json"
    with patch("tuochat.security.startup_audit.run_pip_audit", return_value=(bad_output, "", 1)):
        result = run_startup_audit(cfg)
    assert result is True
    sidecar = load_sidecar(sidecar_path(cfg))
    assert sidecar["status"] == "parse_error"
    captured = capsys.readouterr()
    assert "pip-audit" in captured.out


def test_audit_malformed_json_no_text_clue(tmp_path):
    cfg = make_cfg(tmp_path)
    with patch("tuochat.security.startup_audit.run_pip_audit", return_value=("some unexpected output", "", 1)):
        result = run_startup_audit(cfg)
    assert result is True
    sidecar = load_sidecar(sidecar_path(cfg))
    assert sidecar["status"] == "unknown"
