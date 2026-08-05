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

M6 adds profile/session retention, durable redacted audit metadata, and source/task
metadata. Backup encryption remains in `operations.py` so storage transactions stay
inside this adapter.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ..domain.enums import CloudMode, PersistenceMode
from ..domain.errors import StorageFailureError
from ..domain.models import AuditEvent, Message, SessionRecord
from ..memory import ProfileItem

_SCHEMA_VERSION = 2

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
CREATE TABLE IF NOT EXISTS tasks (
    task_id    TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    status     TEXT NOT NULL,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
"""

_MIGRATION_V2 = """
CREATE TABLE IF NOT EXISTS profile_items (
    item_id TEXT PRIMARY KEY, key TEXT NOT NULL, value TEXT NOT NULL,
    source TEXT NOT NULL, sensitivity TEXT NOT NULL, confirmed INTEGER NOT NULL CHECK (confirmed=1),
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, expires_at TEXT
);
CREATE TABLE IF NOT EXISTS profile_tombstones (
    item_id TEXT PRIMARY KEY, deleted_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, session_id TEXT NOT NULL,
    event_type TEXT NOT NULL, at TEXT NOT NULL, route TEXT, task_status TEXT,
    error_class TEXT, detail TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_task ON audit_events(task_id, id);
CREATE TABLE IF NOT EXISTS task_sources (
    task_id TEXT NOT NULL, source TEXT NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY(task_id, source)
);
"""
_MIGRATION_V2_STATEMENTS = tuple(statement.strip() for statement in _MIGRATION_V2.split(";") if statement.strip())
_PROFILE_TABLES = {
    "profile_items": """CREATE TABLE profile_items (
        item_id TEXT PRIMARY KEY, key TEXT NOT NULL, value TEXT NOT NULL,
        source TEXT NOT NULL, sensitivity TEXT NOT NULL, confirmed INTEGER NOT NULL CHECK (confirmed=1),
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, expires_at TEXT
    )""",
    "profile_tombstones": """CREATE TABLE profile_tombstones (
        item_id TEXT PRIMARY KEY, deleted_at TEXT NOT NULL
    )""",
}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse(dt: str) -> datetime:
    return datetime.fromisoformat(dt).astimezone(timezone.utc)


class SqliteSessionRepository:
    """SQLite-backed session/message repository (real, M1)."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        try:
            if db_path != ":memory:":
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            # check_same_thread=False is safe here: M1 is single-process/single-user
            # and access is serialized by the CLI loop.
            self._conn = sqlite3.connect(db_path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA foreign_keys=ON;")
        except sqlite3.Error as exc:  # pragma: no cover - construction failure is rare
            raise StorageFailureError(f"cannot open database: {type(exc).__name__}") from exc

    def apply_migrations(self) -> None:
        try:
            # V1 creates the original database when needed. V2 is executed one
            # statement at a time inside an explicit transaction: a failed step
            # rolls back and the schema_meta version is not advanced.
            self._conn.executescript(_MIGRATION_V1)
            row = self._conn.execute("SELECT version FROM schema_meta WHERE id=1").fetchone()
            if row is None or row[0] < _SCHEMA_VERSION:
                self._conn.execute("BEGIN")
                try:
                    for statement in _MIGRATION_V2_STATEMENTS:
                        self._conn.execute(statement)
                    if row is None:
                        self._conn.execute(
                            "INSERT INTO schema_meta (id, version) VALUES (1, ?)", (_SCHEMA_VERSION,)
                        )
                    else:
                        self._conn.execute("UPDATE schema_meta SET version=? WHERE id=1", (_SCHEMA_VERSION,))
                    self._conn.commit()
                except sqlite3.Error:
                    self._conn.rollback()
                    raise
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

    def start_task(self, task_id: str, session_id: str, at: datetime) -> None:
        """Record an in-flight task; restart reconciliation never replays it."""
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO tasks(task_id, session_id, status, started_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (task_id, session_id, "running", _iso(at), _iso(at)),
                )
        except sqlite3.Error as exc:
            raise StorageFailureError(f"start_task failed: {type(exc).__name__}") from exc

    def finish_task(self, task_id: str, status: str, at: datetime) -> None:
        try:
            with self._conn:
                self._conn.execute(
                    "UPDATE tasks SET status=?, updated_at=? WHERE task_id=?",
                    (status, _iso(at), task_id),
                )
        except sqlite3.Error as exc:
            raise StorageFailureError(f"finish_task failed: {type(exc).__name__}") from exc

    def mark_interrupted_tasks(self, at: datetime) -> int:
        """Mark prior running tasks interrupted; deliberately performs no replay."""
        try:
            with self._conn:
                cursor = self._conn.execute(
                    "UPDATE tasks SET status='interrupted', updated_at=? WHERE status='running'",
                    (_iso(at),),
                )
                return cursor.rowcount
        except sqlite3.Error as exc:
            raise StorageFailureError(f"reconcile tasks failed: {type(exc).__name__}") from exc

    def task_status(self, task_id: str) -> str | None:
        try:
            row = self._conn.execute("SELECT status FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        except sqlite3.Error as exc:
            raise StorageFailureError(f"task lookup failed: {type(exc).__name__}") from exc
        return row[0] if row else None

    # ---- M6 profile/data controls ---------------------------------------

    def add_profile_item(self, item: ProfileItem) -> None:
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO profile_items(item_id,key,value,source,sensitivity,confirmed,created_at,updated_at,expires_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (item.item_id, item.key, item.value, item.source, item.sensitivity, 1, _iso(item.created_at), _iso(item.updated_at), _iso(item.expires_at) if item.expires_at else None),
                )
        except sqlite3.IntegrityError as exc:
            raise StorageFailureError("profile item already exists") from exc
        except sqlite3.Error as exc:
            raise StorageFailureError(f"add profile failed: {type(exc).__name__}") from exc

    def list_profile_items(self) -> list[ProfileItem]:
        try:
            rows = self._conn.execute("SELECT item_id,key,value,source,sensitivity,confirmed,created_at,updated_at,expires_at FROM profile_items ORDER BY key,item_id").fetchall()
            return [ProfileItem(r[0], r[1], r[2], r[3], r[4], bool(r[5]), _parse(r[6]), _parse(r[7]), _parse(r[8]) if r[8] else None) for r in rows]
        except sqlite3.Error as exc:
            raise StorageFailureError(f"list profile failed: {type(exc).__name__}") from exc

    def get_profile_item(self, item_id: str) -> ProfileItem | None:
        return next((item for item in self.list_profile_items() if item.item_id == item_id), None)

    def update_profile_item(self, item: ProfileItem) -> None:
        try:
            with self._conn:
                cursor = self._conn.execute(
                    "UPDATE profile_items SET key=?,value=?,sensitivity=?,updated_at=?,expires_at=? WHERE item_id=?",
                    (item.key, item.value, item.sensitivity, _iso(item.updated_at), _iso(item.expires_at) if item.expires_at else None, item.item_id),
                )
                if cursor.rowcount != 1:
                    raise StorageFailureError("profile item not found")
        except sqlite3.Error as exc:
            raise StorageFailureError(f"update profile failed: {type(exc).__name__}") from exc

    def delete_profile_item(self, item_id: str, at: datetime) -> bool:
        try:
            with self._conn:
                cursor = self._conn.execute("DELETE FROM profile_items WHERE item_id=?", (item_id,))
                if cursor.rowcount:
                    self._conn.execute("INSERT OR REPLACE INTO profile_tombstones(item_id,deleted_at) VALUES (?,?)", (item_id, _iso(at)))
                    return True
                return False
        except sqlite3.Error as exc:
            raise StorageFailureError(f"delete profile failed: {type(exc).__name__}") from exc

    def purge_expired_profile(self, now: datetime) -> int:
        try:
            with self._conn:
                cursor = self._conn.execute("DELETE FROM profile_items WHERE expires_at IS NOT NULL AND expires_at <= ?", (_iso(now),))
                return cursor.rowcount
        except sqlite3.Error as exc:
            raise StorageFailureError(f"purge profile failed: {type(exc).__name__}") from exc

    def quarantine_profile_store(self, at: datetime) -> str:
        """Move corrupt profile tables aside and recreate empty profile tables.

        Only profile tables are isolated; sessions, tasks, audit records, and
        versioned behavior remain available. The quarantine name contains only
        UTC digits, so it is safe to interpolate as an SQLite identifier.
        """
        suffix = at.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        try:
            with self._conn:
                for name, create_sql in _PROFILE_TABLES.items():
                    exists = self._conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
                    ).fetchone()
                    if exists:
                        quarantine = f"{name}_quarantine_{suffix}"
                        self._conn.execute(f'ALTER TABLE "{name}" RENAME TO "{quarantine}"')
                    self._conn.execute(create_sql)
            return suffix
        except sqlite3.Error as exc:
            raise StorageFailureError(f"profile quarantine failed: {type(exc).__name__}") from exc

    def list_sessions(self) -> list[SessionRecord]:
        try:
            rows = self._conn.execute("SELECT session_id,persistence_mode,cloud_mode,created_at FROM sessions ORDER BY created_at").fetchall()
            return [SessionRecord(r[0], PersistenceMode(r[1]), CloudMode(r[2]), _parse(r[3])) for r in rows]
        except sqlite3.Error as exc:
            raise StorageFailureError(f"list sessions failed: {type(exc).__name__}") from exc

    def delete_session(self, session_id: str) -> bool:
        try:
            with self._conn:
                # Foreign keys are enabled; delete dependents explicitly so
                # user-requested deletion is complete and transactional.
                self._conn.execute("DELETE FROM task_sources WHERE task_id IN (SELECT task_id FROM tasks WHERE session_id=?)", (session_id,))
                self._conn.execute("DELETE FROM audit_events WHERE session_id=?", (session_id,))
                self._conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
                self._conn.execute("DELETE FROM tasks WHERE session_id=?", (session_id,))
                cursor = self._conn.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
                return bool(cursor.rowcount)
        except sqlite3.Error as exc:
            raise StorageFailureError(f"delete session failed: {type(exc).__name__}") from exc

    def purge_sessions(self, before: datetime) -> int:
        """Delete expired sessions and all dependent task, source, and audit rows."""
        try:
            with self._conn:
                rows = self._conn.execute("SELECT session_id FROM sessions WHERE created_at < ?", (_iso(before),)).fetchall()
                for (session_id,) in rows:
                    self._conn.execute(
                        "DELETE FROM task_sources WHERE task_id IN "
                        "(SELECT task_id FROM tasks WHERE session_id=?)", (session_id,)
                    )
                    self._conn.execute("DELETE FROM audit_events WHERE session_id=?", (session_id,))
                    self._conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
                    self._conn.execute("DELETE FROM tasks WHERE session_id=?", (session_id,))
                    self._conn.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
                return len(rows)
        except sqlite3.Error as exc:
            raise StorageFailureError(f"purge sessions failed: {type(exc).__name__}") from exc

    def purge_task_sources(self, before: datetime) -> int:
        """Delete source/evidence metadata older than DEC-OQ-08 retention."""
        try:
            with self._conn:
                cursor = self._conn.execute(
                    "DELETE FROM task_sources WHERE created_at < ?", (_iso(before),)
                )
                return cursor.rowcount
        except sqlite3.Error as exc:
            raise StorageFailureError(f"purge sources failed: {type(exc).__name__}") from exc

    def purge_audit_events(self, before: datetime) -> int:
        """Delete redacted audit metadata older than DEC-OQ-08 retention."""
        try:
            with self._conn:
                cursor = self._conn.execute(
                    "DELETE FROM audit_events WHERE at < ?", (_iso(before),)
                )
                return cursor.rowcount
        except sqlite3.Error as exc:
            raise StorageFailureError(f"purge audit failed: {type(exc).__name__}") from exc

    def healthcheck(self) -> None:
        """Verify the connection and every required schema-v2 table without mutation."""
        required = {
            "sessions", "messages", "tasks", "profile_items",
            "audit_events", "task_sources",
        }
        try:
            self._conn.execute("SELECT 1").fetchone()
            rows = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        except sqlite3.Error as exc:
            raise StorageFailureError(f"storage healthcheck failed: {type(exc).__name__}") from exc
        missing = required - {row[0] for row in rows}
        if missing:
            raise StorageFailureError("storage healthcheck found an incomplete schema")

    # ---- M6 durable trace/source metadata -------------------------------

    def append_audit(self, event: AuditEvent) -> None:
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO audit_events(task_id,session_id,event_type,at,route,task_status,error_class,detail) VALUES (?,?,?,?,?,?,?,?)",
                    (event.task_id, event.session_id, event.event_type, _iso(event.at), event.route.value if event.route else None, event.task_status.value if event.task_status else None, event.error_class.value if event.error_class else None, event.detail),
                )
        except sqlite3.Error as exc:
            raise StorageFailureError(f"append audit failed: {type(exc).__name__}") from exc

    def audit_by_task(self, task_id: str) -> list[AuditEvent]:
        try:
            from ..domain.enums import ErrorClass, Route, TaskStatus
            rows = self._conn.execute("SELECT task_id,session_id,event_type,at,route,task_status,error_class,detail FROM audit_events WHERE task_id=? ORDER BY id", (task_id,)).fetchall()
            return [AuditEvent(r[0], r[1], r[2], _parse(r[3]), Route(r[4]) if r[4] else None, TaskStatus(r[5]) if r[5] else None, ErrorClass(r[6]) if r[6] else None, r[7]) for r in rows]
        except sqlite3.Error as exc:
            raise StorageFailureError(f"query audit failed: {type(exc).__name__}") from exc

    def add_task_source(self, task_id: str, source: str, at: datetime) -> None:
        try:
            with self._conn:
                self._conn.execute("INSERT OR IGNORE INTO task_sources(task_id,source,created_at) VALUES (?,?,?)", (task_id, source, _iso(at)))
        except sqlite3.Error as exc:
            raise StorageFailureError(f"add source failed: {type(exc).__name__}") from exc

    def task_sources(self, task_id: str) -> tuple[str, ...]:
        try:
            return tuple(row[0] for row in self._conn.execute("SELECT source FROM task_sources WHERE task_id=? ORDER BY source", (task_id,)).fetchall())
        except sqlite3.Error as exc:
            raise StorageFailureError(f"query sources failed: {type(exc).__name__}") from exc

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
