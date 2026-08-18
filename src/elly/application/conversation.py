"""Legacy direct-conversation compatibility boundary.

This module is not constructed by the composition root or public V2 API.  The
normal request path is ``AssistantRuntime`` -> ``PlanningService`` ->
``TaskExecutionService``.  The direct class remains only for established
characterization/integration callers that still supply historical routing
inputs; retire it after those callers migrate with equivalent behavior coverage.

Its `handle()` method preserves the historical direct-turn sequencing for those
callers; it is not a second normal request path or a source of public API task
lifecycle authority.

Status: Implemented (M1). Owner waived the "Owner implements with guidance"
exercise on 2026-08-03 and authorized this implementation.

Security/privacy invariants:
- Model output is a PROPOSAL, never an instruction or authorization (SEC-005).
- No secrets/bodies/chain-of-thought in audit `detail` (SEC-007) — `_emit` passes
  only short, non-sensitive summaries.
- Persistence honors PersistenceMode at the repository boundary (DATA-001).

Related: UC-01, BUS-001, AI-002/006/010, FR-002/006, DATA-001/004, OPS-001, UX-001.
"""

from __future__ import annotations

import time
from dataclasses import replace
from threading import Lock

from ..domain.context import resolve_conversation_context
from ..domain.enums import ErrorClass, Route, RouteReasonCode, TaskStatus
from ..domain.errors import CancelledError, ConfigInvalidError, EllyError, StorageFailureError
from ..domain.models import (
    AuditEvent,
    ConversationOutcome,
    Message,
    ProvenanceReference,
    RouteDecision,
    RouteRequest,
    TaskRequest,
    TaskResult,
)
from ..domain.state_machine import ensure_transition
from ..guardrails.controller import GuardrailController
from ..memory import ProfileService
from ..ports.audit import AuditPort
from ..ports.clock import ClockPort
from ..ports.repository import SessionRepositoryPort
from ..privacy import payload_hash
from .capability_workflow import CapabilityExecutionCommand, CapabilityExecutionWorkflow
from .completion import CompletionService
from .context_builder import ContextBuilder
from .execution import CancellationToken
from .local_conversation import LocalConversationUseCase
from .response_composer import (
    compose_blocked,
    compose_cancelled,
    compose_clarification,
    compose_failed,
    compose_partial,
    compose_possible_duplicate,
    compose_success,
)
from .response_pipeline import ResponseCompositionService
from .route_compatibility import enrich_task_result, is_local_route
from .routing import RoutingPolicy


