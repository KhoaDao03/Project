"""Phase 2 proposal contracts, planner adapters, and safe interpretation."""

from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError
from typing import Any
from unittest.mock import patch

from elly.adapters.fake_planner import FakePlanner, PlannerFailureMode
from elly.adapters.ollama_planner import OllamaPlanner
from elly.adapters.recorded_planner import RecordedPlanner
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
    FreshnessSupport,
    OperationIntentContract,
)
from elly.application.plan_interpreter import PlanInterpreter
from elly.config import LocalModelProfile, LocalModelRoleConfig
from elly.domain.enums import CloudMode, Route, RouteReasonCode
from elly.domain.errors import (
    CancelledError,
    InputInvalidError,
    MalformedResultError,
)
from elly.domain.models import ActionProposal, RouteRequest
from elly.planning.catalog import build_planner_catalog, planner_catalog_to_dict
from elly.planning.codec import decode_proposal, encode_proposal, proposal_to_dict
from elly.planning.contracts import (
    MAX_PROPOSAL_BYTES,
    PROPOSAL_SCHEMA_VERSION,
    ClarificationField,
    ExecutionProposal,
    FinalizationStrategy,
    ProposalDisposition,
    ProposedInput,
    ProposedStep,
)
from elly.ports.local_planner import LocalPlannerPort, PlannerRequest


def _operation(
    operation_id: str,
    description: str,
    *,
    domains: tuple[str, ...] = ("general",),
    required_entities: tuple[str, ...] = (),
    freshness: FreshnessSupport = FreshnessSupport.STATIC,
    examples: tuple[str, ...] = (),
) -> OperationIntentContract:
    return OperationIntentContract(
        operation_id=operation_id,
        description=description,
        domains=domains,
        accepted_inputs=("text", "ticker"),
        required_entities=required_entities,
        freshness=freshness,
        examples=examples,
    )


class _Capability:
    def __init__(
        self,
        capability_id: str,
        operations: tuple[OperationIntentContract, ...],
        *,
        available: bool = True,
    ) -> None:
        self.descriptor = CapabilityDescriptor(
            capability_id=capability_id,
            description=f"{capability_id} test capability",
            routes=(Route.CODING_SPECIALIST,),
            request_schema=f"{capability_id}-v1",
            operations=tuple(item.operation_id for item in operations),
            declared_action=ActionProposal.none(),
            routing=CapabilityRoutingDescriptor(
                capability_id=capability_id,
                description=f"{capability_id} test capability",
                operations=operations,
            ),
        )
        self._available = available
        self.executions = 0

    def status(self) -> CapabilityStatus:
        return CapabilityStatus(
            CapabilityAvailability.AVAILABLE
            if self._available
            else CapabilityAvailability.UNAVAILABLE,
            "" if self._available else "TEST_DISABLED",
        )

    def can_handle(self, _request: CapabilityRequest) -> CapabilityMatch:
        return CapabilityMatch(True, "TEST_MATCH")

    def prepare(self, _intent: object, _request: CapabilityRequest) -> CapabilityPreparation:
        return CapabilityPreparation(True, "TEST_PREPARED")

    def execute(self, _request: CapabilityRequest) -> CapabilityExecution:
        self.executions += 1
        raise AssertionError("Phase 2 must not execute capabilities")


def _request(text: str) -> RouteRequest:
    return RouteRequest("phase2-planner", text, cloud_mode=CloudMode.LOCAL_ONLY)


def _proposal(
    capability_id: str,
    operation_id: str,
    *,
    inputs: tuple[ProposedInput, ...] = (),
    dependencies: tuple[str, ...] = (),
    step_id: str = "step-one",
    verification: bool = False,
) -> ExecutionProposal:
    return ExecutionProposal(
        schema_version=PROPOSAL_SCHEMA_VERSION,
        disposition=ProposalDisposition.CAPABILITY_PLAN,
        steps=(
            ProposedStep(
                proposal_step_id=step_id,
                capability_id=capability_id,
                operation_id=operation_id,
                objective="complete the bounded test objective",
                objective_class="analysis",
                perspective="primary",
                inputs=inputs,
                dependencies=dependencies,
                expected_output_type="task_result",
                verification=verification,
            ),
        ),
        finalization=FinalizationStrategy.DIRECT,
        ambiguities=(),
        confidence=0.9,
        reason_code="TEST_PROPOSAL",
        justification="bounded test proposal",
    )


