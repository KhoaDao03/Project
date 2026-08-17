"""Characterization tests for the revised Phase 8 SQLite ownership boundary."""

from __future__ import annotations

import sqlite3
import unittest
from datetime import datetime, timezone
from tempfile import TemporaryDirectory
from unittest.mock import patch

from elly.adapters.sqlite.connection import _SerializedConnection
from elly.adapters.sqlite_repository import SqliteSessionRepository
from elly.domain.enums import CloudMode, PersistenceMode
from elly.domain.models import AuditEvent, Message, SessionRecord
from elly.memory import ProfileItem

UTC = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)


class RevisedPhase8SqliteTests(unittest.TestCase):
    def test_file_database_keeps_wal_and_foreign_keys_enabled(self) -> None:
        with TemporaryDirectory() as directory:
            repository = SqliteSessionRepository(f"{directory}/phase8.db")
            try:
                self.assertEqual(
                    "wal", repository._conn.execute("PRAGMA journal_mode").fetchone()[0]
                )
                self.assertEqual(1, repository._conn.execute("PRAGMA foreign_keys").fetchone()[0])
            finally:
                repository.close()

    def test_facade_opens_one_connection_and_one_serialization_authority(self) -> None:
        original_connect = sqlite3.connect
        with patch(
            "elly.adapters.sqlite_repository.sqlite3.connect", wraps=original_connect
        ) as connect:
            repository = SqliteSessionRepository(":memory:")
            try:
                self.assertEqual(connect.call_count, 1)
                self.assertEqual(set(repository.__dict__), {"_db_path", "_conn"})
                self.assertIsInstance(repository._conn, _SerializedConnection)
                self.assertTrue(hasattr(repository._conn, "_lock"))
            finally:
                repository.close()

    def test_memory_database_is_shared_by_all_persistence_responsibilities(self) -> None:
        repository = SqliteSessionRepository(":memory:")
        try:
            repository.apply_migrations()
            session = SessionRecord(
                "phase8-session", PersistenceMode.STORE_WITH_RETENTION, CloudMode.LOCAL_ONLY, UTC
            )
            repository.create_session(session)
            repository.append_message(session.session_id, Message("user", "hello", UTC))
            repository.start_task("phase8-task", session.session_id, UTC)
            repository.append_audit(
                AuditEvent("phase8-task", session.session_id, "task.received", UTC)
            )
            repository.add_profile_item(
                ProfileItem(
                    "phase8-profile",
                    "timezone",
                    "UTC",
                    "owner_confirmed",
                    "local",
                    True,
                    UTC,
                    UTC,
                )
            )
            lease = repository.claim_operation(
                task_id="phase8-task",
                request_id="phase8-request",
                capability_id="phase8-capability",
                request_digest="phase8-digest",
                at=UTC,
            )

            self.assertTrue(lease.fresh)
            self.assertEqual("hello", repository.recent_messages(session.session_id, 1)[0].content)
            self.assertEqual("running", repository.task_status("phase8-task"))
            self.assertEqual(1, len(repository.audit_by_task("phase8-task")))
            self.assertEqual(1, len(repository.list_profile_items()))
            self.assertEqual(
                1,
                repository._conn.execute(
                    "SELECT COUNT(*) FROM task_operations WHERE operation_id=?",
                    (lease.operation_id,),
                ).fetchone()[0],
            )
        finally:
            repository.close()


if __name__ == "__main__":
    unittest.main()
