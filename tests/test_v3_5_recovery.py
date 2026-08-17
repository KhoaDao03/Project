"""Restart, exactly-once, and legacy-plan recovery tests for V3.5."""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone

from elly.adapters.audit_log import StructuredAuditLog
from elly.adapters.fake_response_composer import FakeResponseComposer
from elly.adapters.sqlite_repository import SqliteSessionRepository
from elly.adapters.system_clock import FixedClock
from elly.application.capabilities import CapabilityRegistry
from elly.application.capability_workflow import CapabilityExecutionWorkflow
from elly.application.completion import CompletionService
from elly.application.plan_builder import PlanBuilder
from elly.application.plan_executor import PlanExecutionRequest, PlanExecutor
from elly.domain.enums import CloudMode, PersistenceMode, TaskStatus
from elly.domain.models import ContextManifest, SessionRecord, TaskRequest
from elly.planning.contracts import (
    PROPOSAL_SCHEMA_VERSION,
    ExecutionProposal,
    FinalizationStrategy,
    PlanLimitsSnapshot,
    PlanStatus,
    ProposalDisposition,
    ProposedStep,
    StepState,
)
from tests.test_v3_phase7_synthesis import _Capability

UTC = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)


class V35RecoveryTests(unittest.TestCase):
    def _fixture(
        self,
        persistence_mode: PersistenceMode,
        *,
        finalization: FinalizationStrategy = FinalizationStrategy.DIRECT,
        legacy_plan: bool = False,
    ) -> tuple[
        SqliteSessionRepository,
        object,
        PlanExecutionRequest,
        FakeResponseComposer,
        object,
    ]:
        repository = SqliteSessionRepository(":memory:")
        self.addCleanup(repository.close)
        repository.apply_migrations()
        repository.create_session(
            SessionRecord("session-v35-recovery", persistence_mode, CloudMode.LOCAL_ONLY, UTC)
        )
        capability = _Capability("recovery")
        registry = CapabilityRegistry((capability,))
        clock = FixedClock(UTC)
        workflow = CapabilityExecutionWorkflow(
            clock=clock,
            capability_registry=registry,
            completion=CompletionService(
                clock=clock,
                repository=repository,
                audit=StructuredAuditLog(repository=repository),
            ),
        )
        proposal = ExecutionProposal(
            schema_version=PROPOSAL_SCHEMA_VERSION,
            disposition=ProposalDisposition.CAPABILITY_PLAN,
            steps=(
                ProposedStep(
                    "recovery-step",
                    "recovery",
                    "recovery.run",
                    "run recovery step",
                    "analysis",
                    "primary",
                ),
            ),
            finalization=finalization,
            ambiguities=(),
            confidence=1.0,
            reason_code="V35_RECOVERY_TEST",
        )
        plan = PlanBuilder(
            registry.routing_catalog(),
            PlanLimitsSnapshot(max_specialist_executions=2),
            legacy_synthesis_enabled=legacy_plan,
        ).build(proposal, "task-v35-recovery")
        repository.save_plan(plan, at=UTC)
        repository.start_task(plan.task_id, "session-v35-recovery", UTC)
        composer = FakeResponseComposer()
        execution = PlanExecutionRequest(
            request=TaskRequest(
                request_id="request-v35-recovery",
                session_id="session-v35-recovery",
                text="run",
                cloud_mode=CloudMode.LOCAL_ONLY,
                persistence_mode=persistence_mode,
                submitted_at=UTC,
            ),
            context_text="approved context",
            context_manifest=ContextManifest((), {}, 16, 0),
        )

        def executor() -> PlanExecutor:
            return PlanExecutor(
                repository=repository,
                capability_registry=registry,
                capability_workflow=workflow,
                clock=clock,
                response_composer_port=composer,
            )

        return repository, plan, execution, composer, executor

    def test_retained_terminal_restart_reuses_composed_output(self) -> None:
        repository, plan, execution, composer, executor = self._fixture(
            PersistenceMode.STORE_WITH_RETENTION
        )
        first = executor().execute(plan, execution)  # type: ignore[union-attr]
        second = executor().execute(first.plan, execution)  # type: ignore[union-attr]

        self.assertEqual(1, len(composer.requests))
        self.assertEqual(first.final_result.answer, second.final_result.answer)
        record = repository.get_synthesis_result(plan.plan_id)
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual("accepted", record.output["outcome"])
        self.assertIn("result_refs", record.output)
        self.assertIn("claim_refs", record.output)
        events = repository.plan_events(plan.plan_id)
        self.assertTrue(any(event.event_type == "response_composer.attempted" for event in events))
        self.assertTrue(any(event.event_type == "response_composer.accepted" for event in events))
        self.assertTrue(any(event.event_type == "response_composer.result" for event in events))
        self.assertNotIn("prompt", " ".join(event.detail for event in events))

    def test_no_store_terminal_restart_does_not_compose_twice(self) -> None:
        _repository, plan, execution, composer, executor = self._fixture(
            PersistenceMode.NO_STORE
        )
        first = executor().execute(plan, execution)  # type: ignore[union-attr]
        second = executor().execute(first.plan, execution)  # type: ignore[union-attr]

        self.assertEqual(1, len(composer.requests))
        self.assertEqual(TaskStatus.COMPLETED, second.final_result.task_status)
        self.assertTrue(second.final_result.answer)

    def test_interrupted_reserved_attempt_recovers_without_redispatch(self) -> None:
        repository, plan, execution, composer, executor = self._fixture(
            PersistenceMode.STORE_WITH_RETENTION
        )
        repository.delete_plans_for_task(plan.task_id)
        terminal = replace(
            plan,
            status=PlanStatus.FAILED,
            steps=tuple(replace(step, state=StepState.FAILED) for step in plan.steps),
        )
        repository.save_plan(terminal, at=UTC)
        # Simulate a process stop after the durable reservation but before a
        # composer result could be saved.
        repository.save_synthesis_result(
            terminal.plan_id,
            terminal.finalization,
            "response_composition:attempting",
            (),
            {"mode": "", "outcome": "attempting", "answer": "", "answer_retained": False},
            at=UTC,
        )
        recovered = executor().execute(terminal, execution)  # type: ignore[union-attr]

        self.assertEqual(0, len(composer.requests))
        self.assertEqual(TaskStatus.FAILED, recovered.final_result.task_status)
        self.assertTrue(recovered.final_result.answer)

    def test_persisted_legacy_synthesis_node_is_a_shim(self) -> None:
        _repository, plan, execution, composer, executor = self._fixture(
            PersistenceMode.STORE_WITH_RETENTION,
            finalization=FinalizationStrategy.LOCAL_SYNTHESIS,
            legacy_plan=True,
        )
        self.assertIn("synthesis", {step.step_id for step in plan.steps})
        result = executor().execute(plan, execution)  # type: ignore[union-attr]

        self.assertEqual(TaskStatus.COMPLETED, result.final_result.task_status)
        self.assertEqual(1, len(composer.requests))

    def test_persisted_legacy_synthesis_result_remains_readable(self) -> None:
        repository, plan, _execution, _composer, _executor = self._fixture(
            PersistenceMode.STORE_WITH_RETENTION,
            finalization=FinalizationStrategy.LOCAL_SYNTHESIS,
            legacy_plan=True,
        )
        repository.save_synthesis_result(
            plan.plan_id,
            FinalizationStrategy.LOCAL_SYNTHESIS,
            "validated",
            ("result-recovery-step",),
            {"answer": "legacy retained answer", "answer_retained": True},
            at=UTC,
        )

        record = repository.get_synthesis_result(plan.plan_id)

        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(FinalizationStrategy.LOCAL_SYNTHESIS, record.strategy)
        self.assertEqual("validated", record.validation_state)
        self.assertEqual(("result-recovery-step",), record.referenced_result_ids)
        self.assertEqual("legacy retained answer", record.output["answer"])


if __name__ == "__main__":
    unittest.main()
