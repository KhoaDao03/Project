"""Execution truth aggregation and finalization tests."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from elly.adapters.sqlite_repository import SqliteSessionRepository
from elly.api.application import EllyApplication
from elly.api.contracts import PlanQuery, PlanTraceQuery
from elly.application.plan_results import (
    DirectFinalizer,
    PlanStatusPolicy,
    TemplateFinalizer,
    aggregate_plan_results,
    derive_plan_status,
)
from elly.application.step_results import ActionExecutionReceipt, StepClaim, StepResultEnvelope
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
    AuthorizationState,
    ExecutionPlan,
    FinalizationStrategy,
    PlanLimitsSnapshot,
    PlanStatus,
    PlanStep,
    StepCriticality,
    StepKind,
    StepState,
)


def _step(
    step_id: str,
    *,
    criticality: StepCriticality = StepCriticality.REQUIRED,
    state: StepState = StepState.PENDING,
) -> PlanStep:
    return PlanStep(
        step_id=step_id,
        kind=StepKind.CAPABILITY,
        capability_id=f"capability-{step_id}",
        operation_id=f"operation-{step_id}",
        objective=f"run {step_id}",
        objective_class="analysis",
        perspective="primary",
        inputs=(),
        dependencies=(),
        output_type="task_result",
        criticality=criticality,
        verification=False,
        timeout_seconds=10,
        effect=ActionCategory.NONE,
        state=state,
        authorization_state=AuthorizationState.PENDING,
    )


def _plan(
    *steps: PlanStep, finalization: FinalizationStrategy = FinalizationStrategy.DIRECT
) -> ExecutionPlan:
    return ExecutionPlan(
        plan_id="plan-phase6",
        task_id="task-phase6",
        schema_version=PLAN_SCHEMA_VERSION,
        revision=0,
        parent_plan_id=None,
        steps=tuple(steps),
        finalization=finalization,
        limits=PlanLimitsSnapshot(max_specialist_executions=4),
        catalog_version="catalog-phase6",
    )


def _result(
    task_id: str = "task-phase6", answer: str = "answer", status: TaskStatus = TaskStatus.COMPLETED
) -> TaskResult:
    return TaskResult(
        task_id=task_id,
        task_status=status,
        epistemic_status=EpistemicStatus.INFERRED,
        validation_status=ValidationStatus.VALIDATED,
        answer=answer,
        route_summary=Route.REGISTERED_CAPABILITY,
        outcome_code=(
            OutcomeCode.SUCCESS if status is TaskStatus.COMPLETED else OutcomeCode.FAILED
        ),
    )


def _envelope(
    plan: ExecutionPlan, step: PlanStep, answer: str, *, finding: str = ""
) -> StepResultEnvelope:
    return StepResultEnvelope(
        schema_version="elly.step-result.v1",
        plan_id=plan.plan_id,
        task_id=plan.task_id,
        step_id=step.step_id,
        capability_id=step.capability_id,
        operation_id=step.operation_id,
        status=TaskStatus.COMPLETED,
        summary=answer,
        answer=answer,
        findings=(finding,) if finding else (),
        claims=(
            StepClaim(
                claim_id="claim-shared",
                text=answer,
            ),
        ),
    )


class Phase6StatusPolicyTests(unittest.TestCase):
    def test_decision_table_rows_and_cancellation_precedence(self) -> None:
        required = _step("required")
        optional = _step("optional", criticality=StepCriticality.OPTIONAL)

        self.assertEqual(
            PlanStatus.CANCELLED,
            derive_plan_status(
                (required,),
                {"required": StepState.COMPLETED},
                cancellation_accepted=True,
            ),
        )
        self.assertEqual(
            PlanStatus.BLOCKED,
            derive_plan_status((required,), {"required": StepState.BLOCKED}),
        )
        self.assertEqual(
            PlanStatus.UNAVAILABLE,
            derive_plan_status((required,), {"required": StepState.UNAVAILABLE}),
        )
        self.assertEqual(
            PlanStatus.FAILED,
            derive_plan_status((required,), {"required": StepState.FAILED}),
        )
        self.assertEqual(
            PlanStatus.FAILED,
            derive_plan_status((required,), {"required": StepState.SKIPPED}),
        )
        self.assertEqual(
            PlanStatus.CANCELLED,
            derive_plan_status((required,), {"required": StepState.CANCELLED}),
        )
        self.assertEqual(
            PlanStatus.RUNNING,
            derive_plan_status((required,), {"required": StepState.RUNNING}),
        )
        self.assertEqual(
            PlanStatus.PARTIAL,
            derive_plan_status((required,), {"required": StepState.PARTIAL}),
        )
        self.assertEqual(
            PlanStatus.PARTIAL,
            derive_plan_status(
                (required, optional),
                {"required": StepState.COMPLETED, "optional": StepState.FAILED},
            ),
        )
        self.assertEqual(
            PlanStatus.PARTIAL,
            derive_plan_status(
                (required,),
                {"required": StepState.COMPLETED},
                has_disagreement=True,
            ),
        )
        self.assertEqual(
            PlanStatus.COMPLETED,
            derive_plan_status((required,), {"required": StepState.COMPLETED}),
        )
        self.assertEqual(len(PlanStatusPolicy.decision_table()), 11)

    def test_failed_required_step_with_retained_eligible_result_is_partial(self) -> None:
        required = _step("required")
        self.assertEqual(
            PlanStatus.PARTIAL,
            derive_plan_status(
                (required,),
                {"required": StepState.FAILED},
                eligible_result_ids=("required",),
            ),
        )


class Phase6AggregationTests(unittest.TestCase):
    def test_disagreement_is_explicit_and_never_becomes_consensus(self) -> None:
        left = _step("left")
        right = _step("right")
        plan = _plan(left, right)
        envelopes = {
            "left": _envelope(plan, left, "The answer is alpha"),
            "right": _envelope(plan, right, "The answer is beta"),
        }

        aggregation = aggregate_plan_results(
            plan,
            step_envelopes=envelopes,
            states={"left": StepState.COMPLETED, "right": StepState.COMPLETED},
        )

        self.assertEqual(PlanStatus.PARTIAL, aggregation.status)
        self.assertEqual(1, len(aggregation.disagreements))
        record = aggregation.disagreements[0]
        self.assertEqual(("left", "right"), record.step_ids)
        self.assertEqual(("The answer is alpha", "The answer is beta"), record.statements)
        self.assertNotIn("consensus", aggregation.to_dict())

    def test_direct_finalizer_preserves_single_validated_result(self) -> None:
        step = _step("single")
        plan = _plan(step)
        aggregation = aggregate_plan_results(
            plan,
            step_results={"single": _result(answer="presentation-ready")},
            states={"single": StepState.COMPLETED},
        )

        result = DirectFinalizer().finalize(aggregation)

        self.assertEqual(TaskStatus.COMPLETED, result.task_status)
        self.assertEqual("presentation-ready", result.answer)
        self.assertEqual(OutcomeCode.SUCCESS, result.outcome_code)

    def test_partial_template_preserves_success_and_names_failed_branch(self) -> None:
        successful = _step("successful")
        optional = _step("optional", criticality=StepCriticality.OPTIONAL)
        plan = _plan(successful, optional, finalization=FinalizationStrategy.TEMPLATE)
        aggregation = aggregate_plan_results(
            plan,
            step_results={"successful": _result(answer="retained work")},
            states={"successful": StepState.COMPLETED, "optional": StepState.FAILED},
        )

        result = TemplateFinalizer().finalize(aggregation)

        self.assertEqual(TaskStatus.PARTIAL, result.task_status)
        self.assertIn("retained work", result.answer)
        self.assertIn("optional", result.answer)
        self.assertIn("partial", result.answer)
        self.assertNotEqual(TaskStatus.COMPLETED, result.task_status)

    def test_cancelled_plan_never_elevates_completed_work_to_success(self) -> None:
        step = _step("running")
        plan = _plan(step)
        aggregation = aggregate_plan_results(
            plan,
            step_results={"running": _result(answer="completed before cancellation")},
            states={"running": StepState.COMPLETED},
            cancellation_accepted=True,
        )

        result = TemplateFinalizer().finalize(aggregation)

        self.assertEqual(PlanStatus.CANCELLED, aggregation.status)
        self.assertEqual(TaskStatus.CANCELLED, result.task_status)
        self.assertIn("cancelled", result.answer)

    def test_cancelled_step_preserves_partial_work_without_promoting_output(self) -> None:
        step = _step("cancelled")
        plan = _plan(step)
        cancelled = TaskResult(
            task_id=plan.task_id,
            task_status=TaskStatus.CANCELLED,
            epistemic_status=EpistemicStatus.BLOCKED,
            validation_status=ValidationStatus.REJECTED,
            answer="untrusted cancelled answer",
            route_summary=Route.REGISTERED_CAPABILITY,
            claims=("untrusted cancelled claim",),
            citations=("https://example.invalid/cancelled",),
            partial_work=("received prefix",),
            outcome_code=OutcomeCode.CANCELLED,
        )

        aggregation = aggregate_plan_results(
            plan,
            step_results={step.step_id: cancelled},
            states={step.step_id: StepState.CANCELLED},
        )
        result = TemplateFinalizer().finalize(aggregation)

        self.assertEqual((), aggregation.eligible_step_ids)
        self.assertEqual(TaskStatus.CANCELLED, result.task_status)
        self.assertIn("received prefix", result.partial_work)
        self.assertNotIn("untrusted cancelled claim", result.claims)
        self.assertNotIn("https://example.invalid/cancelled", result.citations)
        self.assertNotEqual(TaskStatus.COMPLETED, result.task_status)

    def test_template_renders_verified_action_receipt_without_rewriting(self) -> None:
        step = _step("action")
        plan = _plan(step, finalization=FinalizationStrategy.TEMPLATE)
        receipt = ActionExecutionReceipt(
            receipt_id="receipt-phase6",
            action_digest="a" * 64,
            capability_id=step.capability_id,
            operation_id=step.operation_id,
            completed_at=datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc),
        )
        envelope = StepResultEnvelope(
            schema_version="elly.step-result.v1",
            plan_id=plan.plan_id,
            task_id=plan.task_id,
            step_id=step.step_id,
            capability_id=step.capability_id,
            operation_id=step.operation_id,
            status=TaskStatus.COMPLETED,
            summary="action completed",
            answer="action completed",
            action_receipt=receipt,
        )
        aggregation = aggregate_plan_results(
            plan,
            step_envelopes={step.step_id: envelope},
            states={step.step_id: StepState.COMPLETED},
        )

        result = TemplateFinalizer().finalize(aggregation)

        self.assertIn("receipt-phase6", result.answer)
        self.assertIn("succeeded", result.answer)
        self.assertIn("digest=" + ("a" * 64), result.answer)

    def test_public_plan_and_trace_views_are_additive_and_bounded(self) -> None:
        repository = SqliteSessionRepository(":memory:")
        self.addCleanup(repository.close)
        repository.apply_migrations()
        step = _step("view-step")
        plan = _plan(step)
        repository.save_plan(plan)
        api = EllyApplication(SimpleNamespace(repository=repository))

        view = api.get_plan(PlanQuery(plan.plan_id))
        trace = api.get_plan_trace(PlanTraceQuery(plan.plan_id))

        self.assertTrue(view.is_success)
        assert view.value is not None
        self.assertEqual(plan.plan_id, view.value.plan_id)
        self.assertEqual(StepState.PENDING, view.value.steps[0].state)
        self.assertTrue(trace.is_success)
        assert trace.value is not None
        self.assertEqual(plan.task_id, trace.value.task_id)


if __name__ == "__main__":
    unittest.main()
