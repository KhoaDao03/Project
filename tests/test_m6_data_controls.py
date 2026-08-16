"""M6 acceptance tests: confirmed memory, durable trace, retention, backup."""

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import elly.adapters.sqlite_repository as sqlite_repository
from elly.adapters.audit_log import StructuredAuditLog
from elly.adapters.sqlite_repository import SqliteSessionRepository
from elly.domain.enums import CloudMode, PersistenceMode, Route, TaskStatus
from elly.domain.errors import StorageFailureError
from elly.domain.models import AuditEvent, Message, SessionRecord
from elly.memory import ProfileService
from elly.operations import BackupService

NOW = datetime(2026, 8, 4, tzinfo=timezone.utc)


class M6DataControlsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "elly.db")
        self.repo = SqliteSessionRepository(self.db)
        self.repo.apply_migrations()
        self.session = SessionRecord(
            "session-m6", PersistenceMode.STORE_WITH_RETENTION, CloudMode.LOCAL_ONLY, NOW
        )
        self.repo.create_session(self.session)

    def tearDown(self):
        self.repo.close()
        self.tmp.cleanup()

    def test_confirmed_profile_correction_deletion_and_expiry(self):
        profile = ProfileService(self.repo, type("Clock", (), {"now": lambda _: NOW})())
        profile.add(item_id="p1", key="timezone", value="UTC")
        profile.add(item_id="p2", key="secret", value="hidden", sensitivity="restricted")
        profile.add(item_id="p3", key="temporary", value="yes", expires_at=NOW + timedelta(days=1))
        self.assertEqual({"p1", "p2", "p3"}, {x.item_id for x in profile.list()})
        self.assertEqual({"p1", "p3"}, {x.item_id for x in profile.context_items()})
        profile.correct("p1", key="timezone", value="America/New_York")
        self.assertEqual(
            "America/New_York", next(x.value for x in profile.context_items() if x.item_id == "p1")
        )
        self.assertTrue(profile.delete("p1"))
        self.assertIsNone(self.repo.get_profile_item("p1"))
        self.assertEqual(
            1,
            self.repo._conn.execute(
                "SELECT COUNT(*) FROM profile_tombstones WHERE item_id='p1'"
            ).fetchone()[0],
        )
        self.assertEqual(1, self.repo.purge_expired_profile(NOW + timedelta(days=2)))

    def test_no_store_body_is_absent_after_restart(self):
        no_store = SessionRecord("session-ns", PersistenceMode.NO_STORE, CloudMode.LOCAL_ONLY, NOW)
        self.repo.create_session(no_store)
        self.repo.append_message(no_store.session_id, Message("user", "do not retain this", NOW))
        self.repo.close()
        reopened = SqliteSessionRepository(self.db)
        reopened.apply_migrations()
        self.assertEqual("", reopened.recent_messages(no_store.session_id, 1)[0].content)
        self.assertEqual(
            0,
            reopened._conn.execute(
                "SELECT stored_body FROM messages WHERE session_id='session-ns'"
            ).fetchone()[0],
        )
        reopened.close()

    def test_audit_and_sources_are_durable_and_redacted(self):
        audit = StructuredAuditLog(repository=self.repo)
        audit.append(
            AuditEvent(
                "task-m6",
                self.session.session_id,
                "task.completed",
                NOW,
                Route.LOCAL_GENERALIST,
                TaskStatus.COMPLETED,
                detail="short operational summary\n",
            )
        )
        self.repo.add_task_source("task-m6", "https://example.test/source", NOW)
        self.repo.close()
        reopened = SqliteSessionRepository(self.db)
        reopened.apply_migrations()
        event = reopened.audit_by_task("task-m6")[0]
        self.assertEqual("short operational summary", event.detail)
        self.assertNotIn("\n", event.detail)
        self.assertEqual(("https://example.test/source",), reopened.task_sources("task-m6"))
        reopened.close()

    def test_session_delete_removes_dependent_trace_and_messages(self):
        self.repo.append_message(self.session.session_id, Message("user", "body", NOW))
        self.repo.start_task("task-delete", self.session.session_id, NOW)
        self.repo.add_task_source("task-delete", "https://example.test", NOW)
        self.repo.append_audit(
            AuditEvent("task-delete", self.session.session_id, "task.received", NOW)
        )
        self.assertTrue(self.repo.delete_session(self.session.session_id))
        self.assertIsNone(self.repo.get_session(self.session.session_id))
        self.assertEqual([], self.repo.audit_by_task("task-delete"))
        self.assertEqual((), self.repo.task_sources("task-delete"))

    def test_retention_purges_sessions_sources_and_audit_at_independent_cutoffs(self):
        old = NOW - timedelta(days=100)
        recent = NOW - timedelta(days=2)
        old_session = SessionRecord(
            "session-old",
            PersistenceMode.STORE_WITH_RETENTION,
            CloudMode.LOCAL_ONLY,
            old,
        )
        self.repo.create_session(old_session)
        self.repo.append_message(old_session.session_id, Message("user", "expired", old))
        self.repo.start_task("task-old", old_session.session_id, old)
        self.repo.add_task_source("task-old", "https://example.test/old", old)
        self.repo.append_audit(AuditEvent("task-old", old_session.session_id, "old", old))
        self.repo.add_task_source("task-recent", "https://example.test/recent", recent)
        self.repo.append_audit(AuditEvent("task-recent", self.session.session_id, "recent", recent))

        self.assertEqual(1, self.repo.purge_task_sources(NOW - timedelta(days=7)))
        self.assertEqual(1, self.repo.purge_audit_events(NOW - timedelta(days=90)))
        self.assertEqual(1, self.repo.purge_sessions(NOW - timedelta(days=30)))
        self.assertIsNone(self.repo.get_session("session-old"))
        self.assertEqual(("https://example.test/recent",), self.repo.task_sources("task-recent"))
        self.assertEqual(1, len(self.repo.audit_by_task("task-recent")))

    def test_storage_healthcheck_requires_complete_schema(self):
        self.repo.healthcheck()
        self.repo._conn.execute("DROP TABLE audit_events")
        with self.assertRaises(StorageFailureError):
            self.repo.healthcheck()

    def test_backup_authentication_integrity_and_daily_marker(self):
        with TemporaryDirectory() as td:
            backup = BackupService(db_path=self.db, key="owner-test-key")
            path = backup.create(str(Path(td) / "manual.backup"))
            self.assertTrue(Path(path).exists())
            self.assertIsNotNone(backup.create_daily_if_due(str(Path(td) / "daily"), now=NOW))
            self.assertIsNone(backup.create_daily_if_due(str(Path(td) / "daily"), now=NOW))
            blob = bytearray(Path(path).read_bytes())
            blob[-1] ^= 1
            Path(path).write_bytes(blob)
            with self.assertRaises(StorageFailureError):
                backup.restore(path)

    def test_corrupt_profile_is_quarantined_and_base_store_remains_usable(self):
        self.repo._conn.execute("PRAGMA ignore_check_constraints=ON")
        self.repo._conn.execute(
            "INSERT INTO profile_items(item_id,key,value,source,sensitivity,confirmed,created_at,updated_at) VALUES ('bad','timezone','UTC','inferred','local',0,?,?)",
            (NOW.isoformat(), NOW.isoformat()),
        )
        profile = ProfileService(self.repo, type("Clock", (), {"now": lambda _: NOW})())
        self.assertEqual((), profile.load_startup())
        self.assertTrue(profile.degraded)
        self.assertEqual([], self.repo.list_profile_items())
        self.assertIsNotNone(self.repo.get_session(self.session.session_id))
        quarantine_tables = self.repo._conn.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE 'profile_items_quarantine_%'"
        ).fetchall()
        self.assertEqual(1, len(quarantine_tables))

    def test_failed_migration_rolls_back_and_keeps_version_one_usable(self):
        self.repo._conn.execute("DROP TABLE profile_items")
        self.repo._conn.execute("DELETE FROM schema_meta")
        self.repo._conn.execute("INSERT INTO schema_meta(id,version) VALUES (1,1)")
        original = sqlite_repository._MIGRATION_V2_STATEMENTS
        failing = (original[0], "CREATE TABLE profile_items (broken")
        with patch.object(sqlite_repository, "_MIGRATION_V2_STATEMENTS", failing):
            with self.assertRaises(StorageFailureError):
                self.repo.apply_migrations()
        self.assertEqual(
            1, self.repo._conn.execute("SELECT version FROM schema_meta WHERE id=1").fetchone()[0]
        )
        self.assertIsNotNone(self.repo.get_session(self.session.session_id))
        self.assertEqual(
            0,
            self.repo._conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name='profile_items'"
            ).fetchone()[0],
        )

    def test_backup_restore_reports_local_recovery_time(self):
        import time

        with TemporaryDirectory() as td:
            backup = BackupService(db_path=self.db, key="owner-test-key")
            path = backup.create(str(Path(td) / "recovery.backup"))
            self.repo.close()
            started = time.monotonic()
            backup.restore(path)
            elapsed = time.monotonic() - started
            reopened = SqliteSessionRepository(self.db)
            reopened.apply_migrations()
            self.assertIsNotNone(reopened.get_session(self.session.session_id))
            self.assertLess(elapsed, 5.0)
            reopened.close()


if __name__ == "__main__":
    unittest.main()
