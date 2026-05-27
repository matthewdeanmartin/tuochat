"""SQLite persistence for conversations and messages.

Uses only stdlib sqlite3. Schema is versioned with a simple migration table.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

from tuochat.models import Conversation, ConversationSearchResult, Message, Usage
from tuochat.observability import ObservabilityRow, build_daily_rollups, retention_cutoff_iso

logger = logging.getLogger("tuochat.persistence")

SCHEMA_VERSION = 6

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT,
    archived INTEGER NOT NULL DEFAULT 0,
    resource_id TEXT,
    system_prompt TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    cwd TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    request_id TEXT,
    status TEXT NOT NULL DEFAULT 'complete',
    created_at TEXT NOT NULL,
    extras_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON messages(conversation_id, created_at);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    conversation_id UNINDEXED,
    message_id UNINDEXED,
    role UNINDEXED,
    created_at UNINDEXED
);

CREATE TABLE IF NOT EXISTS usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT REFERENCES conversations(id),
    message_id TEXT REFERENCES messages(id),
    input_tokens INTEGER,
    output_tokens INTEGER,
    model TEXT,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS observability_responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NULL,
    message_id TEXT NULL,
    request_id TEXT NULL,
    provider TEXT NOT NULL,
    model TEXT NULL,
    status TEXT NOT NULL,
    request_started_at TEXT NOT NULL,
    first_token_at TEXT NULL,
    finished_at TEXT NOT NULL,
    request_tokens INTEGER NOT NULL,
    response_tokens INTEGER NULL,
    time_to_first_token_ms INTEGER NULL,
    total_response_ms INTEGER NOT NULL,
    time_per_token_ms REAL NULL,
    error_kind TEXT NULL
);

CREATE INDEX IF NOT EXISTS idx_obs_started_at
    ON observability_responses(request_started_at);

CREATE INDEX IF NOT EXISTS idx_obs_status_started_at
    ON observability_responses(status, request_started_at);

CREATE INDEX IF NOT EXISTS idx_obs_request_id
    ON observability_responses(request_id);

CREATE TABLE IF NOT EXISTS error_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at TEXT NOT NULL DEFAULT (datetime('now','utc')),
    level INTEGER NOT NULL,
    level_name TEXT NOT NULL,
    logger_name TEXT NOT NULL,
    message TEXT NOT NULL,
    exc_type TEXT NULL,
    exc_value TEXT NULL,
    exc_traceback TEXT NULL,
    filename TEXT NULL,
    lineno INTEGER NULL,
    func_name TEXT NULL
);

CREATE INDEX IF NOT EXISTS idx_error_log_recorded_at
    ON error_log(recorded_at);

CREATE INDEX IF NOT EXISTS idx_error_log_level
    ON error_log(level);
"""


