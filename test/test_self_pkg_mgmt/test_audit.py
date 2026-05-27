"""Unit tests for tuochat.self_pkg_mgmt.audit."""

from __future__ import annotations

import json

from tuochat.self_pkg_mgmt import audit

# ---------------------------------------------------------------------------
# extract_json
# ---------------------------------------------------------------------------


def test_extract_json_list():
    assert audit.extract_json('[{"a": 1}]') == [{"a": 1}]


def test_extract_json_dict():
    assert audit.extract_json('{"k": "v"}') == {"k": "v"}


def test_extract_json_with_prefix():
    assert audit.extract_json('some prefix {"k": 1}') == {"k": 1}


def test_extract_json_empty():
    assert audit.extract_json("") is None


def test_extract_json_no_json():
    assert audit.extract_json("just text") is None


def test_extract_json_invalid_json():
    assert audit.extract_json("{broken") is None


# ---------------------------------------------------------------------------
# parse_pip_audit
# ---------------------------------------------------------------------------

PIP_AUDIT_LIST_PAYLOAD = json.dumps(
    [
        {
            "name": "requests",
            "version": "2.0.0",
            "vulns": [
                {"id": "GHSA-1", "severity": "HIGH", "fix_versions": ["2.1.0"]},
                {"id": "GHSA-2", "severity": None, "fix_versions": []},
            ],
        },
        {"name": "clean", "version": "1.0", "vulns": []},
    ]
)

PIP_AUDIT_DICT_PAYLOAD = json.dumps(
    {
        "dependencies": [
            {
                "name": "urllib3",
                "version": "1.0",
                "vulns": [{"id": "CVE-1", "severity": "medium", "fix_versions": ["1.1"]}],
            }
        ]
    }
)


def test_parse_pip_audit_list_format():
    vulns = audit.parse_pip_audit(PIP_AUDIT_LIST_PAYLOAD)
    assert len(vulns) == 2
    assert vulns[0].name == "requests"
    assert vulns[0].advisory_id == "GHSA-1"
    assert vulns[0].severity == "high"
    assert vulns[0].fix_versions == ("2.1.0",)
    assert vulns[0].source == "pip-audit"
    assert vulns[1].advisory_id == "GHSA-2"
    assert vulns[1].severity is None
    assert vulns[1].fix_versions == ()


def test_parse_pip_audit_dict_format():
    vulns = audit.parse_pip_audit(PIP_AUDIT_DICT_PAYLOAD)
    assert len(vulns) == 1
    assert vulns[0].name == "urllib3"
    assert vulns[0].advisory_id == "CVE-1"
    assert vulns[0].severity == "medium"


def test_parse_pip_audit_empty_output():
    assert audit.parse_pip_audit("") == []


def test_parse_pip_audit_non_list_non_dict():
    assert audit.parse_pip_audit('"just a string"') == []


def test_parse_pip_audit_skips_non_dict_vulns():
    payload = json.dumps([{"name": "pkg", "version": "1.0", "vulns": ["not-a-dict"]}])
    assert audit.parse_pip_audit(payload) == []


# ---------------------------------------------------------------------------
# parse_safety
# ---------------------------------------------------------------------------

SAFETY_PAYLOAD = json.dumps(
    {
        "vulnerabilities": [
            {
                "package_name": "django",
                "analyzed_version": "3.0",
                "vulnerability_id": "SAF-001",
                "severity": "Critical",
                "fixed_versions": ["3.2"],
            },
            {
                "package_name": "flask",
                "analyzed_version": "1.0",
                "vulnerability_id": "SAF-002",
                "severity": None,
                "fixed_versions": [],
            },
        ]
    }
)


def test_parse_safety_basic():
    vulns = audit.parse_safety(SAFETY_PAYLOAD)
    assert len(vulns) == 2
    assert vulns[0].name == "django"
    assert vulns[0].severity == "critical"
    assert vulns[0].fix_versions == ("3.2",)
    assert vulns[0].source == "safety"
    assert vulns[1].severity is None


def test_parse_safety_not_dict():
    assert audit.parse_safety("[]") == []
    assert audit.parse_safety("") == []


def test_parse_safety_missing_vulnerabilities_key():
    assert audit.parse_safety("{}") == []


def test_parse_safety_skips_non_dict_entries():
    payload = json.dumps({"vulnerabilities": ["not-a-dict"]})
    assert audit.parse_safety(payload) == []


# ---------------------------------------------------------------------------
# runner_pip_audit / runner_safety / runner_uv_audit
# ---------------------------------------------------------------------------


def test_runner_pip_audit_no_tool(monkeypatch):
    monkeypatch.setattr(audit, "which", lambda name: None)
    vulns, tool = audit.runner_pip_audit()
    assert tool is None
    assert vulns == []


