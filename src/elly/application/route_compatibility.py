"""Routing metadata and explicit adapters for historical routing inputs."""

from __future__ import annotations

from dataclasses import replace

from ..domain.enums import IntentAmbiguity, Route
from ..domain.errors import InputInvalidError
from ..domain.models import (
    CapabilityIntent,
    RouteDecision,
    RouteProposal,
    RouteRequest,
    TaskResult,
)
from .routing_contracts import (
    CandidateMatch,
    CapabilitySelectionProposal,
    FreshnessRequirement,
    TaskIntent,
)

ROUTING_CONTRACT_VERSION = "v2.5-routing-v1"
LEGACY_ROUTING_CONTRACT_VERSION = "v2-legacy"


def legacy_capability_intent_to_selection(
    intent: CapabilityIntent,
) -> CapabilitySelectionProposal:
    """Translate one historical capability hint into the canonical proposal.

    This is deliberately a data-only adapter.  The resulting proposal remains
    untrusted until ``RoutingPolicy`` validates it against the live catalog.
    ``CapabilityIntent`` is also used by capability handlers as an internal
    preparation contract, so this translation does not replace that type.
    """

    if intent.proposed_capability_id is None:
        raise InputInvalidError("legacy capability intent must name a capability")
    return CapabilitySelectionProposal(
        capability_id=intent.proposed_capability_id,
        operation_id=intent.operation,
        arguments=intent.arguments,
        entities=intent.entities,
        confidence=intent.confidence,
        ambiguity=intent.ambiguity,
        rationale_code=intent.rationale_code,
    )


def legacy_route_proposal_to_selection(
    request: RouteRequest,
    proposal: RouteProposal,
    *,
    operation_id: str,
) -> CapabilitySelectionProposal:
    """Translate a validated historical route hint into a selection proposal.

    Route/capability/schema validation belongs to the routing boundary because
    it requires the live registry.  This helper only maps the already-validated
    historical payload into the canonical, still-untrusted selection shape.
    """

    if proposal.capability_id is None:
        raise InputInvalidError("legacy route proposal must name a capability")
    return CapabilitySelectionProposal(
        capability_id=proposal.capability_id,
        operation_id=operation_id,
        arguments={"subject": request.text},
        confidence=1.0,
        ambiguity=IntentAmbiguity.CLEAR,
        rationale_code="EXPLICIT_CAPABILITY_PROPOSAL",
    )


def is_local_route(route: Route) -> bool:
    """Return whether a route denotes local conversation rather than a capability."""

    return route in {Route.LOCAL_GENERALIST, Route.LOCAL_CONVERSATION}


def generic_route_for(route: Route, capability_id: str | None = None) -> Route:
    """Normalize a route decision/result to its generic persistence category."""

    if route is Route.LOCAL_CONVERSATION or route is Route.LOCAL_GENERALIST:
        return Route.LOCAL_CONVERSATION
    if route is Route.REGISTERED_CAPABILITY:
        return Route.REGISTERED_CAPABILITY
    if capability_id:
        return Route.REGISTERED_CAPABILITY
    # A route-only V2 value is retained as a historical value for callers that
    # have not supplied a capability identity. It is not a newly selected
    # registered capability and must not be guessed into one.
    return route


def is_generic_route(route: Route) -> bool:
    return route in {Route.LOCAL_CONVERSATION, Route.REGISTERED_CAPABILITY}


def enrich_task_result(
    result: TaskResult,
    decision: RouteDecision,
) -> TaskResult:
    """Attach safe routing metadata using generic routes for all new results."""

    candidate_count = decision.candidate_count
    rejected_codes = decision.rejected_candidate_reason_codes
    if decision.selection is not None:
        alternatives = decision.selection.ranked_alternatives
        if candidate_count == 0:
            candidate_count = len(alternatives)
        if not rejected_codes:
            rejected_codes = _rejected_candidate_reason_codes(alternatives)
    freshness_affected = decision.freshness_affected_selection
    if not freshness_affected and isinstance(decision.intent, TaskIntent):
        freshness_affected = decision.intent.freshness is not FreshnessRequirement.NONE
    return replace(
        result,
        route_summary=decision.generic_route,
        route_category=decision.generic_route,
        capability_id=decision.capability_id,
        operation=decision.operation,
        selection_reason_code=decision.reason_code.value,
        routing_contract_version=ROUTING_CONTRACT_VERSION,
        candidate_count=candidate_count,
        rejected_candidate_reason_codes=rejected_codes,
        clarification_required=decision.clarification_required,
        freshness_affected_selection=freshness_affected,
    )


def inherit_route_metadata(result: TaskResult, source: TaskResult) -> TaskResult:
    """Carry routing metadata into a later denial/confirmation view."""

    return replace(
        result,
        route_summary=source.route_summary,
        route_category=source.route_category,
        capability_id=source.capability_id,
        operation=source.operation,
        selection_reason_code=source.selection_reason_code,
        routing_contract_version=source.routing_contract_version,
        candidate_count=source.candidate_count,
        rejected_candidate_reason_codes=source.rejected_candidate_reason_codes,
        clarification_required=source.clarification_required,
        freshness_affected_selection=source.freshness_affected_selection,
    )


def _rejected_candidate_reason_codes(
    candidates: tuple[CandidateMatch, ...],
) -> tuple[str, ...]:
    """Flatten only validated candidate diagnostic codes for public traces."""
    codes: list[str] = []
    for candidate in candidates:
        for code in candidate.rejection_codes:
            if code not in codes:
                codes.append(code)
    return tuple(codes)


__all__ = [
    "LEGACY_ROUTING_CONTRACT_VERSION",
    "ROUTING_CONTRACT_VERSION",
    "enrich_task_result",
    "generic_route_for",
    "inherit_route_metadata",
    "is_generic_route",
    "is_local_route",
    "legacy_capability_intent_to_selection",
    "legacy_route_proposal_to_selection",
]
