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

from ..domain import validation
from ..domain.context import build_context, resolve_conversation_context
from ..domain.enums import CloudMode, EpistemicStatus, ErrorClass, Route, TaskStatus, ValidationStatus
from ..domain.errors import CancelledError, ConsentRequiredError, EllyError, MalformedResultError, PermissionDeniedError
from ..domain.models import (
    AuditEvent,
    ConversationOutcome,
    GeneralistRequest,
    GeneralistResponse,
    Message,
    TaskRequest,
)
from ..domain.state_machine import ensure_transition
from ..ports.audit import AuditPort
from ..ports.clock import ClockPort
from ..ports.generalist import GeneralistPort
from ..ports.repository import SessionRepositoryPort
from ..guardrails.controller import GuardrailController
from ..research.freshness import needs_current_information
from .research import ResearchPipeline
from .response_composer import compose_blocked, compose_cancelled, compose_research, compose_success
from .response_composer import compose_consent_required, compose_specialist
from ..specialists.contracts import SpecialistTask
from ..specialists.registry import SpecialistRegistry
from ..application.specialists import SpecialistWorkflow
from ..privacy import ConsentWorkflow, PrivacyClass, classify_payload


class ConversationOrchestrator:
    """Sequences a single local conversational turn (UC-01)."""

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
        profile_service=None,
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

    # ---- provided helpers (use these; do not re-implement) ----------------

    def route(self, request: TaskRequest, *, contextual_text: str | None = None) -> Route:
        """Deterministically route the resolved conversational request.

        Current-information or explicit research wording routes to web research;
        dependent turns may inherit that intent from one bounded prior user turn.
        Timeless conversation remains on the local generalist.
        """
        lowered = request.text.lower()
        if any(token in lowered for token in ("review this code", "debug this", "code review", "python function", "programming bug")):
            return Route.CODING_SPECIALIST
        if any(token in lowered for token in ("research specialist", "synthesize the sources", "analyze the evidence")):
            return Route.RESEARCH_SPECIALIST
        route_text = contextual_text if contextual_text is not None else request.text
        return Route.WEB_RESEARCH if needs_current_information(route_text) else Route.LOCAL_GENERALIST

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

    def _call_generalist(self, prompt: str) -> GeneralistResponse:
        """Build the bounded request and return normalized model text plus usage."""
        gen_request = GeneralistRequest(
            prompt=prompt,
            model_id=self._model_id,
            max_output_tokens=self._max_output_tokens,
        )
        return self._generalist.generate(gen_request)

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

    def _start_task_record(self, task_id: str, request: TaskRequest) -> None:
        start = getattr(self._repository, "start_task", None)
        if callable(start):
            start(task_id, request.session_id, self._clock.now())

    def _finish_task_record(self, task_id: str, status: TaskStatus) -> None:
        finish = getattr(self._repository, "finish_task", None)
        if callable(finish):
            finish(task_id, status.value, self._clock.now())

    # ---- orchestration ----------------------------------------------------

    def handle(self, request: TaskRequest) -> ConversationOutcome:
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
        route = self.route(
            request, contextual_text=conversation_context.routing_text
        )
        # Lifecycle transitions go through the state machine so the application —
        # not ad-hoc code — owns valid task states (AI-002, FR-006).
        status = ensure_transition(TaskStatus.QUEUED, TaskStatus.RUNNING)
        self._emit(
            request=request,
            task_id=task_id,
            route=route,
            event_type="task.received",
            status=status,
        )
        self._start_task_record(task_id, request)

        # (2) Context is built from PRIOR turns only; build_context appends the
        # current text itself, so we load history BEFORE persisting this turn to
        # avoid double-counting the current message (FR-002, AI-006).
        prompt, context_manifest = build_context(
            current_text=request.text,
            history=history,
            window=self._context_window,
            reserved_output_tokens=self._max_output_tokens,
        )
        if self._profile_service is not None:
            profile_lines = [f"confirmed {item.key}: {item.value}" for item in self._profile_service.context_items()]
            if profile_lines:
                prompt = "confirmed owner context:\n" + "\n".join(profile_lines) + "\n" + prompt

        # (3) Persist the user turn (verified input; kept even if generation fails).
        # Approval resumes the already-recorded turn; do not duplicate the user
        # body when the exact consent proposal is approved and resubmitted.
        if request.approval_id is None:
            self._repository.append_message(
                request.session_id,
                Message(role="user", content=request.text, created_at=self._clock.now()),
            )

        if route in {Route.CODING_SPECIALIST, Route.RESEARCH_SPECIALIST}:
            specialist_id = "coding" if route is Route.CODING_SPECIALIST else "research"
            specialist_manifest = self._specialist_registry.get(specialist_id) if self._specialist_registry else None
            if specialist_manifest is None or self._specialist_workflow is None:
                reason = "requested specialist capability is disabled"
                blocked = ensure_transition(status, TaskStatus.BLOCKED)
                self._emit(request=request, task_id=task_id, route=route, event_type="specialist.blocked", status=blocked,
                           error_class=ErrorClass.PERMISSION_DENIED,
                           detail=self._failure_detail(reason, started, request_guardrails))
                self._finish_task_record(task_id, blocked)
                return ConversationOutcome(result=compose_blocked(task_id=task_id, reason=reason, route=route), manifest=context_manifest)
            specialist_context = conversation_context.remote_text
            specialist_task = SpecialistTask(
                task_id=task_id, specialist_id=specialist_id, goal=request.text,
                context=specialist_context,
                privacy_class=classify_payload(specialist_context).value,
                approval_id=request.approval_id,
            )
            try:
                execution = self._specialist_workflow.execute(
                    task=specialist_task, manifest=specialist_manifest, cloud_mode=request.cloud_mode,
                    now=self._clock.now(), request_guardrails=request_guardrails,
                )
                specialist_result = execution.result
                result = compose_specialist(
                    task_id=task_id, answer=specialist_result.answer, route=route,
                    epistemic=EpistemicStatus(specialist_result.status) if specialist_result.status != "partial" else EpistemicStatus.INFERRED,
                    assumptions=specialist_result.assumptions, uncertainties=specialist_result.uncertainties,
                    sources=specialist_result.sources, partial=specialist_result.truncated or specialist_result.status == "partial",
                )
                self._repository.append_message(
                    request.session_id,
                    Message(role="assistant", content=result.answer, created_at=self._clock.now()),
                )
                self._emit(request=request, task_id=task_id, route=route, event_type="specialist.completed", status=result.task_status)
                provider_usage = getattr(self._specialist_workflow.provider, "last_usage", {})
                provider_cost = getattr(self._specialist_workflow.provider, "last_cost_usd", 0.0)
                self._emit(
                    request=request, task_id=task_id, route=route, event_type="specialist.usage",
                    status=result.task_status,
                    detail=(
                        f"provider={self._specialist_workflow.provider_name} "
                        f"model={specialist_manifest.provider_model} "
                        f"prompt={specialist_manifest.prompt_version} tools=none "
                        f"duration_ms={int((time.monotonic() - started) * 1000)} "
                        f"cost_usd={provider_cost:.4f} {self._guardrail_detail(request_guardrails)} "
                        f"usage={provider_usage}"
                    ),
                )
                self._record_sources(task_id, result.citations)
                self._finish_task_record(task_id, result.task_status)
                return ConversationOutcome(result=result, manifest=context_manifest)
            except ConsentRequiredError as exc:
                awaiting = ensure_transition(status, TaskStatus.AWAITING_CONSENT)
                self._emit(request=request, task_id=task_id, route=route, event_type="consent.requested", status=awaiting,
                           error_class=exc.error_class,
                           detail=self._failure_detail("exact consent required", started, request_guardrails))
                self._finish_task_record(task_id, awaiting)
                return ConversationOutcome(
                    result=compose_consent_required(task_id=task_id, proposal=exc.proposal, route=route),
                    manifest=context_manifest, consent_proposal=exc.proposal,
                )
            except EllyError as exc:
                blocked = ensure_transition(status, TaskStatus.BLOCKED)
                self._emit(request=request, task_id=task_id, route=route, event_type="specialist.failed", status=blocked,
                           error_class=exc.error_class,
                           detail=self._failure_detail(exc.summary, started, request_guardrails))
                self._finish_task_record(task_id, blocked)
                return ConversationOutcome(result=compose_blocked(task_id=task_id, reason=exc.summary, route=route), manifest=context_manifest)

        if route is Route.WEB_RESEARCH:
            if request.cloud_mode is not CloudMode.CLOUD_PERMITTED:
                denied = PermissionDeniedError("web research requires /mode cloud because the query leaves this device")
                blocked = ensure_transition(status, TaskStatus.BLOCKED)
                self._emit(request=request, task_id=task_id, route=route, event_type="research.blocked", status=blocked,
                           error_class=denied.error_class,
                           detail=self._failure_detail(denied.summary, started, request_guardrails))
                self._finish_task_record(task_id, blocked)
                return ConversationOutcome(result=compose_blocked(task_id=task_id, reason=denied.summary, route=route), manifest=context_manifest)
            if self._research is None:
                denied = PermissionDeniedError("web research capability is disabled")
                blocked = ensure_transition(status, TaskStatus.BLOCKED)
                self._emit(request=request, task_id=task_id, route=route, event_type="research.blocked", status=blocked,
                           error_class=denied.error_class,
                           detail=self._failure_detail(denied.summary, started, request_guardrails))
                self._finish_task_record(task_id, blocked)
                return ConversationOutcome(result=compose_blocked(task_id=task_id, reason=denied.summary, route=route), manifest=context_manifest)
            privacy = classify_payload(research_query)
            if privacy is PrivacyClass.RESTRICTED:
                denied = PermissionDeniedError("restricted content may never be sent to hosted web research")
                blocked = ensure_transition(status, TaskStatus.BLOCKED)
                self._emit(request=request, task_id=task_id, route=route, event_type="research.blocked", status=blocked,
                           error_class=denied.error_class,
                           detail=self._failure_detail(denied.summary, started, request_guardrails))
                self._finish_task_record(task_id, blocked)
                return ConversationOutcome(result=compose_blocked(task_id=task_id, reason=denied.summary, route=route), manifest=context_manifest)
            if privacy is PrivacyClass.UNCLASSIFIED:
                denied = PermissionDeniedError(
                    "unclassified content may not be sent to hosted web research; "
                    "describe it as public or use a recognized public-data request"
                )
                blocked = ensure_transition(status, TaskStatus.BLOCKED)
                self._emit(
                    request=request, task_id=task_id, route=route,
                    event_type="research.blocked", status=blocked,
                    error_class=denied.error_class,
                    detail=self._failure_detail(
                        denied.summary, started, request_guardrails
                    ),
                )
                self._finish_task_record(task_id, blocked)
                return ConversationOutcome(
                    result=compose_blocked(
                        task_id=task_id, reason=denied.summary, route=route
                    ),
                    manifest=context_manifest,
                )
            if privacy is PrivacyClass.LOCAL:
                purpose = "perform hosted web research"
                approved = self._consent is not None and self._consent.check(
                    proposal_id=request.approval_id, payload=research_query,
                    provider=self._research_provider_id, model=self._research_model_id,
                    purpose=purpose, categories=(privacy.value,),
                    max_cost=self._consent_max_cost_usd,
                    now=self._clock.now(),
                )
                if not approved:
                    if self._consent is None:
                        denied = PermissionDeniedError("hosted research consent capability is unavailable")
                        blocked = ensure_transition(status, TaskStatus.BLOCKED)
                        self._emit(request=request, task_id=task_id, route=route, event_type="research.blocked", status=blocked,
                                   error_class=denied.error_class,
                                   detail=self._failure_detail(denied.summary, started, request_guardrails))
                        self._finish_task_record(task_id, blocked)
                        return ConversationOutcome(result=compose_blocked(task_id=task_id, reason=denied.summary, route=route), manifest=context_manifest)
                    proposal = self._consent.propose(
                        task_id=task_id, provider=self._research_provider_id,
                        model=self._research_model_id, purpose=purpose,
                        payload=research_query, categories=(privacy.value,),
                        max_cost=self._consent_max_cost_usd,
                        now=self._clock.now(),
                    )
                    awaiting = ensure_transition(status, TaskStatus.AWAITING_CONSENT)
                    self._emit(request=request, task_id=task_id, route=route, event_type="consent.requested", status=awaiting,
                               error_class=ErrorClass.PERMISSION_DENIED,
                               detail=self._failure_detail("exact consent required", started, request_guardrails))
                    self._finish_task_record(task_id, awaiting)
                    return ConversationOutcome(
                        result=compose_consent_required(task_id=task_id, proposal=proposal, route=route),
                        manifest=context_manifest, consent_proposal=proposal,
                    )
            try:
                research = self._research.execute(
                    research_query, request_guardrails=request_guardrails
                )
                result = compose_research(
                    task_id=task_id, answer=research.answer,
                    citations=tuple(e.canonical_url or e.url for e in research.evidence),
                    claims=research.claims, epistemic=research.epistemic,
                )
                self._repository.append_message(
                    request.session_id,
                    Message(role="assistant", content=result.answer, created_at=self._clock.now()),
                )
                self._record_sources(task_id, result.citations)
                self._emit(
                    request=request, task_id=task_id, route=route, event_type="research.completed",
                    status=result.task_status,
                    detail=(
                        f"provider={research.provider} model={research.model} "
                        f"tools=web_search duration_ms={int((time.monotonic() - started) * 1000)} "
                        f"sources={len(result.citations)} rejected={len(research.rejected)} "
                        f"{self._guardrail_detail(request_guardrails)}"
                    ),
                )
                self._finish_task_record(task_id, result.task_status)
                return ConversationOutcome(result=result, manifest=context_manifest)
            except CancelledError as exc:
                cancelled = ensure_transition(status, TaskStatus.CANCELLED)
                self._emit(request=request, task_id=task_id, route=route, event_type="research.cancelled", status=cancelled,
                           error_class=exc.error_class,
                           detail=self._failure_detail(exc.summary, started, request_guardrails))
                self._finish_task_record(task_id, cancelled)
                return ConversationOutcome(result=compose_cancelled(task_id=task_id, partial_work=exc.partial_work, route=route), manifest=context_manifest)
            except EllyError as exc:
                blocked = ensure_transition(status, TaskStatus.BLOCKED)
                self._emit(request=request, task_id=task_id, route=route, event_type="research.failed", status=blocked,
                           error_class=exc.error_class,
                           detail=self._failure_detail(exc.summary, started, request_guardrails))
                self._finish_task_record(task_id, blocked)
                return ConversationOutcome(result=compose_blocked(task_id=task_id, reason=exc.summary, route=route), manifest=context_manifest)

        # (4)+(5) Call the model and validate its untrusted output. Any typed
        # EllyError (provider failure OR validation rejection) maps to BLOCKED.
        try:
            if self._guardrails is None:
                generalist_response = self._call_generalist(prompt)
            else:
                cancel = getattr(self._generalist, "cancel", None)
                generalist_response = request_guardrails.execute(
                    lambda: self._call_generalist(prompt),
                    cancel=cancel if callable(cancel) else None,
                    output_tokens=self._max_output_tokens,
                    cost_usd=0.0,
                )
            text = generalist_response.text
            if validation.validate_generalist_text(text) is ValidationStatus.REJECTED:
                raise MalformedResultError("model returned empty/invalid output")
            assistant_message = Message(
                role="assistant", content=text, created_at=self._clock.now()
            )
            self._repository.append_message(request.session_id, assistant_message)
        except CancelledError as exc:
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
        result = compose_success(task_id=task_id, answer=text, route=route)
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
        self._finish_task_record(task_id, result.task_status)
        return ConversationOutcome(
            result=result, manifest=context_manifest, assistant_message=assistant_message
        )

    def _record_sources(self, task_id: str, sources) -> None:
        add_source = getattr(self._repository, "add_task_source", None)
        if callable(add_source):
            for source in sources:
                if source:
                    add_source(task_id, str(source), self._clock.now())
