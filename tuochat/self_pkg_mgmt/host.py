"""Host adapter protocol.

The only module inside self_pkg_mgmt that is allowed to know about tuochat.
Everything else depends on the Host protocol, which means this package can be
lifted out as a standalone library by replacing only this file.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class Host(Protocol):
    """Minimal protocol a host application must satisfy."""

    @property
    def dist_name(self) -> str:
        """Name of the distribution this host represents (e.g. 'tuochat')."""

    @property
    def cache_dir(self) -> Path:
        """Directory where self_pkg_mgmt may write its sidecar cache."""

    @property
    def logger(self) -> logging.Logger:
        """Logger used by self_pkg_mgmt."""


class TuochatHost:
    """Host adapter backed by tuochat.config.TuochatConfig.

    This is the only place in the package that imports from tuochat. Extracting
    the package means deleting this class.
    """

    def __init__(self, dist_name: str = "tuochat", cache_dir: Path | None = None) -> None:
        self.dist_name_value = dist_name
        self.cache_dir_value = cache_dir or self.resolve_cache_dir()
        self.logger_value = logging.getLogger("tuochat.self_pkg_mgmt")

    @staticmethod
    def resolve_cache_dir() -> Path:
        try:
            from tuochat.config import data_dir

            return data_dir()
        except Exception:
            return Path(tempfile.gettempdir()) / "tuochat-self-pkg-mgmt"

    @property
    def dist_name(self) -> str:
        return self.dist_name_value

    @property
    def cache_dir(self) -> Path:
        return self.cache_dir_value

    @property
    def logger(self) -> logging.Logger:
        return self.logger_value


class GenericHost:
    """Stdlib-only host for standalone use."""

    def __init__(self, dist_name: str, cache_dir: Path) -> None:
        self.dist_name_value = dist_name
        self.cache_dir_value = cache_dir
        self.logger_value = logging.getLogger(f"self_pkg_mgmt.{dist_name}")

    @property
    def dist_name(self) -> str:
        return self.dist_name_value

    @property
    def cache_dir(self) -> Path:
        return self.cache_dir_value

    @property
    def logger(self) -> logging.Logger:
        return self.logger_value


def default_host(dist_name: str = "tuochat") -> Host:
    """Return a default Host for the given distribution name."""
    try:
        return TuochatHost(dist_name=dist_name)
    except Exception:
        base = Path(tempfile.gettempdir()) / f"self-pkg-mgmt-{dist_name}"
        return GenericHost(dist_name=dist_name, cache_dir=base)
