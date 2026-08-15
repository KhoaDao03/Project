"""ConversationOrchestrator — UC-01 local conversation (M1).

`handle()` IS the orchestration control flow — the core of Elly's architecture
(AI-002: the application, not the model, owns sequencing, validation, and status).
It deterministically sequences one local turn: build minimum context, persist the
user turn, call the generalist via its port, VALIDATE the untrusted output,
compose the three-axis TaskResult, persist the assistant turn, and emit correlated
audit events — mapping any typed failure to a safe blocked result WITHOUT ever
fabricating success.

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
from threading import Lock

from ..application.specialists import SpecialistWorkflow
from ..domain.context import resolve_conversation_context
from ..domain.enums import ErrorClass, OutcomeCode, Route, TaskStatus
from ..domain.errors import CancelledError, ConfigInvalidError, EllyError, StorageFailureError
from ..domain.models import (
    AuditEvent,
    ContextManifest,
    ConversationOutcome,
    Message,
    OperationLease,
    ProvenanceReference,
    RouteDecision,
    RouteRequest,
    TaskRequest,
)
from ..domain.state_machine import ensure_transition
from ..guardrails.controller import GuardrailController
from ..memory import ProfileService
from ..ports.audit import AuditPort
from ..ports.clock import ClockPort
from ..ports.generalist import GeneralistPort
from ..ports.repository import SessionRepositoryPort
from ..privacy import ConsentWorkflow, PrivacyPolicy, payload_hash
from ..specialists.registry import SpecialistRegistry
from .authorization import CloudAuthorizationPolicy
from .capabilities import CapabilityHandler, CapabilityRegistry, CapabilityRequest
from .capability_handlers import ResearchCapabilityHandler, SpecialistCapabilityHandler
from .context_builder import ContextBuilder
from .execution import CancellationToken
from .local_conversation import LocalConversationUseCase
from .research import ResearchPipeline
from .response_composer import (
    compose_blocked,
    compose_cancelled,
    compose_consent_required,
    compose_failed,
    compose_partial,
    compose_possible_duplicate,
    compose_success,
)
from .routing import RoutingPolicy


class ConversationOrchestrator:
    """Sequences a single local conversational turn (UC-01).
    
    Responsibility groups:
    Core infrastructure
        clock
        repository
        audit
    AI execution
        generalist
        research
        specialist_workflow
        local_conversation
    Decision systems
        routing_policy
        privacy_policy
        cloud_authorization_policy
    Control/Safety
        guardrails
        consent
        CancellationToken
    Context/memory
        context_builder
        profile_service
    Extensibility:
        capability_registry
        specialist_registry
    """

    def __init__(
        self,
        *,
        clock: ClockPort,
        generalist: GeneralistPort,
        repository: SessionRepositoryPort,
        audit: AuditPort,
        context_window: int,
        model_id: str,
        max_output_tokens: int,
        guardrails: GuardrailController | None = None,
        research: ResearchPipeline | None = None,
        research_model_id: str = "",
        research_provider_id: str = "openai_web_search",
        consent_max_cost_usd: float = 0.25,
        specialist_registry: SpecialistRegistry | None = None,
        specialist_workflow: SpecialistWorkflow | None = None,
        consent: ConsentWorkflow | None = None,
        profile_service: ProfileService | None = None,
        capability_registry: CapabilityRegistry | None = None,
        routing_policy: RoutingPolicy | None = None,
        context_builder: ContextBuilder | None = None,
        privacy_policy: PrivacyPolicy | None = None,
        cloud_authorization_policy: CloudAuthorizationPolicy | None = None,
        local_conversation: LocalConversationUseCase | None = None,
    ) -> None:
        self._clock = clock
        self._generalist = generalist
        self._repository = repository
        self._audit = audit
        self._context_window = context_window
        self._model_id = model_id
        self._max_output_tokens = max_output_tokens
        self._guardrails = guardrails
        self._research = research
        self._research_model_id = research_model_id
        self._research_provider_id = research_provider_id
        self._consent_max_cost_usd = consent_max_cost_usd
        self._specialist_registry = specialist_registry
        self._specialist_workflow = specialist_workflow
        self._consent = consent
        self._profile_service = profile_service
        self._active_lock = Lock()
        self._active_cancellation: CancellationToken | None = None
        if capability_registry is None:
            handlers: list[CapabilityHandler] = []
            if research is not None:
                handlers.append(
                    ResearchCapabilityHandler(
                        research,
                        provider_id=research_provider_id,
                        model_id=research_model_id or "configured-research-model",
                        max_cost_usd=consent_max_cost_usd,
                    )
                )
            if specialist_workflow is not None:
                registered_specialists: set[str] = set()
                for manifest in (
                    specialist_registry.enabled() if specialist_registry is not None else ()
                ):
                    specialist_route = (
                        Route.CODING_SPECIALIST
                        if manifest.role == "coding"
                        else Route.RESEARCH_SPECIALIST
                    )
                    handlers.append(
                        SpecialistCapabilityHandler(
                            manifest.id,
                            specialist_route,
                            manifest,
                            specialist_workflow,
                        )
                    )
                    registered_specialists.add(manifest.id)
                for specialist_id, specialist_route in (
                    ("coding", Route.CODING_SPECIALIST),
                    ("research", Route.RESEARCH_SPECIALIST),
                ):
                    if specialist_id not in registered_specialists:
                        handlers.append(
                            SpecialistCapabilityHandler(
                                specialist_id,
                                specialist_route,
                                specialist_registry.get(specialist_id) if specialist_registry else None,
                                specialist_workflow,
                            )
                        )
            capability_registry = CapabilityRegistry(tuple(handlers))
        self._capability_registry = capability_registry
        self._capability_registry.validate()
        self._routing_policy = routing_policy or RoutingPolicy(capabilities=capability_registry)
        self._context_builder = context_builder or ContextBuilder(
            context_window=context_window,
            reserved_output_tokens=max_output_tokens,
        )
        self._privacy_policy = privacy_policy or PrivacyPolicy()
        self._cloud_authorization_policy = cloud_authorization_policy or CloudAuthorizationPolicy()
        self._local_conversation = local_conversation or LocalConversationUseCase(
            generalist=generalist,
            model_id=model_id,
            max_output_tokens=max_output_tokens,
            guardrails=guardrails,
        )

    # ---- provided helpers (use these; do not re-implement) ----------------

    def route(self, request: TaskRequest, *, contextual_text: str | None = None) -> Route:
        """Deterministically route the resolved conversational request.

        Current-information or explicit research wording routes to web research;
        dependent turns may inherit that intent from one bounded prior user turn.
        Timeless conversation remains on the local generalist.
        """
        return self._routing_policy.decide(
            RouteRequest(
                request_id=request.request_id,
                text=request.text,
                contextual_text=contextual_text,    # Support follow up questions
                cloud_mode=request.cloud_mode,
            ),
            proposal=request.route_proposal,
        ).route

    def _emit(
        self,
        *,
        request: TaskRequest,
        task_id: str,
        route: Route,
        event_type: str,
        status: TaskStatus | None = None,
        error_class: ErrorClass | None = None,
        detail: str = "",
    ) -> None:
        """Append one redacted, correlated audit event (DATA-004/SEC-007)."""
        self._audit.append(
            AuditEvent(
                task_id=task_id,
                session_id=request.session_id,
                event_type=event_type,
                at=self._clock.now(),
                route=route,
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
        cls, summary: str, started: float,
        request_guardrails: GuardrailController | None,
    ) -> str:
        """Add bounded execution metadata to a display-safe failure summary."""
        return (
            f"{summary} duration_ms={int((time.monotonic() - started) * 1000)} "
            f"{cls._guardrail_detail(request_guardrails)}"
        )

    def _start_task_record(self, task_id: str, request: TaskRequest) -> bool:
        return self._repository.start_task(task_id, request.session_id, self._clock.now())

    def _finish_task_record(self, task_id: str, status: TaskStatus) -> None:
        self._repository.finish_task(task_id, status.value, self._clock.now())

    @staticmethod
    def _capability_id_for_route(
        route: Route, route_decision: RouteDecision
    ) -> str:
        return route_decision.capability_id or {
            Route.WEB_RESEARCH: "web_research",
            Route.CODING_SPECIALIST: "coding",
            Route.RESEARCH_SPECIALIST: "research",
            Route.LOCAL_GENERALIST: "local_generalist",
        }.get(route, "")

    def _fail_operation(
        self, operation_lease: OperationLease | None,
        *, possible_duplicate: bool = False,
    ) -> None:
        if operation_lease is not None:
            self._repository.fail_operation(
                operation_lease.operation_id,
                at=self._clock.now(),
                possible_duplicate=possible_duplicate,
            )

    def _complete_operation(self, operation_lease: OperationLease | None) -> None:
        if operation_lease is not None:
            self._repository.complete_operation(
                operation_lease.operation_id, at=self._clock.now()
            )

    def _best_effort_fail_operation(
        self, operation_lease: OperationLease | None,
        *, possible_duplicate: bool = False,
    ) -> None:
        try:
            self._fail_operation(
                operation_lease, possible_duplicate=possible_duplicate
            )
        except StorageFailureError:
            # The original persistence failure is already the actionable result;
            # do not hide it behind a second failure while recording the ledger.
            return

    def _best_effort_finish_task(self, task_id: str, status: TaskStatus) -> None:
        try:
            self._finish_task_record(task_id, status)
        except StorageFailureError:
            return

    def _record_provenance(
        self, task_id: str, references: tuple[ProvenanceReference, ...]
    ) -> None:
        for reference in references:
            self._repository.add_task_provenance(task_id, reference)

    def _execute_registered_capability(
        self,
        *,
        request: TaskRequest,
        task_id: str,
        status: TaskStatus,
        route: Route,
        route_request: RouteRequest,
        route_decision: RouteDecision,
        context_text: str,
        context_manifest: ContextManifest,
        request_guardrails: GuardrailController | None,
        started: float,
        operation_lease: OperationLease | None,
        cancellation: CancellationToken,
    ) -> ConversationOutcome | None:
        """Authorize and execute one optional capability through its typed port."""
        # Defer tasks needs local generalists focus on tasks need specialist
        if route is Route.LOCAL_GENERALIST:
            return None

        # Find handler/specialist for the task
        capability_id = self._capability_id_for_route(route, route_decision)
        handler = self._capability_registry.get(capability_id)
        if handler is None:
            reason = "requested optional capability is not registered"
            blocked = ensure_transition(status, TaskStatus.BLOCKED)
            self._emit(
                request=request, task_id=task_id, route=route,
                event_type="capability.blocked", status=blocked,
                error_class=ErrorClass.PERMISSION_DENIED,
                detail=self._failure_detail(reason, started, request_guardrails),
            )
            self._fail_operation(operation_lease)
            self._finish_task_record(task_id, blocked)
            return ConversationOutcome(
                result=compose_blocked(
                    task_id=task_id, reason=reason, route=route,
                    outcome_code=OutcomeCode.UNAVAILABLE,
                ),
                manifest=context_manifest,
            )

        # Check specialist health/availablity
        capability_status = handler.status()
        if not route_decision.available or not capability_status.available:
            reason = capability_status.reason_code or route_decision.diagnostic or "capability unavailable"
            blocked = ensure_transition(status, TaskStatus.BLOCKED)
            self._emit(
                request=request, task_id=task_id, route=route,
                event_type="capability.unavailable", status=blocked,
                error_class=ErrorClass.PERMISSION_DENIED,
                detail=self._failure_detail(reason, started, request_guardrails),
            )
            self._fail_operation(operation_lease)
            self._finish_task_record(task_id, blocked)
            return ConversationOutcome(
                result=compose_blocked(
                    task_id=task_id, reason=reason, route=route,
                    outcome_code=OutcomeCode.UNAVAILABLE,
                ),
                manifest=context_manifest,
            )

        # Check if specialist/capaility can accept the request
        capability_request = CapabilityRequest(
            task=request,
            route_request=route_request,
            context_text=context_text,
            context_manifest=context_manifest,
            task_id=task_id,
            execution_at=self._clock.now(),
            request_guardrails=request_guardrails,
            cancellation=cancellation,
        )
        match = handler.can_handle(capability_request)
        if not match.accepted:
            reason = match.reason_code or "capability rejected request"
            blocked = ensure_transition(status, TaskStatus.BLOCKED)
            self._emit(
                request=request, task_id=task_id, route=route,
                event_type="capability.input_rejected", status=blocked,
                error_class=ErrorClass.INPUT_INVALID,
                detail=self._failure_detail(reason, started, request_guardrails),
            )
            self._fail_operation(operation_lease)
            self._finish_task_record(task_id, blocked)
            return ConversationOutcome(
                result=compose_blocked(task_id=task_id, reason=reason, route=route),
                manifest=context_manifest,
            )

        # Check the registered capability match the route. Consistent check
        """
        handler.descriptor describes:
        capability ID
        routes
        destination
        model
        purpose
        cost
        external boundary?
        """
        descriptor = handler.descriptor
        if route not in descriptor.routes:
            self._fail_operation(operation_lease)
            failed = ensure_transition(status, TaskStatus.FAILED)
            self._finish_task_record(task_id, failed)
            return ConversationOutcome(
                result=compose_failed(
                    task_id=task_id,
                    reason="registered capability does not declare the selected route",
                    route=route,
                ),
                manifest=context_manifest,
            )
        execution_started = False
        generated_result = None

        # Privacy classifcation + cloud authorization
        try:
            classification = self._privacy_policy.classify(context_text)
            authorization = self._cloud_authorization_policy.authorize(
                task_id=task_id,
                payload=context_text,
                classification=classification,
                cloud_mode=request.cloud_mode,
                destination=descriptor.destination,
                model=descriptor.model,
                capability_id=descriptor.capability_id,
                purpose=descriptor.purpose or f"execute {descriptor.capability_id}",
                consent=self._consent,
                approval_id=request.approval_id,
                max_cost=descriptor.max_cost_usd,
                now=self._clock.now(),
                capability_available=capability_status.available,
                requires_external_boundary=descriptor.requires_external_boundary,
            )
            if not authorization.allowed:
                proposal = authorization.consent_proposal
                if proposal is not None:
                    awaiting = ensure_transition(status, TaskStatus.AWAITING_CONSENT)
                    self._emit(
                        request=request, task_id=task_id, route=route,
                        event_type="consent.requested", status=awaiting,
                        error_class=ErrorClass.PERMISSION_DENIED,
                        detail=self._failure_detail("exact consent required", started, request_guardrails),
                    )
                    self._fail_operation(operation_lease)
                    self._finish_task_record(task_id, awaiting)
                    return ConversationOutcome(
                        result=compose_consent_required(task_id=task_id, proposal=proposal, route=route),
                        manifest=context_manifest,
                        consent_proposal=proposal,
                    )
                blocked = ensure_transition(status, TaskStatus.BLOCKED)
                self._emit(
                    request=request, task_id=task_id, route=route,
                    event_type="capability.authorization_denied", status=blocked,
                    error_class=ErrorClass.PERMISSION_DENIED,
                    detail=self._failure_detail(authorization.reason_code, started, request_guardrails),
                )
                self._fail_operation(operation_lease)
                self._finish_task_record(task_id, blocked)
                return ConversationOutcome(
                    result=compose_blocked(
                        task_id=task_id, reason=authorization.reason_code, route=route
                    ),
                    manifest=context_manifest,
                )

            # Authorization audit
            self._emit(
                request=request,
                task_id=task_id,
                route=route,
                event_type="authorization.approved",
                status=status,
                detail=(
                    f"capability={descriptor.capability_id} "
                    f"destination={descriptor.destination} "
                    f"classification={classification.classification.value} "
                    f"payload_digest={authorization.payload_digest[:16]} "
                    f"reason={authorization.reason_code}"
                ),
            )

            # Capability execution
            execution_started = True
            execution = handler.execute(capability_request)
            result = execution.result
            if result.task_id != task_id:
                raise ConfigInvalidError("capability returned a mismatched task id")
            generated_result = result

            # Saving generated capability output
            if result.answer and result.task_status not in {
                TaskStatus.AWAITING_CONSENT, TaskStatus.CANCELLED
            }:
                self._repository.append_message(
                    request.session_id,
                    Message(role="assistant", content=result.answer, created_at=self._clock.now()),
                )
            self._record_sources(task_id, result.citations)
            self._record_provenance(task_id, result.provenance)
            self._emit(
                request=request, task_id=task_id, route=route,
                event_type="capability.completed", status=result.task_status,
                detail=(
                    f"capability={descriptor.capability_id} "
                    f"route_reason={route_decision.reason_code.value} "
                    f"duration_ms={int((time.monotonic() - started) * 1000)} "
                    f"{self._guardrail_detail(request_guardrails)}"
                ),
            )
            self._finish_task_record(task_id, result.task_status)
            self._complete_operation(operation_lease)
            return ConversationOutcome(result=result, manifest=context_manifest)
        except StorageFailureError as exc:
            self._best_effort_fail_operation(
                operation_lease, possible_duplicate=execution_started
            )
            failed_status = (
                TaskStatus.PARTIAL if generated_result is not None else TaskStatus.FAILED
            )
            self._best_effort_finish_task(task_id, failed_status)
            return ConversationOutcome(
                result=(
                    compose_partial(
                        task_id=task_id,
                        reason=exc.summary,
                        route=route,
                        answer=generated_result.answer,
                        partial_work=(
                            "capability output was generated but durable completion was incomplete",
                        ),
                    )
                    if generated_result is not None
                    else compose_failed(task_id=task_id, reason=exc.summary, route=route)
                ),
                manifest=context_manifest,
            )
        except CancelledError as exc:
            self._fail_operation(operation_lease, possible_duplicate=execution_started)
            cancelled = ensure_transition(status, TaskStatus.CANCELLED)
            self._emit(
                request=request, task_id=task_id, route=route,
                event_type="capability.cancelled", status=cancelled,
                error_class=exc.error_class,
                detail=self._failure_detail(exc.summary, started, request_guardrails),
            )
            self._finish_task_record(task_id, cancelled)
            return ConversationOutcome(
                result=compose_cancelled(task_id=task_id, partial_work=exc.partial_work, route=route),
                manifest=context_manifest,
            )
        except EllyError as exc:
            self._fail_operation(operation_lease, possible_duplicate=execution_started)
            failed = ensure_transition(status, TaskStatus.FAILED)
            self._emit(
                request=request, task_id=task_id, route=route,
                event_type="capability.failed", status=failed,
                error_class=exc.error_class,
                detail=self._failure_detail(exc.summary, started, request_guardrails),
            )
            self._finish_task_record(task_id, failed)
            return ConversationOutcome(
                result=compose_failed(task_id=task_id, reason=exc.summary, route=route),
                manifest=context_manifest,
            )

    # ---- orchestration ----------------------------------------------------

    # Cancellation
    def cancel_active(self) -> bool:
        """Request cancellation of the currently executing turn, if any."""
        with self._active_lock:
            token = self._active_cancellation
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
    def handle(self, request: TaskRequest) -> ConversationOutcome:
        cancellation = CancellationToken()
        with self._active_lock:
            self._active_cancellation = cancellation
        try:
            return self._handle(request, cancellation=cancellation)
        finally:
            with self._active_lock:
                if self._active_cancellation is cancellation:
                    self._active_cancellation = None

    def _handle(
        self, request: TaskRequest, *, cancellation: CancellationToken
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
        request_guardrails = self._guardrails.for_request() if self._guardrails is not None else None
        # Read prior context before routing. A dependent turn such as "How about
        # silver?" inherits the current-information intent of "price of gold",
        # while a follow-up to a timeless local question stays local.
        history = self._repository.recent_messages(
            request.session_id, self._context_window
        )
        conversation_context = resolve_conversation_context(
            current_text=request.text, history=history
        )
        research_query = conversation_context.remote_text
        route_request = RouteRequest(
            request_id=request.request_id,
            text=request.text,
            contextual_text=conversation_context.routing_text,
            cloud_mode=request.cloud_mode,
        )
        route_decision = self._routing_policy.decide(
            route_request, proposal=request.route_proposal
        )
        route = route_decision.route
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
            profile_lines = [
                f"confirmed {item.key}: {item.value}" for item in profile_items
            ]
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
            capability_id=self._capability_id_for_route(route, route_decision),
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
            self._fail_operation(operation_lease, possible_duplicate=True)
            operation_lease = self._repository.claim_operation(
                task_id=task_id,
                request_id=request.request_id,
                capability_id=self._capability_id_for_route(route, route_decision),
                request_digest=payload_hash(request.text),
                at=self._clock.now(),
            )
        if not operation_lease.fresh:
            duplicate_status = ensure_transition(status, TaskStatus.PARTIAL)
            self._emit(
                request=request,
                task_id=task_id,
                route=route,
                event_type="task.duplicate_prevented",
                status=duplicate_status,
                error_class=ErrorClass.PERMISSION_DENIED,
                detail=(
                    f"operation={operation_lease.operation_id} "
                    "provider_dispatch=not_started"
                ),
            )
            return ConversationOutcome(
                result=compose_possible_duplicate(task_id=task_id, route=route),
                manifest=context_manifest,
            )

        try:
            self._emit(
                request=request,
                task_id=task_id,
                route=route,
                event_type="task.received",
                status=status,
                detail=f"route_reason={route_decision.reason_code.value}",
            )
        except StorageFailureError as exc:
            self._best_effort_fail_operation(operation_lease)
            self._best_effort_finish_task(task_id, TaskStatus.FAILED)
            return ConversationOutcome(
                result=compose_failed(task_id=task_id, reason=exc.summary, route=route),
                manifest=context_manifest,
            )

        # (3) Persist the user turn (verified input; kept even if generation fails).
        # Approval resumes the already-recorded turn; do not duplicate the user
        # body when the exact consent proposal is approved and resubmitted.
        if request.approval_id is None and task_created:
            try:
                self._repository.append_message(
                    request.session_id,
                    Message(role="user", content=request.text, created_at=self._clock.now()),
                )
            except StorageFailureError as exc:
                self._best_effort_fail_operation(operation_lease)
                self._best_effort_finish_task(task_id, TaskStatus.FAILED)
                return ConversationOutcome(
                    result=compose_failed(task_id=task_id, reason=exc.summary, route=route),
                    manifest=context_manifest,
                )

        capability_outcome = self._execute_registered_capability(
            request=request,
            task_id=task_id,
            status=status,
            route=route,
            route_request=route_request,
            route_decision=route_decision,
            context_text=research_query,
            context_manifest=context_manifest,
            request_guardrails=request_guardrails,
            started=started,
            operation_lease=operation_lease,
            cancellation=cancellation,
        )
        if capability_outcome is not None:
            return capability_outcome

        # (4)+(5) Call the model and validate its untrusted output. Any typed
        # EllyError (provider failure OR validation rejection) maps to BLOCKED.
        text = ""
        try:
            # Preserve the V1 test/application seam where a composed provider can
            # be replaced before a turn while keeping the use case typed.
            if self._local_conversation.generalist is not self._generalist:
                self._local_conversation = LocalConversationUseCase(
                    generalist=self._generalist,
                    model_id=self._model_id,
                    max_output_tokens=self._max_output_tokens,
                    guardrails=self._guardrails,
                )
            local_execution = self._local_conversation.execute(
                prompt,
                request_guardrails=request_guardrails,
                cancellation=cancellation,
            )
            generalist_response = local_execution.response
            text = local_execution.text
            assistant_message = Message(
                role="assistant", content=text, created_at=self._clock.now()
            )
            self._repository.append_message(request.session_id, assistant_message)
        except StorageFailureError as exc:
            self._best_effort_fail_operation(operation_lease, possible_duplicate=True)
            self._best_effort_finish_task(task_id, TaskStatus.PARTIAL)
            return ConversationOutcome(
                result=compose_partial(
                    task_id=task_id,
                    reason=exc.summary,
                    answer=text,
                    partial_work=(
                        "local response was generated but durable completion was incomplete",
                    ) if text else (),
                ),
                manifest=context_manifest,
                assistant_message=None,
            )
        except CancelledError as exc:
            self._fail_operation(operation_lease)
            cancelled = ensure_transition(status, TaskStatus.CANCELLED)
            self._emit(
                request=request, task_id=task_id, route=route, event_type="task.cancelled",
                status=cancelled, error_class=exc.error_class,
                detail=self._failure_detail(exc.summary, started, request_guardrails),
            )
            self._finish_task_record(task_id, cancelled)
            return ConversationOutcome(
                result=compose_cancelled(task_id=task_id, partial_work=exc.partial_work), manifest=context_manifest,
                assistant_message=None,
            )
        except EllyError as exc:
            self._fail_operation(operation_lease)
            blocked = ensure_transition(status, TaskStatus.BLOCKED)
            self._emit(
                request=request,
                task_id=task_id,
                route=route,
                event_type="generalist.failed",
                status=blocked,
                error_class=exc.error_class,
                detail=self._failure_detail(exc.summary, started, request_guardrails),
            )
            self._finish_task_record(task_id, blocked)
            return ConversationOutcome(
                result=compose_blocked(task_id=task_id, reason=exc.summary),
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
                ) + profile_provenance,
            )
            ensure_transition(status, result.task_status)
            self._emit(
                request=request,
                task_id=task_id,
                route=route,
                event_type="task.completed",
                status=result.task_status,
                detail=(
                    f"provider={type(self._generalist).__name__} model={self._model_id} "
                    f"prompt=local-generalist-v1 tools=none "
                    f"duration_ms={int((time.monotonic() - started) * 1000)} "
                    f"output_tokens={generalist_response.usage.output_tokens} "
                    f"latency_ms={generalist_response.usage.latency_ms} "
                    f"{self._guardrail_detail(request_guardrails)}"
                ),
            )
            self._record_provenance(task_id, result.provenance)
            self._finish_task_record(task_id, result.task_status)
            self._complete_operation(operation_lease)
            return ConversationOutcome(
                result=result, manifest=context_manifest, assistant_message=assistant_message
            )
        except StorageFailureError as exc:
            self._best_effort_fail_operation(operation_lease, possible_duplicate=True)
            self._best_effort_finish_task(task_id, TaskStatus.PARTIAL)
            return ConversationOutcome(
                result=compose_partial(
                    task_id=task_id,
                    reason=exc.summary,
                    route=route,
                    answer=text,
                    partial_work=(
                        "local response was generated but durable completion was incomplete",
                    ),
                ),
                manifest=context_manifest,
                assistant_message=assistant_message,
            )

    def _record_sources(self, task_id: str, sources: tuple[str, ...]) -> None:
        for source in sources:
            if source:
                self._repository.add_task_source(task_id, str(source), self._clock.now())
