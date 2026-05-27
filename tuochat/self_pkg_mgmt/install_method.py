"""Detect how the host distribution was installed."""

from __future__ import annotations

import json
import sys
from enum import Enum
from importlib import metadata
from pathlib import Path


class InstallMethod(str, Enum):
    UV_TOOL = "uv-tool"
    PIPX = "pipx"
    VENV_PIP = "venv-pip"
    USER_PIP = "user-pip"
    SYSTEM_PIP = "system-pip"
    EDITABLE = "editable"
    UNKNOWN = "unknown"


def is_editable(dist: metadata.Distribution) -> bool:
    try:
        raw = dist.read_text("direct_url.json")
    except Exception:
        return False
    if not raw:
        return False
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return False
    dir_info = data.get("dir_info") or {}
    return bool(dir_info.get("editable"))


def dist_location(dist: metadata.Distribution) -> Path | None:
    locate = getattr(dist, "locate_file", None)
    try:
        if locate is not None:
            return Path(locate("")).resolve()
    except Exception:
        pass
    origin = getattr(dist, "_path", None)
    return Path(origin).resolve() if origin else None


def detect(dist_name: str) -> InstallMethod:
    try:
        dist = metadata.distribution(dist_name)
    except metadata.PackageNotFoundError:
        return InstallMethod.UNKNOWN

    if is_editable(dist):
        return InstallMethod.EDITABLE

    location = dist_location(dist)
    location_str = str(location).replace("\\", "/").lower() if location else ""

    if "/uv/tools/" in location_str or "\\uv\\tools\\" in str(location or "").lower():
        return InstallMethod.UV_TOOL
    if "/pipx/venvs/" in location_str or "pipx" in location_str and "venvs" in location_str:
        return InstallMethod.PIPX

    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    if in_venv:
        return InstallMethod.VENV_PIP

    try:
        import site

        user_site = (site.getusersitepackages() or "").replace("\\", "/").lower()
    except Exception:
        user_site = ""
    if user_site and user_site in location_str:
        return InstallMethod.USER_PIP

    return InstallMethod.SYSTEM_PIP


def upgrade_argv(method: InstallMethod, dist_name: str) -> list[str] | None:
    """Return argv for the appropriate upgrade command, or None if not supported."""
    if method == InstallMethod.UV_TOOL:
        return ["uv", "tool", "upgrade", dist_name]
    if method == InstallMethod.PIPX:
        return ["pipx", "upgrade", dist_name]
    if method == InstallMethod.VENV_PIP:
        return [sys.executable, "-m", "pip", "install", "--upgrade", dist_name]
    if method == InstallMethod.USER_PIP:
        return [sys.executable, "-m", "pip", "install", "--user", "--upgrade", dist_name]
    if method == InstallMethod.SYSTEM_PIP:
        return [sys.executable, "-m", "pip", "install", "--upgrade", dist_name]
    return None
