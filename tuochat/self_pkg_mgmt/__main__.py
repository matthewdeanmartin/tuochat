"""Standalone entrypoint: python -m tuochat.self_pkg_mgmt ..."""

from __future__ import annotations

import sys

from tuochat.self_pkg_mgmt.cli import main

if __name__ == "__main__":
    sys.exit(main())
