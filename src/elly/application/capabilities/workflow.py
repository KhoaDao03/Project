"""Application workflow for already-selected optional capabilities."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from ...domain.enums import (
    ErrorClass,
    IntentAmbiguity,
    IntentEntitySource,
    OutcomeCode,
    Route,
    RouteReasonCode,
    TaskStatus,
)
from ...domain.errors import CancelledError, ConfigInvalidError, EllyError, StorageFailureError
from ...domain.models import (
    ActionConfirmationProposal,
    ActionProposal,
    CapabilityIntent,
    ContextManifest,
    ConversationOutcome,
    IntentEntity,
    OperationLease,
    RouteDecision,
    RouteRequest,
    TaskRequest,
    TaskResult,
)
from ...guardrails.controller import GuardrailController
from ...planning.contracts import ExecutionPlan, PlanStep, StepKind
from ...ports.clock import ClockPort
from ...privacy import ConsentProposal, ConsentWorkflow, PrivacyPolicy
from ..authorization.actions import (
    ActionAuthorizationRequest,
    ActionAuthorizationService,
    safe_action_target_reference,
)
from ..authorization.consent import CloudAuthorizationPolicy, CloudAuthorizationRequest
from ..completion import CompletionService
from ..response.composer import (
    compose_action_confirmation,
    compose_blocked,
    compose_cancelled,
    compose_clarification,
    compose_consent_required,
    compose_failed,
    compose_partial,
)
from ..response.pipeline import ResponseCompositionService
from ..results.step import (
    StepResultEnvelope,
    normalize_step_result,
)
from ..routing.compatibility import enrich_task_result, is_local_route
from ..routing.contracts import TaskIntent
from ..task_execution.cancellation import CancellationToken
from .registry import (
    CapabilityDescriptor,
    CapabilityExecution,
    CapabilityRegistry,
    CapabilityRequest,
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
    objective: str = ""
    persist_completion: bool = True
    before_dispatch: Callable[[], None] | None = None
    plan_id: str = ""
    step_id: str = ""
    require_typed_result: bool = False
    require_action_receipt: bool = False


@dataclass(frozen=True, slots=True)
class CapabilityExecutionOutcome:
    """Normalized result returned by optional-capability execution."""

    result: TaskResult
    manifest: ContextManifest
    consent_proposal: ConsentProposal | None = None
    action_confirmation: ActionConfirmationProposal | None = None
    route_decision: RouteDecision | None = None
    result_envelope: StepResultEnvelope | None = None
    response_composed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.response_composed, bool):
            raise ConfigInvalidError("capability response_composed marker is invalid")
        if self.route_decision is not None:
            object.__setattr__(
                self,
                "result",
                enrich_task_result(self.result, self.route_decision),
            )

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
        response_pipeline: ResponseCompositionService | None = None,
    ) -> None:
        self._clock = clock
        self._capability_registry = capability_registry
        self._completion = completion
        self._consent = consent
        self._privacy_policy = privacy_policy or PrivacyPolicy()
        self._cloud_authorization_policy = cloud_authorization_policy or CloudAuthorizationPolicy()
        self._action_authorization = action_authorization or ActionAuthorizationService()
        if response_pipeline is not None and not isinstance(
            response_pipeline, ResponseCompositionService
        ):
            raise ConfigInvalidError("response pipeline is invalid")
        self._response_pipeline = response_pipeline

    def execute(self, command: CapabilityExecutionCommand) -> CapabilityExecutionOutcome:
        """Execute one selected optional capability behind the runtime boundary."""
        if is_local_route(command.route):
            raise ConfigInvalidError("local conversation must not use capability workflow")

        capability_id = command.route_decision.capability_id
        handler = self._capability_registry.get(capability_id or "")
        if handler is None:
            reason = "requested optional capability is not registered"
            return self._blocked(command, reason, OutcomeCode.UNAVAILABLE)

        capability_status = handler.status()
        if not command.route_decision.available or not capability_status.available:
            reason = (
                capability_status.reason_code
                or command.route_decision.diagnostic
                or "capability unavailable"
            )
            return self._blocked(command, reason, OutcomeCode.UNAVAILABLE)

        descriptor = handler.descriptor
        capability_intent = self._execution_intent(
            command,
            capability_id=capability_id,
            descriptor=descriptor,
        )
        capability_request = CapabilityRequest(
            task=command.request,
            route_request=command.route_request,
            context_text=command.context_text,
            context_manifest=command.context_manifest,
            task_id=command.task_id,
            execution_at=self._clock.now(),
            request_guardrails=command.request_guardrails,
            cancellation=command.cancellation,
            operation=capability_intent.operation,
            intent=capability_intent,
            objective=command.objective,
            plan_id=command.plan_id,
            step_id=command.step_id,
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

        if (
            command.route is not Route.REGISTERED_CAPABILITY
            and command.route not in descriptor.routes
        ):
            if command.persist_completion:
                self._completion.fail_operation(command.operation_lease)
                self._completion.finish_task(command.task_id, TaskStatus.FAILED)
            return CapabilityExecutionOutcome(
                result=compose_failed(
                    task_id=command.task_id,
                    reason="registered capability does not declare the selected route",
                    route=command.route,
                ),
                manifest=command.context_manifest,
                route_decision=command.route_decision,
            )

        execution_started = False
        generated_result: TaskResult | None = None
        try:
            intent = capability_intent
            preparation = handler.prepare(intent, capability_request)
            if not preparation.accepted:
                if preparation.clarification_fields:
                    clarification = compose_clarification(
                        task_id=command.task_id,
                        fields=preparation.clarification_fields,
                        route=command.route,
                    )
                    if command.persist_completion:
                        self._completion.complete_clarification(
                            request=command.request,
                            task_id=command.task_id,
                            route=command.route,
                            route_decision=command.route_decision,
                            result=clarification,
                            operation_lease=command.operation_lease,
                            fields=preparation.clarification_fields,
                        )
                    return CapabilityExecutionOutcome(
                        clarification,
                        command.context_manifest,
                        route_decision=command.route_decision,
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
                plan_id=command.plan_id,
                step_id=command.step_id,
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
                if command.persist_completion:
                    self._completion.complete_action_confirmation(
                        request=command.request,
                        task_id=command.task_id,
                        route=command.route,
                        route_decision=command.route_decision,
                        result=result,
                        proposal=action_decision.confirmation_proposal,
                        operation_lease=command.operation_lease,
                    )
                return CapabilityExecutionOutcome(
                    result=result,
                    manifest=command.context_manifest,
                    action_confirmation=action_decision.confirmation_proposal,
                    route_decision=command.route_decision,
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
                    plan_id=command.plan_id,
                    step_id=command.step_id,
                    operation=capability_request.operation,
                )
            )
            if not authorization.allowed:
                proposal = authorization.consent_proposal
                if proposal is not None:
                    awaiting = TaskStatus.AWAITING_CONSENT
                    consent_result = compose_consent_required(
                        task_id=command.task_id,
                        proposal=proposal,
                        route=command.route,
                    )
                    if command.persist_completion:
                        self._completion.emit(
                            request=command.request,
                            task_id=command.task_id,
                            route=command.route,
                            route_decision=command.route_decision,
                            event_type="consent.requested",
                            status=awaiting,
                            error_class=ErrorClass.PERMISSION_DENIED,
                            detail=self._failure_detail(command, "exact consent required"),
                        )
                        self._completion.fail_operation(command.operation_lease)
                        self._completion.finish_task(command.task_id, awaiting)
                        consent_result = self._completion.persist_result(
                            consent_result,
                            command.route_decision,
                        )
                    return CapabilityExecutionOutcome(
                        result=consent_result,
                        manifest=command.context_manifest,
                        consent_proposal=proposal,
                        route_decision=command.route_decision,
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
                route_decision=command.route_decision,
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
                objective=capability_request.objective,
                plan_id=capability_request.plan_id,
                step_id=capability_request.step_id,
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
                    route_decision=command.route_decision,
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
            if command.before_dispatch is not None:
                command.before_dispatch()
            execution_started = True
            execution = handler.execute(capability_request)
            if not isinstance(execution, CapabilityExecution):
                raise ConfigInvalidError("capability returned an invalid execution envelope")
            candidate_result = execution.result_envelope or execution.result
            result_envelope = normalize_step_result(
                candidate_result,
                plan_id=command.plan_id or "direct-execution",
                task_id=command.task_id,
                step_id=command.step_id or "direct-step",
                capability_id=descriptor.capability_id,
                operation_id=capability_request.operation,
                supported_schema_versions=frozenset(descriptor.output_schema_versions),
                expected_action_digest=action_decision.action_digest,
                require_action_receipt=False,
            )
            if execution.action_receipt is not None and result_envelope.action_receipt is None:
                result_envelope = replace(result_envelope, action_receipt=execution.action_receipt)
            if command.require_action_receipt and action_decision.proposal.is_consequential:
                result_envelope = normalize_step_result(
                    result_envelope,
                    plan_id=command.plan_id or "direct-execution",
                    task_id=command.task_id,
                    step_id=command.step_id or "direct-step",
                    capability_id=descriptor.capability_id,
                    operation_id=capability_request.operation,
                    supported_schema_versions=frozenset(descriptor.output_schema_versions),
                    expected_action_digest=action_decision.action_digest,
                    require_action_receipt=True,
                )
            result = result_envelope.to_task_result()
            if self._response_pipeline is not None and not command.plan_id and not command.step_id:
                immutable_records: dict[str, str] = {}
                receipt = result_envelope.action_receipt
                if receipt is not None:
                    record_ref = f"record-{receipt.receipt_id}"
                    provider_reference = (
                        f"; provider_reference={receipt.provider_reference}"
                        if receipt.provider_reference
                        else ""
                    )
                    immutable_records[record_ref] = (
                        f"{receipt.receipt_id}: succeeded; capability={receipt.capability_id}; "
                        f"operation={receipt.operation_id}; digest={receipt.action_digest}"
                        f"{provider_reference}"
                    )
                result = self._response_pipeline.compose_task_result(
                    result,
                    request=command.request,
                    approved_context=command.context_text,
                    immutable_records=immutable_records,
                    cancellation=command.cancellation,
                ).result
            generated_result = result
            if command.persist_completion:
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
                route_decision=command.route_decision,
                result_envelope=(result_envelope if command.require_typed_result else None),
                response_composed=(
                    self._response_pipeline is not None
                    and not command.plan_id
                    and not command.step_id
                ),
            )
        except StorageFailureError as exc:
            if command.persist_completion:
                self._completion.best_effort_fail_operation(
                    command.operation_lease,
                    possible_duplicate=execution_started,
                )
            failed_status = (
                TaskStatus.PARTIAL if generated_result is not None else TaskStatus.FAILED
            )
            if command.persist_completion:
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
            return CapabilityExecutionOutcome(
                result, command.context_manifest, route_decision=command.route_decision
            )
        except CancelledError as exc:
            if command.persist_completion:
                self._completion.fail_operation(
                    command.operation_lease,
                    possible_duplicate=execution_started,
                )
            cancelled = TaskStatus.CANCELLED
            if command.persist_completion:
                self._completion.emit(
                    request=command.request,
                    task_id=command.task_id,
                    route=command.route,
                    route_decision=command.route_decision,
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
                route_decision=command.route_decision,
            )
        except EllyError as exc:
            if command.persist_completion:
                self._completion.fail_operation(
                    command.operation_lease,
                    possible_duplicate=execution_started,
                )
            failed = TaskStatus.FAILED
            if command.persist_completion:
                self._completion.emit(
                    request=command.request,
                    task_id=command.task_id,
                    route=command.route,
                    route_decision=command.route_decision,
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
                route_decision=command.route_decision,
            )
        except Exception:
            # Provider-native exceptions must stop at this application boundary;
            # their type and message are not safe result or UI contracts.
            if command.persist_completion:
                self._completion.fail_operation(
                    command.operation_lease,
                    possible_duplicate=execution_started,
                )
                self._completion.emit(
                    request=command.request,
                    task_id=command.task_id,
                    route=command.route,
                    route_decision=command.route_decision,
                    event_type="capability.failed",
                    status=TaskStatus.FAILED,
                    error_class=ErrorClass.PERMANENT_PROVIDER,
                    detail=self._failure_detail(command, "capability provider failed"),
                )
                self._completion.finish_task(command.task_id, TaskStatus.FAILED)
            return CapabilityExecutionOutcome(
                compose_failed(
                    task_id=command.task_id,
                    reason="capability provider failed",
                    route=command.route,
                ),
                command.context_manifest,
                route_decision=command.route_decision,
            )

    def execute_plan_step(
        self,
        *,
        plan: ExecutionPlan,
        step: PlanStep,
        request: TaskRequest,
        context_text: str,
        context_manifest: ContextManifest,
        cancellation: CancellationToken,
        request_guardrails: GuardrailController | None = None,
        operation_lease: OperationLease | None = None,
        before_dispatch: Callable[[], None] | None = None,
        started: float | None = None,
    ) -> CapabilityExecutionOutcome:
        """Execute one validated capability step through the existing policy.

        The plan path deliberately creates a synthetic, application-owned route
        decision from the already validated ``PlanStep``.  It does not accept a
        provider or handler from planner output.  ``persist_completion=False``
        leaves plan-level result/state persistence to ``TaskExecutionService``
        while all existing capability, privacy, consent, and action checks remain
        shared.
        """
        if not isinstance(plan, ExecutionPlan) or not isinstance(step, PlanStep):
            raise ConfigInvalidError("plan step execution requires validated plan contracts")
        if step.kind is not StepKind.CAPABILITY:
            raise ConfigInvalidError("capability workflow cannot execute an internal plan step")
        validated_step = next(
            (candidate for candidate in plan.steps if candidate.step_id == step.step_id),
            None,
        )
        if validated_step is None or any(
            getattr(validated_step, field) != getattr(step, field)
            for field in (
                "step_id",
                "kind",
                "capability_id",
                "operation_id",
                "objective",
                "objective_class",
                "perspective",
                "inputs",
                "dependencies",
                "output_type",
                "criticality",
                "verification",
                "timeout_seconds",
                "requires_external_access",
                "effect",
                "requires_consent",
            )
        ):
            raise ConfigInvalidError("plan step does not belong to the validated plan")
        subject = step.objective
        intent = CapabilityIntent(
            proposed_capability_id=step.capability_id,
            operation=step.operation_id,
            entities=(
                IntentEntity(
                    kind="subject",
                    value=subject,
                    source=IntentEntitySource.INFERRED,
                ),
            ),
            arguments={"subject": subject},
            confidence=1.0,
            ambiguity=IntentAmbiguity.CLEAR,
            rationale_code="VALIDATED_PLAN_STEP",
        )
        decision = RouteDecision(
            route=Route.REGISTERED_CAPABILITY,
            reason_code=RouteReasonCode.PROPOSAL_ACCEPTED,
            capability_id=step.capability_id,
            operation=step.operation_id,
            intent=intent,
        )
        command = CapabilityExecutionCommand(
            request=request,
            task_id=plan.task_id,
            status=TaskStatus.RUNNING,
            route=Route.REGISTERED_CAPABILITY,
            route_request=RouteRequest(
                request_id=request.request_id,
                text=request.text,
                contextual_text=context_text,
                cloud_mode=request.cloud_mode,
            ),
            route_decision=decision,
            context_text=context_text,
            context_manifest=context_manifest,
            cancellation=cancellation,
            request_guardrails=request_guardrails,
            operation_lease=operation_lease,
            started=started if started is not None else time.monotonic(),
            objective=step.objective,
            persist_completion=False,
            before_dispatch=before_dispatch,
            plan_id=plan.plan_id,
            step_id=step.step_id,
            require_typed_result=True,
            # Handlers without typed routing metadata are pre-V3 compatibility
            # adapters and never promised execution receipts. Their operation
            # lease and exact confirmation remain enforced. Retire this narrow
            # exception when those handlers migrate to routing descriptors.
            require_action_receipt=(
                getattr(
                    getattr(
                        self._capability_registry.get(step.capability_id),
                        "descriptor",
                        None,
                    ),
                    "routing",
                    None,
                )
                is not None
            ),
        )
        return self.execute(command)

    @staticmethod
    def _execution_intent(
        command: CapabilityExecutionCommand,
        *,
        capability_id: str | None,
        descriptor: CapabilityDescriptor,
    ) -> CapabilityIntent:
        """Project a validated catalog task into the capability handler contract."""
        if not capability_id or not descriptor.operations:
            raise ConfigInvalidError("capability intent is missing")
        selected = command.route_decision.intent
        if isinstance(selected, CapabilityIntent):
            return selected
        if isinstance(selected, TaskIntent):
            selection = command.route_decision.selection
            return CapabilityIntent(
                proposed_capability_id=capability_id,
                operation=(
                    command.route_decision.operation
                    or (selection.operation_id if selection is not None else "")
                    or descriptor.operations[0]
                ),
                entities=(
                    selection.entities
                    if selection is not None and selection.entities
                    else selected.entities
                ),
                arguments=(
                    selection.arguments
                    if selection is not None and selection.arguments
                    else selected.arguments
                ),
                confidence=selected.confidence,
                ambiguity=IntentAmbiguity.CLEAR,
                rationale_code="CATALOG_SELECTION",
            )
        return CapabilityIntent(
            proposed_capability_id=capability_id,
            operation=command.route_decision.operation or descriptor.operations[0],
            arguments={"subject": command.context_text},
            confidence=1.0,
            ambiguity=IntentAmbiguity.CLEAR,
            rationale_code="LEGACY_ROUTE_DECISION",
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
        blocked_result = compose_blocked(
            task_id=command.task_id,
            reason=reason,
            route=command.route,
            outcome_code=outcome_code,
        )
        if command.persist_completion:
            self._completion.emit(
                request=command.request,
                task_id=command.task_id,
                route=command.route,
                route_decision=command.route_decision,
                event_type=event_type,
                status=blocked,
                error_class=error_class,
                detail=detail or self._failure_detail(command, reason),
            )
            self._completion.fail_operation(command.operation_lease)
            self._completion.finish_task(command.task_id, blocked)
            blocked_result = self._completion.persist_result(
                blocked_result,
                command.route_decision,
            )
        return CapabilityExecutionOutcome(
            blocked_result,
            command.context_manifest,
            route_decision=command.route_decision,
        )

    def _failure_detail(self, command: CapabilityExecutionCommand, summary: str) -> str:
        return (
            f"{summary} duration_ms={int((time.monotonic() - command.started) * 1000)} "
            f"{self._completion.guardrail_detail(command.request_guardrails)}"
        )

    @staticmethod
    def _action_detail(proposal: ActionProposal, digest: str, reason: str) -> str:
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
