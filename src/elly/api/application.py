"""Interface-neutral V2 application façade.

This façade is intentionally an adapter over the existing V1.5 application
scope. It translates public DTOs to internal requests, loads authoritative
session state, normalizes results, and prevents repositories/providers from
crossing the interface boundary.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import Future
from dataclasses import dataclass, replace
from typing import cast

from ..application.action_authorization import safe_action_target_reference
from ..application.plan_results import aggregate_plan_results
from ..application.response_composer import compose_cancelled
from ..application.route_compatibility import inherit_route_metadata
from ..composition import Application
from ..domain.enums import (
    CloudMode,
    EpistemicStatus,
    ErrorClass,
    IntentAmbiguity,
    IntentEntitySource,
    OutcomeCode,
    Route,
    TaskStatus,
    ValidationStatus,
)
from ..domain.errors import (
    CancelledError,
    ConflictError,
    EllyError,
    InputInvalidError,
    LimitExceededError,
    PermissionDeniedError,
    StorageFailureError,
)
from ..domain.models import (
    ActionConfirmationProposal,
    AuditEvent,
    CapabilityIntent,
    ContextManifest,
    ConversationOutcome,
    IntentEntity,
    RouteProposal,
    SessionRecord,
    TaskRequest,
    TaskResult,
)
from ..planning.contracts import ExecutionPlan, PlanStatus, StepState
from ..ports.plan_repository import PlanRepositoryPort
from ..presentation.validators import normalize_and_validate
from ..privacy import ConsentProposal
from ..trace_safety import redact_trace_detail
from .contracts import (
    ActionConfirmationView,
    ActionDecisionRequest,
    ApiFailure,
    ApiFailureCode,
    ApiResult,
    ApplicationStatusView,
    BackupRequest,
    BackupView,
    BudgetStatusView,
    CapabilityIntentInput,
    CapabilityStatusView,
    ChangeModeRequest,
    ConsentDecisionRequest,
    ConsentQuery,
    ConsentView,
    CreateSessionRequest,
    DisagreementView,
    HealthView,
    HistoryQuery,
    HistoryView,
    LimitsStatusView,
    LocalModelRoleView,
    PlanQuery,
    PlanResultView,
    PlanStepView,
    PlanSynthesisView,
    PlanTraceEventView,
    PlanTraceQuery,
    PlanTraceView,
    PlanUsageView,
    PlanView,
    PricingStatusView,
    ProfileCommand,
    ProfileCommandKind,
    ProfileQuery,
    ProfileView,
    RestoreRequest,
    RouteProposalInput,
    RuntimeStatusView,
    SessionView,
    SourcesQuery,
    SourcesView,
    SubmitRequest,
    TaskAccepted,
    TaskView,
    TraceEventView,
    TraceQuery,
    TraceView,
)


@dataclass(frozen=True, slots=True)
class _PendingSubmission:
    request: TaskRequest
    proposal: ConsentProposal


@dataclass(frozen=True, slots=True)
class _PendingAction:
    request: TaskRequest
    proposal: ActionConfirmationProposal


class EllyApplication:
    """Stable public application boundary for all interface adapters."""

    def __init__(self, scope: Application) -> None:
        self._scope = scope
        self._lock = threading.RLock()
        self._futures: dict[str, Future[ConversationOutcome]] = {}
        self._requests: dict[str, TaskRequest] = {}
        self._accepted_tasks: dict[str, str] = {}
        self._outcomes: dict[str, ConversationOutcome] = {}
        self._future_errors: dict[str, BaseException] = {}
        self._pending_submissions: dict[str, _PendingSubmission] = {}
        self._pending_actions: dict[str, _PendingAction] = {}
        self._processed_futures: set[Future[ConversationOutcome]] = set()

    def close(self) -> None:
        """Close the composed application scope."""
        self._scope.close()

    # ---- public session operations -------------------------------------

    def create_session(self, request: CreateSessionRequest | None = None) -> ApiResult[SessionView]:
        request = request or CreateSessionRequest()
        correlation_id = "session-create"
        try:
            if not isinstance(request, CreateSessionRequest):
                raise InputInvalidError("create session request is invalid")
            record = self._scope.new_session(
                persistence_mode=request.persistence_mode,
                cloud_mode=request.cloud_mode,
            )
            return ApiResult.success(_session_view(record))
        except BaseException as exc:
            return ApiResult.failed(_failure(exc, correlation_id))

    def get_session(self, session_id: str) -> ApiResult[SessionView]:
        try:
            _require_id(session_id, "session_id")
            record = self._scope.repository.get_session(session_id)
            if record is None:
                return ApiResult.failed(_failure_not_found("session", session_id))
            return ApiResult.success(_session_view(record))
        except BaseException as exc:
            return ApiResult.failed(_failure(exc, session_id or "session-read"))

    def change_session_mode(self, request: ChangeModeRequest) -> ApiResult[SessionView]:
        correlation_id = (
            request.session_id if isinstance(request, ChangeModeRequest) else "session-mode"
        )
        try:
            if not isinstance(request, ChangeModeRequest):
                raise InputInvalidError("change mode request is invalid")
            _require_id(request.session_id, "session_id")
            _require_id(request.actor_id, "actor_id")
            if not isinstance(request.cloud_mode, CloudMode):
                raise InputInvalidError("cloud_mode must be a CloudMode")
            if request.expected_version < 1:
                raise InputInvalidError("expected_version must be at least 1")
            current = self._scope.repository.get_session(request.session_id)
            if current is None:
                return ApiResult.failed(_failure_not_found("session", request.session_id))
            event = AuditEvent(
                task_id=f"session:{request.session_id}",
                session_id=request.session_id,
                event_type="session.mode_change_succeeded",
                at=self._scope.clock.now(),
                detail=(
                    f"previous={current.cloud_mode.value} new={request.cloud_mode.value} "
                    f"version={request.expected_version} actor={request.actor_id}"
                ),
            )
            updated = self._scope.repository.update_cloud_mode(
                request.session_id,
                request.expected_version,
                request.cloud_mode,
                self._scope.clock.now(),
                event,
            )
            return ApiResult.success(_session_view(updated))
        except BaseException as exc:
            return ApiResult.failed(_failure(exc, correlation_id))

    # ---- public task operations ----------------------------------------

    def submit(self, request: SubmitRequest) -> ApiResult[TaskAccepted]:
        correlation_id = request.request_id if isinstance(request, SubmitRequest) else "submit"
        try:
            if not isinstance(request, SubmitRequest):
                raise InputInvalidError("submit request is invalid")
            _require_id(request.request_id, "request_id")
            _require_id(request.session_id, "session_id")
            clean_text = normalize_and_validate(
                request.text, max_chars=self._scope.config.max_input_chars
            )
            session = self._scope.repository.get_session(request.session_id)
            if session is None:
                return ApiResult.failed(_failure_not_found("session", request.session_id))
            task_request = TaskRequest(
                request_id=request.request_id,
                session_id=session.session_id,
                text=clean_text,
                cloud_mode=session.cloud_mode,
                persistence_mode=session.persistence_mode,
                submitted_at=self._scope.clock.now(),
                approval_id=request.approval_id,
                action_confirmation_id=request.action_confirmation_id,
                route_proposal=_route_proposal(request.route_proposal),
                capability_intent=_capability_intent(request.capability_intent),
            )
            task_id = f"task-{task_request.request_id}"
            future = self._submit_internal(task_request)
            with self._lock:
                self._futures[task_id] = future
                self._accepted_tasks[task_id] = session.session_id
            return ApiResult.success(
                TaskAccepted(
                    task_id=task_id,
                    request_id=request.request_id,
                    session_id=session.session_id,
                    status=TaskStatus.QUEUED,
                )
            )
        except BaseException as exc:
            return ApiResult.failed(_failure(exc, correlation_id))

    def submit_and_wait(self, request: SubmitRequest) -> ApiResult[TaskView]:
        accepted = self.submit(request)
        if not accepted.is_success:
            return ApiResult.failed(accepted.failure)  # type: ignore[arg-type]
        assert accepted.value is not None
        with self._lock:
            future = self._futures.get(accepted.value.task_id)
        if future is None:
            return ApiResult.failed(
                _failure_internal("task future was not retained", accepted.value.task_id)
            )
        try:
            future.result()
        except BaseException as exc:
            # The durable task state, when available, remains the source of truth.
            if isinstance(exc, EllyError):
                return ApiResult.failed(_failure(exc, accepted.value.task_id))
            return ApiResult.failed(
                _failure_internal("task execution failed", accepted.value.task_id)
            )
        return self.get_task(accepted.value.task_id)

    def get_task(self, task_id: str) -> ApiResult[TaskView]:
        try:
            _require_id(task_id, "task_id")
            self._harvest_future(task_id)
            session_id = self._scope.repository.task_session_id(task_id)
            status_raw = self._scope.repository.task_status(task_id)
            if session_id is None or status_raw is None:
                with self._lock:
                    accepted_session_id = self._accepted_tasks.get(task_id)
                if accepted_session_id is not None:
                    return ApiResult.success(
                        TaskView(
                            task_id=task_id,
                            session_id=accepted_session_id,
                            status=TaskStatus.QUEUED,
                        )
                    )
                return ApiResult.failed(_failure_not_found("task", task_id))
            try:
                status = TaskStatus(status_raw)
            except ValueError as exc:
                raise StorageFailureError("stored task status is invalid") from exc
            with self._lock:
                outcome = self._outcomes.get(task_id)
            if outcome is None:
                result = self._scope.repository.get_task_result(task_id)
                if result is None and status in {
                    TaskStatus.AWAITING_CONSENT,
                    TaskStatus.AWAITING_CONFIRMATION,
                    TaskStatus.COMPLETED,
                    TaskStatus.PARTIAL,
                    TaskStatus.CANCELLED,
                    TaskStatus.FAILED,
                    TaskStatus.BLOCKED,
                }:
                    # The orchestrator records its terminal row immediately
                    # before the executor publishes the Future result. Give
                    # that handoff a bounded opportunity to complete instead
                    # of returning a terminal view with missing fields.
                    self._wait_for_future(task_id)
                    self._harvest_future(task_id)
                    with self._lock:
                        outcome = self._outcomes.get(task_id)
                    result = (
                        outcome.result
                        if outcome is not None
                        else self._scope.repository.get_task_result(task_id)
                    )
            else:
                result = outcome.result
            with self._lock:
                action_confirmation = next(
                    (
                        pending.proposal
                        for pending in self._pending_actions.values()
                        if pending.proposal.task_id == task_id
                    ),
                    None,
                )
            fallback_route = None
            if result is None:
                fallback_route = next(
                    (
                        event.route
                        for event in reversed(self._scope.repository.audit_by_task(task_id))
                        if event.route is not None
                    ),
                    None,
                )
            plan = _latest_plan_for_task(self._scope.repository, task_id)
            plan_view = _plan_view(self._scope.repository, plan) if plan is not None else None
            plan_result_view = (
                _plan_result_view(self._scope.repository, plan, result)
                if plan is not None
                else None
            )
            return ApiResult.success(
                _task_view(
                    task_id,
                    session_id,
                    status,
                    result,
                    self._scope.repository.task_sources(task_id),
                    action_confirmation,
                    fallback_route,
                    plan_view,
                    plan_result_view,
                )
            )
        except BaseException as exc:
            return ApiResult.failed(_failure(exc, task_id or "task-read"))

    def get_plan(self, request: PlanQuery) -> ApiResult[PlanView]:
        """Return a bounded public view of one persisted execution plan."""

        correlation_id = request.plan_id if isinstance(request, PlanQuery) else "plan-read"
        try:
            if not isinstance(request, PlanQuery):
                raise InputInvalidError("plan query is invalid")
            _require_id(request.plan_id, "plan_id")
            _require_id(request.actor_id, "actor_id")
            plan = cast(PlanRepositoryPort, self._scope.repository).get_plan(request.plan_id)
            if plan is None:
                return ApiResult.failed(_failure_not_found("plan", request.plan_id))
            return ApiResult.success(_plan_view(self._scope.repository, plan))
        except BaseException as exc:
            return ApiResult.failed(_failure(exc, correlation_id))

    def get_plan_trace(self, request: PlanTraceQuery) -> ApiResult[PlanTraceView]:
        """Return safe plan transitions and contributing result/evidence IDs."""

        correlation_id = request.plan_id if isinstance(request, PlanTraceQuery) else "plan-trace"
        try:
            if not isinstance(request, PlanTraceQuery):
                raise InputInvalidError("plan trace query is invalid")
            _require_id(request.plan_id, "plan_id")
            _require_id(request.actor_id, "actor_id")
            plan = cast(PlanRepositoryPort, self._scope.repository).get_plan(request.plan_id)
            if plan is None:
                return ApiResult.failed(_failure_not_found("plan", request.plan_id))
            return ApiResult.success(_plan_trace_view(self._scope.repository, plan))
        except BaseException as exc:
            return ApiResult.failed(_failure(exc, correlation_id))

    def cancel_task(self, task_id: str) -> ApiResult[TaskView]:
        try:
            _require_id(task_id, "task_id")
            current = self.get_task(task_id)
            if not current.is_success:
                return current
            assert current.value is not None
            if current.value.status in {
                TaskStatus.COMPLETED,
                TaskStatus.PARTIAL,
                TaskStatus.CANCELLED,
                TaskStatus.FAILED,
                TaskStatus.BLOCKED,
                TaskStatus.INTERRUPTED,
            }:
                return current
            if current.value.status is TaskStatus.QUEUED:
                with self._lock:
                    future = self._futures.get(task_id)
                if future is not None and future.cancel():
                    return self._cancel_queued_task(task_id, current.value.session_id)
            if not self._scope.cancel_task(task_id):
                return ApiResult.failed(
                    ApiFailure(
                        code=ApiFailureCode.CONFLICT,
                        safe_message="task is not cancellable in this application instance",
                        retryable=False,
                        correlation_id=task_id,
                    )
                )
            with self._lock:
                future = self._futures.get(task_id)
            if future is not None:
                try:
                    future.result(timeout=2.0)
                except TimeoutError:
                    pass
                except BaseException:
                    pass
            return self.get_task(task_id)
        except BaseException as exc:
            return ApiResult.failed(_failure(exc, task_id or "task-cancel"))

    def _cancel_queued_task(self, task_id: str, session_id: str) -> ApiResult[TaskView]:
        """Materialize cancellation for work removed before orchestration starts."""
        now = self._scope.clock.now()
        result = compose_cancelled(task_id=task_id)
        self._scope.repository.start_task(task_id, session_id, now)
        self._scope.repository.finish_task(task_id, TaskStatus.CANCELLED.value, now)
        self._scope.repository.save_task_result(result, now)
        return self.get_task(task_id)

    # ---- approved query/command operations -----------------------------

    def get_profile(
        self, request: ProfileQuery | None = None
    ) -> ApiResult[tuple[ProfileView, ...]]:
        request = request or ProfileQuery()
        try:
            if not isinstance(request, ProfileQuery):
                raise InputInvalidError("profile query is invalid")
            _require_id(request.actor_id, "actor_id")
            return ApiResult.success(
                tuple(_profile_view(item) for item in self._scope.profile.list())
            )
        except BaseException as exc:
            return ApiResult.failed(_failure(exc, "profile-read"))

    def change_profile(self, request: ProfileCommand) -> ApiResult[ProfileView | bool]:
        correlation_id = (
            request.item_id if isinstance(request, ProfileCommand) else "profile-command"
        )
        try:
            if not isinstance(request, ProfileCommand):
                raise InputInvalidError("profile command is invalid")
            _require_id(request.actor_id, "actor_id")
            _require_id(request.item_id, "item_id")
            if request.operation is ProfileCommandKind.ADD:
                item = self._scope.profile.add(
                    item_id=request.item_id,
                    key=request.key,
                    value=request.value,
                    sensitivity=request.sensitivity,
                )
                return ApiResult.success(_profile_view(item))
            if request.operation is ProfileCommandKind.CORRECT:
                item = self._scope.profile.correct(
                    request.item_id,
                    key=request.key,
                    value=request.value,
                    sensitivity=request.sensitivity,
                )
                return ApiResult.success(_profile_view(item))
            if request.operation is ProfileCommandKind.DELETE:
                return ApiResult.success(self._scope.profile.delete(request.item_id))
            raise InputInvalidError("profile operation is invalid")
        except BaseException as exc:
            return ApiResult.failed(_failure(exc, correlation_id))

    def list_history(self, request: HistoryQuery | None = None) -> ApiResult[HistoryView]:
        request = request or HistoryQuery()
        try:
            if not isinstance(request, HistoryQuery):
                raise InputInvalidError("history query is invalid")
            _require_id(request.actor_id, "actor_id")
            if request.session_id is None:
                records = self._scope.repository.list_sessions()
            else:
                _require_id(request.session_id, "session_id")
                record = self._scope.repository.get_session(request.session_id)
                if record is None:
                    return ApiResult.failed(_failure_not_found("session", request.session_id))
                records = [record]
            return ApiResult.success(
                HistoryView(tuple(_session_view(record) for record in records))
            )
        except BaseException as exc:
            return ApiResult.failed(_failure(exc, "history-read"))

    def delete_session(self, session_id: str) -> ApiResult[bool]:
        try:
            _require_id(session_id, "session_id")
            deleted = self._scope.repository.delete_session(session_id)
            if not deleted:
                return ApiResult.failed(_failure_not_found("session", session_id))
            return ApiResult.success(True)
        except BaseException as exc:
            return ApiResult.failed(_failure(exc, session_id or "session-delete"))

    def get_trace(self, request: TraceQuery) -> ApiResult[TraceView]:
        try:
            if not isinstance(request, TraceQuery):
                raise InputInvalidError("trace query is invalid")
            _require_id(request.task_id, "task_id")
            _require_id(request.actor_id, "actor_id")
            if self._scope.repository.task_session_id(request.task_id) is None:
                return ApiResult.failed(_failure_not_found("task", request.task_id))
            events = self._scope.repository.audit_by_task(request.task_id)
            plan_trace_events: list[TraceEventView] = []
            list_plans = getattr(self._scope.repository, "list_plans_for_task", None)
            if callable(list_plans):
                for plan in list_plans(request.task_id):
                    event_reader = getattr(self._scope.repository, "plan_events", None)
                    if not callable(event_reader):
                        continue
                    plan_trace_events.extend(
                        TraceEventView(
                            event_type=event.event_type,
                            at=event.created_at,
                            route=None,
                            task_status=None,
                            error_class=None,
                            detail=_public_trace_detail(event.detail),
                        )
                        for event in event_reader(plan.plan_id)
                    )
            audit_trace_events = tuple(
                TraceEventView(
                    event_type=event.event_type,
                    at=event.at,
                    route=event.route,
                    task_status=event.task_status,
                    error_class=event.error_class.value if event.error_class else None,
                    detail=_public_trace_detail(event.detail),
                )
                for event in events
            )
            combined_events = tuple(
                sorted(audit_trace_events + tuple(plan_trace_events), key=lambda event: event.at)
            )
            result = self._scope.repository.get_task_result(request.task_id)
            return ApiResult.success(
                TraceView(
                    task_id=request.task_id,
                    events=combined_events,
                    route_category=result.route_category if result is not None else None,
                    capability_id=result.capability_id if result is not None else None,
                    operation=result.operation if result is not None else "",
                    selection_reason_code=(
                        result.selection_reason_code if result is not None else ""
                    ),
                    routing_contract_version=(
                        result.routing_contract_version if result is not None else ""
                    ),
                    candidate_count=result.candidate_count if result is not None else 0,
                    rejected_candidate_reason_codes=(
                        result.rejected_candidate_reason_codes if result is not None else ()
                    ),
                    clarification_required=(
                        result.clarification_required if result is not None else False
                    ),
                    freshness_affected_selection=(
                        result.freshness_affected_selection if result is not None else False
                    ),
                )
            )
        except BaseException as exc:
            return ApiResult.failed(_failure(exc, "trace-read"))

    def get_sources(self, request: SourcesQuery) -> ApiResult[SourcesView]:
        try:
            if not isinstance(request, SourcesQuery):
                raise InputInvalidError("sources query is invalid")
            _require_id(request.task_id, "task_id")
            _require_id(request.actor_id, "actor_id")
            if self._scope.repository.task_session_id(request.task_id) is None:
                return ApiResult.failed(_failure_not_found("task", request.task_id))
            return ApiResult.success(
                SourcesView(request.task_id, self._scope.repository.task_sources(request.task_id))
            )
        except BaseException as exc:
            return ApiResult.failed(_failure(exc, "sources-read"))

    # ---- consent, action, backup, and status ---------------------------

    def list_consents(
        self, request: ConsentQuery | None = None
    ) -> ApiResult[tuple[ConsentView, ...]]:
        request = request or ConsentQuery()
        try:
            if not isinstance(request, ConsentQuery):
                raise InputInvalidError("consent query is invalid")
            _require_id(request.actor_id, "actor_id")
            if self._scope.consent is None:
                return ApiResult.failed(
                    _failure_unavailable("consent workflow is unavailable", "consent-list")
                )
            return ApiResult.success(
                tuple(
                    _consent_view(proposal)
                    for proposal in self._scope.consent.pending(now=self._scope.clock.now())
                )
            )
        except BaseException as exc:
            return ApiResult.failed(_failure(exc, "consent-list"))

    def decide_consent(self, request: ConsentDecisionRequest) -> ApiResult[TaskView]:
        correlation_id = (
            request.proposal_id
            if isinstance(request, ConsentDecisionRequest)
            else "consent-decision"
        )
        try:
            if not isinstance(request, ConsentDecisionRequest):
                raise InputInvalidError("consent decision is invalid")
            _require_id(request.proposal_id, "proposal_id")
            _require_id(request.actor_id, "actor_id")
            if self._scope.consent is None:
                return ApiResult.failed(
                    _failure_unavailable("consent workflow is unavailable", correlation_id)
                )
            with self._lock:
                pending = self._pending_submissions.get(request.proposal_id)
            if pending is None:
                return ApiResult.failed(_failure_not_found("consent proposal", request.proposal_id))
            if not request.approve:
                self._scope.consent.deny(
                    request.proposal_id, interface=request.actor_id, now=self._scope.clock.now()
                )
                with self._lock:
                    existing = self._outcomes.get(pending.proposal.task_id)
                blocked = _blocked_after_consent_denial(
                    pending.proposal,
                    existing.result.route_summary
                    if existing is not None
                    else Route.REGISTERED_CAPABILITY,
                )
                if existing is not None:
                    blocked = inherit_route_metadata(blocked, existing.result)
                self._scope.repository.finish_task(
                    pending.proposal.task_id, TaskStatus.BLOCKED.value, self._scope.clock.now()
                )
                self._scope.repository.save_task_result(blocked, self._scope.clock.now())
                self._scope.audit.append(
                    AuditEvent(
                        task_id=pending.proposal.task_id,
                        session_id=pending.request.session_id,
                        event_type="consent.denied",
                        at=self._scope.clock.now(),
                        task_status=TaskStatus.BLOCKED,
                        detail=f"proposal={request.proposal_id} actor={request.actor_id}",
                    )
                )
                with self._lock:
                    self._pending_submissions.pop(request.proposal_id, None)
                return self.get_task(pending.proposal.task_id)
            self._scope.consent.approve(
                request.proposal_id, interface=request.actor_id, now=self._scope.clock.now()
            )
            self._scope.audit.append(
                AuditEvent(
                    task_id=pending.proposal.task_id,
                    session_id=pending.request.session_id,
                    event_type="consent.approved",
                    at=self._scope.clock.now(),
                    task_status=TaskStatus.AWAITING_CONSENT,
                    detail=f"proposal={request.proposal_id} actor={request.actor_id}",
                )
            )
            approved_request = replace(pending.request, approval_id=request.proposal_id)
            approved_future = self._submit_internal(approved_request)
            try:
                approved_future.result(timeout=2.0)
            except TimeoutError:
                pass
            except BaseException as exc:
                return ApiResult.failed(_failure(exc, correlation_id))
            with self._lock:
                self._pending_submissions.pop(request.proposal_id, None)
            return self.get_task(pending.proposal.task_id)
        except BaseException as exc:
            return ApiResult.failed(_failure(exc, correlation_id))

    def decide_action(self, request: ActionDecisionRequest) -> ApiResult[TaskView]:
        correlation_id = (
            request.confirmation_id
            if isinstance(request, ActionDecisionRequest)
            else "action-decision"
        )
        try:
            if not isinstance(request, ActionDecisionRequest):
                raise InputInvalidError("action decision is invalid")
            _require_id(request.confirmation_id, "confirmation_id")
            _require_id(request.actor_id, "actor_id")
            pending = self._pending_actions.get(request.confirmation_id)
            if pending is None:
                return ApiResult.failed(
                    _failure_not_found("action confirmation", request.confirmation_id)
                )
            if not request.approve:
                self._scope.action_authorization.confirmations.deny(
                    request.confirmation_id,
                    interface=request.actor_id,
                    now=self._scope.clock.now(),
                )
                with self._lock:
                    prior_outcome = self._outcomes.get(pending.proposal.task_id)
                route = (
                    prior_outcome.result.route_summary
                    if prior_outcome is not None
                    else Route.LOCAL_CONVERSATION
                )
                blocked = _blocked_after_action_denial(pending.proposal, route)
                if prior_outcome is not None:
                    blocked = inherit_route_metadata(blocked, prior_outcome.result)
                self._scope.repository.finish_task(
                    pending.proposal.task_id,
                    TaskStatus.BLOCKED.value,
                    self._scope.clock.now(),
                )
                self._scope.repository.save_task_result(blocked, self._scope.clock.now())
                self._scope.audit.append(
                    AuditEvent(
                        task_id=pending.proposal.task_id,
                        session_id=pending.request.session_id,
                        event_type="action.confirmation_denied",
                        at=self._scope.clock.now(),
                        task_status=TaskStatus.BLOCKED,
                        detail=(
                            f"confirmation={request.confirmation_id} "
                            f"category={pending.proposal.proposal.category.value} "
                            f"target={safe_action_target_reference(pending.proposal.proposal.target)} "
                            f"digest={pending.proposal.action_digest[:16]} "
                            f"actor={request.actor_id}"
                        ),
                    )
                )
                with self._lock:
                    self._pending_actions.pop(request.confirmation_id, None)
                    prior = self._outcomes.get(pending.proposal.task_id)
                    self._outcomes[pending.proposal.task_id] = ConversationOutcome(
                        result=blocked,
                        manifest=(
                            prior.manifest if prior is not None else ContextManifest((), {}, 0, 0)
                        ),
                    )
                return self.get_task(pending.proposal.task_id)

            self._scope.action_authorization.confirmations.approve(
                request.confirmation_id,
                interface=request.actor_id,
                now=self._scope.clock.now(),
            )
            self._scope.audit.append(
                AuditEvent(
                    task_id=pending.proposal.task_id,
                    session_id=pending.request.session_id,
                    event_type="action.confirmation_approved",
                    at=self._scope.clock.now(),
                    task_status=TaskStatus.AWAITING_CONFIRMATION,
                    detail=(
                        f"confirmation={request.confirmation_id} "
                        f"category={pending.proposal.proposal.category.value} "
                        f"target={safe_action_target_reference(pending.proposal.proposal.target)} "
                        f"digest={pending.proposal.action_digest[:16]} "
                        f"actor={request.actor_id}"
                    ),
                )
            )
            approved_request = replace(
                pending.request,
                action_confirmation_id=request.confirmation_id,
            )
            approved_future = self._submit_internal(approved_request)
            try:
                approved_future.result(timeout=2.0)
            except TimeoutError:
                pass
            except BaseException as exc:
                return ApiResult.failed(_failure(exc, correlation_id))
            with self._lock:
                self._pending_actions.pop(request.confirmation_id, None)
            return self.get_task(pending.proposal.task_id)
        except BaseException as exc:
            return ApiResult.failed(_failure(exc, correlation_id))

    def create_backup(self, request: BackupRequest) -> ApiResult[BackupView]:
        correlation_id = "backup-create"
        try:
            if not isinstance(request, BackupRequest):
                raise InputInvalidError("backup request is invalid")
            _require_id(request.destination, "destination")
            if self._scope.backup is None:
                return ApiResult.failed(
                    _failure_unavailable("backup is unavailable", correlation_id)
                )
            return ApiResult.success(BackupView(self._scope.backup.create(request.destination)))
        except BaseException as exc:
            return ApiResult.failed(_failure(exc, correlation_id))

    def restore_backup(self, request: RestoreRequest) -> ApiResult[BackupView]:
        correlation_id = "backup-restore"
        try:
            if not isinstance(request, RestoreRequest):
                raise InputInvalidError("restore request is invalid")
            _require_id(request.backup_path, "backup_path")
            if self._scope.backup is None:
                return ApiResult.failed(
                    _failure_unavailable("backup is unavailable", correlation_id)
                )
            self._scope.backup.restore(request.backup_path)
            return ApiResult.success(BackupView(request.backup_path, restart_required=True))
        except BaseException as exc:
            return ApiResult.failed(_failure(exc, correlation_id))

    def get_status(self) -> ApiResult[ApplicationStatusView]:
        try:
            config = self._scope.config
            guardrails = self._scope.guardrails
            capabilities = tuple(
                CapabilityStatusView(
                    descriptor.capability_id,
                    self._scope.capability_registry.status(descriptor.capability_id).state.value,
                    self._scope.capability_registry.status(descriptor.capability_id).reason_code,
                )
                for descriptor in self._scope.capability_registry.descriptors()
            )
            return ApiResult.success(
                ApplicationStatusView(
                    health=tuple(
                        HealthView(report.component, report.state, report.detail)
                        for report in self._scope.health()
                    ),
                    capabilities=capabilities,
                    runtime=RuntimeStatusView(
                        generalist_provider=config.conversation_role.provider,
                        generalist_model_id=config.conversation_role.model_id,
                        research_provider=config.research_provider,
                        research_model_id=config.research_model_id,
                        specialist_provider=config.specialist_provider,
                        specialist_model_id=config.specialist_default_model_id,
                        local_model_roles=tuple(
                            LocalModelRoleView(
                                role=role.role,
                                profile_name=role.profile_name,
                                provider=role.provider,
                                model_id=role.model_id,
                                endpoint_host=role.endpoint_host,
                                max_output_tokens=role.max_output_tokens,
                                timeout_seconds=role.timeout_seconds,
                            )
                            for role in (
                                config.conversation_role,
                                config.planner_role,
                                config.response_composer_role,
                            )
                        ),
                    ),
                    limits=LimitsStatusView(
                        max_steps=config.max_steps,
                        max_provider_calls=config.max_provider_calls,
                        max_retries=config.max_retries,
                        max_concurrency=config.max_concurrency,
                        max_queue_size=config.max_queue_size,
                        tool_timeout_seconds=config.tool_timeout_seconds,
                        total_timeout_seconds=config.total_timeout_seconds,
                    ),
                    pricing=PricingStatusView(
                        remote_call_reservation_usd=config.remote_call_reservation_usd,
                        consent_max_cost_usd=config.consent_max_cost_usd,
                        monthly_budget_usd=config.monthly_budget_usd,
                    ),
                    budget=(
                        BudgetStatusView(
                            reserved_usd=guardrails.cost.reserved_usd,
                            remaining_usd=guardrails.cost.remaining_usd,
                            warning_level=guardrails.cost.warning_level,
                        )
                        if guardrails is not None
                        else None
                    ),
                )
            )
        except BaseException as exc:
            return ApiResult.failed(_failure(exc, "status"))

    # ---- internal translation and future lifecycle --------------------

    def _submit_internal(self, request: TaskRequest) -> Future[ConversationOutcome]:
        if self._scope.executor is not None:
            future = self._scope.submit(request)
        else:
            future = Future()
            try:
                future.set_result(self._scope.handle(request))
            except BaseException as exc:
                future.set_exception(exc)
        task_id = f"task-{request.request_id}"
        with self._lock:
            self._futures[task_id] = future
            self._requests[task_id] = request
        future.add_done_callback(
            lambda completed: self._on_future_done(task_id, request, completed)
        )
        return future

    def _on_future_done(
        self,
        task_id: str,
        request: TaskRequest,
        future: Future[ConversationOutcome],
    ) -> None:
        with self._lock:
            if future in self._processed_futures:
                return
            self._processed_futures.add(future)
            try:
                outcome = future.result()
            except BaseException as exc:
                self._future_errors[task_id] = exc
                return
            # Persist before publishing resumable consent/action state. Keep
            # the façade lock until publication so submit_and_wait/get_task
            # cannot observe a processed-but-not-yet-published callback.
            try:
                self._scope.repository.save_task_result(outcome.result, self._scope.clock.now())
            except StorageFailureError:
                logging.getLogger("elly.api").error(
                    "task result persistence failed task_id=%s", task_id
                )
            self._outcomes[task_id] = outcome
            if outcome.consent_proposal is not None:
                self._pending_submissions[outcome.consent_proposal.proposal_id] = (
                    _PendingSubmission(
                        request=request,
                        proposal=outcome.consent_proposal,
                    )
                )
            if outcome.action_confirmation is not None:
                self._pending_actions[outcome.action_confirmation.confirmation_id] = _PendingAction(
                    request=request,
                    proposal=outcome.action_confirmation,
                )

    def _harvest_future(self, task_id: str) -> None:
        with self._lock:
            future = self._futures.get(task_id)
            request = self._requests.get(task_id)
        if future is None or not future.done():
            return
        if request is not None:
            self._on_future_done(task_id, request, future)

    def _wait_for_future(self, task_id: str) -> None:
        with self._lock:
            future = self._futures.get(task_id)
        if future is None or future.done():
            return
        try:
            future.result(timeout=1.0)
        except TimeoutError:
            return
        except BaseException:
            return


def _session_view(record: SessionRecord) -> SessionView:
    assert record.updated_at is not None
    return SessionView(
        session_id=record.session_id,
        persistence_mode=record.persistence_mode,
        cloud_mode=record.cloud_mode,
        created_at=record.created_at,
        updated_at=record.updated_at,
        version=record.version,
    )


def _route_proposal(proposal: RouteProposalInput | None) -> RouteProposal | None:
    if proposal is None:
        return None
    return RouteProposal(
        route=proposal.route,
        capability_id=proposal.capability_id,
        request_schema=proposal.request_schema,
    )


def _capability_intent(intent: CapabilityIntentInput | None) -> CapabilityIntent | None:
    if intent is None:
        return None
    try:
        ambiguity = IntentAmbiguity(intent.ambiguity)
        entities = tuple(
            IntentEntity(entity.kind, entity.value, IntentEntitySource(entity.source))
            for entity in intent.entities
        )
        arguments = dict(intent.arguments)
    except (TypeError, ValueError) as exc:
        raise InputInvalidError("capability intent is invalid") from exc
    return CapabilityIntent(
        proposed_capability_id=intent.proposed_capability_id,
        operation=intent.operation,
        entities=entities,
        arguments=arguments,
        confidence=intent.confidence,
        ambiguity=ambiguity,
        rationale_code=intent.rationale_code,
    )


def _profile_view(item) -> ProfileView:  # type: ignore[no-untyped-def]
    return ProfileView(
        item_id=item.item_id,
        key=item.key,
        value=item.value,
        sensitivity=item.sensitivity,
        confirmed=item.confirmed,
        created_at=item.created_at,
        updated_at=item.updated_at,
        expires_at=item.expires_at,
    )


def _latest_plan_for_task(repository: object, task_id: str) -> ExecutionPlan | None:
    list_plans = getattr(repository, "list_plans_for_task", None)
    if not callable(list_plans):
        return None
    plans = tuple(plan for plan in list_plans(task_id) if isinstance(plan, ExecutionPlan))
    if not plans:
        return None
    return max(plans, key=lambda plan: (plan.revision, plan.plan_id))


def _step_event_parts(detail: str) -> tuple[str, str]:
    if not isinstance(detail, str):
        return "", ""
    values: dict[str, str] = {}
    for item in detail.split():
        if "=" in item:
            key, value = item.split("=", 1)
            values[key] = value
    return values.get("step", ""), values.get("state", "")


def _plan_view(repository: object, plan: ExecutionPlan) -> PlanView:
    events_reader = getattr(repository, "plan_events", None)
    events = tuple(events_reader(plan.plan_id)) if callable(events_reader) else ()
    step_events: dict[str, list[object]] = {step.step_id: [] for step in plan.steps}
    for event in events:
        step_id, _state = _step_event_parts(getattr(event, "detail", ""))
        if step_id in step_events:
            step_events[step_id].append(event)

    get_envelope = getattr(repository, "get_step_envelope", None)
    get_result = getattr(repository, "get_step_result", None)
    step_views: list[PlanStepView] = []
    terminal_states = {
        StepState.COMPLETED,
        StepState.PARTIAL,
        StepState.FAILED,
        StepState.BLOCKED,
        StepState.UNAVAILABLE,
        StepState.CANCELLED,
        StepState.SKIPPED,
        StepState.INTERRUPTED,
    }
    for step in plan.steps:
        history = step_events[step.step_id]
        reason_code = getattr(history[-1], "reason_code", "") if history else ""
        started_at = None
        completed_at = None
        for event in history:
            _step_id, state_value = _step_event_parts(getattr(event, "detail", ""))
            if state_value == StepState.RUNNING.value and started_at is None:
                started_at = getattr(event, "created_at", None)
            if state_value in {state.value for state in terminal_states}:
                completed_at = getattr(event, "created_at", None)
            if getattr(event, "event_type", "") == "step.result" and completed_at is None:
                completed_at = getattr(event, "created_at", None)
        envelope = get_envelope(plan.plan_id, step.step_id) if callable(get_envelope) else None
        result = get_result(plan.plan_id, step.step_id) if callable(get_result) else None
        usage = None
        if envelope is not None and envelope.usage is not None:
            usage = PlanUsageView(
                input_tokens=envelope.usage.input_tokens,
                output_tokens=envelope.usage.output_tokens,
                latency_ms=envelope.usage.latency_ms,
                provider_calls=envelope.usage.provider_calls,
                cost_usd=envelope.usage.cost_usd,
            )
        result_ids = (
            (f"result-{step.step_id}",) if envelope is not None or result is not None else ()
        )
        evidence_ids: list[str] = []
        if envelope is not None:
            for claim in envelope.claims:
                evidence_ids.extend(claim.evidence_ids)
            for support in envelope.claim_supports:
                evidence_ids.extend(support.evidence_ids)
        step_views.append(
            PlanStepView(
                step_id=step.step_id,
                capability_id=step.capability_id,
                operation=step.operation_id,
                dependencies=step.dependencies,
                state=step.state,
                criticality=step.criticality,
                reason_code=reason_code,
                started_at=started_at,
                completed_at=completed_at,
                usage=usage,
                result_ids=result_ids,
                evidence_ids=tuple(dict.fromkeys(evidence_ids)),
            )
        )
    synthesis_view = None
    get_synthesis = getattr(repository, "get_synthesis_result", None)
    synthesis = get_synthesis(plan.plan_id) if callable(get_synthesis) else None
    if synthesis is not None:
        synthesis_view = PlanSynthesisView(
            plan_id=synthesis.plan_id,
            strategy=synthesis.strategy,
            validation_state=synthesis.validation_state,
            referenced_result_ids=synthesis.referenced_result_ids,
            created_at=synthesis.created_at,
            updated_at=synthesis.updated_at,
        )
    return PlanView(
        plan_id=plan.plan_id,
        task_id=plan.task_id,
        revision=plan.revision,
        status=plan.status,
        finalization=plan.finalization,
        steps=tuple(step_views),
        parent_plan_id=plan.parent_plan_id,
        catalog_version=plan.catalog_version,
        created_at=(getattr(events[0], "created_at", None) if events else None),
        updated_at=(getattr(events[-1], "created_at", None) if events else None),
        synthesis=synthesis_view,
    )


def _plan_result_view(
    repository: object,
    plan: ExecutionPlan,
    task_result: TaskResult | None,
) -> PlanResultView | None:
    if plan.status in {PlanStatus.PENDING, PlanStatus.RUNNING}:
        return None
    get_result = getattr(repository, "get_step_result", None)
    get_envelope = getattr(repository, "get_step_envelope", None)
    results = {
        step.step_id: value
        for step in plan.steps
        if callable(get_result) and (value := get_result(plan.plan_id, step.step_id)) is not None
    }
    envelopes = {
        step.step_id: value
        for step in plan.steps
        if callable(get_envelope)
        and (value := get_envelope(plan.plan_id, step.step_id)) is not None
    }
    aggregation = aggregate_plan_results(
        plan,
        results,
        envelopes,
        states={step.step_id: step.state for step in plan.steps},
        cancellation_accepted=plan.status is PlanStatus.CANCELLED,
    )
    answer = task_result.answer if task_result is not None and task_result.answer_retained else ""
    if not answer and aggregation.eligible_step_ids:
        answer = "\n".join(
            aggregation.step_results[step_id].answer
            for step_id in aggregation.eligible_step_ids
            if aggregation.step_results.get(step_id) is not None
            and aggregation.step_results[step_id].answer_retained
            and aggregation.step_results[step_id].answer
        )
    return PlanResultView(
        plan_id=plan.plan_id,
        task_id=plan.task_id,
        # The persisted plan status is the authoritative terminal value. The
        # aggregate may have less evidence after no-store retention and must
        # never elevate that status from partial/cancelled to completed.
        status=plan.status,
        finalization=plan.finalization,
        answer=answer,
        eligible_step_ids=aggregation.eligible_step_ids,
        failures=aggregation.failures,
        warnings=aggregation.warnings,
        uncertainties=aggregation.uncertainties,
        disagreements=tuple(
            DisagreementView(
                disagreement_id=item.disagreement_id,
                claim_id=item.claim_id,
                source_kind=item.source_kind,
                step_ids=item.step_ids,
                statements=item.statements,
                evidence_ids=item.evidence_ids,
                reason_code=item.reason_code,
            )
            for item in aggregation.disagreements
        ),
    )


def _plan_trace_view(repository: object, plan: ExecutionPlan) -> PlanTraceView:
    events_reader = getattr(repository, "plan_events", None)
    events = tuple(events_reader(plan.plan_id)) if callable(events_reader) else ()
    get_envelope = getattr(repository, "get_step_envelope", None)
    get_result = getattr(repository, "get_step_result", None)
    result_ids: list[str] = []
    evidence_ids: list[str] = []
    for step in plan.steps:
        envelope = get_envelope(plan.plan_id, step.step_id) if callable(get_envelope) else None
        result = get_result(plan.plan_id, step.step_id) if callable(get_result) else None
        if envelope is not None or result is not None:
            result_ids.append(f"result-{step.step_id}")
        if envelope is not None:
            for claim in envelope.claims:
                evidence_ids.extend(claim.evidence_ids)
            for support in envelope.claim_supports:
                evidence_ids.extend(support.evidence_ids)
    get_synthesis = getattr(repository, "get_synthesis_result", None)
    synthesis = get_synthesis(plan.plan_id) if callable(get_synthesis) else None
    synthesis_result_id = None
    if synthesis is not None:
        synthesis_result_id = f"synthesis-{plan.plan_id}"
        result_ids.extend(synthesis.referenced_result_ids)
    replacements: list[str] = []
    authorization_ids: list[str] = []
    for event in events:
        fields = _safe_event_fields(getattr(event, "detail", ""))
        replacement = fields.get("replacement_plan")
        if replacement is not None:
            replacements.append(replacement)
        for key in ("authorization_id", "consent_id", "decision_id"):
            value = fields.get(key)
            if value is not None:
                authorization_ids.append(value)
    lineage = _plan_lineage(repository, plan)
    public_events = tuple(
        PlanTraceEventView(
            event_type=getattr(event, "event_type", ""),
            reason_code=getattr(event, "reason_code", ""),
            detail=_public_trace_detail(getattr(event, "detail", "")),
            at=getattr(event, "created_at"),
        )
        for event in events
    )
    return PlanTraceView(
        plan_id=plan.plan_id,
        task_id=plan.task_id,
        events=public_events,
        contributing_result_ids=tuple(dict.fromkeys(result_ids)),
        contributing_evidence_ids=tuple(dict.fromkeys(evidence_ids)),
        authorization_ids=tuple(dict.fromkeys(authorization_ids)),
        revision=plan.revision,
        parent_plan_id=plan.parent_plan_id,
        lineage_plan_ids=lineage,
        replacement_plan_ids=tuple(dict.fromkeys(replacements)),
        synthesis_result_id=synthesis_result_id,
    )


def _safe_event_fields(detail: str) -> dict[str, str]:
    """Parse only bounded identifier-like event metadata for provenance links."""
    if not isinstance(detail, str):
        return {}
    fields: dict[str, str] = {}
    for item in detail.split():
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        if key not in {"replacement_plan", "authorization_id", "consent_id", "decision_id"}:
            continue
        if value and all(char.isalnum() or char in "_.:-" for char in value):
            fields[key] = value[:128]
    return fields


def _plan_lineage(repository: object, plan: ExecutionPlan) -> tuple[str, ...]:
    """Return original-to-current plan IDs without following untrusted text."""
    values = [plan.plan_id]
    current = plan
    get_plan = getattr(repository, "get_plan", None)
    seen = {plan.plan_id}
    while current.parent_plan_id and current.parent_plan_id not in seen:
        seen.add(current.parent_plan_id)
        values.append(current.parent_plan_id)
        if not callable(get_plan):
            break
        parent = get_plan(current.parent_plan_id)
        if not isinstance(parent, ExecutionPlan):
            break
        current = parent
    return tuple(reversed(values))


def _task_view(
    task_id: str,
    session_id: str,
    status: TaskStatus,
    result: TaskResult | None,
    sources: tuple[str, ...],
    action_confirmation: ActionConfirmationProposal | None = None,
    fallback_route: Route | None = None,
    plan_view: PlanView | None = None,
    plan_result_view: PlanResultView | None = None,
) -> TaskView:
    if result is None:
        return TaskView(
            task_id=task_id,
            session_id=session_id,
            status=status,
            route=fallback_route,
            sources=sources,
            action_confirmation=(
                _action_confirmation_view(action_confirmation)
                if action_confirmation is not None
                else None
            ),
            plan_id=plan_view.plan_id if plan_view is not None else None,
            plan_status=plan_view.status if plan_view is not None else None,
            plan=plan_view,
            plan_result=plan_result_view,
        )
    return TaskView(
        task_id=task_id,
        session_id=session_id,
        status=status,
        outcome_code=result.outcome_code,
        epistemic_status=result.epistemic_status,
        validation_status=result.validation_status,
        route=result.route_summary,
        answer=result.answer if result.answer_retained else "",
        failures=result.failures,
        partial_work=result.partial_work,
        next_actions=result.next_actions,
        sources=sources,
        action_confirmation=(
            _action_confirmation_view(action_confirmation)
            if action_confirmation is not None
            else None
        ),
        route_category=result.route_category,
        capability_id=result.capability_id,
        operation=result.operation,
        selection_reason_code=result.selection_reason_code,
        routing_contract_version=result.routing_contract_version,
        candidate_count=result.candidate_count,
        rejected_candidate_reason_codes=result.rejected_candidate_reason_codes,
        clarification_required=result.clarification_required,
        freshness_affected_selection=result.freshness_affected_selection,
        plan_id=plan_view.plan_id if plan_view is not None else None,
        plan_status=plan_view.status if plan_view is not None else None,
        plan=plan_view,
        plan_result=plan_result_view,
    )


def _action_confirmation_view(
    proposal: ActionConfirmationProposal,
) -> ActionConfirmationView:
    target_kind = proposal.proposal.target.kind if proposal.proposal.target else None
    target_reference = (
        safe_action_target_reference(proposal.proposal.target) if proposal.proposal.target else None
    )
    return ActionConfirmationView(
        confirmation_id=proposal.confirmation_id,
        task_id=proposal.task_id,
        capability_id=proposal.capability_id,
        operation=proposal.operation,
        category=proposal.proposal.category,
        target_kind=target_kind,
        target_reference=target_reference,
        side_effect=proposal.proposal.side_effect,
        reversibility=proposal.proposal.reversibility,
        data_sensitivity=proposal.proposal.data_sensitivity,
        impact_flags=proposal.proposal.impact_flags,
        action_digest=proposal.action_digest,
        created_at=proposal.created_at,
        expires_at=proposal.expires_at,
    )


def _consent_view(proposal: ConsentProposal) -> ConsentView:
    return ConsentView(
        proposal_id=proposal.proposal_id,
        task_id=proposal.task_id,
        capability_id=proposal.capability_id,
        provider=proposal.provider,
        model=proposal.model,
        purpose=proposal.purpose,
        categories=proposal.categories,
        redacted_preview=proposal.redacted_preview,
        max_reserved_cost=proposal.max_reserved_cost,
        created_at=proposal.created_at,
        expires_at=proposal.expires_at,
    )


def _blocked_after_consent_denial(proposal: ConsentProposal, route: Route) -> TaskResult:
    return TaskResult(
        task_id=proposal.task_id,
        task_status=TaskStatus.BLOCKED,
        outcome_code=OutcomeCode.BLOCKED,
        epistemic_status=EpistemicStatus.BLOCKED,
        validation_status=ValidationStatus.REJECTED,
        answer="",
        route_summary=route,
        failures=("consent denied",),
        next_actions=("submit a new request",),
    )


def _blocked_after_action_denial(proposal: ActionConfirmationProposal, route: Route) -> TaskResult:
    return TaskResult(
        task_id=proposal.task_id,
        task_status=TaskStatus.BLOCKED,
        outcome_code=OutcomeCode.BLOCKED,
        epistemic_status=EpistemicStatus.BLOCKED,
        validation_status=ValidationStatus.REJECTED,
        answer="",
        route_summary=route,
        failures=("action confirmation denied",),
        next_actions=("submit a new request",),
    )


def _require_id(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise InputInvalidError(f"{name} must be non-empty")


def _failure(exc: BaseException, correlation_id: str) -> ApiFailure:
    if isinstance(exc, InputInvalidError):
        return ApiFailure(ApiFailureCode.INVALID_INPUT, exc.summary, False, correlation_id)
    if isinstance(exc, ConflictError):
        return ApiFailure(ApiFailureCode.CONFLICT, exc.summary, True, correlation_id)
    if isinstance(exc, CancelledError):
        return ApiFailure(ApiFailureCode.CANCELLED, exc.summary, False, correlation_id)
    if isinstance(exc, PermissionDeniedError):
        return ApiFailure(ApiFailureCode.BLOCKED, exc.summary, False, correlation_id)
    if isinstance(exc, LimitExceededError):
        return ApiFailure(ApiFailureCode.UNAVAILABLE, exc.summary, True, correlation_id)
    if isinstance(exc, StorageFailureError):
        return ApiFailure(ApiFailureCode.INTERNAL_FAILURE, exc.summary, True, correlation_id)
    if isinstance(exc, EllyError):
        if exc.error_class is ErrorClass.CANCELLED:
            return ApiFailure(ApiFailureCode.CANCELLED, exc.summary, False, correlation_id)
        if exc.error_class is ErrorClass.PERMISSION_DENIED:
            return ApiFailure(ApiFailureCode.BLOCKED, exc.summary, False, correlation_id)
        return ApiFailure(ApiFailureCode.INTERNAL_FAILURE, exc.summary, False, correlation_id)
    if isinstance(exc, ValueError):
        return ApiFailure(ApiFailureCode.INVALID_INPUT, str(exc), False, correlation_id)
    return _failure_internal("internal application failure", correlation_id)


def _failure_not_found(kind: str, identifier: str) -> ApiFailure:
    return ApiFailure(
        ApiFailureCode.NOT_FOUND,
        f"{kind} was not found",
        False,
        identifier,
    )


def _failure_unavailable(message: str, correlation_id: str) -> ApiFailure:
    return ApiFailure(ApiFailureCode.UNAVAILABLE, message, True, correlation_id)


def _failure_internal(message: str, correlation_id: str) -> ApiFailure:
    return ApiFailure(ApiFailureCode.INTERNAL_FAILURE, message, True, correlation_id)


def _public_trace_detail(detail: str) -> str:
    """Apply boundary redaction even when a nonstandard audit port is used."""
    return redact_trace_detail(detail)
    (IntentEntity,)
    (RouteProposal,)
