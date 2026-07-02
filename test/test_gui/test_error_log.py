"""Tests for the SQLite error log: store layer, logging handler, and GUI tab."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest

tk = pytest.importorskip("tkinter", exc_type=ImportError)

import pytest

from tuochat.logging_config import SQLiteLogHandler
from tuochat.persistence.store import ConversationStore, NullConversationStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path):
    with ConversationStore(tmp_path / "test.db") as s:
        yield s


@pytest.fixture()
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk unavailable: {exc}")
    root.withdraw()
    try:
        yield root
    finally:
        root.destroy()


def iso_now_minus(*, days: int = 0, hours: int = 0, minutes: int = 0) -> str:
    timestamp = datetime.now(timezone.utc) - timedelta(days=days, hours=hours, minutes=minutes)
    return timestamp.replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Store — basic CRUD
# ---------------------------------------------------------------------------


def test_save_and_retrieve_warning(store):
    store.save_error_log_entry(
        recorded_at=iso_now_minus(days=1),
        level=logging.WARNING,
        level_name="WARNING",
        logger_name="tuochat.test",
        message="something fishy",
        exc_type=None,
        exc_value=None,
        exc_traceback=None,
        filename="foo.py",
        lineno=42,
        func_name="do_thing",
    )
    entries = store.get_error_log_entries(min_level=logging.WARNING)
    assert len(entries) == 1
    e = entries[0]
    assert e["level_name"] == "WARNING"
    assert e["logger_name"] == "tuochat.test"
    assert e["message"] == "something fishy"
    assert e["filename"] == "foo.py"
    assert e["lineno"] == 42
    assert e["func_name"] == "do_thing"
    assert e["exc_type"] is None


def test_save_error_with_exception_fields(store):
    store.save_error_log_entry(
        recorded_at=iso_now_minus(days=1, minutes=1),
        level=logging.ERROR,
        level_name="ERROR",
        logger_name="tuochat.provider",
        message="connection failed",
        exc_type="ConnectionError",
        exc_value="refused",
        exc_traceback="  File x.py line 1\n",
        filename="provider.py",
        lineno=99,
        func_name="connect",
    )
    entries = store.get_error_log_entries(min_level=logging.ERROR)
    assert len(entries) == 1
    e = entries[0]
    assert e["exc_type"] == "ConnectionError"
    assert e["exc_value"] == "refused"
    assert "File x.py" in e["exc_traceback"]


def test_min_level_filter_excludes_lower(store):
    for offset_minutes, (level, name) in enumerate(
        [(logging.WARNING, "WARNING"), (logging.ERROR, "ERROR"), (logging.CRITICAL, "CRITICAL")]
    ):
        store.save_error_log_entry(
            recorded_at=iso_now_minus(days=1, minutes=offset_minutes),
            level=level,
            level_name=name,
            logger_name="tuochat.x",
            message=f"msg {name}",
            exc_type=None,
            exc_value=None,
            exc_traceback=None,
            filename="f.py",
            lineno=1,
            func_name="f",
        )
    assert len(store.get_error_log_entries(min_level=logging.WARNING)) == 3
    assert len(store.get_error_log_entries(min_level=logging.ERROR)) == 2
    assert len(store.get_error_log_entries(min_level=logging.CRITICAL)) == 1


def test_entries_returned_newest_first(store):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    timestamps = [
        (now - timedelta(hours=3)).isoformat(),
        (now - timedelta(hours=2)).isoformat(),
        (now - timedelta(hours=1)).isoformat(),
    ]
    for ts in timestamps:
        store.save_error_log_entry(
            recorded_at=ts,
            level=logging.WARNING,
            level_name="WARNING",
            logger_name="tuochat.x",
            message=ts,
            exc_type=None,
            exc_value=None,
            exc_traceback=None,
            filename="f.py",
            lineno=1,
            func_name="f",
        )
    entries = store.get_error_log_entries()
    assert entries[0]["message"] == timestamps[-1]
    assert entries[-1]["message"] == timestamps[0]


def test_delete_entry_by_id(store):
    store.save_error_log_entry(
        recorded_at=iso_now_minus(days=1),
        level=logging.ERROR,
        level_name="ERROR",
        logger_name="tuochat.x",
        message="to delete",
        exc_type=None,
        exc_value=None,
        exc_traceback=None,
        filename="f.py",
        lineno=1,
        func_name="f",
    )
    entries = store.get_error_log_entries()
    assert len(entries) == 1
    entry_id = entries[0]["id"]

    assert store.delete_error_log_entry(entry_id) is True
    assert store.get_error_log_entries() == []


def test_delete_nonexistent_entry_returns_false(store):
    assert store.delete_error_log_entry(999999) is False


def test_clear_all_removes_all_entries(store):
    for i in range(5):
        store.save_error_log_entry(
            recorded_at=iso_now_minus(days=1, minutes=i),
            level=logging.WARNING,
            level_name="WARNING",
            logger_name="tuochat.x",
            message=f"msg {i}",
            exc_type=None,
            exc_value=None,
            exc_traceback=None,
            filename="f.py",
            lineno=i,
            func_name="f",
        )
    deleted = store.clear_error_log()
    assert deleted == 5
    assert store.get_error_log_entries() == []


def test_limit_parameter_caps_results(store):
    for i in range(10):
        store.save_error_log_entry(
            recorded_at=iso_now_minus(days=1, minutes=i),
            level=logging.ERROR,
            level_name="ERROR",
            logger_name="tuochat.x",
            message=f"msg {i}",
            exc_type=None,
            exc_value=None,
            exc_traceback=None,
            filename="f.py",
            lineno=i,
            func_name="f",
        )
    entries = store.get_error_log_entries(limit=3)
    assert len(entries) == 3


def test_retention_cleanup_removes_old_entries(store):
    store.save_error_log_entry(
        recorded_at=iso_now_minus(days=31),
        level=logging.ERROR,
        level_name="ERROR",
        logger_name="tuochat.x",
        message="ancient",
        exc_type=None,
        exc_value=None,
        exc_traceback=None,
        filename="f.py",
        lineno=1,
        func_name="f",
    )
    store.save_error_log_entry(
        recorded_at=iso_now_minus(days=1),
        level=logging.ERROR,
        level_name="ERROR",
        logger_name="tuochat.x",
        message="recent",
        exc_type=None,
        exc_value=None,
        exc_traceback=None,
        filename="f.py",
        lineno=1,
        func_name="f",
    )
    deleted = store.cleanup_error_log_retention(days=30)
    assert deleted == 1
    entries = store.get_error_log_entries(limit=500)
    assert len(entries) == 1
    assert entries[0]["message"] == "recent"


# ---------------------------------------------------------------------------
# NullConversationStore stubs
# ---------------------------------------------------------------------------


def test_null_store_stubs_are_no_ops():
    null = NullConversationStore(None)  # type: ignore[arg-type]
    # Should not raise
    null.save_error_log_entry(
        recorded_at=iso_now_minus(days=1),
        level=logging.WARNING,
        level_name="WARNING",
        logger_name="x",
        message="m",
        exc_type=None,
        exc_value=None,
        exc_traceback=None,
        filename=None,
        lineno=None,
        func_name=None,
    )
    assert null.get_error_log_entries() == []
    assert null.delete_error_log_entry(1) is False
    assert null.clear_error_log() == 0
    assert null.cleanup_error_log_retention() == 0


# ---------------------------------------------------------------------------
# SQLiteLogHandler
# ---------------------------------------------------------------------------


def test_handler_captures_warning_to_store(store):
    handler = SQLiteLogHandler(level=logging.WARNING)
    handler.attach_store(store)

    logger = logging.getLogger("tuochat.test_handler_warn")
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        logger.warning("handler test warning")
    finally:
        logger.removeHandler(handler)

    entries = store.get_error_log_entries(min_level=logging.WARNING)
    assert any("handler test warning" in e["message"] for e in entries)


def test_handler_captures_exception_info(store):
    handler = SQLiteLogHandler(level=logging.WARNING)
    handler.attach_store(store)

    logger = logging.getLogger("tuochat.test_handler_exc")
    logger.addHandler(handler)
    logger.setLevel(logging.ERROR)
    try:
        try:
            raise ValueError("test boom")
        except ValueError:
            logger.error("caught it", exc_info=True)
    finally:
        logger.removeHandler(handler)

    entries = store.get_error_log_entries(min_level=logging.ERROR)
    exc_entries = [e for e in entries if e.get("exc_type") == "ValueError"]
    assert exc_entries, "expected an entry with exc_type=ValueError"
    e = exc_entries[0]
    assert e["exc_value"] == "test boom"
    assert "ValueError" in (e["exc_traceback"] or "")


def test_handler_is_noop_without_store():
    """Handler must not raise when no store is attached."""
    handler = SQLiteLogHandler(level=logging.WARNING)
    record = logging.LogRecord(
        name="tuochat.x",
        level=logging.WARNING,
        pathname="f.py",
        lineno=1,
        msg="no store yet",
        args=(),
        exc_info=None,
    )
    handler.emit(record)  # should not raise


def test_handler_drops_below_min_level(store):
    handler = SQLiteLogHandler(level=logging.ERROR)
    handler.attach_store(store)

    logger = logging.getLogger("tuochat.test_handler_drop")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        logger.warning("below threshold — should not persist")
    finally:
        logger.removeHandler(handler)

    assert store.get_error_log_entries(min_level=logging.WARNING) == []


def test_handler_source_location_fields(store):
    handler = SQLiteLogHandler(level=logging.WARNING)
    handler.attach_store(store)

    logger = logging.getLogger("tuochat.test_handler_loc")
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        logger.warning("location check")
    finally:
        logger.removeHandler(handler)

    entries = store.get_error_log_entries()
    loc_entries = [e for e in entries if "location check" in e["message"]]
    assert loc_entries
    e = loc_entries[0]
    assert e["filename"] is not None
    assert e["lineno"] is not None
    assert e["func_name"] is not None


# ---------------------------------------------------------------------------
# GUI tab (unit — no display, requires Tk)
# ---------------------------------------------------------------------------


class FakeStore:
    """Minimal store double for GUI tests."""

    def __init__(self, entries=None):
        self.entries = entries or []
        self.deleted: list[int] = []
        self.cleared = False

    def get_error_log_entries(self, limit=500, min_level=logging.WARNING):
        return [e for e in self.entries if e["level"] >= min_level][:limit]

    def cleanup_error_log_retention(self, days=30):
        return 0

    def delete_error_log_entry(self, entry_id: int) -> bool:
        self.deleted.append(entry_id)
        self.entries = [e for e in self.entries if e["id"] != entry_id]
        return True

    def clear_error_log(self) -> int:
        count = len(self.entries)
        self.entries = []
        self.cleared = True
        return count


def make_entry(entry_id: int, level: int = logging.ERROR, message: str = "boom") -> dict:
    return {
        "id": entry_id,
        "recorded_at": "2026-04-11T10:00:00",
        "level": level,
        "level_name": logging.getLevelName(level),
        "logger_name": "tuochat.test",
        "message": message,
        "exc_type": None,
        "exc_value": None,
        "exc_traceback": None,
        "filename": "f.py",
        "lineno": 1,
        "func_name": "go",
    }


def test_tab_builds_and_shows_entries(tk_root):
    from tuochat.gui.error_log_tab import build_error_log_tab

    fake = FakeStore([make_entry(1, logging.ERROR, "first"), make_entry(2, logging.WARNING, "second")])
    frame = tk.Frame(tk_root)
    view = build_error_log_tab(frame, fake)

    assert len(view.entries) == 2
    assert len(view.tree.get_children()) == 2


def test_tab_refresh_updates_tree(tk_root):
    from tuochat.gui.error_log_tab import build_error_log_tab

    fake = FakeStore([make_entry(1)])
    frame = tk.Frame(tk_root)
    view = build_error_log_tab(frame, fake)
    assert len(view.tree.get_children()) == 1

    fake.entries.append(make_entry(2, message="new one"))
    view.refresh()
    assert len(view.tree.get_children()) == 2


def test_tab_delete_selected_calls_store(tk_root):
    from tuochat.gui.error_log_tab import build_error_log_tab

    fake = FakeStore([make_entry(42)])
    frame = tk.Frame(tk_root)
    view = build_error_log_tab(frame, fake)

    children = view.tree.get_children()
    assert children
    view.tree.selection_set(children[0])
    view.delete_selected()

    assert 42 in fake.deleted
    assert len(view.tree.get_children()) == 0


def test_tab_level_filter_change(tk_root):
    from tuochat.gui.error_log_tab import build_error_log_tab

    fake = FakeStore(
        [
            make_entry(1, logging.WARNING, "warn msg"),
            make_entry(2, logging.ERROR, "error msg"),
        ]
    )
    frame = tk.Frame(tk_root)
    view = build_error_log_tab(frame, fake)
    assert len(view.entries) == 2

    view.level_var.set("ERROR")
    view.on_level_change()
    assert len(view.entries) == 1
    assert view.entries[0]["level_name"] == "ERROR"


def test_tab_empty_store_shows_no_rows(tk_root):
    from tuochat.gui.error_log_tab import build_error_log_tab

    frame = tk.Frame(tk_root)
    view = build_error_log_tab(frame, FakeStore([]))
    assert view.tree.get_children() == ()
    assert "0 entr" in view.count_var.get()


def test_tab_count_label_singular(tk_root):
    from tuochat.gui.error_log_tab import build_error_log_tab

    frame = tk.Frame(tk_root)
    view = build_error_log_tab(frame, FakeStore([make_entry(1)]))
    assert view.count_var.get() == "1 entry"


def test_tab_count_label_plural(tk_root):
    from tuochat.gui.error_log_tab import build_error_log_tab

    frame = tk.Frame(tk_root)
    view = build_error_log_tab(frame, FakeStore([make_entry(1), make_entry(2)]))
    assert view.count_var.get() == "2 entries"
