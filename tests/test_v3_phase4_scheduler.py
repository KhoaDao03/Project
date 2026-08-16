"""V3 Phase 4 bounded plan scheduler tests."""

from __future__ import annotations

import threading
import time
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
    CapabilityStatus,
)
from elly.application.capability_workflow import CapabilityExecutionWorkflow
from elly.application.completion import CompletionService
from elly.application.execution import CancellationToken
from elly.application.plan_builder import PlanBuilder
from elly.application.plan_executor import PlanExecutor
from elly.application.plan_orchestrator import PlanOrchestrator
from elly.application.routing_contracts import (
    CapabilityKind,
    CapabilityRoutingDescriptor,
    OperationIntentContract,
)
from elly.domain.enums import (
    ActionCategory,
    CloudMode,
    EpistemicStatus,
    PersistenceMode,
    Route,
    TaskStatus,
    ValidationStatus,
)
from elly.domain.errors import ConflictError
from elly.domain.models import (
    ContextManifest,
    SessionRecord,
    TaskRequest,
    TaskResult,
)
from elly.planning.contracts import (
    PROPOSAL_SCHEMA_VERSION,
    ExecutionProposal,
    FinalizationStrategy,
    PlanLimitsSnapshot,
    PlanStatus,
    ProposalDisposition,
    ProposedInput,
    ProposedStep,
    StepState,
)

UTC = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)


class _Capability:
    def __init__(
        self,
        capability_id: str,
        *,
        delay: float = 0.0,
        failure: bool = False,
        external: bool = False,
        events: list[str] | None = None,
        started: threading.Event | None = None,
    ) -> None:
        self.capability_id = capability_id
        self.delay = delay
        self.failure = failure
        self.external = external
        self.events = events if events is not None else []
        self.started = started
        operation = OperationIntentContract(
            operation_id=f"{capability_id}.run",
            description=f"Run {capability_id}",
            domains=("test",),
            accepted_inputs=("text", "task_result"),
            required_entities=(),
            output_type="task_result",
            effect=ActionCategory.NONE,
        )
        self.descriptor = CapabilityDescriptor(
            capability_id=capability_id,
            description=f"{capability_id} test capability",
            routes=(Route.REGISTERED_CAPABILITY,),
            request_schema="test-v3-step-v1",
            operations=(operation.operation_id,),
            requires_external_boundary=external,
            destination="test-provider" if external else "",
            model="test-model" if external else "",
            purpose="run test capability" if external else "",
            requires_consent=external,
            routing=CapabilityRoutingDescriptor(
                capability_id=capability_id,
                description=f"{capability_id} test capability",
                operations=(operation,),
                kind=CapabilityKind.SPECIALIST,
                requires_external_access=external,
                requires_consent=external,
            ),
        )

    def status(self) -> CapabilityStatus:
        return CapabilityStatus(CapabilityAvailability.AVAILABLE)

    def can_handle(self, _request) -> CapabilityMatch:  # type: ignore[no-untyped-def]
        return CapabilityMatch(True, "TEST_MATCH")

    def prepare(self, _intent, _request) -> CapabilityPreparation:  # type: ignore[no-untyped-def]
        return CapabilityPreparation(True, "TEST_PREPARED")

    def execute(self, request) -> CapabilityExecution:  # type: ignore[no-untyped-def]
        self.events.append(f"start:{self.capability_id}")
        if self.started is not None:
            self.started.set()
        end = time.monotonic() + self.delay
        while time.monotonic() < end:
            if request.cancellation is not None:
                request.cancellation.raise_if_cancelled()
            time.sleep(0.002)
        self.events.append(f"finish:{self.capability_id}")
        status = TaskStatus.FAILED if self.failure else TaskStatus.COMPLETED
        return CapabilityExecution(
            TaskResult(
                task_id=request.task_id,
                task_status=status,
                epistemic_status=(
                    EpistemicStatus.UNKNOWN if self.failure else EpistemicStatus.INFERRED
                ),
                validation_status=(
                    ValidationStatus.REJECTED if self.failure else ValidationStatus.VALIDATED
                ),
                answer="" if self.failure else self.capability_id,
                route_summary=Route.REGISTERED_CAPABILITY,
            ),
            request.context_manifest,
        )


def _proposal(
    steps: tuple[ProposedStep, ...],
    *,
    finalization: FinalizationStrategy = FinalizationStrategy.DIRECT,
) -> ExecutionProposal:
    return ExecutionProposal(
        schema_version=PROPOSAL_SCHEMA_VERSION,
        disposition=ProposalDisposition.CAPABILITY_PLAN,
        steps=steps,
        finalization=finalization,
        ambiguities=(),
        confidence=1.0,
        reason_code="TEST_PHASE4",
    )


def _step(
    step_id: str,
    capability_id: str,
    *,
    dependencies: tuple[str, ...] = (),
    required: bool = True,
    input_reference: str = "",
) -> ProposedStep:
    inputs = (ProposedInput("text", "text"),)
    if input_reference:
        inputs = (ProposedInput("prior", "task_result", "step", input_reference),)
    return ProposedStep(
        proposal_step_id=step_id,
        capability_id=capability_id,
        operation_id=f"{capability_id}.run",
        objective=f"run the {step_id} objective",
        objective_class="analysis",
        perspective="primary",
        inputs=inputs,
        dependencies=dependencies,
        required=required,
    )


