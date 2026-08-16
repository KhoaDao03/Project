"""Provider-free Phase 2 catalog interpretation, ranking, and validation tests."""

from __future__ import annotations

import unittest

from elly.application.capabilities import (
    CapabilityAvailability,
    CapabilityDescriptor,
    CapabilityExecution,
    CapabilityMatch,
    CapabilityPreparation,
    CapabilityRegistry,
    CapabilityRequest,
    CapabilityRoutingDescriptor,
    CapabilityStatus,
    FreshnessRequirement,
    FreshnessSupport,
    OperationIntentContract,
    TaskIntent,
)
from elly.application.catalog_routing import CatalogCandidateSelector, CatalogIntentInterpreter
from elly.application.routing import RoutingPolicy
from elly.domain.enums import CloudMode, IntentAmbiguity, IntentEntitySource, Route, RouteReasonCode
from elly.domain.models import ActionProposal, IntentEntity, RouteRequest


def _operation(
    operation_id: str,
    description: str,
    *,
    domains: tuple[str, ...] = ("general",),
    required_entities: tuple[str, ...] = (),
    freshness: FreshnessSupport = FreshnessSupport.STATIC,
    specificity: int = 50,
    examples: tuple[str, ...] = (),
) -> OperationIntentContract:
    return OperationIntentContract(
        operation_id=operation_id,
        description=description,
        domains=domains,
        accepted_inputs=("text", "ticker"),
        required_entities=required_entities,
        freshness=freshness,
        specificity=specificity,
        examples=examples,
    )


class _SyntheticCapability:
    def __init__(
        self,
        capability_id: str,
        operations: tuple[OperationIntentContract, ...],
        *,
        priority: int = 50,
        available: bool = True,
    ) -> None:
        self.descriptor = CapabilityDescriptor(
            capability_id=capability_id,
            description="Synthetic catalog capability",
            routes=(Route.CODING_SPECIALIST,),
            request_schema=f"{capability_id}-v1",
            operations=tuple(operation.operation_id for operation in operations),
            declared_action=ActionProposal.none(),
            routing=CapabilityRoutingDescriptor(
                capability_id=capability_id,
                description="Synthetic catalog capability",
                operations=operations,
                priority=priority,
            ),
        )
        self._available = available

    def status(self) -> CapabilityStatus:
        return CapabilityStatus(
            CapabilityAvailability.AVAILABLE
            if self._available
            else CapabilityAvailability.UNAVAILABLE,
            "" if self._available else "SYNTHETIC_DISABLED",
        )

    def can_handle(self, _request: CapabilityRequest) -> CapabilityMatch:
        return CapabilityMatch(True, "SYNTHETIC_MATCH")

    def prepare(self, _intent, _request: CapabilityRequest) -> CapabilityPreparation:
        return CapabilityPreparation(True, "SYNTHETIC_PREPARED")

    def execute(self, _request: CapabilityRequest) -> CapabilityExecution:
        raise AssertionError("Phase 2 tests must not invoke a provider")


def _request(text: str) -> RouteRequest:
    return RouteRequest("phase2-catalog", text, cloud_mode=CloudMode.LOCAL_ONLY)


