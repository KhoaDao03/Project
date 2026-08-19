"""M5 specialist authorization and execution workflow."""

from __future__ import annotations

from dataclasses import dataclass

from ...domain.errors import (
    CancelledError,
    EllyError,
    MalformedResultError,
    PermissionDeniedError,
)
from ...domain.models import ActionProposal
from ...guardrails.controller import GuardrailController
from ...ports.specialist import SpecialistProviderPort
from ...specialists.contracts import SpecialistResult, validate_result
from ..authorization.actions import (
    ActionAuthorizationPolicy,
    interpret_recommended_action,
)
from ..plan_management.specialist_policy import SpecialistExecutionPolicy, SpecialistPolicyRequest
from ..task_execution.cancellation import CancellationToken


@dataclass(frozen=True, slots=True)
class SpecialistExecution:
    result: SpecialistResult
    action_proposal: ActionProposal | None = None


class SpecialistWorkflow:
    """Execute a specialist request after specialist policy approval.

    Generic cloud mode, privacy classification, destination, and consent are
    deliberately absent here; ``CapabilityExecutionWorkflow`` evaluates the
    shared cloud policy before this workflow is called.

    Execution dependency
        provider: SpecialistProviderPort
    Resource constraints
        policy: SpecialistExecutionPolicy
        guardrails
        call_cost_usd
    Provider metadata
        provider_name
        consent_max_cost_usd
    """

    def __init__(
        self,
        *,
        provider: SpecialistProviderPort,
        policy: SpecialistExecutionPolicy | None = None,
        max_output_tokens: int = 2000,
        guardrails: GuardrailController | None = None,
        provider_name: str = "openai",
        call_cost_usd: float = 0.0,
        consent_max_cost_usd: float = 0.25,
        action_policy: ActionAuthorizationPolicy | None = None,
    ) -> None:
        self.provider = provider
        self.policy = policy or SpecialistExecutionPolicy(max_output_tokens=max_output_tokens)
        self.guardrails = guardrails
        self.provider_name = provider_name
        self.call_cost_usd = call_cost_usd
        # Retained as descriptor metadata until the capability descriptor gains
        # a separate cost field. Consent decisions themselves are centralized.
        self.consent_max_cost_usd = consent_max_cost_usd
        self.action_policy = action_policy or ActionAuthorizationPolicy()

    def execute(
        self,
        *,
        request: SpecialistPolicyRequest,
        request_guardrails: GuardrailController | None = None,
        cancellation: CancellationToken | None = None,
    ) -> SpecialistExecution:
        """Execute one specialist request after specialist policy approval."""
        decision = self.policy.evaluate(request)
        if not decision.allowed:
            raise PermissionDeniedError(decision.reason_code)
        task = request.task
        manifest = request.manifest
        if cancellation is not None:
            cancellation.raise_if_cancelled()

        def operation() -> SpecialistResult:
            return self.provider.execute(
                task,
                model=manifest.provider_model,
                prompt_version=manifest.prompt_version,
                output_limit=decision.output_limit,
            )

        try:
            if cancellation is not None:
                cancellation.register(self.provider.cancel)
            if request_guardrails is None and self.guardrails is not None:
                request_guardrails = self.guardrails.for_request()
            result = (
                request_guardrails.execute(
                    operation,
                    output_tokens=decision.output_limit,
                    cost_usd=self.call_cost_usd,
                )
                if request_guardrails
                else operation()
            )
        except ValueError as exc:
            raise MalformedResultError("specialist provider returned malformed output") from exc
        except EllyError as exc:
            if cancellation is not None and cancellation.cancelled:
                raise CancelledError("specialist execution cancelled") from exc
            raise
        finally:
            if cancellation is not None:
                cancellation.unregister(self.provider.cancel)
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        action_proposal = result.action_proposal
        if action_proposal is None and result.recommended_action:
            action_proposal = interpret_recommended_action(result.recommended_action)
        if action_proposal is not None:
            assessment = self.action_policy.evaluate(action_proposal)
            if not assessment.allowed:
                raise PermissionDeniedError(
                    f"specialist action proposal rejected: {assessment.reason_code}"
                )
        return SpecialistExecution(result=validate_result(result), action_proposal=action_proposal)