class ProposalContractTests(unittest.TestCase):
    def test_round_trip_is_strict_and_immutable(self) -> None:
        proposal = _proposal(
            "finance_capability",
            "valuation.analyze",
            inputs=(ProposedInput("ticker", "ticker"),),
        )
        self.assertEqual(proposal, decode_proposal(encode_proposal(proposal)))
        with self.assertRaises(FrozenInstanceError):
            proposal.reason_code = "changed"  # type: ignore[misc]

    def test_unknown_fields_invalid_json_and_excessive_output_are_rejected(self) -> None:
        value = proposal_to_dict(
            ExecutionProposal(
                PROPOSAL_SCHEMA_VERSION,
                ProposalDisposition.LOCAL_ONLY,
                (),
                FinalizationStrategy.DIRECT,
                (),
                1.0,
                "TEST_LOCAL",
                "bounded local proposal",
            )
        )
        value["unexpected"] = True
        with self.assertRaises(MalformedResultError):
            decode_proposal(value)
        with self.assertRaises(MalformedResultError):
            decode_proposal("not-json")
        with self.assertRaises(MalformedResultError):
            decode_proposal("x" * (MAX_PROPOSAL_BYTES + 1))

    def test_unsafe_ids_and_invalid_dependency_references_fail_closed(self) -> None:
        with self.assertRaises(InputInvalidError):
            ProposedStep(
                "step-one",
                "../../provider",
                "operation.run",
                "objective",
                "analysis",
                "primary",
            )
        with self.assertRaises(InputInvalidError):
            ProposedInput("input", "text", source="step")
        with self.assertRaises(InputInvalidError):
            ProposedInput("input", "text", source="provider", reference="openai")
        with self.assertRaises(InputInvalidError):
            ExecutionProposal(
                PROPOSAL_SCHEMA_VERSION,
                ProposalDisposition.CAPABILITY_PLAN,
                (
                    ProposedStep(
                        "step-one",
                        "capability",
                        "operation.run",
                        "objective",
                        "analysis",
                        "primary",
                        dependencies=("missing-step",),
                    ),
                ),
                FinalizationStrategy.DIRECT,
                (),
                0.9,
                "TEST_PROPOSAL",
                "bounded test proposal",
            )


class PlannerAdapterTests(unittest.TestCase):
    def _planner_request(self) -> PlannerRequest:
        catalog = build_planner_catalog(())
        return PlannerRequest(
            request_id="planner-request",
            text="hello",
            approved_context="none",
            catalog=catalog,
            max_output_tokens=100,
            timeout_seconds=5.0,
        )

    def test_fake_recorded_and_protocol_adapters_are_provider_free(self) -> None:
        proposal = ExecutionProposal(
            PROPOSAL_SCHEMA_VERSION,
            ProposalDisposition.LOCAL_ONLY,
            (),
            FinalizationStrategy.DIRECT,
            (),
            1.0,
            "TEST_LOCAL",
            "bounded local proposal",
        )
        request = self._planner_request()
        fake = FakePlanner(encode_proposal(proposal))
        self.assertIsInstance(fake, LocalPlannerPort)
        self.assertEqual(proposal, fake.propose(request))
        recorded = RecordedPlanner((proposal,))
        self.assertIsInstance(recorded, LocalPlannerPort)
        self.assertEqual(proposal, recorded.propose(request))
        with self.assertRaises(MalformedResultError):
            FakePlanner(failure=PlannerFailureMode.MALFORMED).propose(request)

    def test_cancellation_is_preserved_at_the_planner_boundary(self) -> None:
        planner = FakePlanner()
        planner.cancel()
        with self.assertRaises(CancelledError):
            planner.propose(self._planner_request())


class PlannerCatalogTests(unittest.TestCase):
    def test_catalog_is_sorted_deterministic_and_contains_only_safe_metadata(self) -> None:
        first = _Capability(
            "zeta_capability",
            (_operation("zeta.inspect", "Inspect a bounded request"),),
        )
        second = _Capability(
            "alpha_capability",
            (_operation("alpha.inspect", "Inspect a bounded request"),),
        )
        first_catalog = build_planner_catalog(CapabilityRegistry((first, second)).routing_catalog())
        second_catalog = build_planner_catalog(
            CapabilityRegistry((second, first)).routing_catalog()
        )
        self.assertEqual(first_catalog, second_catalog)
        self.assertEqual(("alpha_capability", "zeta_capability"), first_catalog.capability_ids)
        encoded = planner_catalog_to_dict(first_catalog)
        encoded_text = json.dumps(encoded)
        self.assertNotIn("handler", encoded_text)
        self.assertNotIn("provider", encoded_text)
        self.assertNotIn("model", encoded_text)
        self.assertNotIn("endpoint", encoded_text)
        with self.assertRaises((FrozenInstanceError, TypeError, AttributeError)):
            first_catalog.capabilities += ()  # type: ignore[misc]


