"""Provider-free Phase 1 routing-contract and catalog tests."""

from __future__ import annotations

import unittest

from elly.application.capabilities import (
    CandidateMatch,
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
    MatchStrength,
    OperationIntentContract,
    TaskIntent,
)
from elly.domain.enums import ActionCategory, IntentAmbiguity, IntentEntitySource, Route
from elly.domain.errors import ConfigInvalidError, InputInvalidError
from elly.domain.models import IntentEntity


def _operation(
    operation_id: str = "finance.analyze",
    *,
    effect: ActionCategory = ActionCategory.NONE,
    freshness: FreshnessSupport = FreshnessSupport.PREFERRED,
) -> OperationIntentContract:
    return OperationIntentContract(
        operation_id=operation_id,
        description="Analyze a bounded public-company request",
        domains=("finance", "analysis"),
        accepted_inputs=("text", "ticker"),
        required_entities=("ticker_or_company",),
        freshness=freshness,
        effect=effect,
        specificity=80,
        examples=("Analyze AAPL valuation",),
        counterexamples=("Buy AAPL shares",),
    )


def _routing(
    capability_id: str,
    operation: OperationIntentContract | None = None,
    *,
    priority: int = 50,
) -> CapabilityRoutingDescriptor:
    return CapabilityRoutingDescriptor(
        capability_id=capability_id,
        description="A safe catalog test capability",
        operations=(operation or _operation(),),
        priority=priority,
    )


class _CatalogHandler:
    def __init__(self, capability_id: str, *, available: bool = True, routing=None) -> None:
        operation = routing.operations[0] if routing is not None else _operation()
        self.descriptor = CapabilityDescriptor(
            capability_id=capability_id,
            description="A safe catalog test capability",
            routes=(Route.CODING_SPECIALIST,),
            request_schema=f"{capability_id}-v1",
            operations=(operation.operation_id,),
            routing=(routing or _routing(capability_id, operation)),
        )
        self._available = available

    def status(self) -> CapabilityStatus:
        return CapabilityStatus(
            CapabilityAvailability.AVAILABLE
            if self._available
            else CapabilityAvailability.UNAVAILABLE,
            "" if self._available else "TEST_DISABLED",
        )

    def can_handle(self, _request: CapabilityRequest) -> CapabilityMatch:
        return CapabilityMatch(True, "TEST_MATCH")

    def prepare(self, _intent, _request: CapabilityRequest) -> CapabilityPreparation:
        return CapabilityPreparation(True, "TEST_PREPARED")

    def execute(self, _request: CapabilityRequest) -> CapabilityExecution:
        raise AssertionError("catalog tests must not execute a provider")


