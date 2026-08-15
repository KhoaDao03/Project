"""Adapters from existing workflows to the optional capability contract."""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.enums import EpistemicStatus, HealthState, Route
from ..domain.errors import PermissionDeniedError
from ..domain.models import ActionProposal, CapabilityIntent, ProvenanceReference
from ..specialists.contracts import SpecialistTask
from ..specialists.manifest import SpecialistManifest
from .capabilities import (
    CapabilityAvailability,
    CapabilityDescriptor,
    CapabilityExecution,
    CapabilityMatch,
    CapabilityPreparation,
    CapabilityRequest,
    CapabilityStatus,
)
from .research import ResearchPipeline
from .response_composer import compose_research, compose_specialist
from .specialist_policy import SpecialistPolicyRequest
from .specialists import SpecialistWorkflow


@dataclass(frozen=True, slots=True)
class ResearchCapabilityHandler:
    """Optional web-research handler backed by the existing typed pipeline."""

    pipeline: ResearchPipeline | None
    provider_id: str = "openai_web_search"
    model_id: str = ""
    max_cost_usd: float = 0.0

    @property
    def descriptor(self) -> CapabilityDescriptor:
        return CapabilityDescriptor(
            capability_id="web_research",
            description="Research current public information with validated sources",
            routes=(Route.WEB_RESEARCH,),
            request_schema="research-request-v1",
            operations=("research.search",),
            requires_external_boundary=True,
            requires_consent=True,
            destination=self.provider_id,
            model=self.model_id,
            purpose="perform hosted web research",
            max_cost_usd=self.max_cost_usd,
        )

    def status(self) -> CapabilityStatus:
        if self.pipeline is None:
            return CapabilityStatus(CapabilityAvailability.UNAVAILABLE, "NOT_CONFIGURED")
        health = self.pipeline.provider.health()
        if health.state in {HealthState.DISABLED, HealthState.UNAVAILABLE}:
            return CapabilityStatus(
                CapabilityAvailability.UNAVAILABLE,
                f"PROVIDER_{health.state.value.upper()}",
            )
        return CapabilityStatus(CapabilityAvailability.AVAILABLE)

    def can_handle(self, request: CapabilityRequest) -> CapabilityMatch:
        accepted = request.route_request.contextual_text is not None or request.route_request.text.strip() != ""
        return CapabilityMatch(accepted, "RESEARCH_REQUEST" if accepted else "EMPTY_REQUEST")

    def prepare(
        self, intent: CapabilityIntent, request: CapabilityRequest
    ) -> CapabilityPreparation:
        if intent.proposed_capability_id != self.descriptor.capability_id:
            return CapabilityPreparation(False, "CAPABILITY_ID_MISMATCH")
        if intent.operation != "research.search":
            return CapabilityPreparation(False, "OPERATION_NOT_SUPPORTED")
        if not intent.arguments.get("subject"):
            return CapabilityPreparation(
                False, "RESEARCH_QUERY_REQUIRED", ("subject",)
            )
        return CapabilityPreparation(True, "RESEARCH_INPUT_ACCEPTED")

    def propose_action(self, _request: CapabilityRequest) -> ActionProposal:
        """Research is read-only; it declares no state-changing effect."""
        return self.descriptor.declared_action

    def execute(self, request: CapabilityRequest) -> CapabilityExecution:
        if self.pipeline is None:
            raise PermissionDeniedError("web research capability is unavailable")
        execution = self.pipeline.execute(
            request.context_text,
            request_guardrails=request.request_guardrails,
            cancellation=request.cancellation,
        )
        result = compose_research(
            task_id=request.task_id,
            answer=execution.answer,
            citations=tuple(item.canonical_url or item.url for item in execution.evidence),
            claims=execution.claims,
            epistemic=execution.epistemic,
            claim_supports=execution.claim_supports,
            provenance=tuple(
                ProvenanceReference("evidence", item.evidence_id, item.retrieved_at)
                for item in execution.evidence
            ),
        )
        return CapabilityExecution(result=result, manifest=request.context_manifest)