class ConversationOrchestrator:
    """Sequence historical direct callers without becoming the normal runtime.

    Provider-specific optional execution and durable completion are delegated to
    ``CapabilityExecutionWorkflow`` and ``CompletionService``. The local model
    path is bound once through ``LocalConversationUseCase`` at composition time.
    """

    def __init__(
        self,
        *,
        clock: ClockPort,
        repository: SessionRepositoryPort,
        audit: AuditPort,
        context_window: int,
        local_conversation: LocalConversationUseCase,
        completion: CompletionService | None = None,
        capability_workflow: CapabilityExecutionWorkflow | None = None,
        guardrails: GuardrailController | None = None,
        profile_service: ProfileService | None = None,
        routing_policy: RoutingPolicy | None = None,
        context_builder: ContextBuilder | None = None,
        response_pipeline: ResponseCompositionService | None = None,
    ) -> None:
        self._clock = clock
        self._repository = repository
        self._audit = audit
        self._context_window = context_window
        self._guardrails = guardrails
        self._profile_service = profile_service
        self._completion = completion or CompletionService(
            clock=clock,
            repository=repository,
            audit=audit,
        )
        self._capability_workflow = capability_workflow
        if response_pipeline is not None and not isinstance(
            response_pipeline, ResponseCompositionService
        ):
            raise ConfigInvalidError("response pipeline is invalid")
        self._response_pipeline = response_pipeline
        self._active_lock = Lock()
        self._active_cancellation: CancellationToken | None = None
        self._active_cancellations: dict[str, CancellationToken] = {}
        self._routing_policy = routing_policy or RoutingPolicy()
        if not isinstance(local_conversation, LocalConversationUseCase):
            raise ConfigInvalidError("local_conversation must be constructed before orchestration")
        self._context_builder = context_builder or ContextBuilder(
            context_window=context_window,
            reserved_output_tokens=local_conversation.max_output_tokens,
        )
        self._local_conversation = local_conversation

    # ---- provided helpers (use these; do not re-implement) ----------------

    def route(self, request: TaskRequest, *, contextual_text: str | None = None) -> Route:
        """Deterministically route the resolved conversational request.

        Current-information or explicit research wording routes to web research;
        dependent turns may inherit that intent from one bounded prior user turn.
        Timeless conversation remains on the local generalist.
        """
        decision = self._routing_policy.decide(
            RouteRequest(
                request_id=request.request_id,
                text=request.text,
                contextual_text=contextual_text,  # Support follow up questions
                cloud_mode=request.cloud_mode,
            ),
            proposal=request.route_proposal,
        )
        return decision.generic_route

    def _emit(
        self,
        *,
        request: TaskRequest,
        task_id: str,
        route: Route,
        route_decision: RouteDecision | None = None,
        event_type: str,
        status: TaskStatus | None = None,
        error_class: ErrorClass | None = None,
        detail: str = "",
    ) -> None:
        """Append one redacted, correlated audit event (DATA-004/SEC-007)."""
        audit_route = route_decision.generic_route if route_decision is not None else route
        self._audit.append(
            AuditEvent(
                task_id=task_id,
                session_id=request.session_id,
                event_type=event_type,
                at=self._clock.now(),
                route=audit_route,
                task_status=status,
                error_class=error_class,
                detail=detail,
            )
        )

    @staticmethod
    def _guardrail_detail(request_guardrails: GuardrailController | None) -> str:
        """Render non-sensitive request usage for correlated audit events."""
        if request_guardrails is None:
            return "guardrails=disabled"
        steps, calls, active = request_guardrails.ledger.snapshot
        return (
            f"steps={steps} provider_calls={calls} retries={request_guardrails.retry_count} "
            f"active={active} estimated_cost_usd={request_guardrails.request_cost_usd:.4f}"
        )

    @classmethod
    def _failure_detail(
        cls,
        summary: str,
        started: float,
        request_guardrails: GuardrailController | None,
    ) -> str:
        """Add bounded execution metadata to a display-safe failure summary."""
        return (
            f"{summary} duration_ms={int((time.monotonic() - started) * 1000)} "
            f"{cls._guardrail_detail(request_guardrails)}"
        )

    def _start_task_record(self, task_id: str, request: TaskRequest) -> bool:
        return self._repository.start_task(task_id, request.session_id, self._clock.now())

    # ---- orchestration ----------------------------------------------------

    # Cancellation
    def cancel_active(self) -> bool:
        """Request cancellation of the currently executing turn, if any."""
        with self._active_lock:
            token = self._active_cancellation
            if token is None and self._active_cancellations:
                token = next(iter(self._active_cancellations.values()))
        if token is None:
            return False
        token.cancel()
        return True

    def cancel_task(self, task_id: str) -> bool:
        """Request cancellation of one identified in-flight task."""
        with self._active_lock:
            token = self._active_cancellations.get(task_id)
        if token is None:
            return False
        token.cancel()
        return True

    """
    handle()
    = lifecycle wrapper

    _handle()
    = business workflow
    """

    def handle(
        self,
        request: TaskRequest,
        *,
        route_decision: RouteDecision | None = None,
    ) -> ConversationOutcome:
        task_id = f"task-{request.request_id}"
        cancellation = CancellationToken()
        with self._active_lock:
            self._active_cancellations[task_id] = cancellation
            self._active_cancellation = cancellation
        try:
            return self._handle(
                request,
                cancellation=cancellation,
                route_decision=route_decision,
            )
        finally:
            with self._active_lock:
                self._active_cancellations.pop(task_id, None)
                if self._active_cancellation is cancellation:
                    self._active_cancellation = next(
                        iter(self._active_cancellations.values()), None
                    )

    def _handle(
        self,
        request: TaskRequest,
        *,
        cancellation: CancellationToken,
        route_decision: RouteDecision | None = None,
    ) -> ConversationOutcome:
        # Main method
        """Process one local conversational turn (UC-01).

        Deterministic sequence:
          1. correlate + record receipt;
          2. build minimum-sufficient context from PRIOR history (AI-006);
          3. persist the user turn (repository honors no-store, DATA-001);
          4. call the generalist via its port and VALIDATE the untrusted output;
          5. on any typed failure -> a BLOCKED result (no fabricated success,
             FR-006); on success -> persist the assistant turn and COMPLETE.

        Returns a ConversationOutcome. Never raises for provider/validation
        failures — those become a blocked TaskResult. Storage failures surface as
        typed EllyErrors to the caller (the CLI renders them as blocked).
        """
        started = time.monotonic()
        cancellation.raise_if_cancelled()
        task_id = f"task-{request.request_id}"
        request_guardrails = (
            self._guardrails.for_request() if self._guardrails is not None else None
        )
        # Read prior context before routing. A dependent turn such as "How about
        # silver?" inherits the current-information intent of "price of gold",
        # while a follow-up to a timeless local question stays local.
        history = self._repository.recent_messages(request.session_id, self._context_window)
        conversation_context = resolve_conversation_context(
            current_text=request.text, history=history
        )
        capability_context = conversation_context.remote_text
        route_request = RouteRequest(
            request_id=request.request_id,
            text=request.text,
            contextual_text=conversation_context.routing_text,
            cloud_mode=request.cloud_mode,
        )
        route_decision = route_decision or self._routing_policy.decide(
            route_request,
            proposal=request.route_proposal,
            intent=request.capability_intent,
        )
        route = route_decision.generic_route

        def decorate(result: TaskResult) -> TaskResult:
            return enrich_task_result(result, route_decision)

        def compose_response(
            result: TaskResult,
            *,
            approved_context: str | None = None,
        ) -> TaskResult:
            """Run the common presentation policy for a direct conversational turn."""
            if self._response_pipeline is None:
                return result
            composed = self._response_pipeline.compose_task_result(
                result,
                request=request,
                approved_context=prompt if approved_context is None else approved_context,
                cancellation=cancellation,
            )
            observation = composed.observation
            if observation is not None:
                try:
                    self._emit(
                        request=request,
                        task_id=task_id,
                        route=route,
                        route_decision=route_decision,
                        event_type=f"response_composer.{observation.outcome}",
                        status=composed.result.task_status,
                        detail=(
                            f"mode={observation.mode.value} attempted={int(observation.attempted)} "
                            f"outcome={observation.outcome} profile={observation.profile[:64]} "
                            f"model={observation.model_version[:128]} "
                            f"reason={observation.reason_code[:128]} "
                            f"result_refs={','.join(observation.result_refs)} "
                            f"claim_refs={','.join(observation.claim_refs)} "
                            f"citation_refs={','.join(observation.citation_refs)} "
                            f"warning_refs={','.join(observation.warning_refs)} "
                            f"disagreement_refs={','.join(observation.disagreement_refs)} "
                            f"record_refs={','.join(observation.immutable_record_refs)} "
                            f"duration_ms={observation.duration_ms} "
                            f"output_tokens={observation.output_tokens}"
                        )[:512],
                    )
                except StorageFailureError:
                    # Presentation telemetry must not turn a safe result into a
                    # second execution or a storage-driven provider retry.
                    pass
            return composed.result

        # Lifecycle transitions go through the state machine so the application —
        # not ad-hoc code — owns valid task states (AI-002, FR-006).
        status = ensure_transition(TaskStatus.QUEUED, TaskStatus.RUNNING)

        # (2) Context is built from PRIOR turns only; build_context appends the
        # current text itself, so we load history BEFORE persisting this turn to
        # avoid double-counting the current message (FR-002, AI-006).
        prompt, context_manifest = self._context_builder.build(
            current_text=request.text,
            history=history,
        )
        profile_provenance: tuple[ProvenanceReference, ...] = ()
        if self._profile_service is not None:
            profile_items = self._profile_service.context_items()
            profile_lines = [f"confirmed {item.key}: {item.value}" for item in profile_items]
            profile_provenance = tuple(
                ProvenanceReference("profile", item.item_id, item.updated_at)
                for item in profile_items
            )
            if profile_lines:
                prompt = "confirmed owner context:\n" + "\n".join(profile_lines) + "\n" + prompt

        # Claim the request before persisting another user turn or starting an
        # optional provider.  The digest is over the immutable request payload;
        # authorization separately hashes the exact context sent externally.
        task_created = self._start_task_record(task_id, request)
        operation_lease = self._repository.claim_operation(
            task_id=task_id,
            request_id=request.request_id,
            capability_id=(
                route_decision.capability_id
                or ("local_generalist" if is_local_route(route) else "optional")
            ),
            request_digest=payload_hash(request.text),
            at=self._clock.now(),
        )
        existing_task_status = self._repository.task_status(task_id)
        if (
            not task_created
            and operation_lease.fresh
            and existing_task_status in {TaskStatus.COMPLETED.value, TaskStatus.PARTIAL.value}
        ):
            # A task created before the V1.5 operation migration has no ledger
            # row.  Treat its terminal record as already executed rather than
            # replaying the provider call during the first post-migration retry.
            self._completion.fail_operation(operation_lease, possible_duplicate=True)
            operation_lease = self._repository.claim_operation(
                task_id=task_id,
                request_id=request.request_id,
                capability_id=(
                    route_decision.capability_id
                    or ("local_generalist" if is_local_route(route) else "optional")
                ),
                request_digest=payload_hash(request.text),
                at=self._clock.now(),
            )
        if not operation_lease.fresh:
            duplicate_status = ensure_transition(status, TaskStatus.PARTIAL)
            self._emit(
                request=request,
                task_id=task_id,
                route=route,
                route_decision=route_decision,
                event_type="task.duplicate_prevented",
                status=duplicate_status,
                error_class=ErrorClass.PERMISSION_DENIED,
                detail=(f"operation={operation_lease.operation_id} provider_dispatch=not_started"),
            )
            return ConversationOutcome(
                # This is an exact idempotency protocol response, not a new
                # substantive answer. Never re-enter the composer for a replay.
                result=decorate(compose_possible_duplicate(task_id=task_id, route=route)),
                manifest=context_manifest,
            )

        try:
            self._emit(
                request=request,
                task_id=task_id,
                route=route,
                route_decision=route_decision,
                event_type="task.received",
                status=status,
                detail=f"route_reason={route_decision.reason_code.value}",
            )
        except StorageFailureError as exc:
            self._completion.best_effort_fail_operation(operation_lease)
            self._completion.best_effort_finish_task(task_id, TaskStatus.FAILED)
            return ConversationOutcome(
                result=compose_response(
                    decorate(compose_failed(task_id=task_id, reason=exc.summary, route=route))
                ),
                manifest=context_manifest,
            )

        # (3) Persist the user turn (verified input; kept even if generation fails).
        # Approval resumes the already-recorded turn; do not duplicate the user
        # body when the exact consent proposal is approved and resubmitted.
        if request.approval_id is None and request.action_confirmation_id is None and task_created:
            try:
                self._repository.append_message(
                    request.session_id,
                    Message(role="user", content=request.text, created_at=self._clock.now()),
                )
            except StorageFailureError as exc:
                self._completion.best_effort_fail_operation(operation_lease)
                self._completion.best_effort_finish_task(task_id, TaskStatus.FAILED)
                return ConversationOutcome(
                    result=compose_response(
                        decorate(compose_failed(task_id=task_id, reason=exc.summary, route=route))
                    ),
                    manifest=context_manifest,
                )

        if route_decision.reason_code is RouteReasonCode.ACTION_UNSUPPORTED:
            blocked_result = compose_response(
                decorate(
                    compose_blocked(
                        task_id=task_id,
                        reason="the requested consequential action is not supported",
                        route=route,
                    )
                )
            )
            try:
                blocked_status = ensure_transition(status, TaskStatus.BLOCKED)
                self._completion.emit(
                    request=request,
                    task_id=task_id,
                    route=route,
                    route_decision=route_decision,
                    event_type="action.authorization_denied",
                    status=blocked_status,
                    error_class=ErrorClass.PERMISSION_DENIED,
                    detail="reason=ACTION_UNSUPPORTED provider_dispatch=not_started",
                )
                self._completion.fail_operation(operation_lease)
                self._completion.persist_result(blocked_result)
                self._completion.finish_task(task_id, blocked_status)
            except StorageFailureError as exc:
                self._completion.best_effort_fail_operation(operation_lease)
                self._completion.best_effort_finish_task(task_id, TaskStatus.FAILED)
                return ConversationOutcome(
                    result=compose_response(
                        decorate(compose_failed(task_id=task_id, reason=exc.summary, route=route))
                    ),
                    manifest=context_manifest,
                )
            return ConversationOutcome(result=blocked_result, manifest=context_manifest)

        if route_decision.clarification_required:
            clarification = compose_clarification(
                task_id=task_id,
                fields=route_decision.clarification_fields,
                route=route,
            )
            clarification = compose_response(decorate(clarification))
            try:
                self._completion.complete_clarification(
                    request=request,
                    task_id=task_id,
                    route=route,
                    route_decision=route_decision,
                    result=clarification,
                    operation_lease=operation_lease,
                    fields=route_decision.clarification_fields,
                )
            except StorageFailureError as exc:
                self._completion.best_effort_fail_operation(
                    operation_lease, possible_duplicate=False
                )
                self._completion.best_effort_finish_task(task_id, TaskStatus.FAILED)
                return ConversationOutcome(
                    result=compose_response(
                        decorate(compose_failed(task_id=task_id, reason=exc.summary, route=route))
                    ),
                    manifest=context_manifest,
                )
            return ConversationOutcome(result=clarification, manifest=context_manifest)

        if not is_local_route(route):
            if self._capability_workflow is None:
                reason = "optional capability workflow is unavailable"
                self._completion.best_effort_fail_operation(operation_lease)
                self._completion.best_effort_finish_task(task_id, TaskStatus.FAILED)
                return ConversationOutcome(
                    result=compose_response(
                        decorate(compose_failed(task_id=task_id, reason=reason, route=route))
                    ),
                    manifest=context_manifest,
                )
            capability_outcome = self._capability_workflow.execute(
                CapabilityExecutionCommand(
                    request=request,
                    task_id=task_id,
                    status=status,
                    route=route,
                    route_request=route_request,
                    route_decision=route_decision,
                    context_text=capability_context,
                    context_manifest=context_manifest,
                    cancellation=cancellation,
                    request_guardrails=request_guardrails,
                    operation_lease=operation_lease,
                    started=started,
                )
            )
            # The capability workflow composes successful direct results while
            # preserving typed plan-step results for TaskExecutionService.
            # Complete the same common presentation pipeline for direct failures and
            # blocked explanations that return before provider execution.  The
            # protocol statuses remain deterministic-only by policy.
            if (
                self._response_pipeline is not None
                and not capability_outcome.response_composed
                and capability_outcome.result.task_status
                not in {TaskStatus.AWAITING_CONSENT, TaskStatus.AWAITING_CONFIRMATION}
            ):
                composed_result = compose_response(
                    capability_outcome.result,
                    approved_context=capability_context,
                )
                # Early capability failures are normally persisted by the
                # workflow before control returns here.  Replace that raw
                # presentation artifact with the common composed result when
                # storage is still available; a telemetry/persistence error
                # must not trigger a second provider call or hide the safe
                # result already prepared for the caller.
                try:
                    if capability_outcome.result.task_status is not TaskStatus.CANCELLED:
                        self._completion.persist_result(composed_result, route_decision)
                except StorageFailureError:
                    pass
                capability_outcome = replace(
                    capability_outcome,
                    result=composed_result,
                    response_composed=True,
                )
            return capability_outcome.as_conversation_outcome()

        # (4)+(5) Call the model and validate its untrusted output. Any typed
        # EllyError (provider failure OR validation rejection) maps to BLOCKED.
        text = ""
        assistant_message: Message | None = None
        try:
            local_execution = self._local_conversation.execute(
                prompt,
                request_guardrails=request_guardrails,
                cancellation=cancellation,
            )
            generalist_response = local_execution.response
            text = local_execution.text
            if self._response_pipeline is None:
                assistant_message = Message(
                    role="assistant", content=text, created_at=self._clock.now()
                )
                self._repository.append_message(request.session_id, assistant_message)
        except StorageFailureError as exc:
            self._completion.best_effort_fail_operation(operation_lease, possible_duplicate=True)
            self._completion.best_effort_finish_task(task_id, TaskStatus.PARTIAL)
            return ConversationOutcome(
                result=compose_response(
                    decorate(
                        compose_partial(
                            task_id=task_id,
                            reason=exc.summary,
                            route=route,
                            answer=text,
                            partial_work=(
                                "local response was generated but durable completion was incomplete",
                            )
                            if text
                            else (),
                        )
                    )
                ),
                manifest=context_manifest,
                assistant_message=None,
            )
        except CancelledError as exc:
            self._completion.fail_operation(operation_lease)
            cancelled = ensure_transition(status, TaskStatus.CANCELLED)
            self._emit(
                request=request,
                task_id=task_id,
                route=route,
                event_type="task.cancelled",
                route_decision=route_decision,
                status=cancelled,
                error_class=exc.error_class,
                detail=self._failure_detail(exc.summary, started, request_guardrails),
            )
            self._completion.finish_task(task_id, cancelled)
            return ConversationOutcome(
                result=compose_response(
                    decorate(
                        compose_cancelled(
                            task_id=task_id,
                            partial_work=exc.partial_work,
                            route=route,
                        )
                    )
                ),
                manifest=context_manifest,
                assistant_message=None,
            )
        except EllyError as exc:
            self._completion.fail_operation(operation_lease)
            blocked = ensure_transition(status, TaskStatus.BLOCKED)
            self._emit(
                request=request,
                task_id=task_id,
                route=route,
                route_decision=route_decision,
                event_type="generalist.failed",
                status=blocked,
                error_class=exc.error_class,
                detail=self._failure_detail(exc.summary, started, request_guardrails),
            )
            self._completion.finish_task(task_id, blocked)
            return ConversationOutcome(
                result=compose_response(
                    decorate(compose_blocked(task_id=task_id, reason=exc.summary, route=route))
                ),
                manifest=context_manifest,
                assistant_message=None,
            )

        # (6) Success: compose the three-axis result and record completion.
        try:
            result = compose_success(
                task_id=task_id,
                answer=text,
                route=route,
                provenance=tuple(
                    ProvenanceReference("message", str(message_id))
                    for message_id in context_manifest.included_message_ids
                )
                + profile_provenance,
            )
            result = decorate(result)
            result = compose_response(result)
            if self._response_pipeline is not None:
                assistant_message = Message(
                    role="assistant", content=result.answer, created_at=self._clock.now()
                )
                self._repository.append_message(request.session_id, assistant_message)
            ensure_transition(status, result.task_status)
            self._completion.complete_local(
                request=request,
                task_id=task_id,
                route=route,
                route_decision=route_decision,
                result=result,
                started=started,
                request_guardrails=request_guardrails,
                operation_lease=operation_lease,
                response=generalist_response,
                provider_name=type(self._local_conversation.generalist).__name__,
                model_id=self._local_conversation.model_id,
            )
            return ConversationOutcome(
                result=result, manifest=context_manifest, assistant_message=assistant_message
            )
        except StorageFailureError as exc:
            self._completion.best_effort_fail_operation(operation_lease, possible_duplicate=True)
            self._completion.best_effort_finish_task(task_id, TaskStatus.PARTIAL)
            return ConversationOutcome(
                result=decorate(
                    compose_partial(
                        task_id=task_id,
                        reason=exc.summary,
                        route=route,
                        answer=text,
                        partial_work=(
                            "local response was generated but durable completion was incomplete",
                        ),
                    )
                ),
                manifest=context_manifest,
                assistant_message=assistant_message,
            )
