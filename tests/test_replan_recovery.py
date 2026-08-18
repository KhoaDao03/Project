"""Bounded replanning, recovery, and provenance tests."""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone

from elly.adapters.sqlite_repository import SqliteSessionRepository
from elly.adapters.system_clock import FixedClock
from elly.api.application import _plan_trace_view, _plan_view
from elly.application.plan_builder import PlanBuilder
from elly.application.recovery import PlanRecovery
from elly.application.replan import (
    ReplanPolicy,
    ReplanRequest,
    ReplanService,
    ReplanTrigger,
)
from elly.application.routing_contracts import (
    CapabilityRoutingDescriptor,
    OperationIntentContract,
)
from elly.domain.enums import (
    ActionCategory,
    EpistemicStatus,
    OutcomeCode,
    Route,
    TaskStatus,
    ValidationStatus,
)
from elly.domain.models import TaskResult
from elly.planning.contracts import (
    PLAN_SCHEMA_VERSION,
    PROPOSAL_SCHEMA_VERSION,
    AuthorizationState,
    ExecutionPlan,
    ExecutionProposal,
    FinalizationStrategy,
    PlanLimitsSnapshot,
    PlanStatus,
    PlanStep,
    ProposalDisposition,
    ProposedInput,
    ProposedStep,
    StepCriticality,
    StepKind,
    StepState,
)

UTC = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)


def _operation(operation_id: str) -> OperationIntentContract:
    return OperationIntentContract(
        operation_id=operation_id,
        description="bounded test operation",
        domains=("analysis",),
        accepted_inputs=("text",),
        required_entities=(),
        effect=ActionCategory.NONE,
    )


def _catalog() -> tuple[CapabilityRoutingDescriptor, ...]:
    return (
        CapabilityRoutingDescriptor("alpha", "alpha", (_operation("alpha.run"),)),
        CapabilityRoutingDescriptor("beta", "beta", (_operation("beta.run"),)),
    )


def _step(step_id: str, *, state: StepState, external: bool = False) -> PlanStep:
    return PlanStep(
        step_id=step_id,
        kind=StepKind.CAPABILITY,
        capability_id=f"cap-{step_id}",
        operation_id=f"op-{step_id}",
        objective=f"run {step_id}",
        objective_class="analysis",
        perspective="primary",
        inputs=(),
        dependencies=(),
        output_type="task_result",
        criticality=StepCriticality.REQUIRED,
        verification=False,
        timeout_seconds=10,
        requires_external_access=external,
        effect=ActionCategory.NONE,
        requires_consent=external,
        state=state,
        authorization_state=AuthorizationState.APPROVED
        if external
        else AuthorizationState.NOT_REQUIRED,
    )


def _proposal(*steps: ProposedStep) -> ExecutionProposal:
    return ExecutionProposal(
        schema_version=PROPOSAL_SCHEMA_VERSION,
        disposition=ProposalDisposition.CAPABILITY_PLAN,
        steps=tuple(steps),
        finalization=FinalizationStrategy.DIRECT,
        ambiguities=(),
        confidence=0.9,
        reason_code="TEST_REPLAN",
    )


def _proposed(step_id: str, capability: str, operation: str) -> ProposedStep:
    return ProposedStep(
        proposal_step_id=step_id,
        capability_id=capability,
        operation_id=operation,
        objective=f"run {step_id}",
        objective_class="analysis",
        perspective="primary",
        inputs=(ProposedInput("text", "text"),),
    )


