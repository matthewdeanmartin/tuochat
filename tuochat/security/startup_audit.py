"""Startup dependency vulnerability audit via pip-audit.

Runs at most once per calendar day, stores last-run metadata in a JSON sidecar
file next to the SQLite database, parses machine-readable pip-audit output, and
prompts the user only when pip-audit itself reports High or Critical findings.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tuochat.config import TuochatConfig

logger = logging.getLogger(__name__)

AUDIT_TIMEOUT = 60
SIDECAR_FILENAME = "audit_state.json"

HIGH_CRITICAL_SEVERITIES = {"high", "critical"}


#
# Scheduling helpers
#


def sidecar_path(cfg: TuochatConfig) -> Path:
    """Return the path to the audit sidecar file."""
    return cfg.data_dir / SIDECAR_FILENAME


def load_sidecar(path: Path) -> dict:
    """Load the audit sidecar file, returning an empty dict on any error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_sidecar(path: Path, data: dict) -> None:
    """Write the audit sidecar file, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def already_ran_today(path: Path) -> bool:
    """Return True if the audit sidecar records a run on today's local date."""
    sidecar = load_sidecar(path)
    last_run = sidecar.get("last_run_date")
    if not last_run:
        return False
    try:
        return date.fromisoformat(last_run) == date.today()
    except ValueError:
        return False


#
# Subprocess execution
#


def run_pip_audit(timeout: int = AUDIT_TIMEOUT) -> tuple[str, str, int | None]:
    """Invoke pip-audit and return (stdout, stderr, returncode).

    Returns returncode=None when the executable is not found or fails to start.
    """
    try:
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "pip_audit", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return result.stdout, result.stderr, result.returncode
    except FileNotFoundError:
        return "", "pip-audit executable not found", None
    except subprocess.TimeoutExpired:
        return "", f"pip-audit timed out after {timeout}s", None
    except Exception as exc:
        return "", str(exc), None


#
# Output parsing
#


def extract_json_payload(text: str) -> list | dict | None:
    """Locate and parse the JSON payload from pip-audit output.

    pip-audit may emit a human summary line before the JSON payload. Older
    versions emit a top-level JSON array, while newer versions emit a JSON
    object with a ``dependencies`` key.
    """
    starts = [index for index in (text.find("["), text.find("{")) if index != -1]
    if not starts:
        return None
    try:
        return json.loads(text[min(starts) :])
    except json.JSONDecodeError:
        return None


def parse_findings(stdout: str) -> list[dict] | None:
    """Parse pip-audit JSON output into a flat list of finding dicts.

    Each finding dict has keys: name, version, id, aliases, fix_versions,
    description, severity (may be missing or None).

    Returns None when the output cannot be parsed.
    """
    payload = extract_json_payload(stdout)
    if payload is None:
        return None

    if isinstance(payload, list):
        packages = payload
    elif isinstance(payload, dict):
        packages = payload.get("dependencies", [])
    else:
        return None

    findings: list[dict] = []
    for pkg in packages:
        name = pkg.get("name", "")
        version = pkg.get("version", "")
        for vuln in pkg.get("vulns", []):
            findings.append(
                {
                    "name": name,
                    "version": version,
                    "id": vuln.get("id", ""),
                    "aliases": vuln.get("aliases", []),
                    "fix_versions": vuln.get("fix_versions", []),
                    "description": vuln.get("description", ""),
                    "severity": vuln.get("severity"),
                }
            )
    return findings


def has_any_vulnerability_text(stdout: str, stderr: str) -> bool:
    """Fallback: check whether pip-audit output mentions known vulnerabilities."""
    combined = stdout + stderr
    return "Found " in combined and "known vulnerabilit" in combined


#
# Filtering
#


def filter_high_critical(findings: list[dict]) -> list[dict]:
    """Return only findings with High or Critical severity."""
    return [f for f in findings if (f.get("severity") or "").lower() in HIGH_CRITICAL_SEVERITIES]


#
# User confirmation
#


def format_finding_line(finding: dict) -> str:
    """Format one finding for display."""
    pkg = f"{finding['name']} {finding['version']}"
    advisory = finding["id"]
    severity = finding.get("severity") or "unknown severity"
    fix = ", ".join(finding.get("fix_versions") or []) or "no fix available"
    return f"  {pkg}  {advisory}  [{severity}]  fix: {fix}"


def prompt_continue_despite_vulns(findings: list[dict]) -> bool:
    """Print findings and ask whether startup should continue.

    Returns True to continue, False to abort.
    """
    from tuochat.cli.prompts import prompt_bool

    print("\nSecurity audit found High/Critical vulnerabilities in your Python environment:")
    for finding in findings:
        print(format_finding_line(finding))
    print()
    return prompt_bool("Continue startup anyway?", default=False)


#
# Top-level entry point
#


def run_startup_audit(cfg: TuochatConfig) -> bool:
    """Run the startup audit if enabled and not already done today.

    Returns True to continue startup, False to abort.
    On any error (missing tool, timeout, parse failure), logs and returns True
    (fail open).
    """
    if not cfg.features.startup_audit:
        logger.debug("startup audit feature disabled")
        return True

    if not cfg.security.audit_enabled:
        logger.debug("startup audit disabled")
        return True

    path = sidecar_path(cfg)
    if already_ran_today(path):
        logger.debug("startup audit already ran today, skipping")
        return True

    logger.debug("running pip-audit startup audit")
    stdout, stderr, returncode = run_pip_audit()

    if returncode is None:
        logger.warning("startup audit could not run: %s", stderr or "unknown error")
        save_sidecar(path, {"last_run_date": date.today().isoformat(), "status": "error", "error": stderr})
        return True

    if returncode == 0:
        logger.debug("startup audit found no known vulnerabilities")
        save_sidecar(path, {"last_run_date": date.today().isoformat(), "status": "clean"})
        return True

    # returncode == 1 means vulnerabilities found
    findings = parse_findings(stdout)

    if findings is None:
        # JSON parse failed — fall back to text detection
        if has_any_vulnerability_text(stdout, stderr):
            logger.warning("startup audit found vulnerabilities (JSON parse failed, text fallback)")
            print("\nWarning: pip-audit reported vulnerabilities but output could not be parsed.")
            print("Run `pip-audit` manually for details.")
            save_sidecar(path, {"last_run_date": date.today().isoformat(), "status": "parse_error"})
        else:
            logger.warning(
                "startup audit finished with unexpected exit code %d (no vulnerability text found)", returncode
            )
            save_sidecar(path, {"last_run_date": date.today().isoformat(), "status": "unknown"})
        return True

    if not findings:
        logger.debug("startup audit: no findings after parsing")
        save_sidecar(path, {"last_run_date": date.today().isoformat(), "status": "clean"})
        return True

    logger.debug("startup audit: %d raw findings, using pip-audit severities only", len(findings))
    critical = filter_high_critical(findings)

    save_sidecar(
        path,
        {
            "last_run_date": date.today().isoformat(),
            "status": "vulnerabilities",
            "finding_count": len(findings),
            "high_critical_count": len(critical),
        },
    )

    if not critical:
        logger.info("startup audit: %d vulnerabilities found, none High/Critical", len(findings))
        return True

    return prompt_continue_despite_vulns(critical)
