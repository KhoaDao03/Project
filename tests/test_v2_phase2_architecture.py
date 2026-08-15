"""Phase 2 architecture contracts for stable wiring and capability workflow isolation."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from elly.adapters.audit_log import StructuredAuditLog
from elly.adapters.fake_generalist import FakeGeneralist
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
from elly.application.conversation import ConversationOrchestrator
from elly.application.execution import CancellationToken
from elly.application.local_conversation import LocalConversationUseCase
from elly.domain.enums import (
    CloudMode,
    EpistemicStatus,
    PersistenceMode,
    Route,
    RouteReasonCode,
    TaskStatus,
    ValidationStatus,
)
from elly.domain.models import (
    CapabilityIntent,
    ContextManifest,
    RouteDecision,
    RouteProposal,
    RouteRequest,
    SessionRecord,
    TaskRequest,
    TaskResult,
)

UTC = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


class _RegisteredCapability:
    descriptor = CapabilityDescriptor(
        capability_id="phase2.test",
        description="Phase 2 deterministic test capability",
        routes=(Route.CODING_SPECIALIST,),
        request_schema="phase2-test-v1",
        operations=("phase2.execute",),
        requires_external_boundary=False,
    )

    def status(self) -> CapabilityStatus:
        return CapabilityStatus(CapabilityAvailability.AVAILABLE)

    def can_handle(self, _request: CapabilityRequest) -> CapabilityMatch:
        return CapabilityMatch(True, "PHASE2_MATCH")

    def prepare(
        self, _intent: CapabilityIntent, _request: CapabilityRequest
    ) -> CapabilityPreparation:
        return CapabilityPreparation(True, "PHASE2_INPUT_ACCEPTED")

    def execute(self, request: CapabilityRequest) -> CapabilityExecution:
        return CapabilityExecution(
            TaskResult(
                task_id=request.task_id,
                task_status=TaskStatus.COMPLETED,
                epistemic_status=EpistemicStatus.INFERRED,
                validation_status=ValidationStatus.VALIDATED,
                answer="phase2 handled",
                route_summary=Route.CODING_SPECIALIST,
            ),
            request.context_manifest,
        )


class Phase2ArchitectureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = SqliteSessionRepository(":memory:")
        self.repository.apply_migrations()
        self.repository.create_session(
            SessionRecord(
                "phase2-session",
                PersistenceMode.STORE_WITH_RETENTION,
                CloudMode.LOCAL_ONLY,
                UTC,
            )
        )
        self.audit = StructuredAuditLog()
        self.clock = FixedClock(UTC)
        self.addCleanup(self.repository.close)

    def test_orchestrator_uses_one_injected_local_workflow(self) -> None:
        local = LocalConversationUseCase(
            generalist=FakeGeneralist(),
            model_id="phase2-local",
            max_output_tokens=32,
        )
        orchestrator = ConversationOrchestrator(
            clock=self.clock,
            repository=self.repository,
            audit=self.audit,
            context_window=20,
            local_conversation=local,
        )
        self.assertIs(local, orchestrator._local_conversation)
        self.assertFalse(hasattr(orchestrator, "_generalist"))
        self.assertFalse(hasattr(orchestrator, "_research"))
        self.assertFalse(hasattr(orchestrator, "_specialist_workflow"))

    def test_registered_capability_executes_without_constructing_orchestrator(self) -> None:
        registry = CapabilityRegistry((_RegisteredCapability(),))
        completion = CompletionService(
            clock=self.clock,
            repository=self.repository,
            audit=self.audit,
        )
        workflow = CapabilityExecutionWorkflow(
            clock=self.clock,
            capability_registry=registry,
            completion=completion,
        )
        task = TaskRequest(
            request_id="phase2-request",
            session_id="phase2-session",
            text="test capability",
            cloud_mode=CloudMode.LOCAL_ONLY,
            persistence_mode=PersistenceMode.STORE_WITH_RETENTION,
            submitted_at=UTC,
            route_proposal=RouteProposal(
                route=Route.CODING_SPECIALIST,
                capability_id="phase2.test",
                request_schema="phase2-test-v1",
            ),
        )
        task_id = "task-phase2-request"
        self.repository.start_task(task_id, task.session_id, UTC)
        lease = self.repository.claim_operation(
            task_id=task_id,
            request_id=task.request_id,
            capability_id="phase2.test",
            request_digest="a" * 64,
            at=UTC,
        )
        outcome = workflow.execute(
            CapabilityExecutionCommand(
                request=task,
                task_id=task_id,
                status=TaskStatus.RUNNING,
                route=Route.CODING_SPECIALIST,
                route_request=RouteRequest(
                    request_id=task.request_id,
                    text=task.text,
                    cloud_mode=task.cloud_mode,
                ),
                route_decision=RouteDecision(
                    Route.CODING_SPECIALIST,
                    RouteReasonCode.PROPOSAL_ACCEPTED,
                    capability_id="phase2.test",
                ),
                context_text=task.text,
                context_manifest=ContextManifest((), {}, 32, 2),
                cancellation=CancellationToken(),
                operation_lease=lease,
            )
        )
        self.assertEqual(TaskStatus.COMPLETED, outcome.result.task_status)
        self.assertEqual("phase2 handled", outcome.result.answer)
        self.assertEqual("completed", self.repository.task_status(task_id))
        self.assertTrue(
            any(event.event_type == "capability.completed" for event in self.audit.by_task(task_id))
        )


if __name__ == "__main__":
    unittest.main()
