"""Run pytest benchmarks with repository defaults."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


def has_option(args: list[str], flag: str) -> bool:
    """Return True when a long-option flag is already present."""
    return any(arg == flag or arg.startswith(f"{flag}=") for arg in args)


def build_pytest_args(argv: list[str], repo_root: Path) -> list[str]:
    """Apply benchmark defaults without overriding explicit caller options."""
    args = list(argv)
    benchmark_storage = repo_root / ".benchmarks"
    benchmark_storage.mkdir(exist_ok=True)

    if not has_option(args, "--benchmark-storage"):
        args.extend(["--benchmark-storage", str(benchmark_storage)])
    if not has_option(args, "--benchmark-save") and not has_option(args, "--benchmark-autosave"):
        args.append("--benchmark-autosave")
    return args


def main(argv: list[str] | None = None) -> int:
    """Run pytest with benchmark-friendly defaults for this repository."""
    repo_root = Path(__file__).resolve().parent.parent
    os.chdir(repo_root)
    os.environ.setdefault("PYTHONHASHSEED", "0")
    pytest_args = build_pytest_args(list(sys.argv[1:] if argv is None else argv), repo_root)
    return pytest.main(pytest_args)


if __name__ == "__main__":
    raise SystemExit(main())
