"""Unit tests for tuochat.self_pkg_mgmt.install_method."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

from tuochat.self_pkg_mgmt import install_method
from tuochat.self_pkg_mgmt.install_method import InstallMethod, detect, upgrade_argv

# ---------------------------------------------------------------------------
# is_editable
# ---------------------------------------------------------------------------


def dist_with_direct_url(data: dict | None, raise_on_read: bool = False) -> MagicMock:
    dist = MagicMock()
    if raise_on_read:
        dist.read_text.side_effect = OSError("nope")
    elif data is None:
        dist.read_text.return_value = None
    else:
        dist.read_text.return_value = json.dumps(data)
    return dist


def test_is_editable_true():
    dist = dist_with_direct_url({"url": "file:///foo", "dir_info": {"editable": True}})
    assert install_method.is_editable(dist) is True


def test_is_editable_false():
    dist = dist_with_direct_url({"url": "file:///foo", "dir_info": {"editable": False}})
    assert install_method.is_editable(dist) is False


def test_is_editable_no_dir_info():
    dist = dist_with_direct_url({"url": "file:///foo"})
    assert install_method.is_editable(dist) is False


def test_is_editable_no_file():
    dist = dist_with_direct_url(None)
    assert install_method.is_editable(dist) is False


def test_is_editable_read_raises():
    dist = dist_with_direct_url(None, raise_on_read=True)
    assert install_method.is_editable(dist) is False


def test_is_editable_bad_json():
    dist = MagicMock()
    dist.read_text.return_value = "not json {"
    assert install_method.is_editable(dist) is False


# ---------------------------------------------------------------------------
# dist_location
# ---------------------------------------------------------------------------


def test_dist_location_via_locate_file():
    dist = MagicMock()
    dist.locate_file.return_value = Path("/some/path")
    loc = install_method.dist_location(dist)
    assert loc is not None
    assert loc.is_absolute()


def test_dist_location_via_path_attr():
    dist = MagicMock(spec=[])  # no locate_file attribute
    dist._path = Path("/other/path")
    loc = install_method.dist_location(dist)
    assert loc is not None


def test_dist_location_locate_file_raises():
    dist = MagicMock()
    dist.locate_file.side_effect = RuntimeError("boom")
    # Should fall through to _path or return None without raising
    install_method.dist_location(dist)


# ---------------------------------------------------------------------------
# detect — not installed
# ---------------------------------------------------------------------------


def test_detect_unknown_for_nonexistent_package():
    result = detect("___no_such_package_ever___")
    assert result == InstallMethod.UNKNOWN


# ---------------------------------------------------------------------------
# detect — editable
# ---------------------------------------------------------------------------


def test_detect_editable(monkeypatch):
    dist = dist_with_direct_url({"url": "file:///src", "dir_info": {"editable": True}})
    monkeypatch.setattr(install_method.metadata, "distribution", lambda name: dist)
    assert detect("mypkg") == InstallMethod.EDITABLE


# ---------------------------------------------------------------------------
# detect — uv-tool
# ---------------------------------------------------------------------------


def test_detect_uv_tool(monkeypatch):
    dist = dist_with_direct_url(None)  # not editable
    dist.locate_file.return_value = Path("/home/user/.local/share/uv/tools/mypkg/lib")
    monkeypatch.setattr(install_method.metadata, "distribution", lambda name: dist)
    assert detect("mypkg") == InstallMethod.UV_TOOL


# ---------------------------------------------------------------------------
# detect — pipx
# ---------------------------------------------------------------------------


def test_detect_pipx(monkeypatch):
    dist = dist_with_direct_url(None)
    dist.locate_file.return_value = Path("/home/user/.local/pipx/venvs/mypkg/lib")
    monkeypatch.setattr(install_method.metadata, "distribution", lambda name: dist)
    assert detect("mypkg") == InstallMethod.PIPX


# ---------------------------------------------------------------------------
# detect — venv-pip (in venv, not uv/pipx)
# ---------------------------------------------------------------------------


def test_detect_venv_pip(monkeypatch):
    dist = dist_with_direct_url(None)
    dist.locate_file.return_value = Path("/some/venv/lib/python3.12/site-packages")
    monkeypatch.setattr(install_method.metadata, "distribution", lambda name: dist)
    # Simulate being in a venv
    monkeypatch.setattr(install_method.sys, "prefix", "/some/venv")
    monkeypatch.setattr(install_method.sys, "base_prefix", "/usr")
    assert detect("mypkg") == InstallMethod.VENV_PIP


# ---------------------------------------------------------------------------
# detect — user-pip
# ---------------------------------------------------------------------------


def test_detect_user_pip(monkeypatch):
    dist = dist_with_direct_url(None)
    dist.locate_file.return_value = Path("/home/user/.local/lib/python3.12/site-packages")
    monkeypatch.setattr(install_method.metadata, "distribution", lambda name: dist)
    # Not in a venv
    monkeypatch.setattr(install_method.sys, "prefix", "/usr")
    monkeypatch.setattr(install_method.sys, "base_prefix", "/usr")

    import site as site_module

    monkeypatch.setattr(site_module, "getusersitepackages", lambda: "/home/user/.local/lib/python3.12/site-packages")

    result = detect("mypkg")
    assert result == InstallMethod.USER_PIP


# ---------------------------------------------------------------------------
# detect — system-pip fallback
# ---------------------------------------------------------------------------


def test_detect_system_pip(monkeypatch):
    dist = dist_with_direct_url(None)
    dist.locate_file.return_value = Path("/usr/lib/python3/dist-packages")
    monkeypatch.setattr(install_method.metadata, "distribution", lambda name: dist)
    monkeypatch.setattr(install_method.sys, "prefix", "/usr")
    monkeypatch.setattr(install_method.sys, "base_prefix", "/usr")

    import site as site_module

    monkeypatch.setattr(site_module, "getusersitepackages", lambda: "/home/user/.local/lib/python3/site-packages")

    result = detect("mypkg")
    assert result == InstallMethod.SYSTEM_PIP


# ---------------------------------------------------------------------------
# upgrade_argv
# ---------------------------------------------------------------------------


def test_upgrade_argv_uv_tool():
    argv = upgrade_argv(InstallMethod.UV_TOOL, "mypkg")
    assert argv == ["uv", "tool", "upgrade", "mypkg"]


def test_upgrade_argv_pipx():
    argv = upgrade_argv(InstallMethod.PIPX, "mypkg")
    assert argv == ["pipx", "upgrade", "mypkg"]


def test_upgrade_argv_venv_pip():
    argv = upgrade_argv(InstallMethod.VENV_PIP, "mypkg")
    assert argv is not None
    assert argv[0] == sys.executable
    assert "--upgrade" in argv
    assert "mypkg" in argv
    assert "--user" not in argv


def test_upgrade_argv_user_pip():
    argv = upgrade_argv(InstallMethod.USER_PIP, "mypkg")
    assert argv is not None
    assert "--user" in argv
    assert "--upgrade" in argv


def test_upgrade_argv_system_pip():
    argv = upgrade_argv(InstallMethod.SYSTEM_PIP, "mypkg")
    assert argv is not None
    assert "--upgrade" in argv
    assert "--user" not in argv


def test_upgrade_argv_editable_returns_none():
    assert upgrade_argv(InstallMethod.EDITABLE, "mypkg") is None


def test_upgrade_argv_unknown_returns_none():
    assert upgrade_argv(InstallMethod.UNKNOWN, "mypkg") is None