class Phase4SchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = SqliteSessionRepository(":memory:")
        self.repository.apply_migrations()
        self.repository.create_session(
            SessionRecord(
                "phase4-session",
                PersistenceMode.STORE_WITH_RETENTION,
                CloudMode.LOCAL_ONLY,
                UTC,
            )
        )
        self.clock = FixedClock(UTC)
        self.audit = StructuredAuditLog(repository=self.repository)
        self.events: list[str] = []
        self.addCleanup(self.repository.close)

    def _runtime(self, handlers: tuple[_Capability, ...], *, limits=None):
        registry = CapabilityRegistry(handlers)
        workflow = CapabilityExecutionWorkflow(
            clock=self.clock,
            capability_registry=registry,
            completion=CompletionService(
                clock=self.clock,
                repository=self.repository,
                audit=self.audit,
            ),
        )
        executor = PlanExecutor(
            repository=self.repository,
            capability_registry=registry,
            capability_workflow=workflow,
            clock=self.clock,
        )
        return PlanOrchestrator(
            repository=self.repository,
            executor=executor,
            clock=self.clock,
        ), registry

    def _plan(
        self,
        registry: CapabilityRegistry,
        proposal: ExecutionProposal,
        task_id: str,
        *,
        limits=None,
    ):
        return PlanBuilder(
            registry.routing_catalog(),
            limits or PlanLimitsSnapshot(max_specialist_executions=4),
        ).build(proposal, task_id)

    def _request(self, request_id: str = "phase4-request") -> TaskRequest:
        return TaskRequest(
            request_id=request_id,
            session_id="phase4-session",
            text="public test request",
            cloud_mode=CloudMode.LOCAL_ONLY,
            persistence_mode=PersistenceMode.STORE_WITH_RETENTION,
            submitted_at=UTC,
        )

    def _execute(self, plan, orchestrator, request_id="phase4-request", token=None):
        return orchestrator.execute(
            plan,
            request=self._request(request_id),
            context_text="public test context",
            context_manifest=ContextManifest((), {}, 32, 4),
            cancellation=token,
        )

    def test_one_step_execution_persists_transitions_and_uses_registry(self) -> None:
        handler = _Capability("alpha", events=self.events)
        orchestrator, registry = self._runtime((handler,))
        plan = self._plan(registry, _proposal((_step("alpha-step", "alpha"),)), "task-phase4-one")
        self.repository.save_plan(plan, at=UTC)

        result = self._execute(plan, orchestrator)

        self.assertEqual(TaskStatus.COMPLETED, result.step_results["alpha-step"].task_status)
        self.assertEqual("completed", result.status.value)
        self.assertEqual(("start:alpha", "finish:alpha"), tuple(self.events))
        stored = self.repository.get_plan(plan.plan_id)
        self.assertIsNotNone(stored)
        self.assertEqual(StepState.COMPLETED, stored.steps[0].state)  # type: ignore[union-attr]
        self.assertTrue(
            any(
                event.event_type == "step.transition"
                for event in self.repository.plan_events(plan.plan_id)
            )
        )

    def test_dependencies_execute_in_order_and_receive_declared_result(self) -> None:
        first = _Capability("first", events=self.events)
        second = _Capability("second", events=self.events)
        orchestrator, registry = self._runtime((first, second))
        plan = self._plan(
            registry,
            _proposal(
                (
                    _step(
                        "second-step",
                        "second",
                        dependencies=("first-step",),
                        input_reference="first-step",
                    ),
                    _step("first-step", "first"),
                )
            ),
            "task-phase4-linear",
        )
        self.repository.save_plan(plan, at=UTC)

        result = self._execute(plan, orchestrator, "phase4-linear")

        self.assertEqual(TaskStatus.COMPLETED, result.status)
        self.assertEqual(
            ("start:first", "finish:first", "start:second", "finish:second"), tuple(self.events)
        )

    def test_independent_ready_steps_are_bounded_and_parallel(self) -> None:
        left = _Capability("left", delay=0.12, events=self.events)
        right = _Capability("right", delay=0.12, events=self.events)
        orchestrator, registry = self._runtime((left, right))
        plan = self._plan(
            registry,
            _proposal((_step("left-step", "left"), _step("right-step", "right"))),
            "task-phase4-parallel",
            limits=PlanLimitsSnapshot(max_specialist_executions=2, max_parallel_steps=2),
        )
        self.repository.save_plan(plan, at=UTC)
        started = time.monotonic()

        result = self._execute(plan, orchestrator, "phase4-parallel")

        self.assertEqual(TaskStatus.COMPLETED, result.status)
        self.assertLess(time.monotonic() - started, 0.22)
        self.assertEqual(2, sum(item.startswith("start:") for item in self.events))

    def test_mandatory_failure_skips_descendant(self) -> None:
        failing = _Capability("failing", failure=True, events=self.events)
        dependent = _Capability("dependent", events=self.events)
        orchestrator, registry = self._runtime((failing, dependent))
        plan = self._plan(
            registry,
            _proposal(
                (
                    _step(
                        "dependent-step",
                        "dependent",
                        dependencies=("failing-step",),
                        input_reference="failing-step",
                    ),
                    _step("failing-step", "failing"),
                )
            ),
            "task-phase4-failure",
        )
        self.repository.save_plan(plan, at=UTC)

        result = self._execute(plan, orchestrator, "phase4-failure")

        self.assertEqual("failed", result.status.value)
        stored = self.repository.get_plan(plan.plan_id)
        self.assertEqual(StepState.SKIPPED, stored.steps[1].state)  # type: ignore[union-attr]
        self.assertNotIn("start:dependent", self.events)

    def test_optional_failure_keeps_independent_work_and_returns_partial(self) -> None:
        optional = _Capability("optional", failure=True, events=self.events)
        required = _Capability("required", events=self.events)
        orchestrator, registry = self._runtime((optional, required))
        plan = self._plan(
            registry,
            _proposal(
                (
                    _step("optional-step", "optional", required=False),
                    _step("required-step", "required"),
                )
            ),
            "task-phase4-optional",
            limits=PlanLimitsSnapshot(max_specialist_executions=2),
        )
        self.repository.save_plan(plan, at=UTC)

        result = self._execute(plan, orchestrator, "phase4-optional")

        self.assertEqual("partial", result.status.value)
        self.assertEqual(TaskStatus.COMPLETED, result.step_results["required-step"].task_status)

    def test_cancellation_prevents_new_steps_and_cancels_in_progress_work(self) -> None:
        started = threading.Event()
        running = _Capability("running", delay=1.0, events=self.events, started=started)
        queued = _Capability("queued", events=self.events)
        orchestrator, registry = self._runtime((running, queued))
        plan = self._plan(
            registry,
            _proposal(
                (
                    _step("running-step", "running"),
                    _step(
                        "queued-step",
                        "queued",
                        dependencies=("running-step",),
                        input_reference="running-step",
                    ),
                )
            ),
            "task-phase4-cancel",
            limits=PlanLimitsSnapshot(
                max_specialist_executions=2,
                max_concurrency=1,
                max_parallel_steps=1,
            ),
        )
        self.repository.save_plan(plan, at=UTC)
        token = CancellationToken()
        outcome: list[object] = []

        thread = threading.Thread(
            target=lambda: outcome.append(
                self._execute(plan, orchestrator, "phase4-cancel", token)
            ),
            daemon=True,
        )
        thread.start()
        self.assertTrue(started.wait(1.0))
        token.cancel()
        thread.join(2.0)
        self.assertFalse(thread.is_alive())
        self.assertEqual(1, len(outcome))
        result = outcome[0]
        self.assertEqual("cancelled", result.status.value)  # type: ignore[union-attr]
        self.assertNotIn("start:queued", self.events)

    def test_timeout_is_bounded_and_does_not_wait_for_a_late_worker(self) -> None:
        handler = _Capability("slow", delay=0.3, events=self.events)
        orchestrator, registry = self._runtime((handler,))
        plan = self._plan(
            registry,
            _proposal((_step("slow-step", "slow"),)),
            "task-phase4-timeout",
            limits=PlanLimitsSnapshot(
                max_step_timeout_seconds=0.03,
                max_total_timeout_seconds=0.5,
            ),
        )
        self.repository.save_plan(plan, at=UTC)
        started = time.monotonic()

        result = self._execute(plan, orchestrator, "phase4-timeout")

        self.assertLess(time.monotonic() - started, 0.18)
        self.assertEqual("failed", result.status.value)
        self.assertEqual(StepState.FAILED, result.plan.steps[0].state)

    def test_external_authorization_denial_blocks_without_dispatch(self) -> None:
        handler = _Capability("cloud", external=True, events=self.events)
        orchestrator, registry = self._runtime((handler,))
        plan = self._plan(
            registry,
            _proposal((_step("cloud-step", "cloud"),)),
            "task-phase4-auth",
        )
        self.repository.save_plan(plan, at=UTC)

        result = self._execute(plan, orchestrator, "phase4-auth")

        self.assertEqual("blocked", result.status.value)
        self.assertEqual(StepState.BLOCKED, result.plan.steps[0].state)
        self.assertNotIn("start:cloud", self.events)

    def test_persisted_transitions_use_compare_and_set(self) -> None:
        handler = _Capability("cas")
        _, registry = self._runtime((handler,))
        plan = self._plan(registry, _proposal((_step("cas-step", "cas"),)), "task-phase4-cas")
        self.repository.save_plan(plan, at=UTC)

        self.repository.transition_plan(
            plan.plan_id,
            PlanStatus.RUNNING,
            expected_status=PlanStatus.PENDING,
            at=UTC,
        )
        with self.assertRaises(ConflictError):
            self.repository.transition_plan(
                plan.plan_id,
                PlanStatus.COMPLETED,
                expected_status=PlanStatus.PENDING,
                at=UTC,
            )


if __name__ == "__main__":
    unittest.main()
