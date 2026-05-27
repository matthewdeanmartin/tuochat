"""Fast startup-oriented CLI benchmarks."""

from __future__ import annotations

import pytest

from test_perf.conftest import run_cli_command

FAST_CASES = [
    pytest.param(("--help",), "usage: tuochat", id="root-help"),
    pytest.param(("--version",), ".", id="version"),
    pytest.param(("chat", "--help"), "--prompt PROMPT", id="chat-help"),
    pytest.param(("context", "--help"), "custom-instructions", id="context-help"),
    pytest.param(("headless", "--help"), "Start a new non-interactive conversation", id="headless-help"),
]


@pytest.mark.parametrize(("args", "expected_text"), FAST_CASES)
def test_cli_fast_paths(benchmark, repo_root, benchmark_workspace, cli_env, args: tuple[str, ...], expected_text: str) -> None:
    """Benchmark cheap CLI entrypoints that mostly measure startup overhead."""
    result = benchmark(run_cli_command, args, repo_root, benchmark_workspace, cli_env)

    assert result.returncode == 0, result.stderr
    assert expected_text in result.stdout
    assert "Traceback" not in result.stderr
