"""Registry-backed local conversation/reasoning capability."""

from __future__ import annotations

from dataclasses import dataclass

from ...domain.enums import (
    ActionCategory,
    EpistemicStatus,
    HealthState,
    OutcomeCode,
    Route,
    TaskStatus,
    ValidationStatus,
)
from ...domain.errors import CancelledError, EllyError
from ...domain.models import ActionProposal, CapabilityIntent, ProvenanceReference
from ..response.composer import compose_blocked, compose_success
from ..results.step import RESULT_SCHEMA_VERSION, StepResultEnvelope, StepUsage
from ..routing.contracts import (
    CapabilityAvailability,
    CapabilityKind,
    CapabilityRoutingDescriptor,
    OperationIntentContract,
)
from .local_conversation import LocalConversationUseCase
from .registry import (
    CapabilityDescriptor,
    CapabilityExecution,
    CapabilityMatch,
    CapabilityPreparation,
    CapabilityRequest,
    CapabilityStatus,
)

LOCAL_CONVERSATION_CAPABILITY_ID = "local_conversation"
LOCAL_CONVERSATION_OPERATION_ID = "conversation.respond"

_LOCAL_OPERATIONS = (
    OperationIntentContract(
        operation_id=LOCAL_CONVERSATION_OPERATION_ID,
        description="Explain, discuss, or answer a timeless local conversation request",
        domains=("general", "conversation", "reasoning"),
        accepted_inputs=("text", "context", "task_result"),
        required_entities=(),
        output_type="task_result",
        effect=ActionCategory.NONE,
        specificity=10,
        examples=("Hello", "Explain dependency injection"),
        counterexamples=("Find current news", "Look up a live market price"),
    ),
)


@dataclass(frozen=True, slots=True)
class LocalConversationCapabilityHandler:
    """Execute one bounded local model turn behind the capability contract."""

    use_case: LocalConversationUseCase

    @property
    def descriptor(self) -> CapabilityDescriptor:
        return CapabilityDescriptor(
            capability_id=LOCAL_CONVERSATION_CAPABILITY_ID,
            description="Local conversation and general reasoning",
            routes=(Route.LOCAL_CONVERSATION,),
            request_schema="local-conversation-v1",
            operations=(LOCAL_CONVERSATION_OPERATION_ID,),
            declared_action=ActionProposal.none(),
            routing=CapabilityRoutingDescriptor(
                capability_id=LOCAL_CONVERSATION_CAPABILITY_ID,
                description="Local conversation and general reasoning",
                operations=_LOCAL_OPERATIONS,
                priority=1,
                kind=CapabilityKind.LOCAL,
            ),
        )

    def status(self) -> CapabilityStatus:
        health = self.use_case.generalist.health()
        if health.state in {HealthState.DISABLED, HealthState.UNAVAILABLE}:
            return CapabilityStatus(
                CapabilityAvailability.UNAVAILABLE,
                f"PROVIDER_{health.state.value.upper()}",
            )
        return CapabilityStatus(CapabilityAvailability.AVAILABLE)

    def can_handle(self, request: CapabilityRequest) -> CapabilityMatch:
        accepted = bool(request.context_text.strip())
        return CapabilityMatch(accepted, "LOCAL_REQUEST" if accepted else "EMPTY_REQUEST")

    def prepare(
        self,
        intent: CapabilityIntent,
        _request: CapabilityRequest,
    ) -> CapabilityPreparation:
        if intent.proposed_capability_id != LOCAL_CONVERSATION_CAPABILITY_ID:
            return CapabilityPreparation(False, "CAPABILITY_ID_MISMATCH")
        if intent.operation != LOCAL_CONVERSATION_OPERATION_ID:
            return CapabilityPreparation(False, "OPERATION_NOT_SUPPORTED")
        return CapabilityPreparation(True, "LOCAL_INPUT_ACCEPTED")

    def propose_action(self, _request: CapabilityRequest) -> ActionProposal:
        return ActionProposal.none()

    def execute(self, request: CapabilityRequest) -> CapabilityExecution:
        try:
            execution = self.use_case.execute(
                request.context_text,
                request_guardrails=request.request_guardrails,
                cancellation=request.cancellation,
            )
        except CancelledError:
            raise
        except EllyError as exc:
            return CapabilityExecution(
                compose_blocked(
                    task_id=request.task_id,
                    reason=exc.summary,
                    route=Route.LOCAL_CONVERSATION,
                ),
                request.context_manifest,
            )
        result = compose_success(
            task_id=request.task_id,
            answer=execution.text,
            route=Route.LOCAL_CONVERSATION,
            provenance=tuple(
                ProvenanceReference("message", str(message_id))
                for message_id in request.context_manifest.included_message_ids
            ),
        )
        response = execution.response
        envelope = StepResultEnvelope(
            schema_version=RESULT_SCHEMA_VERSION,
            plan_id=request.plan_id,
            task_id=request.task_id,
            step_id=request.step_id,
            capability_id=LOCAL_CONVERSATION_CAPABILITY_ID,
            operation_id=LOCAL_CONVERSATION_OPERATION_ID,
            status=TaskStatus.COMPLETED,
            summary=execution.text,
            answer=execution.text,
            provenance=result.provenance,
            usage=StepUsage(
                output_tokens=response.usage.output_tokens,
                latency_ms=response.usage.latency_ms,
                provider_calls=1,
            ),
            epistemic_status=EpistemicStatus.INFERRED,
            validation_status=ValidationStatus.VALIDATED,
            outcome_code=OutcomeCode.SUCCESS,
        )
        return CapabilityExecution(
            result,
            request.context_manifest,
            result_envelope=envelope,
        )


__all__ = [
    "LOCAL_CONVERSATION_CAPABILITY_ID",
    "LOCAL_CONVERSATION_OPERATION_ID",
    "LocalConversationCapabilityHandler",
]
