"""Integration: orchestrator + CLI failure/audit behavior (M1, UC-01).

Complements tests/test_orchestrator_conversation.py (the behavior spec) with
additional failure-class coverage and an entry-point blocked render.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from elly.adapters.audit_log import StructuredAuditLog
from elly.adapters.fake_generalist import FailureMode, FakeGeneralist
from elly.adapters.sqlite_repository import SqliteSessionRepository
from elly.adapters.system_clock import FixedClock
from elly.application.conversation import ConversationOrchestrator
from elly.application.local_conversation import LocalConversationUseCase
from elly.composition import Application
from elly.config import load_config
from elly.domain.enums import (
    CloudMode,
    EpistemicStatus,
    PersistenceMode,
    Route,
    TaskStatus,
)
from elly.domain.models import SessionRecord, TaskRequest
from elly.presentation.cli import Cli

UTC = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


def _orchestrator(failure: FailureMode):
    repo = SqliteSessionRepository(":memory:")
    repo.apply_migrations()
    repo.create_session(
        SessionRecord("s1", PersistenceMode.STORE_WITH_RETENTION, CloudMode.LOCAL_ONLY, UTC)
    )
    audit = StructuredAuditLog()
    orch = ConversationOrchestrator(
        clock=FixedClock(UTC, step_seconds=1),
        repository=repo,
        audit=audit,
        context_window=20,
        local_conversation=LocalConversationUseCase(
            generalist=FakeGeneralist(failure=failure),
            model_id="fake-generalist-v1",
            max_output_tokens=64,
        ),
    )
    return orch, repo, audit


def _req(text: str = "hi") -> TaskRequest:
    return TaskRequest(
        request_id="req-1",
        session_id="s1",
        text=text,
        cloud_mode=CloudMode.LOCAL_ONLY,
        persistence_mode=PersistenceMode.STORE_WITH_RETENTION,
        submitted_at=UTC,
    )


class FailureMappingTests(unittest.TestCase):
    def test_malformed_output_blocks(self) -> None:
        orch, _repo, audit = _orchestrator(FailureMode.MALFORMED)
        self.addCleanup(_repo.close)
        outcome = orch.handle(_req())
        self.assertIs(outcome.result.task_status, TaskStatus.BLOCKED)
        self.assertIs(outcome.result.epistemic_status, EpistemicStatus.BLOCKED)
        self.assertIsNone(outcome.assistant_message)
        self.assertFalse(any(e.task_status is TaskStatus.COMPLETED for e in audit.by_task(outcome.result.task_id)))

    def test_permanent_failure_blocks(self) -> None:
        orch, repo, _audit = _orchestrator(FailureMode.PERMANENT)
        self.addCleanup(repo.close)
        outcome = orch.handle(_req())
        self.assertIs(outcome.result.task_status, TaskStatus.BLOCKED)
        # user turn kept (verified partial work); no assistant turn persisted
        roles = [m.role for m in repo.recent_messages("s1", 10)]
        self.assertEqual(roles, ["user"])


class AuditCorrelationTests(unittest.TestCase):
    def test_success_emits_received_and_completed_same_task(self) -> None:
        orch, _repo, audit = _orchestrator(FailureMode.NONE)
        self.addCleanup(_repo.close)
        outcome = orch.handle(_req())
        events = audit.by_task(outcome.result.task_id)
        types = {e.event_type for e in events}
        self.assertIn("task.received", types)
        self.assertIn("task.completed", types)
        self.assertTrue(all(e.task_id == outcome.result.task_id for e in events))

    def test_route_is_local(self) -> None:
        orch, _repo, _audit = _orchestrator(FailureMode.NONE)
        self.addCleanup(_repo.close)
        self.assertIs(orch.route(_req()), Route.LOCAL_CONVERSATION)


class SessionIsolationTests(unittest.TestCase):
    def test_new_session_has_no_inherited_context(self) -> None:
        # AT-01.5: a new session must not inherit another session's transient turns.
        repo = SqliteSessionRepository(":memory:")
        self.addCleanup(repo.close)
        repo.apply_migrations()
        for sid in ("A", "B"):
            repo.create_session(
                SessionRecord(sid, PersistenceMode.STORE_WITH_RETENTION, CloudMode.LOCAL_ONLY, UTC)
            )
        orch = ConversationOrchestrator(
            clock=FixedClock(UTC, step_seconds=1),
            repository=repo,
            audit=StructuredAuditLog(),
            context_window=20,
            local_conversation=LocalConversationUseCase(
                generalist=FakeGeneralist(),
                model_id="fake-generalist-v1",
                max_output_tokens=64,
            ),
        )
        orch.handle(
            TaskRequest("rA", "A", "fact from A", CloudMode.LOCAL_ONLY, PersistenceMode.STORE_WITH_RETENTION, UTC)
        )
        outcome_b = orch.handle(
            TaskRequest("rB", "B", "hi", CloudMode.LOCAL_ONLY, PersistenceMode.STORE_WITH_RETENTION, UTC)
        )
        # B's context was built from B's (empty) prior history — no A turns.
        self.assertEqual(len(outcome_b.manifest.included_message_ids), 0)
        self.assertEqual([m.content for m in repo.recent_messages("A", 10)][0], "fact from A")


class CliBlockedRenderTests(unittest.TestCase):
    def _app_with(self, failure: FailureMode) -> Application:
        cfg = load_config(None)
        repo = SqliteSessionRepository(":memory:")
        repo.apply_migrations()
        return Application(
            config=cfg,
            clock=FixedClock(UTC, step_seconds=1),
            generalist=FakeGeneralist(failure=failure),
            repository=repo,
            audit=StructuredAuditLog(),
        )

    def test_cli_renders_blocked_on_provider_failure(self) -> None:
        app = self._app_with(FailureMode.TRANSIENT)
        self.addCleanup(app.close)
        cli = Cli.start(app)
        out = cli.dispatch("hello")
        self.assertIn("blocked", out.lower())
        self.assertIn("Failure:", out)


if __name__ == "__main__":
    unittest.main()
