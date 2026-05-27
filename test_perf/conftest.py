"""Shared fixtures for CLI performance benchmarks."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Return the repository root."""
    return Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def benchmark_workspace(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create a stable workspace for context discovery benchmarks."""
    workspace = tmp_path_factory.mktemp("benchmark-workspace")
    (workspace / "README.md").write_text("# Benchmark fixture\n", encoding="utf-8")
    (workspace / "docs").mkdir()
    (workspace / "docs" / "notes.txt").write_text("Local benchmark note\n", encoding="utf-8")
    (workspace / ".claude" / "custom_instructions").mkdir(parents=True)
    (workspace / ".claude" / "custom_instructions" / "workspace.md").write_text(
        "Keep responses concise.\n",
        encoding="utf-8",
    )
    return workspace


@pytest.fixture(scope="session")
def benchmark_state_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create shared config and data directories for benchmark runs."""
    root = tmp_path_factory.mktemp("benchmark-state")
    config_dir = root / "config"
    data_dir = root / "data"
    templates_dir = config_dir / "templates" / "central-template"
    custom_instructions_dir = config_dir / "custom_instructions"

    config_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    templates_dir.mkdir(parents=True, exist_ok=True)
    custom_instructions_dir.mkdir(parents=True, exist_ok=True)

    (templates_dir / "TEMPLATE.md").write_text(
        "---\nname: Central template\ndescription: Benchmark template fixture\n---\nHello\n",
        encoding="utf-8",
    )
    (custom_instructions_dir / "central.md").write_text("Prefer explicit errors.\n", encoding="utf-8")
    return root


@pytest.fixture(scope="session")
def cli_env(repo_root: Path, benchmark_state_root: Path) -> dict[str, str]:
    """Build a deterministic environment for subprocess CLI runs."""
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    pythonpath_parts = [str(repo_root)]
    if existing_pythonpath:
        pythonpath_parts.append(existing_pythonpath)

    env.update(
        {
            "PYTHONPATH": os.pathsep.join(pythonpath_parts),
            "TUOCHAT_CONFIG_DIR": str(benchmark_state_root / "config"),
            "TUOCHAT_DATA_DIR": str(benchmark_state_root / "data"),
            "TUOCHAT_GITLAB_HOST": "",
            "TUOCHAT_GITLAB_TOKEN": "",
            "PYTHONHASHSEED": "0",
        }
    )
    return env


def run_cli_command(args: tuple[str, ...], repo_root: Path, working_dir: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run the CLI in a subprocess so import and startup cost are included."""
    return subprocess.run(
        [sys.executable, "-m", "tuochat", *args],
        capture_output=True,
        check=False,
        cwd=working_dir,
        env=env,
        text=True,
    )
