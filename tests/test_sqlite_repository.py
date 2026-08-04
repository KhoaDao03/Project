"""Fake-backed behavior: SqliteSessionRepository (real adapter, in-memory DB).

Uses ":memory:" for a fast, isolated REAL SQLite database (DATA-001).
"""

from __future__ import annotations

import unittest
import tempfile
import os
from datetime import datetime, timezone

from elly.adapters.sqlite_repository import SqliteSessionRepository
from elly.domain.enums import CloudMode, PersistenceMode
from elly.domain.errors import StorageFailureError
from elly.domain.models import Message, SessionRecord
from elly.ports.repository import SessionRepositoryPort

UTC = datetime(2026, 8, 3, tzinfo=timezone.utc)


class SqliteRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = SqliteSessionRepository(":memory:")
        self.repo.apply_migrations()

    def tearDown(self) -> None:
        self.repo.close()

    def _session(self, mode: PersistenceMode) -> SessionRecord:
        rec = SessionRecord(
            session_id=f"s-{mode.value}",
            persistence_mode=mode,
            cloud_mode=CloudMode.LOCAL_ONLY,
            created_at=UTC,
        )
        self.repo.create_session(rec)
        return rec

    def test_satisfies_port(self) -> None:
        self.assertIsInstance(self.repo, SessionRepositoryPort)

    def test_migrations_idempotent(self) -> None:
        self.repo.apply_migrations()  # second run must not error

    def test_create_and_get_session(self) -> None:
        rec = self._session(PersistenceMode.STORE_WITH_RETENTION)
        got = self.repo.get_session(rec.session_id)
        assert got is not None
        self.assertEqual(got.persistence_mode, PersistenceMode.STORE_WITH_RETENTION)

    def test_stored_session_persists_body(self) -> None:
        rec = self._session(PersistenceMode.STORE_WITH_RETENTION)
        self.repo.append_message(rec.session_id, Message("user", "remember apples", UTC))
        msgs = self.repo.recent_messages(rec.session_id, 10)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].content, "remember apples")

    def test_no_store_session_does_not_persist_body(self) -> None:
        # DATA-001: no-store must leave no message body.
        rec = self._session(PersistenceMode.NO_STORE)
        self.repo.append_message(rec.session_id, Message("user", "secret diary", UTC))
        msgs = self.repo.recent_messages(rec.session_id, 10)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].content, "")  # body redacted

    def test_recent_messages_order_and_limit(self) -> None:
        rec = self._session(PersistenceMode.STORE_WITH_RETENTION)
        for i in range(5):
            self.repo.append_message(rec.session_id, Message("user", f"m{i}", UTC))
        msgs = self.repo.recent_messages(rec.session_id, 3)
        self.assertEqual([m.content for m in msgs], ["m2", "m3", "m4"])  # oldest-first of last 3

    def test_append_to_unknown_session_fails(self) -> None:
        with self.assertRaises(StorageFailureError):
            self.repo.append_message("nope", Message("user", "x", UTC))

    def test_restart_marks_running_tasks_interrupted_without_replay(self) -> None:
        rec = self._session(PersistenceMode.STORE_WITH_RETENTION)
        self.repo.start_task("task-running", rec.session_id, UTC)
        self.assertEqual(self.repo.mark_interrupted_tasks(UTC), 1)
        self.assertEqual(self.repo.task_status("task-running"), "interrupted")
        self.assertEqual(self.repo.mark_interrupted_tasks(UTC), 0)

    def test_reopen_reconciles_running_task_without_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "elly.db")
            first = SqliteSessionRepository(path)
            first.apply_migrations()
            rec = SessionRecord("persistent", PersistenceMode.STORE_WITH_RETENTION, CloudMode.LOCAL_ONLY, UTC)
            first.create_session(rec)
            first.start_task("task-restart", rec.session_id, UTC)
            first.close()

            second = SqliteSessionRepository(path)
            second.apply_migrations()
            self.assertEqual(second.mark_interrupted_tasks(UTC), 1)
            self.assertEqual(second.task_status("task-restart"), "interrupted")
            second.close()


if __name__ == "__main__":
    unittest.main()
