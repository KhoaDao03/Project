"""Persisted ``LOCAL_SYNTHESIS`` compatibility tests."""

from __future__ import annotations

import unittest
from dataclasses import replace
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
    CapabilityStatus,
)
from elly.application.capability_workflow import CapabilityExecutionWorkflow
from elly.application.completion import CompletionService
from elly.application.plan_builder import PlanBuilder
from elly.application.task_execution import PlanExecutionRequest, TaskExecutionService
from elly.application.routing_contracts import (
    CapabilityKind,
    CapabilityRoutingDescriptor,
    OperationIntentContract,
)
from elly.domain.enums import (
    ActionCategory,
    CloudMode,
    EpistemicStatus,
    OutcomeCode,
    PersistenceMode,
    Route,
    TaskStatus,
    ValidationStatus,
)
from elly.domain.models import ContextManifest, SessionRecord, TaskRequest, TaskResult
from elly.planning.contracts import (
    PROPOSAL_SCHEMA_VERSION,
    ExecutionProposal,
    FinalizationStrategy,
    PlanLimitsSnapshot,
    PlanStatus,
    ProposalDisposition,
    ProposedStep,
)

UTC = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)


def _request() -> TaskRequest:
    return TaskRequest(
        request_id="request-phase7",
        session_id="session-phase7",
        text="compare the two bounded specialist findings",
        cloud_mode=CloudMode.LOCAL_ONLY,
        persistence_mode=PersistenceMode.STORE_WITH_RETENTION,
        submitted_at=UTC,
    )


class _Capability:
    def __init__(self, capability_id: str) -> None:
        self.capability_id = capability_id
        operation = OperationIntentContract(
            operation_id=f"{capability_id}.run",
            description=f"Run {capability_id}",
            domains=("analysis",),
            accepted_inputs=("text",),
            required_entities=(),
            effect=ActionCategory.NONE,
        )
        self.descriptor = CapabilityDescriptor(
            capability_id=capability_id,
            description=f"{capability_id} capability",
            routes=(Route.REGISTERED_CAPABILITY,),
            request_schema="phase7-v1",
            operations=(operation.operation_id,),
            routing=CapabilityRoutingDescriptor(
                capability_id=capability_id,
                description=f"{capability_id} capability",
                operations=(operation,),
                kind=CapabilityKind.SPECIALIST,
            ),
        )

    def status(self) -> CapabilityStatus:
        return CapabilityStatus(CapabilityAvailability.AVAILABLE)

    def can_handle(self, _request: object) -> CapabilityMatch:
        return CapabilityMatch(True, "PHASE7_TEST")

    def prepare(self, _intent: object, _request: object) -> CapabilityPreparation:
        return CapabilityPreparation(True, "PHASE7_TEST")

    def execute(self, request: object) -> CapabilityExecution:
        task_id = request.task_id  # type: ignore[attr-defined]
        answer = self.capability_id
        return CapabilityExecution(
            TaskResult(
                task_id=task_id,
                task_status=TaskStatus.COMPLETED,
                epistemic_status=EpistemicStatus.INFERRED,
                validation_status=ValidationStatus.VALIDATED,
                answer=answer,
                route_summary=Route.REGISTERED_CAPABILITY,
                outcome_code=OutcomeCode.SUCCESS,
            ),
            request.context_manifest,  # type: ignore[attr-defined]
        )


class PersistedSynthesisCompatibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = SqliteSessionRepository(":memory:")
        self.addCleanup(self.repository.close)
        self.repository.apply_migrations()
        self.repository.create_session(
            SessionRecord(
                "session-phase7", PersistenceMode.STORE_WITH_RETENTION, CloudMode.LOCAL_ONLY, UTC
            )
        )
        self.clock = FixedClock(UTC)
        self._run_count = 0

    def _run(self):
        self._run_count += 1
        registry = CapabilityRegistry((_Capability("left"), _Capability("right")))
        audit = StructuredAuditLog(repository=self.repository)
        workflow = CapabilityExecutionWorkflow(
            clock=self.clock,
            capability_registry=registry,
            completion=CompletionService(clock=self.clock, repository=self.repository, audit=audit),
        )
        proposal = ExecutionProposal(
            schema_version=PROPOSAL_SCHEMA_VERSION,
            disposition=ProposalDisposition.CAPABILITY_PLAN,
            steps=(
                ProposedStep(
                    "left-step",
                    "left",
                    "left.run",
                    "analyze the left perspective",
                    "analysis",
                    "primary",
                ),
                ProposedStep(
                    "right-step",
                    "right",
                    "right.run",
                    "analyze the right perspective",
                    "analysis",
                    "secondary",
                ),
            ),
            finalization=FinalizationStrategy.LOCAL_SYNTHESIS,
            ambiguities=(),
            confidence=1.0,
            reason_code="PHASE7_TEST",
        )
        plan = PlanBuilder(
            registry.routing_catalog(),
            PlanLimitsSnapshot(max_specialist_executions=4, max_parallel_steps=2),
            legacy_synthesis_enabled=True,
        ).build(proposal, f"task-phase7-execution-{self._run_count}")
        self.repository.save_plan(plan, at=UTC)
        self.repository.start_task(plan.task_id, "session-phase7", UTC)
        result = TaskExecutionService(
            repository=self.repository,
            capability_registry=registry,
            capability_workflow=workflow,
            clock=self.clock,
        ).execute(
            plan,
            PlanExecutionRequest(
                request=replace(_request(), request_id="request-phase7-execution"),
                context_text="approved context",
                context_manifest=ContextManifest((), {}, 32, 4),
            ),
        )
        return result, plan

    def test_persisted_synthesis_node_is_a_deterministic_shim(self) -> None:
        result, plan = self._run()

        self.assertEqual(PlanStatus.COMPLETED, result.status)
        self.assertIn("left", result.final_result.answer)  # type: ignore[union-attr]
        self.assertIn("right", result.final_result.answer)  # type: ignore[union-attr]
        record = self.repository.get_synthesis_result(plan.plan_id)
        self.assertIsNotNone(record)
        self.assertTrue(record.validation_state.startswith("response_composition:"))  # type: ignore[union-attr]
        self.assertFalse(
            any(
                event.event_type == "synthesis.fallback"
                for event in self.repository.plan_events(plan.plan_id)
            )
        )


if __name__ == "__main__":
    unittest.main()
