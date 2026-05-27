"""Minimal module entrypoint that verifies package integrity before importing CLI code."""

from __future__ import annotations

import sys

from tuochat.security.tamper import TamperError, verify_or_die


def ensure_utf8_stdio() -> None:
    """Reconfigure stdout/stderr to UTF-8 on Windows when the console codepage would otherwise mangle non-ASCII."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass


def main() -> int:
    """Run tamper verification and then dispatch to the real CLI."""
    ensure_utf8_stdio()
    try:
        verify_or_die("tuochat", allow_env_override=True)
    except TamperError as exc:
        print(str(exc), flush=True)
        return 2

    from tuochat.cli import main as cli_main

    return int(cli_main())


if __name__ == "__main__":
    raise SystemExit(main())
