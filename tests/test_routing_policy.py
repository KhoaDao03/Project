"""Pure routing-policy tests; no model, database, CLI, or network."""

from __future__ import annotations

import unittest

from elly.application.capabilities import (
    CapabilityAvailability,
    CapabilityDescriptor,
    CapabilityExecution,
    CapabilityMatch,
    CapabilityRegistry,
    CapabilityRequest,
    CapabilityStatus,
)
from elly.application.routing import RoutingPolicy
from elly.domain.enums import CloudMode, Route, RouteReasonCode
from elly.domain.models import RouteProposal, RouteRequest


class _AvailableCapability:
    def __init__(self, capability_id: str, route: Route, available: bool = True) -> None:
        self.descriptor = CapabilityDescriptor(
            capability_id=capability_id,
            description="test",
            routes=(route,),
            request_schema=f"{capability_id}-v1",
        )
        self._available = available

    def status(self) -> CapabilityStatus:
        return CapabilityStatus(
            CapabilityAvailability.AVAILABLE if self._available else CapabilityAvailability.UNAVAILABLE,
            "TEST_DISABLED" if not self._available else "",
        )

    def can_handle(self, _request: CapabilityRequest) -> CapabilityMatch:
        return CapabilityMatch(True, "TEST_ROUTE")

    def execute(self, _request: CapabilityRequest) -> CapabilityExecution:
        raise AssertionError("routing test capability must not execute")


def _request(text: str, contextual_text: str | None = None) -> RouteRequest:
    return RouteRequest(
        request_id="r1", text=text, contextual_text=contextual_text,
        cloud_mode=CloudMode.LOCAL_ONLY,
    )


class RoutingPolicyTests(unittest.TestCase):
    def test_preserves_v1_route_rules(self) -> None:
        policy = RoutingPolicy()
        self.assertEqual(policy.decide(_request("Explain recursion")).route, Route.LOCAL_GENERALIST)
        self.assertEqual(policy.decide(_request("What is the latest gold price?")).route, Route.WEB_RESEARCH)
        self.assertEqual(policy.decide(_request("debug this Python function")).route, Route.CODING_SPECIALIST)
        self.assertEqual(policy.decide(_request("analyze the evidence")).route, Route.RESEARCH_SPECIALIST)

    def test_route_has_safe_reason_code(self) -> None:
        decision = RoutingPolicy().decide(_request("What is the latest news?"))
        self.assertEqual(decision.reason_code, RouteReasonCode.CURRENT_INFORMATION_REQUIRED)

    def test_dependent_context_can_inherit_current_information(self) -> None:
        decision = RoutingPolicy().decide(
            _request("how about now?", contextual_text="What is the latest gold price?")
        )
        self.assertEqual(decision.route, Route.WEB_RESEARCH)

    def test_unavailable_capability_is_not_executable(self) -> None:
        registry = CapabilityRegistry(
            (_AvailableCapability("web_research", Route.WEB_RESEARCH, available=False),)
        )
        decision = RoutingPolicy(capabilities=registry).decide(
            _request("What is the latest gold price?")
        )
        self.assertFalse(decision.available)
        self.assertEqual(decision.reason_code, RouteReasonCode.CAPABILITY_UNAVAILABLE)

    def test_unregistered_proposal_is_rejected_and_falls_back(self) -> None:
        registry = CapabilityRegistry()
        decision = RoutingPolicy(capabilities=registry).decide(
            _request("hello"),
            proposal=RouteProposal(capability_id="missing", request_schema="missing-v1"),
        )
        self.assertEqual(decision.route, Route.LOCAL_GENERALIST)
        self.assertEqual(decision.reason_code, RouteReasonCode.PROPOSAL_REJECTED)


if __name__ == "__main__":
    unittest.main()
