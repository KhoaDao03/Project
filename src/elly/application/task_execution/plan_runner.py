"""DAG scheduling, bounded concurrency, and plan state transitions."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from threading import RLock
from typing import cast

from elly.application.capabilities import CapabilityKind, CapabilityRegistry
from elly.application.capability_workflow import CapabilityExecutionWorkflow
from elly.application.execution import CancellationToken
from elly.application.plan_results import (
    aggregate_plan_results,
    derive_plan_status,
)
from elly.application.plan_state import STEP_ELIGIBLE_STATES, STEP_TERMINAL_STATES
from elly.application.recovery import PlanRecovery
from elly.application.response_composer import compose_blocked, compose_cancelled, compose_failed
from elly.application.response_pipeline import ResponseCompositionService
from elly.application.step_results import StepResultEnvelope, normalize_step_result
from elly.domain.enums import ActionCategory, OutcomeCode, Route, TaskStatus
from elly.domain.errors import ConfigInvalidError, ConflictError, InputInvalidError
from elly.domain.models import (
    ActionConfirmationProposal,
    ContextManifest,
    OperationLease,
    TaskRequest,
    TaskResult,
)
from elly.guardrails.controller import GuardrailController
from elly.planning.contracts import (
    AuthorizationState,
    ExecutionPlan,
    PlanLimitsSnapshot,
    PlanStatus,
    PlanStep,
    StepCriticality,
    StepKind,
    StepState,
)
from elly.ports.clock import ClockPort
from elly.ports.local_response_composer import LocalResponseComposerPort
from elly.ports.plan_repository import PlanRepositoryPort
from elly.privacy import ConsentProposal

from .contracts import PlanExecutionRequest, PlanExecutionResult
from .finalizer import PlanFinalizer
from .step_runner import StepRunner, _StepCallResult, _StepInputError


def _request_for_plan(plan: ExecutionPlan) -> TaskRequest:
    """Construct a conservative convenience request for direct unit callers."""

    raise InputInvalidError(f"plan {plan.plan_id} requires a TaskRequest and execution context")


class _NonBlockingThreadPoolExecutor(ThreadPoolExecutor):
    """Pool whose shutdown does not turn a step timeout into a hard wait."""

    def __exit__(self, exc_type, exc_value, traceback):  # type: ignore[no-untyped-def]
        self.shutdown(wait=False, cancel_futures=True)
        return False

@dataclass
class _RunningStep:
    step: PlanStep
    future: Future["_StepCallResult"]
    cancellation: CancellationToken
    started_monotonic: float
    lease: OperationLease | None
    dispatch_state: dict[str, bool]
    dispatched: bool = False


class PlanRunner:
    """Own plan state, dependency scheduling, bounds, and cancellation propagation."""

    def __init__(
        self,
        *,
        repository: PlanRepositoryPort,
        capability_registry: CapabilityRegistry,
        capability_workflow: CapabilityExecutionWorkflow,
        clock: ClockPort,
        max_workers: int | None = None,
        response_composer_port: LocalResponseComposerPort | None = None,
        response_composer_max_output_tokens: int = 1600,
        response_composer_timeout_seconds: float = 120.0,
        response_pipeline: ResponseCompositionService | None = None,
    ) -> None:
        if not isinstance(capability_registry, CapabilityRegistry):
            raise ConfigInvalidError("task execution requires a capability registry")
        if not isinstance(capability_workflow, CapabilityExecutionWorkflow):
            raise ConfigInvalidError("task execution requires the capability workflow")
        if not isinstance(clock, ClockPort):
            raise ConfigInvalidError("task execution requires a clock")
        if max_workers is not None and (
            isinstance(max_workers, bool) or not isinstance(max_workers, int) or max_workers <= 0
        ):
            raise ConfigInvalidError("task execution max_workers must be positive")
        if response_composer_port is not None and not isinstance(
            response_composer_port, LocalResponseComposerPort
        ):
            raise ConfigInvalidError("task execution response composer port is invalid")
        if response_pipeline is not None and not isinstance(
            response_pipeline, ResponseCompositionService
        ):
            raise ConfigInvalidError("task execution response pipeline is invalid")
        if (
            isinstance(response_composer_max_output_tokens, bool)
            or not isinstance(response_composer_max_output_tokens, int)
            or response_composer_max_output_tokens <= 0
        ):
            raise ConfigInvalidError(
                "task execution response composer output limit must be positive"
            )
        if (
            isinstance(response_composer_timeout_seconds, bool)
            or not isinstance(response_composer_timeout_seconds, (int, float))
            or response_composer_timeout_seconds <= 0
        ):
            raise ConfigInvalidError(
                "task execution response composer timeout must be positive"
            )
        self._repository = repository
        self._clock = clock
        self._max_workers = max_workers
        resolved_response_pipeline = response_pipeline or ResponseCompositionService(
            composer=response_composer_port,
            max_output_tokens=response_composer_max_output_tokens,
            timeout_seconds=response_composer_timeout_seconds,
        )
        self._finalizer = PlanFinalizer(
            repository=repository,
            response_pipeline=resolved_response_pipeline,
            clock=clock,
        )
        self._step_runner = StepRunner(
            repository=repository,
            capability_registry=capability_registry,
            capability_workflow=capability_workflow,
            clock=clock,
        )
        self._run_lock = RLock()
        self._last_plan: ExecutionPlan | None = None

    def execute(
        self,
        plan: ExecutionPlan,
        execution: PlanExecutionRequest | None = None,
        *,
        request: TaskRequest | None = None,
        context_text: str | None = None,
        context_manifest: ContextManifest | None = None,
        cancellation: CancellationToken | None = None,
        request_guardrails: GuardrailController | None = None,
    ) -> PlanExecutionResult:
        """Run one persisted plan until every step is terminal.

        ``execution`` is the preferred typed entry point.  The keyword form is
        kept as a small convenience for application adapters and tests.
        """
        if not isinstance(plan, ExecutionPlan):
            raise InputInvalidError("plan execution requires an ExecutionPlan")
        execution = execution or PlanExecutionRequest(
            request=request if request is not None else _request_for_plan(plan),
            context_text=context_text or plan.task_id,
            context_manifest=context_manifest or ContextManifest((), {}, 0, 0),
            cancellation=cancellation,
            request_guardrails=request_guardrails,
        )
        token = execution.cancellation or CancellationToken()
        # SQLite transition CAS makes one plan safe across workers.  A small
        # per-executor lock also protects the in-memory fallback state used by
        # contract-test repositories that implement only the Phase 3 port.
        with self._run_lock:
            return self._run(plan, execution, token)

    run = execute

    def _run(
        self,
        plan: ExecutionPlan,
        execution: PlanExecutionRequest,
        cancellation: CancellationToken,
    ) -> PlanExecutionResult:
        working_plan = plan
        self._last_plan = plan
        state_lock = RLock()
        states: dict[str, StepState] = {step.step_id: step.state for step in plan.steps}
        results: dict[str, TaskResult] = {}
        envelopes: dict[str, StepResultEnvelope] = {}
        for step in plan.steps:
            stored = self._step_runner.get_result(plan.plan_id, step.step_id)
            if stored is not None:
                results[step.step_id] = stored
            stored_envelope = self._step_runner.get_envelope(plan.plan_id, step.step_id)
            if stored_envelope is not None:
                envelopes[step.step_id] = stored_envelope
            elif stored is not None and step.kind is StepKind.CAPABILITY:
                # V3 Phase 3/4 rows used the legacy TaskResult payload.  The
                # first V3.5 read upgrades that safe, provider-neutral shape
                # before any dependent step can consume it.
                migrated = normalize_step_result(
                    stored,
                    plan_id=plan.plan_id,
                    task_id=plan.task_id,
                    step_id=step.step_id,
                    capability_id=step.capability_id,
                    operation_id=step.operation_id,
                )
                envelopes[step.step_id] = migrated
                self._step_runner.save_result(plan, step, stored, envelope=migrated)

        if working_plan.status in {
            PlanStatus.COMPLETED,
            PlanStatus.PARTIAL,
            PlanStatus.BLOCKED,
            PlanStatus.FAILED,
            PlanStatus.UNAVAILABLE,
            PlanStatus.CANCELLED,
            PlanStatus.INTERRUPTED,
        }:
            aggregation = aggregate_plan_results(
                working_plan,
                results,
                envelopes,
                states=states,
                cancellation_accepted=working_plan.status is PlanStatus.CANCELLED,
            )
            final_result = self._finalizer.finalize(aggregation, execution, cancellation)
            return PlanExecutionResult(
                working_plan,
                results,
                "PLAN_ALREADY_TERMINAL",
                envelopes,
                aggregation,
                final_result,
            )

        # A restart must not silently reissue a step whose provider dispatch is
        # uncertain. Local/read-only work is the only active work eligible for
        # a bounded retry; external or consequential work remains interrupted.
        for step in plan.steps:
            if states[step.step_id] in {StepState.AUTHORIZING, StepState.RUNNING}:
                target = (
                    StepState.PENDING
                    if PlanRecovery.is_retryable_local(step)
                    else StepState.INTERRUPTED
                )
                reason = (
                    "PLAN_RECOVERY_LOCAL_RETRY"
                    if target is StepState.PENDING
                    else "PLAN_RECOVERY_EXTERNAL_UNCERTAIN"
                )
                reconcile = getattr(self._repository, "reconcile_step", None)
                with state_lock:
                    if callable(reconcile):
                        updated = reconcile(
                            working_plan.plan_id,
                            step.step_id,
                            target,
                            expected_state=states[step.step_id],
                            reason_code=reason,
                            at=self._clock.now(),
                        )
                    else:
                        if states[step.step_id] is not step.state:
                            raise ConflictError("plan step state changed before recovery")
                        updated = replace(
                            working_plan,
                            steps=tuple(
                                replace(item, state=target)
                                if item.step_id == step.step_id
                                else item
                                for item in working_plan.steps
                            ),
                        )
                    states[step.step_id] = target
                    self._last_plan = updated
                working_plan = self._last_plan

        if working_plan.status is PlanStatus.PENDING:
            working_plan = self._transition_plan(
                working_plan,
                PlanStatus.RUNNING,
                expected_status=PlanStatus.PENDING,
                reason_code="PLAN_EXECUTION_STARTED",
            )
            self._last_plan = working_plan

        limits = working_plan.limits
        worker_count = min(limits.max_concurrency, limits.max_parallel_steps)
        if self._max_workers is not None:
            worker_count = min(worker_count, self._max_workers)
        if worker_count <= 0:
            raise ConfigInvalidError("plan has no executable concurrency capacity")

        running: dict[Future[_StepCallResult], _RunningStep] = {}
        reserved_specialists = 0
        reserved_research = 0
        reserved_synthesis = 0
        reserved_provider_calls = 0
        started_at = time.monotonic()
        deadline = started_at + limits.max_total_timeout_seconds
        cancelled_at: float | None = None
        plan_cancelled = False
        deadline_expired = False
        consent_proposal: ConsentProposal | None = None
        action_confirmation: ActionConfirmationProposal | None = None
        authorization_paused = False

        with _NonBlockingThreadPoolExecutor(
            max_workers=worker_count, thread_name_prefix="elly-plan"
        ) as pool:
            while True:
                now = time.monotonic()
                if cancellation.cancelled and cancelled_at is None:
                    cancelled_at = now
                    plan_cancelled = True
                    for item in running.values():
                        item.cancellation.cancel()
                    for step in working_plan.steps:
                        if states[step.step_id] in {
                            StepState.PENDING,
                            StepState.READY,
                        }:
                            self._transition_step(
                                working_plan,
                                step,
                                StepState.CANCELLED,
                                expected_state=states[step.step_id],
                                reason_code="PLAN_CANCELLED_BEFORE_DISPATCH",
                                states=states,
                                state_lock=state_lock,
                            )
                            working_plan = self._last_plan

                if cancelled_at is None and now >= deadline:
                    cancelled_at = now
                    deadline_expired = True
                    for item in running.values():
                        item.cancellation.cancel()
                    for step in working_plan.steps:
                        if states[step.step_id] in {
                            StepState.PENDING,
                            StepState.READY,
                        }:
                            self._transition_step(
                                working_plan,
                                step,
                                StepState.FAILED,
                                expected_state=states[step.step_id],
                                reason_code="PLAN_TOTAL_TIMEOUT",
                                states=states,
                                state_lock=state_lock,
                            )
                            working_plan = self._last_plan
                            timeout_result = compose_failed(
                                task_id=working_plan.task_id,
                                reason="plan total timeout exceeded",
                                route=Route.REGISTERED_CAPABILITY,
                            )
                            results[step.step_id] = timeout_result
                            self._step_runner.save_result(working_plan, step, timeout_result)

                # Exact consent and consequential-action confirmation suspend
                # the whole plan. Already-running siblings may finish, but no
                # further provider dispatch is allowed after the pause becomes
                # observable. Remaining steps are marked with a resumable,
                # persisted state so the same plan revision can continue.
                if authorization_paused and not running:
                    for step in working_plan.steps:
                        if states[step.step_id] in {StepState.PENDING, StepState.READY}:
                            self._transition_step(
                                working_plan,
                                step,
                                StepState.BLOCKED,
                                expected_state=states[step.step_id],
                                reason_code="PLAN_AWAITING_AUTHORIZATION",
                                states=states,
                                state_lock=state_lock,
                            )
                            working_plan = self._last_plan
                    break

                working_plan = self._skip_failed_descendants(
                    working_plan, states, results, state_lock
                )

                if cancelled_at is None:
                    for step in sorted(working_plan.steps, key=lambda item: item.step_id):
                        if len(running) >= worker_count:
                            break
                        if states[step.step_id] is not StepState.PENDING:
                            continue
                        if not self._dependencies_ready(step, working_plan.steps, states):
                            continue
                        # The public outcome carries one exact authorization
                        # proposal at a time. Serialize consent/consequential
                        # authorization boundaries so parallel ready work can
                        # never orphan a second proposal or resume the wrong
                        # step/revision.
                        step_may_pause = (
                            step.requires_consent
                            or step.effect is not ActionCategory.NONE
                        )
                        running_may_pause = any(
                            item.step.requires_consent
                            or item.step.effect is not ActionCategory.NONE
                            for item in running.values()
                        )
                        if running and (step_may_pause or running_may_pause):
                            continue

                        self._transition_step(
                            working_plan,
                            step,
                            StepState.READY,
                            expected_state=StepState.PENDING,
                            reason_code="STEP_READY",
                            states=states,
                            state_lock=state_lock,
                        )
                        working_plan = self._last_plan
                        try:
                            payload = self._step_runner.resolve_inputs(
                                step,
                                execution,
                                results,
                                envelopes,
                            )
                        except _StepInputError as exc:
                            result = compose_blocked(
                                task_id=working_plan.task_id,
                                reason=exc.summary,
                                route=Route.REGISTERED_CAPABILITY,
                                outcome_code=OutcomeCode.BLOCKED,
                            )
                            results[step.step_id] = result
                            self._step_runner.save_result(working_plan, step, result)
                            self._transition_step(
                                working_plan,
                                step,
                                StepState.BLOCKED,
                                expected_state=StepState.READY,
                                authorization_state=AuthorizationState.DENIED,
                                reason_code="STEP_INPUT_REJECTED",
                                states=states,
                                state_lock=state_lock,
                            )
                            working_plan = self._last_plan
                            continue

                        live_handler = self._step_runner.live_handler(step)
                        if isinstance(live_handler, str):
                            result = compose_blocked(
                                task_id=working_plan.task_id,
                                reason=live_handler,
                                route=Route.REGISTERED_CAPABILITY,
                                outcome_code=OutcomeCode.UNAVAILABLE,
                            )
                            results[step.step_id] = result
                            self._step_runner.save_result(working_plan, step, result)
                            self._transition_step(
                                working_plan,
                                step,
                                StepState.UNAVAILABLE,
                                expected_state=StepState.READY,
                                reason_code="CAPABILITY_UNAVAILABLE",
                                states=states,
                                state_lock=state_lock,
                            )
                            working_plan = self._last_plan
                            continue

                        kind = self._step_runner.capability_kind(step, live_handler)
                        limit_reason = self._reserve_execution(
                            kind,
                            step,
                            reserved_specialists,
                            reserved_research,
                            reserved_synthesis,
                            reserved_provider_calls,
                            limits,
                        )
                        if limit_reason is not None:
                            result = compose_blocked(
                                task_id=working_plan.task_id,
                                reason=limit_reason,
                                route=Route.REGISTERED_CAPABILITY,
                                outcome_code=OutcomeCode.BLOCKED,
                            )
                            results[step.step_id] = result
                            self._step_runner.save_result(working_plan, step, result)
                            self._transition_step(
                                working_plan,
                                step,
                                StepState.BLOCKED,
                                expected_state=StepState.READY,
                                reason_code="PLAN_LIMIT_REACHED",
                                states=states,
                                state_lock=state_lock,
                            )
                            working_plan = self._last_plan
                            continue

                        if kind is CapabilityKind.SPECIALIST:
                            reserved_specialists += 1
                        elif kind is CapabilityKind.RESEARCH:
                            reserved_research += 1
                        elif step.kind is StepKind.LOCAL_SYNTHESIS:
                            reserved_synthesis += 1
                        if step.requires_external_access:
                            reserved_provider_calls += 1

                        self._transition_step(
                            working_plan,
                            step,
                            StepState.AUTHORIZING,
                            expected_state=StepState.READY,
                            reason_code="STEP_AUTHORIZATION_STARTED",
                            states=states,
                            state_lock=state_lock,
                        )
                        working_plan = self._last_plan
                        lease = (
                            self._step_runner.claim_lease(
                                working_plan, step, payload, execution
                            )
                            if step.kind is StepKind.CAPABILITY
                            else None
                        )
                        if lease is not None and not lease.fresh:
                            result = compose_blocked(
                                task_id=working_plan.task_id,
                                reason="operation already has a recorded execution",
                                route=Route.REGISTERED_CAPABILITY,
                                outcome_code=OutcomeCode.POSSIBLE_DUPLICATE_EXECUTION,
                            )
                            results[step.step_id] = result
                            self._step_runner.save_result(working_plan, step, result)
                            self._transition_step(
                                working_plan,
                                step,
                                StepState.BLOCKED,
                                expected_state=StepState.AUTHORIZING,
                                authorization_state=AuthorizationState.DENIED,
                                reason_code="OPERATION_LEASE_NOT_FRESH",
                                states=states,
                                state_lock=state_lock,
                            )
                            working_plan = self._last_plan
                            continue

                        step_token = CancellationToken()
                        unregister = cancellation.register(step_token.cancel)
                        dispatch_state = {"started": False}

                        def mark_running(
                            step: PlanStep = step,
                            step_token: CancellationToken = step_token,
                        ) -> None:
                            step_token.raise_if_cancelled()
                            dispatch_state["started"] = True
                            self._transition_step(
                                working_plan,
                                step,
                                StepState.RUNNING,
                                expected_state=StepState.AUTHORIZING,
                                authorization_state=(
                                    AuthorizationState.NOT_REQUIRED
                                    if step.kind is StepKind.LOCAL_SYNTHESIS
                                    else AuthorizationState.APPROVED
                                ),
                                reason_code="STEP_DISPATCH_LEASED",
                                states=states,
                                state_lock=state_lock,
                            )

                        future = pool.submit(
                            self._step_runner.call,
                            working_plan,
                            step,
                            execution,
                            payload,
                            results,
                            envelopes,
                            step_token,
                            lease,
                            mark_running,
                        )

                        # The callback is intentionally retained on the future
                        # so its token unregisters even if the worker fails
                        # before returning a result.
                        def release_step_token(
                            _future: Future[_StepCallResult],
                            done: Callable[[], None] = unregister,
                        ) -> None:
                            done()

                        future.add_done_callback(release_step_token)
                        running[future] = _RunningStep(
                            step=step,
                            future=future,
                            cancellation=step_token,
                            started_monotonic=time.monotonic(),
                            lease=lease,
                            dispatch_state=dispatch_state,
                        )

                        # The callback updates the persisted plan from a worker
                        # thread. Refresh the local immutable snapshot so the
                        # next dependency check sees the transition.
                        if states[step.step_id] is StepState.RUNNING:
                            working_plan = self._last_plan

                if not running:
                    if all(
                        states[step.step_id] in STEP_TERMINAL_STATES for step in working_plan.steps
                    ):
                        break
                    if cancelled_at is not None:
                        for step in working_plan.steps:
                            if states[step.step_id] not in STEP_TERMINAL_STATES:
                                target = StepState.CANCELLED
                                self._transition_step(
                                    working_plan,
                                    step,
                                    target,
                                    expected_state=states[step.step_id],
                                    reason_code="PLAN_CANCELLED",
                                    states=states,
                                    state_lock=state_lock,
                                )
                                working_plan = self._last_plan
                        break
                    # A structurally valid plan should always make progress.
                    # If live availability or a stale persisted state prevents
                    # that, terminate safely instead of spinning indefinitely.
                    for step in working_plan.steps:
                        if states[step.step_id] not in STEP_TERMINAL_STATES:
                            result = compose_failed(
                                task_id=working_plan.task_id,
                                reason="plan scheduler made no progress",
                                route=Route.REGISTERED_CAPABILITY,
                            )
                            results[step.step_id] = result
                            self._step_runner.save_result(working_plan, step, result)
                            self._transition_step(
                                working_plan,
                                step,
                                StepState.FAILED,
                                expected_state=states[step.step_id],
                                reason_code="SCHEDULER_NO_PROGRESS",
                                states=states,
                                state_lock=state_lock,
                            )
                            working_plan = self._last_plan
                    break

                timeout = self._wait_timeout(running, deadline, cancelled_at)
                done, _ = wait(tuple(running), timeout=timeout, return_when=FIRST_COMPLETED)
                now = time.monotonic()
                for future, item in tuple(running.items()):
                    if (
                        future not in done
                        and now - item.started_monotonic >= item.step.timeout_seconds
                    ):
                        item.cancellation.cancel()
                        future.cancel()
                        running.pop(future, None)
                        result = compose_failed(
                            task_id=working_plan.task_id,
                            reason="step timeout exceeded",
                            route=Route.REGISTERED_CAPABILITY,
                        )
                        item.dispatched = item.dispatch_state["started"]
                        results[item.step.step_id] = result
                        self._step_runner.save_result(working_plan, item.step, result)
                        self._step_runner.finish_lease(
                            item.lease, dispatched=item.dispatched
                        )
                        expected = (
                            StepState.RUNNING
                            if states[item.step.step_id] is StepState.RUNNING
                            else StepState.AUTHORIZING
                        )
                        self._transition_step(
                            working_plan,
                            item.step,
                            StepState.FAILED,
                            expected_state=expected,
                            reason_code="STEP_TIMEOUT",
                            states=states,
                            state_lock=state_lock,
                        )
                        working_plan = self._last_plan
                for future in tuple(done):
                    item = running.pop(future)
                    call_result = self._step_runner.future_result(
                        future, working_plan.task_id
                    )
                    result = call_result.result
                    if call_result.consent_proposal is not None:
                        consent_proposal = call_result.consent_proposal
                        authorization_paused = True
                    if call_result.action_confirmation is not None:
                        action_confirmation = call_result.action_confirmation
                        authorization_paused = True
                    item.dispatched = item.dispatch_state["started"]
                    cancellation_wins = plan_cancelled
                    if deadline_expired:
                        result = compose_failed(
                            task_id=working_plan.task_id,
                            reason="plan total timeout exceeded",
                            route=Route.REGISTERED_CAPABILITY,
                        )
                    elif cancellation_wins:
                        result = compose_cancelled(
                            task_id=working_plan.task_id,
                            partial_work="plan cancellation accepted",
                            route=Route.REGISTERED_CAPABILITY,
                        )
                    results[item.step.step_id] = result
                    if (
                        call_result.envelope is not None
                        and not cancellation_wins
                        and not deadline_expired
                    ):
                        envelopes[item.step.step_id] = call_result.envelope
                    self._step_runner.save_result(
                        working_plan,
                        item.step,
                        result,
                        envelope=(
                            call_result.envelope
                            if not cancellation_wins and not deadline_expired
                            else None
                        ),
                    )
                    target = self._step_runner.state_for_result(result)
                    self._step_runner.finish_lease(
                        item.lease,
                        dispatched=item.dispatched,
                        success=target in STEP_ELIGIBLE_STATES,
                    )
                    expected = (
                        StepState.RUNNING
                        if states[item.step.step_id] is StepState.RUNNING
                        else StepState.AUTHORIZING
                    )
                    self._transition_step(
                        working_plan,
                        item.step,
                        target,
                        expected_state=expected,
                        authorization_state=(
                            AuthorizationState.DENIED
                            if target in {StepState.BLOCKED, StepState.UNAVAILABLE}
                            else None
                        ),
                        reason_code=self._step_runner.reason_for_result(result, target),
                        states=states,
                        state_lock=state_lock,
                    )
                    working_plan = self._last_plan

        if authorization_paused:
            if working_plan.status is PlanStatus.RUNNING:
                working_plan = self._transition_plan(
                    working_plan,
                    PlanStatus.BLOCKED,
                    expected_status=PlanStatus.RUNNING,
                    reason_code="PLAN_AWAITING_AUTHORIZATION",
                )
            waiting_result = next(
                (
                    result
                    for result in results.values()
                    if result.task_status
                    in {TaskStatus.AWAITING_CONSENT, TaskStatus.AWAITING_CONFIRMATION}
                ),
                None,
            )
            return PlanExecutionResult(
                working_plan,
                results,
                "PLAN_AWAITING_AUTHORIZATION",
                envelopes,
                final_result=waiting_result,
                consent_proposal=consent_proposal,
                action_confirmation=action_confirmation,
            )

        aggregation = aggregate_plan_results(
            working_plan,
            results,
            envelopes,
            states=states,
            cancellation_accepted=plan_cancelled,
        )
        final_status = aggregation.status
        if working_plan.status is PlanStatus.RUNNING:
            working_plan = self._transition_plan(
                working_plan,
                final_status,
                expected_status=PlanStatus.RUNNING,
                reason_code=f"PLAN_{final_status.value.upper()}",
            )
        if aggregation.plan is not working_plan:
            # The immutable plan snapshot carries the final persisted status;
            # the aggregate keeps the pure derived status and all step data.
            aggregation = aggregate_plan_results(
                working_plan,
                results,
                envelopes,
                states=states,
                cancellation_accepted=plan_cancelled,
            )
        final_result = self._finalizer.finalize(aggregation, execution, cancellation)
        return PlanExecutionResult(
            working_plan,
            results,
            f"PLAN_{final_status.value.upper()}",
            envelopes,
            aggregation,
            final_result,
        )

    @staticmethod
    def _reserve_execution(
        kind: CapabilityKind,
        step: PlanStep,
        specialists: int,
        research: int,
        synthesis: int,
        provider_calls: int,
        limits: PlanLimitsSnapshot,
    ) -> str | None:
        if step.kind is StepKind.LOCAL_SYNTHESIS:
            if synthesis >= limits.max_synthesis_executions:
                return "maximum local synthesis executions reached"
            return None
        if kind is CapabilityKind.SPECIALIST and specialists >= limits.max_specialist_executions:
            return "maximum specialist executions reached"
        if kind is CapabilityKind.RESEARCH and research >= limits.max_research_executions:
            return "maximum research executions reached"
        if step.requires_external_access and provider_calls >= limits.max_provider_calls:
            return "maximum provider calls reached"
        return None

    @staticmethod
    def _dependencies_ready(
        step: PlanStep,
        all_steps: tuple[PlanStep, ...],
        states: Mapping[str, StepState],
    ) -> bool:
        by_id = {item.step_id: item for item in all_steps}
        return all(
            states[dependency] in STEP_TERMINAL_STATES
            for dependency in step.dependencies
            if dependency in by_id
        ) and all(
            states[dependency] in STEP_ELIGIBLE_STATES
            for dependency in step.dependencies
            if PlanRunner._dependency_required(step, by_id[dependency])
        )

    @staticmethod
    def _dependency_required(step: PlanStep, dependency: PlanStep) -> bool:
        return dependency.criticality is StepCriticality.REQUIRED or any(
            item.source == "step" and item.reference == dependency.step_id and item.required
            for item in step.inputs
        )

    def _skip_failed_descendants(
        self,
        plan: ExecutionPlan,
        states: dict[str, StepState],
        results: dict[str, TaskResult],
        state_lock: RLock,
    ) -> ExecutionPlan:
        working = plan
        by_id = {step.step_id: step for step in plan.steps}
        changed = True
        while changed:
            changed = False
            for step in sorted(plan.steps, key=lambda item: item.step_id):
                if states[step.step_id] not in {StepState.PENDING, StepState.READY}:
                    continue
                if not any(
                    states[dependency]
                    in {
                        StepState.FAILED,
                        StepState.BLOCKED,
                        StepState.UNAVAILABLE,
                        StepState.SKIPPED,
                        StepState.INTERRUPTED,
                    }
                    and self._dependency_required(step, by_id[dependency])
                    for dependency in step.dependencies
                ):
                    continue
                self._transition_step(
                    working,
                    step,
                    StepState.SKIPPED,
                    expected_state=states[step.step_id],
                    reason_code="MANDATORY_DEPENDENCY_FAILED",
                    states=states,
                    state_lock=state_lock,
                )
                if self._last_plan is None:
                    raise ConflictError("plan transition did not produce an updated plan")
                working = self._last_plan
                changed = True
        return working

    def _wait_timeout(
        self,
        running: Mapping[Future[_StepCallResult], _RunningStep],
        deadline: float,
        cancelled_at: float | None,
    ) -> float:
        now = time.monotonic()
        values = [0.05, max(0.0, deadline - now)]
        if cancelled_at is not None:
            values.append(0.05)
        else:
            values.extend(
                max(0.0, item.started_monotonic + item.step.timeout_seconds - now)
                for item in running.values()
            )
        return max(0.001, min(values))

    def _transition_step(
        self,
        plan: ExecutionPlan,
        step: PlanStep,
        target: StepState,
        *,
        expected_state: StepState,
        reason_code: str,
        states: dict[str, StepState],
        state_lock: RLock,
        authorization_state: AuthorizationState | None = None,
    ) -> None:
        with state_lock:
            transition = getattr(self._repository, "transition_step", None)
            if callable(transition):
                updated = transition(
                    plan.plan_id,
                    step.step_id,
                    target,
                    expected_state=expected_state,
                    authorization_state=authorization_state,
                    reason_code=reason_code,
                    at=self._clock.now(),
                )
            else:
                if states[step.step_id] is not expected_state:
                    raise ConflictError("plan step state changed before transition")
                base_plan = (
                    self._last_plan
                    if self._last_plan is not None and self._last_plan.plan_id == plan.plan_id
                    else plan
                )
                updated_steps = tuple(
                    replace(
                        item,
                        state=target,
                        authorization_state=authorization_state
                        if item.step_id == step.step_id and authorization_state is not None
                        else item.authorization_state,
                    )
                    if item.step_id == step.step_id
                    else item
                    for item in base_plan.steps
                )
                updated = replace(base_plan, steps=updated_steps)
            states[step.step_id] = target
            self._last_plan = updated

    def _transition_plan(
        self,
        plan: ExecutionPlan,
        target: PlanStatus,
        *,
        expected_status: PlanStatus,
        reason_code: str,
    ) -> ExecutionPlan:
        transition = getattr(self._repository, "transition_plan", None)
        if callable(transition):
            return cast(
                ExecutionPlan,
                transition(
                    plan.plan_id,
                    target,
                    expected_status=expected_status,
                    reason_code=reason_code,
                    at=self._clock.now(),
                ),
            )
        if plan.status is not expected_status:
            raise ConflictError("plan status changed before transition")
        return replace(plan, status=target)

    @staticmethod
    def _derive_plan_status(
        steps: tuple[PlanStep, ...],
        states: Mapping[str, StepState],
        cancelled: bool,
    ) -> PlanStatus:
        return derive_plan_status(
            steps,
            states,
            cancellation_accepted=cancelled,
        )