class ConversationStore:
    """SQLite-backed storage for conversations and messages."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.closed = False
        self.connections: dict[int, sqlite3.Connection] = {}
        self.connections_lock = threading.RLock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    @property
    def conn(self) -> sqlite3.Connection:
        """Return the SQLite connection for the current thread."""
        if self.closed:
            raise RuntimeError("ConversationStore is closed")
        thread_id = threading.get_ident()
        with self.connections_lock:
            existing = self.connections.get(thread_id)
            if existing is not None:
                return existing
            connection = sqlite3.connect(str(self.db_path), check_same_thread=False)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            self.connections[thread_id] = connection
            return connection

    def migrate(self) -> None:
        """Apply schema migrations."""
        cur = self.conn.cursor()
        # Check if schema_version table exists
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'")
        if cur.fetchone() is None:
            # Fresh database — apply full schema
            self.conn.executescript(SCHEMA_SQL)
            cur.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
            self.conn.commit()
            logger.debug("Created database schema v%d", SCHEMA_VERSION)
            return

        cur.execute("SELECT MAX(version) FROM schema_version")
        row = cur.fetchone()
        current = row[0] if row else 0

        if current < SCHEMA_VERSION:
            # Future migrations go here
            logger.info("Migrating database from v%d to v%d", current, SCHEMA_VERSION)
            if current < 2:
                self.conn.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                           content,
                           conversation_id UNINDEXED,
                           message_id UNINDEXED,
                           role UNINDEXED,
                           created_at UNINDEXED
                       )""")
                self.rebuild_message_index()
            if current < 3:
                self.conn.execute("ALTER TABLE conversations ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
            if current < 4:
                self.conn.executescript("""
                    CREATE TABLE IF NOT EXISTS observability_responses (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        conversation_id TEXT NULL,
                        message_id TEXT NULL,
                        request_id TEXT NULL,
                        provider TEXT NOT NULL,
                        model TEXT NULL,
                        status TEXT NOT NULL,
                        request_started_at TEXT NOT NULL,
                        first_token_at TEXT NULL,
                        finished_at TEXT NOT NULL,
                        request_tokens INTEGER NOT NULL,
                        response_tokens INTEGER NULL,
                        time_to_first_token_ms INTEGER NULL,
                        total_response_ms INTEGER NOT NULL,
                        time_per_token_ms REAL NULL,
                        error_kind TEXT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_obs_started_at
                        ON observability_responses(request_started_at);
                    CREATE INDEX IF NOT EXISTS idx_obs_status_started_at
                        ON observability_responses(status, request_started_at);
                    CREATE INDEX IF NOT EXISTS idx_obs_request_id
                        ON observability_responses(request_id);
                """)
            if current < 5:
                self.conn.executescript("""
                    CREATE TABLE IF NOT EXISTS error_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        recorded_at TEXT NOT NULL DEFAULT (datetime('now','utc')),
                        level INTEGER NOT NULL,
                        level_name TEXT NOT NULL,
                        logger_name TEXT NOT NULL,
                        message TEXT NOT NULL,
                        exc_type TEXT NULL,
                        exc_value TEXT NULL,
                        exc_traceback TEXT NULL,
                        filename TEXT NULL,
                        lineno INTEGER NULL,
                        func_name TEXT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_error_log_recorded_at
                        ON error_log(recorded_at);
                    CREATE INDEX IF NOT EXISTS idx_error_log_level
                        ON error_log(level);
                """)
            if current < 6:
                self.conn.execute("ALTER TABLE conversations ADD COLUMN cwd TEXT")
            cur.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
            self.conn.commit()

        self.ensure_message_index()

    def ensure_message_index(self) -> None:
        """Ensure the full-text index exists and can answer searches."""
        self.conn.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                   content,
                   conversation_id UNINDEXED,
                   message_id UNINDEXED,
                   role UNINDEXED,
                   created_at UNINDEXED
               )""")
        row = self.conn.execute("SELECT COUNT(*) AS count FROM messages_fts").fetchone()
        if row is not None and row["count"] == 0:
            self.rebuild_message_index()
            self.conn.commit()

    def rebuild_message_index(self) -> None:
        """Rebuild the FTS index from the canonical messages table."""
        self.conn.execute("DELETE FROM messages_fts")
        self.conn.execute("""INSERT INTO messages_fts(rowid, content, conversation_id, message_id, role, created_at)
               SELECT rowid, content, conversation_id, id, role, created_at
               FROM messages""")

    def close(self) -> None:
        """Close the database connection."""
        with self.connections_lock:
            if self.closed:
                return
            self.closed = True
            connections = list(self.connections.values())
            self.connections.clear()
        for connection in connections:
            connection.close()

    def __enter__(self) -> ConversationStore:
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.close()

    # --- Conversations ---

    def save_conversation(self, conv: Conversation) -> None:
        """Insert or update a conversation."""
        self.conn.execute(
            """INSERT INTO conversations (id, title, archived, resource_id, system_prompt, created_at, updated_at, cwd)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 title=excluded.title,
                 archived=excluded.archived,
                 resource_id=excluded.resource_id,
                 system_prompt=excluded.system_prompt,
                 updated_at=excluded.updated_at,
                 cwd=excluded.cwd""",
            (
                conv.id,
                conv.title,
                int(conv.archived),
                conv.resource_id,
                conv.system_prompt,
                conv.created_at,
                conv.updated_at,
                conv.cwd,
            ),
        )
        self.conn.commit()

    def get_conversation(self, conv_id: str) -> Conversation | None:
        """Load a conversation by ID (without messages)."""
        cur = self.conn.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,))
        row = cur.fetchone()
        if row is None:
            return None
        return Conversation.from_dict(dict(row))

    def list_conversations(self, limit: int = 50, *, archived: bool = False) -> list[Conversation]:
        """List conversations ordered by most recently updated."""
        cur = self.conn.execute(
            "SELECT * FROM conversations WHERE archived = ? ORDER BY updated_at DESC LIMIT ?",
            (int(archived), limit),
        )
        return [Conversation.from_dict(dict(row)) for row in cur.fetchall()]

    def list_archived_conversations(self, limit: int = 50) -> list[Conversation]:
        """List archived conversations ordered by most recently updated."""
        return self.list_conversations(limit=limit, archived=True)

    def list_expired_conversations(self, cutoff_iso: str, limit: int = 100) -> list[Conversation]:
        """List conversations older than the given ISO timestamp."""
        cur = self.conn.execute(
            "SELECT * FROM conversations WHERE updated_at < ? ORDER BY updated_at ASC LIMIT ?",
            (cutoff_iso, limit),
        )
        return [Conversation.from_dict(dict(row)) for row in cur.fetchall()]

    def delete_conversation(self, conv_id: str) -> bool:
        """Delete a conversation and its messages."""
        self.conn.execute("DELETE FROM usage WHERE conversation_id = ?", (conv_id,))
        self.conn.execute("DELETE FROM messages_fts WHERE conversation_id = ?", (conv_id,))
        self.conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
        cur = self.conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def set_conversation_archived(self, conv_id: str, archived: bool) -> bool:
        """Set archived status for a conversation."""
        cur = self.conn.execute(
            "UPDATE conversations SET archived = ? WHERE id = ?",
            (int(archived), conv_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def unarchive_all_conversations(self) -> int:
        """Unarchive every archived conversation."""
        cur = self.conn.execute("UPDATE conversations SET archived = 0 WHERE archived = 1")
        self.conn.commit()
        return cur.rowcount

    # --- Messages ---

    def save_message(self, msg: Message) -> None:
        """Insert or update a message."""
        cur = self.conn.execute(
            """INSERT INTO messages (id, conversation_id, role, content, request_id, status, created_at, extras_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 content=excluded.content,
                 status=excluded.status,
                 extras_json=excluded.extras_json""",
            (
                msg.id,
                msg.conversation_id,
                msg.role,
                msg.content,
                msg.request_id,
                msg.status,
                msg.created_at,
                msg.extras_json,
            ),
        )
        # Use lastrowid on INSERT; fall back to a lookup on UPDATE (lastrowid is 0 on conflict)
        rowid = cur.lastrowid or None
        if not rowid:
            row = self.conn.execute("SELECT rowid FROM messages WHERE id = ?", (msg.id,)).fetchone()
            rowid = row["rowid"] if row else None
        if rowid:
            self.conn.execute("DELETE FROM messages_fts WHERE rowid = ?", (rowid,))
            self.conn.execute(
                """INSERT INTO messages_fts(rowid, content, conversation_id, message_id, role, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    rowid,
                    msg.content,
                    msg.conversation_id,
                    msg.id,
                    msg.role,
                    msg.created_at,
                ),
            )
        self.conn.commit()

    def get_messages(self, conv_id: str) -> list[Message]:
        """Get all messages for a conversation, ordered by creation time."""
        cur = self.conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at",
            (conv_id,),
        )
        return [Message.from_dict(dict(row)) for row in cur.fetchall()]

    def search_conversations(
        self,
        query: str,
        *,
        limit: int = 20,
        title_filter: str | None = None,
        updated_after: str | None = None,
        updated_before: str | None = None,
    ) -> list[ConversationSearchResult]:
        """Search conversation messages with optional title and date filters."""
        text = query.strip()
        if not text:
            return []

        where = ["messages_fts MATCH ?", "conversations.archived = 0"]
        params: list[object] = [text]
        if title_filter:
            where.append("COALESCE(conversations.title, '') LIKE ?")
            params.append(f"%{title_filter}%")
        if updated_after:
            where.append("conversations.updated_at >= ?")
            params.append(updated_after)
        if updated_before:
            where.append("conversations.updated_at <= ?")
            params.append(updated_before)

        params.append(limit)
        sql = f"""
            SELECT
                conversations.id AS conversation_id,
                messages.id AS message_id,
                messages.role AS role,
                conversations.archived AS archived,
                conversations.title AS title,
                conversations.updated_at AS updated_at,
                messages.created_at AS created_at,
                snippet(messages_fts, 0, '[', ']', ' ... ', 12) AS snippet
            FROM messages_fts
            JOIN messages ON messages.id = messages_fts.message_id
            JOIN conversations ON conversations.id = messages_fts.conversation_id
            WHERE {' AND '.join(where)}
            ORDER BY bm25(messages_fts), conversations.updated_at DESC, messages.created_at DESC
            LIMIT ?
            """  # nosec B608
        cur = self.conn.execute(sql, params)
        return [ConversationSearchResult(**dict(row)) for row in cur.fetchall()]

    # --- Usage ---

    def save_usage(self, usage: Usage) -> None:
        """Record token usage."""
        self.conn.execute(
            """INSERT INTO usage (conversation_id, message_id, input_tokens, output_tokens, model, recorded_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                usage.conversation_id,
                usage.message_id,
                usage.input_tokens,
                usage.output_tokens,
                usage.model,
                usage.recorded_at,
            ),
        )
        self.conn.commit()

    def get_weekly_usage(self, week_start_iso: str) -> dict:
        """Return aggregated token usage since the given ISO timestamp (week start).

        Returns a dict with keys: input_tokens, output_tokens, total_tokens, turns.
        The caller is responsible for computing the week_start_iso (Sunday 00:00 UTC).
        """
        row = self.conn.execute(
            """SELECT
                COALESCE(SUM(input_tokens), 0) AS input_tokens,
                COALESCE(SUM(output_tokens), 0) AS output_tokens,
                COALESCE(SUM(COALESCE(input_tokens,0) + COALESCE(output_tokens,0)), 0) AS total_tokens,
                COUNT(*) AS turns
               FROM usage
               WHERE recorded_at >= ?""",
            (week_start_iso,),
        ).fetchone()
        if row is None:
            return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "turns": 0}
        return {
            "input_tokens": row["input_tokens"],
            "output_tokens": row["output_tokens"],
            "total_tokens": row["total_tokens"],
            "turns": row["turns"],
        }

    # --- Observability ---

    def save_observability_row(self, row: ObservabilityRow) -> None:
        """Insert one Duo response observability row."""
        self.conn.execute(
            """INSERT INTO observability_responses (
                conversation_id, message_id, request_id, provider, model, status,
                request_started_at, first_token_at, finished_at,
                request_tokens, response_tokens,
                time_to_first_token_ms, total_response_ms, time_per_token_ms,
                error_kind
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                row.conversation_id,
                row.message_id,
                row.request_id,
                row.provider,
                row.model,
                row.status,
                row.request_started_at,
                row.first_token_at,
                row.finished_at,
                row.request_tokens,
                row.response_tokens,
                row.time_to_first_token_ms,
                row.total_response_ms,
                row.time_per_token_ms,
                row.error_kind,
            ),
        )
        self.conn.commit()

    def get_observability_rows(self, since_iso: str) -> list[dict]:
        """Fetch raw observability rows since the given UTC ISO timestamp."""
        cur = self.conn.execute(
            "SELECT * FROM observability_responses WHERE request_started_at >= ? ORDER BY request_started_at",
            (since_iso,),
        )
        return [dict(r) for r in cur.fetchall()]

    def get_observability_rollups(self, since_iso: str) -> list:
        """Return daily rollup objects for the observability surfaces.

        Triggers lazy retention cleanup before reading.
        """
        self.cleanup_observability_retention()
        rows = self.get_observability_rows(since_iso)
        return build_daily_rollups(rows)

    def cleanup_observability_retention(self, days: int = 30) -> int:
        """Delete observability rows older than *days* days.  Idempotent."""
        cutoff = retention_cutoff_iso(days)
        cur = self.conn.execute(
            "DELETE FROM observability_responses WHERE request_started_at < ?",
            (cutoff,),
        )
        self.conn.commit()
        deleted = cur.rowcount
        if deleted:
            logger.debug("Cleaned up %d observability rows older than %d days", deleted, days)
        return deleted

    # --- Error log ---

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
        """Insert one error log entry."""
        self.conn.execute(
            """INSERT INTO error_log (
                recorded_at, level, level_name, logger_name, message,
                exc_type, exc_value, exc_traceback, filename, lineno, func_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                recorded_at,
                level,
                level_name,
                logger_name,
                message,
                exc_type,
                exc_value,
                exc_traceback,
                filename,
                lineno,
                func_name,
            ),
        )
        self.conn.commit()

    def get_error_log_entries(self, limit: int = 500, min_level: int = logging.WARNING) -> list[dict]:
        """Fetch error log entries at or above min_level, newest first.

        Triggers lazy retention cleanup before reading.
        """
        self.cleanup_error_log_retention()
        cur = self.conn.execute(
            "SELECT * FROM error_log WHERE level >= ? ORDER BY recorded_at DESC LIMIT ?",
            (min_level, limit),
        )
        return [dict(r) for r in cur.fetchall()]

    def delete_error_log_entry(self, entry_id: int) -> bool:
        """Delete a single error log entry by id. Returns True if a row was deleted."""
        cur = self.conn.execute("DELETE FROM error_log WHERE id = ?", (entry_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def clear_error_log(self) -> int:
        """Delete all error log entries. Returns the count deleted."""
        cur = self.conn.execute("DELETE FROM error_log")
        self.conn.commit()
        return cur.rowcount

    def cleanup_error_log_retention(self, days: int = 30) -> int:
        """Delete error log entries older than *days* days. Idempotent."""
        cutoff = retention_cutoff_iso(days)
        cur = self.conn.execute("DELETE FROM error_log WHERE recorded_at < ?", (cutoff,))
        self.conn.commit()
        deleted = cur.rowcount
        if deleted:
            logger.debug("Cleaned up %d error log entries older than %d days", deleted, days)
        return deleted

    # --- Export ---

    def export_markdown(self, conv_id: str) -> str | None:
        """Export a conversation as markdown."""
        conv = self.get_conversation(conv_id)
        if conv is None:
            return None

        messages = self.get_messages(conv_id)
        lines = [f"# {conv.title or 'Untitled Conversation'}", ""]
        if conv.system_prompt:
            lines.extend([f"**System prompt:** {conv.system_prompt}", ""])
        lines.append(f"*Started: {conv.created_at}*\n")

        for msg in messages:
            role_label = msg.role.capitalize()
            lines.append(f"## {role_label}")
            lines.append("")
            lines.append(msg.content)
            lines.append("")

        return "\n".join(lines)


class NullConversationStore:
    """Read-only no-op store used when local writes are disabled."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def close(self) -> None:
        """Close the store."""

    def __enter__(self) -> NullConversationStore:
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.close()

    def save_conversation(self, conv: Conversation) -> None:
        """No-op conversation save."""

    def get_conversation(self, conv_id: str) -> Conversation | None:
        """No saved conversations exist while writes are disabled."""
        _ = conv_id
        conversation: Conversation | None = None
        return conversation

    def list_conversations(self, limit: int = 50, *, archived: bool = False) -> list[Conversation]:
        """Return no conversations."""
        _ = (limit, archived)
        return []

    def list_archived_conversations(self, limit: int = 50) -> list[Conversation]:
        """Return no archived conversations."""
        _ = limit
        return []

    def list_expired_conversations(self, cutoff_iso: str, limit: int = 100) -> list[Conversation]:
        """Return no expired conversations."""
        _ = (cutoff_iso, limit)
        return []

    def delete_conversation(self, conv_id: str) -> bool:
        """Deletion is unavailable while writes are disabled."""
        _ = conv_id
        return False

    def set_conversation_archived(self, conv_id: str, archived: bool) -> bool:
        """Archiving is unavailable while writes are disabled."""
        _ = (conv_id, archived)
        return False

    def unarchive_all_conversations(self) -> int:
        """No archived conversations exist."""
        return 0

    def save_message(self, msg: Message) -> None:
        """No-op message save."""

    def get_messages(self, conv_id: str) -> list[Message]:
        """Return no persisted messages."""
        _ = conv_id
        return []

    def search_conversations(
        self,
        query: str,
        *,
        limit: int = 20,
        title_filter: str | None = None,
        updated_after: str | None = None,
        updated_before: str | None = None,
    ) -> list[ConversationSearchResult]:
        """Return no search results."""
        _ = (query, limit, title_filter, updated_after, updated_before)
        return []

    def save_usage(self, usage: Usage) -> None:
        """No-op usage save."""

    def get_weekly_usage(self, week_start_iso: str) -> dict:
        """Return empty usage totals."""
        _ = week_start_iso
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "turns": 0}

    def save_observability_row(self, row: ObservabilityRow) -> None:
        """No-op: observability is unavailable while writes are disabled."""

    def get_observability_rows(self, since_iso: str) -> list[dict]:
        """No observability rows while writes are disabled."""
        _ = since_iso
        return []

    def get_observability_rollups(self, since_iso: str) -> list:
        """No observability rollups while writes are disabled."""
        _ = since_iso
        return []

    def cleanup_observability_retention(self, days: int = 30) -> int:
        """No-op cleanup while writes are disabled."""
        _ = days
        return 0

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
        """No-op: error logging unavailable while writes are disabled."""

    def get_error_log_entries(self, limit: int = 500, min_level: int = logging.WARNING) -> list[dict]:
        """Return no error log entries while writes are disabled."""
        _ = (limit, min_level)
        return []

    def delete_error_log_entry(self, entry_id: int) -> bool:
        """Deletion unavailable while writes are disabled."""
        _ = entry_id
        return False

    def clear_error_log(self) -> int:
        """No-op clear while writes are disabled."""
        return 0

    def cleanup_error_log_retention(self, days: int = 30) -> int:
        """No-op cleanup while writes are disabled."""
        _ = days
        return 0

    def export_markdown(self, conv_id: str) -> str | None:
        """No exports are available without local persistence."""
        _ = conv_id
        markdown: str | None = None
        return markdown