@dataclass(frozen=True, slots=True)
class SpecialistCapabilityHandler:
    """Optional specialist handler; manifest policy remains capability-specific."""

    capability_id: str
    route: Route
    manifest: SpecialistManifest | None
    workflow: SpecialistWorkflow | None

    @property
    def descriptor(self) -> CapabilityDescriptor:
        return CapabilityDescriptor(
            capability_id=self.capability_id,
            description=f"{self.capability_id} specialist capability",
            routes=(self.route,),
            request_schema="specialist-task-v1",
            operations=("specialist.analyze",),
            requires_external_boundary=True,
            requires_consent=True,
            destination=self.workflow.provider_name if self.workflow is not None else "",
            model=self.manifest.provider_model if self.manifest is not None else "",
            purpose=f"execute {self.capability_id} specialist",
            max_cost_usd=self.workflow.consent_max_cost_usd if self.workflow is not None else 0.0,
        )

    def status(self) -> CapabilityStatus:
        if self.manifest is None or self.workflow is None:
            return CapabilityStatus(CapabilityAvailability.UNAVAILABLE, "NOT_CONFIGURED")
        if not self.manifest.enabled:
            return CapabilityStatus(CapabilityAvailability.UNAVAILABLE, "DISABLED")
        health = self.workflow.provider.health()
        if health.state in {HealthState.DISABLED, HealthState.UNAVAILABLE}:
            return CapabilityStatus(
                CapabilityAvailability.UNAVAILABLE,
                f"PROVIDER_{health.state.value.upper()}",
            )
        return CapabilityStatus(CapabilityAvailability.AVAILABLE)

    def can_handle(self, request: CapabilityRequest) -> CapabilityMatch:
        if request.route_request.contextual_text is None and not request.context_text.strip():
            return CapabilityMatch(False, "EMPTY_REQUEST")
        return CapabilityMatch(True, "SPECIALIST_REQUEST")

    def prepare(
        self, intent: CapabilityIntent, request: CapabilityRequest
    ) -> CapabilityPreparation:
        if intent.proposed_capability_id != self.descriptor.capability_id:
            return CapabilityPreparation(False, "CAPABILITY_ID_MISMATCH")
        if intent.operation != "specialist.analyze":
            return CapabilityPreparation(False, "OPERATION_NOT_SUPPORTED")
        if not intent.arguments.get("subject"):
            return CapabilityPreparation(
                False, "SPECIALIST_SUBJECT_REQUIRED", ("subject",)
            )
        return CapabilityPreparation(True, "SPECIALIST_INPUT_ACCEPTED")

    def propose_action(self, _request: CapabilityRequest) -> ActionProposal:
        """Specialist analysis is read-only; recommendations are data, not actions."""
        return self.descriptor.declared_action

    def execute(self, request: CapabilityRequest) -> CapabilityExecution:
        if self.manifest is None or self.workflow is None:
            raise PermissionDeniedError(f"{self.capability_id} capability is unavailable")
        if request.classification is None:
            raise PermissionDeniedError(
                "specialist execution requires centralized cloud classification"
            )
        specialist_task = SpecialistTask(
            task_id=request.task_id,
            specialist_id=self.manifest.id,
            goal=request.task.text,
            context=request.context_text,
            privacy_class=request.classification.classification.value,
            approval_id=request.task.approval_id,
        )
        execution = self.workflow.execute(
            request=SpecialistPolicyRequest(
                task=specialist_task,
                manifest=self.manifest,
            ),
            request_guardrails=request.request_guardrails,
            cancellation=request.cancellation,
        )
        specialist_result = execution.result
        provider_epistemic = (
            EpistemicStatus(specialist_result.status)
            if specialist_result.status != "partial"
            else EpistemicStatus.INFERRED
        )
        # Specialist URLs and free-form evidence strings are discovery metadata,
        # not application-validated claim support. Never upgrade them to known.
        epistemic = (
            EpistemicStatus.INFERRED
            if provider_epistemic is EpistemicStatus.KNOWN
            else provider_epistemic
        )
        uncertainties = specialist_result.uncertainties
        if provider_epistemic is EpistemicStatus.KNOWN:
            uncertainties += (
                "Provider asserted this as known, but no application-validated claim evidence was supplied.",
            )
        result = compose_specialist(
            task_id=request.task_id,
            answer=specialist_result.answer,
            route=self.route,
            epistemic=epistemic,
            assumptions=specialist_result.assumptions,
            uncertainties=uncertainties,
            sources=(),
            partial=specialist_result.truncated or specialist_result.status == "partial",
            provenance=(),
        )
        return CapabilityExecution(
            result=result,
            manifest=request.context_manifest,
        )
