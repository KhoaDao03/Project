"""Deterministic routing and validation of structured capability intent."""

from __future__ import annotations

from dataclasses import replace

from ..domain.enums import IntentAmbiguity, Route, RouteReasonCode
from ..domain.models import CapabilityIntent, RouteDecision, RouteProposal, RouteRequest
from ..ports.intent import IntentInterpreterPort
from ..research.freshness import needs_current_information
from .capabilities import CapabilityRegistry
from .intent import DeterministicIntentInterpreter


class RoutingPolicy:
    """Resolve typed intent to a registered route without provider calls."""

    _ROUTE_CAPABILITIES = {
        Route.WEB_RESEARCH: "web_research",
        Route.CODING_SPECIALIST: "coding",
        Route.RESEARCH_SPECIALIST: "research",
    }

    _RATIONALES = {
        "CODING_REQUEST": RouteReasonCode.CODING_REQUEST,
        "RESEARCH_SPECIALIST_REQUEST": RouteReasonCode.RESEARCH_SPECIALIST_REQUEST,
        "CURRENT_INFORMATION_REQUIRED": RouteReasonCode.CURRENT_INFORMATION_REQUIRED,
        "PROPOSAL_ACCEPTED": RouteReasonCode.PROPOSAL_ACCEPTED,
        "LEGACY_ROUTE_PROPOSAL": RouteReasonCode.PROPOSAL_ACCEPTED,
    }

    def __init__(
        self,
        *,
        capabilities: CapabilityRegistry | None = None,
        intent_interpreter: IntentInterpreterPort | None = None,
    ) -> None:
        self._capabilities = capabilities
        self._intent_interpreter = intent_interpreter or DeterministicIntentInterpreter()
        if not isinstance(self._intent_interpreter, IntentInterpreterPort):
            raise TypeError("intent_interpreter must implement IntentInterpreterPort")

    def decide(
        self,
        request: RouteRequest,
        *,
        proposal: RouteProposal | None = None,
        intent: CapabilityIntent | None = None,
    ) -> RouteDecision:
        """Interpret and validate one proposal before selecting a route."""
        selected_intent = intent or self._intent_interpreter.interpret(
            request, proposal=proposal
        )
        if not isinstance(selected_intent, CapabilityIntent):
            return self._rejected("INTENT_INTERPRETER_INVALID")

        if (
            proposal is not None
            and proposal.capability_id is not None
            and self._capabilities is not None
            and self._capabilities.get(proposal.capability_id) is None
        ):
            return self._rejected(
                "CAPABILITY_NOT_REGISTERED",
                capability_id=proposal.capability_id,
                operation=selected_intent.operation,
                intent=selected_intent,
                legacy=proposal is not None,
            )

        legacy_handler = (
            self._capabilities.get(proposal.capability_id)
            if proposal is not None
            and proposal.capability_id is not None
            and self._capabilities is not None
            else None
        )
        if (
            proposal is not None
            and legacy_handler is not None
            and not selected_intent.operation
        ):
            selected_intent = replace(
                selected_intent,
                operation=legacy_handler.descriptor.operations[0],
                arguments={"subject": request.text},
                ambiguity=IntentAmbiguity.CLEAR,
            )

        if selected_intent.ambiguity in {
            IntentAmbiguity.AMBIGUOUS,
            IntentAmbiguity.MISSING_FIELDS,
        }:
            fields = (
                ("capability", "operation")
                if selected_intent.ambiguity is IntentAmbiguity.AMBIGUOUS
                else ("operation",)
            )
            return RouteDecision(
                Route.LOCAL_GENERALIST,
                RouteReasonCode.INTENT_CLARIFICATION_REQUIRED,
                capability_id=selected_intent.proposed_capability_id,
                operation=selected_intent.operation,
                intent=selected_intent,
                clarification_required=True,
                clarification_fields=fields,
            )

        capability_id = selected_intent.proposed_capability_id
        if capability_id is None:
            return RouteDecision(
                Route.LOCAL_GENERALIST,
                RouteReasonCode.LOCAL_DEFAULT,
                operation=selected_intent.operation,
                intent=selected_intent,
            )

        handler = self._capabilities.get(capability_id) if self._capabilities else None
        if handler is None:
            # Preserve the pre-V2 deterministic route signal for isolated routing
            # tests, but never claim an unknown registered capability is executable.
            if self._capabilities is None:
                route = next(
                    (
                        route
                        for route, known_id in self._ROUTE_CAPABILITIES.items()
                        if known_id == capability_id
                    ),
                    Route.LOCAL_GENERALIST,
                )
                if route is not Route.LOCAL_GENERALIST:
                    return RouteDecision(
                        route,
                        self._reason_for(selected_intent),
                        capability_id=capability_id,
                        operation=selected_intent.operation,
                        intent=selected_intent,
                    )
            return self._rejected(
                "CAPABILITY_NOT_REGISTERED",
                capability_id=capability_id,
                operation=selected_intent.operation,
                intent=selected_intent,
            )

        descriptor = handler.descriptor
        if proposal is not None and proposal.capability_id == capability_id:
            if proposal.request_schema != descriptor.request_schema:
                return self._rejected(
                    "REQUEST_SCHEMA_MISMATCH",
                    capability_id=capability_id,
                    operation=selected_intent.operation,
                    intent=selected_intent,
                    legacy=proposal is not None,
                )

        status = handler.status()
        if not status.available:
            route = self._legacy_route(proposal, descriptor.routes[0])
            return RouteDecision(
                route,
                RouteReasonCode.CAPABILITY_UNAVAILABLE,
                capability_id=capability_id,
                diagnostic=status.reason_code,
                available=False,
                operation=selected_intent.operation,
                intent=selected_intent,
            )

        if selected_intent.operation not in descriptor.operations:
            return self._rejected(
                "OPERATION_NOT_SUPPORTED",
                capability_id=capability_id,
                operation=selected_intent.operation,
                intent=selected_intent,
                legacy=proposal is not None,
            )

        route = self._legacy_route(proposal, descriptor.routes[0])
        if route not in descriptor.routes:
            return self._rejected(
                "ROUTE_NOT_DECLARED",
                capability_id=capability_id,
                operation=selected_intent.operation,
                intent=selected_intent,
            )
        return RouteDecision(
            route,
            self._reason_for(selected_intent),
            capability_id=capability_id,
            operation=selected_intent.operation,
            intent=selected_intent,
        )

    def _reason_for(self, intent: CapabilityIntent) -> RouteReasonCode:
        return self._RATIONALES.get(
            intent.rationale_code, RouteReasonCode.PROPOSAL_ACCEPTED
        )

    @staticmethod
    def _legacy_route(proposal: RouteProposal | None, default: Route) -> Route:
        if proposal is not None and proposal.route is not None:
            return proposal.route
        return default

    @staticmethod
    def _rejected(
        diagnostic: str,
        *,
        capability_id: str | None = None,
        operation: str = "",
        intent: CapabilityIntent | None = None,
        legacy: bool = False,
    ) -> RouteDecision:
        return RouteDecision(
            Route.LOCAL_GENERALIST,
            RouteReasonCode.PROPOSAL_REJECTED if legacy else RouteReasonCode.INTENT_REJECTED,
            capability_id=capability_id,
            diagnostic=diagnostic,
            operation=operation,
            intent=intent,
        )

    # Kept as a small compatibility helper for callers that only need the old
    # current-information signal; capability selection itself uses the intent
    # interpreter above.
    @staticmethod
    def current_information(text: str) -> bool:
        return needs_current_information(text)
