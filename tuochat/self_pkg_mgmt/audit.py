"""Opportunistic vulnerability audit via pip-audit, safety, or uv audit."""

from __future__ import annotations

import json
import shutil
import subprocess  # noqa: S404
import sys
from typing import Callable, Optional

from tuochat.self_pkg_mgmt.report import Vulnerability

AUDIT_TIMEOUT = 60


def which(tool: str) -> str | None:
    return shutil.which(tool)


def run_cmd(argv: list[str]) -> tuple[str, str, int | None]:
    try:
        proc = subprocess.run(  # noqa: S603
            argv,
            capture_output=True,
            text=True,
            timeout=AUDIT_TIMEOUT,
            check=False,
        )
        return proc.stdout, proc.stderr, proc.returncode
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return "", "", None


def extract_json(text: str) -> object | None:
    starts = [i for i in (text.find("["), text.find("{")) if i != -1]
    if not starts:
        return None
    try:
        return json.loads(text[min(starts) :])
    except json.JSONDecodeError:
        return None


def parse_pip_audit(stdout: str) -> list[Vulnerability]:
    payload = extract_json(stdout)
    if payload is None:
        return []
    packages: list[dict]
    if isinstance(payload, list):
        packages = [p for p in payload if isinstance(p, dict)]
    elif isinstance(payload, dict):
        packages = [p for p in payload.get("dependencies", []) if isinstance(p, dict)]
    else:
        return []
    findings: list[Vulnerability] = []
    for pkg in packages:
        name = str(pkg.get("name", ""))
        version = str(pkg.get("version", ""))
        for vuln in pkg.get("vulns", []) or []:
            if not isinstance(vuln, dict):
                continue
            findings.append(
                Vulnerability(
                    name=name,
                    installed=version,
                    advisory_id=str(vuln.get("id", "")),
                    severity=(str(vuln["severity"]).lower() if vuln.get("severity") else None),
                    fix_versions=tuple(str(v) for v in vuln.get("fix_versions") or ()),
                    source="pip-audit",
                )
            )
    return findings


def parse_safety(stdout: str) -> list[Vulnerability]:
    payload = extract_json(stdout)
    if not isinstance(payload, dict):
        return []
    vulns = payload.get("vulnerabilities") or []
    findings: list[Vulnerability] = []
    if isinstance(vulns, list):
        for vuln in vulns:
            if not isinstance(vuln, dict):
                continue
            findings.append(
                Vulnerability(
                    name=str(vuln.get("package_name", "")),
                    installed=str(vuln.get("analyzed_version", "")),
                    advisory_id=str(vuln.get("vulnerability_id", "")),
                    severity=(str(vuln["severity"]).lower() if vuln.get("severity") else None),
                    fix_versions=tuple(str(v) for v in vuln.get("fixed_versions") or ()),
                    source="safety",
                )
            )
    return findings


AuditRunner = Callable[[], tuple[list[Vulnerability], Optional[str]]]


def runner_pip_audit() -> tuple[list[Vulnerability], str | None]:
    if not which("pip-audit"):
        return [], None
    stdout, stderr, rc = run_cmd(["pip-audit", "--format", "json"])
    if rc is None:
        stdout, stderr, rc = run_cmd([sys.executable, "-m", "pip_audit", "--format", "json"])
    if rc is None:
        return [], None
    return parse_pip_audit(stdout), "pip-audit"


def runner_safety() -> tuple[list[Vulnerability], str | None]:
    if not which("safety"):
        return [], None
    stdout, stderr, rc = run_cmd(["safety", "scan", "--output", "json"])
    if rc is None:
        return [], None
    return parse_safety(stdout), "safety"


def runner_uv_audit() -> tuple[list[Vulnerability], str | None]:
    if not which("uv"):
        return [], None
    stdout, stderr, rc = run_cmd(["uv", "pip", "audit", "--format", "json"])
    if rc is None:
        return [], None
    return parse_pip_audit(stdout), "uv-audit"


def run_available_audit() -> tuple[list[Vulnerability], str | None]:
    """Run the first available audit tool and return (vulnerabilities, tool_name)."""
    for runner in (runner_uv_audit, runner_pip_audit, runner_safety):
        vulns, tool = runner()
        if tool is not None:
            return vulns, tool
    return [], None
