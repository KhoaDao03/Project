"""Isolated V2 capability-workflow failure and recovery matrix."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from elly.adapters.audit_log import StructuredAuditLog
from elly.adapters.sqlite_repository import SqliteSessionRepository
from elly.adapters.system_clock import FixedClock
from elly.application.capabilities import (
    CapabilityAvailability,
    CapabilityDescriptor,
    CapabilityExecution,
    CapabilityMatch,
    CapabilityPreparation,
    CapabilityRegistry,
    CapabilityRequest,
    CapabilityStatus,
)
from elly.application.capability_workflow import (
    CapabilityExecutionCommand,
    CapabilityExecutionWorkflow,
)
from elly.application.completion import CompletionService
from elly.application.execution import CancellationToken
from elly.domain.enums import (
    CloudMode,
    EpistemicStatus,
    IntentAmbiguity,
    OutcomeCode,
    PersistenceMode,
    Route,
    RouteReasonCode,
    TaskStatus,
    ValidationStatus,
)
from elly.domain.errors import PermanentProviderError, StorageFailureError
from elly.domain.models import (
    ActionProposal,
    CapabilityIntent,
    ContextManifest,
    RouteDecision,
    RouteRequest,
    SessionRecord,
    TaskRequest,
    TaskResult,
)

UTC = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


class _MatrixCapability:
    def __init__(
        self,
        *,
        available: bool = True,
        match: bool = True,
        prepared: bool = True,
        external: bool = False,
        provider_failure: bool = False,
    ) -> None:
        self.available = available
        self.match = match
        self.prepared = prepared
        self.provider_failure = provider_failure
        self.calls = 0
        self.descriptor = CapabilityDescriptor(
            capability_id="matrix.test",
            description="workflow matrix capability",
            routes=(Route.CODING_SPECIALIST,),
            request_schema="matrix-v1",
            operations=("matrix.execute",),
            requires_external_boundary=external,
            destination="fixture" if external else "",
            model="fixture-v1" if external else "",
        )

    def status(self) -> CapabilityStatus:
        return CapabilityStatus(
            CapabilityAvailability.AVAILABLE
            if self.available
            else CapabilityAvailability.UNAVAILABLE,
            "" if self.available else "MATRIX_DISABLED",
        )

    def can_handle(self, request: CapabilityRequest) -> CapabilityMatch:
        return CapabilityMatch(self.match, "MATCH" if self.match else "INPUT_REJECTED")

    def prepare(
        self, intent: CapabilityIntent, request: CapabilityRequest
    ) -> CapabilityPreparation:
        return CapabilityPreparation(
            self.prepared,
            "PREPARED" if self.prepared else "SCHEMA_REJECTED",
        )

    def propose_action(self, request: CapabilityRequest) -> ActionProposal:
        return ActionProposal.none()

    def execute(self, request: CapabilityRequest) -> CapabilityExecution:
        self.calls += 1
        if self.provider_failure:
            raise PermanentProviderError("matrix provider failed")
        return CapabilityExecution(
            TaskResult(
                task_id=request.task_id,
                task_status=TaskStatus.COMPLETED,
                epistemic_status=EpistemicStatus.INFERRED,
                validation_status=ValidationStatus.VALIDATED,
                answer="matrix output",
                route_summary=Route.CODING_SPECIALIST,
            ),
            request.context_manifest,
        )


class _FailingResultRepository(SqliteSessionRepository):
    def save_task_result(self, result: TaskResult, at: datetime) -> None:
        raise StorageFailureError("matrix persistence failed")


class _FailingAudit:
    def __init__(self, *, fail_on: int = 1) -> None:
        self.calls = 0
        self.fail_on = fail_on

    def append(self, event) -> None:  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.calls == self.fail_on:
            raise StorageFailureError("matrix audit failed")


class CapabilityWorkflowFailureMatrixTests(unittest.TestCase):
    def _execute(
        self,
        capability: _MatrixCapability | None,
        *,
        repository: SqliteSessionRepository | None = None,
        audit=None,  # type: ignore[no-untyped-def]
        cloud_mode: CloudMode = CloudMode.LOCAL_ONLY,
        cancelled: bool = False,
        request_id: str = "matrix-request",
    ):
        repo = repository or SqliteSessionRepository(":memory:")
        self.addCleanup(repo.close)
        repo.apply_migrations()
        repo.create_session(
            SessionRecord(
                "matrix-session",
                PersistenceMode.STORE_WITH_RETENTION,
                cloud_mode,
                UTC,
            )
        )
        task_id = f"task-{request_id}"
        task = TaskRequest(
            request_id,
            "matrix-session",
            "execute matrix capability",
            cloud_mode,
            PersistenceMode.STORE_WITH_RETENTION,
            UTC,
        )
        repo.start_task(task_id, task.session_id, UTC)
        lease = repo.claim_operation(
            task_id=task_id,
            request_id=request_id,
            capability_id="matrix.test",
            request_digest="a" * 64,
            at=UTC,
        )
        token = CancellationToken()
        if cancelled:
            token.cancel()
        sink = audit or StructuredAuditLog()
        workflow = CapabilityExecutionWorkflow(
            clock=FixedClock(UTC),
            capability_registry=CapabilityRegistry((capability,) if capability is not None else ()),
            completion=CompletionService(clock=FixedClock(UTC), repository=repo, audit=sink),
        )
        intent = CapabilityIntent(
            "matrix.test",
            "matrix.execute",
            arguments={"subject": task.text},
            confidence=1.0,
            ambiguity=IntentAmbiguity.CLEAR,
            rationale_code="MATRIX",
        )
        return workflow.execute(
            CapabilityExecutionCommand(
                request=task,
                task_id=task_id,
                status=TaskStatus.RUNNING,
                route=Route.CODING_SPECIALIST,
                route_request=RouteRequest(request_id, task.text, cloud_mode=cloud_mode),
                route_decision=RouteDecision(
                    Route.CODING_SPECIALIST,
                    RouteReasonCode.PROPOSAL_ACCEPTED,
                    capability_id="matrix.test",
                    operation="matrix.execute",
                    intent=intent,
                ),
                context_text=task.text,
                context_manifest=ContextManifest((), {}, 32, 2),
                cancellation=token,
                operation_lease=lease,
            )
        )

    def test_registered_capability_completes_through_the_workflow_contract(self) -> None:
        capability = _MatrixCapability()

        outcome = self._execute(capability)

        self.assertEqual(TaskStatus.COMPLETED, outcome.result.task_status)
        self.assertEqual("matrix output", outcome.result.answer)
        self.assertEqual(1, capability.calls)
        self.assertEqual("completed", outcome.result.task_status.value)

    def test_lookup_unavailable_and_invalid_input_fail_without_execution(self) -> None:
        for capability, expected in (
            (None, OutcomeCode.UNAVAILABLE),
            (_MatrixCapability(available=False), OutcomeCode.UNAVAILABLE),
            (_MatrixCapability(match=False), OutcomeCode.BLOCKED),
            (_MatrixCapability(prepared=False), OutcomeCode.BLOCKED),
        ):
            with self.subTest(expected=expected, capability=capability):
                outcome = self._execute(capability)
                self.assertEqual(TaskStatus.BLOCKED, outcome.result.task_status)
                self.assertEqual(expected, outcome.result.outcome_code)
                if capability is not None:
                    self.assertEqual(0, capability.calls)

    def test_authorization_and_cancellation_block_before_provider(self) -> None:
        external = _MatrixCapability(external=True)
        denied = self._execute(external)
        self.assertEqual(TaskStatus.BLOCKED, denied.result.task_status)
        self.assertEqual(0, external.calls)

        cancelled = _MatrixCapability()
        outcome = self._execute(cancelled, cancelled=True, request_id="matrix-cancel")
        self.assertEqual(TaskStatus.CANCELLED, outcome.result.task_status)
        self.assertEqual(0, cancelled.calls)

    def test_provider_failure_is_typed_and_does_not_escape(self) -> None:
        capability = _MatrixCapability(provider_failure=True)
        outcome = self._execute(capability)
        self.assertEqual(TaskStatus.FAILED, outcome.result.task_status)
        self.assertEqual(OutcomeCode.FAILED, outcome.result.outcome_code)
        self.assertEqual(1, capability.calls)

    def test_completion_persistence_and_audit_failures_are_not_success(self) -> None:
        persistence = self._execute(
            _MatrixCapability(), repository=_FailingResultRepository(":memory:")
        )
        self.assertEqual(TaskStatus.PARTIAL, persistence.result.task_status)
        self.assertEqual(OutcomeCode.PARTIAL, persistence.result.outcome_code)

        audit = self._execute(_MatrixCapability(), audit=_FailingAudit(fail_on=2))
        self.assertEqual(TaskStatus.PARTIAL, audit.result.task_status)
        self.assertEqual(OutcomeCode.PARTIAL, audit.result.outcome_code)


if __name__ == "__main__":
    unittest.main()
