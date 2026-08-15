"""V1.5 operation-ledger and repeated-request behavior."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from elly.adapters.audit_log import StructuredAuditLog
from elly.adapters.fake_generalist import FailureMode, FakeGeneralist
from elly.adapters.sqlite_repository import SqliteSessionRepository
from elly.adapters.system_clock import FixedClock
from elly.application.conversation import ConversationOrchestrator
from elly.domain.enums import CloudMode, OutcomeCode, PersistenceMode, TaskStatus
from elly.domain.errors import StorageFailureError
from elly.domain.models import SessionRecord, TaskRequest

UTC = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


def _session(repo: SqliteSessionRepository) -> str:
    session_id = "idempotency-session"
    repo.create_session(
        SessionRecord(
            session_id,
            PersistenceMode.STORE_WITH_RETENTION,
            CloudMode.LOCAL_ONLY,
            UTC,
        )
    )
    return session_id


class OperationLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = SqliteSessionRepository(":memory:")
        self.repo.apply_migrations()
        self.session_id = _session(self.repo)
        self.repo.start_task("task-ledger", self.session_id, UTC)

    def tearDown(self) -> None:
        self.repo.close()

    def test_completed_operation_is_not_claimed_again(self) -> None:
        first = self.repo.claim_operation(
            task_id="task-ledger",
            request_id="request-1",
            capability_id="local_generalist",
            request_digest="a" * 64,
            at=UTC,
        )
        self.assertTrue(first.fresh)
        self.repo.complete_operation(first.operation_id, at=UTC)

        repeated = self.repo.claim_operation(
            task_id="task-ledger",
            request_id="request-1",
            capability_id="local_generalist",
            request_digest="a" * 64,
            at=UTC,
        )
        self.assertFalse(repeated.fresh)
        self.assertTrue(repeated.possible_duplicate)

    def test_retryable_failure_can_be_claimed_again_but_uncertain_failure_cannot(self) -> None:
        first = self.repo.claim_operation(
            task_id="task-ledger",
            request_id="request-1",
            capability_id="research",
            request_digest="b" * 64,
            at=UTC,
        )
        self.repo.fail_operation(first.operation_id, at=UTC)
        retry = self.repo.claim_operation(
            task_id="task-ledger",
            request_id="request-1",
            capability_id="research",
            request_digest="b" * 64,
            at=UTC,
        )
        self.assertTrue(retry.fresh)
        self.repo.fail_operation(retry.operation_id, at=UTC, possible_duplicate=True)
        uncertain_retry = self.repo.claim_operation(
            task_id="task-ledger",
            request_id="request-1",
            capability_id="research",
            request_digest="b" * 64,
            at=UTC,
        )
        self.assertFalse(uncertain_retry.fresh)
        self.assertTrue(uncertain_retry.possible_duplicate)


class OrchestratorIdempotencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = SqliteSessionRepository(":memory:")
        self.repo.apply_migrations()
        self.session_id = _session(self.repo)
        self.provider = FakeGeneralist()
        self.orchestrator = ConversationOrchestrator(
            clock=FixedClock(UTC, step_seconds=1),
            generalist=self.provider,
            repository=self.repo,
            audit=StructuredAuditLog(),
            context_window=20,
            model_id="fake-generalist-v1",
            max_output_tokens=64,
        )

    def tearDown(self) -> None:
        self.repo.close()

    def _request(self) -> TaskRequest:
        return TaskRequest(
            request_id="request-repeat",
            session_id=self.session_id,
            text="hello",
            cloud_mode=CloudMode.LOCAL_ONLY,
            persistence_mode=PersistenceMode.STORE_WITH_RETENTION,
            submitted_at=UTC,
        )

    def test_repeated_completed_request_does_not_append_or_generate_again(self) -> None:
        first = self.orchestrator.handle(self._request())
        second = self.orchestrator.handle(self._request())

        self.assertIs(first.result.task_status, TaskStatus.COMPLETED)
        self.assertIs(second.result.task_status, TaskStatus.PARTIAL)
        self.assertIs(second.result.outcome_code, OutcomeCode.POSSIBLE_DUPLICATE_EXECUTION)
        messages = self.repo.recent_messages(self.session_id, 10)
        self.assertEqual([message.role for message in messages], ["user", "assistant"])

    def test_failed_request_can_retry_without_duplicate_user_turn(self) -> None:
        failing = ConversationOrchestrator(
            clock=FixedClock(UTC, step_seconds=1),
            generalist=FakeGeneralist(failure=FailureMode.TRANSIENT),
            repository=self.repo,
            audit=StructuredAuditLog(),
            context_window=20,
            model_id="fake-generalist-v1",
            max_output_tokens=64,
        )
        first = failing.handle(self._request())
        self.assertIs(first.result.task_status, TaskStatus.BLOCKED)

        second = self.orchestrator.handle(self._request())
        self.assertIs(second.result.task_status, TaskStatus.COMPLETED)
        messages = self.repo.recent_messages(self.session_id, 10)
        self.assertEqual([message.role for message in messages], ["user", "assistant"])


class _FailingAssistantRepository(SqliteSessionRepository):
    def append_message(self, session_id, message):  # type: ignore[no-untyped-def]
        if message.role == "assistant":
            raise StorageFailureError("assistant persistence unavailable")
        super().append_message(session_id, message)


class _FailingCompletionAudit:
    def append(self, event):  # type: ignore[no-untyped-def]
        if event.event_type == "task.completed":
            raise StorageFailureError("completion audit unavailable")

    def by_task(self, _task_id):  # type: ignore[no-untyped-def]
        return []

    def health(self):  # type: ignore[no-untyped-def]
        return None


class _FailingInitialAudit(_FailingCompletionAudit):
    def append(self, event):  # type: ignore[no-untyped-def]
        if event.event_type == "task.received":
            raise StorageFailureError("initial audit unavailable")


class _CountingGeneralist(FakeGeneralist):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def generate(self, request):  # type: ignore[no-untyped-def]
        self.calls += 1
        return super().generate(request)


class ReliabilityOutcomeTests(unittest.TestCase):
    def _request(self, session_id: str) -> TaskRequest:
        return TaskRequest(
            request_id="request-persistence",
            session_id=session_id,
            text="hello",
            cloud_mode=CloudMode.LOCAL_ONLY,
            persistence_mode=PersistenceMode.STORE_WITH_RETENTION,
            submitted_at=UTC,
        )

    def test_generated_output_with_persistence_failure_is_partial(self) -> None:
        repo = _FailingAssistantRepository(":memory:")
        repo.apply_migrations()
        session_id = _session(repo)
        self.addCleanup(repo.close)
        orchestrator = ConversationOrchestrator(
            clock=FixedClock(UTC),
            generalist=FakeGeneralist(),
            repository=repo,
            audit=StructuredAuditLog(),
            context_window=20,
            model_id="fake-generalist-v1",
            max_output_tokens=64,
        )

        outcome = orchestrator.handle(self._request(session_id))

        self.assertIs(outcome.result.task_status, TaskStatus.PARTIAL)
        self.assertIs(outcome.result.outcome_code, OutcomeCode.PARTIAL)
        self.assertIn("fake-generalist", outcome.result.answer)
        self.assertEqual(repo.task_status(outcome.result.task_id), "partial")

    def test_initial_audit_failure_is_typed_and_prevents_provider_dispatch(self) -> None:
        repo = SqliteSessionRepository(":memory:")
        repo.apply_migrations()
        session_id = _session(repo)
        self.addCleanup(repo.close)
        provider = _CountingGeneralist()
        orchestrator = ConversationOrchestrator(
            clock=FixedClock(UTC), generalist=provider, repository=repo,
            audit=_FailingInitialAudit(), context_window=20,
            model_id="fake-generalist-v1", max_output_tokens=64,
        )

        outcome = orchestrator.handle(self._request(session_id))

        self.assertIs(outcome.result.task_status, TaskStatus.FAILED)
        self.assertIn("initial audit unavailable", outcome.result.failures)
        self.assertEqual(0, provider.calls)

    def test_completion_audit_failure_is_partial_not_success(self) -> None:
        repo = SqliteSessionRepository(":memory:")
        repo.apply_migrations()
        session_id = _session(repo)
        self.addCleanup(repo.close)
        orchestrator = ConversationOrchestrator(
            clock=FixedClock(UTC),
            generalist=FakeGeneralist(),
            repository=repo,
            audit=_FailingCompletionAudit(),
            context_window=20,
            model_id="fake-generalist-v1",
            max_output_tokens=64,
        )

        outcome = orchestrator.handle(self._request(session_id))

        self.assertIs(outcome.result.task_status, TaskStatus.PARTIAL)
        self.assertIs(outcome.result.outcome_code, OutcomeCode.PARTIAL)
        self.assertIn("completion audit unavailable", outcome.result.failures)
        self.assertEqual(repo.task_status(outcome.result.task_id), "partial")

if __name__ == "__main__":
    unittest.main()
