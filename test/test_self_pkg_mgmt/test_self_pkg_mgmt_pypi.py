"""Unit tests for tuochat.self_pkg_mgmt.pypi JSON parsing."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from tuochat.self_pkg_mgmt.pypi import (
    PypiError,
    fetch_package_json,
    get_latest,
    parse_latest_version,
    validate_name,
    validate_version,
)

# ---------------------------------------------------------------------------
# Minimal fixture — mirrors the real pypi.org/pypi/<name>/json shape
# ---------------------------------------------------------------------------

TUOCHAT_FIXTURE: dict = {
    "info": {
        "name": "tuochat",
        "version": "0.4.0",
        "summary": "GitLab Duo chat client",
        "requires_python": ">=3.9",
    },
    "releases": {
        "0.3.0": [
            {
                "filename": "tuochat-0.3.0-py3-none-any.whl",
                "upload_time_iso_8601": "2026-01-10T12:00:00Z",
                "size": 10000,
            }
        ],
        "0.4.0": [
            {
                "filename": "tuochat-0.4.0-py3-none-any.whl",
                "upload_time_iso_8601": "2026-04-01T08:00:00Z",
                "size": 11000,
            },
            {
                "filename": "tuochat-0.4.0.tar.gz",
                "upload_time_iso_8601": "2026-04-01T08:05:00Z",
                "size": 12000,
            },
        ],
    },
    "urls": [],
}

MULTI_FILE_FIXTURE: dict = {
    "info": {"name": "multifile", "version": "2.0.0"},
    "releases": {
        "2.0.0": [
            {"upload_time_iso_8601": "2026-03-15T10:00:00Z", "size": 1},
            {"upload_time_iso_8601": "2026-03-15T09:00:00Z", "size": 2},  # earlier → picked
            {"upload_time_iso_8601": "2026-03-15T11:00:00Z", "size": 3},
        ]
    },
    "urls": [],
}

NO_RELEASE_FILES_FIXTURE: dict = {
    "info": {"name": "nofiles", "version": "1.0.0"},
    "releases": {"1.0.0": []},
    "urls": [],
}

MISSING_VERSION_FIXTURE: dict = {
    "info": {"name": "broken"},
    "releases": {},
    "urls": [],
}

FALLBACK_TIME_FIXTURE: dict = {
    "info": {"name": "fallback", "version": "3.0.0"},
    "releases": {
        "3.0.0": [
            {
                "upload_time": "2026-02-20T14:00:00",  # no _iso_8601 key
                "size": 500,
            }
        ]
    },
    "urls": [],
}


# ---------------------------------------------------------------------------
# validate_name / validate_version
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["tuochat", "my-pkg", "pkg.name", "pkg_name", "A1"])
def test_validate_name_valid(name):
    assert validate_name(name) == name


@pytest.mark.parametrize("name", ["", "-bad", "a" * 201, "has space", "has/slash"])
def test_validate_name_invalid(name):
    with pytest.raises(PypiError, match="invalid package name"):
        validate_name(name)


@pytest.mark.parametrize("version", ["1.0.0", "0.4.0", "1.0.0a1", "1!2.3", "1.0+local"])
def test_validate_version_valid(version):
    assert validate_version(version) == version


@pytest.mark.parametrize("version", ["", " 1.0", "a" * 129])
def test_validate_version_invalid(version):
    with pytest.raises(PypiError, match="invalid version"):
        validate_version(version)


# ---------------------------------------------------------------------------
# parse_latest_version
# ---------------------------------------------------------------------------


def test_parse_latest_version_basic():
    version, published = parse_latest_version(TUOCHAT_FIXTURE)
    assert version == "0.4.0"
    assert published is not None
    assert published == datetime(2026, 4, 1, 8, 0, 0, tzinfo=timezone.utc)


def test_parse_latest_version_picks_earliest_file():
    version, published = parse_latest_version(MULTI_FILE_FIXTURE)
    assert version == "2.0.0"
    assert published == datetime(2026, 3, 15, 9, 0, 0, tzinfo=timezone.utc)


def test_parse_latest_version_no_release_files():
    version, published = parse_latest_version(NO_RELEASE_FILES_FIXTURE)
    assert version == "1.0.0"
    assert published is None


def test_parse_latest_version_missing_version_key():
    with pytest.raises(PypiError, match="missing info.version"):
        parse_latest_version(MISSING_VERSION_FIXTURE)


def test_parse_latest_version_not_a_dict():
    # parse_latest_version assumes a dict; non-dict raises AttributeError
    with pytest.raises((PypiError, AttributeError)):
        parse_latest_version([])  # type: ignore[arg-type]


def test_parse_latest_version_fallback_upload_time():
    """upload_time (no _iso_8601) is also accepted."""
    version, published = parse_latest_version(FALLBACK_TIME_FIXTURE)
    assert version == "3.0.0"
    assert published is not None
    assert published.year == 2026


def test_parse_latest_version_published_is_utc_aware():
    version, published = parse_latest_version(TUOCHAT_FIXTURE)
    assert published is not None
    assert published.tzinfo is not None


def test_parse_latest_version_empty_payload():
    with pytest.raises(PypiError):
        parse_latest_version({})


def test_parse_latest_version_bad_upload_time_skipped():
    payload = {
        "info": {"name": "x", "version": "1.0"},
        "releases": {
            "1.0": [
                {"upload_time_iso_8601": "not-a-date", "size": 1},
                {"upload_time_iso_8601": "2026-05-01T00:00:00Z", "size": 2},
            ]
        },
        "urls": [],
    }
    version, published = parse_latest_version(payload)
    assert version == "1.0"
    assert published == datetime(2026, 5, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# fetch_package_json (network call mocked)
# ---------------------------------------------------------------------------


def make_response(payload: dict) -> MagicMock:
    body = json.dumps(payload).encode()
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def test_fetch_package_json_success():
    with patch("urllib.request.urlopen", return_value=make_response(TUOCHAT_FIXTURE)):
        result = fetch_package_json("tuochat")
    assert result["info"]["version"] == "0.4.0"


def test_fetch_package_json_bad_name():
    with pytest.raises(PypiError, match="invalid package name"):
        fetch_package_json("has space")


def test_fetch_package_json_network_error():
    import urllib.error

    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
        with pytest.raises(PypiError, match="pypi fetch failed"):
            fetch_package_json("tuochat")


def test_fetch_package_json_bad_json():
    resp = MagicMock()
    resp.read.return_value = b"not json {"
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=resp):
        with pytest.raises(PypiError, match="pypi json parse failed"):
            fetch_package_json("tuochat")


def test_fetch_package_json_non_dict_response():
    resp = MagicMock()
    resp.read.return_value = b"[1, 2, 3]"
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=resp):
        with pytest.raises(PypiError, match="not a JSON object"):
            fetch_package_json("tuochat")


# ---------------------------------------------------------------------------
# get_latest convenience wrapper
# ---------------------------------------------------------------------------


def test_get_latest_returns_version_and_date():
    with patch("urllib.request.urlopen", return_value=make_response(TUOCHAT_FIXTURE)):
        version, published = get_latest("tuochat")
    assert version == "0.4.0"
    assert published is not None