class Phase8PolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = SqliteSessionRepository(":memory:")
        self.addCleanup(self.repository.close)
        self.repository.apply_migrations()
        self.builder = PlanBuilder(
            _catalog(),
            PlanLimitsSnapshot(max_specialist_executions=3, max_replanning_attempts=1),
        )
        self.plan = self.builder.build(
            _proposal(_proposed("alpha-step", "alpha", "alpha.run")),
            "task-phase8",
        )

    def test_one_replan_reuses_completed_artifact_and_links_lineage(self) -> None:
        completed = replace(
            self.plan,
            steps=(replace(self.plan.steps[0], state=StepState.COMPLETED),),
        )
        self.repository.save_plan(completed, at=UTC)
        self.repository.save_step_result(
            completed.plan_id,
            "alpha-step",
            TaskResult(
                task_id=completed.task_id,
                task_status=TaskStatus.COMPLETED,
                epistemic_status=EpistemicStatus.INFERRED,
                validation_status=ValidationStatus.VALIDATED,
                answer="completed alpha",
                route_summary=Route.REGISTERED_CAPABILITY,
                outcome_code=OutcomeCode.SUCCESS,
            ),
            at=UTC,
        )
        service = ReplanService(
            repository=self.repository,
            plan_builder=self.builder,
            clock=FixedClock(UTC),
        )
        result = service.replan(
            completed,
            _proposal(
                _proposed("alpha-step", "alpha", "alpha.run"),
                _proposed("beta-step", "beta", "beta.run"),
            ),
            request=ReplanRequest(
                source_plan=completed,
                trigger=ReplanTrigger.PROVIDER_SUBSTITUTION,
                failed_step_id="alpha-step",
                replacement_capability_id="alpha",
                replacement_operation_id="alpha.run",
            ),
        )

        self.assertTrue(result.approved)
        assert result.plan is not None
        self.assertEqual(1, result.plan.revision)
        self.assertEqual(completed.plan_id, result.plan.parent_plan_id)
        self.assertEqual(("alpha-step",), result.reused_step_ids)
        self.assertEqual(StepState.COMPLETED, result.plan.steps[0].state)
        self.assertIsNotNone(self.repository.get_step_result(result.plan.plan_id, "alpha-step"))
        self.assertTrue(
            any(
                event.event_type == "plan.replanned" and result.plan.plan_id in event.detail
                for event in self.repository.plan_events(completed.plan_id)
            )
        )

        trace = _plan_trace_view(self.repository, result.plan)
        self.assertEqual((completed.plan_id, result.plan.plan_id), trace.lineage_plan_ids)
        self.assertEqual((completed.plan_id,), trace.lineage_plan_ids[:-1])
        self.assertIn("result-alpha-step", trace.contributing_result_ids)

    def test_policy_rejects_second_attempt_and_never_replans_for_safety_gates(self) -> None:
        policy = ReplanPolicy()
        base = ReplanRequest(self.plan, ReplanTrigger.CAPABILITY_UNAVAILABLE)
        self.assertEqual("REPLAN_APPROVED", policy.evaluate(base).reason_code)
        self.assertEqual(
            "REPLAN_ATTEMPT_EXHAUSTED",
            policy.evaluate(replace(base, attempt=1)).reason_code,
        )
        for field in (
            "cancellation_accepted",
            "authorization_denied",
            "consent_denied",
            "hard_limit_reached",
            "uncertain_external_action",
        ):
            with self.subTest(field=field):
                self.assertFalse(policy.evaluate(replace(base, **{field: True})).approved)
        self.assertEqual(
            "REPLAN_PROVIDER_CONTRACT_CHANGED",
            policy.evaluate(
                replace(
                    base,
                    trigger=ReplanTrigger.PROVIDER_SUBSTITUTION,
                    same_contract=False,
                )
            ).reason_code,
        )


class Phase8RecoveryAndTraceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = SqliteSessionRepository(":memory:")
        self.addCleanup(self.repository.close)
        self.repository.apply_migrations()

    def test_local_active_step_is_resumable_but_external_active_step_is_held(self) -> None:
        plan = ExecutionPlan(
            plan_id="plan-recovery",
            task_id="task-recovery",
            schema_version=PLAN_SCHEMA_VERSION,
            revision=0,
            parent_plan_id=None,
            steps=(
                _step("local-step", state=StepState.RUNNING),
                _step("hosted-step", state=StepState.RUNNING, external=True),
            ),
            finalization=FinalizationStrategy.DIRECT,
            limits=PlanLimitsSnapshot(max_plan_steps=2),
            catalog_version="catalog-recovery",
            status=PlanStatus.RUNNING,
        )
        self.repository.save_plan(plan, at=UTC)
        report = PlanRecovery(clock=FixedClock(UTC)).reconcile(plan, self.repository)

        self.assertEqual(("local-step",), report.resumed_step_ids)
        self.assertEqual(("hosted-step",), report.uncertain_step_ids)
        self.assertEqual(PlanStatus.INTERRUPTED, report.plan.status)
        self.assertEqual(StepState.PENDING, report.plan.steps[0].state)
        self.assertEqual(StepState.INTERRUPTED, report.plan.steps[1].state)
        self.assertTrue(
            any(
                event.event_type == "recovery.step"
                for event in self.repository.plan_events(plan.plan_id)
            )
        )
        self.assertTrue(
            any(
                event.event_type == "recovery.plan"
                for event in self.repository.plan_events(plan.plan_id)
            )
        )

    def test_trace_and_views_expose_safe_ids_only(self) -> None:
        plan = ExecutionPlan(
            plan_id="plan-safe-trace",
            task_id="task-safe-trace",
            schema_version=PLAN_SCHEMA_VERSION,
            revision=0,
            parent_plan_id=None,
            steps=(_step("safe-step", state=StepState.PENDING),),
            finalization=FinalizationStrategy.DIRECT,
            limits=PlanLimitsSnapshot(),
            catalog_version="catalog-safe",
        )
        self.repository.save_plan(plan, at=UTC)
        self.repository.append_plan_event(
            plan.plan_id,
            "diagnostic",
            "SAFE_TEST",
            (
                "prompt=private prompt payload=secret token=credential "
                "chain_of_thought=hidden provider_body=body"
            ),
            at=UTC,
        )
        trace = _plan_trace_view(self.repository, plan)
        view = _plan_view(self.repository, plan)
        detail = " ".join(event.detail for event in trace.events)
        self.assertNotIn("private prompt", detail)
        self.assertNotIn("secret", detail)
        self.assertNotIn("credential", detail)
        self.assertNotIn("hidden", detail)
        self.assertNotIn("provider_body=body", detail)
        self.assertEqual(plan.plan_id, view.plan_id)
        self.assertEqual("safe-step", view.steps[0].step_id)


if __name__ == "__main__":
    unittest.main()
