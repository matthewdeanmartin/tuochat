"""Unit tests for tuochat.self_pkg_mgmt.installed."""

from __future__ import annotations

from tuochat.self_pkg_mgmt import installed

# ---------------------------------------------------------------------------
# host_version
# ---------------------------------------------------------------------------


def test_host_version_known_package():
    # pytest is installed in any test environment
    version = installed.host_version("pytest")
    assert version is not None
    assert isinstance(version, str)
    assert len(version) > 0


def test_host_version_missing_package():
    assert installed.host_version("___no_such_pkg___") is None


# ---------------------------------------------------------------------------
# parse_requirement_name
# ---------------------------------------------------------------------------


def test_parse_requirement_name_plain():
    assert installed.parse_requirement_name("requests") == "requests"


def test_parse_requirement_name_with_specifier():
    assert installed.parse_requirement_name("requests>=2.0") == "requests"


def test_parse_requirement_name_with_extras():
    assert installed.parse_requirement_name("requests[security]>=2.0") == "requests"


def test_parse_requirement_name_with_marker():
    assert installed.parse_requirement_name('requests; python_version >= "3.8"') == "requests"


def test_parse_requirement_name_empty():
    assert installed.parse_requirement_name("") is None


def test_parse_requirement_name_only_marker():
    assert installed.parse_requirement_name("; python_version >= '3.8'") is None


# ---------------------------------------------------------------------------
# direct_dependencies
# ---------------------------------------------------------------------------


def test_direct_dependencies_missing_dist():
    result = installed.direct_dependencies("___no_such_pkg___")
    assert result == []


def test_direct_dependencies_returns_list_of_tuples():
    # pytest is always installed and has dependencies
    result = installed.direct_dependencies("pytest")
    assert isinstance(result, list)
    for name, version in result:
        assert isinstance(name, str)
        assert isinstance(version, str)


def test_direct_dependencies_skips_extras():
    """Deps behind 'extra ==' markers should be excluded."""
    from importlib import metadata
    from unittest.mock import MagicMock, patch

    fake_dist = MagicMock()
    fake_dist.requires = [
        "pluggy>=0.12",
        'colorama; extra == "testing"',
    ]

    with patch.object(metadata, "distribution", return_value=fake_dist):
        with patch.object(metadata, "version", return_value="1.0"):
            result = installed.direct_dependencies("mypkg")

    names = [n for n, _ in result]
    assert "pluggy" in names
    assert "colorama" not in names


def test_direct_dependencies_skips_missing_deps():
    from importlib import metadata
    from unittest.mock import MagicMock, patch

    fake_dist = MagicMock()
    fake_dist.requires = ["installed-dep>=1.0", "missing-dep>=2.0"]

    def fake_version(name):
        if name == "installed-dep":
            return "1.5"
        raise metadata.PackageNotFoundError(name)

    with patch.object(metadata, "distribution", return_value=fake_dist):
        with patch.object(metadata, "version", side_effect=fake_version):
            result = installed.direct_dependencies("mypkg")

    assert result == [("installed-dep", "1.5")]


def test_direct_dependencies_deduplicates():
    from importlib import metadata
    from unittest.mock import MagicMock, patch

    fake_dist = MagicMock()
    fake_dist.requires = ["requests>=1.0", "Requests>=2.0"]  # same pkg, different case

    with patch.object(metadata, "distribution", return_value=fake_dist):
        with patch.object(metadata, "version", return_value="2.5"):
            result = installed.direct_dependencies("mypkg")

    names = [n for n, _ in result]
    assert names.count("requests") + names.count("Requests") == 1


def test_direct_dependencies_none_requires():
    from importlib import metadata
    from unittest.mock import MagicMock, patch

    fake_dist = MagicMock()
    fake_dist.requires = None

    with patch.object(metadata, "distribution", return_value=fake_dist):
        result = installed.direct_dependencies("mypkg")

    assert result == []


# ---------------------------------------------------------------------------
# all_installed
# ---------------------------------------------------------------------------


def test_all_installed_returns_non_empty_list():
    result = installed.all_installed()
    assert isinstance(result, list)
    assert len(result) > 0


def test_all_installed_contains_pytest():
    result = installed.all_installed()
    names = [n.lower() for n, _ in result]
    assert "pytest" in names


def test_all_installed_all_tuples():
    result = installed.all_installed()
    for name, version in result:
        assert isinstance(name, str)
        assert isinstance(version, str)
