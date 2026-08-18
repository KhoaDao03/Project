"""Application runtime boundary for Elly's outer request lifecycle."""

from __future__ import annotations

import time
import uuid
from concurrent.futures import Future
from dataclasses import dataclass, replace
from threading import RLock

from ..application.action_authorization import (
    ActionAuthorizationService,
    safe_action_target_reference,
)
from ..domain.context import resolve_conversation_context
from ..domain.enums import (
    CloudMode,
    ErrorClass,
    OutcomeCode,
    PersistenceMode,
    RouteReasonCode,
    TaskStatus,
)
from ..domain.errors import ConfigInvalidError, InputInvalidError, PermissionDeniedError
from ..domain.models import (
    ActionConfirmationProposal,
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
from ..privacy import ConsentProposal, ConsentWorkflow
from .completion import CompletionService
from .context_builder import ContextBuilder
from .execution import CancellationToken
from .local_conversation import LocalConversationUseCase
from .local_conversation_capability import LOCAL_CONVERSATION_CAPABILITY_ID
from .task_execution import PlanExecutionResult, TaskExecutionService
from .planning_service import PlanningService
from .recovery import RecoveryReport
from .replan import ReplanRequest, ReplanResult, ReplanTrigger
from .response_composer import (
    compose_blocked,
    compose_cancelled,
    compose_clarification,
    compose_possible_duplicate,
)
from .response_pipeline import ResponseCompositionService
from .route_compatibility import enrich_task_result, inherit_route_metadata


@dataclass(frozen=True, slots=True)
class _ExecutionContinuation:
    """Minimum in-process context required to resume one authorization pause."""

    task_id: str
    external_context: str
    local_context: str
    manifest: ContextManifest
    route_decision: RouteDecision


@dataclass(frozen=True, slots=True)
class _AuthorizationContinuation:
    """Process-local request/proposal context for one exact decision."""

    request: TaskRequest
    plan_id: str
    step_id: str
    manifest: ContextManifest
    route_decision: RouteDecision
    consent_proposal: ConsentProposal | None = None
    action_confirmation: ActionConfirmationProposal | None = None


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
        consent: ConsentWorkflow | None,
        action_authorization: ActionAuthorizationService,
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
        self._consent = consent
        self._action_authorization = action_authorization
        self._context_window = context_window
        self._guardrails = guardrails
        self._executor = executor
        self._continuation_lock = RLock()
        self._authorization_continuations: dict[str, _AuthorizationContinuation] = {}
        self._deciding_authorizations: set[str] = set()
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
        if planning or execution:
            return True
        return self._cancel_authorization_pause(task_id)

    def cancel_queued_task(self, task_id: str, session_id: str) -> None:
        """Materialize cancellation for work removed before runtime execution."""
        result = compose_cancelled(task_id=task_id)
        self._repository.start_task(task_id, session_id, self._clock.now())
        self._completion.persist_result(result)
        self._completion.finish_task(task_id, TaskStatus.CANCELLED)

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
        try:
            return self._handle_planned(request)
        except BaseException:
            # A planning/execution exception can happen after process-local
            # continuation context has been retained but before the normal
            # terminal update runs. Never leave an unusable resume target.
            self._clear_continuations_for_task(f"task-{request.request_id}")
            raise

    def submit(self, request: TaskRequest) -> Future[ConversationOutcome]:
        if self._executor is None:
            raise RuntimeError("task executor is not configured")
        return self._executor.submit(lambda: self.handle(request))

    def _authorization_resume_target(self, request: TaskRequest) -> tuple[str, str] | None:
        authorization_id = request.approval_id or request.action_confirmation_id
        if authorization_id is None:
            return None
        with self._continuation_lock:
            continuation = self._authorization_continuations.get(authorization_id)
            if continuation is None:
                return None
            return continuation.plan_id, continuation.step_id

    def authorization_task_id(self, authorization_id: str) -> str | None:
        """Return the task bound to a live process-local authorization request."""
        if not isinstance(authorization_id, str) or not authorization_id.strip():
            return None
        with self._continuation_lock:
            continuation = self._authorization_continuations.get(authorization_id)
            return f"task-{continuation.request.request_id}" if continuation else None

    def pending_action_for_task(self, task_id: str) -> ActionConfirmationProposal | None:
        """Return the runtime-owned pending action for public projection only."""
        with self._continuation_lock:
            for continuation in self._authorization_continuations.values():
                proposal = continuation.action_confirmation
                if proposal is not None and proposal.task_id == task_id:
                    return proposal
        return None

    def decide_consent(
        self,
        proposal_id: str,
        approve: bool,
        *,
        actor_id: str = "owner",
    ) -> Future[ConversationOutcome]:
        """Decide one exact consent proposal and own its task lifecycle."""
        if self._consent is None:
            raise ConfigInvalidError("consent workflow is unavailable")
        _require_authorization_decision(proposal_id, approve, actor_id)
        continuation = self._claim_authorization(proposal_id, consent=True)
        proposal = continuation.consent_proposal
        if proposal is None:  # pragma: no cover - guarded by the claim
            self._release_authorization(proposal_id)
            raise PermissionDeniedError("authorization request is not a consent proposal")

        try:
            if not approve:
                try:
                    self._consent.deny(
                        proposal_id,
                        interface=actor_id,
                        now=self._clock.now(),
                    )
                except PermissionDeniedError:
                    outcome = self._complete_authorization_block(
                        continuation,
                        reason="consent proposal is missing or expired",
                        event_type="consent.invalidated",
                        detail=f"proposal={proposal_id} actor={actor_id}",
                    )
                else:
                    outcome = self._complete_authorization_block(
                        continuation,
                        reason="consent denied",
                        event_type="consent.denied",
                        detail=f"proposal={proposal_id} actor={actor_id}",
                    )
                self._clear_plan_continuation(continuation.plan_id)
                self._release_authorization(proposal_id)
                return _completed_future(outcome)

            try:
                self._consent.approve(
                    proposal_id,
                    interface=actor_id,
                    now=self._clock.now(),
                )
            except PermissionDeniedError:
                outcome = self._complete_authorization_block(
                    continuation,
                    reason="consent proposal is missing or expired",
                    event_type="consent.invalidated",
                    detail=f"proposal={proposal_id} actor={actor_id}",
                )
                self._clear_plan_continuation(continuation.plan_id)
                self._release_authorization(proposal_id)
                return _completed_future(outcome)

            self._completion.emit(
                request=continuation.request,
                task_id=proposal.task_id,
                route=continuation.route_decision.generic_route,
                route_decision=continuation.route_decision,
                event_type="consent.approved",
                status=TaskStatus.AWAITING_CONSENT,
                detail=f"proposal={proposal_id} actor={actor_id}",
            )
            approved_request = replace(continuation.request, approval_id=proposal_id)
            return self._schedule_authorization_resume(
                continuation,
                proposal_id,
                approved_request,
            )
        except BaseException:
            self._clear_plan_continuation(continuation.plan_id)
            self._release_authorization(proposal_id)
            raise

    def decide_action(
        self,
        confirmation_id: str,
        approve: bool,
        *,
        actor_id: str = "owner",
    ) -> Future[ConversationOutcome]:
        """Decide one exact consequential-action confirmation."""
        _require_authorization_decision(confirmation_id, approve, actor_id)
        continuation = self._claim_authorization(confirmation_id, consent=False)
        proposal = continuation.action_confirmation
        if proposal is None:  # pragma: no cover - guarded by the claim
            self._release_authorization(confirmation_id)
            raise PermissionDeniedError("authorization request is not an action confirmation")

        try:
            if not approve:
                try:
                    self._action_authorization.confirmations.deny(
                        confirmation_id,
                        interface=actor_id,
                        now=self._clock.now(),
                    )
                except PermissionDeniedError:
                    outcome = self._complete_authorization_block(
                        continuation,
                        reason="action confirmation is missing or expired",
                        event_type="action.confirmation_invalidated",
                        detail=(
                            f"confirmation={confirmation_id} actor={actor_id}"
                        ),
                    )
                else:
                    outcome = self._complete_authorization_block(
                        continuation,
                        reason="action confirmation denied",
                        event_type="action.confirmation_denied",
                        detail=(
                            f"confirmation={confirmation_id} "
                            f"category={proposal.proposal.category.value} "
                            f"target={safe_action_target_reference(proposal.proposal.target)} "
                            f"digest={proposal.action_digest[:16]} actor={actor_id}"
                        ),
                    )
                self._clear_plan_continuation(continuation.plan_id)
                self._release_authorization(confirmation_id)
                return _completed_future(outcome)

            try:
                self._action_authorization.confirmations.approve(
                    confirmation_id,
                    interface=actor_id,
                    now=self._clock.now(),
                )
            except PermissionDeniedError:
                outcome = self._complete_authorization_block(
                    continuation,
                    reason="action confirmation is missing or expired",
                    event_type="action.confirmation_invalidated",
                    detail=f"confirmation={confirmation_id} actor={actor_id}",
                )
                self._clear_plan_continuation(continuation.plan_id)
                self._release_authorization(confirmation_id)
                return _completed_future(outcome)

            self._completion.emit(
                request=continuation.request,
                task_id=proposal.task_id,
                route=continuation.route_decision.generic_route,
                route_decision=continuation.route_decision,
                event_type="action.confirmation_approved",
                status=TaskStatus.AWAITING_CONFIRMATION,
                detail=(
                    f"confirmation={confirmation_id} "
                    f"category={proposal.proposal.category.value} "
                    f"target={safe_action_target_reference(proposal.proposal.target)} "
                    f"digest={proposal.action_digest[:16]} actor={actor_id}"
                ),
            )
            approved_request = replace(
                continuation.request,
                action_confirmation_id=confirmation_id,
            )
            return self._schedule_authorization_resume(
                continuation,
                confirmation_id,
                approved_request,
            )
        except BaseException:
            self._clear_plan_continuation(continuation.plan_id)
            self._release_authorization(confirmation_id)
            raise

    def _claim_authorization(
        self,
        authorization_id: str,
        *,
        consent: bool,
    ) -> _AuthorizationContinuation:
        with self._continuation_lock:
            continuation = self._authorization_continuations.get(authorization_id)
            if continuation is None or authorization_id in self._deciding_authorizations:
                raise PermissionDeniedError(
                    "authorization request is missing or already being decided"
                )
            if consent and continuation.consent_proposal is None:
                raise PermissionDeniedError("authorization request is not a consent proposal")
            if not consent and continuation.action_confirmation is None:
                raise PermissionDeniedError(
                    "authorization request is not an action confirmation"
                )
            self._deciding_authorizations.add(authorization_id)
            return continuation

    def _release_authorization(self, authorization_id: str) -> None:
        with self._continuation_lock:
            self._authorization_continuations.pop(authorization_id, None)
            self._deciding_authorizations.discard(authorization_id)

    def _schedule_authorization_resume(
        self,
        continuation: _AuthorizationContinuation,
        authorization_id: str,
        request: TaskRequest,
    ) -> Future[ConversationOutcome]:
        def operation() -> ConversationOutcome:
            return self._resume_authorization(continuation, authorization_id, request)

        if self._executor is not None:
            try:
                return self._executor.submit(operation)
            except BaseException:
                self._clear_plan_continuation(continuation.plan_id)
                self._release_authorization(authorization_id)
                raise
        future: Future[ConversationOutcome] = Future()
        try:
            future.set_result(operation())
        except BaseException as exc:
            future.set_exception(exc)
        return future

    def _resume_authorization(
        self,
        continuation: _AuthorizationContinuation,
        authorization_id: str,
        request: TaskRequest,
    ) -> ConversationOutcome:
        try:
            return self.handle(request)
        except BaseException:
            self._clear_plan_continuation(continuation.plan_id)
            raise
        finally:
            self._release_authorization(authorization_id)

    def _complete_authorization_block(
        self,
        continuation: _AuthorizationContinuation,
        *,
        reason: str,
        event_type: str,
        detail: str,
    ) -> ConversationOutcome:
        proposal = continuation.consent_proposal or continuation.action_confirmation
        if proposal is None:  # pragma: no cover - guarded by the claim
            raise ConfigInvalidError("authorization continuation proposal is unavailable")
        task_id = proposal.task_id
        blocked = compose_blocked(
            task_id=task_id,
            reason=reason,
            route=continuation.route_decision.generic_route,
            outcome_code=OutcomeCode.BLOCKED,
        )
        existing = self._repository.get_task_result(task_id)
        if existing is not None:
            blocked = inherit_route_metadata(blocked, existing)
        else:
            blocked = enrich_task_result(blocked, continuation.route_decision)
        self._completion.emit(
            request=continuation.request,
            task_id=task_id,
            route=continuation.route_decision.generic_route,
            route_decision=continuation.route_decision,
            event_type=event_type,
            status=TaskStatus.BLOCKED,
            error_class=ErrorClass.PERMISSION_DENIED,
            detail=detail,
        )
        durable = self._completion.persist_result(blocked)
        self._completion.finish_task(task_id, TaskStatus.BLOCKED)
        return ConversationOutcome(result=durable, manifest=continuation.manifest)

    def _cancel_authorization_pause(self, task_id: str) -> bool:
        with self._continuation_lock:
            pending = tuple(
                (authorization_id, continuation)
                for authorization_id, continuation in self._authorization_continuations.items()
                if continuation.request.request_id
                and f"task-{continuation.request.request_id}" == task_id
                and authorization_id not in self._deciding_authorizations
            )
        if not pending:
            return False
        for authorization_id, continuation in pending:
            if continuation.consent_proposal is not None and self._consent is not None:
                try:
                    self._consent.deny(
                        authorization_id,
                        interface="cancellation",
                        now=self._clock.now(),
                    )
                except PermissionDeniedError:
                    pass
            if continuation.action_confirmation is not None:
                try:
                    self._action_authorization.confirmations.deny(
                        authorization_id,
                        interface="cancellation",
                        now=self._clock.now(),
                    )
                except PermissionDeniedError:
                    pass
            cancelled = compose_cancelled(
                task_id=task_id,
                partial_work="authorization pause cancelled",
                route=continuation.route_decision.generic_route,
            )
            existing = self._repository.get_task_result(task_id)
            if existing is not None:
                cancelled = inherit_route_metadata(cancelled, existing)
            else:
                cancelled = enrich_task_result(cancelled, continuation.route_decision)
            self._completion.emit(
                request=continuation.request,
                task_id=task_id,
                route=continuation.route_decision.generic_route,
                route_decision=continuation.route_decision,
                event_type="authorization.cancelled",
                status=TaskStatus.CANCELLED,
                error_class=ErrorClass.CANCELLED,
                detail=f"authorization={authorization_id}",
            )
            self._completion.persist_result(cancelled)
            self._completion.finish_task(task_id, TaskStatus.CANCELLED)
            self._clear_plan_continuation(continuation.plan_id)
            self._release_authorization(authorization_id)
        return True

    def _clear_plan_continuation(self, plan_id: str) -> None:
        with self._continuation_lock:
            self._execution_continuations.pop(plan_id, None)
            for authorization_id, continuation in tuple(
                self._authorization_continuations.items()
            ):
                if continuation.plan_id == plan_id:
                    self._authorization_continuations.pop(authorization_id, None)
                    self._deciding_authorizations.discard(authorization_id)

    def _clear_continuations_for_task(self, task_id: str) -> None:
        with self._continuation_lock:
            plan_ids = {
                plan_id
                for plan_id, continuation in self._execution_continuations.items()
                if continuation.task_id == task_id
            }
            plan_ids.update(
                continuation.plan_id
                for continuation in self._authorization_continuations.values()
                if f"task-{continuation.request.request_id}" == task_id
            )
            for plan_id in plan_ids:
                self._execution_continuations.pop(plan_id, None)
            for authorization_id, continuation in tuple(
                self._authorization_continuations.items()
            ):
                if (
                    f"task-{continuation.request.request_id}" == task_id
                    or continuation.plan_id in plan_ids
                ):
                    self._authorization_continuations.pop(authorization_id, None)
                    self._deciding_authorizations.discard(authorization_id)

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
                    task_id=plan.task_id,
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
            consumed_authorization_id = request.approval_id or request.action_confirmation_id
            if consumed_authorization_id is not None:
                self._authorization_continuations.pop(consumed_authorization_id, None)
            if execution.consent_proposal is not None:
                proposal = execution.consent_proposal
                self._authorization_continuations[proposal.proposal_id] = (
                    _AuthorizationContinuation(
                        request=request,
                        plan_id=proposal.plan_id,
                        step_id=proposal.step_id,
                        manifest=self._execution_continuations[plan.plan_id].manifest,
                        route_decision=self._execution_continuations[plan.plan_id].route_decision,
                        consent_proposal=proposal,
                    )
                )
            if execution.action_confirmation is not None:
                confirmation = execution.action_confirmation
                self._authorization_continuations[confirmation.confirmation_id] = (
                    _AuthorizationContinuation(
                        request=request,
                        plan_id=confirmation.plan_id,
                        step_id=confirmation.step_id,
                        manifest=self._execution_continuations[plan.plan_id].manifest,
                        route_decision=self._execution_continuations[plan.plan_id].route_decision,
                        action_confirmation=confirmation,
                    )
                )
            if execution.consent_proposal is None and execution.action_confirmation is None:
                self._execution_continuations.pop(plan.plan_id, None)


def _completed_future(outcome: ConversationOutcome) -> Future[ConversationOutcome]:
    future: Future[ConversationOutcome] = Future()
    future.set_result(outcome)
    return future


def _require_authorization_decision(
    authorization_id: str,
    approve: bool,
    actor_id: str,
) -> None:
    if not isinstance(authorization_id, str) or not authorization_id.strip():
        raise InputInvalidError("authorization id must be non-empty")
    if not isinstance(approve, bool):
        raise InputInvalidError("authorization decision must be boolean")
    if not isinstance(actor_id, str) or not actor_id.strip():
        raise InputInvalidError("authorization actor id must be non-empty")


__all__ = ["AssistantRuntime"]
