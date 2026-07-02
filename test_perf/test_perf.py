"""Dry-run oriented CLI benchmarks."""

from __future__ import annotations

import json

import pytest

from test_perf.conftest import run_cli_command

JSON_CASES = [
    pytest.param(("config", "json"), "dict-key", "gitlab", id="config-json"),
    pytest.param(("doctor", "--format", "json"), "dict-key", "warnings", id="doctor-json"),
    pytest.param(("usage", "--format", "json"), "dict-key", "total_tokens", id="usage-json"),
    pytest.param(("context", "files", "--format", "json"), "list-member", "README.md", id="context-files-json"),
    pytest.param(("context", "skills", "--format", "json"), "list-dict-key", "name", id="context-skills-json"),
    pytest.param(
        ("context", "templates", "--format", "json"),
        "list-member-label",
        "central:central-template",
        id="context-templates-json",
    ),
    pytest.param(
        ("context", "custom-instructions", "--format", "json"),
        "list-member-label",
        "central:central.md",
        id="context-custom-instructions-json",
    ),
]


def assert_payload_shape(payload: object, shape: str, expected: str) -> None:
    """Assert a benchmarked command returned the expected JSON shape."""
    if shape == "dict-key":
        assert isinstance(payload, dict)
        assert expected in payload
        return
    if shape == "list-member":
        assert isinstance(payload, list)
        assert expected in payload
        return
    if shape == "list-dict-key":
        assert isinstance(payload, list)
        assert payload
        assert isinstance(payload[0], dict)
        assert expected in payload[0]
        return
    if shape == "list-member-label":
        assert isinstance(payload, list)
        labels = [item["label"] for item in payload if isinstance(item, dict) and "label" in item]
        assert any(expected in label for label in labels)
        return
    raise AssertionError(f"Unexpected payload shape: {shape}")


@pytest.mark.parametrize(("args", "shape", "expected"), JSON_CASES)
def test_cli_dry_run_json_paths(
    benchmark, repo_root, benchmark_workspace, cli_env, args: tuple[str, ...], shape: str, expected: str
) -> None:
    """Benchmark dry-run style commands that stay local and deterministic."""
    result = benchmark(run_cli_command, args, repo_root, benchmark_workspace, cli_env)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert_payload_shape(payload, shape, expected)
    assert "Traceback" not in result.stderr
