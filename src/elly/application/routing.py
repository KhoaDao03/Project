"""Deterministic application-owned routing policy."""

from __future__ import annotations

from ..domain.enums import Route, RouteReasonCode
from ..domain.models import RouteDecision, RouteProposal, RouteRequest
from ..research.freshness import needs_current_information
from .capabilities import CapabilityRegistry


class RoutingPolicy:
    """Selects a route from trusted request data and untrusted proposals.

    The policy preserves V1's deterministic rules. Optional capability
    availability is checked before a decision is returned as executable.
    """

    _ROUTE_CAPABILITIES = {
        Route.WEB_RESEARCH: "web_research",
        Route.RESEARCH_SPECIALIST: "research",
        Route.CODING_SPECIALIST: "coding",
    }

    def __init__(self, *, capabilities: CapabilityRegistry | None = None) -> None:
        self._capabilities = capabilities

    def decide(
        self,
        request: RouteRequest,
        *,
        proposal: RouteProposal | None = None,
    ) -> RouteDecision:
        if proposal is not None:
            proposed = self._validate_proposal(request, proposal)
            if proposed is not None:
                return proposed

        lowered = request.text.lower()
        if any(
            token in lowered
            for token in (
                "review this code",
                "debug this",
                "code review",
                "python function",
                "programming bug",
            )
        ):
            return self._decision(Route.CODING_SPECIALIST, RouteReasonCode.CODING_REQUEST)
        if any(
            token in lowered
            for token in (
                "research specialist",
                "synthesize the sources",
                "analyze the evidence",
            )
        ):
            return self._decision(
                Route.RESEARCH_SPECIALIST,
                RouteReasonCode.RESEARCH_SPECIALIST_REQUEST,
            )

        route_text = request.contextual_text if request.contextual_text is not None else request.text
        if needs_current_information(route_text):
            return self._decision(
                Route.WEB_RESEARCH,
                RouteReasonCode.CURRENT_INFORMATION_REQUIRED,
            )
        return self._decision(Route.LOCAL_GENERALIST, RouteReasonCode.LOCAL_DEFAULT)

    def _validate_proposal(
        self, request: RouteRequest, proposal: RouteProposal
    ) -> RouteDecision | None:
        if proposal.capability_id is None:
            if proposal.route is Route.LOCAL_GENERALIST:
                return RouteDecision(
                    Route.LOCAL_GENERALIST,
                    RouteReasonCode.PROPOSAL_ACCEPTED,
                )
            return None
        if self._capabilities is None:
            return None
        handler = self._capabilities.get(proposal.capability_id)
        if handler is None:
            return RouteDecision(
                Route.LOCAL_GENERALIST,
                RouteReasonCode.PROPOSAL_REJECTED,
                diagnostic="CAPABILITY_NOT_REGISTERED",
            )
        descriptor = handler.descriptor
        if proposal.request_schema != descriptor.request_schema:
            return RouteDecision(
                Route.LOCAL_GENERALIST,
                RouteReasonCode.PROPOSAL_REJECTED,
                capability_id=proposal.capability_id,
                diagnostic="REQUEST_SCHEMA_MISMATCH",
            )
        status = handler.status()
        if not status.available:
            route = proposal.route or descriptor.routes[0]
            return RouteDecision(
                route,
                RouteReasonCode.CAPABILITY_UNAVAILABLE,
                capability_id=proposal.capability_id,
                diagnostic=status.reason_code,
                available=False,
            )
        route = proposal.route or descriptor.routes[0]
        if route not in descriptor.routes:
            return RouteDecision(
                Route.LOCAL_GENERALIST,
                RouteReasonCode.PROPOSAL_REJECTED,
                capability_id=proposal.capability_id,
                diagnostic="ROUTE_NOT_DECLARED",
            )
        return RouteDecision(
            route,
            RouteReasonCode.PROPOSAL_ACCEPTED,
            capability_id=proposal.capability_id,
        )

    def _decision(self, route: Route, reason_code: RouteReasonCode) -> RouteDecision:
        capability_id = self._ROUTE_CAPABILITIES.get(route)
        if self._capabilities is None or capability_id is None:
            return RouteDecision(route, reason_code, capability_id=capability_id)
        status = self._capabilities.status(capability_id)
        if not status.available:
            return RouteDecision(
                route,
                RouteReasonCode.CAPABILITY_UNAVAILABLE,
                capability_id=capability_id,
                diagnostic=status.reason_code,
                available=False,
            )
        return RouteDecision(route, reason_code, capability_id=capability_id)
