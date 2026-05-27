"""Stdlib-only PyPI JSON client."""

from __future__ import annotations

import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

PYPI_HOST = "pypi.org"
PYPI_URL = "https://pypi.org/pypi/{name}/json"
USER_AGENT = "tuochat-self-pkg-mgmt/1 (+https://gitlab.com/matthewdeanmartin/tuochat)"
TIMEOUT_SECONDS = 3.0
NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+!-]{0,127}$")


class PypiError(RuntimeError):
    """PyPI fetch or parse failure."""


def validate_name(name: str) -> str:
    if not NAME_PATTERN.match(name):
        raise PypiError(f"invalid package name: {name!r}")
    return name


def validate_version(version: str) -> str:
    if not VERSION_PATTERN.match(version):
        raise PypiError(f"invalid version: {version!r}")
    return version


def validate_pypi_url(url: str) -> str:
    """Reject unexpected schemes or hosts before fetching package metadata."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != PYPI_HOST:
        raise PypiError(f"refusing to fetch non-PyPI URL: {url!r}")
    return url


def fetch_package_json(name: str, timeout: float = TIMEOUT_SECONDS) -> dict:
    """Fetch and parse pypi.org's JSON metadata for a package."""
    safe_name = validate_name(name)
    url = validate_pypi_url(PYPI_URL.format(name=safe_name))
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:  # nosec B310
            raw = response.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        raise PypiError(f"pypi fetch failed for {safe_name}: {exc}") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PypiError(f"pypi json parse failed for {safe_name}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PypiError(f"pypi response for {safe_name} is not a JSON object")
    return payload


def parse_latest_version(payload: dict) -> tuple[str, datetime | None]:
    """Extract (latest_version, upload_time) from a PyPI JSON payload."""
    info = payload.get("info") or {}
    latest = info.get("version")
    if not isinstance(latest, str):
        raise PypiError("pypi payload missing info.version")
    validate_version(latest)

    releases = payload.get("releases") or {}
    files = releases.get(latest) or []
    published: datetime | None = None
    if isinstance(files, list) and files:
        timestamps: list[datetime] = []
        for file_info in files:
            if not isinstance(file_info, dict):
                continue
            iso = file_info.get("upload_time_iso_8601") or file_info.get("upload_time")
            if not isinstance(iso, str):
                continue
            try:
                dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            except ValueError:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            timestamps.append(dt)
        if timestamps:
            published = min(timestamps)
    return latest, published


def get_latest(name: str, timeout: float = TIMEOUT_SECONDS) -> tuple[str, datetime | None]:
    """Convenience: fetch and parse the latest version of a package."""
    return parse_latest_version(fetch_package_json(name, timeout=timeout))
