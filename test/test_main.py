"""Tests for the package entrypoint."""

from __future__ import annotations

import runpy

from tuochat.security.tamper import TamperError


def test_module_entrypoint_invokes_cli_main(monkeypatch):
    """Test ``python -m tuochat`` exits with the CLI return code."""
    captured_verify_calls: list[tuple[tuple, dict]] = []

    def fake_main():
        return 7

    def fake_exit(code):
        raise SystemExit(code)

    def fake_verify_or_die(*args, **kwargs):
        captured_verify_calls.append((args, kwargs))

    monkeypatch.setattr("tuochat.security.tamper.verify_or_die", fake_verify_or_die)
    monkeypatch.setattr("tuochat.cli.main", fake_main)
    monkeypatch.setattr("sys.exit", fake_exit)

    try:
        runpy.run_module("tuochat", run_name="__main__")
    except SystemExit as exc:
        assert exc.code == 7
    else:
        raise AssertionError("Expected SystemExit")

    assert captured_verify_calls == [(("tuochat",), {"allow_env_override": True})]


def test_module_entrypoint_aborts_on_tamper(monkeypatch, capsys):
    """Test ``python -m tuochat`` exits early when verification fails."""

    def fail_verification(*args, **kwargs):
        raise TamperError("tamper detected")

    monkeypatch.setattr("tuochat.security.tamper.verify_or_die", fail_verification)

    try:
        runpy.run_module("tuochat", run_name="__main__")
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected SystemExit")

    captured = capsys.readouterr()
    assert "tamper detected" in captured.out
