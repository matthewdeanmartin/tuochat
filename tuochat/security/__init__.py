"""Security-related helpers."""

from tuochat.security.windows_isolation import AVAILABLE as WINDOWS_ISOLATION_AVAILABLE
from tuochat.security.windows_isolation import apply_isolation, is_isolated, spawn_isolated

__all__ = [
    "WINDOWS_ISOLATION_AVAILABLE",
    "apply_isolation",
    "is_isolated",
    "spawn_isolated",
]
