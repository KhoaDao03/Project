"""Contracts for decomposed plan execution.

The request/result objects live here so the execution service, scheduler,
step runner, and finalizer share one stable contract without importing the
legacy compatibility module.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from elly.application.execution import CancellationToken
from elly.application.plan_results import DisagreementRecord, PlanAggregation
from elly.application.step_results import StepResultEnvelope
from elly.domain.errors import InputInvalidError
from elly.domain.models import (
    ActionConfirmationProposal,
    ContextManifest,
    TaskRequest,
    TaskResult,
)
from elly.guardrails.controller import GuardrailController
from elly.planning.contracts import ExecutionPlan, PlanStatus, StepState
from elly.privacy import ConsentProposal


@dataclass(frozen=True, slots=True)
class PlanExecutionRequest:
    """Request-scoped, already-approved context supplied to a plan run."""

    request: TaskRequest
    context_text: str
    context_manifest: ContextManifest
    local_context_text: str = ""
    cancellation: CancellationToken | None = None
    request_guardrails: GuardrailController | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.request, TaskRequest):
            raise InputInvalidError("plan execution request is invalid")
        if not isinstance(self.context_text, str) or not self.context_text.strip():
            raise InputInvalidError("plan execution context must be non-empty")
        if not isinstance(self.context_manifest, ContextManifest):
            raise InputInvalidError("plan execution context manifest is invalid")
        if not isinstance(self.local_context_text, str):
            raise InputInvalidError("plan execution local context must be text")
        if self.cancellation is not None and not isinstance(self.cancellation, CancellationToken):
            raise InputInvalidError("plan execution cancellation token is invalid")


@dataclass(frozen=True, slots=True)
class PlanExecutionResult:
    """Safe outcome of one bounded plan execution."""

    plan: ExecutionPlan
    step_results: Mapping[str, TaskResult]
    reason_code: str = ""
    step_envelopes: Mapping[str, StepResultEnvelope] = field(default_factory=dict)
    aggregation: PlanAggregation | None = None
    final_result: TaskResult | None = None
    consent_proposal: ConsentProposal | None = None
    action_confirmation: ActionConfirmationProposal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.plan, ExecutionPlan):
            raise InputInvalidError("plan execution result plan is invalid")
        if not isinstance(self.step_results, Mapping):
            raise InputInvalidError("plan execution step results must be a mapping")
        normalized = dict(self.step_results)
        if any(
            not isinstance(step_id, str) or not isinstance(result, TaskResult)
            for step_id, result in normalized.items()
        ):
            raise InputInvalidError("plan execution results are invalid")
        object.__setattr__(self, "step_results", MappingProxyType(normalized))
        envelopes = dict(self.step_envelopes)
        if any(
            not isinstance(step_id, str) or not isinstance(envelope, StepResultEnvelope)
            for step_id, envelope in envelopes.items()
        ):
            raise InputInvalidError("plan execution result envelopes are invalid")
        object.__setattr__(self, "step_envelopes", MappingProxyType(envelopes))
        if self.aggregation is not None:
            if not isinstance(self.aggregation, PlanAggregation):
                raise InputInvalidError("plan execution aggregation is invalid")
            if self.aggregation.plan.plan_id != self.plan.plan_id:
                raise InputInvalidError("plan execution aggregation identity is invalid")
        if self.final_result is not None:
            if not isinstance(self.final_result, TaskResult):
                raise InputInvalidError("plan execution final result is invalid")
            if self.final_result.task_id != self.plan.task_id:
                raise InputInvalidError("plan execution final result identity is invalid")
        if self.consent_proposal is not None and not isinstance(
            self.consent_proposal, ConsentProposal
        ):
            raise InputInvalidError("plan execution consent proposal is invalid")
        if self.action_confirmation is not None and not isinstance(
            self.action_confirmation, ActionConfirmationProposal
        ):
            raise InputInvalidError("plan execution action confirmation is invalid")

    @property
    def status(self) -> PlanStatus:
        return self.plan.status

    @property
    def step_states(self) -> Mapping[str, StepState]:
        return MappingProxyType({step.step_id: step.state for step in self.plan.steps})

    @property
    def results(self) -> Mapping[str, TaskResult]:
        """Compatibility alias for callers that use the shorter result name."""

        return self.step_results

    @property
    def envelopes(self) -> Mapping[str, StepResultEnvelope]:
        """Typed result envelopes available to downstream plan consumers."""

        return self.step_envelopes

    @property
    def plan_result(self) -> PlanAggregation | None:
        """Typed aggregate result, if this execution reached aggregation."""

        return self.aggregation

    @property
    def result(self) -> TaskResult | None:
        """Final user-facing result, retained as an additive convenience."""

        return self.final_result

    @property
    def disagreements(self) -> tuple[DisagreementRecord, ...]:
        """Explicit specialist disagreements, if aggregation was completed."""

        return self.aggregation.disagreements if self.aggregation is not None else ()


PlanRunResult = PlanExecutionResult


