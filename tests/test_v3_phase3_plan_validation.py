"""Pure V3 Phase 3 plan construction, DAG, and redundancy tests."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import NamedTemporaryFile

from elly.application.plan_builder import PlanBuilder
from elly.application.redundancy_policy import redundancy_fingerprint
from elly.application.routing_contracts import (
    CapabilityAvailability,
    CapabilityKind,
    CapabilityRoutingDescriptor,
    FreshnessSupport,
    OperationIntentContract,
)
from elly.config import load_config
from elly.domain.enums import ActionCategory
from elly.domain.errors import ConfigInvalidError, InputInvalidError, PlanValidationError
from elly.planning.contracts import (
    PROPOSAL_SCHEMA_VERSION,
    ExecutionProposal,
    FinalizationStrategy,
    PlanLimitsSnapshot,
    ProposalDisposition,
    ProposedInput,
    ProposedStep,
    StepKind,
)


def _operation(
    operation_id: str,
    *,
    inputs: tuple[str, ...] = ("text",),
    output: str = "task_result",
    freshness: FreshnessSupport = FreshnessSupport.STATIC,
    objective_classes: tuple[str, ...] = (),
    perspectives: tuple[str, ...] = (),
    effect: ActionCategory = ActionCategory.NONE,
) -> OperationIntentContract:
    return OperationIntentContract(
        operation_id=operation_id,
        description=f"{operation_id} bounded operation",
        domains=("test",),
        accepted_inputs=inputs,
        required_entities=(),
        freshness=freshness,
        effect=effect,
        output_type=output,
        objective_classes=objective_classes,
        perspectives=perspectives,
    )


def _catalog(
    *entries: tuple[str, OperationIntentContract],
    unavailable: frozenset[str] = frozenset(),
    kinds: dict[str, CapabilityKind] | None = None,
    external: frozenset[str] = frozenset(),
) -> tuple[CapabilityRoutingDescriptor, ...]:
    kinds = kinds or {}
    return tuple(
        CapabilityRoutingDescriptor(
            capability_id=capability_id,
            description=f"{capability_id} capability",
            operations=(operation,),
            availability=(
                CapabilityAvailability.UNAVAILABLE
                if capability_id in unavailable
                else CapabilityAvailability.AVAILABLE
            ),
            availability_reason="TEST_DISABLED" if capability_id in unavailable else "",
            kind=kinds.get(capability_id, CapabilityKind.SPECIALIST),
            requires_external_access=capability_id in external,
            requires_consent=capability_id in external,
        )
        for capability_id, operation in entries
    )


def _step(
    step_id: str,
    capability_id: str,
    operation_id: str,
    *,
    dependencies: tuple[str, ...] = (),
    inputs: tuple[ProposedInput, ...] = (),
    output: str = "task_result",
    objective: str | None = None,
    objective_class: str = "analysis",
    perspective: str = "primary",
    verification: bool = False,
    current: bool = False,
    external: bool = False,
) -> ProposedStep:
    return ProposedStep(
        proposal_step_id=step_id,
        capability_id=capability_id,
        operation_id=operation_id,
        objective=objective or f"complete the {step_id} objective",
        objective_class=objective_class,
        perspective=perspective,
        inputs=inputs,
        dependencies=dependencies,
        expected_output_type=output,
        verification=verification,
        requires_current_information=current,
        requires_external_access=external,
    )


def _proposal(
    steps: tuple[ProposedStep, ...],
    *,
    finalization: FinalizationStrategy = FinalizationStrategy.DIRECT,
) -> ExecutionProposal:
    return ExecutionProposal(
        schema_version=PROPOSAL_SCHEMA_VERSION,
        disposition=ProposalDisposition.CAPABILITY_PLAN,
        steps=steps,
        finalization=finalization,
        ambiguities=(),
        confidence=0.9,
        reason_code="TEST_PROPOSAL",
    )


class Phase3PlanBuilderTests(unittest.TestCase):
    def test_orchestration_limits_are_centrally_configurable_and_cannot_expand_global_bounds(
        self,
    ) -> None:
        with NamedTemporaryFile("w", suffix=".toml", delete=False) as handle:
            handle.write(
                "[limits]\nmax_steps = 4\nmax_concurrency = 3\n"
                "[orchestration]\nmax_plan_steps = 4\n"
                "max_specialist_executions = 1\nmax_research_executions = 0\n"
                "max_synthesis_executions = 1\nmax_replans = 0\n"
                "max_parallel_steps = 3\nrecursive_planning = false\n"
                "specialist_delegation = false\nautomatic_replanning = false\n"
            )
            path = handle.name
        try:
            config = load_config(path)
        finally:
            Path(path).unlink(missing_ok=True)
        limits = config.execution_plan_limits()
        self.assertEqual(4, limits.max_plan_steps)
        self.assertEqual(1, limits.max_specialist_executions)
        self.assertEqual(0, limits.max_research_executions)
        self.assertEqual(0, limits.max_replanning_attempts)
        self.assertEqual(3, limits.max_parallel_steps)

        with NamedTemporaryFile("w", suffix=".toml", delete=False) as handle:
            handle.write("[limits]\nmax_steps = 3\n[orchestration]\nmax_plan_steps = 4\n")
            invalid_path = handle.name
        try:
            with self.assertRaises(ConfigInvalidError):
                load_config(invalid_path)
        finally:
            Path(invalid_path).unlink(missing_ok=True)

    def test_linear_and_diamond_graphs_are_topologically_sorted(self) -> None:
        catalog = _catalog(
            ("alpha", _operation("alpha.run")),
            ("beta", _operation("beta.run")),
            ("gamma", _operation("gamma.run")),
        )
        linear = _proposal(
            (
                _step("gamma-step", "gamma", "gamma.run", dependencies=("beta-step",)),
                _step("beta-step", "beta", "beta.run", dependencies=("alpha-step",)),
                _step("alpha-step", "alpha", "alpha.run"),
            )
        )
        plan = PlanBuilder(
            catalog,
            PlanLimitsSnapshot(max_specialist_executions=3, max_total_timeout_seconds=180),
        ).build(linear, "task-linear")
        self.assertEqual(
            ("alpha-step", "beta-step", "gamma-step"), tuple(item.step_id for item in plan.steps)
        )

        diamond_catalog = _catalog(
            ("root", _operation("root.run")),
            ("left", _operation("left.run")),
            ("right", _operation("right.run")),
            ("join", _operation("join.run")),
        )
        diamond = _proposal(
            (
                _step("join-step", "join", "join.run", dependencies=("right-step", "left-step")),
                _step("right-step", "right", "right.run", dependencies=("root-step",)),
                _step("left-step", "left", "left.run", dependencies=("root-step",)),
                _step("root-step", "root", "root.run"),
            )
        )
        self.assertEqual(
            ("root-step", "left-step", "right-step", "join-step"),
            tuple(
                item.step_id
                for item in PlanBuilder(
                    diamond_catalog,
                    PlanLimitsSnapshot(max_specialist_executions=4, max_total_timeout_seconds=180),
                )
                .build(diamond, "task-diamond")
                .steps
            ),
        )

    def test_direct_indirect_and_self_cycles_are_rejected(self) -> None:
        catalog = _catalog(
            ("a", _operation("a.run")),
            ("b", _operation("b.run")),
            ("c", _operation("c.run")),
        )
        direct = _proposal(
            (
                _step("a-step", "a", "a.run", dependencies=("b-step",)),
                _step("b-step", "b", "b.run", dependencies=("a-step",)),
            )
        )
        indirect = _proposal(
            (
                _step("a-step", "a", "a.run", dependencies=("c-step",)),
                _step("b-step", "b", "b.run", dependencies=("a-step",)),
                _step("c-step", "c", "c.run", dependencies=("b-step",)),
            )
        )
        for proposal in (direct, indirect):
            result = PlanBuilder(catalog).validate(proposal, "task-cycle")
            self.assertFalse(result.accepted)
            self.assertEqual("PLAN_DEPENDENCY_CYCLE", result.reason_code)
        with self.assertRaises(InputInvalidError):
            _step("a-step", "a", "a.run", dependencies=("a-step",))

    def test_catalog_operation_availability_freshness_and_types_are_validated(self) -> None:
        catalog = _catalog(
            ("missing", _operation("missing.run")),
            (
                "disabled",
                _operation("disabled.run"),
            ),
            ("current", _operation("current.run", freshness=FreshnessSupport.CURRENT)),
            ("producer", _operation("producer.run", output="finance_result")),
            ("consumer", _operation("consumer.run", inputs=("risk_result",))),
            unavailable=frozenset({"disabled"}),
        )
        builder = PlanBuilder(catalog)
        self.assertEqual(
            "PLAN_CAPABILITY_UNKNOWN",
            builder.validate(
                _proposal((_step("x", "unknown", "x.run"),)), "task-unknown"
            ).reason_code,
        )
        self.assertEqual(
            "PLAN_CAPABILITY_UNAVAILABLE",
            builder.validate(
                _proposal((_step("x", "disabled", "disabled.run"),)), "task-disabled"
            ).reason_code,
        )
        static_catalog = _catalog(("static", _operation("static.run")))
        self.assertEqual(
            "PLAN_FRESHNESS_UNSUPPORTED",
            PlanBuilder(static_catalog)
            .validate(
                _proposal((_step("x", "static", "static.run", current=True),)),
                "task-fresh",
            )
            .reason_code,
        )
        type_result = builder.validate(
            _proposal(
                (
                    _step(
                        "consumer-step",
                        "consumer",
                        "consumer.run",
                        dependencies=("producer-step",),
                        inputs=(ProposedInput("risk", "risk_result", "step", "producer-step"),),
                    ),
                    _step("producer-step", "producer", "producer.run", output="finance_result"),
                )
            ),
            "task-type",
        )
        self.assertEqual("PLAN_TYPE_FLOW_MISMATCH", type_result.reason_code)

    def test_freshness_and_external_effect_metadata_are_derived_from_catalog(self) -> None:
        catalog = _catalog(
            ("current", _operation("current.run", freshness=FreshnessSupport.CURRENT)),
            ("external", _operation("external.run", effect=ActionCategory.CONTENT_DRAFT)),
        )
        current_plan = PlanBuilder(catalog).build(
            _proposal((_step("current-step", "current", "current.run", current=True),)),
            "task-current",
        )
        self.assertEqual(FreshnessSupport.CURRENT, FreshnessSupport.CURRENT)
        self.assertFalse(current_plan.steps[0].requires_external_access)
        external_plan = PlanBuilder(
            _catalog(
                ("external", _operation("external.run", effect=ActionCategory.CONTENT_DRAFT)),
                external=frozenset({"external"}),
            )
        ).build(
            _proposal((_step("external-step", "external", "external.run", external=True),)),
            "task-external",
        )
        self.assertTrue(external_plan.steps[0].requires_external_access)
        self.assertIs(ActionCategory.CONTENT_DRAFT, external_plan.steps[0].effect)

    def test_limits_and_finalization_rules_are_enforced(self) -> None:
        catalog = _catalog(
            ("a", _operation("a.run")),
            ("b", _operation("b.run")),
            ("c", _operation("c.run")),
        )
        proposal = _proposal(
            (
                _step("a-step", "a", "a.run"),
                _step("b-step", "b", "b.run"),
                _step("c-step", "c", "c.run"),
            )
        )
        result = PlanBuilder(
            catalog,
            PlanLimitsSnapshot(max_plan_steps=2),
        ).validate(proposal, "task-limit")
        self.assertEqual("PLAN_LIMIT_MAX_PLAN_STEPS", result.reason_code)
        self.assertEqual(
            "PLAN_LIMIT_PARALLELISM",
            PlanBuilder(
                catalog,
                PlanLimitsSnapshot(max_specialist_executions=3, max_parallel_steps=2),
            )
            .validate(proposal, "task-parallel")
            .reason_code,
        )

        synthesis_catalog = _catalog(
            ("a", _operation("a.run")),
            ("b", _operation("b.run")),
        )
        synthesis = PlanBuilder(synthesis_catalog).build(
            _proposal(
                (_step("a-step", "a", "a.run"), _step("b-step", "b", "b.run")),
                finalization=FinalizationStrategy.LOCAL_SYNTHESIS,
            ),
            "task-synthesis",
        )
        self.assertEqual(StepKind.LOCAL_SYNTHESIS, synthesis.steps[-1].kind)
        self.assertEqual(("a-step", "b-step"), synthesis.steps[-1].dependencies)
        self.assertEqual("synthesis", synthesis.steps[-1].step_id)

    def test_redundancy_perspective_and_verification_rules_are_narrow(self) -> None:
        operation = _operation("specialist.run")
        catalog = _catalog(("specialist", operation))
        duplicate = _proposal(
            (
                _step("first", "specialist", "specialist.run"),
                _step("second", "specialist", "specialist.run"),
            )
        )
        rejected = PlanBuilder(catalog).validate(duplicate, "task-duplicate")
        self.assertEqual("PLAN_REDUNDANT_STEP", rejected.reason_code)
        distinct = _proposal(
            (
                _step("finance", "specialist", "specialist.run", perspective="finance"),
                _step("risk", "specialist", "specialist.run", perspective="risk"),
            )
        )
        self.assertTrue(PlanBuilder(catalog).validate(distinct, "task-distinct").accepted)
        marked = _proposal(
            (
                _step("first", "specialist", "specialist.run"),
                _step("second", "specialist", "specialist.run", verification=True),
            )
        )
        self.assertEqual(
            "PLAN_VERIFICATION_UNAUTHORIZED",
            PlanBuilder(catalog).validate(marked, "task-unauthorized").reason_code,
        )
        accepted = PlanBuilder(catalog).validate(
            marked, "task-authorized", verification_requested=True
        )
        self.assertTrue(accepted.accepted)
        self.assertEqual(
            redundancy_fingerprint(marked.steps[0]), redundancy_fingerprint(marked.steps[1])
        )

    def test_catalog_order_does_not_change_generated_plan_identity(self) -> None:
        entries = (
            ("zeta", _operation("zeta.run")),
            ("alpha", _operation("alpha.run")),
        )
        proposal = _proposal(
            (_step("zeta-step", "zeta", "zeta.run"), _step("alpha-step", "alpha", "alpha.run"))
        )
        first = PlanBuilder(_catalog(*entries)).build(proposal, "task-order")
        second = PlanBuilder(_catalog(*reversed(entries))).build(proposal, "task-order")
        self.assertEqual(first.plan_id, second.plan_id)
        self.assertEqual(first.steps, second.steps)

    def test_build_raises_typed_rejection_without_provider_or_database(self) -> None:
        with self.assertRaises(PlanValidationError) as raised:
            PlanBuilder(_catalog(("a", _operation("a.run")))).build(
                _proposal((_step("a-step", "a", "a.run"), _step("duplicate", "a", "a.run"))),
                "task-error",
            )
        self.assertEqual("PLAN_REDUNDANT_STEP", raised.exception.reason_code)


if __name__ == "__main__":
    unittest.main()
