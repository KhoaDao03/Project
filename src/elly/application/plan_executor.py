"""Bounded dependency-ready execution for validated V3 plans.

The executor is deliberately separate from ``ConversationOrchestrator``.  It
accepts an immutable, already validated plan, resolves each capability again
from the live optional-capability registry, and keeps all scheduling state in
application code.  Planner output never supplies a handler, provider, or
callback.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field, replace
from threading import RLock
from types import MappingProxyType
from typing import cast

from ..domain.enums import (
    ActionCategory,
    ErrorClass,
    OutcomeCode,
    PersistenceMode,
    PresentationMode,
    Route,
    TaskStatus,
)
from ..domain.errors import (
    CancelledError,
    ConfigInvalidError,
    ConflictError,
    EllyError,
    InputInvalidError,
)
from ..domain.models import (
    ActionConfirmationProposal,
    ContextManifest,
    OperationLease,
    TaskRequest,
    TaskResult,
)
from ..guardrails.controller import GuardrailController
from ..planning.contracts import (
    AuthorizationState,
    ExecutionPlan,
    PlanLimitsSnapshot,
    PlanStatus,
    PlanStep,
    StepCriticality,
    StepKind,
    StepState,
)
from ..ports.clock import ClockPort
from ..ports.local_response_composer import LocalResponseComposerPort
from ..ports.local_synthesis import (
    LocalSynthesisPort,
    SynthesisDraft,
    SynthesisInput,
    SynthesisRequest,
)
from ..ports.plan_repository import PlanRepositoryPort
from ..privacy import ConsentProposal, payload_hash
from .capabilities import CapabilityKind, CapabilityRegistry
from .capability_workflow import CapabilityExecutionOutcome, CapabilityExecutionWorkflow
from .execution import CancellationToken
from .plan_results import (
    DisagreementRecord,
    PlanAggregation,
    PlanStatusPolicy,
    TemplateFinalizer,
    aggregate_plan_results,
    derive_plan_status,
    finalize_plan,
)
from .plan_state import STEP_ELIGIBLE_STATES, STEP_TERMINAL_STATES
from .recovery import PlanRecovery
from .response_composer import compose_blocked, compose_cancelled, compose_failed
from .response_pipeline import ResponseCompositionService, ResponsePipelineResult
from .step_results import (
    RESULT_SCHEMA_VERSION,
    StepResultEnvelope,
    normalize_step_result,
)
from .synthesis import (
    build_synthesis_input,
    deterministic_synthesis_fallback,
    render_synthesis_draft,
    source_aggregation,
    validate_synthesis_draft,
)

SynthesisExecutor = Callable[
    [ExecutionPlan, PlanStep, Mapping[str, TaskResult], CancellationToken], TaskResult
]


class _NonBlockingThreadPoolExecutor(ThreadPoolExecutor):
    """Pool whose shutdown does not turn a step timeout into a hard wait."""

    def __exit__(self, exc_type, exc_value, traceback):  # type: ignore[no-untyped-def]
        self.shutdown(wait=False, cancel_futures=True)
        return False


@dataclass(frozen=True, slots=True)
class PlanExecutionRequest:
    """Request-scoped, already-approved context supplied to a plan run."""

    request: TaskRequest
    context_text: str
    context_manifest: ContextManifest
    cancellation: CancellationToken | None = None
    request_guardrails: GuardrailController | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.request, TaskRequest):
            raise InputInvalidError("plan execution request is invalid")
        if not isinstance(self.context_text, str) or not self.context_text.strip():
            raise InputInvalidError("plan execution context must be non-empty")
        if not isinstance(self.context_manifest, ContextManifest):
            raise InputInvalidError("plan execution context manifest is invalid")
        if self.cancellation is not None and not isinstance(self.cancellation, CancellationToken):
            raise InputInvalidError("plan execution cancellation token is invalid")


@dataclass(frozen=True, slots=True)
class PlanExecutionResult:
    """Safe outcome of one bounded plan execution."""

    plan: ExecutionPlan
    step_results: Mapping[str, TaskResult]
    reason_code: str = ""
    step_envelopes: Mapping[str, StepResultEnvelope] = field(default_factory=dict)
    aggregation: PlanAggregation | None = None
    final_result: TaskResult | None = None
    consent_proposal: ConsentProposal | None = None
    action_confirmation: ActionConfirmationProposal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.plan, ExecutionPlan):
            raise InputInvalidError("plan execution result plan is invalid")
        if not isinstance(self.step_results, Mapping):
            raise InputInvalidError("plan execution step results must be a mapping")
        normalized = dict(self.step_results)
        if any(
            not isinstance(step_id, str) or not isinstance(result, TaskResult)
            for step_id, result in normalized.items()
        ):
            raise InputInvalidError("plan execution results are invalid")
        object.__setattr__(self, "step_results", MappingProxyType(normalized))
        envelopes = dict(self.step_envelopes)
        if any(
            not isinstance(step_id, str) or not isinstance(envelope, StepResultEnvelope)
            for step_id, envelope in envelopes.items()
        ):
            raise InputInvalidError("plan execution result envelopes are invalid")
        object.__setattr__(self, "step_envelopes", MappingProxyType(envelopes))
        if self.aggregation is not None:
            if not isinstance(self.aggregation, PlanAggregation):
                raise InputInvalidError("plan execution aggregation is invalid")
            if self.aggregation.plan.plan_id != self.plan.plan_id:
                raise InputInvalidError("plan execution aggregation identity is invalid")
        if self.final_result is not None:
            if not isinstance(self.final_result, TaskResult):
                raise InputInvalidError("plan execution final result is invalid")
            if self.final_result.task_id != self.plan.task_id:
                raise InputInvalidError("plan execution final result identity is invalid")
        if self.consent_proposal is not None and not isinstance(
            self.consent_proposal, ConsentProposal
        ):
            raise InputInvalidError("plan execution consent proposal is invalid")
        if self.action_confirmation is not None and not isinstance(
            self.action_confirmation, ActionConfirmationProposal
        ):
            raise InputInvalidError("plan execution action confirmation is invalid")

    @property
    def status(self) -> PlanStatus:
        return self.plan.status

    @property
    def step_states(self) -> Mapping[str, StepState]:
        return MappingProxyType({step.step_id: step.state for step in self.plan.steps})

    @property
    def results(self) -> Mapping[str, TaskResult]:
        """Compatibility alias for callers that use the shorter result name."""

        return self.step_results

    @property
    def envelopes(self) -> Mapping[str, StepResultEnvelope]:
        """Typed result envelopes available to downstream plan consumers."""

        return self.step_envelopes

    @property
    def plan_result(self) -> PlanAggregation | None:
        """Typed aggregate result, if this execution reached aggregation."""

        return self.aggregation

    @property
    def result(self) -> TaskResult | None:
        """Final user-facing result, retained as an additive convenience."""

        return self.final_result

    @property
    def disagreements(self) -> tuple[DisagreementRecord, ...]:
        """Explicit specialist disagreements, if aggregation was completed."""

        return self.aggregation.disagreements if self.aggregation is not None else ()


PlanRunResult = PlanExecutionResult


@dataclass
class _RunningStep:
    step: PlanStep
    future: Future["_StepCallResult"]
    cancellation: CancellationToken
    started_monotonic: float
    lease: OperationLease | None
    dispatch_state: dict[str, bool]
    dispatched: bool = False


class _StepInputError(EllyError):
    """Safe application failure while resolving declared step inputs."""

    error_class = ErrorClass.INPUT_INVALID


@dataclass(frozen=True, slots=True)
class _StepCallResult:
    result: TaskResult
    envelope: StepResultEnvelope | None = None
    synthesis_input: SynthesisInput | None = None
    synthesis_draft: SynthesisDraft | None = None
    synthesis_validation_state: str = ""
    consent_proposal: ConsentProposal | None = None
    action_confirmation: ActionConfirmationProposal | None = None


class PlanExecutor:
    """Execute validated plans with dependency and resource ceilings."""

    def __init__(
        self,
        *,
        repository: PlanRepositoryPort,
        capability_registry: CapabilityRegistry,
        capability_workflow: CapabilityExecutionWorkflow,
        clock: ClockPort,
        max_workers: int | None = None,
        synthesis_executor: SynthesisExecutor | None = None,
        synthesis_port: LocalSynthesisPort | None = None,
        synthesis_max_output_tokens: int = 1600,
        synthesis_timeout_seconds: float = 120.0,
        response_composer_port: LocalResponseComposerPort | None = None,
        response_composer_max_output_tokens: int = 1600,
        response_composer_timeout_seconds: float = 120.0,
        response_pipeline: ResponseCompositionService | None = None,
    ) -> None:
        if not isinstance(capability_registry, CapabilityRegistry):
            raise ConfigInvalidError("plan executor requires a capability registry")
        if not isinstance(capability_workflow, CapabilityExecutionWorkflow):
            raise ConfigInvalidError("plan executor requires the capability workflow")
        if not isinstance(clock, ClockPort):
            raise ConfigInvalidError("plan executor requires a clock")
        if max_workers is not None and (
            isinstance(max_workers, bool) or not isinstance(max_workers, int) or max_workers <= 0
        ):
            raise ConfigInvalidError("plan executor max_workers must be positive")
        if synthesis_port is not None and not isinstance(synthesis_port, LocalSynthesisPort):
            raise ConfigInvalidError("plan executor synthesis port is invalid")
        if response_composer_port is not None and not isinstance(
            response_composer_port, LocalResponseComposerPort
        ):
            raise ConfigInvalidError("plan executor response composer port is invalid")
        if response_pipeline is not None and not isinstance(
            response_pipeline, ResponseCompositionService
        ):
            raise ConfigInvalidError("plan executor response pipeline is invalid")
        if (
            isinstance(synthesis_max_output_tokens, bool)
            or not isinstance(synthesis_max_output_tokens, int)
            or synthesis_max_output_tokens <= 0
        ):
            raise ConfigInvalidError("plan executor synthesis output limit must be positive")
        if (
            isinstance(synthesis_timeout_seconds, bool)
            or not isinstance(synthesis_timeout_seconds, (int, float))
            or synthesis_timeout_seconds <= 0
        ):
            raise ConfigInvalidError("plan executor synthesis timeout must be positive")
        if (
            isinstance(response_composer_max_output_tokens, bool)
            or not isinstance(response_composer_max_output_tokens, int)
            or response_composer_max_output_tokens <= 0
        ):
            raise ConfigInvalidError("plan executor response composer output limit must be positive")
        if (
            isinstance(response_composer_timeout_seconds, bool)
            or not isinstance(response_composer_timeout_seconds, (int, float))
            or response_composer_timeout_seconds <= 0
        ):
            raise ConfigInvalidError("plan executor response composer timeout must be positive")
        self._repository = repository
        self._capability_registry = capability_registry
        self._capability_workflow = capability_workflow
        self._clock = clock
        self._max_workers = max_workers
        self._synthesis_executor = synthesis_executor
        self._synthesis_port = synthesis_port
        self._synthesis_max_output_tokens = synthesis_max_output_tokens
        self._synthesis_timeout_seconds = float(synthesis_timeout_seconds)
        self._response_pipeline = response_pipeline or (
            ResponseCompositionService(
                composer=response_composer_port,
                max_output_tokens=response_composer_max_output_tokens,
                timeout_seconds=response_composer_timeout_seconds,
            )
            if response_composer_port is not None
            else None
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
            stored = self._get_step_result(plan.plan_id, step.step_id)
            if stored is not None:
                results[step.step_id] = stored
            stored_envelope = self._get_step_envelope(plan.plan_id, step.step_id)
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
                self._save_step_result(plan, step, stored, envelope=migrated)

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
            final_result = self._finalize_aggregation(aggregation, execution, cancellation)
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
                            self._save_step_result(working_plan, step, timeout_result)

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
                            payload = self._resolve_step_inputs(
                                step,
                                execution,
                                results,
                                envelopes,
                                working_plan.steps,
                            )
                        except _StepInputError as exc:
                            result = compose_blocked(
                                task_id=working_plan.task_id,
                                reason=exc.summary,
                                route=Route.REGISTERED_CAPABILITY,
                                outcome_code=OutcomeCode.BLOCKED,
                            )
                            results[step.step_id] = result
                            self._save_step_result(working_plan, step, result)
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

                        live_handler = self._live_handler(step)
                        if isinstance(live_handler, str):
                            result = compose_blocked(
                                task_id=working_plan.task_id,
                                reason=live_handler,
                                route=Route.REGISTERED_CAPABILITY,
                                outcome_code=OutcomeCode.UNAVAILABLE,
                            )
                            results[step.step_id] = result
                            self._save_step_result(working_plan, step, result)
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

                        kind = self._capability_kind(step, live_handler)
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
                            self._save_step_result(working_plan, step, result)
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
                            self._claim_lease(working_plan, step, payload, execution)
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
                            self._save_step_result(working_plan, step, result)
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
                            self._call_step,
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
                            self._save_step_result(working_plan, step, result)
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
                        self._save_step_result(working_plan, item.step, result)
                        self._finish_lease(item.lease, dispatched=item.dispatched)
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
                    call_result = self._future_result(future, working_plan.task_id)
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
                    self._save_step_result(
                        working_plan,
                        item.step,
                        result,
                        envelope=(
                            call_result.envelope
                            if not cancellation_wins and not deadline_expired
                            else None
                        ),
                    )
                    if (
                        call_result.synthesis_input is not None
                        and not cancellation_wins
                        and not deadline_expired
                    ):
                        self._save_synthesis_result(
                            working_plan,
                            call_result,
                            result,
                            retain_output=(
                                execution.request.persistence_mode
                                is PersistenceMode.STORE_WITH_RETENTION
                            ),
                        )
                    target = self._step_state_for_result(result)
                    self._finish_lease(
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
                        reason_code=self._reason_for_result(result, target),
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
        final_result = self._finalize_aggregation(aggregation, execution, cancellation)
        return PlanExecutionResult(
            working_plan,
            results,
            f"PLAN_{final_status.value.upper()}",
            envelopes,
            aggregation,
            final_result,
        )

    def _finalize_aggregation(
        self,
        aggregation: PlanAggregation,
        execution: PlanExecutionRequest,
        cancellation: CancellationToken | None = None,
    ) -> TaskResult:
        """Apply one common V3.5 presentation decision after aggregation."""

        if self._response_pipeline is None:
            return finalize_plan(
                aggregation,
                synthesized_result=self._synthesis_result(aggregation.plan, aggregation.step_results),
            )

        stored = self._stored_response_result(aggregation)
        if stored is not None:
            self._record_response_composition(
                aggregation.plan,
                ResponsePipelineResult(
                    result=stored,
                    mode=PresentationMode.COMPOSED,
                    observation=None,
                ),
            )
            return stored

        # Persist an application-owned attempt reservation before invoking the
        # local model. If the process stops after dispatch but before the final
        # draft is stored, recovery deterministically finalizes the canonical
        # aggregation instead of issuing a second composition request.
        self._reserve_response_composition(aggregation.plan)
        composed = self._response_pipeline.compose_aggregation(
            aggregation,
            request=execution.request,
            approved_context=execution.context_text,
            cancellation=cancellation,
        )
        self._record_response_composition(aggregation.plan, composed)
        self._save_response_composition(
            aggregation.plan,
            composed,
            retain_output=(
                execution.request.persistence_mode is PersistenceMode.STORE_WITH_RETENTION
            ),
        )
        return composed.result

    def _reserve_response_composition(self, plan: ExecutionPlan) -> None:
        save = getattr(self._repository, "save_synthesis_result", None)
        if not callable(save):
            return
        save(
            plan.plan_id,
            plan.finalization,
            "response_composition:attempting",
            (),
            {"mode": "", "outcome": "attempting", "answer": "", "answer_retained": False},
            at=self._clock.now(),
        )
        append_event = getattr(self._repository, "append_plan_event", None)
        if callable(append_event):
            append_event(
                plan.plan_id,
                "response_composer.attempted",
                "RESPONSE_COMPOSITION_RESERVED",
                "attempted=1 outcome=attempting",
                at=self._clock.now(),
            )

    def _record_response_composition(
        self,
        plan: ExecutionPlan,
        composed: ResponsePipelineResult,
    ) -> None:
        observation = composed.observation
        if observation is None:
            return
        append_event = getattr(self._repository, "append_plan_event", None)
        if not callable(append_event):
            return
        outcome = observation.outcome or "unknown"
        reason = observation.reason_code[:128]
        detail = (
            f"mode={observation.mode.value} attempted={int(observation.attempted)} "
            f"outcome={outcome} profile={observation.profile[:64]} "
            f"model={observation.model_version[:128]} "
            f"result_refs={','.join(observation.result_refs)} "
            f"claim_refs={','.join(observation.claim_refs)} "
            f"citation_refs={','.join(observation.citation_refs)} "
            f"warning_refs={','.join(observation.warning_refs)} "
            f"disagreement_refs={','.join(observation.disagreement_refs)} "
            f"record_refs={','.join(observation.immutable_record_refs)} "
            f"duration_ms={observation.duration_ms} output_tokens={observation.output_tokens}"
        )
        append_event(
            plan.plan_id,
            f"response_composer.{outcome}",
            reason or "RESPONSE_COMPOSITION_RECORDED",
            detail[:512],
            at=self._clock.now(),
        )

    def _save_response_composition(
        self,
        plan: ExecutionPlan,
        composed: ResponsePipelineResult,
        *,
        retain_output: bool,
    ) -> None:
        observation = composed.observation
        save = getattr(self._repository, "save_synthesis_result", None)
        if observation is None or not callable(save):
            return
        output: dict[str, object] = {
            "mode": observation.mode.value,
            "outcome": observation.outcome,
            "reason_code": observation.reason_code,
            "profile": observation.profile,
            "model_version": observation.model_version,
            "result_refs": list(observation.result_refs),
            "claim_refs": list(observation.claim_refs),
            "citation_refs": list(observation.citation_refs),
            "warning_refs": list(observation.warning_refs),
            "disagreement_refs": list(observation.disagreement_refs),
            "immutable_record_refs": list(observation.immutable_record_refs),
            "duration_ms": observation.duration_ms,
            "output_tokens": observation.output_tokens,
            "answer": composed.result.answer if retain_output else "",
            "answer_retained": bool(retain_output and composed.result.answer_retained),
        }
        save(
            plan.plan_id,
            plan.finalization,
            f"response_composition:{observation.outcome}",
            observation.result_refs,
            output,
            at=self._clock.now(),
        )

    def _stored_response_result(self, aggregation: PlanAggregation) -> TaskResult | None:
        get = getattr(self._repository, "get_synthesis_result", None)
        if not callable(get):
            return None
        record = get(aggregation.plan_id)
        if record is None or not record.validation_state.startswith("response_composition:"):
            return None
        canonical = TemplateFinalizer().finalize(aggregation)
        answer = record.output.get("answer") if isinstance(record.output, Mapping) else None
        if not isinstance(answer, str) or not answer.strip():
            return canonical
        return replace(canonical, answer=answer, answer_retained=True)

    def _call_step(
        self,
        plan: ExecutionPlan,
        step: PlanStep,
        execution: PlanExecutionRequest,
        payload: str,
        results: Mapping[str, TaskResult],
        envelopes: Mapping[str, StepResultEnvelope],
        cancellation: CancellationToken,
        lease: OperationLease | None,
        before_dispatch: Callable[[], None],
    ) -> _StepCallResult:
        cancellation.raise_if_cancelled()
        if step.kind is StepKind.LOCAL_SYNTHESIS:
            before_dispatch()
            if self._response_pipeline is not None:
                # A persisted V3 plan may still contain the old terminal
                # synthesis node.  Treat it as a deterministic migration shim;
                # V3.5's single response composer runs only after the complete
                # aggregation below.
                source_result = source_aggregation(
                    plan,
                    results,
                    envelopes,
                    {item.step_id: item.state for item in plan.steps},
                )
                return _StepCallResult(TemplateFinalizer().finalize(source_result))
            if self._synthesis_executor is not None:
                result = self._synthesis_executor(plan, step, results, cancellation)
                if not isinstance(result, TaskResult):
                    raise ConfigInvalidError("synthesis executor returned an invalid result")
                return _StepCallResult(result)

            source_input: SynthesisInput | None = None
            try:
                source_input, source_result = build_synthesis_input(
                    plan,
                    execution.request,
                    execution.context_text,
                    results,
                    envelopes,
                    {item.step_id: item.state for item in plan.steps},
                )
            except Exception:
                # The deterministic source aggregation is still useful for a
                # safe fallback even if a bounded model input cannot be built.
                source_result = source_aggregation(
                    plan,
                    results,
                    envelopes,
                    {item.step_id: item.state for item in plan.steps},
                )
            if self._synthesis_port is None or source_input is None:
                return self._synthesis_fallback(
                    plan,
                    source_result,
                    source_input,
                    "SYNTHESIS_PORT_UNAVAILABLE"
                    if self._synthesis_port is None
                    else "SYNTHESIS_INPUT_INVALID",
                )

            request = SynthesisRequest(
                request_id=execution.request.request_id,
                synthesis_input=source_input,
                max_output_tokens=self._synthesis_max_output_tokens,
                timeout_seconds=min(step.timeout_seconds, self._synthesis_timeout_seconds),
            )
            unregister = cancellation.register(self._synthesis_port.cancel)
            try:
                draft = self._synthesis_port.synthesize(request)
                validated = validate_synthesis_draft(source_input, draft)
                rendered = render_synthesis_draft(source_input, validated, source_result)
                if not isinstance(rendered, TaskResult):
                    raise ConfigInvalidError("synthesis renderer returned invalid output")
                return _StepCallResult(
                    rendered,
                    synthesis_input=source_input,
                    synthesis_draft=validated,
                    synthesis_validation_state="validated",
                )
            except CancelledError:
                if cancellation.cancelled:
                    raise
                return self._synthesis_fallback(
                    plan,
                    source_result,
                    source_input,
                    "SYNTHESIS_CANCELLED",
                )
            except Exception as exc:  # provider/model/parser failures are safe fallbacks
                return self._synthesis_fallback(
                    plan,
                    source_result,
                    source_input,
                    self._synthesis_failure_code(exc),
                )
            finally:
                unregister()
        outcome: CapabilityExecutionOutcome = self._capability_workflow.execute_plan_step(
            plan=plan,
            step=step,
            request=execution.request,
            context_text=payload,
            context_manifest=execution.context_manifest,
            cancellation=cancellation,
            request_guardrails=execution.request_guardrails,
            operation_lease=lease,
            before_dispatch=before_dispatch,
        )
        envelope = outcome.result_envelope
        if envelope is None:
            handler = self._capability_registry.get(step.capability_id)
            supported = frozenset(
                getattr(
                    getattr(handler, "descriptor", None),
                    "output_schema_versions",
                    (),
                )
            )
            envelope = normalize_step_result(
                outcome.result,
                plan_id=plan.plan_id,
                task_id=plan.task_id,
                step_id=step.step_id,
                capability_id=step.capability_id,
                operation_id=step.operation_id,
                supported_schema_versions=supported or frozenset({RESULT_SCHEMA_VERSION}),
            )
        return _StepCallResult(
            outcome.result,
            envelope,
            consent_proposal=outcome.consent_proposal,
            action_confirmation=outcome.action_confirmation,
        )

    def _live_handler(self, step: PlanStep) -> object | str:
        if step.kind is StepKind.LOCAL_SYNTHESIS:
            return object()
        handler = self._capability_registry.get(step.capability_id)
        if handler is None:
            return "capability is not registered"
        status = handler.status()
        if not status.available:
            return status.reason_code or "capability is unavailable"
        if step.operation_id not in handler.descriptor.operations:
            return "operation is not supported by the live capability"
        return handler

    def _synthesis_fallback(
        self,
        plan: ExecutionPlan,
        aggregation: PlanAggregation,
        synthesis_input: SynthesisInput | None,
        reason_code: str,
    ) -> _StepCallResult:
        result = deterministic_synthesis_fallback(aggregation, reason_code)
        append_event = getattr(self._repository, "append_plan_event", None)
        if callable(append_event):
            append_event(
                plan.plan_id,
                "synthesis.fallback",
                "SYNTHESIS_FALLBACK",
                reason_code[:256],
                at=self._clock.now(),
            )
        return _StepCallResult(
            result,
            synthesis_input=synthesis_input,
            synthesis_validation_state=f"fallback:{reason_code}",
        )

    @staticmethod
    def _synthesis_failure_code(error: Exception) -> str:
        name = type(error).__name__.upper()
        if "TIMEOUT" in name:
            return "SYNTHESIS_TIMEOUT"
        if "MALFORMED" in name or "VALUE" in name or "TYPE" in name:
            return "SYNTHESIS_DRAFT_INVALID"
        if "UNAVAILABLE" in name or "PERMANENT" in name or "TRANSIENT" in name:
            return "SYNTHESIS_LOCAL_MODEL_UNAVAILABLE"
        return "SYNTHESIS_FAILED"

    @staticmethod
    def _synthesis_result(
        plan: ExecutionPlan,
        results: Mapping[str, TaskResult],
    ) -> TaskResult | None:
        for step in plan.steps:
            if step.kind is StepKind.LOCAL_SYNTHESIS:
                result = results.get(step.step_id)
                return result if isinstance(result, TaskResult) else None
        return None

    @staticmethod
    def _capability_kind(step: PlanStep, handler: object) -> CapabilityKind:
        if step.kind is StepKind.LOCAL_SYNTHESIS:
            return CapabilityKind.SPECIALIST
        routing = getattr(getattr(handler, "descriptor", None), "routing", None)
        return routing.kind if routing is not None else CapabilityKind.SPECIALIST

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
            if PlanExecutor._dependency_required(step, by_id[dependency])
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

    def _resolve_step_inputs(
        self,
        step: PlanStep,
        execution: PlanExecutionRequest,
        results: Mapping[str, TaskResult],
        envelopes: Mapping[str, StepResultEnvelope],
        all_steps: tuple[PlanStep, ...],
    ) -> str:
        del all_steps
        values: list[str] = []
        for item in step.inputs:
            value: str | None
            if item.source == "request":
                value = execution.request.text
            elif item.source == "context":
                value = execution.context_text
            elif item.source == "step":
                result = results.get(item.reference)
                envelope = envelopes.get(item.reference)
                value = (
                    (envelope.answer or envelope.summary)
                    if envelope is not None
                    else (result.answer if result is not None else None)
                )
                if not value and envelope is not None and envelope.structured_output:
                    value = "; ".join(
                        f"{key}={item_value}"
                        for key, item_value in envelope.structured_output.items()
                    )
                if not value and result is not None and result.claims:
                    value = "; ".join(result.claims)
            else:
                value = None
            if not value:
                if item.required:
                    raise _StepInputError(f"required input {item.name} is unavailable")
                continue
            values.append(f"{item.name}: {value}")
        if not values:
            values.append(f"request: {execution.request.text}")
        if step.objective_class == "deterministic_fallback" and len(values) == 1:
            return values[0].split(": ", 1)[-1]
        # The objective is application-owned metadata and is included so a
        # single handler can distinguish materially different validated steps.
        return f"objective: {step.objective}\n" + "\n".join(values)

    def _claim_lease(
        self,
        plan: ExecutionPlan,
        step: PlanStep,
        payload: str,
        execution: PlanExecutionRequest,
    ) -> OperationLease | None:
        claim = getattr(self._repository, "claim_operation", None)
        if not callable(claim):
            return None
        return cast(
            OperationLease,
            claim(
                task_id=plan.task_id,
                request_id=f"{execution.request.request_id}:{step.step_id}",
                capability_id=step.capability_id,
                request_digest=payload_hash(payload),
                at=self._clock.now(),
            ),
        )

    def _finish_lease(
        self,
        lease: OperationLease | None,
        *,
        dispatched: bool,
        success: bool = False,
    ) -> None:
        if lease is None:
            return
        if success:
            complete = getattr(self._repository, "complete_operation", None)
            if callable(complete):
                complete(lease.operation_id, at=self._clock.now())
            return
        fail = getattr(self._repository, "fail_operation", None)
        if callable(fail):
            fail(
                lease.operation_id,
                at=self._clock.now(),
                possible_duplicate=dispatched,
            )

    def _future_result(self, future: Future[_StepCallResult], task_id: str) -> _StepCallResult:
        try:
            result = future.result()
        except CancelledError as exc:
            return _StepCallResult(
                compose_cancelled(
                    task_id=task_id,
                    partial_work=exc.partial_work,
                    route=Route.REGISTERED_CAPABILITY,
                )
            )
        except EllyError as exc:
            return _StepCallResult(
                compose_failed(
                    task_id=task_id,
                    reason=exc.summary,
                    route=Route.REGISTERED_CAPABILITY,
                )
            )
        except BaseException:
            return _StepCallResult(
                compose_failed(
                    task_id=task_id,
                    reason="plan step failed",
                    route=Route.REGISTERED_CAPABILITY,
                )
            )
        if not isinstance(result, _StepCallResult) or result.result.task_id != task_id:
            return _StepCallResult(
                compose_failed(
                    task_id=task_id,
                    reason="plan step returned an invalid result",
                    route=Route.REGISTERED_CAPABILITY,
                )
            )
        return result

    @staticmethod
    def _step_state_for_result(result: TaskResult) -> StepState:
        if result.task_status is TaskStatus.COMPLETED:
            return StepState.COMPLETED
        if result.task_status is TaskStatus.PARTIAL:
            return StepState.PARTIAL
        if result.task_status is TaskStatus.CANCELLED:
            return StepState.CANCELLED
        if (
            result.task_status is TaskStatus.AWAITING_CONSENT
            or result.task_status is TaskStatus.AWAITING_CONFIRMATION
        ):
            return StepState.BLOCKED
        if result.task_status is TaskStatus.BLOCKED:
            return StepState.BLOCKED
        return StepState.FAILED

    @staticmethod
    def _reason_for_result(result: TaskResult, state: StepState) -> str:
        if result.failures:
            safe = result.failures[0].replace(" ", "_").upper()
            if safe and all(char.isalnum() or char == "_" for char in safe):
                return safe[:64]
        return f"STEP_{state.value.upper()}"

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

    def _save_step_result(
        self,
        plan: ExecutionPlan,
        step: PlanStep,
        result: TaskResult,
        envelope: StepResultEnvelope | None = None,
    ) -> None:
        if envelope is not None:
            save_envelope = getattr(self._repository, "save_step_envelope", None)
            if callable(save_envelope):
                save_envelope(
                    plan.plan_id,
                    step.step_id,
                    envelope,
                    at=self._clock.now(),
                )
                return
        save = getattr(self._repository, "save_step_result", None)
        if callable(save):
            save(plan.plan_id, step.step_id, result, at=self._clock.now())

    def _save_synthesis_result(
        self,
        plan: ExecutionPlan,
        call_result: _StepCallResult,
        result: TaskResult,
        *,
        retain_output: bool,
    ) -> None:
        save = getattr(self._repository, "save_synthesis_result", None)
        if not callable(save) or call_result.synthesis_input is None:
            return
        output: dict[str, object] = {
            "status": result.task_status.value,
            "answer": result.answer if retain_output and result.answer_retained else "",
            "claims": list(result.claims) if retain_output else [],
            "citations": list(result.citations) if retain_output else [],
            "partial_work": list(result.partial_work) if retain_output else [],
            "failures": list(result.failures),
            "next_actions": list(result.next_actions) if retain_output else [],
            "draft": (
                call_result.synthesis_draft.to_dict()
                if call_result.synthesis_draft is not None
                else None
            ),
        }
        save(
            plan.plan_id,
            plan.finalization,
            call_result.synthesis_validation_state or "fallback",
            call_result.synthesis_input.result_ids,
            output,
            at=self._clock.now(),
        )

    def _get_step_result(self, plan_id: str, step_id: str) -> TaskResult | None:
        get = getattr(self._repository, "get_step_result", None)
        return get(plan_id, step_id) if callable(get) else None

    def _get_step_envelope(self, plan_id: str, step_id: str) -> StepResultEnvelope | None:
        get = getattr(self._repository, "get_step_envelope", None)
        return get(plan_id, step_id) if callable(get) else None

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


def _request_for_plan(plan: ExecutionPlan) -> TaskRequest:
    """Construct a conservative convenience request for direct unit callers."""

    raise InputInvalidError(f"plan {plan.plan_id} requires a TaskRequest and execution context")


__all__ = [
    "PlanExecutionRequest",
    "PlanExecutionResult",
    "PlanExecutor",
    "PlanStatusPolicy",
    "PlanRunResult",
]
