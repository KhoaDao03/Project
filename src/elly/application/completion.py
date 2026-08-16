"""Durable completion primitives shared by application workflows.

Completion is deliberately kept below the interface and orchestration layers.
It records only validated result metadata and delegates all storage to the
repository/audit ports.
"""

from __future__ import annotations

import time

from ..domain.enums import ErrorClass, Route, TaskStatus
from ..domain.errors import StorageFailureError
from ..domain.models import (
    ActionConfirmationProposal,
    AuditEvent,
    GeneralistResponse,
    Message,
    OperationLease,
    ProvenanceReference,
    RouteDecision,
    TaskRequest,
    TaskResult,
)
from ..guardrails.controller import GuardrailController
from ..ports.audit import AuditPort
from ..ports.clock import ClockPort
from ..ports.repository import SessionRepositoryPort
from .action_authorization import safe_action_target_reference
from .capabilities import CapabilityDescriptor
from .route_compatibility import enrich_task_result


class CompletionService:
    """Own durable task, operation, message, source, provenance, and audit writes."""

    def __init__(
        self,
        *,
        clock: ClockPort,
        repository: SessionRepositoryPort,
        audit: AuditPort,
    ) -> None:
        self._clock = clock
        self._repository = repository
        self._audit = audit

    def emit(
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

    def fail_operation(
        self,
        operation_lease: OperationLease | None,
        *,
        possible_duplicate: bool = False,
    ) -> None:
        if operation_lease is not None:
            self._repository.fail_operation(
                operation_lease.operation_id,
                at=self._clock.now(),
                possible_duplicate=possible_duplicate,
            )

    def best_effort_fail_operation(
        self,
        operation_lease: OperationLease | None,
        *,
        possible_duplicate: bool = False,
    ) -> None:
        try:
            self.fail_operation(operation_lease, possible_duplicate=possible_duplicate)
        except StorageFailureError:
            return

    def finish_task(self, task_id: str, status: TaskStatus) -> None:
        self._repository.finish_task(task_id, status.value, self._clock.now())

    def best_effort_finish_task(self, task_id: str, status: TaskStatus) -> None:
        try:
            self.finish_task(task_id, status)
        except StorageFailureError:
            return

    def persist_result(
        self,
        result: TaskResult,
        route_decision: RouteDecision | None = None,
    ) -> TaskResult:
        """Persist a result and return it with safe routing metadata attached."""
        durable_result = (
            enrich_task_result(result, route_decision) if route_decision is not None else result
        )
        self._repository.save_task_result(durable_result, self._clock.now())
        return durable_result

    def complete_capability(
        self,
        *,
        request: TaskRequest,
        task_id: str,
        route: Route,
        route_decision: RouteDecision,
        descriptor: CapabilityDescriptor,
        result: TaskResult,
        started: float,
        request_guardrails: GuardrailController | None,
        operation_lease: OperationLease | None,
    ) -> None:
        """Persist a validated optional-capability result and close its ledger."""
        durable_result = enrich_task_result(result, route_decision)
        if durable_result.answer and durable_result.task_status not in {
            TaskStatus.AWAITING_CONSENT,
            TaskStatus.CANCELLED,
        }:
            self._repository.append_message(
                request.session_id,
                Message(
                    role="assistant",
                    content=durable_result.answer,
                    created_at=self._clock.now(),
                ),
            )
        self.record_sources(task_id, result.citations)
        self.record_provenance(task_id, result.provenance)
        self.emit(
            request=request,
            task_id=task_id,
            route=route,
            route_decision=route_decision,
            event_type="capability.completed",
            status=durable_result.task_status,
            detail=(
                f"capability={descriptor.capability_id} "
                f"route_reason={route_decision.reason_code.value} "
                f"duration_ms={int((time.monotonic() - started) * 1000)} "
                f"{self.guardrail_detail(request_guardrails)}"
            ),
        )
        self._repository.save_task_result(durable_result, self._clock.now())
        self.finish_task(task_id, durable_result.task_status)
        self.complete_operation(operation_lease)

    def complete_local(
        self,
        *,
        request: TaskRequest,
        task_id: str,
        route: Route,
        route_decision: RouteDecision | None = None,
        result: TaskResult,
        started: float,
        request_guardrails: GuardrailController | None,
        operation_lease: OperationLease | None,
        response: GeneralistResponse,
        provider_name: str,
        model_id: str,
    ) -> None:
        """Persist a validated local result and close its request ledger."""
        durable_result = (
            enrich_task_result(result, route_decision) if route_decision is not None else result
        )
        self.emit(
            request=request,
            task_id=task_id,
            route=route,
            route_decision=route_decision,
            event_type="task.completed",
            status=durable_result.task_status,
            detail=(
                f"provider={provider_name} model={model_id} "
                "prompt=local-generalist-v1 tools=none "
                f"duration_ms={int((time.monotonic() - started) * 1000)} "
                f"output_tokens={response.usage.output_tokens} "
                f"latency_ms={response.usage.latency_ms} "
                f"{self.guardrail_detail(request_guardrails)}"
            ),
        )
        self.record_provenance(task_id, result.provenance)
        self._repository.save_task_result(durable_result, self._clock.now())
        self.finish_task(task_id, durable_result.task_status)
        self.complete_operation(operation_lease)

    def complete_clarification(
        self,
        *,
        request: TaskRequest,
        task_id: str,
        route: Route,
        route_decision: RouteDecision | None = None,
        result: TaskResult,
        operation_lease: OperationLease | None,
        fields: tuple[str, ...],
    ) -> None:
        """Persist a non-executing clarification result and close the ledger."""
        durable_result = (
            enrich_task_result(result, route_decision) if route_decision is not None else result
        )
        self.emit(
            request=request,
            task_id=task_id,
            route=route,
            route_decision=route_decision,
            event_type="intent.clarification_required",
            status=TaskStatus.BLOCKED,
            error_class=ErrorClass.INPUT_INVALID,
            detail=f"fields={','.join(fields)}",
        )
        self.fail_operation(operation_lease)
        self._repository.save_task_result(durable_result, self._clock.now())
        self.finish_task(task_id, TaskStatus.BLOCKED)

    def complete_action_confirmation(
        self,
        *,
        request: TaskRequest,
        task_id: str,
        route: Route,
        route_decision: RouteDecision | None = None,
        result: TaskResult,
        proposal: ActionConfirmationProposal,
        operation_lease: OperationLease | None,
    ) -> None:
        """Persist a non-executing action pause and close this attempt."""
        durable_result = (
            enrich_task_result(result, route_decision) if route_decision is not None else result
        )
        target = (
            f"{proposal.proposal.target.kind}={safe_action_target_reference(proposal.proposal.target)}"
            if proposal.proposal.target is not None
            else "unspecified"
        )
        self.emit(
            request=request,
            task_id=task_id,
            route=route,
            route_decision=route_decision,
            event_type="action.confirmation_requested",
            status=TaskStatus.AWAITING_CONFIRMATION,
            error_class=ErrorClass.PERMISSION_DENIED,
            detail=(
                f"confirmation={proposal.confirmation_id} "
                f"category={proposal.proposal.category.value} target={target} "
                f"digest={proposal.action_digest[:16]}"
            ),
        )
        self.fail_operation(operation_lease)
        self._repository.save_task_result(durable_result, self._clock.now())
        self.finish_task(task_id, TaskStatus.AWAITING_CONFIRMATION)

    def complete_operation(self, operation_lease: OperationLease | None) -> None:
        if operation_lease is not None:
            self._repository.complete_operation(
                operation_lease.operation_id,
                at=self._clock.now(),
            )

    def record_sources(self, task_id: str, sources: tuple[str, ...]) -> None:
        for source in sources:
            if source:
                self._repository.add_task_source(task_id, str(source), self._clock.now())

    def record_provenance(
        self,
        task_id: str,
        references: tuple[ProvenanceReference, ...],
    ) -> None:
        for reference in references:
            self._repository.add_task_provenance(task_id, reference)

    @staticmethod
    def guardrail_detail(request_guardrails: GuardrailController | None) -> str:
        if request_guardrails is None:
            return "guardrails=disabled"
        steps, calls, active = request_guardrails.ledger.snapshot
        return (
            f"steps={steps} provider_calls={calls} retries={request_guardrails.retry_count} "
            f"active={active} estimated_cost_usd={request_guardrails.request_cost_usd:.4f}"
        )
