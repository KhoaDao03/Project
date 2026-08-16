"""Plan lifecycle façade around the independent V3 scheduler."""

from __future__ import annotations

from threading import RLock

from ..domain.enums import TaskStatus
from ..domain.errors import ConfigInvalidError, InputInvalidError
from ..domain.models import ContextManifest, TaskRequest
from ..guardrails.controller import GuardrailController
from ..planning.contracts import (
    AuthorizationState,
    ExecutionPlan,
    ExecutionProposal,
    PlanStatus,
    StepState,
)
from ..ports.clock import ClockPort
from ..ports.plan_repository import PlanRepositoryPort
from .execution import CancellationToken
from .plan_executor import (
    PlanExecutionRequest,
    PlanExecutionResult,
    PlanExecutor,
)
from .replan import ReplanRequest, ReplanResult, ReplanService, ReplanTrigger


class PlanOrchestrator:
    """Own plan lookup, task lifecycle handoff, and request-scoped cancellation.

    Conversation orchestration remains a separate path.  This class only
    accepts a persisted validated plan and delegates dependency scheduling to
    ``PlanExecutor``.
    """

    def __init__(
        self,
        *,
        repository: PlanRepositoryPort,
        executor: PlanExecutor,
        clock: ClockPort,
        replan_service: ReplanService | None = None,
    ) -> None:
        if not isinstance(executor, PlanExecutor):
            raise ConfigInvalidError("plan orchestrator requires a PlanExecutor")
        if not isinstance(clock, ClockPort):
            raise ConfigInvalidError("plan orchestrator requires a clock")
        self._repository = repository
        self._executor = executor
        self._clock = clock
        self._replan_service = replan_service
        self._lock = RLock()
        self._active: dict[str, CancellationToken] = {}
        self._active_tasks: dict[str, str] = {}

    def execute(
        self,
        plan: ExecutionPlan | str,
        *,
        execution: PlanExecutionRequest | None = None,
        request: TaskRequest | None = None,
        context_text: str | None = None,
        context_manifest: ContextManifest | None = None,
        cancellation: CancellationToken | None = None,
        request_guardrails: GuardrailController | None = None,
    ) -> PlanExecutionResult:
        """Execute one persisted plan synchronously and return its safe outcome."""
        if execution is not None:
            if not isinstance(execution, PlanExecutionRequest):
                raise InputInvalidError("plan orchestrator execution context is invalid")
            request = execution.request
            context_text = execution.context_text
            context_manifest = execution.context_manifest
            cancellation = execution.cancellation
            request_guardrails = execution.request_guardrails
        if request is None or context_text is None or context_manifest is None:
            raise InputInvalidError("plan orchestrator execution context is incomplete")
        if not isinstance(request, TaskRequest):
            raise InputInvalidError("plan orchestrator request is invalid")
        resolved = self._resolve_plan(plan)
        token = cancellation or CancellationToken()
        with self._lock:
            self._active[resolved.plan_id] = token
            self._active_tasks[resolved.task_id] = resolved.plan_id
        self._start_task_if_available(resolved, request)
        try:
            result = self._executor.execute(
                resolved,
                PlanExecutionRequest(
                    request=request,
                    context_text=context_text,
                    context_manifest=context_manifest,
                    cancellation=token,
                    request_guardrails=request_guardrails,
                ),
            )
            self._finish_task_if_available(result)
            return result
        finally:
            with self._lock:
                self._active.pop(resolved.plan_id, None)
                self._active_tasks.pop(resolved.task_id, None)

    run = execute

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
        """Create a bounded replacement through the shared replan policy."""
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
        """Request cancellation of one in-process plan run."""
        with self._lock:
            token = self._active.get(plan_id)
        if token is None:
            return False
        token.cancel()
        return True

    def cancel_active(self) -> bool:
        """Request cancellation of one active plan, if present."""
        with self._lock:
            token = next(iter(self._active.values()), None)
        if token is None:
            return False
        token.cancel()
        return True

    def cancel_task(self, task_id: str) -> bool:
        """Request cancellation using the public task identifier."""
        with self._lock:
            plan_id = self._active_tasks.get(task_id)
        return self.cancel(plan_id) if plan_id is not None else False

    def resume_authorized_step(self, plan_id: str, step_id: str) -> ExecutionPlan:
        """Reset only a persisted authorization pause on the same revision."""
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

    cancel_plan = cancel

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
        if not callable(get_session) or not callable(start_task):
            return
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
        if callable(finish_task):
            # PlanStatus.UNAVAILABLE has no legacy TaskStatus member. The
            # additive plan view retains the precise value while the existing
            # task lifecycle uses the closest safe terminal status.
            task_status = (
                result.final_result.task_status.value
                if result.final_result is not None
                and result.final_result.task_status
                in {TaskStatus.AWAITING_CONSENT, TaskStatus.AWAITING_CONFIRMATION}
                else ("failed" if result.status is PlanStatus.UNAVAILABLE else result.status.value)
            )
            finish_task(result.plan.task_id, task_status, self._clock.now())


__all__ = ["PlanOrchestrator"]
