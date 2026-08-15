"""Application workflow for already-selected optional capabilities."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..domain.enums import ErrorClass, IntentAmbiguity, OutcomeCode, Route, TaskStatus
from ..domain.errors import CancelledError, ConfigInvalidError, EllyError, StorageFailureError
from ..domain.models import (
    ActionConfirmationProposal,
    ActionProposal,
    CapabilityIntent,
    ContextManifest,
    ConversationOutcome,
    OperationLease,
    RouteDecision,
    RouteRequest,
    TaskRequest,
    TaskResult,
)
from ..guardrails.controller import GuardrailController
from ..ports.clock import ClockPort
from ..privacy import ConsentProposal, ConsentWorkflow, PrivacyPolicy
from .action_authorization import (
    ActionAuthorizationRequest,
    ActionAuthorizationService,
    safe_action_target_reference,
)
from .authorization import CloudAuthorizationPolicy, CloudAuthorizationRequest
from .capabilities import CapabilityExecution, CapabilityRegistry, CapabilityRequest
from .completion import CompletionService
from .execution import CancellationToken
from .response_composer import (
    compose_action_confirmation,
    compose_blocked,
    compose_cancelled,
    compose_clarification,
    compose_consent_required,
    compose_failed,
    compose_partial,
)


@dataclass(frozen=True, slots=True)
class CapabilityExecutionCommand:
    """Immutable context passed from routing/orchestration to the workflow."""

    request: TaskRequest
    task_id: str
    status: TaskStatus
    route: Route
    route_request: RouteRequest
    route_decision: RouteDecision
    context_text: str
    context_manifest: ContextManifest
    cancellation: CancellationToken
    request_guardrails: GuardrailController | None = None
    operation_lease: OperationLease | None = None
    started: float = field(default_factory=time.monotonic)


@dataclass(frozen=True, slots=True)
class CapabilityExecutionOutcome:
    """Normalized result returned by optional-capability execution."""

    result: TaskResult
    manifest: ContextManifest
    consent_proposal: ConsentProposal | None = None
    action_confirmation: ActionConfirmationProposal | None = None

    def as_conversation_outcome(self) -> ConversationOutcome:
        return ConversationOutcome(
            result=self.result,
            manifest=self.manifest,
            consent_proposal=self.consent_proposal,
            action_confirmation=self.action_confirmation,
        )


class CapabilityExecutionWorkflow:
    """Own lookup, policy checks, optional execution, and durable completion."""

    def __init__(
        self,
        *,
        clock: ClockPort,
        capability_registry: CapabilityRegistry,
        completion: CompletionService,
        consent: ConsentWorkflow | None = None,
        privacy_policy: PrivacyPolicy | None = None,
        cloud_authorization_policy: CloudAuthorizationPolicy | None = None,
        action_authorization: ActionAuthorizationService | None = None,
    ) -> None:
        self._clock = clock
        self._capability_registry = capability_registry
        self._completion = completion
        self._consent = consent
        self._privacy_policy = privacy_policy or PrivacyPolicy()
        self._cloud_authorization_policy = cloud_authorization_policy or CloudAuthorizationPolicy()
        self._action_authorization = action_authorization or ActionAuthorizationService()

    def execute(self, command: CapabilityExecutionCommand) -> CapabilityExecutionOutcome:
        """Execute one selected optional capability without invoking the orchestrator."""
        if command.route is Route.LOCAL_GENERALIST:
            raise ConfigInvalidError("local conversation must not use capability workflow")

        capability_id = command.route_decision.capability_id
        handler = self._capability_registry.get(capability_id or "")
        if handler is None:
            reason = "requested optional capability is not registered"
            return self._blocked(command, reason, OutcomeCode.UNAVAILABLE)

        capability_status = handler.status()
        if (
            not command.route_decision.available
            or not capability_status.available
        ):
            reason = (
                capability_status.reason_code
                or command.route_decision.diagnostic
                or "capability unavailable"
            )
            return self._blocked(command, reason, OutcomeCode.UNAVAILABLE)

        capability_request = CapabilityRequest(
            task=command.request,
            route_request=command.route_request,
            context_text=command.context_text,
            context_manifest=command.context_manifest,
            task_id=command.task_id,
            execution_at=self._clock.now(),
            request_guardrails=command.request_guardrails,
            cancellation=command.cancellation,
            operation=command.route_decision.operation,
            intent=command.route_decision.intent,
        )
        match = handler.can_handle(capability_request)
        if not match.accepted:
            return self._blocked(
                command,
                match.reason_code or "capability rejected request",
                OutcomeCode.BLOCKED,
                error_class=ErrorClass.INPUT_INVALID,
                event_type="capability.input_rejected",
            )

        descriptor = handler.descriptor
        if command.route not in descriptor.routes:
            self._completion.fail_operation(command.operation_lease)
            self._completion.finish_task(command.task_id, TaskStatus.FAILED)
            return CapabilityExecutionOutcome(
                result=compose_failed(
                    task_id=command.task_id,
                    reason="registered capability does not declare the selected route",
                    route=command.route,
                ),
                manifest=command.context_manifest,
            )

        execution_started = False
        generated_result: TaskResult | None = None
        try:
            intent = command.route_decision.intent
            if intent is None:
                if not capability_id or not descriptor.operations:
                    raise ConfigInvalidError("capability intent is missing")
                intent = CapabilityIntent(
                    proposed_capability_id=capability_id,
                    operation=(
                        command.route_decision.operation or descriptor.operations[0]
                    ),
                    arguments={"subject": command.context_text},
                    confidence=1.0,
                    ambiguity=IntentAmbiguity.CLEAR,
                    rationale_code="LEGACY_ROUTE_DECISION",
                )
                capability_request = CapabilityRequest(
                    task=capability_request.task,
                    route_request=capability_request.route_request,
                    context_text=capability_request.context_text,
                    context_manifest=capability_request.context_manifest,
                    task_id=capability_request.task_id,
                    execution_at=capability_request.execution_at,
                    request_guardrails=capability_request.request_guardrails,
                    cancellation=capability_request.cancellation,
                    operation=intent.operation,
                    intent=intent,
                )
            preparation = handler.prepare(intent, capability_request)
            if not preparation.accepted:
                if preparation.clarification_fields:
                    clarification = compose_clarification(
                        task_id=command.task_id,
                        fields=preparation.clarification_fields,
                        route=command.route,
                    )
                    self._completion.complete_clarification(
                        request=command.request,
                        task_id=command.task_id,
                        route=command.route,
                        result=clarification,
                        operation_lease=command.operation_lease,
                        fields=preparation.clarification_fields,
                    )
                    return CapabilityExecutionOutcome(
                        clarification, command.context_manifest
                    )
                return self._blocked(
                    command,
                    preparation.reason_code,
                    OutcomeCode.BLOCKED,
                    error_class=ErrorClass.INPUT_INVALID,
                    event_type="capability.input_rejected",
                )

            action_proposal = self._propose_action(
                handler, capability_request, descriptor.declared_action
            )
            action_request = ActionAuthorizationRequest(
                task_id=command.task_id,
                capability_id=descriptor.capability_id,
                operation=capability_request.operation,
                proposal=action_proposal,
                declared_action=descriptor.declared_action,
                confirmation_id=command.request.action_confirmation_id,
                now=self._clock.now(),
            )
            action_assessment = self._action_authorization.assess(
                action_proposal,
                declared_action=descriptor.declared_action,
            )
            if not action_assessment.allowed:
                return self._blocked(
                    command,
                    action_assessment.reason_code,
                    OutcomeCode.BLOCKED,
                    event_type="action.authorization_denied",
                    detail=self._action_detail(
                        action_assessment.proposal,
                        action_assessment.action_digest,
                        action_assessment.reason_code,
                    ),
                )
            if (
                action_assessment.confirmation_required
                and command.request.action_confirmation_id is None
            ):
                action_decision = self._action_authorization.authorize(action_request)
                if action_decision.confirmation_proposal is None:
                    return self._blocked(
                        command,
                        action_decision.reason_code,
                        OutcomeCode.BLOCKED,
                        event_type="action.authorization_denied",
                        detail=self._action_detail(
                            action_decision.proposal,
                            action_decision.action_digest,
                            action_decision.reason_code,
                        ),
                    )
                result = compose_action_confirmation(
                    task_id=command.task_id,
                    proposal=action_decision.confirmation_proposal,
                    route=command.route,
                )
                self._completion.complete_action_confirmation(
                    request=command.request,
                    task_id=command.task_id,
                    route=command.route,
                    result=result,
                    proposal=action_decision.confirmation_proposal,
                    operation_lease=command.operation_lease,
                )
                return CapabilityExecutionOutcome(
                    result=result,
                    manifest=command.context_manifest,
                    action_confirmation=action_decision.confirmation_proposal,
                )
            classification = self._privacy_policy.classify(command.context_text)
            authorization = self._cloud_authorization_policy.authorize(
                CloudAuthorizationRequest(
                    task_id=command.task_id,
                    payload=command.context_text,
                    classification=classification,
                    cloud_mode=command.request.cloud_mode,
                    destination=descriptor.destination,
                    model=descriptor.model,
                    capability_id=descriptor.capability_id,
                    purpose=descriptor.purpose or f"execute {descriptor.capability_id}",
                    consent=self._consent,
                    approval_id=command.request.approval_id,
                    max_cost=descriptor.max_cost_usd,
                    now=self._clock.now(),
                    capability_available=capability_status.available,
                    requires_external_boundary=descriptor.requires_external_boundary,
                )
            )
            if not authorization.allowed:
                proposal = authorization.consent_proposal
                if proposal is not None:
                    awaiting = TaskStatus.AWAITING_CONSENT
                    self._completion.emit(
                        request=command.request,
                        task_id=command.task_id,
                        route=command.route,
                        event_type="consent.requested",
                        status=awaiting,
                        error_class=ErrorClass.PERMISSION_DENIED,
                        detail=self._failure_detail(command, "exact consent required"),
                    )
                    self._completion.fail_operation(command.operation_lease)
                    self._completion.finish_task(command.task_id, awaiting)
                    return CapabilityExecutionOutcome(
                        result=compose_consent_required(
                            task_id=command.task_id,
                            proposal=proposal,
                            route=command.route,
                        ),
                        manifest=command.context_manifest,
                        consent_proposal=proposal,
                    )
                return self._blocked(
                    command,
                    authorization.reason_code,
                    OutcomeCode.BLOCKED,
                    event_type="capability.authorization_denied",
                )

            self._completion.emit(
                request=command.request,
                task_id=command.task_id,
                route=command.route,
                event_type="authorization.approved",
                status=command.status,
                detail=(
                    f"capability={descriptor.capability_id} "
                    f"destination={descriptor.destination} "
                    f"classification={classification.classification.value} "
                    f"payload_digest={authorization.payload_digest[:16]} "
                    f"reason={authorization.reason_code}"
                ),
            )
            capability_request = CapabilityRequest(
                task=capability_request.task,
                route_request=capability_request.route_request,
                context_text=capability_request.context_text,
                context_manifest=capability_request.context_manifest,
                task_id=capability_request.task_id,
                execution_at=capability_request.execution_at,
                request_guardrails=capability_request.request_guardrails,
                cancellation=capability_request.cancellation,
                operation=capability_request.operation,
                intent=capability_request.intent,
                classification=classification,
            )

            action_decision = self._action_authorization.authorize(action_request)
            if not action_decision.allowed:
                return self._blocked(
                    command,
                    action_decision.reason_code,
                    OutcomeCode.BLOCKED,
                    event_type="action.authorization_denied",
                    detail=self._action_detail(
                        action_decision.proposal,
                        action_decision.action_digest,
                        action_decision.reason_code,
                    ),
                )
            if action_assessment.confirmation_required:
                self._completion.emit(
                    request=command.request,
                    task_id=command.task_id,
                    route=command.route,
                    event_type="action.authorization_approved",
                    status=command.status,
                    detail=(
                        f"category={action_decision.proposal.category.value} "
                        f"target={safe_action_target_reference(action_decision.proposal.target)} "
                        f"digest={action_decision.action_digest[:16]} "
                        f"reason={action_decision.reason_code}"
                    ),
                )

            command.cancellation.raise_if_cancelled()
            execution_started = True
            execution = handler.execute(capability_request)
            if not isinstance(execution, CapabilityExecution):
                raise ConfigInvalidError("capability returned an invalid execution envelope")
            result = execution.result
            if result.task_id != command.task_id:
                raise ConfigInvalidError("capability returned a mismatched task id")
            generated_result = result
            self._completion.complete_capability(
                request=command.request,
                task_id=command.task_id,
                route=command.route,
                route_decision=command.route_decision,
                descriptor=descriptor,
                result=result,
                started=command.started,
                request_guardrails=command.request_guardrails,
                operation_lease=command.operation_lease,
            )
            return CapabilityExecutionOutcome(
                result=result,
                manifest=command.context_manifest,
                consent_proposal=execution.consent_proposal,
            )
        except StorageFailureError as exc:
            self._completion.best_effort_fail_operation(
                command.operation_lease,
                possible_duplicate=execution_started,
            )
            failed_status = (
                TaskStatus.PARTIAL if generated_result is not None else TaskStatus.FAILED
            )
            self._completion.best_effort_finish_task(command.task_id, failed_status)
            if generated_result is not None:
                result = compose_partial(
                    task_id=command.task_id,
                    reason=exc.summary,
                    route=command.route,
                    answer=generated_result.answer,
                    partial_work=(
                        "capability output was generated but durable completion was incomplete",
                    ),
                )
            else:
                result = compose_failed(
                    task_id=command.task_id,
                    reason=exc.summary,
                    route=command.route,
                )
            return CapabilityExecutionOutcome(result, command.context_manifest)
        except CancelledError as exc:
            self._completion.fail_operation(
                command.operation_lease,
                possible_duplicate=execution_started,
            )
            cancelled = TaskStatus.CANCELLED
            self._completion.emit(
                request=command.request,
                task_id=command.task_id,
                route=command.route,
                event_type="capability.cancelled",
                status=cancelled,
                error_class=exc.error_class,
                detail=self._failure_detail(command, exc.summary),
            )
            self._completion.finish_task(command.task_id, cancelled)
            return CapabilityExecutionOutcome(
                compose_cancelled(
                    task_id=command.task_id,
                    partial_work=exc.partial_work,
                    route=command.route,
                ),
                command.context_manifest,
            )
        except EllyError as exc:
            self._completion.fail_operation(
                command.operation_lease,
                possible_duplicate=execution_started,
            )
            failed = TaskStatus.FAILED
            self._completion.emit(
                request=command.request,
                task_id=command.task_id,
                route=command.route,
                event_type="capability.failed",
                status=failed,
                error_class=exc.error_class,
                detail=self._failure_detail(command, exc.summary),
            )
            self._completion.finish_task(command.task_id, failed)
            return CapabilityExecutionOutcome(
                compose_failed(
                    task_id=command.task_id,
                    reason=exc.summary,
                    route=command.route,
                ),
                command.context_manifest,
            )

    def _blocked(
        self,
        command: CapabilityExecutionCommand,
        reason: str,
        outcome_code: OutcomeCode,
        *,
        error_class: ErrorClass = ErrorClass.PERMISSION_DENIED,
        event_type: str = "capability.unavailable",
        detail: str | None = None,
    ) -> CapabilityExecutionOutcome:
        blocked = TaskStatus.BLOCKED
        self._completion.emit(
            request=command.request,
            task_id=command.task_id,
            route=command.route,
            event_type=event_type,
            status=blocked,
            error_class=error_class,
            detail=detail or self._failure_detail(command, reason),
        )
        self._completion.fail_operation(command.operation_lease)
        self._completion.finish_task(command.task_id, blocked)
        return CapabilityExecutionOutcome(
            compose_blocked(
                task_id=command.task_id,
                reason=reason,
                route=command.route,
                outcome_code=outcome_code,
            ),
            command.context_manifest,
        )

    def _failure_detail(self, command: CapabilityExecutionCommand, summary: str) -> str:
        return (
            f"{summary} duration_ms={int((time.monotonic() - command.started) * 1000)} "
            f"{self._completion.guardrail_detail(command.request_guardrails)}"
        )

    @staticmethod
    def _action_detail(
        proposal: ActionProposal, digest: str, reason: str
    ) -> str:
        return (
            f"category={proposal.category.value} "
            f"target={safe_action_target_reference(proposal.target)} "
            f"digest={digest[:16]} reason={reason}"
        )

    @staticmethod
    def _propose_action(
        handler: object,
        request: CapabilityRequest,
        declared_action: ActionProposal,
    ) -> ActionProposal:
        proposer = getattr(handler, "propose_action", None)
        proposal = proposer(request) if callable(proposer) else declared_action
        if not isinstance(proposal, ActionProposal):
            raise ConfigInvalidError("capability returned an invalid action proposal")
        return proposal
