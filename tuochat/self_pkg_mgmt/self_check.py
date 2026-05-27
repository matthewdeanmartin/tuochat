"""pip-check-style integrity verification using importlib.metadata only."""

from __future__ import annotations

import platform
import re
import sys
from importlib import metadata

SPECIFIER_PATTERN = re.compile(r"(?P<op>==|!=|<=|>=|<|>|~=|===)\s*(?P<version>[A-Za-z0-9][A-Za-z0-9._+!-]*)")
NAME_PATTERN = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")

# Marker variable values for the current interpreter, per PEP 508 / PEP 345.
MARKER_ENV: dict[str, str] = {
    "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
    "python_full_version": platform.python_version(),
    "os_name": __import__("os").name,
    "sys_platform": sys.platform,
    "platform_system": platform.system(),
    "platform_machine": platform.machine(),
    "implementation_name": sys.implementation.name,
}

# Regex to match a single marker comparison: <var> <op> <quoted-value>
MARKER_CMP_PATTERN = re.compile(
    r'(?P<var>[a-z_]+)\s*(?P<op>==|!=|<|<=|>|>=)\s*["\'](?P<val>[^"\']*)["\']'
    r'|["\'](?P<lval>[^"\']*)["\']?\s*(?P<rop>==|!=|<|<=|>|>=)\s*(?P<rvar>[a-z_]+)'
)


def split_requirement(requirement: str) -> tuple[str, str, str | None] | None:
    """Return (name, specifier_string, marker_string) or None."""
    if ";" in requirement:
        head, marker = requirement.split(";", 1)
        marker = marker.strip()
    else:
        head, marker = requirement, None
    head = head.strip()
    if not head:
        return None
    match = NAME_PATTERN.match(head)
    if not match:
        return None
    name = match.group(1)
    rest = head[match.end() :]
    rest = rest.split("[", 1)[0] if "[" in rest else rest
    rest = rest.replace("(", "").replace(")", "").strip()
    return name, rest, marker


def version_tuple(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in re.split(r"[.+-]", version):
        match = re.match(r"(\d+)", chunk)
        if not match:
            break
        parts.append(int(match.group(1)))
    return tuple(parts) or (0,)


def satisfies(op: str, installed: str, wanted: str) -> bool:
    if op in {"==", "==="}:
        return installed == wanted
    if op == "!=":
        return installed != wanted
    lhs = version_tuple(installed)
    rhs = version_tuple(wanted)
    if op == ">=":
        return lhs >= rhs
    if op == ">":
        return lhs > rhs
    if op == "<=":
        return lhs <= rhs
    if op == "<":
        return lhs < rhs
    if op == "~=":
        if len(rhs) < 2:
            return lhs >= rhs
        upper = rhs[:-1]
        upper_plus = upper[:-1] + (upper[-1] + 1,)
        return lhs >= rhs and lhs[: len(upper_plus)] < upper_plus
    return True


def check_specifier(installed: str, specifier: str) -> bool:
    if not specifier:
        return True
    for part in specifier.split(","):
        match = SPECIFIER_PATTERN.search(part)
        if not match:
            continue
        if not satisfies(match.group("op"), installed, match.group("version")):
            return False
    return True


def normalize(name: str) -> str:
    """PEP 503 canonical name: lowercase, runs of [-_.] -> '-'."""
    return re.sub(r"[-_.]+", "-", name).lower()


def marker_applies(marker: str) -> bool:
    """Return True if the marker expression applies to the current environment.

    Evaluates only simple single-comparison markers whose variable is in
    MARKER_ENV.  Compound expressions joined by ``and``/``or``, and any
    ``extra`` marker, are treated as applicable (True) so we never silently
    miss a required dependency.
    """
    # Extra markers are never about installed packages; skip check entirely.
    if "extra" in marker:
        return False

    # If the expression contains boolean operators, fall back to True so we
    # don't accidentally skip a requirement on the current platform.
    if " and " in marker.lower() or " or " in marker.lower():
        return True

    match = MARKER_CMP_PATTERN.search(marker)
    if not match:
        return True  # unknown format → assume applicable

    # Normalise regardless of which capture group fired.
    if match.group("var"):
        var, op, val = match.group("var"), match.group("op"), match.group("val")
    else:
        var, op, val = match.group("rvar"), match.group("rop"), match.group("lval")
        # operands are reversed → flip operator
        flip = {"<": ">", ">": "<", "<=": ">=", ">=": "<="}
        op = flip.get(op, op)

    env_val = MARKER_ENV.get(var)
    if env_val is None:
        return True  # unknown variable → assume applicable

    # Compare using version tuples for version-like variables, else string equality.
    version_vars = {"python_version", "python_full_version"}
    if var in version_vars:
        lhs = version_tuple(env_val)
        rhs = version_tuple(val)
        return (
            satisfies(op, env_val, val)
            if op in {"==", "!="}
            else (
                lhs >= rhs
                if op == ">="
                else lhs > rhs if op == ">" else lhs <= rhs if op == "<=" else lhs < rhs if op == "<" else True
            )
        )
    # String comparison for os_name, sys_platform, platform_system, etc.
    if op == "==":
        return env_val == val
    if op == "!=":
        return env_val != val
    return True  # relational string comparisons are unusual; assume applicable


def run() -> list[str]:
    """Return a list of human-readable integrity problems. Empty = clean.

    Requirements with environment markers are evaluated against the current
    interpreter.  Only requirements that apply to this environment are checked.
    Markers that cannot be evaluated (compound expressions, unknown variables)
    are treated as applicable so we never silently miss a required dependency.
    ``extra`` markers are skipped because they describe optional install groups,
    not runtime requirements.
    """
    problems: list[str] = []
    all_dists = list(metadata.distributions())
    installed_versions: dict[str, str] = {}
    for dist in all_dists:
        name = dist.metadata["Name"] if dist.metadata else None
        if name:
            installed_versions[normalize(name)] = dist.version

    for dist in all_dists:
        origin = dist.metadata["Name"] if dist.metadata else None
        if not origin:
            continue
        for requirement in dist.requires or []:
            parsed = split_requirement(requirement)
            if not parsed:
                continue
            req_name, specifier, marker = parsed
            if marker and not marker_applies(marker):
                continue
            installed = installed_versions.get(normalize(req_name))
            if not installed:
                problems.append(f"{origin} requires {req_name} which is not installed")
                continue
            if not check_specifier(installed, specifier):
                problems.append(f"{origin} requires {req_name}{specifier} but {installed} is installed")
    return problems
