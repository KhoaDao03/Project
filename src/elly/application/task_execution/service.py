"""Public task execution service and active-run lifecycle management."""

from __future__ import annotations

from threading import RLock

from elly.application.capabilities import CapabilityRegistry
from elly.application.capability_workflow import CapabilityExecutionWorkflow
from elly.application.execution import CancellationToken
from elly.application.recovery import PlanRecovery, RecoveryReport
from elly.application.replan import ReplanRequest, ReplanResult, ReplanService, ReplanTrigger
from elly.application.response_pipeline import ResponseCompositionService
from elly.domain.enums import TaskStatus
from elly.domain.errors import ConfigInvalidError, InputInvalidError
from elly.domain.models import ContextManifest, TaskRequest
from elly.guardrails.controller import GuardrailController
from elly.planning.contracts import (
    AuthorizationState,
    ExecutionPlan,
    ExecutionProposal,
    PlanStatus,
    StepState,
)
from elly.ports.clock import ClockPort
from elly.ports.local_response_composer import LocalResponseComposerPort
from elly.ports.plan_repository import PlanRepositoryPort

from .contracts import PlanExecutionRequest, PlanExecutionResult
from .plan_runner import PlanRunner


class TaskExecutionService:
    """Sole public authority for executing one validated task plan."""

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
        recovery: PlanRecovery | None = None,
        replan_service: ReplanService | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._recovery = recovery or PlanRecovery(clock=clock)
        self._replan_service = replan_service
        self._active_lock = RLock()
        self._active: dict[str, CancellationToken] = {}
        self._active_tasks: dict[str, str] = {}
        self._runner = PlanRunner(
            repository=repository,
            capability_registry=capability_registry,
            capability_workflow=capability_workflow,
            clock=clock,
            max_workers=max_workers,
            response_composer_port=response_composer_port,
            response_composer_max_output_tokens=response_composer_max_output_tokens,
            response_composer_timeout_seconds=response_composer_timeout_seconds,
            response_pipeline=response_pipeline,
        )

    def execute(
        self,
        plan: ExecutionPlan | str,
        execution: PlanExecutionRequest | None = None,
        *,
        request: TaskRequest | None = None,
        context_text: str | None = None,
        context_manifest: ContextManifest | None = None,
        local_context_text: str = "",
        cancellation: CancellationToken | None = None,
        request_guardrails: GuardrailController | None = None,
        manage_task_lifecycle: bool = True,
    ) -> PlanExecutionResult:
        if execution is not None:
            if not isinstance(execution, PlanExecutionRequest):
                raise InputInvalidError("task execution context is invalid")
            request = execution.request
            context_text = execution.context_text
            context_manifest = execution.context_manifest
            local_context_text = execution.local_context_text
            cancellation = execution.cancellation
            request_guardrails = execution.request_guardrails
        if request is None or context_text is None or context_manifest is None:
            raise InputInvalidError("task execution context is incomplete")
        if not isinstance(request, TaskRequest):
            raise InputInvalidError("task execution request is invalid")
        resolved = self._resolve_plan(plan)
        token = cancellation or CancellationToken()
        with self._active_lock:
            self._active[resolved.plan_id] = token
            self._active_tasks[resolved.task_id] = resolved.plan_id
        if manage_task_lifecycle:
            self._start_task_if_available(resolved, request)
        try:
            result = self._runner.execute(
                resolved,
                PlanExecutionRequest(
                    request=request,
                    context_text=context_text,
                    context_manifest=context_manifest,
                    local_context_text=local_context_text,
                    cancellation=token,
                    request_guardrails=request_guardrails,
                ),
            )
            if manage_task_lifecycle:
                self._finish_task_if_available(result)
            return result
        finally:
            with self._active_lock:
                self._active.pop(resolved.plan_id, None)
                self._active_tasks.pop(resolved.task_id, None)

    run = execute

    def reconcile_startup(self) -> tuple[RecoveryReport, ...]:
        """Recover persisted nonterminal plans without dispatching providers."""

        return self._recovery.reconcile_startup(self._repository)

    def replan(
        self,
        plan: ExecutionPlan | str,
        proposal: ExecutionProposal,
        *,
        request: ReplanRequest | None = None,
        trigger: ReplanTrigger | None = None,
        failed_step_id: str | None = None,
        cancellation_accepted: bool = False,
        authorization_denied: bool = False,
        consent_denied: bool = False,
        hard_limit_reached: bool = False,
        uncertain_external_action: bool = False,
        idempotency_safe: bool = True,
        same_contract: bool = True,
        cancellation: CancellationToken | None = None,
    ) -> ReplanResult:
        if self._replan_service is None:
            raise ConfigInvalidError("plan replanning is not configured")
        return self._replan_service.replan(
            self._resolve_plan(plan),
            proposal,
            request=request,
            trigger=trigger,
            failed_step_id=failed_step_id,
            cancellation_accepted=cancellation_accepted,
            authorization_denied=authorization_denied,
            consent_denied=consent_denied,
            hard_limit_reached=hard_limit_reached,
            uncertain_external_action=uncertain_external_action,
            idempotency_safe=idempotency_safe,
            same_contract=same_contract,
            cancellation=cancellation,
        )

    def cancel(self, plan_id: str) -> bool:
        with self._active_lock:
            token = self._active.get(plan_id)
        if token is None:
            return False
        token.cancel()
        return True

    cancel_plan = cancel

    def cancel_active(self) -> bool:
        with self._active_lock:
            token = next(iter(self._active.values()), None)
        if token is None:
            return False
        token.cancel()
        return True

    def cancel_task(self, task_id: str) -> bool:
        with self._active_lock:
            plan_id = self._active_tasks.get(task_id)
        return self.cancel(plan_id) if plan_id is not None else False

    def resume_authorized_step(self, plan_id: str, step_id: str) -> ExecutionPlan:
        plan = self._resolve_plan(plan_id)
        if plan.status is not PlanStatus.BLOCKED:
            raise InputInvalidError("execution plan is not awaiting authorization")
        selected = next((step for step in plan.steps if step.step_id == step_id), None)
        if selected is None or selected.state is not StepState.BLOCKED:
            raise InputInvalidError("authorized plan step is not resumable")
        stored = self._repository.get_step_result(plan.plan_id, step_id)
        if stored is None or stored.task_status not in {
            TaskStatus.AWAITING_CONSENT,
            TaskStatus.AWAITING_CONFIRMATION,
        }:
            raise InputInvalidError("plan step has no matching authorization pause")
        updated = plan
        for step in plan.steps:
            if step.state is not StepState.BLOCKED:
                continue
            step_result = self._repository.get_step_result(plan.plan_id, step.step_id)
            if step.step_id != step_id and step_result is not None:
                continue
            updated = self._repository.transition_step(
                plan.plan_id,
                step.step_id,
                StepState.PENDING,
                expected_state=StepState.BLOCKED,
                authorization_state=AuthorizationState.PENDING,
                reason_code="PLAN_AUTHORIZATION_RESUMED",
                at=self._clock.now(),
            )
        return self._repository.transition_plan(
            updated.plan_id,
            PlanStatus.PENDING,
            expected_status=PlanStatus.BLOCKED,
            reason_code="PLAN_AUTHORIZATION_RESUMED",
            at=self._clock.now(),
        )

    def _resolve_plan(self, plan: ExecutionPlan | str) -> ExecutionPlan:
        if isinstance(plan, ExecutionPlan):
            return plan
        if not isinstance(plan, str) or not plan.strip():
            raise InputInvalidError("plan identifier is invalid")
        loaded = self._repository.get_plan(plan)
        if loaded is None:
            raise InputInvalidError("execution plan was not found")
        return loaded

    def _start_task_if_available(self, plan: ExecutionPlan, request: TaskRequest) -> None:
        get_session = getattr(self._repository, "get_session", None)
        start_task = getattr(self._repository, "start_task", None)
        if callable(get_session) and callable(start_task):
            if get_session(request.session_id) is not None:
                start_task(plan.task_id, request.session_id, self._clock.now())

    def _finish_task_if_available(self, result: PlanExecutionResult) -> None:
        save_task_result = getattr(self._repository, "save_task_result", None)
        task_session_id = getattr(self._repository, "task_session_id", None)
        if (
            result.final_result is not None
            and callable(save_task_result)
            and callable(task_session_id)
            and task_session_id(result.plan.task_id) is not None
        ):
            save_task_result(result.final_result, self._clock.now())
        finish_task = getattr(self._repository, "finish_task", None)
        if not callable(finish_task):
            return
        task_status = (
            result.final_result.task_status.value
            if result.final_result is not None
            and result.final_result.task_status
            in {TaskStatus.AWAITING_CONSENT, TaskStatus.AWAITING_CONFIRMATION}
            else ("failed" if result.status is PlanStatus.UNAVAILABLE else result.status.value)
        )
        finish_task(result.plan.task_id, task_status, self._clock.now())
