"""V2.5 Phase 3 manifest-driven specialist routing tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from elly.application.capabilities import CapabilityAvailability, CapabilityRegistry
from elly.application.routing import RoutingPolicy
from elly.application.specialists import SpecialistWorkflow
from elly.composition import _specialist_capability_handlers
from elly.domain.enums import CloudMode, Route, RouteReasonCode
from elly.domain.errors import ConfigInvalidError
from elly.domain.models import RouteRequest
from elly.specialists.fake_provider import FakeSpecialistProvider
from elly.specialists.registry import SpecialistRegistry


def _request(text: str) -> RouteRequest:
    return RouteRequest(
        request_id="phase3-manifest-route",
        text=text,
        cloud_mode=CloudMode.CLOUD_PERMITTED,
    )


def _security_manifest(*, enabled: bool = True) -> str:
    return f"""[specialist]
id = "security_review"
version = "1.0"
description = "Reviews public security posture and control evidence."
role = "security"
capabilities = ["security_review", "control_analysis"]
accepted_inputs = ["text"]
requires_current_data = false
preferred_runtime = "cloud"
risk_level = "high"
estimated_cost = "medium"
timeout_seconds = 60
prompt_version = "security-v1"
privacy_class = "remote_allowed"
output_limit = 2000
enabled = {str(enabled).lower()}
allowed_tools = []
exclusions = ["tool_execution", "file_write"]

[routing]
priority = 75

[[routing.operations]]
id = "security.review"
description = "Review a public organization's security posture and control evidence"
domains = ["security", "control_analysis"]
accepted_inputs = ["text"]
required_entities = ["subject"]
freshness = "static"
specificity = 85
examples = ["Review this organization's security posture"]
counterexamples = ["Execute a security change"]
"""


class Phase3ManifestSpecialistTests(unittest.TestCase):
    def test_configured_manifests_publish_typed_operations(self) -> None:
        registry = SpecialistRegistry.from_directory(
            "config/specialists", default_model="central-model"
        )
        coding = registry.get("coding")
        research = registry.get("research")
        stock = registry.get("stock_analysis")
        assert coding is not None
        assert research is not None
        assert stock is not None

        self.assertEqual(
            ("specialist.analyze",),
            tuple(operation.operation_id for operation in coding.routing_operations),
        )
        self.assertEqual(
            (
                "security.analyze",
                "financial_statement.analyze",
                "valuation.analyze",
                "risk.analyze",
            ),
            tuple(operation.operation_id for operation in stock.routing_operations),
        )
        valuation = next(
            operation
            for operation in stock.routing_operations
            if operation.operation_id == "valuation.analyze"
        )
        self.assertEqual(("ticker_or_company",), valuation.required_entities)

    def test_new_manifest_is_routable_without_central_python_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "security_review.toml").write_text(
                _security_manifest(), encoding="utf-8"
            )
            specialist_registry = SpecialistRegistry.from_directory(
                directory, default_model="central-model"
            )
            workflow = SpecialistWorkflow(provider=FakeSpecialistProvider())
            handlers = _specialist_capability_handlers(specialist_registry, workflow)
            capability_registry = CapabilityRegistry(handlers)

            self.assertEqual(
                ("security_review",),
                tuple(handler.descriptor.capability_id for handler in handlers),
            )
            decision = RoutingPolicy(capabilities=capability_registry).decide(
                _request("Review this organization's security posture")
            )

        self.assertEqual("security_review", decision.capability_id)
        self.assertEqual("security.review", decision.operation)
        self.assertEqual(Route.REGISTERED_CAPABILITY, decision.route)
        self.assertEqual(Route.REGISTERED_CAPABILITY, decision.route)
        self.assertEqual(RouteReasonCode.CATALOG_SINGLE_MATCH, decision.reason_code)

    def test_disabling_manifest_keeps_catalog_status_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "security_review.toml").write_text(
                _security_manifest(enabled=False), encoding="utf-8"
            )
            specialist_registry = SpecialistRegistry.from_directory(
                directory, default_model="central-model"
            )
            workflow = SpecialistWorkflow(provider=FakeSpecialistProvider())
            handlers = _specialist_capability_handlers(specialist_registry, workflow)
            capability_registry = CapabilityRegistry(handlers)

            self.assertEqual(
                ("security_review",), tuple(manifest.id for manifest in specialist_registry.all())
            )
            self.assertIs(handlers[0].status().state, CapabilityAvailability.UNAVAILABLE)
            self.assertEqual("DISABLED", handlers[0].status().reason_code)
            decision = RoutingPolicy(capabilities=capability_registry).decide(
                _request("Review this organization's security posture")
            )

        self.assertFalse(decision.available)
        self.assertEqual("security_review", decision.capability_id)
        self.assertEqual(RouteReasonCode.CAPABILITY_UNAVAILABLE, decision.reason_code)
        self.assertEqual("DISABLED", decision.diagnostic)

    def test_invalid_routing_declaration_fails_startup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            invalid = _security_manifest().replace("specificity = 85", "specificity = 101")
            Path(directory, "security_review.toml").write_text(invalid, encoding="utf-8")
            with self.assertRaises(ConfigInvalidError):
                SpecialistRegistry.from_directory(directory, default_model="central-model")

    def test_enabled_manifest_without_routing_contract_fails_startup(self) -> None:
        manifest = _security_manifest().split("\n[routing]", maxsplit=1)[0]
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "security_review.toml").write_text(manifest, encoding="utf-8")
            with self.assertRaises(ConfigInvalidError):
                SpecialistRegistry.from_directory(directory, default_model="central-model")

    def test_duplicate_manifest_ids_fail_startup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "first.toml").write_text(_security_manifest(), encoding="utf-8")
            Path(directory, "second.toml").write_text(_security_manifest(), encoding="utf-8")
            with self.assertRaises(ConfigInvalidError):
                SpecialistRegistry.from_directory(directory, default_model="central-model")

    def test_stock_analysis_is_selected_for_company_valuation(self) -> None:
        specialist_registry = SpecialistRegistry.from_directory(
            "config/specialists", default_model="central-model"
        )
        workflow = SpecialistWorkflow(provider=FakeSpecialistProvider())
        capability_registry = CapabilityRegistry(
            _specialist_capability_handlers(specialist_registry, workflow)
        )

        decision = RoutingPolicy(capabilities=capability_registry).decide(
            _request("Analyze Apple's valuation")
        )

        self.assertEqual("stock_analysis", decision.capability_id)
        self.assertEqual("valuation.analyze", decision.operation)
        self.assertEqual(RouteReasonCode.CATALOG_SINGLE_MATCH, decision.reason_code)
        self.assertIsNotNone(decision.intent)
        assert decision.intent is not None
        self.assertIn("company", decision.intent.arguments)

    def test_removing_manifest_leaves_no_stale_capability(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            specialist_registry = SpecialistRegistry.from_directory(
                directory, default_model="central-model"
            )
            capability_registry = CapabilityRegistry(
                _specialist_capability_handlers(
                    specialist_registry,
                    SpecialistWorkflow(provider=FakeSpecialistProvider()),
                )
            )

        self.assertEqual((), specialist_registry.all())
        self.assertEqual((), capability_registry.routing_catalog())
        self.assertIsNone(capability_registry.get("security_review"))


if __name__ == "__main__":
    unittest.main()
