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

from ..domain import validation
from ..domain.context import build_context
from ..domain.enums import ErrorClass, Route, TaskStatus, ValidationStatus
from ..domain.errors import CancelledError, EllyError, MalformedResultError
from ..domain.models import (
    AuditEvent,
    ConversationOutcome,
    GeneralistRequest,
    Message,
    TaskRequest,
)
from ..domain.state_machine import ensure_transition
from ..ports.audit import AuditPort
from ..ports.clock import ClockPort
from ..ports.generalist import GeneralistPort
from ..ports.repository import SessionRepositoryPort
from ..guardrails.controller import GuardrailController
from .response_composer import compose_blocked, compose_cancelled, compose_success


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
    ) -> None:
        self._clock = clock
        self._generalist = generalist
        self._repository = repository
        self._audit = audit
        self._context_window = context_window
        self._model_id = model_id
        self._max_output_tokens = max_output_tokens
        self._guardrails = guardrails

    # ---- provided helpers (use these; do not re-implement) ----------------

    def route(self, request: TaskRequest) -> Route:
        """Deterministic M1 routing: everything is local (AI-005 initial).

        There is no research/coding/cloud path in M1, so this always returns
        LOCAL_GENERALIST. It exists as a seam so richer routing slots in at M4/M5.
        """
        return Route.LOCAL_GENERALIST

    def _emit(
        self,
        *,
        request: TaskRequest,
        task_id: str,
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
                route=Route.LOCAL_GENERALIST,
                task_status=status,
                error_class=error_class,
                detail=detail,
            )
        )

    def _call_generalist(self, prompt: str) -> str:
        """Build the bounded request and call the port; returns proposed text."""
        gen_request = GeneralistRequest(
            prompt=prompt,
            model_id=self._model_id,
            max_output_tokens=self._max_output_tokens,
        )
        response = self._generalist.generate(gen_request)
        return response.text

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
        task_id = f"task-{request.request_id}"
        route = self.route(request)  # AI-005 (initial): always local in M1
        # Lifecycle transitions go through the state machine so the application —
        # not ad-hoc code — owns valid task states (AI-002, FR-006).
        status = ensure_transition(TaskStatus.QUEUED, TaskStatus.RUNNING)
        self._emit(
            request=request,
            task_id=task_id,
            event_type="task.received",
            status=status,
        )
        self._start_task_record(task_id, request)

        # (2) Context is built from PRIOR turns only; build_context appends the
        # current text itself, so we load history BEFORE persisting this turn to
        # avoid double-counting the current message (FR-002, AI-006).
        history = self._repository.recent_messages(request.session_id, self._context_window)
        prompt, manifest = build_context(
            current_text=request.text,
            history=history,
            window=self._context_window,
            reserved_output_tokens=self._max_output_tokens,
        )

        # (3) Persist the user turn (verified input; kept even if generation fails).
        self._repository.append_message(
            request.session_id,
            Message(role="user", content=request.text, created_at=self._clock.now()),
        )

        # (4)+(5) Call the model and validate its untrusted output. Any typed
        # EllyError (provider failure OR validation rejection) maps to BLOCKED.
        try:
            if self._guardrails is None:
                text = self._call_generalist(prompt)
            else:
                cancel = getattr(self._generalist, "cancel", None)
                text = self._guardrails.execute(
                    lambda: self._call_generalist(prompt),
                    cancel=cancel if callable(cancel) else None,
                    output_tokens=self._max_output_tokens,
                )
            if validation.validate_generalist_text(text) is ValidationStatus.REJECTED:
                raise MalformedResultError("model returned empty/invalid output")
            assistant_message = Message(
                role="assistant", content=text, created_at=self._clock.now()
            )
            self._repository.append_message(request.session_id, assistant_message)
        except CancelledError as exc:
            cancelled = ensure_transition(status, TaskStatus.CANCELLED)
            self._emit(
                request=request, task_id=task_id, event_type="task.cancelled",
                status=cancelled, error_class=exc.error_class, detail=exc.summary,
            )
            self._finish_task_record(task_id, cancelled)
            return ConversationOutcome(
                result=compose_cancelled(task_id=task_id, partial_work=exc.partial_work), manifest=manifest,
                assistant_message=None,
            )
        except EllyError as exc:
            blocked = ensure_transition(status, TaskStatus.BLOCKED)
            self._emit(
                request=request,
                task_id=task_id,
                event_type="generalist.failed",
                status=blocked,
                error_class=exc.error_class,
                detail=exc.summary,
            )
            self._finish_task_record(task_id, blocked)
            return ConversationOutcome(
                result=compose_blocked(task_id=task_id, reason=exc.summary),
                manifest=manifest,
                assistant_message=None,
            )

        # (6) Success: compose the three-axis result and record completion.
        result = compose_success(task_id=task_id, answer=text)
        ensure_transition(status, result.task_status)
        self._emit(
            request=request,
            task_id=task_id,
            event_type="task.completed",
            status=result.task_status,
        )
        self._finish_task_record(task_id, result.task_status)
        return ConversationOutcome(
            result=result, manifest=manifest, assistant_message=assistant_message
        )
