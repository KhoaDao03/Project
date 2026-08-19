"""Advisory local planning followed by deterministic catalog validation."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from ...domain.enums import IntentAmbiguity, Route, RouteReasonCode
from ...domain.errors import CancelledError, EllyError, InputInvalidError
from ...domain.models import RouteDecision, RouteRequest
from ...planning.catalog import PlannerCatalog, build_planner_catalog
from ...planning.contracts import (
    PROPOSAL_SCHEMA_VERSION,
    ClarificationField,
    ExecutionProposal,
    FinalizationStrategy,
    ProposalDisposition,
    ProposedInput,
    ProposedStep,
)
from ...ports.local_planner import LocalPlannerPort, PlannerRequest
from ..capabilities.registry import CapabilityRegistry
from ..routing.catalog import CatalogCandidateSelector, CatalogIntentInterpreter
from ..routing.contracts import (
    CapabilitySelectionProposal,
    FreshnessRequirement,
    OperationIntentContract,
    RoutingCatalog,
    TaskIntent,
)
from ..routing.policy import RoutingPolicy

_PROVIDER_IDENTIFIERS = frozenset(
    {
        "anthropic",
        "azure",
        "bedrock",
        "claude",
        "cohere",
        "fake",
        "fixtures",
        "gemini",
        "google",
        "gpt",
        "gpt4",
        "gpt-4",
        "llama",
        "mistral",
        "ollama",
        "openai",
        "openai_web_search",
    }
)
_PROVIDER_TOKENS = frozenset(
    {
        "anthropic",
        "azure",
        "bedrock",
        "claude",
        "cohere",
        "fake",
        "fixtures",
        "gemini",
        "google",
        "gpt",
        "llama",
        "mistral",
        "ollama",
        "openai",
    }
)


@dataclass(frozen=True, slots=True)
class ProposalValidation:
    """Pure validation result for one proposal/catalog snapshot."""

    accepted: bool
    reason_code: str
    proposal: ExecutionProposal
    task_intent: TaskIntent | None = None
    clarification_fields: tuple[str, ...] = ()
    catalog_version: str = ""


@dataclass(frozen=True, slots=True)
class PlanningDecision:
    """Safe result of planning, including any deterministic fallback route."""

    proposal: ExecutionProposal
    route_decision: RouteDecision
    accepted: bool
    fallback_used: bool
    rejection_code: str = ""
    catalog_version: str = ""


class PlanInterpreter:
    """Call a local planner, then validate its capability-first proposal.

    This service has no execution authority.  It can return an accepted
    proposal or a deterministic V2.5 route fallback, but it never calls a
    capability handler or resolves a provider.
    """

    def __init__(
        self,
        *,
        planner: LocalPlannerPort,
        capabilities: CapabilityRegistry,
        max_output_tokens: int = 1200,
        timeout_seconds: float = 120.0,
        routing_policy: RoutingPolicy | None = None,
        catalog_interpreter: CatalogIntentInterpreter | None = None,
        candidate_selector: CatalogCandidateSelector | None = None,
    ) -> None:
        if not isinstance(planner, LocalPlannerPort):
            raise InputInvalidError("planner must implement LocalPlannerPort")
        if not isinstance(capabilities, CapabilityRegistry):
            raise InputInvalidError("capabilities must be a CapabilityRegistry")
        if (
            isinstance(max_output_tokens, bool)
            or not isinstance(max_output_tokens, int)
            or max_output_tokens <= 0
        ):
            raise InputInvalidError("planner max_output_tokens must be positive")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or timeout_seconds <= 0
        ):
            raise InputInvalidError("planner timeout_seconds must be positive")
        self._planner = planner
        self._capabilities = capabilities
        self._max_output_tokens = max_output_tokens
        self._timeout_seconds = timeout_seconds
        self._routing_policy = routing_policy or RoutingPolicy(capabilities=capabilities)
        self._catalog_interpreter = catalog_interpreter or CatalogIntentInterpreter()
        self._candidate_selector = candidate_selector or CatalogCandidateSelector()

    @property
    def planner(self) -> LocalPlannerPort:
        return self._planner

    def catalog_snapshot(self) -> PlannerCatalog:
        """Return a fresh immutable model-safe view of the live registry."""
        return build_planner_catalog(self._capabilities.routing_catalog())

    def deterministic_decision(self, request: RouteRequest) -> PlanningDecision:
        """Return the validated catalog strategy without invoking the planner.

        ``PlanningService`` owns strategy selection. This method exposes the
        existing deterministic machinery without creating a second planning
        entry point or granting routing output execution authority.
        """

        if not isinstance(request, RouteRequest):
            raise InputInvalidError("planning requires a RouteRequest")
        catalog = self._capabilities.routing_catalog()
        version = build_planner_catalog(catalog).version
        decision = self._fallback(request, catalog, version, "")
        proposal = replace(
            decision.proposal,
            reason_code="DETERMINISTIC_FAST_PATH",
            justification="validated deterministic catalog strategy",
        )
        return replace(
            decision,
            proposal=proposal,
            accepted=True,
            fallback_used=False,
            rejection_code="",
        )

    def interpret(
        self,
        request: RouteRequest,
        *,
        approved_context: str | None = None,
    ) -> PlanningDecision:
        """Plan one request or use the existing deterministic route fallback."""
        if not isinstance(request, RouteRequest):
            raise InputInvalidError("planning requires a RouteRequest")
        catalog = self._capabilities.routing_catalog()
        model_catalog = build_planner_catalog(catalog)
        planner_request = PlannerRequest(
            request_id=request.request_id,
            text=request.text,
            approved_context=(approved_context or request.contextual_text or ""),
            catalog=model_catalog,
            max_output_tokens=self._max_output_tokens,
            timeout_seconds=self._timeout_seconds,
        )
        try:
            proposal = self._planner.propose(planner_request)
        except CancelledError:
            raise
        except (EllyError, TypeError, ValueError):
            return self._fallback(request, catalog, model_catalog.version, "PROPOSAL_MALFORMED")
        except Exception:  # noqa: BLE001 - provider boundary must fail closed
            return self._fallback(request, catalog, model_catalog.version, "PROPOSAL_MALFORMED")

        if not isinstance(proposal, ExecutionProposal):
            return self._fallback(request, catalog, model_catalog.version, "PROPOSAL_MALFORMED")
        # The planner's catalog is advisory.  Re-snapshot the live registry
        # after generation so a capability becoming stale or unavailable
        # cannot be accepted from the earlier request snapshot.
        fresh_catalog = self._capabilities.routing_catalog()
        fresh_model_catalog = build_planner_catalog(fresh_catalog)
        validation = self.validate_proposal(
            proposal,
            request,
            catalog=fresh_catalog,
            catalog_version=fresh_model_catalog.version,
        )
        if not validation.accepted:
            return self._fallback(
                request,
                fresh_catalog,
                fresh_model_catalog.version,
                validation.reason_code,
            )
        route_decision = self._route_accepted(request, proposal, validation)
        return PlanningDecision(
            proposal=proposal,
            route_decision=route_decision,
            accepted=True,
            fallback_used=False,
            catalog_version=fresh_model_catalog.version,
        )

    decide = interpret

    def validate_proposal(
        self,
        proposal: ExecutionProposal,
        request: RouteRequest,
        *,
        catalog: RoutingCatalog | None = None,
        catalog_version: str = "",
    ) -> ProposalValidation:
        """Validate planner output against one fresh provider-free catalog."""
        if not isinstance(proposal, ExecutionProposal):
            raise InputInvalidError("proposal must be an ExecutionProposal")
        if not isinstance(request, RouteRequest):
            raise InputInvalidError("proposal validation requires a RouteRequest")
        active_catalog = self._capabilities.routing_catalog() if catalog is None else catalog
        model_catalog = build_planner_catalog(active_catalog)
        version = catalog_version or model_catalog.version
        task_intent = self._catalog_interpreter.interpret(request, active_catalog)

        if proposal.disposition is ProposalDisposition.CLARIFICATION_REQUIRED:
            return ProposalValidation(
                True,
                "CLARIFICATION_REQUIRED",
                proposal,
                task_intent,
                tuple(item.field_id for item in proposal.ambiguities),
                version,
            )
        if proposal.disposition is ProposalDisposition.LOCAL_ONLY:
            return ProposalValidation(
                True, "PROPOSAL_LOCAL_ONLY", proposal, task_intent, catalog_version=version
            )
        if proposal.disposition is ProposalDisposition.UNABLE:
            return ProposalValidation(
                True, "PROPOSAL_UNABLE", proposal, task_intent, catalog_version=version
            )

        if proposal.disposition is not ProposalDisposition.CAPABILITY_PLAN:
            return ProposalValidation(
                False, "PROPOSAL_MALFORMED", proposal, catalog_version=version
            )

        dependency_reason = self._validate_dependency_graph(proposal)
        if dependency_reason:
            return ProposalValidation(
                False,
                dependency_reason,
                proposal,
                task_intent,
                catalog_version=version,
            )

        capability_by_id = {item.capability_id: item for item in active_catalog}
        for step in proposal.steps:
            provider_rejection = self._provider_identifier_rejection(step)
            if provider_rejection:
                return ProposalValidation(
                    False, provider_rejection, proposal, task_intent, catalog_version=version
                )
            descriptor = capability_by_id.get(step.capability_id)
            if descriptor is None:
                return ProposalValidation(
                    False,
                    "PROPOSAL_CAPABILITY_UNKNOWN",
                    proposal,
                    task_intent,
                    catalog_version=version,
                )
            if not descriptor.available:
                return ProposalValidation(
                    False,
                    "CAPABILITY_UNAVAILABLE",
                    proposal,
                    task_intent,
                    catalog_version=version,
                )
            operation = next(
                (item for item in descriptor.operations if item.operation_id == step.operation_id),
                None,
            )
            if operation is None:
                return ProposalValidation(
                    False,
                    "OPERATION_UNSUPPORTED",
                    proposal,
                    task_intent,
                    catalog_version=version,
                )
            if step.verification:
                return ProposalValidation(
                    False,
                    "VERIFICATION_NOT_AUTHORIZED",
                    proposal,
                    task_intent,
                    catalog_version=version,
                )
            input_reason = self._validate_inputs(step, operation)
            if input_reason:
                return ProposalValidation(
                    False,
                    input_reason,
                    proposal,
                    task_intent,
                    catalog_version=version,
                )
            step_intent = self._intent_for_step(task_intent, step, operation)
            selection = CapabilitySelectionProposal(
                capability_id=step.capability_id,
                operation_id=step.operation_id,
                arguments=step_intent.arguments,
                entities=step_intent.entities,
                confidence=proposal.confidence,
                ambiguity=IntentAmbiguity.CLEAR,
                rationale_code="PLANNER_PROPOSAL",
            )
            selection_validation = self._candidate_selector.validate_proposal(
                selection,
                active_catalog,
                intent=step_intent,
            )
            if not selection_validation.accepted:
                return ProposalValidation(
                    False,
                    self._proposal_reason(selection_validation.reason_code),
                    proposal,
                    task_intent,
                    catalog_version=version,
                )
        return ProposalValidation(
            True, "PROPOSAL_VALIDATED", proposal, task_intent, catalog_version=version
        )

    validate = validate_proposal

    @staticmethod
    def _provider_identifier_rejection(step: ProposedStep) -> str:
        capability_parts = set(
            step.capability_id.casefold().replace("-", "_").replace(".", "_").split("_")
        )
        operation_parts = set(
            step.operation_id.casefold().replace("-", "_").replace(".", "_").split("_")
        )
        if (
            step.capability_id.casefold() in _PROVIDER_IDENTIFIERS
            or capability_parts & _PROVIDER_TOKENS
        ):
            return "PROVIDER_IDENTIFIER_NOT_ALLOWED"
        if (
            step.operation_id.casefold() in _PROVIDER_IDENTIFIERS
            or operation_parts & _PROVIDER_TOKENS
        ):
            return "PROVIDER_IDENTIFIER_NOT_ALLOWED"
        return ""

    @staticmethod
    def _validate_dependency_graph(proposal: ExecutionProposal) -> str:
        """Reject cyclic proposal graphs before a later plan phase exists."""
        dependencies = {step.proposal_step_id: set(step.dependencies) for step in proposal.steps}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(step_id: str) -> bool:
            if step_id in visiting:
                return True
            if step_id in visited:
                return False
            visiting.add(step_id)
            if any(visit(dependency) for dependency in dependencies[step_id]):
                return True
            visiting.remove(step_id)
            visited.add(step_id)
            return False

        if any(visit(step_id) for step_id in dependencies):
            return "PLAN_CYCLE"
        return ""

    @staticmethod
    def _validate_inputs(step: ProposedStep, operation: OperationIntentContract) -> str:
        accepted = set(operation.accepted_inputs)
        accepted.update(operation.required_entities)
        accepted.update(operation.optional_entities)
        accepted.update({"subject"})
        if "ticker_or_company" in accepted:
            accepted.update({"ticker", "company"})
        if "security" in accepted:
            accepted.update({"security", "ticker", "company"})
        for item in step.inputs:
            if item.value_type not in accepted:
                return "INPUT_UNSUPPORTED"
            if item.source == "step" and item.reference not in step.dependencies:
                return "INPUT_REFERENCE_INVALID"
        return ""

    @staticmethod
    def _intent_for_step(
        base: TaskIntent,
        step: ProposedStep,
        operation: OperationIntentContract,
    ) -> TaskIntent:
        return TaskIntent(
            requested_operation=step.operation_id,
            domain=operation.domains[0],
            entities=base.entities,
            arguments=base.arguments,
            # Freshness belongs to the individual proposed operation, not the
            # whole user request. A static specialist may validly analyze the
            # current result produced by an upstream research step.
            freshness=(
                base.freshness
                if step.requires_current_information
                else FreshnessRequirement.NONE
            ),
            expected_effect=operation.effect,
            confidence=base.confidence,
            ambiguity=IntentAmbiguity.CLEAR,
            rationale_code="PLANNER_VALIDATION",
        )

    @staticmethod
    def _proposal_reason(reason: str) -> str:
        return {
            "CAPABILITY_NOT_REGISTERED": "PROPOSAL_CAPABILITY_UNKNOWN",
            "SELECTION_AMBIGUOUS": "PROPOSAL_AMBIGUOUS",
            "LOW_CONFIDENCE": "PROPOSAL_LOW_CONFIDENCE",
            "INPUT_UNSUPPORTED": "INPUT_UNSUPPORTED",
            "ENTITY_UNSUPPORTED": "INPUT_UNSUPPORTED",
            "REQUIRED_ENTITY_MISSING": "REQUIRED_INPUT_MISSING",
            "FRESHNESS_UNSUPPORTED": "FRESHNESS_UNSUPPORTED",
            "OPERATION_UNSUPPORTED": "OPERATION_UNSUPPORTED",
            "CAPABILITY_UNAVAILABLE": "CAPABILITY_UNAVAILABLE",
        }.get(reason, "PROPOSAL_REJECTED")

    def _route_accepted(
        self,
        request: RouteRequest,
        proposal: ExecutionProposal,
        validation: ProposalValidation,
    ) -> RouteDecision:
        if proposal.disposition is ProposalDisposition.CLARIFICATION_REQUIRED:
            return RouteDecision(
                Route.LOCAL_CONVERSATION,
                RouteReasonCode.INTENT_CLARIFICATION_REQUIRED,
                operation="planner.clarify",
                intent=validation.task_intent,
                clarification_required=True,
                clarification_fields=validation.clarification_fields,
            )
        if proposal.disposition is ProposalDisposition.LOCAL_ONLY:
            return RouteDecision(
                Route.LOCAL_CONVERSATION,
                RouteReasonCode.PROPOSAL_ACCEPTED,
                operation="conversation.respond",
                intent=validation.task_intent,
            )
        if proposal.disposition is ProposalDisposition.UNABLE:
            return RouteDecision(
                Route.LOCAL_CONVERSATION,
                RouteReasonCode.PROPOSAL_REJECTED,
                operation="conversation.respond",
                intent=validation.task_intent,
            )
        if len(proposal.steps) == 1:
            step = proposal.steps[0]
            base_intent = validation.task_intent or self._catalog_interpreter.interpret(
                request, self._capabilities.routing_catalog()
            )
            selection = CapabilitySelectionProposal(
                capability_id=step.capability_id,
                operation_id=step.operation_id,
                arguments=base_intent.arguments,
                entities=base_intent.entities,
                confidence=proposal.confidence,
                ambiguity=IntentAmbiguity.CLEAR,
                rationale_code="PLANNER_PROPOSAL",
            )
            return self._routing_policy.decide(
                request,
                selection=selection,
                task_intent=self._intent_for_step(
                    base_intent,
                    step,
                    next(
                        item
                        for descriptor in self._capabilities.routing_catalog()
                        if descriptor.capability_id == step.capability_id
                        for item in descriptor.operations
                        if item.operation_id == step.operation_id
                    ),
                ),
            )
        return RouteDecision(
            Route.LOCAL_CONVERSATION,
            RouteReasonCode.PROPOSAL_ACCEPTED,
            operation="plan.execute",
            intent=validation.task_intent,
        )

    def _fallback(
        self,
        request: RouteRequest,
        catalog: RoutingCatalog,
        catalog_version: str,
        rejection_code: str,
    ) -> PlanningDecision:
        route_decision = self._routing_policy.decide(request)
        if route_decision.route is Route.REGISTERED_CAPABILITY and route_decision.capability_id:
            handler = self._capabilities.get(route_decision.capability_id)
            operation = route_decision.operation or (
                handler.descriptor.operations[0] if handler is not None else "capability.execute"
            )
            routing_operation = next(
                (
                    item
                    for descriptor in catalog
                    if descriptor.capability_id == route_decision.capability_id
                    for item in descriptor.operations
                    if item.operation_id == operation
                ),
                None,
            )
            fallback_input = self._fallback_input(routing_operation)
            requires_external = bool(
                handler is not None and handler.descriptor.requires_external_boundary
            )
            proposal = ExecutionProposal(
                schema_version=PROPOSAL_SCHEMA_VERSION,
                disposition=ProposalDisposition.CAPABILITY_PLAN,
                steps=(
                    ProposedStep(
                        proposal_step_id="fallback-step",
                        capability_id=route_decision.capability_id,
                        operation_id=operation,
                        objective="deterministic catalog fallback",
                        objective_class="deterministic_fallback",
                        perspective="default",
                        inputs=(fallback_input,),
                        expected_output_type="task_result",
                        requires_current_information=route_decision.freshness_affected_selection,
                        requires_external_access=requires_external,
                    ),
                ),
                finalization=FinalizationStrategy.DIRECT,
                ambiguities=(),
                confidence=1.0,
                reason_code="DETERMINISTIC_FALLBACK",
                justification="existing deterministic catalog route",
            )
        elif route_decision.clarification_required:
            proposal = ExecutionProposal(
                schema_version=PROPOSAL_SCHEMA_VERSION,
                disposition=ProposalDisposition.CLARIFICATION_REQUIRED,
                steps=(),
                finalization=FinalizationStrategy.DIRECT,
                ambiguities=tuple(
                    ClarificationField(field, "DETERMINISTIC_CLARIFICATION")
                    for field in route_decision.clarification_fields
                ),
                confidence=1.0,
                reason_code="DETERMINISTIC_FALLBACK",
                justification="deterministic routing requires clarification",
            )
        else:
            proposal = ExecutionProposal(
                schema_version=PROPOSAL_SCHEMA_VERSION,
                disposition=ProposalDisposition.LOCAL_ONLY,
                steps=(),
                finalization=FinalizationStrategy.DIRECT,
                ambiguities=(),
                confidence=1.0,
                reason_code="DETERMINISTIC_FALLBACK",
                justification="deterministic local conversation fallback",
            )
        return PlanningDecision(
            proposal=proposal,
            route_decision=route_decision,
            accepted=False,
            fallback_used=True,
            rejection_code=rejection_code,
            catalog_version=catalog_version,
        )

    @staticmethod
    def _fallback_input(operation: OperationIntentContract | None) -> ProposedInput:
        """Describe the deterministic route's first declared input safely."""
        if operation is not None and operation.required_entities:
            value_type = operation.required_entities[0]
            if value_type == "ticker_or_company":
                value_type = "ticker"
            elif value_type == "security":
                value_type = "security"
        else:
            value_type = (
                "text"
                if operation is None or "text" in operation.accepted_inputs
                else operation.accepted_inputs[0]
            )
        # Deterministic V2.5 fallback consumes the already resolved bounded
        # conversation context, preserving follow-up behavior and one-step
        # execution equivalence while still entering the V3 plan pipeline.
        return ProposedInput(value_type, value_type, source="context")


__all__ = ["PlanInterpreter", "PlanningDecision", "ProposalValidation"]
