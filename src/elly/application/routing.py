"""Deterministic routing and validation of structured capability intent."""

from __future__ import annotations

from ..domain.enums import ActionCategory, IntentAmbiguity, Route, RouteReasonCode
from ..domain.models import CapabilityIntent, RouteDecision, RouteProposal, RouteRequest
from ..research.freshness import needs_current_information
from .capabilities import CapabilityRegistry
from .catalog_routing import (
    CatalogCandidateSelector,
    CatalogIntentInterpreter,
    CatalogSelectionResult,
)
from .routing_contracts import (
    CandidateMatch,
    CapabilitySelectionProposal,
    FreshnessRequirement,
    TaskIntent,
)


def _rejected_candidate_reason_codes(
    candidates: tuple[CandidateMatch, ...],
) -> tuple[str, ...]:
    """Return stable, safe rejection codes without exposing candidate payloads."""
    codes: list[str] = []
    for candidate in candidates:
        for code in candidate.rejection_codes:
            if code not in codes:
                codes.append(code)
    return tuple(codes)


def _selection_trace_metadata(
    *,
    intent: TaskIntent | None,
    selection: CapabilitySelectionProposal | None = None,
    candidates: tuple[CandidateMatch, ...] = (),
) -> tuple[int, tuple[str, ...], bool]:
    """Build bounded observability fields from validated catalog evidence."""
    evidence = candidates or (selection.ranked_alternatives if selection is not None else ())
    return (
        len(evidence),
        _rejected_candidate_reason_codes(evidence),
        bool(intent is not None and intent.freshness is not FreshnessRequirement.NONE),
    )