class Phase2CatalogSelectionTests(unittest.TestCase):
    def test_new_capability_is_selected_without_a_central_capability_branch(self) -> None:
        capability = _SyntheticCapability(
            "weather_capability",
            (
                _operation(
                    "weather.lookup",
                    "Look up weather for a location",
                    domains=("weather",),
                    required_entities=("location",),
                    freshness=FreshnessSupport.CURRENT,
                    specificity=80,
                    examples=("What is the weather in Boston?",),
                ),
            ),
        )
        decision = RoutingPolicy(capabilities=CapabilityRegistry((capability,))).decide(
            _request("What is the weather in Boston?")
        )
        self.assertEqual(Route.REGISTERED_CAPABILITY, decision.route)
        self.assertEqual("weather_capability", decision.capability_id)
        self.assertEqual("weather.lookup", decision.operation)
        self.assertEqual(RouteReasonCode.CATALOG_SINGLE_MATCH, decision.reason_code)
        self.assertIsInstance(decision.intent, TaskIntent)
        self.assertIsNotNone(decision.selection)

    def test_missing_required_entity_is_a_typed_clarification(self) -> None:
        capability = _SyntheticCapability(
            "finance_capability",
            (
                _operation(
                    "valuation.analyze",
                    "Analyze company valuation",
                    domains=("finance", "valuation"),
                    required_entities=("ticker_or_company",),
                    specificity=90,
                ),
            ),
        )
        decision = RoutingPolicy(capabilities=CapabilityRegistry((capability,))).decide(
            _request("Analyze the valuation")
        )
        self.assertTrue(decision.clarification_required)
        self.assertEqual(("ticker_or_company",), decision.clarification_fields)
        self.assertEqual(RouteReasonCode.REQUIRED_ENTITY_MISSING, decision.reason_code)
        self.assertEqual(Route.LOCAL_CONVERSATION, decision.route)
        self.assertIsNotNone(decision.selection)
        self.assertEqual("valuation.analyze", decision.selection.operation_id)

    def test_exact_operation_beats_broader_operation_regardless_of_registration_order(self) -> None:
        exact = _SyntheticCapability(
            "specific",
            (
                _operation(
                    "valuation.analyze",
                    "Analyze company valuation",
                    domains=("finance",),
                    specificity=60,
                ),
            ),
        )
        broad = _SyntheticCapability(
            "broad",
            (
                _operation(
                    "analysis.analyze",
                    "Analyze a general request",
                    domains=("finance",),
                    specificity=100,
                ),
            ),
        )
        decisions = []
        for handlers in ((broad, exact), (exact, broad)):
            decisions.append(
                RoutingPolicy(capabilities=CapabilityRegistry(handlers)).decide(
                    _request("Analyze the valuation")
                )
            )
        self.assertEqual(("specific", "specific"), tuple(item.capability_id for item in decisions))
        self.assertEqual(
            ("valuation.analyze", "valuation.analyze"), tuple(item.operation for item in decisions)
        )

    def test_semantic_tie_requests_clarification_instead_of_using_capability_id(self) -> None:
        operation = _operation(
            "lookup.find", "Find a matching record", domains=("records",), specificity=70
        )
        first = _SyntheticCapability("first", (operation,))
        second = _SyntheticCapability("second", (operation,))
        decision = RoutingPolicy(capabilities=CapabilityRegistry((second, first))).decide(
            _request("Find a matching record")
        )
        self.assertEqual(RouteReasonCode.CATALOG_AMBIGUOUS, decision.reason_code)
        self.assertTrue(decision.clarification_required)
        self.assertEqual(("capability", "operation"), decision.clarification_fields)
        self.assertIsNone(decision.capability_id)

    def test_domain_specificity_precedes_declared_priority(self) -> None:
        specific = _SyntheticCapability(
            "specific_domain",
            (
                _operation(
                    "records.lookup", "Find a matching record", domains=("records",), specificity=90
                ),
            ),
            priority=10,
        )
        broad = _SyntheticCapability(
            "high_priority_broad",
            (
                _operation(
                    "records.lookup", "Find a matching record", domains=("records",), specificity=40
                ),
            ),
            priority=100,
        )
        decision = RoutingPolicy(capabilities=CapabilityRegistry((broad, specific))).decide(
            _request("Find a matching record")
        )
        self.assertEqual("specific_domain", decision.capability_id)

    def test_live_requirement_excludes_static_only_candidates(self) -> None:
        live = _SyntheticCapability(
            "live_provider",
            (
                _operation(
                    "market.quote",
                    "Provide a live market quote",
                    domains=("market",),
                    required_entities=("ticker",),
                    freshness=FreshnessSupport.LIVE,
                    specificity=50,
                ),
            ),
        )
        static = _SyntheticCapability(
            "static_provider",
            (
                _operation(
                    "market.quote",
                    "Provide a market quote from stored data",
                    domains=("market",),
                    required_entities=("ticker",),
                    freshness=FreshnessSupport.STATIC,
                    specificity=100,
                ),
            ),
        )
        intent = TaskIntent(
            requested_operation="market.quote",
            domain="market",
            entities=(IntentEntity("ticker", "AAPL", IntentEntitySource.EXPLICIT),),
            arguments={"ticker": "AAPL"},
            freshness=FreshnessRequirement.LIVE,
            confidence=0.9,
            ambiguity=IntentAmbiguity.CLEAR,
            rationale_code="TEST_LIVE_REQUEST",
        )
        decision = RoutingPolicy(capabilities=CapabilityRegistry((static, live))).decide(
            _request("quote AAPL"), task_intent=intent
        )
        self.assertEqual("live_provider", decision.capability_id)
        self.assertEqual("market.quote", decision.operation)
        self.assertEqual(RouteReasonCode.CATALOG_SINGLE_MATCH, decision.reason_code)

    def test_unavailable_candidate_is_visible_but_not_executable(self) -> None:
        capability = _SyntheticCapability(
            "disabled_finance",
            (
                _operation(
                    "valuation.analyze",
                    "Analyze company valuation",
                    domains=("finance",),
                    required_entities=("ticker_or_company",),
                ),
            ),
            available=False,
        )
        decision = RoutingPolicy(capabilities=CapabilityRegistry((capability,))).decide(
            _request("Analyze AAPL valuation")
        )
        self.assertFalse(decision.available)
        self.assertEqual(RouteReasonCode.CAPABILITY_UNAVAILABLE, decision.reason_code)
        self.assertEqual("SYNTHETIC_DISABLED", decision.diagnostic)

    def test_invented_selection_is_rejected_against_the_live_catalog(self) -> None:
        capability = _SyntheticCapability(
            "finance_capability",
            (
                _operation(
                    "valuation.analyze",
                    "Analyze company valuation",
                    domains=("finance",),
                    required_entities=("ticker_or_company",),
                ),
            ),
        )
        from elly.application.routing_contracts import CapabilitySelectionProposal

        selection = CapabilitySelectionProposal(
            capability_id="invented_capability",
            operation_id="valuation.analyze",
            arguments={"ticker": "AAPL"},
            confidence=1.0,
            ambiguity=IntentAmbiguity.CLEAR,
            rationale_code="MODEL_PROPOSAL",
        )
        decision = RoutingPolicy(capabilities=CapabilityRegistry((capability,))).decide(
            _request("Analyze AAPL valuation"), selection=selection
        )
        self.assertEqual(RouteReasonCode.SELECTION_PROPOSAL_REJECTED, decision.reason_code)
        self.assertEqual("CAPABILITY_NOT_REGISTERED", decision.diagnostic)
        self.assertEqual(Route.LOCAL_CONVERSATION, decision.route)

    def test_low_confidence_selection_does_not_execute(self) -> None:
        capability = _SyntheticCapability(
            "finance_capability",
            (
                _operation(
                    "valuation.analyze",
                    "Analyze company valuation",
                    domains=("finance",),
                    required_entities=("ticker_or_company",),
                ),
            ),
        )
        from elly.application.routing_contracts import CapabilitySelectionProposal

        selection = CapabilitySelectionProposal(
            capability_id="finance_capability",
            operation_id="valuation.analyze",
            arguments={"ticker": "AAPL"},
            confidence=0.1,
            ambiguity=IntentAmbiguity.CLEAR,
            rationale_code="MODEL_PROPOSAL",
        )
        decision = RoutingPolicy(capabilities=CapabilityRegistry((capability,))).decide(
            _request("Analyze AAPL valuation"), selection=selection
        )
        self.assertEqual(RouteReasonCode.SELECTION_PROPOSAL_REJECTED, decision.reason_code)
        self.assertEqual("LOW_CONFIDENCE", decision.diagnostic)

    def test_selector_rank_output_is_order_independent(self) -> None:
        operation = _operation(
            "record.lookup",
            "Look up a record",
            domains=("records",),
            freshness=FreshnessSupport.CURRENT,
            specificity=70,
        )
        first = _SyntheticCapability("zeta", (operation,))
        second = _SyntheticCapability("alpha", (operation,))
        catalog_a = CapabilityRegistry((first, second)).routing_catalog()
        catalog_b = CapabilityRegistry((second, first)).routing_catalog()
        intent = CatalogIntentInterpreter().interpret(_request("Look up a record"), catalog_a)
        selector = CatalogCandidateSelector()
        result_a = selector.select(intent, catalog_a)
        result_b = selector.select(intent, catalog_b)
        self.assertEqual(result_a.reason_code, result_b.reason_code)
        self.assertTrue(result_a.clarification_required)
        self.assertTrue(result_b.clarification_required)


if __name__ == "__main__":
    unittest.main()
