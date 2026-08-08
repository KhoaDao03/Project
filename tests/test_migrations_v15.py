"""Compatibility coverage for representative V1 data opened by V1.5."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from elly.adapters.sqlite_repository import SqliteSessionRepository
from elly.domain.enums import CloudMode, PersistenceMode
from elly.domain.models import Message, SessionRecord


UTC = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


class V15MigrationTests(unittest.TestCase):
    def test_representative_v1_database_retains_data_and_gets_v15_tables(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "v1.db"
            connection = sqlite3.connect(path)
            connection.executescript(
                """
                CREATE TABLE schema_meta (id INTEGER PRIMARY KEY CHECK (id = 1), version INTEGER NOT NULL);
                INSERT INTO schema_meta(id, version) VALUES (1, 1);
                CREATE TABLE sessions (
                    session_id TEXT PRIMARY KEY,
                    persistence_mode TEXT NOT NULL,
                    cloud_mode TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    stored_body INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE tasks (
                    task_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            connection.execute(
                "INSERT INTO sessions(session_id,persistence_mode,cloud_mode,created_at) VALUES (?,?,?,?)",
                ("legacy-session", PersistenceMode.STORE_WITH_RETENTION.value, CloudMode.LOCAL_ONLY.value, UTC.isoformat()),
            )
            connection.execute(
                "INSERT INTO messages(session_id,role,content,stored_body,created_at) VALUES (?,?,?,?,?)",
                ("legacy-session", "user", "legacy body", 1, UTC.isoformat()),
            )
            connection.commit()
            connection.close()

            repository = SqliteSessionRepository(str(path))
            self.addCleanup(repository.close)
            repository.apply_migrations()

            session = repository.get_session("legacy-session")
            self.assertIsNotNone(session)
            self.assertEqual(
                repository.recent_messages("legacy-session", 10),
                [Message("user", "legacy body", UTC)],
            )
            tables = {
                row[0]
                for row in repository._conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            self.assertIn("task_operations", tables)
            self.assertIn("task_provenance", tables)
            repository.healthcheck()

    def test_new_v15_task_can_use_migrated_database(self) -> None:
        repository = SqliteSessionRepository(":memory:")
        self.addCleanup(repository.close)
        repository.apply_migrations()
        session = SessionRecord(
            "new-session",
            PersistenceMode.STORE_WITH_RETENTION,
            CloudMode.LOCAL_ONLY,
            UTC,
        )
        repository.create_session(session)
        self.assertTrue(repository.start_task("new-task", session.session_id, UTC))
        lease = repository.claim_operation(
            task_id="new-task",
            request_id="new-request",
            capability_id="local_generalist",
            request_digest="c" * 64,
            at=UTC,
        )
        self.assertTrue(lease.fresh)


if __name__ == "__main__":
    unittest.main()
