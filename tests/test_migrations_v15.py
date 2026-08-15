"""Representative V1 schema-v2 to V1.5 schema-v3 compatibility coverage."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from elly.adapters.audit_log import StructuredAuditLog
from elly.adapters.fake_generalist import FakeGeneralist
from elly.adapters.sqlite_repository import SqliteSessionRepository
from elly.adapters.system_clock import FixedClock
from elly.application.conversation import ConversationOrchestrator
from elly.domain.enums import CloudMode, PersistenceMode, TaskStatus
from elly.domain.errors import StorageFailureError
from elly.domain.models import Message, TaskRequest

UTC = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)
FIXTURE = Path(__file__).parent / "fixtures" / "v1_schema_v2.sql"


def _materialize_fixture(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(FIXTURE.read_text(encoding="utf-8"))
        connection.commit()
    finally:
        connection.close()


class V15MigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "representative-v1.db"
        _materialize_fixture(self.path)
        self.repository = SqliteSessionRepository(str(self.path))
        self.addCleanup(self.repository.close)

    def test_representative_v2_records_survive_v3_migration(self) -> None:
        self.repository.apply_migrations()

        self.assertEqual(
            self.repository.recent_messages("legacy-session", 10),
            [
                Message("user", "legacy question", UTC),
                Message("assistant", "legacy answer", UTC.replace(second=1)),
            ],
        )
        self.assertEqual("completed", self.repository.task_status("legacy-task"))
        self.assertEqual("Owner", self.repository.get_profile_item("profile-legacy").value)
        self.assertEqual(1, len(self.repository.audit_by_task("legacy-task")))
        self.assertEqual(
            ("https://example.com/legacy",),
            self.repository.task_sources("legacy-task"),
        )
        version = self.repository._conn.execute(
            "SELECT version FROM schema_meta WHERE id=1"
        ).fetchone()[0]
        self.assertEqual(3, version)
        self.repository.healthcheck()

    def test_complete_new_task_runs_on_the_migrated_database(self) -> None:
        self.repository.apply_migrations()
        orchestrator = ConversationOrchestrator(
            clock=FixedClock(UTC, step_seconds=1),
            generalist=FakeGeneralist(),
            repository=self.repository,
            audit=StructuredAuditLog(repository=self.repository),
            context_window=20,
            model_id="fake-generalist-v1",
            max_output_tokens=64,
        )

        outcome = orchestrator.handle(
            TaskRequest(
                request_id="migrated-request",
                session_id="legacy-session",
                text="Continue after migration",
                cloud_mode=CloudMode.LOCAL_ONLY,
                persistence_mode=PersistenceMode.STORE_WITH_RETENTION,
                submitted_at=UTC,
            )
        )

        self.assertIs(outcome.result.task_status, TaskStatus.COMPLETED)
        self.assertEqual("completed", self.repository.task_status(outcome.result.task_id))
        self.assertEqual(
            ["user", "assistant", "user", "assistant"],
            [item.role for item in self.repository.recent_messages("legacy-session", 10)],
        )

    def test_failed_v3_statement_rolls_back_and_does_not_advance_version(self) -> None:
        # This incompatible pre-existing name makes the V3 index statement fail.
        self.repository._conn.execute(
            "CREATE TABLE task_operations (operation_id TEXT PRIMARY KEY)"
        )
        self.repository._conn.commit()

        with self.assertRaises(StorageFailureError):
            self.repository.apply_migrations()

        version = self.repository._conn.execute(
            "SELECT version FROM schema_meta WHERE id=1"
        ).fetchone()[0]
        self.assertEqual(2, version)
        provenance = self.repository._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_provenance'"
        ).fetchone()
        self.assertIsNone(provenance)

    def test_future_schema_version_fails_startup(self) -> None:
        self.repository._conn.execute("UPDATE schema_meta SET version=99 WHERE id=1")
        self.repository._conn.commit()

        with self.assertRaisesRegex(StorageFailureError, "newer"):
            self.repository.apply_migrations()


if __name__ == "__main__":
    unittest.main()
