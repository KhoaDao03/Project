"""Adapters from existing workflows to the optional capability contract."""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.enums import EpistemicStatus, HealthState, Route
from ..domain.errors import PermissionDeniedError
from ..domain.models import ActionProposal, CapabilityIntent, ProvenanceReference
from ..specialists.contracts import SpecialistTask
from ..specialists.manifest import SpecialistManifest
from .capabilities import (
    CapabilityDescriptor,
    CapabilityExecution,
    CapabilityMatch,
    CapabilityPreparation,
    CapabilityRequest,
    CapabilityStatus,
)
from .research import ResearchPipeline
from .response_composer import compose_research, compose_specialist
from .routing_contracts import (
    CapabilityAvailability,
    CapabilityKind,
    CapabilityRoutingDescriptor,
    FreshnessSupport,
    OperationIntentContract,
)
from .specialist_policy import SpecialistPolicyRequest
from .specialists import SpecialistWorkflow

_WEB_RESEARCH_OPERATIONS: tuple[OperationIntentContract, ...] = (
    # Kept first for callers that still submit the V2 operation name. It is a
    # compatibility alias; the catalog-facing operations below are the normal
    # Phase 4 selection surface.
    OperationIntentContract(
        operation_id="research.search",
        description="Legacy hosted research request compatibility",
        domains=("research",),
        accepted_inputs=("text", "context"),
        required_entities=("subject",),
        freshness=FreshnessSupport.CURRENT,
        specificity=40,
        counterexamples=("Use the research specialist",),
    ),
    OperationIntentContract(
        operation_id="public_information.search",
        description="Search and synthesize current public information",
        domains=("public_information", "research"),
        accepted_inputs=("text", "context"),
        required_entities=("subject",),
        freshness=FreshnessSupport.CURRENT,
        specificity=70,
        examples=("Find the latest public information about this topic",),
    ),
    OperationIntentContract(
        operation_id="news.current",
        description="Find and synthesize current news about a subject",
        domains=("news", "public_information"),
        accepted_inputs=("text", "context"),
        required_entities=("subject",),
        freshness=FreshnessSupport.CURRENT,
        specificity=85,
        examples=("What news is developing about this company?",),
    ),
    OperationIntentContract(
        operation_id="release.lookup",
        description="Look up a current software, product, or standards release",
        domains=("release", "public_information"),
        accepted_inputs=("text", "context"),
        required_entities=("subject",),
        freshness=FreshnessSupport.CURRENT,
        specificity=80,
        examples=("Look up the Python release",),
    ),
    OperationIntentContract(
        operation_id="market.quote",
        description="Find a current or live market quote or market-index level",
        domains=("finance", "market_data", "market_index", "public_information"),
        accepted_inputs=("text", "ticker"),
        required_entities=(),
        optional_entities=("ticker", "company", "security"),
        freshness=FreshnessSupport.LIVE,
        specificity=95,
        examples=(
            "What is AAPL trading at?",
            "What is the current gold price?",
            "What is the current S&P500 index?",
            "What is the current stock-market index level?",
        ),
    ),
)


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
            routes=(Route.REGISTERED_CAPABILITY,),
            request_schema="research-request-v1",
            operations=tuple(operation.operation_id for operation in _WEB_RESEARCH_OPERATIONS),
            requires_external_boundary=True,
            requires_consent=True,
            destination=self.provider_id,
            model=self.model_id,
            purpose="perform hosted web research",
            max_cost_usd=self.max_cost_usd,
            routing=CapabilityRoutingDescriptor(
                capability_id="web_research",
                description="Research current public information with validated sources",
                operations=_WEB_RESEARCH_OPERATIONS,
                kind=CapabilityKind.RESEARCH,
                requires_external_access=True,
                requires_consent=True,
            ),
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
        accepted = (
            request.route_request.contextual_text is not None
            or request.route_request.text.strip() != ""
        )
        return CapabilityMatch(accepted, "RESEARCH_REQUEST" if accepted else "EMPTY_REQUEST")

    def prepare(
        self, intent: CapabilityIntent, request: CapabilityRequest
    ) -> CapabilityPreparation:
        if intent.proposed_capability_id != self.descriptor.capability_id:
            return CapabilityPreparation(False, "CAPABILITY_ID_MISMATCH")
        operation = next(
            (
                candidate
                for candidate in _WEB_RESEARCH_OPERATIONS
                if candidate.operation_id == intent.operation
            ),
            None,
        )
        if operation is None:
            return CapabilityPreparation(False, "OPERATION_NOT_SUPPORTED")
        if "subject" in operation.required_entities and not intent.arguments.get("subject"):
            return CapabilityPreparation(False, "RESEARCH_QUERY_REQUIRED", ("subject",))
        return CapabilityPreparation(True, "RESEARCH_INPUT_ACCEPTED")

    def propose_action(self, _request: CapabilityRequest) -> ActionProposal:
        """Research is read-only; it declares no state-changing effect."""
        return self.descriptor.declared_action

    def execute(self, request: CapabilityRequest) -> CapabilityExecution:
        if self.pipeline is None:
            raise PermissionDeniedError("web research capability is unavailable")
        operation = next(
            (
                candidate
                for candidate in _WEB_RESEARCH_OPERATIONS
                if candidate.operation_id == request.operation
            ),
            None,
        )
        execution = self.pipeline.execute(
            request.context_text,
            request_guardrails=request.request_guardrails,
            cancellation=request.cancellation,
            current_information=(
                operation is not None
                and operation.freshness in {FreshnessSupport.CURRENT, FreshnessSupport.LIVE}
            )
            if operation is not None
            else None,
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
    manifest: SpecialistManifest | None
    workflow: SpecialistWorkflow | None

    def _routing_operations(self) -> tuple[OperationIntentContract, ...]:
        """Return the manifest-declared specialist routing contract."""
        if self.manifest is not None and self.manifest.routing_operations:
            return self.manifest.routing_operations
        description = (
            self.manifest.description
            if self.manifest is not None
            else f"{self.capability_id} specialist capability"
        )
        accepted_inputs = (
            tuple(sorted(self.manifest.accepted_inputs)) if self.manifest is not None else ("text",)
        )
        domains = (
            tuple(sorted(self.manifest.capabilities))
            if self.manifest is not None
            else ("specialist",)
        )
        return (
            OperationIntentContract(
                operation_id="specialist.analyze",
                description=description,
                domains=domains,
                accepted_inputs=accepted_inputs,
                required_entities=("subject",),
                freshness=(
                    FreshnessSupport.CURRENT
                    if self.manifest is not None and self.manifest.requires_current_data
                    else FreshnessSupport.STATIC
                ),
                specificity=60,
            ),
        )

    @property
    def descriptor(self) -> CapabilityDescriptor:
        description = (
            self.manifest.description
            if self.manifest is not None
            else f"{self.capability_id} specialist capability"
        )
        routing_operations = self._routing_operations()
        return CapabilityDescriptor(
            capability_id=self.capability_id,
            description=description,
            routes=(Route.REGISTERED_CAPABILITY,),
            request_schema="specialist-task-v1",
            operations=tuple(operation.operation_id for operation in routing_operations),
            requires_external_boundary=True,
            requires_consent=True,
            destination=self.workflow.provider_name if self.workflow is not None else "",
            model=self.manifest.provider_model if self.manifest is not None else "",
            purpose=f"execute {self.capability_id} specialist",
            max_cost_usd=self.workflow.consent_max_cost_usd if self.workflow is not None else 0.0,
            routing=CapabilityRoutingDescriptor(
                capability_id=self.capability_id,
                description=description,
                operations=routing_operations,
                priority=(self.manifest.routing_priority if self.manifest is not None else 50),
                kind=CapabilityKind.SPECIALIST,
                requires_external_access=True,
                requires_consent=True,
            ),
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
        operations = self._routing_operations()
        operation = next(
            (candidate for candidate in operations if candidate.operation_id == intent.operation),
            None,
        )
        if operation is None:
            return CapabilityPreparation(False, "OPERATION_NOT_SUPPORTED")
        available = {entity.kind for entity in intent.entities} | set(intent.arguments)
        missing: list[str] = []
        for required in operation.required_entities:
            if required == "ticker_or_company":
                satisfied = bool({"ticker", "company", "ticker_or_company"} & available)
            elif required == "security":
                satisfied = bool({"security", "ticker", "company"} & available)
            else:
                satisfied = required in available and bool(intent.arguments.get(required))
            if not satisfied:
                missing.append(required)
        if missing:
            if missing == ["subject"]:
                return CapabilityPreparation(False, "SPECIALIST_SUBJECT_REQUIRED", ("subject",))
            return CapabilityPreparation(False, "SPECIALIST_ENTITY_REQUIRED", tuple(missing))
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
            goal=request.objective or request.task.text,
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
            route=Route.REGISTERED_CAPABILITY,
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
