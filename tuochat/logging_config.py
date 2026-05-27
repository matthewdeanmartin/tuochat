"""Logging configuration for tuochat.

Uses stdlib logging with JSON-structured output and token redaction.
On Windows, operationally important events are also forwarded to the
Windows Application event log via the ``tuochat`` source (requires pywin32).
"""

from __future__ import annotations

import logging
import re
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Protocol

from tuochat.serialization import json_dumps


class ErrorLogStore(Protocol):
    """Minimal store interface used by SQLiteLogHandler."""

    def save_error_log_entry(
        self,
        recorded_at: str,
        level: int,
        level_name: str,
        logger_name: str,
        message: str,
        exc_type: str | None,
        exc_value: str | None,
        exc_traceback: str | None,
        filename: str | None,
        lineno: int | None,
        func_name: str | None,
    ) -> None:
        """Persist one error log entry."""
        ...


# Rolling log: 1 MB per file, keep 3 backups → max ~3 MB on disk.
LOG_MAX_BYTES = 1_000_000
LOG_BACKUP_COUNT = 3


class TokenRedactFilter(logging.Filter):
    """Redact GitLab tokens from log output."""

    patterns = [
        re.compile(r"(glpat-)\w+"),
        re.compile(r"(gloas-)\w+"),
        re.compile(r"(PRIVATE-TOKEN:\s*)\S+"),
        re.compile(r"(Authorization:\s*Bearer\s+)\S+"),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact tokens in the log message."""
        msg = record.getMessage()
        for pat in self.patterns:
            msg = pat.sub(r"\1***REDACTED***", msg)
        record.msg = msg
        record.args = None
        return True


class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON."""

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as JSON."""
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            entry["exception"] = self.formatException(record.exc_info)
        return json_dumps(entry, default=str)


class SQLiteLogHandler(logging.Handler):
    """Logging handler that persists WARNING+ records to the SQLite error log table.

    Attach a store via ``attach_store(store)`` once the database is open.
    Records are silently dropped until a store is attached.  Safe to add to
    the root logger early in startup; it becomes active as soon as the store
    is ready.
    """

    def __init__(self, level: int = logging.WARNING) -> None:
        super().__init__(level)
        self.store: ErrorLogStore | None = None

    def attach_store(self, store: ErrorLogStore) -> None:
        """Wire in the persistence store.  Thread-safe assignment."""
        self.store = store

    def emit(self, record: logging.LogRecord) -> None:
        store = self.store
        if store is None:
            return
        try:
            msg = self.format(record)
            exc_type: str | None = None
            exc_value: str | None = None
            exc_tb: str | None = None
            if record.exc_info and record.exc_info[0] is not None:
                import traceback  # noqa: PLC0415

                exc_type = record.exc_info[0].__name__
                exc_value = str(record.exc_info[1])
                exc_tb = "".join(traceback.format_tb(record.exc_info[2]))
            recorded_at = datetime.now(timezone.utc).isoformat()
            store.save_error_log_entry(
                recorded_at=recorded_at,
                level=record.levelno,
                level_name=record.levelname,
                logger_name=record.name,
                message=msg,
                exc_type=exc_type,
                exc_value=exc_value,
                exc_traceback=exc_tb,
                filename=record.filename,
                lineno=record.lineno,
                func_name=record.funcName,
            )
        except Exception:  # noqa: BLE001
            self.handleError(record)


# Module-level singleton so app.py can call attach_store() after DB init.
sqlite_log_handler = SQLiteLogHandler(level=logging.WARNING)


def setup_logging(
    log_dir: Path | None = None,
    level: int = logging.WARNING,
    debug: bool = False,
    enable_file_logging: bool = True,
    stdout: bool = False,
) -> None:
    """Configure logging for tuochat.

    Args:
        log_dir: Directory for rolling log files. If None, no file logging.
        level: Console logging level. Defaults to WARNING.
        debug: If True, set console and file level to DEBUG.
        enable_file_logging: If False, skip the file handler even when log_dir is set.
        stdout: If True, direct the console handler to stdout instead of stderr.
            Intended for the GUI, which captures stdout for its transcript pane.
    """
    if debug:
        level = logging.DEBUG

    root = logging.getLogger("tuochat")
    root.setLevel(level)

    # Don't add handlers if already configured (e.g., in tests)
    if root.handlers:
        return

    redact_filter = TokenRedactFilter()

    # Console handler — human-readable, goes to stdout (GUI) or stderr (CLI)
    stream = sys.stdout if stdout else sys.stderr
    console = logging.StreamHandler(stream)
    console.setLevel(level)
    console.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    console.addFilter(redact_filter)
    root.addHandler(console)

    # Rolling file handler — JSON structured, WARNING+ by default to avoid perf
    # impact from chatty debug output. Bumped to DEBUG only when --debug is set.
    if log_dir and enable_file_logging:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "tuochat.log"
        file_level = logging.DEBUG if debug else logging.WARNING
        file_handler = RotatingFileHandler(
            str(log_file),
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(file_level)
        file_handler.setFormatter(JsonFormatter())
        file_handler.addFilter(redact_filter)
        root.addHandler(file_handler)

    # Windows Event Log handler — only active on Windows with pywin32 installed.
    # Accepts all levels so the handler itself decides per-record via event_id.
    if sys.platform == "win32":
        try:
            from tuochat.winlog import WindowsEventLogHandler  # noqa: PLC0415

            win_handler = WindowsEventLogHandler()
            win_handler.setLevel(logging.DEBUG)
            win_handler.addFilter(redact_filter)
            root.addHandler(win_handler)
        except ImportError:
            pass

    # SQLite error log handler — collects WARNING+ for the GUI Errors tab.
    # No-op until attach_store() is called; safe to add unconditionally.
    sqlite_log_handler.addFilter(redact_filter)
    root.addHandler(sqlite_log_handler)

    # Suppress noisy loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def set_console_level(level: int) -> None:
    """Adjust the console handler level on the tuochat root logger at runtime.

    Used by the GUI to crank verbosity up/down without restarting.
    """
    root = logging.getLogger("tuochat")
    root.setLevel(level)
    for handler in root.handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, RotatingFileHandler):
            handler.setLevel(level)
