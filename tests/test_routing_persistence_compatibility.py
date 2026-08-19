"""Generic-route and additive routing-persistence compatibility coverage."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from elly.adapters.sqlite_repository import SqliteSessionRepository
from elly.application.routing.compatibility import ROUTING_CONTRACT_VERSION
from elly.domain.enums import (
    CloudMode,
    EpistemicStatus,
    OutcomeCode,
    PersistenceMode,
    Route,
    RouteReasonCode,
    TaskStatus,
    ValidationStatus,
)
from elly.domain.models import RouteDecision, SessionRecord, TaskResult

UTC = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


def _result(task_id: str = "task-phase5") -> TaskResult:
    return TaskResult(
        task_id=task_id,
        task_status=TaskStatus.COMPLETED,
        epistemic_status=EpistemicStatus.KNOWN,
        validation_status=ValidationStatus.VALIDATED,
        answer="safe answer",
        route_summary=Route.REGISTERED_CAPABILITY,
        outcome_code=OutcomeCode.SUCCESS,
        route_category=Route.REGISTERED_CAPABILITY,
        capability_id="security_review",
        operation="security.inspect",
        selection_reason_code=RouteReasonCode.CATALOG_SINGLE_MATCH.value,
        routing_contract_version=ROUTING_CONTRACT_VERSION,
    )


class Phase5RouteCompatibilityTests(unittest.TestCase):
    def test_generic_decision_has_no_legacy_route_view(self) -> None:
        decision = RouteDecision(
            route=Route.REGISTERED_CAPABILITY,
            reason_code=RouteReasonCode.CATALOG_SINGLE_MATCH,
            capability_id="security_review",
            operation="security.inspect",
        )

        self.assertIs(Route.REGISTERED_CAPABILITY, decision.generic_route)
        self.assertFalse(hasattr(decision, "compatibility_view"))
        self.assertFalse(hasattr(decision, "legacy_route"))

    def test_generic_routing_module_has_no_fixed_capability_route_map(self) -> None:
        source = Path("src/elly/application/routing/policy.py").read_text(encoding="utf-8")
        self.assertNotIn("_ROUTE_CAPABILITIES", source)
        self.assertNotIn('"web_research"', source)
        self.assertNotIn('"coding"', source)
        self.assertNotIn('"research"', source)


class Phase5PersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = SqliteSessionRepository(":memory:")
        self.repo.apply_migrations()
        self.repo.create_session(
            SessionRecord(
                "phase5-session",
                PersistenceMode.STORE_WITH_RETENTION,
                CloudMode.LOCAL_ONLY,
                UTC,
            )
        )
        self.addCleanup(self.repo.close)

    def test_new_result_persists_generic_route_and_selected_metadata(self) -> None:
        self.repo.start_task("task-phase5", "phase5-session", UTC)
        self.repo.save_task_result(_result(), UTC)

        raw = self.repo._conn.execute(
            "SELECT route, route_category, selected_capability_id, selected_operation, "
            "selection_reason_code, routing_contract_version FROM task_results"
        ).fetchone()
        self.assertEqual(
            (
                "registered_capability",
                "registered_capability",
                "security_review",
                "security.inspect",
                "CATALOG_SINGLE_MATCH",
                ROUTING_CONTRACT_VERSION,
            ),
            tuple(raw),
        )
        loaded = self.repo.get_task_result("task-phase5")
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertIs(Route.REGISTERED_CAPABILITY, loaded.route_summary)
        self.assertIs(Route.REGISTERED_CAPABILITY, loaded.route_category)
        self.assertEqual("security_review", loaded.capability_id)
        self.assertEqual("security.inspect", loaded.operation)

    def test_schema_v4_historical_result_migrates_without_rewriting_route(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "v4.db"
            connection = sqlite3.connect(path)
            try:
                connection.executescript(
                    """
                    CREATE TABLE schema_meta (id INTEGER PRIMARY KEY, version INTEGER NOT NULL);
                    INSERT INTO schema_meta VALUES (1, 4);
                    CREATE TABLE sessions (
                        session_id TEXT PRIMARY KEY, persistence_mode TEXT NOT NULL,
                        cloud_mode TEXT NOT NULL, created_at TEXT NOT NULL,
                        updated_at TEXT, version INTEGER NOT NULL DEFAULT 1
                    );
                    CREATE TABLE tasks (
                        task_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                        status TEXT NOT NULL, started_at TEXT NOT NULL, updated_at TEXT NOT NULL
                    );
                    CREATE TABLE audit_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
                        session_id TEXT NOT NULL, event_type TEXT NOT NULL, at TEXT NOT NULL,
                        route TEXT, task_status TEXT, error_class TEXT, detail TEXT NOT NULL
                    );
                    CREATE TABLE task_results (
                        task_id TEXT PRIMARY KEY, task_status TEXT NOT NULL,
                        outcome_code TEXT NOT NULL, epistemic_status TEXT NOT NULL,
                        validation_status TEXT NOT NULL, answer TEXT NOT NULL,
                        answer_retained INTEGER NOT NULL DEFAULT 1, route TEXT NOT NULL,
                        claims_json TEXT NOT NULL, citations_json TEXT NOT NULL,
                        partial_work_json TEXT NOT NULL, failures_json TEXT NOT NULL,
                        next_actions_json TEXT NOT NULL, updated_at TEXT NOT NULL
                    );
                    INSERT INTO sessions VALUES
                        ('legacy', 'store_with_retention', 'local_only',
                         '2026-08-15T12:00:00+00:00', '2026-08-15T12:00:00+00:00', 1);
                    INSERT INTO tasks VALUES
                        ('legacy-task', 'legacy', 'completed',
                         '2026-08-15T12:00:00+00:00', '2026-08-15T12:00:00+00:00');
                    INSERT INTO task_results VALUES
                        ('legacy-task', 'completed', 'success', 'known', 'validated',
                         'legacy answer', 1, 'web_research', '[]', '[]', '[]', '[]', '[]',
                         '2026-08-15T12:00:00+00:00');
                    """
                )
                connection.commit()
            finally:
                connection.close()

            repository = SqliteSessionRepository(str(path))
            self.addCleanup(repository.close)
            repository.apply_migrations()
            self.assertEqual(
                7,
                repository._conn.execute("SELECT version FROM schema_meta WHERE id=1").fetchone()[
                    0
                ],
            )
            loaded = repository.get_task_result("legacy-task")
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertIs(Route.WEB_RESEARCH, loaded.route_summary)
            self.assertIs(Route.REGISTERED_CAPABILITY, loaded.route_category)
            self.assertEqual("web_research", loaded.capability_id)
            self.assertEqual("research.search", loaded.operation)
            self.assertEqual("LEGACY_ROUTE", loaded.selection_reason_code)


if __name__ == "__main__":
    unittest.main()
