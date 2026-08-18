"""Pure routing-policy tests; no model, database, CLI, or network."""

from __future__ import annotations

import inspect
import unittest

from elly.application.capabilities import (
    CapabilityAvailability,
    CapabilityDescriptor,
    CapabilityExecution,
    CapabilityMatch,
    CapabilityPreparation,
    CapabilityRegistry,
    CapabilityRequest,
    CapabilityStatus,
)
from elly.application.routing import RoutingPolicy
from elly.application.routing_contracts import TaskIntent
from elly.domain.enums import CloudMode, IntentAmbiguity, Route, RouteReasonCode
from elly.domain.models import CapabilityIntent, RouteProposal, RouteRequest


class _AvailableCapability:
    def __init__(self, capability_id: str, route: Route, available: bool = True) -> None:
        self.descriptor = CapabilityDescriptor(
            capability_id=capability_id,
            description="test",
            routes=(route,),
            request_schema=f"{capability_id}-v1",
            operations=("test.execute",),
        )
        self._available = available

    def status(self) -> CapabilityStatus:
        return CapabilityStatus(
            CapabilityAvailability.AVAILABLE
            if self._available
            else CapabilityAvailability.UNAVAILABLE,
            "TEST_DISABLED" if not self._available else "",
        )

    def can_handle(self, _request: CapabilityRequest) -> CapabilityMatch:
        return CapabilityMatch(True, "TEST_ROUTE")

    def prepare(
        self, _intent: CapabilityIntent, _request: CapabilityRequest
    ) -> CapabilityPreparation:
        return CapabilityPreparation(True, "TEST_INPUT_ACCEPTED")

    def execute(self, _request: CapabilityRequest) -> CapabilityExecution:
        raise AssertionError("routing test capability must not execute")


def _request(text: str, contextual_text: str | None = None) -> RouteRequest:
    return RouteRequest(
        request_id="r1",
        text=text,
        contextual_text=contextual_text,
        cloud_mode=CloudMode.LOCAL_ONLY,
    )


class RoutingPolicyTests(unittest.TestCase):
    def test_canonical_decision_branch_has_only_canonical_inputs(self) -> None:
        parameters = tuple(inspect.signature(RoutingPolicy._decide_canonical).parameters)
        self.assertEqual(
            ("self", "request", "task_intent", "selection"),
            parameters,
        )

    def test_legacy_capability_intent_is_translated_to_selection(self) -> None:
        registry = CapabilityRegistry(
            (_AvailableCapability("test_capability", Route.REGISTERED_CAPABILITY),)
        )
        decision = RoutingPolicy(capabilities=registry).decide(
            _request("run the test capability"),
            intent=CapabilityIntent(
                proposed_capability_id="test_capability",
                operation="test.execute",
                arguments={"subject": "run the test capability"},
                confidence=1.0,
                ambiguity=IntentAmbiguity.CLEAR,
                rationale_code="LEGACY_TEST_HINT",
            ),
        )

        self.assertEqual(Route.REGISTERED_CAPABILITY, decision.route)
        self.assertIsNotNone(decision.selection)
        assert decision.selection is not None
        self.assertEqual("test_capability", decision.selection.capability_id)
        self.assertEqual("test.execute", decision.selection.operation_id)
        self.assertIsInstance(decision.intent, TaskIntent)

    def test_legacy_route_proposal_is_revalidated_before_canonical_decision(self) -> None:
        registry = CapabilityRegistry(
            (_AvailableCapability("test_capability", Route.REGISTERED_CAPABILITY),)
        )
        decision = RoutingPolicy(capabilities=registry).decide(
            _request("run the test capability"),
            proposal=RouteProposal(
                route=Route.REGISTERED_CAPABILITY,
                capability_id="test_capability",
                request_schema="test_capability-v1",
            ),
        )

        self.assertEqual(Route.REGISTERED_CAPABILITY, decision.route)
        self.assertIsNotNone(decision.selection)
        assert decision.selection is not None
        self.assertEqual("test.execute", decision.selection.operation_id)

    def test_without_catalog_evidence_uses_generic_local_route(self) -> None:
        policy = RoutingPolicy()
        for text in (
            "Explain recursion",
            "What is the latest gold price?",
            "debug this Python function",
            "analyze the evidence",
        ):
            with self.subTest(text=text):
                self.assertEqual(policy.decide(_request(text)).route, Route.LOCAL_CONVERSATION)

    def test_route_has_safe_reason_code(self) -> None:
        decision = RoutingPolicy().decide(_request("What is the latest news?"))
        self.assertEqual(decision.reason_code, RouteReasonCode.LOCAL_DEFAULT)

    def test_dependent_context_can_inherit_current_information(self) -> None:
        decision = RoutingPolicy().decide(
            _request("how about now?", contextual_text="What is the latest gold price?")
        )
        self.assertEqual(decision.route, Route.LOCAL_CONVERSATION)

    def test_unavailable_capability_is_not_executable(self) -> None:
        registry = CapabilityRegistry(
            (_AvailableCapability("web_research", Route.REGISTERED_CAPABILITY, available=False),)
        )
        decision = RoutingPolicy(capabilities=registry).decide(
            _request("What is the latest gold price?"),
            intent=CapabilityIntent(
                proposed_capability_id="web_research",
                operation="test.execute",
                arguments={"subject": "gold"},
                confidence=1.0,
                ambiguity=IntentAmbiguity.CLEAR,
                rationale_code="TEST_SELECTION",
            ),
        )
        self.assertFalse(decision.available)
        self.assertEqual(decision.reason_code, RouteReasonCode.CAPABILITY_UNAVAILABLE)
        self.assertEqual(Route.REGISTERED_CAPABILITY, decision.route)
        self.assertFalse(hasattr(decision, "compatibility_view"))

    def test_unregistered_proposal_is_rejected_and_falls_back(self) -> None:
        registry = CapabilityRegistry()
        decision = RoutingPolicy(capabilities=registry).decide(
            _request("hello"),
            proposal=RouteProposal(capability_id="missing", request_schema="missing-v1"),
        )
        self.assertEqual(decision.route, Route.LOCAL_CONVERSATION)
        self.assertEqual(decision.reason_code, RouteReasonCode.SELECTION_PROPOSAL_REJECTED)


if __name__ == "__main__":
    unittest.main()