class PlanInterpreterTests(unittest.TestCase):
    def _registry(
        self, *, available: bool = True
    ) -> tuple[CapabilityRegistry, _Capability, _Capability]:
        research = _Capability(
            "research_capability",
            (
                _operation(
                    "research.search",
                    "Research current public information",
                    domains=("research",),
                    required_entities=("ticker_or_company",),
                    freshness=FreshnessSupport.CURRENT,
                    examples=("Research current information about AAPL",),
                ),
            ),
            available=available,
        )
        finance = _Capability(
            "finance_capability",
            (
                _operation(
                    "valuation.analyze",
                    "Analyze company valuation",
                    domains=("finance",),
                    required_entities=("ticker_or_company",),
                    examples=("Analyze AAPL valuation",),
                ),
            ),
            available=available,
        )
        return CapabilityRegistry((research, finance)), research, finance

    def test_local_only_and_clarification_are_typed_decisions(self) -> None:
        registry, _, _ = self._registry()
        local = ExecutionProposal(
            PROPOSAL_SCHEMA_VERSION,
            ProposalDisposition.LOCAL_ONLY,
            (),
            FinalizationStrategy.DIRECT,
            (),
            0.8,
            "LOCAL_REQUEST",
            "keep the request local",
        )
        local_decision = PlanInterpreter(
            planner=FakePlanner(local), capabilities=registry
        ).interpret(_request("Say hello"))
        self.assertTrue(local_decision.accepted)
        self.assertEqual(Route.LOCAL_CONVERSATION, local_decision.route_decision.route)
        self.assertEqual(
            RouteReasonCode.PROPOSAL_ACCEPTED, local_decision.route_decision.reason_code
        )

        clarification = ExecutionProposal(
            PROPOSAL_SCHEMA_VERSION,
            ProposalDisposition.CLARIFICATION_REQUIRED,
            (),
            FinalizationStrategy.DIRECT,
            (ClarificationField("ticker", "MISSING_INPUT", "Which company?"),),
            0.4,
            "MISSING_INPUT",
            "the company is unspecified",
        )
        clarification_decision = PlanInterpreter(
            planner=FakePlanner(clarification), capabilities=registry
        ).interpret(_request("Analyze valuation"))
        self.assertTrue(clarification_decision.accepted)
        self.assertTrue(clarification_decision.route_decision.clarification_required)
        self.assertEqual(("ticker",), clarification_decision.route_decision.clarification_fields)

    def test_single_capability_is_validated_against_the_fresh_catalog(self) -> None:
        registry, _, finance = self._registry()
        proposal = _proposal(
            "finance_capability",
            "valuation.analyze",
            inputs=(ProposedInput("ticker", "ticker"),),
        )
        decision = PlanInterpreter(planner=FakePlanner(proposal), capabilities=registry).interpret(
            _request("Analyze AAPL valuation")
        )
        self.assertTrue(decision.accepted)
        self.assertFalse(decision.fallback_used)
        self.assertEqual(Route.REGISTERED_CAPABILITY, decision.route_decision.route)
        self.assertEqual("finance_capability", decision.route_decision.capability_id)
        self.assertEqual("valuation.analyze", decision.route_decision.operation)
        self.assertEqual(0, finance.executions)

    def test_registry_change_after_planning_is_revalidated(self) -> None:
        registry, _, finance = self._registry()
        proposal = _proposal(
            "finance_capability",
            "valuation.analyze",
            inputs=(ProposedInput("ticker", "ticker"),),
        )

        class _StalingPlanner(FakePlanner):
            def propose(self, request: PlannerRequest) -> ExecutionProposal:
                result = super().propose(request)
                finance._available = False
                return result

        decision = PlanInterpreter(
            planner=_StalingPlanner(proposal), capabilities=registry
        ).interpret(_request("Analyze AAPL valuation"))
        self.assertFalse(decision.accepted)
        self.assertTrue(decision.fallback_used)
        self.assertEqual("CAPABILITY_UNAVAILABLE", decision.rejection_code)
        self.assertFalse(decision.route_decision.available)

    def test_multi_capability_proposal_is_advisory_and_not_executed(self) -> None:
        registry, research, finance = self._registry()
        proposal = ExecutionProposal(
            PROPOSAL_SCHEMA_VERSION,
            ProposalDisposition.CAPABILITY_PLAN,
            (
                ProposedStep(
                    "research-step",
                    "research_capability",
                    "research.search",
                    "find current public information",
                    "evidence",
                    "market",
                    (ProposedInput("ticker", "ticker"),),
                ),
                ProposedStep(
                    "finance-step",
                    "finance_capability",
                    "valuation.analyze",
                    "analyze valuation using the evidence",
                    "analysis",
                    "fundamental",
                    (ProposedInput("ticker", "ticker"),),
                    dependencies=("research-step",),
                ),
            ),
            FinalizationStrategy.LOCAL_SYNTHESIS,
            (),
            0.9,
            "MULTI_CAPABILITY",
            "research and analysis are both bounded",
        )
        decision = PlanInterpreter(planner=FakePlanner(proposal), capabilities=registry).interpret(
            _request("Research AAPL information and analyze valuation")
        )
        self.assertTrue(decision.accepted)
        self.assertEqual(Route.LOCAL_CONVERSATION, decision.route_decision.route)
        self.assertEqual("plan.execute", decision.route_decision.operation)
        self.assertEqual(0, research.executions)
        self.assertEqual(0, finance.executions)

    def test_two_independent_capabilities_remain_bounded_advisory_work(self) -> None:
        registry, research, finance = self._registry()
        proposal = ExecutionProposal(
            PROPOSAL_SCHEMA_VERSION,
            ProposalDisposition.CAPABILITY_PLAN,
            (
                ProposedStep(
                    "research-step",
                    "research_capability",
                    "research.search",
                    "collect the research perspective",
                    "evidence",
                    "market",
                    (ProposedInput("ticker", "ticker"),),
                ),
                ProposedStep(
                    "finance-step",
                    "finance_capability",
                    "valuation.analyze",
                    "collect the valuation perspective",
                    "analysis",
                    "fundamental",
                    (ProposedInput("ticker", "ticker"),),
                ),
            ),
            FinalizationStrategy.LOCAL_SYNTHESIS,
            (),
            0.9,
            "TWO_PERSPECTIVES",
            "two independent bounded perspectives",
        )
        decision = PlanInterpreter(planner=FakePlanner(proposal), capabilities=registry).interpret(
            _request("Research and analyze AAPL valuation")
        )
        self.assertTrue(decision.accepted)
        self.assertEqual("plan.execute", decision.route_decision.operation)
        self.assertEqual(0, research.executions)
        self.assertEqual(0, finance.executions)

    def test_provider_unknown_unavailable_and_unsupported_proposals_fallback(self) -> None:
        registry, _, _ = self._registry()

        provider_proposal = _proposal("openai", "chat.complete")
        provider_decision = PlanInterpreter(
            planner=FakePlanner(provider_proposal), capabilities=registry
        ).interpret(_request("hello"))
        self.assertTrue(provider_decision.fallback_used)
        self.assertEqual("PROVIDER_IDENTIFIER_NOT_ALLOWED", provider_decision.rejection_code)
        self.assertLessEqual(len(provider_decision.proposal.steps), 1)

        unknown = _proposal("unknown_capability", "unknown.run")
        unknown_decision = PlanInterpreter(
            planner=FakePlanner(unknown), capabilities=registry
        ).interpret(_request("hello"))
        self.assertEqual("PROPOSAL_CAPABILITY_UNKNOWN", unknown_decision.rejection_code)
        self.assertLessEqual(len(unknown_decision.proposal.steps), 1)

        unavailable_registry, _, _ = self._registry(available=False)
        unavailable = _proposal(
            "finance_capability",
            "valuation.analyze",
            inputs=(ProposedInput("ticker", "ticker"),),
        )
        unavailable_decision = PlanInterpreter(
            planner=FakePlanner(unavailable), capabilities=unavailable_registry
        ).interpret(_request("Analyze AAPL valuation"))
        self.assertEqual("CAPABILITY_UNAVAILABLE", unavailable_decision.rejection_code)
        self.assertFalse(unavailable_decision.route_decision.available)

        unsupported = _proposal(
            "finance_capability",
            "valuation.write",
            inputs=(ProposedInput("ticker", "ticker"),),
        )
        unsupported_decision = PlanInterpreter(
            planner=FakePlanner(unsupported), capabilities=registry
        ).interpret(_request("Analyze AAPL valuation"))
        self.assertEqual("OPERATION_UNSUPPORTED", unsupported_decision.rejection_code)
        self.assertLessEqual(len(unsupported_decision.proposal.steps), 1)

    def test_malformed_or_timeout_planner_uses_only_deterministic_fallback(self) -> None:
        registry, _, _ = self._registry()
        for failure in (PlannerFailureMode.MALFORMED, PlannerFailureMode.TIMEOUT):
            decision = PlanInterpreter(
                planner=FakePlanner(failure=failure), capabilities=registry
            ).interpret(_request("Analyze AAPL valuation"))
            self.assertFalse(decision.accepted)
            self.assertTrue(decision.fallback_used)
            self.assertLessEqual(len(decision.proposal.steps), 1)
            self.assertNotEqual("plan.execute", decision.route_decision.operation)

    def test_cycle_and_verification_marker_are_rejected_before_routing(self) -> None:
        registry, _, _ = self._registry()
        first = ProposedStep(
            "step-one",
            "finance_capability",
            "valuation.analyze",
            "analyze valuation",
            "analysis",
            "primary",
            dependencies=("step-two",),
        )
        second = ProposedStep(
            "step-two",
            "research_capability",
            "research.search",
            "research current information",
            "evidence",
            "market",
            dependencies=("step-one",),
        )
        cycle = ExecutionProposal(
            PROPOSAL_SCHEMA_VERSION,
            ProposalDisposition.CAPABILITY_PLAN,
            (first, second),
            FinalizationStrategy.LOCAL_SYNTHESIS,
            (),
            0.9,
            "CYCLE",
            "cyclic test proposal",
        )
        cycle_decision = PlanInterpreter(
            planner=FakePlanner(cycle), capabilities=registry
        ).interpret(_request("Research and analyze AAPL"))
        self.assertEqual("PLAN_CYCLE", cycle_decision.rejection_code)
        verification = _proposal(
            "finance_capability",
            "valuation.analyze",
            inputs=(ProposedInput("ticker", "ticker"),),
            verification=True,
        )
        verification_decision = PlanInterpreter(
            planner=FakePlanner(verification), capabilities=registry
        ).interpret(_request("Analyze AAPL valuation"))
        self.assertEqual("VERIFICATION_NOT_AUTHORIZED", verification_decision.rejection_code)


