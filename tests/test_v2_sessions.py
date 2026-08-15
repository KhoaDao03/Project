"""Phase 1 durable session and compare-and-set behavior."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from elly.adapters.sqlite_repository import SqliteSessionRepository
from elly.domain.enums import CloudMode, PersistenceMode
from elly.domain.errors import ConflictError
from elly.domain.models import AuditEvent, SessionRecord

UTC = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


class V2SessionPersistenceTests(unittest.TestCase):
    def test_new_session_has_version_and_updated_at(self) -> None:
        repository = SqliteSessionRepository(":memory:")
        repository.apply_migrations()
        try:
            session = SessionRecord(
                "phase1-session",
                PersistenceMode.STORE_WITH_RETENTION,
                CloudMode.LOCAL_ONLY,
                UTC,
            )
            repository.create_session(session)
            loaded = repository.get_session(session.session_id)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(1, loaded.version)
            self.assertEqual(UTC, loaded.updated_at)
        finally:
            repository.close()

    def test_mode_update_is_atomic_and_survives_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "elly.db"
            repository = SqliteSessionRepository(str(path))
            repository.apply_migrations()
            repository.create_session(
                SessionRecord(
                    "phase1-session",
                    PersistenceMode.STORE_WITH_RETENTION,
                    CloudMode.LOCAL_ONLY,
                    UTC,
                )
            )
            audit = AuditEvent(
                task_id="session:phase1-session",
                session_id="phase1-session",
                event_type="session.mode_change_succeeded",
                at=UTC + timedelta(seconds=1),
                detail="previous=local_only new=cloud_permitted version=1",
            )
            updated = repository.update_cloud_mode(
                "phase1-session", 1, CloudMode.CLOUD_PERMITTED, UTC + timedelta(seconds=1), audit
            )
            self.assertEqual(CloudMode.CLOUD_PERMITTED, updated.cloud_mode)
            self.assertEqual(2, updated.version)
            self.assertEqual(["session.mode_change_succeeded"], [e.event_type for e in repository.audit_by_task("session:phase1-session")])
            repository.close()

            reopened = SqliteSessionRepository(str(path))
            reopened.apply_migrations()
            try:
                loaded = reopened.get_session("phase1-session")
                self.assertIsNotNone(loaded)
                assert loaded is not None
                self.assertEqual(CloudMode.CLOUD_PERMITTED, loaded.cloud_mode)
                self.assertEqual(2, loaded.version)
                self.assertEqual(UTC + timedelta(seconds=1), loaded.updated_at)
            finally:
                reopened.close()

    def test_stale_mode_update_is_rejected_without_overwrite_or_audit(self) -> None:
        repository = SqliteSessionRepository(":memory:")
        repository.apply_migrations()
        repository.create_session(
            SessionRecord(
                "phase1-session",
                PersistenceMode.STORE_WITH_RETENTION,
                CloudMode.LOCAL_ONLY,
                UTC,
            )
        )
        repository.update_cloud_mode(
            "phase1-session", 1, CloudMode.CLOUD_PERMITTED, UTC + timedelta(seconds=1)
        )
        with self.assertRaises(ConflictError):
            repository.update_cloud_mode(
                "phase1-session",
                1,
                CloudMode.LOCAL_ONLY,
                UTC + timedelta(seconds=2),
                AuditEvent(
                    "session:phase1-session",
                    "phase1-session",
                    "session.mode_change_succeeded",
                    UTC + timedelta(seconds=2),
                    detail="must not be written",
                ),
            )
        loaded = repository.get_session("phase1-session")
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(CloudMode.CLOUD_PERMITTED, loaded.cloud_mode)
        self.assertEqual(2, loaded.version)
        self.assertEqual([], repository.audit_by_task("session:phase1-session"))
        repository.close()


if __name__ == "__main__":
    unittest.main()
