"""V2.5 Phase 4 web-research and freshness routing tests."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from elly.adapters.system_clock import FixedClock
from elly.application.capabilities.handlers import ResearchCapabilityHandler
from elly.application.capabilities.registry import CapabilityRegistry
from elly.application.capabilities.research import ResearchPipeline
from elly.application.capabilities.specialists import SpecialistWorkflow
from elly.application.routing.contracts import FreshnessSupport
from elly.application.routing.policy import RoutingPolicy
from elly.composition import _specialist_capability_handlers
from elly.domain.enums import CloudMode, IntentAmbiguity, Route, RouteReasonCode
from elly.domain.models import CapabilityIntent, RouteRequest
from elly.ports.web_research import ProviderCitation
from elly.research.fake_provider import FixtureWebResearchProvider
from elly.specialists.fake_provider import FakeSpecialistProvider
from elly.specialists.registry import SpecialistRegistry

UTC = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


def _request(text: str) -> RouteRequest:
    return RouteRequest(
        request_id="phase4-web-route",
        text=text,
        cloud_mode=CloudMode.CLOUD_PERMITTED,
    )


def _capability_registry() -> CapabilityRegistry:
    research = ResearchPipeline(
        provider=FixtureWebResearchProvider(),
        clock=FixedClock(UTC),
        max_results=3,
        timeout_seconds=1,
    )
    specialists = SpecialistRegistry.from_directory(
        "config/specialists", default_model="central-model"
    )
    return CapabilityRegistry(
        (
            ResearchCapabilityHandler(research, provider_id="fixtures"),
            *_specialist_capability_handlers(
                specialists,
                SpecialistWorkflow(provider=FakeSpecialistProvider()),
            ),
        )
    )


class Phase4WebFreshnessTests(unittest.TestCase):
    def test_web_research_publishes_normal_current_and_live_operations(self) -> None:
        descriptor = ResearchCapabilityHandler(None).descriptor
        assert descriptor.routing is not None
        operations = {
            operation.operation_id: operation for operation in descriptor.routing.operations
        }

        self.assertEqual(
            {
                "research.search",
                "public_information.search",
                "news.current",
                "release.lookup",
                "market.quote",
            },
            set(operations),
        )
        self.assertIs(FreshnessSupport.CURRENT, operations["news.current"].freshness)
        self.assertIs(FreshnessSupport.CURRENT, operations["release.lookup"].freshness)
        self.assertIs(FreshnessSupport.LIVE, operations["market.quote"].freshness)
        self.assertEqual(
            ("ticker", "company", "security"), operations["market.quote"].optional_entities
        )

    def test_web_operations_are_selected_by_operation_and_freshness(self) -> None:
        registry = _capability_registry()
        policy = RoutingPolicy(capabilities=registry)
        cases = (
            (
                "Search public information about Apple",
                "public_information.search",
            ),
            ("What is the latest news about Apple?", "news.current"),
            ("What is the latest Python release?", "release.lookup"),
            ("What is AAPL trading at?", "market.quote"),
            ("What is the current S&P500 index?", "market.quote"),
        )
        for text, operation in cases:
            with self.subTest(text=text):
                decision = policy.decide(_request(text))
                self.assertEqual("web_research", decision.capability_id)
                self.assertEqual(operation, decision.operation)
                self.assertEqual(Route.REGISTERED_CAPABILITY, decision.route)
                self.assertEqual(RouteReasonCode.CATALOG_SINGLE_MATCH, decision.reason_code)

    def test_live_quote_prefers_web_over_analysis_only_stock(self) -> None:
        registry = _capability_registry()
        decision = RoutingPolicy(capabilities=registry).decide(_request("What is AAPL trading at?"))

        self.assertEqual("web_research", decision.capability_id)
        self.assertEqual("market.quote", decision.operation)
        stock = registry.get("stock_analysis")
        assert stock is not None
        assert stock.descriptor.routing is not None
        self.assertNotIn(
            FreshnessSupport.LIVE,
            tuple(operation.freshness for operation in stock.descriptor.routing.operations),
        )

    def test_valuation_still_prefers_stock_analysis(self) -> None:
        decision = RoutingPolicy(capabilities=_capability_registry()).decide(
            _request("Analyze Apple's valuation")
        )

        self.assertEqual("stock_analysis", decision.capability_id)
        self.assertEqual("valuation.analyze", decision.operation)
        self.assertEqual(RouteReasonCode.CATALOG_SINGLE_MATCH, decision.reason_code)

    def test_underspecified_specialist_request_requires_clarification(self) -> None:
        decision = RoutingPolicy(capabilities=_capability_registry()).decide(
            _request("Use a specialist for this")
        )

        self.assertTrue(decision.clarification_required)
        self.assertEqual(RouteReasonCode.CATALOG_AMBIGUOUS, decision.reason_code)
        self.assertIsNone(decision.capability_id)

    def test_explicit_research_specialist_request_preserves_v2_behavior(self) -> None:
        decision = RoutingPolicy(capabilities=_capability_registry()).decide(
            _request("Use the research specialist")
        )

        self.assertEqual("research", decision.capability_id)
        self.assertEqual("specialist.analyze", decision.operation)
        self.assertEqual(Route.REGISTERED_CAPABILITY, decision.route)

    def test_consequential_financial_request_is_rejected_without_clarification(self) -> None:
        decision = RoutingPolicy(capabilities=_capability_registry()).decide(
            _request("Buy ten Apple shares")
        )

        self.assertEqual(RouteReasonCode.ACTION_UNSUPPORTED, decision.reason_code)
        self.assertFalse(decision.clarification_required)
        self.assertIsNone(decision.capability_id)
        assert decision.intent is not None
        self.assertEqual("Apple", decision.intent.arguments.get("company"))

    def test_legacy_web_operation_remains_preparable(self) -> None:
        handler = ResearchCapabilityHandler(None)
        intent = CapabilityIntent(
            proposed_capability_id="web_research",
            operation="research.search",
            arguments={"subject": "latest public information"},
            confidence=1.0,
            ambiguity=IntentAmbiguity.CLEAR,
            rationale_code="LEGACY_TEST",
        )

        preparation = handler.prepare(intent, None)  # type: ignore[arg-type]

        self.assertTrue(preparation.accepted)

    def test_declared_current_operation_controls_evidence_freshness(self) -> None:
        old = UTC - timedelta(days=31)
        provider = FixtureWebResearchProvider(
            answer="The release was published.",
            citations=(
                ProviderCitation(
                    "https://example.com/release",
                    "Python release",
                    snippet="The release was published.",
                    supporting_passage="The release was published.",
                    retrieved_at=old,
                ),
            ),
        )
        pipeline = ResearchPipeline(
            provider=provider,
            clock=FixedClock(UTC),
            max_results=3,
            timeout_seconds=1,
        )

        current = pipeline.execute("release lookup", current_information=True)
        static = pipeline.execute("release lookup", current_information=False)

        self.assertEqual((), current.evidence)
        self.assertEqual(1, len(static.evidence))


if __name__ == "__main__":
    unittest.main()
