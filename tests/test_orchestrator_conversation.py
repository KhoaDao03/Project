"""Behavior spec — ConversationOrchestrator.handle (M1, UC-01).

Status: ACTIVE (handle implemented 2026-08-03). These encode the required M1
conversation behavior:
- success -> COMPLETED / INFERRED / VALIDATED, assistant turn persisted, audit
  records a completed event;
- provider/validation failure -> BLOCKED, NO fabricated success, failure audited;
- no-store -> assistant body not persisted;
- multi-turn -> context manifest reflects prior turns.

They assert observable outcomes (statuses, persistence, audit correlation), not
exact audit event names, so the sequencing remains free to evolve.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from elly.adapters.audit_log import StructuredAuditLog
from elly.adapters.fake_generalist import FailureMode, FakeGeneralist
from elly.adapters.sqlite_repository import SqliteSessionRepository
from elly.adapters.system_clock import FixedClock
from elly.application.conversation import ConversationOrchestrator
from elly.domain.enums import (
    CloudMode,
    EpistemicStatus,
    PersistenceMode,
    Route,
    TaskStatus,
    ValidationStatus,
)
from elly.domain.models import SessionRecord, TaskRequest

UTC = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


def _orchestrator(
    *, failure: FailureMode = FailureMode.NONE, persistence: PersistenceMode
) -> tuple[ConversationOrchestrator, SqliteSessionRepository, StructuredAuditLog, str]:
    repo = SqliteSessionRepository(":memory:")
    repo.apply_migrations()
    session = SessionRecord(
        session_id="s-owner-exercise",
        persistence_mode=persistence,
        cloud_mode=CloudMode.LOCAL_ONLY,
        created_at=UTC,
    )
    repo.create_session(session)
    audit = StructuredAuditLog()
    orch = ConversationOrchestrator(
        clock=FixedClock(UTC, step_seconds=1),
        generalist=FakeGeneralist(failure=failure),
        repository=repo,
        audit=audit,
        context_window=20,
        model_id="fake-generalist-v1",
        max_output_tokens=64,
    )
    return orch, repo, audit, session.session_id


def _request(session_id: str, text: str) -> TaskRequest:
    return TaskRequest(
        request_id=f"req-{text[:6]}",
        session_id=session_id,
        text=text,
        cloud_mode=CloudMode.LOCAL_ONLY,
        persistence_mode=PersistenceMode.STORE_WITH_RETENTION,
        submitted_at=UTC,
    )


class OrchestratorConversationTests(unittest.TestCase):
    def test_success_three_axis_and_persistence(self) -> None:
        orch, repo, audit, sid = _orchestrator(persistence=PersistenceMode.STORE_WITH_RETENTION)
        self.addCleanup(repo.close)
        outcome = orch.handle(_request(sid, "hello"))
        self.assertIs(outcome.result.task_status, TaskStatus.COMPLETED)
        self.assertIs(outcome.result.epistemic_status, EpistemicStatus.INFERRED)
        self.assertIs(outcome.result.validation_status, ValidationStatus.VALIDATED)
        self.assertIs(outcome.result.route_summary, Route.LOCAL_GENERALIST)
        self.assertTrue(outcome.result.answer.startswith("[fake-generalist]"))
        # user + assistant persisted
        msgs = repo.recent_messages(sid, 10)
        self.assertEqual([m.role for m in msgs], ["user", "assistant"])
        # a terminal completed event is recorded
        self.assertTrue(any(e.task_status is TaskStatus.COMPLETED for e in audit.by_task(outcome.result.task_id)))

    def test_provider_failure_blocks_without_fake_success(self) -> None:
        orch, repo, audit, sid = _orchestrator(
            failure=FailureMode.TRANSIENT, persistence=PersistenceMode.STORE_WITH_RETENTION
        )
        self.addCleanup(repo.close)
        outcome = orch.handle(_request(sid, "hello"))
        self.assertIs(outcome.result.task_status, TaskStatus.BLOCKED)
        self.assertIs(outcome.result.epistemic_status, EpistemicStatus.BLOCKED)
        self.assertEqual(outcome.result.answer, "")
        self.assertTrue(outcome.result.failures)
        # no completed event on failure
        self.assertFalse(any(e.task_status is TaskStatus.COMPLETED for e in audit.by_task(outcome.result.task_id)))

    def test_no_store_does_not_persist_bodies(self) -> None:
        orch, repo, _audit, sid = _orchestrator(persistence=PersistenceMode.NO_STORE)
        self.addCleanup(repo.close)
        orch.handle(_request(sid, "secret"))
        for m in repo.recent_messages(sid, 10):
            self.assertEqual(m.content, "")

    def test_multi_turn_context_manifest(self) -> None:
        orch, _repo, _audit, sid = _orchestrator(persistence=PersistenceMode.STORE_WITH_RETENTION)
        self.addCleanup(_repo.close)
        orch.handle(_request(sid, "first"))
        outcome = orch.handle(_request(sid, "second"))
        self.assertGreaterEqual(len(outcome.manifest.included_message_ids), 1)


if __name__ == "__main__":
    unittest.main()
