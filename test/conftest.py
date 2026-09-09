"""Shared fixtures for the unit test suite."""

from __future__ import annotations

import pytest

import tuochat.cli.io as io_module


@pytest.fixture(autouse=True)
def reset_interactive_io_backend():
    """Keep a stub input backend from leaking between tests.

    tuochat.cli.io caches the selected backend in a module global.  A test that
    installs a fake one -- directly or via monkeypatch -- would otherwise leave
    it in place for every test that runs afterwards in the same process, and
    those tests fail far from the code that actually broke them.
    """
    yield
    io_module.reset_backend()
