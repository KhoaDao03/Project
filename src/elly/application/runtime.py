"""Application runtime boundary for Elly's outer request lifecycle."""

from __future__ import annotations

import time
import uuid
from concurrent.futures import Future
from dataclasses import dataclass
from threading import RLock

from ..domain.context import resolve_conversation_context
from ..domain.enums import (
    CloudMode,
    ErrorClass,
    PersistenceMode,
    RouteReasonCode,
    TaskStatus,
)
from ..domain.errors import ConfigInvalidError
from ..domain.models import (
    ContextManifest,
    ConversationOutcome,
    Message,
    RouteDecision,
    RouteRequest,
    SessionRecord,
    TaskRequest,
    TaskResult,
)
from ..guardrails import BoundedTaskExecutor, GuardrailController
from ..planning.contracts import ExecutionPlan, ExecutionProposal, ProposalDisposition
from ..ports.clock import ClockPort
from ..ports.plan_repository import PlanRepositoryPort
from ..ports.repository import SessionRepositoryPort
from .completion import CompletionService
from .context_builder import ContextBuilder
from .execution import CancellationToken
from .local_conversation import LocalConversationUseCase
from .local_conversation_capability import LOCAL_CONVERSATION_CAPABILITY_ID
from .plan_executor import PlanExecutionResult, TaskExecutionService
from .planning_service import PlanningService
from .recovery import RecoveryReport
from .replan import ReplanRequest, ReplanResult, ReplanTrigger
from .response_composer import (
    compose_blocked,
    compose_clarification,
    compose_possible_duplicate,
)
from .response_pipeline import ResponseCompositionService
from .route_compatibility import enrich_task_result


@dataclass(frozen=True, slots=True)
class _ExecutionContinuation:
    """Minimum in-process context required to resume one authorization pause."""

    external_context: str
    local_context: str
    manifest: ContextManifest
    route_decision: RouteDecision


