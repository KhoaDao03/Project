"""Single-step execution, input resolution, and operation lease handling."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import Future
from dataclasses import dataclass
from typing import cast

from elly.application.capabilities.local_conversation_handler import (
    LOCAL_CONVERSATION_CAPABILITY_ID,
)
from elly.application.capabilities.registry import CapabilityKind, CapabilityRegistry
from elly.application.capabilities.workflow import (
    CapabilityExecutionOutcome,
    CapabilityExecutionWorkflow,
)
from elly.application.response.composer import compose_cancelled, compose_failed
from elly.application.results.step import (
    RESULT_SCHEMA_VERSION,
    StepResultEnvelope,
    normalize_step_result,
)
from elly.application.task_execution.cancellation import CancellationToken
from elly.domain.enums import ErrorClass, Route, TaskStatus
from elly.domain.errors import CancelledError, EllyError
from elly.domain.models import (
    ActionConfirmationProposal,
    OperationLease,
    TaskResult,
)
from elly.planning.contracts import ExecutionPlan, PlanStep, StepKind, StepState
from elly.ports.clock import ClockPort
from elly.ports.plan_repository import PlanRepositoryPort
from elly.privacy import ConsentProposal, payload_hash

from .contracts import PlanExecutionRequest
from .legacy import execute_legacy_synthesis


class _StepInputError(EllyError):
    """Safe application failure while resolving declared step inputs."""

    error_class = ErrorClass.INPUT_INVALID


@dataclass(frozen=True, slots=True)
class _StepCallResult:
    result: TaskResult
    envelope: StepResultEnvelope | None = None
    consent_proposal: ConsentProposal | None = None
    action_confirmation: ActionConfirmationProposal | None = None


class StepRunner:
    """Resolve, authorize, invoke, normalize, and persist one validated step."""

    def __init__(
        self,
        *,
        repository: PlanRepositoryPort,
        capability_registry: CapabilityRegistry,
        capability_workflow: CapabilityExecutionWorkflow,
        clock: ClockPort,
    ) -> None:
        self._repository = repository
        self._capability_registry = capability_registry
        self._capability_workflow = capability_workflow
        self._clock = clock

    def call(
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
            return _StepCallResult(
                execute_legacy_synthesis(
                    plan,
                    step,
                    results,
                    envelopes,
                    before_dispatch,
                )
            )
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

    def live_handler(self, step: PlanStep) -> object | str:
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

    @staticmethod
    def capability_kind(step: PlanStep, handler: object) -> CapabilityKind:
        if step.kind is StepKind.LOCAL_SYNTHESIS:
            return CapabilityKind.SPECIALIST
        routing = getattr(getattr(handler, "descriptor", None), "routing", None)
        return routing.kind if routing is not None else CapabilityKind.SPECIALIST

    @staticmethod
    def resolve_inputs(
        step: PlanStep,
        execution: PlanExecutionRequest,
        results: Mapping[str, TaskResult],
        envelopes: Mapping[str, StepResultEnvelope],
    ) -> str:
        values: list[str] = []
        for item in step.inputs:
            value: str | None
            if item.source == "request":
                value = execution.request.text
            elif item.source == "context":
                value = (
                    execution.local_context_text
                    if step.capability_id == LOCAL_CONVERSATION_CAPABILITY_ID
                    and execution.local_context_text
                    else execution.context_text
                )
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
        return f"objective: {step.objective}\n" + "\n".join(values)

    def claim_lease(
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

    def finish_lease(
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

    @staticmethod
    def future_result(future: Future[_StepCallResult], task_id: str) -> _StepCallResult:
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
    def state_for_result(result: TaskResult) -> StepState:
        if result.task_status is TaskStatus.COMPLETED:
            return StepState.COMPLETED
        if result.task_status is TaskStatus.PARTIAL:
            return StepState.PARTIAL
        if result.task_status is TaskStatus.CANCELLED:
            return StepState.CANCELLED
        if result.task_status in {
            TaskStatus.AWAITING_CONSENT,
            TaskStatus.AWAITING_CONFIRMATION,
            TaskStatus.BLOCKED,
        }:
            return StepState.BLOCKED
        return StepState.FAILED

    @staticmethod
    def reason_for_result(result: TaskResult, state: StepState) -> str:
        if result.failures:
            safe = result.failures[0].replace(" ", "_").upper()
            if safe and all(char.isalnum() or char == "_" for char in safe):
                return safe[:64]
        return f"STEP_{state.value.upper()}"

    def save_result(
        self,
        plan: ExecutionPlan,
        step: PlanStep,
        result: TaskResult,
        envelope: StepResultEnvelope | None = None,
    ) -> None:
        if envelope is not None:
            save_envelope = getattr(self._repository, "save_step_envelope", None)
            if callable(save_envelope):
                save_envelope(plan.plan_id, step.step_id, envelope, at=self._clock.now())
                return
        save = getattr(self._repository, "save_step_result", None)
        if callable(save):
            save(plan.plan_id, step.step_id, result, at=self._clock.now())

    def get_result(self, plan_id: str, step_id: str) -> TaskResult | None:
        get = getattr(self._repository, "get_step_result", None)
        return get(plan_id, step_id) if callable(get) else None

    def get_envelope(self, plan_id: str, step_id: str) -> StepResultEnvelope | None:
        get = getattr(self._repository, "get_step_envelope", None)
        return get(plan_id, step_id) if callable(get) else None