def test_runner_pip_audit_tool_present_returns_results(monkeypatch):
    monkeypatch.setattr(audit, "which", lambda name: "/usr/bin/pip-audit" if name == "pip-audit" else None)
    payload = json.dumps(
        [{"name": "pkg", "version": "1.0", "vulns": [{"id": "X", "severity": None, "fix_versions": []}]}]
    )
    monkeypatch.setattr(audit, "run_cmd", lambda argv: (payload, "", 0))
    vulns, tool = audit.runner_pip_audit()
    assert tool == "pip-audit"
    assert len(vulns) == 1


def test_runner_pip_audit_falls_back_to_python_m(monkeypatch):
    """When the CLI binary fails (rc=None), fall back to `python -m pip_audit`."""
    monkeypatch.setattr(audit, "which", lambda name: "/usr/bin/pip-audit" if name == "pip-audit" else None)
    payload = json.dumps([])
    call_count = [0]

    def fake_run_cmd(argv):
        call_count[0] += 1
        if call_count[0] == 1:
            return "", "", None  # first call: binary fails
        return payload, "", 0  # second call: python -m succeeds

    monkeypatch.setattr(audit, "run_cmd", fake_run_cmd)
    vulns, tool = audit.runner_pip_audit()
    assert tool == "pip-audit"
    assert call_count[0] == 2


def test_runner_pip_audit_both_fail(monkeypatch):
    monkeypatch.setattr(audit, "which", lambda name: "/usr/bin/pip-audit" if name == "pip-audit" else None)
    monkeypatch.setattr(audit, "run_cmd", lambda argv: ("", "", None))
    vulns, tool = audit.runner_pip_audit()
    assert tool is None


def test_runner_safety_no_tool(monkeypatch):
    monkeypatch.setattr(audit, "which", lambda name: None)
    vulns, tool = audit.runner_safety()
    assert tool is None


def test_runner_safety_present(monkeypatch):
    monkeypatch.setattr(audit, "which", lambda name: "/usr/bin/safety" if name == "safety" else None)
    payload = json.dumps({"vulnerabilities": []})
    monkeypatch.setattr(audit, "run_cmd", lambda argv: (payload, "", 0))
    vulns, tool = audit.runner_safety()
    assert tool == "safety"
    assert vulns == []


def test_runner_safety_cmd_fails(monkeypatch):
    monkeypatch.setattr(audit, "which", lambda name: "/usr/bin/safety" if name == "safety" else None)
    monkeypatch.setattr(audit, "run_cmd", lambda argv: ("", "", None))
    vulns, tool = audit.runner_safety()
    assert tool is None


def test_runner_uv_audit_no_tool(monkeypatch):
    monkeypatch.setattr(audit, "which", lambda name: None)
    vulns, tool = audit.runner_uv_audit()
    assert tool is None


def test_runner_uv_audit_present(monkeypatch):
    monkeypatch.setattr(audit, "which", lambda name: "/usr/bin/uv" if name == "uv" else None)
    payload = json.dumps([])
    monkeypatch.setattr(audit, "run_cmd", lambda argv: (payload, "", 0))
    vulns, tool = audit.runner_uv_audit()
    assert tool == "uv-audit"


# ---------------------------------------------------------------------------
# run_available_audit — picks first successful runner
# ---------------------------------------------------------------------------


def test_run_available_audit_uv_first(monkeypatch):
    monkeypatch.setattr(audit, "runner_uv_audit", lambda: ([], "uv-audit"))
    monkeypatch.setattr(audit, "runner_pip_audit", lambda: ([], "pip-audit"))
    vulns, tool = audit.run_available_audit()
    assert tool == "uv-audit"


def test_run_available_audit_falls_through_to_pip_audit(monkeypatch):
    monkeypatch.setattr(audit, "runner_uv_audit", lambda: ([], None))
    monkeypatch.setattr(audit, "runner_pip_audit", lambda: ([], "pip-audit"))
    monkeypatch.setattr(audit, "runner_safety", lambda: ([], "safety"))
    vulns, tool = audit.run_available_audit()
    assert tool == "pip-audit"


def test_run_available_audit_falls_through_to_safety(monkeypatch):
    monkeypatch.setattr(audit, "runner_uv_audit", lambda: ([], None))
    monkeypatch.setattr(audit, "runner_pip_audit", lambda: ([], None))
    monkeypatch.setattr(audit, "runner_safety", lambda: ([], "safety"))
    vulns, tool = audit.run_available_audit()
    assert tool == "safety"


def test_run_available_audit_none_available(monkeypatch):
    monkeypatch.setattr(audit, "runner_uv_audit", lambda: ([], None))
    monkeypatch.setattr(audit, "runner_pip_audit", lambda: ([], None))
    monkeypatch.setattr(audit, "runner_safety", lambda: ([], None))
    vulns, tool = audit.run_available_audit()
    assert tool is None
    assert vulns == []