class OllamaPlannerAdapterTests(unittest.TestCase):
    def test_structured_ollama_adapter_uses_planner_role_and_safe_catalog(self) -> None:
        proposal = ExecutionProposal(
            PROPOSAL_SCHEMA_VERSION,
            ProposalDisposition.LOCAL_ONLY,
            (),
            FinalizationStrategy.DIRECT,
            (),
            1.0,
            "TEST_LOCAL",
            "bounded local proposal",
        )
        profile = LocalModelProfile(
            "planner_test",
            "ollama",
            "planner-model",
            "http://127.0.0.1:11434",
            5.0,
        )
        role = LocalModelRoleConfig("planner", profile, 100)
        planner = OllamaPlanner(role=role)
        request = PlannerRequest(
            "ollama-request",
            "Say hello",
            "approved context",
            build_planner_catalog(()),
            100,
            5.0,
        )

        class _Response:
            def read(self) -> bytes:
                return json.dumps({"response": encode_proposal(proposal)}).encode("utf-8")

            def close(self) -> None:
                return None

        captured: dict[str, Any] = {}

        def fake_urlopen(request_object: object, *, timeout: float) -> _Response:
            captured["request"] = request_object
            captured["timeout"] = timeout
            return _Response()

        with patch("elly.adapters.ollama_planner.urlopen", fake_urlopen):
            self.assertEqual(proposal, planner.propose(request))
        request_object = captured["request"]
        body = json.loads(request_object.data.decode("utf-8"))
        self.assertEqual("planner-model", body["model"])
        self.assertFalse(body["stream"])
        self.assertNotIn("handler", body["prompt"])
        self.assertIn("elly.routing-catalog.v1", body["prompt"])


if __name__ == "__main__":
    unittest.main()
