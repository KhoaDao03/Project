"""Compatibility façade for the canonical task execution service."""

from __future__ import annotations

from ..domain.errors import ConfigInvalidError
from ..domain.models import ContextManifest, TaskRequest
from ..guardrails.controller import GuardrailController
from ..planning.contracts import ExecutionPlan, ExecutionProposal
from ..ports.clock import ClockPort
from ..ports.plan_repository import PlanRepositoryPort
from .execution import CancellationToken
from .plan_executor import (
    PlanExecutionRequest,
    PlanExecutionResult,
    TaskExecutionService,
)
from .replan import ReplanRequest, ReplanResult, ReplanService, ReplanTrigger


class PlanOrchestrator:
    """Delegate the historical API to ``TaskExecutionService`` without state.

    ``repository``, ``clock``, and ``replan_service`` remain accepted only for
    constructor compatibility. The execution service owns lifecycle,
    cancellation, recovery, and bounded replan state. Retire this façade after
    direct callers migrate in Phase 10.
    """

    def __init__(
        self,
        *,
        repository: PlanRepositoryPort,
        execution_service: TaskExecutionService,
        clock: ClockPort,
        replan_service: ReplanService | None = None,
    ) -> None:
        del repository, clock, replan_service
        if not isinstance(execution_service, TaskExecutionService):
            raise ConfigInvalidError(
                "plan orchestrator requires a TaskExecutionService"
            )
        self._execution_service = execution_service

    def execute(
        self,
        plan: ExecutionPlan | str,
        *,
        execution: PlanExecutionRequest | None = None,
        request: TaskRequest | None = None,
        context_text: str | None = None,
        context_manifest: ContextManifest | None = None,
        local_context_text: str = "",
        cancellation: CancellationToken | None = None,
        request_guardrails: GuardrailController | None = None,
        manage_task_lifecycle: bool = True,
    ) -> PlanExecutionResult:
        return self._execution_service.execute(
            plan,
            execution,
            request=request,
            context_text=context_text,
            context_manifest=context_manifest,
            local_context_text=local_context_text,
            cancellation=cancellation,
            request_guardrails=request_guardrails,
            manage_task_lifecycle=manage_task_lifecycle,
        )

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
        return self._execution_service.replan(
            plan,
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
        return self._execution_service.cancel(plan_id)

    cancel_plan = cancel

    def cancel_active(self) -> bool:
        return self._execution_service.cancel_active()

    def cancel_task(self, task_id: str) -> bool:
        return self._execution_service.cancel_task(task_id)

    def resume_authorized_step(self, plan_id: str, step_id: str) -> ExecutionPlan:
        return self._execution_service.resume_authorized_step(plan_id, step_id)


__all__ = ["PlanOrchestrator"]
