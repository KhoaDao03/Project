"""V2.5 Phase 0 characterization of the closed V2 routing surface."""

from __future__ import annotations

import unittest
from pathlib import Path

from elly.application.capabilities.registry import (
    CapabilityAvailability,
    CapabilityDescriptor,
    CapabilityMatch,
    CapabilityPreparation,
    CapabilityRegistry,
    CapabilityStatus,
)
from elly.application.routing.policy import RoutingPolicy
from elly.domain.enums import (
    CloudMode,
    IntentAmbiguity,
    OutcomeCode,
    Route,
    RouteReasonCode,
    TaskStatus,
)
from elly.domain.models import CapabilityIntent, RouteRequest

ROOT = Path(__file__).resolve().parents[1]


class _UnavailableCapability:
    """Minimal registered capability used to freeze unavailable behavior."""

    descriptor = CapabilityDescriptor(
        capability_id="web_research",
        description="test web research",
        routes=(Route.REGISTERED_CAPABILITY,),
        request_schema="web-research-v1",
        operations=("research.search",),
    )

    def status(self) -> CapabilityStatus:
        return CapabilityStatus(CapabilityAvailability.UNAVAILABLE, "TEST_DISABLED")

    def can_handle(self, _request: object) -> CapabilityMatch:
        return CapabilityMatch(True, "TEST_MATCH")

    def prepare(self, _intent: object, _request: object) -> CapabilityPreparation:
        return CapabilityPreparation(True, "TEST_PREPARED")

    def execute(self, _request: object) -> object:
        raise AssertionError("unavailable characterization capability must not execute")


def _request(text: str, contextual_text: str | None = None) -> RouteRequest:
    return RouteRequest(
        request_id="phase0-route",
        text=text,
        contextual_text=contextual_text,
        cloud_mode=CloudMode.LOCAL_ONLY,
    )


class V25Phase0StaticCharacterizationTests(unittest.TestCase):
    def test_legacy_interpreter_modules_are_removed(self) -> None:
        self.assertFalse((ROOT / "src/elly/application/legacy_routing.py").exists())
        self.assertFalse((ROOT / "src/elly/application/intent.py").exists())

    def test_fixed_route_map_is_removed_from_generic_policy(self) -> None:
        source = (ROOT / "src/elly/application/routing/policy.py").read_text(encoding="utf-8")
        self.assertNotIn('Route.WEB_RESEARCH: "web_research"', source)
        self.assertNotIn('Route.CODING_SPECIALIST: "coding"', source)
        self.assertNotIn('Route.RESEARCH_SPECIALIST: "research"', source)
        self.assertNotIn("_ROUTE_CAPABILITIES", source)
        self.assertNotIn("legacy_route_for_capability", source)

    def test_manifest_route_composition_replaces_role_based_branch(self) -> None:
        source = (ROOT / "src/elly/composition.py").read_text(encoding="utf-8")
        self.assertNotIn('if manifest.role == "coding"', source)
        self.assertNotIn('("coding", Route.CODING_SPECIALIST)', source)
        self.assertNotIn('("research", Route.RESEARCH_SPECIALIST)', source)
        self.assertNotIn("manifest.legacy_route", source)


class V25Phase0BehaviorCharacterizationTests(unittest.TestCase):
    def test_without_a_registry_requests_use_generic_local_conversation(self) -> None:
        policy = RoutingPolicy()
        for text in (
            "Explain dependency injection",
            "What is the latest Python release?",
            "debug this Python function",
            "analyze the evidence",
        ):
            with self.subTest(text=text):
                decision = policy.decide(_request(text))
                self.assertIs(decision.route, Route.LOCAL_CONVERSATION)
                self.assertIs(decision.reason_code, RouteReasonCode.LOCAL_DEFAULT)

    def test_context_does_not_activate_a_removed_legacy_route(self) -> None:
        decision = RoutingPolicy().decide(
            _request("how about now?", contextual_text="What is the latest gold price?")
        )
        self.assertIs(decision.route, Route.LOCAL_CONVERSATION)
        self.assertIs(decision.reason_code, RouteReasonCode.LOCAL_DEFAULT)

    def test_underspecified_specialist_request_stays_at_clarification(self) -> None:
        decision = RoutingPolicy().decide(_request("Ask a specialist to help me"))
        self.assertIs(decision.route, Route.LOCAL_CONVERSATION)
        self.assertFalse(decision.clarification_required)

    def test_unavailable_registered_capability_never_executes(self) -> None:
        registry = CapabilityRegistry((_UnavailableCapability(),))
        decision = RoutingPolicy(capabilities=registry).decide(
            _request("What is the latest gold price?"),
            intent=CapabilityIntent(
                proposed_capability_id="web_research",
                operation="research.search",
                arguments={"subject": "What is the latest gold price?"},
                confidence=1.0,
                ambiguity=IntentAmbiguity.CLEAR,
                rationale_code="TEST_SELECTION",
            ),
        )
        self.assertFalse(decision.available)
        self.assertIs(decision.route, Route.REGISTERED_CAPABILITY)
        self.assertIs(decision.reason_code, RouteReasonCode.CAPABILITY_UNAVAILABLE)
        self.assertEqual("TEST_DISABLED", decision.diagnostic)

    def test_historical_route_and_approval_contracts_remain_distinct(self) -> None:
        self.assertTrue(
            {
                "local_generalist",
                "web_research",
                "research_specialist",
                "coding_specialist",
            }
            <= {route.value for route in Route}
        )
        self.assertIn("local_conversation", {route.value for route in Route})
        self.assertIn("registered_capability", {route.value for route in Route})
        self.assertIsNot(TaskStatus.AWAITING_CONSENT, TaskStatus.AWAITING_CONFIRMATION)
        self.assertIsNot(OutcomeCode.AWAITING_CONSENT, OutcomeCode.AWAITING_CONFIRMATION)


if __name__ == "__main__":
    unittest.main()
