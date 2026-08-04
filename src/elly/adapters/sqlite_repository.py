"""SqliteSessionRepository — REAL M1 persistence (DESIGN §5.9, ADR-006).

Implements `ports.repository.SessionRepositoryPort` on stdlib sqlite3 (WAL mode).
This is a genuine capability in M1, not a fake: sessions and (when permitted)
message bodies are stored transactionally.

Privacy (DATA-001): when a session's PersistenceMode is NO_STORE, message BODIES
are not written — only a redacted placeholder row is kept so counts/metadata
remain consistent, and `recent_messages` returns the placeholder content as empty.

Failures: any sqlite error is wrapped as StorageFailureError (FR-006 fail-closed);
provider-specific exceptions never cross the port boundary.

Tests point `db_path` at ":memory:" for a fast, isolated real database.

Non-responsibilities: retention/expiry jobs and backups are OPS-004/M6, not here.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from ..domain.enums import CloudMode, PersistenceMode
from ..domain.errors import StorageFailureError
from ..domain.models import Message, SessionRecord

_SCHEMA_VERSION = 1

_MIGRATION_V1 = """
CREATE TABLE IF NOT EXISTS schema_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    session_id       TEXT PRIMARY KEY,
    persistence_mode TEXT NOT NULL,
    cloud_mode       TEXT NOT NULL,
    created_at       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES sessions(session_id),
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    stored_body INTEGER NOT NULL,   -- 1 if body persisted, 0 if redacted (no_store)
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
"""


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse(dt: str) -> datetime:
    return datetime.fromisoformat(dt).astimezone(timezone.utc)


class SqliteSessionRepository:
    """SQLite-backed session/message repository (real, M1)."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        try:
            # check_same_thread=False is safe here: M1 is single-process/single-user
            # and access is serialized by the CLI loop.
            self._conn = sqlite3.connect(db_path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA foreign_keys=ON;")
        except sqlite3.Error as exc:  # pragma: no cover - construction failure is rare
            raise StorageFailureError(f"cannot open database: {type(exc).__name__}") from exc

    def apply_migrations(self) -> None:
        try:
            with self._conn:
                self._conn.executescript(_MIGRATION_V1)
                row = self._conn.execute("SELECT version FROM schema_meta WHERE id=1").fetchone()
                if row is None:
                    self._conn.execute(
                        "INSERT INTO schema_meta (id, version) VALUES (1, ?)", (_SCHEMA_VERSION,)
                    )
        except sqlite3.Error as exc:
            raise StorageFailureError(f"migration failed: {type(exc).__name__}") from exc

    def create_session(self, session: SessionRecord) -> None:
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO sessions (session_id, persistence_mode, cloud_mode, created_at)"
                    " VALUES (?, ?, ?, ?)",
                    (
                        session.session_id,
                        session.persistence_mode.value,
                        session.cloud_mode.value,
                        _iso(session.created_at),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise StorageFailureError("session already exists") from exc
        except sqlite3.Error as exc:
            raise StorageFailureError(f"create_session failed: {type(exc).__name__}") from exc

    def get_session(self, session_id: str) -> SessionRecord | None:
        try:
            row = self._conn.execute(
                "SELECT session_id, persistence_mode, cloud_mode, created_at"
                " FROM sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise StorageFailureError(f"get_session failed: {type(exc).__name__}") from exc
        if row is None:
            return None
        return SessionRecord(
            session_id=row[0],
            persistence_mode=PersistenceMode(row[1]),
            cloud_mode=CloudMode(row[2]),
            created_at=_parse(row[3]),
        )

    def append_message(self, session_id: str, message: Message) -> None:
        session = self.get_session(session_id)
        if session is None:
            raise StorageFailureError("append to unknown session")
        no_store = session.persistence_mode is PersistenceMode.NO_STORE
        # DATA-001: never persist bodies for no-store sessions.
        stored_body = 0 if no_store else 1
        body = "" if no_store else message.content
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO messages (session_id, role, content, stored_body, created_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (session_id, message.role, body, stored_body, _iso(message.created_at)),
                )
        except sqlite3.Error as exc:
            raise StorageFailureError(f"append_message failed: {type(exc).__name__}") from exc

    def recent_messages(self, session_id: str, limit: int) -> list[Message]:
        if limit <= 0:
            return []
        try:
            rows = self._conn.execute(
                "SELECT role, content, stored_body, created_at FROM messages"
                " WHERE session_id=? ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        except sqlite3.Error as exc:
            raise StorageFailureError(f"recent_messages failed: {type(exc).__name__}") from exc
        # Return oldest-first. Redacted (no_store) rows surface as empty content.
        return [
            Message(role=r[0], content=r[1], created_at=_parse(r[3]))
            for r in reversed(rows)
        ]

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:  # pragma: no cover
            pass
