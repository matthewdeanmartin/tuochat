"""Unit tests for tuochat.self_pkg_mgmt.self_check."""

from __future__ import annotations

import importlib

# The package __init__ shadows 'self_check' with the api function; import the module by full path.
self_check = importlib.import_module("tuochat.self_pkg_mgmt.self_check")


# ---------------------------------------------------------------------------
# split_requirement
# ---------------------------------------------------------------------------


def test_split_requirement_plain():
    result = self_check.split_requirement("requests")
    assert result == ("requests", "", None)


def test_split_requirement_with_specifier():
    result = self_check.split_requirement("requests>=2.0,<3")
    assert result is not None
    name, spec, marker = result
    assert name == "requests"
    assert ">=2.0" in spec


def test_split_requirement_with_marker():
    result = self_check.split_requirement('requests>=2.0; python_version >= "3.8"')
    assert result is not None
    name, spec, marker = result
    assert name == "requests"
    assert marker is not None
    assert "python_version" in marker


def test_split_requirement_with_extras():
    result = self_check.split_requirement("requests[security]>=2.0")
    assert result is not None
    name, spec, marker = result
    assert name == "requests"
    # extras bracket stripped from specifier
    assert "[" not in spec


def test_split_requirement_empty():
    assert self_check.split_requirement("") is None


def test_split_requirement_semicolon_only():
    assert self_check.split_requirement("; python_version >= '3.8'") is None


# ---------------------------------------------------------------------------
# version_tuple
# ---------------------------------------------------------------------------


def test_version_tuple_standard():
    assert self_check.version_tuple("1.2.3") == (1, 2, 3)


def test_version_tuple_single():
    assert self_check.version_tuple("5") == (5,)


def test_version_tuple_with_pre():
    # stops at non-numeric chunk
    assert self_check.version_tuple("1.0a1") == (1, 0)


def test_version_tuple_empty():
    assert self_check.version_tuple("") == (0,)


def test_version_tuple_dash_separator():
    assert self_check.version_tuple("1-2-3") == (1, 2, 3)


# ---------------------------------------------------------------------------
# satisfies
# ---------------------------------------------------------------------------


def test_satisfies_eq():
    assert self_check.satisfies("==", "1.0", "1.0") is True
    assert self_check.satisfies("==", "1.0", "1.1") is False


def test_satisfies_ne():
    assert self_check.satisfies("!=", "1.0", "1.1") is True
    assert self_check.satisfies("!=", "1.0", "1.0") is False


def test_satisfies_gte():
    assert self_check.satisfies(">=", "2.0", "1.0") is True
    assert self_check.satisfies(">=", "1.0", "2.0") is False
    assert self_check.satisfies(">=", "1.0", "1.0") is True


def test_satisfies_gt():
    assert self_check.satisfies(">", "2.0", "1.0") is True
    assert self_check.satisfies(">", "1.0", "1.0") is False


def test_satisfies_lte():
    assert self_check.satisfies("<=", "1.0", "2.0") is True
    assert self_check.satisfies("<=", "2.0", "1.0") is False


def test_satisfies_lt():
    assert self_check.satisfies("<", "1.0", "2.0") is True
    assert self_check.satisfies("<", "2.0", "1.0") is False


def test_satisfies_compatible():
    # ~=1.4 means >=1.4, <2
    assert self_check.satisfies("~=", "1.4.1", "1.4") is True
    assert self_check.satisfies("~=", "2.0", "1.4") is False
    assert self_check.satisfies("~=", "1.3", "1.4") is False


def test_satisfies_compatible_single_component():
    # ~=1 with len(rhs) < 2 → just >=
    assert self_check.satisfies("~=", "1.0", "1") is True
    assert self_check.satisfies("~=", "0.9", "1") is False


def test_satisfies_triple_eq():
    assert self_check.satisfies("===", "1.0", "1.0") is True
    assert self_check.satisfies("===", "1.0", "1.1") is False


def test_satisfies_unknown_op():
    # unknown operator returns True (permissive)
    assert self_check.satisfies("??", "1.0", "1.0") is True


# ---------------------------------------------------------------------------
# check_specifier
# ---------------------------------------------------------------------------


def test_check_specifier_empty():
    assert self_check.check_specifier("1.0", "") is True


def test_check_specifier_single_satisfied():
    assert self_check.check_specifier("2.0", ">=1.0") is True


def test_check_specifier_single_violated():
    assert self_check.check_specifier("0.9", ">=1.0") is False


def test_check_specifier_multi_all_satisfied():
    assert self_check.check_specifier("1.5", ">=1.0,<2.0") is True


def test_check_specifier_multi_one_violated():
    assert self_check.check_specifier("2.1", ">=1.0,<2.0") is False


def test_check_specifier_no_op_in_part():
    # part without a recognisable specifier → skip → True
    assert self_check.check_specifier("1.0", "somegarbage") is True


# ---------------------------------------------------------------------------
# normalize
# ---------------------------------------------------------------------------


def test_normalize_dashes():
    assert self_check.normalize("my-pkg") == "my-pkg"


def test_normalize_underscores():
    assert self_check.normalize("my_pkg") == "my-pkg"


def test_normalize_dots():
    assert self_check.normalize("my.pkg") == "my-pkg"


def test_normalize_mixed():
    assert self_check.normalize("My_.Pkg") == "my-pkg"


def test_normalize_uppercase():
    assert self_check.normalize("MyPkg") == "mypkg"


# ---------------------------------------------------------------------------
# marker_applies
# ---------------------------------------------------------------------------


def test_marker_applies_extra_always_false():
    assert self_check.marker_applies('extra == "security"') is False


def test_marker_applies_and_expression():
    # compound → permissive True
    assert self_check.marker_applies('python_version >= "3.8" and sys_platform == "linux"') is True


def test_marker_applies_or_expression():
    assert self_check.marker_applies('os_name == "nt" or os_name == "posix"') is True


def test_marker_applies_known_var_matching():
    import sys

    ver = f"{sys.version_info.major}.{sys.version_info.minor}"
    assert self_check.marker_applies(f'python_version == "{ver}"') is True


def test_marker_applies_known_var_not_matching():
    assert self_check.marker_applies('python_version == "2.7"') is False


def test_marker_applies_unknown_var():
    assert self_check.marker_applies('some_unknown_var == "value"') is True


def test_marker_applies_no_match_at_all():
    assert self_check.marker_applies("no operators here") is True


def test_marker_applies_reversed_operands():
    # '3.8' <= python_version — reversed form

    # Any real python version should be >= 3.8 in our test env
    assert self_check.marker_applies('"2.0" <= python_version') is True


def test_marker_applies_sys_platform_match(monkeypatch):
    monkeypatch.setattr(self_check, "MARKER_ENV", {**self_check.MARKER_ENV, "sys_platform": "linux"})
    assert self_check.marker_applies('sys_platform == "linux"') is True
    assert self_check.marker_applies('sys_platform == "win32"') is False


def test_marker_applies_sys_platform_ne(monkeypatch):
    monkeypatch.setattr(self_check, "MARKER_ENV", {**self_check.MARKER_ENV, "sys_platform": "darwin"})
    assert self_check.marker_applies('sys_platform != "win32"') is True


# ---------------------------------------------------------------------------
# run() — integration using real importlib.metadata
# ---------------------------------------------------------------------------


def test_run_returns_list():
    result = self_check.run()
    assert isinstance(result, list)
    # All entries should be strings
    for item in result:
        assert isinstance(item, str)


def test_run_does_not_raise():
    # Should complete without any exception against the real environment.
    self_check.run()