class RoutingPolicy:
    """Resolve typed intent to a registered route without provider calls."""

    _CATALOG_REASONS = {
        "CATALOG_NO_MATCH": RouteReasonCode.CATALOG_NO_MATCH,
        "CATALOG_SINGLE_MATCH": RouteReasonCode.CATALOG_SINGLE_MATCH,
        "CATALOG_AMBIGUOUS": RouteReasonCode.CATALOG_AMBIGUOUS,
        "REQUIRED_ENTITY_MISSING": RouteReasonCode.REQUIRED_ENTITY_MISSING,
        "FRESHNESS_UNSUPPORTED": RouteReasonCode.FRESHNESS_UNSUPPORTED,
        "OPERATION_UNSUPPORTED": RouteReasonCode.OPERATION_UNSUPPORTED,
        "ACTION_EFFECT_MISMATCH": RouteReasonCode.ACTION_UNSUPPORTED,
    }

    def __init__(
        self,
        *,
        capabilities: CapabilityRegistry | None = None,
        catalog_interpreter: CatalogIntentInterpreter | None = None,
        candidate_selector: CatalogCandidateSelector | None = None,
    ) -> None:
        self._capabilities = capabilities
        self._catalog_interpreter = catalog_interpreter or CatalogIntentInterpreter()
        if not isinstance(self._catalog_interpreter, CatalogIntentInterpreter):
            raise TypeError("catalog_interpreter must be a CatalogIntentInterpreter")
        self._candidate_selector = candidate_selector or CatalogCandidateSelector()
        if not isinstance(self._candidate_selector, CatalogCandidateSelector):
            raise TypeError("candidate_selector must be a CatalogCandidateSelector")

    def decide(
        self,
        request: RouteRequest,
        *,
        proposal: RouteProposal | None = None,
        intent: CapabilityIntent | TaskIntent | None = None,
        task_intent: TaskIntent | None = None,
        selection: CapabilitySelectionProposal | None = None,
    ) -> RouteDecision:
        """Interpret and validate one request against the live registry catalog."""
        if isinstance(intent, TaskIntent):
            if task_intent is not None:
                return self._catalog_rejected("DUPLICATE_TASK_INTENT", intent=task_intent)
            task_intent = intent
            intent = None

        if isinstance(intent, CapabilityIntent):
            if intent.ambiguity in {
                IntentAmbiguity.AMBIGUOUS,
                IntentAmbiguity.MISSING_FIELDS,
            }:
                return RouteDecision(
                    Route.LOCAL_CONVERSATION,
                    RouteReasonCode.CATALOG_AMBIGUOUS,
                    operation=intent.operation,
                    intent=intent,
                    clarification_required=True,
                    clarification_fields=("capability", "operation"),
                )
            if intent.proposed_capability_id is None:
                return self._local_default(operation=intent.operation, intent=intent)
            selection = CapabilitySelectionProposal(
                capability_id=intent.proposed_capability_id,
                operation_id=intent.operation,
                arguments=intent.arguments,
                entities=intent.entities,
                confidence=intent.confidence,
                ambiguity=intent.ambiguity,
                rationale_code=intent.rationale_code,
            )
            intent = None

        if proposal is not None:
            if selection is not None or task_intent is not None:
                return self._catalog_rejected("DUPLICATE_SELECTION_INPUT")
            proposal_selection = self._selection_from_route_proposal(request, proposal)
            if isinstance(proposal_selection, RouteDecision):
                return proposal_selection
            selection = proposal_selection

        if selection is not None or task_intent is not None:
            catalog_decision = self._decide_from_catalog(
                request,
                task_intent=task_intent,
                selection=selection,
                force=True,
            )
            if catalog_decision is None:  # pragma: no cover - force is fail-closed
                return self._catalog_rejected("CAPABILITY_CATALOG_UNAVAILABLE", intent=task_intent)
            return catalog_decision

        catalog_decision = self._decide_from_catalog(request)
        return catalog_decision if catalog_decision is not None else self._local_default()

    def _selection_from_route_proposal(
        self, request: RouteRequest, proposal: RouteProposal
    ) -> CapabilitySelectionProposal | RouteDecision:
        if proposal.route not in {None, Route.REGISTERED_CAPABILITY}:
            return self._catalog_rejected("LEGACY_ROUTE_UNSUPPORTED")
        if proposal.capability_id is None or self._capabilities is None:
            return self._catalog_rejected("CAPABILITY_NOT_REGISTERED")
        handler = self._capabilities.get(proposal.capability_id)
        if handler is None:
            return self._catalog_rejected(
                "CAPABILITY_NOT_REGISTERED", capability_id=proposal.capability_id
            )
        descriptor = handler.descriptor
        if proposal.request_schema != descriptor.request_schema:
            return self._catalog_rejected(
                "REQUEST_SCHEMA_MISMATCH", capability_id=proposal.capability_id
            )
        if len(descriptor.operations) != 1:
            return RouteDecision(
                Route.LOCAL_CONVERSATION,
                RouteReasonCode.CATALOG_AMBIGUOUS,
                capability_id=proposal.capability_id,
                clarification_required=True,
                clarification_fields=("operation",),
            )
        return CapabilitySelectionProposal(
            capability_id=proposal.capability_id,
            operation_id=descriptor.operations[0],
            arguments={"subject": request.text},
            confidence=1.0,
            ambiguity=IntentAmbiguity.CLEAR,
            rationale_code="EXPLICIT_CAPABILITY_PROPOSAL",
        )

    @staticmethod
    def _local_default(
        *, operation: str = "conversation.respond", intent: CapabilityIntent | None = None
    ) -> RouteDecision:
        return RouteDecision(
            Route.LOCAL_CONVERSATION,
            RouteReasonCode.LOCAL_DEFAULT,
            operation=operation,
            intent=intent,
        )

    def _decide_from_catalog(
        self,
        request: RouteRequest,
        *,
        task_intent: TaskIntent | None = None,
        selection: CapabilitySelectionProposal | None = None,
        force: bool = False,
    ) -> RouteDecision | None:
        """Run the catalog path and validate its result against a fresh snapshot."""
        if self._capabilities is None:
            if force:
                return self._catalog_rejected(
                    "CAPABILITY_CATALOG_UNAVAILABLE",
                    intent=task_intent,
                    selection=selection,
                )
            return None

        catalog = self._capabilities.routing_catalog()
        if selection is not None:
            validation = self._candidate_selector.validate_proposal(
                selection,
                catalog,
                # An explicit proposal is allowed to supply the operation
                # signal; structural catalog validation must not require the
                # deterministic interpreter to recognize the same wording.
                intent=task_intent,
            )
            selected_task_intent = task_intent or self._catalog_interpreter.interpret(
                request, catalog
            )
            if not validation.accepted or validation.selection is None:
                if validation.reason_code == "CAPABILITY_UNAVAILABLE":
                    # Availability is an execution concern, not a malformed
                    # selection. Preserve the selected capability so callers
                    # receive its stable, actionable unavailable reason.
                    return self._route_catalog_selection(
                        selected_task_intent,
                        selection,
                        reason=RouteReasonCode.CATALOG_SINGLE_MATCH,
                    )
                return self._catalog_rejected(
                    validation.reason_code,
                    capability_id=selection.capability_id,
                    operation=selection.operation_id,
                    intent=selected_task_intent,
                    selection=selection,
                )
            return self._route_catalog_selection(
                selected_task_intent,
                validation.selection,
                reason=RouteReasonCode.CATALOG_SINGLE_MATCH,
            )

        selected_task_intent = task_intent or self._catalog_interpreter.interpret(request, catalog)
        result = self._candidate_selector.select(selected_task_intent, catalog)
        if (
            result.reason_code == "CATALOG_NO_MATCH"
            and not force
            and selected_task_intent.expected_effect is ActionCategory.NONE
        ):
            # Ordinary requests with no catalog evidence use the generic local
            # conversation route. Positive evidence and selection failures stay
            # on the catalog path below.
            return None
        if result.selection is not None and result.reason_code == "CATALOG_SINGLE_MATCH":
            validation = self._candidate_selector.validate_proposal(
                result.selection,
                catalog,
                intent=selected_task_intent,
            )
            if not validation.accepted or validation.selection is None:
                return self._catalog_rejected(
                    validation.reason_code,
                    capability_id=result.selection.capability_id,
                    operation=result.selection.operation_id,
                    intent=selected_task_intent,
                    selection=result.selection,
                )
            return self._route_catalog_selection(
                selected_task_intent,
                validation.selection,
                reason=RouteReasonCode.CATALOG_SINGLE_MATCH,
                candidates=result.matches,
            )
        return self._catalog_result_decision(selected_task_intent, result)

    def _route_catalog_selection(
        self,
        task_intent: TaskIntent,
        selection: CapabilitySelectionProposal,
        *,
        reason: RouteReasonCode,
        candidates: tuple[CandidateMatch, ...] = (),
    ) -> RouteDecision:
        handler = self._capabilities.get(selection.capability_id) if self._capabilities else None
        if handler is None:
            return self._catalog_rejected(
                "CAPABILITY_NOT_REGISTERED",
                capability_id=selection.capability_id,
                operation=selection.operation_id,
                intent=task_intent,
                selection=selection,
            )
        descriptor = handler.descriptor
        if selection.operation_id not in descriptor.operations:
            return self._catalog_rejected(
                "OPERATION_UNSUPPORTED",
                capability_id=selection.capability_id,
                operation=selection.operation_id,
                intent=task_intent,
                selection=selection,
            )
        status = handler.status()
        if not status.available:
            candidate_count, rejected_codes, freshness_affected = _selection_trace_metadata(
                intent=task_intent, selection=selection, candidates=candidates
            )
            return RouteDecision(
                Route.REGISTERED_CAPABILITY,
                RouteReasonCode.CAPABILITY_UNAVAILABLE,
                capability_id=selection.capability_id,
                diagnostic=status.reason_code,
                available=False,
                operation=selection.operation_id,
                intent=task_intent,
                selection=selection,
                candidate_count=candidate_count,
                rejected_candidate_reason_codes=rejected_codes,
                freshness_affected_selection=freshness_affected,
            )
        candidate_count, rejected_codes, freshness_affected = _selection_trace_metadata(
            intent=task_intent, selection=selection, candidates=candidates
        )
        return RouteDecision(
            Route.REGISTERED_CAPABILITY,
            reason,
            capability_id=selection.capability_id,
            operation=selection.operation_id,
            intent=task_intent,
            selection=selection,
            candidate_count=candidate_count,
            rejected_candidate_reason_codes=rejected_codes,
            freshness_affected_selection=freshness_affected,
        )

    def _catalog_result_decision(
        self,
        task_intent: TaskIntent,
        result: CatalogSelectionResult,
    ) -> RouteDecision:
        if result.reason_code == "LOW_CONFIDENCE":
            reason = RouteReasonCode.CATALOG_AMBIGUOUS
        elif result.reason_code == "CAPABILITY_UNAVAILABLE":
            reason = RouteReasonCode.CAPABILITY_UNAVAILABLE
        else:
            reason = self._CATALOG_REASONS.get(
                result.reason_code, RouteReasonCode.SELECTION_PROPOSAL_REJECTED
            )
        best = result.best_candidate
        capability_id = (
            best.capability_id
            if best is not None
            and result.reason_code
            not in {
                "CATALOG_AMBIGUOUS",
                "LOW_CONFIDENCE",
                "ACTION_EFFECT_MISMATCH",
            }
            else None
        )
        operation = best.operation_id if best is not None else task_intent.requested_operation
        if result.reason_code in {"CATALOG_AMBIGUOUS", "LOW_CONFIDENCE"}:
            operation = task_intent.requested_operation
        if result.reason_code == "CAPABILITY_UNAVAILABLE" and best is not None:
            handler = self._capabilities.get(best.capability_id) if self._capabilities else None
            if handler is not None:
                status = handler.status()
                unavailable_selection = result.selection or self._candidate_selector.proposal_for(
                    task_intent, best, result.matches
                )
                candidate_count, rejected_codes, freshness_affected = _selection_trace_metadata(
                    intent=task_intent,
                    selection=unavailable_selection,
                    candidates=result.matches,
                )
                return RouteDecision(
                    Route.REGISTERED_CAPABILITY,
                    RouteReasonCode.CAPABILITY_UNAVAILABLE,
                    capability_id=best.capability_id,
                    diagnostic=status.reason_code or "CAPABILITY_UNAVAILABLE",
                    available=False,
                    operation=best.operation_id,
                    intent=task_intent,
                    selection=unavailable_selection,
                    candidate_count=candidate_count,
                    rejected_candidate_reason_codes=rejected_codes,
                    freshness_affected_selection=freshness_affected,
                )
        candidate_count, rejected_codes, freshness_affected = _selection_trace_metadata(
            intent=task_intent,
            selection=result.selection,
            candidates=result.matches,
        )
        return RouteDecision(
            Route.LOCAL_CONVERSATION,
            reason,
            capability_id=capability_id,
            operation=operation,
            intent=task_intent,
            selection=result.selection,
            clarification_required=result.clarification_required,
            clarification_fields=result.clarification_fields,
            candidate_count=candidate_count,
            rejected_candidate_reason_codes=rejected_codes,
            freshness_affected_selection=freshness_affected,
        )

    @staticmethod
    def _catalog_rejected(
        diagnostic: str,
        *,
        capability_id: str | None = None,
        operation: str = "",
        intent: TaskIntent | None = None,
        selection: CapabilitySelectionProposal | None = None,
    ) -> RouteDecision:
        candidate_count, rejected_codes, freshness_affected = _selection_trace_metadata(
            intent=intent, selection=selection
        )
        return RouteDecision(
            Route.LOCAL_CONVERSATION,
            RouteReasonCode.SELECTION_PROPOSAL_REJECTED,
            capability_id=capability_id,
            diagnostic=diagnostic,
            operation=operation,
            intent=intent,
            selection=selection,
            candidate_count=candidate_count,
            rejected_candidate_reason_codes=rejected_codes,
            freshness_affected_selection=freshness_affected,
        )

    # Small public helper for callers that need the current-information signal;
    # capability selection itself uses the catalog interpreter above.
    @staticmethod
    def current_information(text: str) -> bool:
        return needs_current_information(text)