class RoutingContractValidationTests(unittest.TestCase):
    def test_operation_contract_accepts_typed_metadata(self) -> None:
        operation = _operation()
        self.assertEqual("finance.analyze", operation.operation_id)
        self.assertEqual(FreshnessSupport.PREFERRED, operation.freshness)
        self.assertEqual(("ticker_or_company",), operation.required_entities)

    def test_invalid_input_entity_freshness_and_priority_fail_as_config_errors(self) -> None:
        with self.assertRaises(ConfigInvalidError):
            OperationIntentContract(
                "finance.analyze",
                "description",
                ("finance",),
                ("email",),
                (),
            )
        with self.assertRaises(ConfigInvalidError):
            OperationIntentContract(
                "finance.analyze",
                "description",
                ("finance",),
                ("text",),
                ("unknown_entity",),
            )
        with self.assertRaises(ConfigInvalidError):
            OperationIntentContract(
                "finance.analyze",
                "description",
                ("finance",),
                ("text",),
                (),
                freshness="not-a-freshness",  # type: ignore[arg-type]
            )
        with self.assertRaises(ConfigInvalidError):
            CapabilityRoutingDescriptor(
                "finance",
                "description",
                (_operation(),),
                priority=101,
            )

    def test_duplicate_operations_and_mismatched_effects_fail_startup_validation(self) -> None:
        with self.assertRaises(ConfigInvalidError):
            CapabilityRoutingDescriptor(
                "finance",
                "description",
                (_operation(), _operation()),
            )
        effectful = _operation(effect=ActionCategory.DELETE)
        with self.assertRaises(ConfigInvalidError):
            CapabilityDescriptor(
                capability_id="finance",
                description="finance",
                routes=(Route.CODING_SPECIALIST,),
                request_schema="finance-v1",
                operations=(effectful.operation_id,),
                routing=_routing("finance", effectful),
            )

    def test_task_intent_and_selection_values_are_immutable_and_typed(self) -> None:
        intent = TaskIntent(
            requested_operation="valuation.analyze",
            domain="finance",
            entities=(IntentEntity("ticker", "AAPL", IntentEntitySource.EXPLICIT),),
            arguments={"ticker": "AAPL"},
            freshness=FreshnessRequirement.PREFERRED,
            confidence=0.9,
            ambiguity=IntentAmbiguity.CLEAR,
            rationale_code="EXPLICIT_OPERATION",
        )
        with self.assertRaises(TypeError):
            intent.arguments["ticker"] = "MSFT"  # type: ignore[index]
        candidate = CandidateMatch(
            capability_id="finance",
            operation_id="valuation.analyze",
            compatible=True,
            required_inputs_satisfied=True,
            operation_match=MatchStrength.EXACT,
            freshness_match=MatchStrength.PREFERRED,
            domain_specificity=90,
            declared_priority=50,
        )
        self.assertTrue(candidate.compatible)
        with self.assertRaises(InputInvalidError):
            TaskIntent(
                requested_operation="valuation.analyze",
                domain="finance",
                entities=(IntentEntity("email", "owner@example.com", IntentEntitySource.EXPLICIT),),
                rationale_code="INVALID_ENTITY",
            )


class RoutingCatalogTests(unittest.TestCase):
    def test_catalog_is_sorted_immutable_and_contains_no_executable_collaborators(self) -> None:
        registry = CapabilityRegistry(
            (
                _CatalogHandler("zeta"),
                _CatalogHandler("alpha", available=False),
            )
        )
        catalog = registry.routing_catalog()
        self.assertEqual(("alpha", "zeta"), tuple(item.capability_id for item in catalog))
        self.assertFalse(catalog[0].available)
        self.assertEqual("TEST_DISABLED", catalog[0].availability_reason)
        self.assertFalse(hasattr(catalog[0], "handler"))
        self.assertFalse(hasattr(catalog[0], "provider"))
        with self.assertRaises((AttributeError, TypeError)):
            catalog[0].operations += ()  # type: ignore[misc]

    def test_legacy_descriptor_gets_a_conservative_catalog_contract(self) -> None:
        class LegacyHandler(_CatalogHandler):
            def __init__(self) -> None:
                self.descriptor = CapabilityDescriptor(
                    capability_id="legacy",
                    description="legacy capability",
                    routes=(Route.CODING_SPECIALIST,),
                    request_schema="legacy-v1",
                    operations=("legacy.execute",),
                )
                self._available = True

        catalog = CapabilityRegistry((LegacyHandler(),)).routing_catalog()
        self.assertEqual("legacy.execute", catalog[0].operations[0].operation_id)
        self.assertEqual(FreshnessSupport.STATIC, catalog[0].operations[0].freshness)

    def test_catalog_snapshot_does_not_change_when_handler_status_changes(self) -> None:
        handler = _CatalogHandler("toggle")
        registry = CapabilityRegistry((handler,))
        first = registry.routing_catalog()
        handler._available = False
        second = registry.routing_catalog()
        self.assertTrue(first[0].available)
        self.assertFalse(second[0].available)


if __name__ == "__main__":
    unittest.main()
