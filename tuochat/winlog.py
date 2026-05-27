"""Windows Event Log integration for tuochat.

Sends operationally important events to the Windows Application event log
using the registered source ``tuochat``.  The module is a no-op on non-Windows
platforms and when pywin32 is not installed.

Event ID registry
-----------------
Events are grouped into ranges so Event Viewer filters are easy to build:

  1000–1099  Lifecycle   (startup / shutdown)
  1100–1199  Auth        (token load, OAuth, auth failures)
  1200–1299  Config      (bad config, missing required field)
  1300–1399  Dependency  (optional dep unavailable, sandbox failure)
  1400–1499  Network     (connectivity failures)
  1500–1599  Data        (DB corruption, BagIt failure)
  1600–1699  Admin       (nuke, purge, source registration)

Keep this table in sync with the constants below so that IT admins can
build stable alert rules without parsing message text.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Stable event IDs — never renumber once shipped
# ---------------------------------------------------------------------------

# Lifecycle
EV_STARTUP = 1000
EV_SHUTDOWN = 1001
EV_CRASH_RECOVERY = 1002

# Auth
EV_AUTH_TOKEN_LOADED = 1100
EV_AUTH_OAUTH_STARTED = 1101
EV_AUTH_FAILURE = 1102
EV_AUTHZ_FAILURE = 1103  # 403 / permission denied from server

# Config
EV_CONFIG_ERROR = 1200
EV_CONFIG_MISSING_REQUIRED = 1201

# Dependencies
EV_DEP_UNAVAILABLE = 1300
EV_DEP_SANDBOX_FAILURE = 1301

# Network
EV_NETWORK_FAILURE = 1400

# Data integrity
EV_DB_CORRUPTION = 1500
EV_BAGIT_FAILURE = 1501

# Admin actions
EV_ADMIN_NUKE = 1600
EV_ADMIN_PURGE = 1601
EV_SOURCE_REGISTERED = 1602

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

SOURCE = "tuochat"
LOG = "Application"
win32evtlog: Any | None = None
win32evtlogutil: Any | None = None

# Cached availability flag; set once at import time.
WIN32_AVAILABLE: bool = sys.platform == "win32"
if WIN32_AVAILABLE:
    try:
        import win32evtlog as _win32evtlog_mod
        import win32evtlogutil as _win32evtlogutil_mod

        win32evtlog = _win32evtlog_mod
        win32evtlogutil = _win32evtlogutil_mod
    except ImportError:
        WIN32_AVAILABLE = False


def evtype(level: int) -> int:
    """Map a stdlib logging level to a Windows event type constant."""
    if win32evtlog is None:
        raise RuntimeError("win32evtlog is unavailable")
    if level >= logging.ERROR:
        return win32evtlog.EVENTLOG_ERROR_TYPE
    if level >= logging.WARNING:
        return win32evtlog.EVENTLOG_WARNING_TYPE
    return win32evtlog.EVENTLOG_INFORMATION_TYPE


def try_register_source() -> bool:
    """Attempt to register the ``tuochat`` event source in the registry.

    Requires elevated privileges.  Returns True on success, False if
    registration was skipped (no admin rights) or pywin32 is absent.
    """
    if not WIN32_AVAILABLE:
        return False
    if win32evtlogutil is None:
        return False
    try:
        win32evtlogutil.AddSourceToRegistry(SOURCE, msgDLL=None, eventLogType=LOG)
        report_event(EV_SOURCE_REGISTERED, "tuochat event source registered in Windows registry.", logging.INFO)
        return True
    except Exception:  # noqa: BLE001 — pywintypes.error doesn't inherit OSError
        # Access denied or registry error — not running as admin; silently skip.
        return False


def report_event(
    event_id: int,
    message: str,
    level: int = logging.INFO,
    *,
    strings: list[str] | None = None,
) -> None:
    """Write a single event to the Windows Application event log.

    A no-op when pywin32 is unavailable or the platform is not Windows.

    Args:
        event_id: One of the ``EV_*`` constants defined in this module.
        message: Human-readable description of the event.
        level: stdlib logging level used to map to EVENTLOG_{INFO,WARNING,ERROR}_TYPE.
        strings: Additional insertion strings appended after *message*.
    """
    if not WIN32_AVAILABLE:
        return
    if win32evtlogutil is None:
        return
    all_strings = [message] + (strings or [])
    try:
        win32evtlogutil.ReportEvent(
            SOURCE,
            event_id,
            eventType=evtype(level),
            strings=all_strings,
        )
    except OSError:
        # Silently swallow — event log failures must never crash the app.
        pass


# ---------------------------------------------------------------------------
# logging.Handler subclass
# ---------------------------------------------------------------------------

# Records whose ``winlog_event_id`` extra attribute is set get routed to
# the Windows event log.  Normal log records are ignored.
#
# Usage in application code:
#
#   logger.warning(
#       "Auth failure for host %s: %s", host, err,
#       extra={"winlog_event_id": winlog.EV_AUTH_FAILURE},
#   )


class WindowsEventLogHandler(logging.Handler):
    """Logging handler that writes records to the Windows Application event log.

    Only records that carry the ``winlog_event_id`` extra field are forwarded.
    All others are silently dropped so the handler is cheap to attach globally.
    """

    def emit(self, record: logging.LogRecord) -> None:
        event_id: int | None = getattr(record, "winlog_event_id", None)
        if event_id is None or not WIN32_AVAILABLE:
            return
        try:
            msg = self.format(record)
            report_event(event_id, msg, record.levelno)
        except Exception:  # noqa: BLE001
            self.handleError(record)
