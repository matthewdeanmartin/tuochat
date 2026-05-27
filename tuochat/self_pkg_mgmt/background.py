"""Background refresh runner.

Uses a daemon thread so it never blocks interpreter shutdown. Callers are
expected to be fine with fire-and-forget: the result is written to the cache
and picked up on the next startup.
"""

from __future__ import annotations

import threading
from typing import Callable


def spawn(target: Callable[[], None], name: str = "self-pkg-mgmt-refresh") -> threading.Thread:
    thread = threading.Thread(target=wrap(target), name=name, daemon=True)
    thread.start()
    return thread


def wrap(target: Callable[[], None]) -> Callable[[], None]:
    def runner() -> None:
        try:
            target()
        except Exception:
            # Fail silent: this is a best-effort background task.
            pass

    return runner