class AssistantRuntime:
    """Coordinate one request from context loading through durable completion.

    Normal final task status and ``TaskResult`` persistence are authoritative
    here. ``TaskExecutionService`` owns execution state; this runtime owns the
    surrounding request, plan, message, and authorization-continuation lifecycle.
    """

    def __init__(
        self,
        *,
        clock: ClockPort,
        repository: SessionRepositoryPort,
        plan_repository: PlanRepositoryPort,
        planning_service: PlanningService,
        task_execution_service: TaskExecutionService,
        context_builder: ContextBuilder,
        completion: CompletionService,
        response_pipeline: ResponseCompositionService,
        local_conversation: LocalConversationUseCase,
        context_window: int,
        guardrails: GuardrailController | None = None,
        executor: BoundedTaskExecutor | None = None,
    ) -> None:
        self._clock = clock
        self._repository = repository
        self._plan_repository = plan_repository
        self._planning_service = planning_service
        self._task_execution_service = task_execution_service
        self._context_builder = context_builder
        self._completion = completion
        self._response_pipeline = response_pipeline
        self._local_conversation = local_conversation
        self._context_window = context_window
        self._guardrails = guardrails
        self._executor = executor
        self._continuation_lock = RLock()
        self._authorization_targets: dict[str, tuple[str, str]] = {}
        self._execution_continuations: dict[str, _ExecutionContinuation] = {}

    def new_session(
        self,
        *,
        persistence_mode: PersistenceMode = PersistenceMode.STORE_WITH_RETENTION,
        cloud_mode: CloudMode = CloudMode.LOCAL_ONLY,
    ) -> SessionRecord:
        record = SessionRecord(
            session_id=f"session-{uuid.uuid4().hex[:12]}",
            persistence_mode=persistence_mode,
            cloud_mode=cloud_mode,
            created_at=self._clock.now(),
        )
        self._repository.create_session(record)
        return record

    def cancel_active(self) -> bool:
        planning = self._planning_service.cancel()
        execution = self._task_execution_service.cancel_active()
        return planning or execution

    def cancel_task(self, task_id: str) -> bool:
        planning = self._planning_service.cancel(task_id)
        execution = self._task_execution_service.cancel_task(task_id)
        return planning or execution

    def cancel_plan(self, plan_id: str) -> bool:
        return self._task_execution_service.cancel(plan_id)

    def reconcile_plans(self) -> tuple[RecoveryReport, ...]:
        return self._task_execution_service.reconcile_startup()

    def replan_plan(
        self,
        source_plan: ExecutionPlan | str,
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
        return self._task_execution_service.replan(
            source_plan,
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

    def execute_plan(
        self,
        plan: ExecutionPlan | str,
        *,
        request: TaskRequest,
        context_text: str,
        context_manifest: ContextManifest,
        local_context_text: str = "",
        cancellation: CancellationToken | None = None,
        request_guardrails: GuardrailController | None = None,
        manage_task_lifecycle: bool = True,
    ) -> PlanExecutionResult:
        effective_guardrails = request_guardrails
        if effective_guardrails is None and self._guardrails is not None:
            effective_guardrails = self._guardrails.for_request()
        return self._task_execution_service.execute(
            plan,
            request=request,
            context_text=context_text,
            context_manifest=context_manifest,
            local_context_text=local_context_text,
            cancellation=cancellation,
            request_guardrails=effective_guardrails,
            manage_task_lifecycle=manage_task_lifecycle,
        )

    def handle(self, request: TaskRequest) -> ConversationOutcome:
        return self._handle_planned(request)

    def submit(self, request: TaskRequest) -> Future[ConversationOutcome]:
        if self._executor is None:
            raise RuntimeError("task executor is not configured")
        return self._executor.submit(lambda: self.handle(request))

    def _authorization_resume_target(self, request: TaskRequest) -> tuple[str, str] | None:
        authorization_id = request.approval_id or request.action_confirmation_id
        if authorization_id is None:
            return None
        with self._continuation_lock:
            return self._authorization_targets.get(authorization_id)

    def _handle_direct_planning_result(
        self,
        request: TaskRequest,
        route_decision: RouteDecision,
        prompt: str,
        context_manifest: ContextManifest,
    ) -> ConversationOutcome:
        task_id = f"task-{request.request_id}"
        task_created = self._repository.start_task(
            task_id,
            request.session_id,
            self._clock.now(),
        )
        if task_created:
            self._repository.append_message(
                request.session_id,
                Message("user", request.text, self._clock.now()),
            )
        if route_decision.clarification_required:
            result = compose_clarification(
                task_id=task_id,
                fields=route_decision.clarification_fields,
                route=route_decision.generic_route,
            )
            event_type = "intent.clarification_required"
            error_class = ErrorClass.INPUT_INVALID
            detail = f"fields={','.join(route_decision.clarification_fields)}"
        else:
            unsupported_action = (
                route_decision.reason_code is RouteReasonCode.ACTION_UNSUPPORTED
            )
            result = compose_blocked(
                task_id=task_id,
                reason=(
                    "the requested consequential action is not supported"
                    if unsupported_action
                    else "the request could not be converted into an executable plan"
                ),
                route=route_decision.generic_route,
            )
            event_type = (
                "action.authorization_denied" if unsupported_action else "planning.unable"
            )
            error_class = ErrorClass.PERMISSION_DENIED
            detail = (
                "reason=ACTION_UNSUPPORTED provider_dispatch=not_started"
                if unsupported_action
                else "provider_dispatch=not_started"
            )
        result = self._response_pipeline.compose_task_result(
            result,
            request=request,
            approved_context=prompt,
        ).result
        result = enrich_task_result(result, route_decision)
        self._completion.emit(
            request=request,
            task_id=task_id,
            route=route_decision.generic_route,
            route_decision=route_decision,
            event_type=event_type,
            status=TaskStatus.BLOCKED,
            error_class=error_class,
            detail=detail,
        )
        self._completion.persist_result(result)
        self._completion.finish_task(task_id, TaskStatus.BLOCKED)
        return ConversationOutcome(result=result, manifest=context_manifest)

    def _handle_planned(self, request: TaskRequest) -> ConversationOutcome:
        task_id = f"task-{request.request_id}"
        resume_target = self._authorization_resume_target(request)
        if resume_target is not None:
            plan_id, step_id = resume_target
            plan = self._task_execution_service.resume_authorized_step(plan_id, step_id)
            with self._continuation_lock:
                continuation = self._execution_continuations.get(plan_id)
            if continuation is None:
                raise ConfigInvalidError("authorization continuation context is unavailable")
            context_text = continuation.external_context
            local_context_text = continuation.local_context
            context_manifest = continuation.manifest
            route_decision = continuation.route_decision
        else:
            history = self._repository.recent_messages(
                request.session_id,
                self._context_window,
            )
            conversation_context = resolve_conversation_context(
                current_text=request.text,
                history=history,
            )
            prompt, context_manifest = self._context_builder.build(
                current_text=request.text,
                history=history,
            )
            planning = self._planning_service.plan(
                RouteRequest(
                    request_id=request.request_id,
                    text=request.text,
                    contextual_text=conversation_context.routing_text,
                    cloud_mode=request.cloud_mode,
                ),
                task_id,
                approved_context=prompt,
            )
            decision = planning.decision
            route_decision = decision.route_decision
            if decision.proposal.disposition is not ProposalDisposition.CAPABILITY_PLAN:
                return self._handle_direct_planning_result(
                    request,
                    route_decision,
                    prompt,
                    context_manifest,
                )
            planned_plan = planning.plan
            if planned_plan is None:
                raise ConfigInvalidError("planning returned no execution plan")
            plan = planned_plan
            if self._repository.get_task_result(task_id) is not None:
                duplicate = enrich_task_result(
                    compose_possible_duplicate(
                        task_id=task_id,
                        route=route_decision.generic_route,
                    ),
                    route_decision,
                )
                return ConversationOutcome(result=duplicate, manifest=context_manifest)
            self._plan_repository.save_plan(plan, at=self._clock.now())
            context_text = conversation_context.remote_text
            local_context_text = prompt
            task_created = self._repository.start_task(
                task_id,
                request.session_id,
                self._clock.now(),
            )
            if task_created:
                self._repository.append_message(
                    request.session_id,
                    Message("user", request.text, self._clock.now()),
                )
            self._plan_repository.append_plan_event(
                plan.plan_id,
                "plan.interpreted",
                decision.proposal.reason_code,
                (
                    f"catalog={decision.catalog_version} "
                    f"fallback={str(decision.fallback_used).lower()} "
                    f"strategy={planning.strategy.value}"
                ),
                at=self._clock.now(),
            )
            with self._continuation_lock:
                self._execution_continuations[plan.plan_id] = _ExecutionContinuation(
                    external_context=context_text,
                    local_context=local_context_text,
                    manifest=context_manifest,
                    route_decision=route_decision,
                )

        started = time.monotonic()
        request_guardrails = (
            self._guardrails.for_request() if self._guardrails is not None else None
        )
        execution = self.execute_plan(
            plan,
            request=request,
            context_text=context_text,
            context_manifest=context_manifest,
            local_context_text=local_context_text,
            request_guardrails=request_guardrails,
            manage_task_lifecycle=False,
        )
        final_result = execution.final_result
        if final_result is None:
            raise ConfigInvalidError("plan execution returned no final result")
        final_result = enrich_task_result(final_result, route_decision)
        self._completion.record_sources(plan.task_id, final_result.citations)
        self._completion.record_provenance(plan.task_id, final_result.provenance)
        self._completion.persist_result(final_result)
        self._completion.finish_task(plan.task_id, final_result.task_status)
        if len(plan.steps) == 1:
            self._emit_single_step_completion(
                request,
                plan,
                execution,
                final_result,
                route_decision,
                request_guardrails,
                started,
            )
        assistant_message: Message | None = None
        if (
            final_result.answer_retained
            and final_result.answer
            and final_result.task_status.value
            not in {"awaiting_consent", "awaiting_confirmation"}
        ):
            assistant_message = Message("assistant", final_result.answer, self._clock.now())
            self._repository.append_message(request.session_id, assistant_message)
        self._update_continuation(plan, request, execution)
        return ConversationOutcome(
            result=final_result,
            manifest=context_manifest,
            assistant_message=assistant_message,
            consent_proposal=execution.consent_proposal,
            action_confirmation=execution.action_confirmation,
        )

    def _emit_single_step_completion(
        self,
        request: TaskRequest,
        plan: ExecutionPlan,
        execution: PlanExecutionResult,
        final_result: TaskResult,
        route_decision: RouteDecision,
        request_guardrails: GuardrailController | None,
        started: float,
    ) -> None:
        local_step = plan.steps[0].capability_id == LOCAL_CONVERSATION_CAPABILITY_ID
        event_type = (
            "task.completed"
            if local_step and final_result.task_status is TaskStatus.COMPLETED
            else "task.cancelled"
            if local_step and final_result.task_status is TaskStatus.CANCELLED
            else "generalist.failed"
            if local_step
            else "capability.completed"
        )
        detail = (
            f"capability={plan.steps[0].capability_id} "
            f"operation={plan.steps[0].operation_id} unified_plan=true"
        )
        if local_step:
            envelope = execution.step_envelopes.get(plan.steps[0].step_id)
            usage = envelope.usage if envelope is not None else None
            detail = (
                f"provider={type(self._local_conversation.generalist).__name__} "
                f"model={self._local_conversation.model_id} "
                "prompt=local-generalist-v1 tools=none "
                f"duration_ms={int((time.monotonic() - started) * 1000)} "
                f"output_tokens={usage.output_tokens if usage is not None else 0} "
                f"latency_ms={usage.latency_ms if usage is not None else 0} "
                f"{self._completion.guardrail_detail(request_guardrails)} "
                "unified_plan=true"
            )
        self._completion.emit(
            request=request,
            task_id=plan.task_id,
            route=route_decision.generic_route,
            route_decision=route_decision,
            event_type=event_type,
            status=final_result.task_status,
            detail=detail,
        )

    def _update_continuation(
        self,
        plan: ExecutionPlan,
        request: TaskRequest,
        execution: PlanExecutionResult,
    ) -> None:
        with self._continuation_lock:
            if execution.consent_proposal is not None:
                proposal = execution.consent_proposal
                self._authorization_targets[proposal.proposal_id] = (
                    proposal.plan_id,
                    proposal.step_id,
                )
            if execution.action_confirmation is not None:
                confirmation = execution.action_confirmation
                self._authorization_targets[confirmation.confirmation_id] = (
                    confirmation.plan_id,
                    confirmation.step_id,
                )
            if execution.consent_proposal is None and execution.action_confirmation is None:
                self._execution_continuations.pop(plan.plan_id, None)
                authorization_id = request.approval_id or request.action_confirmation_id
                if authorization_id is not None:
                    self._authorization_targets.pop(authorization_id, None)


__all__ = ["AssistantRuntime"]
