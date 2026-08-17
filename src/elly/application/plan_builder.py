"""Pure proposal-to-plan construction and DAG validation for V3 Phase 3."""

from __future__ import annotations

import hashlib
import heapq
import json
import math
from dataclasses import dataclass

from ..application.routing_contracts import (
    CapabilityKind,
    CapabilityRoutingDescriptor,
    FreshnessSupport,
    OperationIntentContract,
    RoutingCatalog,
)
from ..domain.enums import ActionCategory
from ..domain.errors import InputInvalidError, PlanValidationError
from ..planning.catalog import build_planner_catalog
from ..planning.contracts import (
    COMPILED_MAX_REPLANNING_ATTEMPTS,
    LOCAL_SYNTHESIS_CAPABILITY_ID,
    LOCAL_SYNTHESIS_OPERATION_ID,
    PLAN_SCHEMA_VERSION,
    AuthorizationState,
    ExecutionPlan,
    ExecutionProposal,
    FinalizationStrategy,
    PlanLimitsSnapshot,
    PlanStatus,
    PlanStep,
    ProposalDisposition,
    ProposedInput,
    ProposedStep,
    StepCriticality,
    StepKind,
    StepState,
)
from .plan_validation import PlanValidationResult
from .redundancy_policy import RedundancyPolicy, normalize_objective

_GENERIC_OBJECTIVES = frozenset(
    {
        "do work",
        "complete the task",
        "analyze the request",
        "perform analysis",
        "return a result",
    }
)


@dataclass(frozen=True, slots=True)
class _PreparedStep:
    proposal: ProposedStep
    descriptor: CapabilityRoutingDescriptor
    operation: OperationIntentContract
    requires_external_access: bool
    requires_consent: bool


class PlanBuilder:
    """Build immutable plans from one immutable routing-catalog snapshot.

    The builder deliberately accepts descriptive catalog values instead of a
    registry or handler.  It therefore remains deterministic and provider-free:
    availability is the value captured in the snapshot supplied by the caller.
    """

    def __init__(
        self,
        catalog: RoutingCatalog,
        limits: PlanLimitsSnapshot | None = None,
        *,
        default_timeout_seconds: float = 60.0,
        synthesis_timeout_seconds: float | None = None,
        redundancy_policy: RedundancyPolicy | None = None,
        legacy_synthesis_enabled: bool = True,
    ) -> None:
        if not isinstance(catalog, tuple):
            raise InputInvalidError("plan builder catalog must be an immutable tuple")
        if any(not isinstance(item, CapabilityRoutingDescriptor) for item in catalog):
            raise InputInvalidError("plan builder catalog contains an invalid descriptor")
        ids = tuple(item.capability_id for item in catalog)
        if len(set(ids)) != len(ids):
            raise InputInvalidError("plan builder catalog capability IDs must be unique")
        if limits is not None and not isinstance(limits, PlanLimitsSnapshot):
            raise InputInvalidError("plan builder limits must be a PlanLimitsSnapshot")
        for value, name in (
            (default_timeout_seconds, "default_timeout_seconds"),
            (synthesis_timeout_seconds, "synthesis_timeout_seconds"),
        ):
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise InputInvalidError(f"{name} must be numeric")
            if not math.isfinite(float(value)) or value <= 0:
                raise InputInvalidError(f"{name} must be positive and finite")
        if not isinstance(legacy_synthesis_enabled, bool):
            raise InputInvalidError("legacy_synthesis_enabled must be a bool")
        self._catalog = tuple(sorted(catalog, key=lambda item: item.capability_id))
        self._catalog_by_id = {item.capability_id: item for item in self._catalog}
        self._catalog_version = build_planner_catalog(self._catalog).version
        self._limits = limits or PlanLimitsSnapshot()
        self._default_timeout_seconds = float(default_timeout_seconds)
        self._synthesis_timeout_seconds = float(
            synthesis_timeout_seconds
            if synthesis_timeout_seconds is not None
            else default_timeout_seconds
        )
        self._redundancy_policy = redundancy_policy or RedundancyPolicy()
        self._legacy_synthesis_enabled = legacy_synthesis_enabled

    @property
    def catalog_version(self) -> str:
        return self._catalog_version

    @property
    def catalog(self) -> tuple[CapabilityRoutingDescriptor, ...]:
        """Return the immutable catalog snapshot used by this builder.

        Replanning creates a fresh builder from the current catalog while
        retaining the original plan's captured execution limits.  Exposing
        the snapshot through a read-only property keeps that operation
        provider-neutral and avoids reaching into builder internals.
        """

        return self._catalog

    @property
    def limits(self) -> PlanLimitsSnapshot:
        return self._limits

    def validate(
        self,
        proposal: ExecutionProposal,
        task_id: str,
        *,
        plan_id: str | None = None,
        revision: int = 0,
        parent_plan_id: str | None = None,
        verification_requested: bool = False,
    ) -> PlanValidationResult:
        """Return a typed result without raising for proposal rejection."""

        return self._try_build(
            proposal,
            task_id,
            plan_id=plan_id,
            revision=revision,
            parent_plan_id=parent_plan_id,
            verification_requested=verification_requested,
        )

    try_build = validate

    def build(
        self,
        proposal: ExecutionProposal,
        task_id: str,
        *,
        plan_id: str | None = None,
        revision: int = 0,
        parent_plan_id: str | None = None,
        verification_requested: bool = False,
    ) -> ExecutionPlan:
        """Build a plan or raise a typed, display-safe rejection."""

        result = self._try_build(
            proposal,
            task_id,
            plan_id=plan_id,
            revision=revision,
            parent_plan_id=parent_plan_id,
            verification_requested=verification_requested,
        )
        if not result.accepted:
            raise PlanValidationError(result.reason_code, result.diagnostics)
        assert result.plan is not None
        return result.plan

    def _try_build(
        self,
        proposal: ExecutionProposal,
        task_id: str,
        *,
        plan_id: str | None,
        revision: int,
        parent_plan_id: str | None,
        verification_requested: bool,
    ) -> PlanValidationResult:
        if not isinstance(proposal, ExecutionProposal):
            return self._reject("PLAN_PROPOSAL_INVALID")
        if not isinstance(task_id, str) or not task_id.strip():
            return self._reject("PLAN_TASK_ID_INVALID")
        if not isinstance(verification_requested, bool):
            return self._reject("PLAN_VERIFICATION_FLAG_INVALID")
        config_failure = self._validate_limit_configuration()
        if config_failure is not None:
            return config_failure
        if proposal.disposition is not ProposalDisposition.CAPABILITY_PLAN:
            return self._reject("PLAN_PROPOSAL_NOT_EXECUTABLE")

        proposal_steps = proposal.steps
        by_id = {step.proposal_step_id: step for step in proposal_steps}
        if len(by_id) != len(proposal_steps):
            return self._reject("PLAN_DUPLICATE_STEP_ID")
        graph_failure = self._validate_dependencies(proposal_steps, by_id)
        if graph_failure is not None:
            return graph_failure

        prepared: list[_PreparedStep] = []
        for step in proposal_steps:
            prepared_result = self._prepare_step(step)
            if isinstance(prepared_result, PlanValidationResult):
                return prepared_result
            prepared.append(prepared_result)

        verification_failure = self._validate_verification(proposal_steps, verification_requested)
        if verification_failure is not None:
            return verification_failure
        redundancy = self._redundancy_policy.validate(
            proposal_steps,
            verification_requested=verification_requested,
        )
        if not redundancy.accepted:
            return self._reject(
                redundancy.reason_code,
                *(f"duplicate={left}:{right}" for left, right in redundancy.duplicate_step_ids),
            )

        input_failure = self._validate_input_flow(prepared, by_id)
        if input_failure is not None:
            return input_failure

        ordered_ids = self._topological_order(by_id)
        if ordered_ids is None:
            return self._reject("PLAN_DEPENDENCY_CYCLE")

        plan_steps = tuple(
            self._to_plan_step(by_id[step_id], self._prepared_for(prepared, step_id))
            for step_id in ordered_ids
        )
        effective_finalization = proposal.finalization
        if (
            not self._legacy_synthesis_enabled
            and effective_finalization is FinalizationStrategy.LOCAL_SYNTHESIS
        ):
            # V3.5 composition is a mandatory post-aggregation application
            # phase.  Retain the legacy enum only for persisted/read-compatible
            # plans; new production plans cannot acquire a model-controlled
            # synthesis node or presentation mode from planner output.
            effective_finalization = FinalizationStrategy.TEMPLATE

        if effective_finalization is FinalizationStrategy.LOCAL_SYNTHESIS:
            if any(step.proposal_step_id == "synthesis" for step in proposal_steps):
                return self._reject("PLAN_SYNTHESIS_STEP_ID_RESERVED")
            plan_steps += (self._synthesis_step(plan_steps),)

        limit_failure = self._validate_limits(plan_steps, prepared, effective_finalization)
        if limit_failure is not None:
            return limit_failure
        finalization_failure = self._validate_finalization(
            effective_finalization, plan_steps, proposal_steps
        )
        if finalization_failure is not None:
            return finalization_failure

        resolved_plan_id = plan_id or self._generated_plan_id(
            proposal, task_id, revision, parent_plan_id
        )
        try:
            plan = ExecutionPlan(
                plan_id=resolved_plan_id,
                task_id=task_id,
                schema_version=PLAN_SCHEMA_VERSION,
                revision=revision,
                parent_plan_id=parent_plan_id,
                steps=plan_steps,
                finalization=effective_finalization,
                limits=self._limits,
                catalog_version=self._catalog_version,
                status=PlanStatus.PENDING,
            )
        except InputInvalidError as exc:
            return self._reject("PLAN_CONTRACT_INVALID", str(exc))
        return PlanValidationResult(True, "PLAN_VALIDATED", plan)

    def _validate_limit_configuration(self) -> PlanValidationResult | None:
        if self._limits.max_parallel_steps > self._limits.max_concurrency:
            return self._reject("PLAN_LIMIT_CONFIGURATION", "parallelism exceeds concurrency")
        if self._limits.max_replanning_attempts > COMPILED_MAX_REPLANNING_ATTEMPTS:
            return self._reject("PLAN_REPLANNING_LIMIT_UNSUPPORTED")
        return None

    def _prepare_step(self, step: ProposedStep) -> _PreparedStep | PlanValidationResult:
        descriptor = self._catalog_by_id.get(step.capability_id)
        if descriptor is None:
            return self._reject("PLAN_CAPABILITY_UNKNOWN")
        if not descriptor.available:
            return self._reject("PLAN_CAPABILITY_UNAVAILABLE")
        operation = next(
            (
                candidate
                for candidate in descriptor.operations
                if candidate.operation_id == step.operation_id
            ),
            None,
        )
        if operation is None:
            return self._reject("PLAN_OPERATION_UNSUPPORTED")
        if not self._meaningful_objective(step.objective):
            return self._reject("PLAN_OBJECTIVE_INVALID")
        if operation.objective_classes and step.objective_class not in operation.objective_classes:
            return self._reject("PLAN_OBJECTIVE_CLASS_UNSUPPORTED")
        if operation.perspectives and step.perspective not in operation.perspectives:
            return self._reject("PLAN_PERSPECTIVE_UNSUPPORTED")
        if step.expected_output_type != operation.output_type:
            return self._reject("PLAN_OUTPUT_TYPE_MISMATCH")
        if step.requires_current_information and operation.freshness not in {
            FreshnessSupport.CURRENT,
            FreshnessSupport.LIVE,
        }:
            return self._reject("PLAN_FRESHNESS_UNSUPPORTED")
        if step.requires_external_access and not descriptor.requires_external_access:
            return self._reject("PLAN_EXTERNAL_ACCESS_MISMATCH")
        return _PreparedStep(
            proposal=step,
            descriptor=descriptor,
            operation=operation,
            requires_external_access=descriptor.requires_external_access,
            requires_consent=descriptor.requires_consent,
        )

    def _validate_dependencies(
        self,
        steps: tuple[ProposedStep, ...],
        by_id: dict[str, ProposedStep],
    ) -> PlanValidationResult | None:
        for step in steps:
            if len(set(step.dependencies)) != len(step.dependencies):
                return self._reject("PLAN_DUPLICATE_DEPENDENCY", step.proposal_step_id)
            if any(dependency not in by_id for dependency in step.dependencies):
                return self._reject("PLAN_DEPENDENCY_UNKNOWN", step.proposal_step_id)
            if step.proposal_step_id in step.dependencies:
                return self._reject("PLAN_SELF_DEPENDENCY", step.proposal_step_id)
        return None

    @staticmethod
    def _prepared_for(prepared: list[_PreparedStep], step_id: str) -> _PreparedStep:
        return next(item for item in prepared if item.proposal.proposal_step_id == step_id)

    def _validate_input_flow(
        self,
        prepared: list[_PreparedStep],
        by_id: dict[str, ProposedStep],
    ) -> PlanValidationResult | None:
        prepared_by_id = {item.proposal.proposal_step_id: item for item in prepared}
        for item in prepared:
            step = item.proposal
            accepted = set(item.operation.accepted_inputs)
            accepted.update(item.operation.required_entities)
            accepted.update(item.operation.optional_entities)
            if "ticker_or_company" in accepted:
                accepted.update({"ticker", "company"})
            if "security" in accepted:
                accepted.update({"security", "ticker", "company"})
            input_names = {input_item.name for input_item in step.inputs}
            for required_entity in item.operation.required_entities:
                matching_inputs = tuple(
                    input_item
                    for input_item in step.inputs
                    if self._input_satisfies_entity(input_item, required_entity)
                )
                if not matching_inputs:
                    return self._reject(
                        "PLAN_REQUIRED_INPUT_MISSING",
                        f"{step.proposal_step_id}:{required_entity}",
                    )
                if not any(input_item.required for input_item in matching_inputs):
                    return self._reject(
                        "PLAN_REQUIRED_INPUT_OPTIONAL",
                        f"{step.proposal_step_id}:{required_entity}",
                    )
            for input_item in step.inputs:
                if input_item.value_type not in accepted:
                    return self._reject(
                        "PLAN_INPUT_TYPE_UNSUPPORTED",
                        f"{step.proposal_step_id}:{input_item.name}",
                    )
                if input_item.source != "step":
                    continue
                if input_item.reference not in step.dependencies:
                    return self._reject(
                        "PLAN_INPUT_REFERENCE_INVALID",
                        f"{step.proposal_step_id}:{input_item.reference}",
                    )
                producer = prepared_by_id.get(input_item.reference)
                if producer is None:
                    return self._reject("PLAN_DEPENDENCY_UNKNOWN", input_item.reference)
                producer_type = producer.operation.output_type
                if not self._types_compatible(producer_type, input_item.value_type):
                    return self._reject(
                        "PLAN_TYPE_FLOW_MISMATCH",
                        f"{producer.proposal.proposal_step_id}->{step.proposal_step_id}",
                    )
            # A declared input name must be unique at the contract boundary;
            # this check remains here for callers that construct objects without
            # invoking the normal dataclass initializer.
            if len(input_names) != len(step.inputs):
                return self._reject("PLAN_DUPLICATE_INPUT", step.proposal_step_id)
            for dependency in step.dependencies:
                if dependency not in by_id:
                    return self._reject("PLAN_DEPENDENCY_UNKNOWN", dependency)
        return None

    @staticmethod
    def _input_satisfies_entity(input_item: ProposedInput, entity: str) -> bool:
        if input_item.name == entity or input_item.value_type == entity:
            return True
        if entity == "ticker_or_company":
            return input_item.name in {"ticker", "company"} or input_item.value_type in {
                "ticker",
                "company",
            }
        if entity == "security":
            return input_item.name in {
                "ticker",
                "company",
                "security",
            } or input_item.value_type in {
                "ticker",
                "company",
                "security",
            }
        return False

    @staticmethod
    def _types_compatible(producer: str, consumer: str) -> bool:
        return producer == consumer or (consumer == "task_result" and producer.endswith("_result"))

    @staticmethod
    def _meaningful_objective(objective: str) -> bool:
        normalized = normalize_objective(objective)
        return (
            len(normalized) >= 8
            and normalized not in _GENERIC_OBJECTIVES
            and any(character.isalpha() for character in normalized)
        )

    @staticmethod
    def _validate_verification(
        steps: tuple[ProposedStep, ...], verification_requested: bool
    ) -> PlanValidationResult | None:
        if any(step.verification for step in steps) and not verification_requested:
            return PlanValidationResult(False, "PLAN_VERIFICATION_UNAUTHORIZED")
        return None

    def _topological_order(self, by_id: dict[str, ProposedStep]) -> tuple[str, ...] | None:
        dependents: dict[str, list[str]] = {step_id: [] for step_id in by_id}
        indegree = {step_id: len(step.dependencies) for step_id, step in by_id.items()}
        for step_id, step in by_id.items():
            for dependency in step.dependencies:
                dependents[dependency].append(step_id)
        ready = [step_id for step_id, degree in indegree.items() if degree == 0]
        heapq.heapify(ready)
        ordered: list[str] = []
        while ready:
            step_id = heapq.heappop(ready)
            ordered.append(step_id)
            for dependent in sorted(dependents[step_id]):
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    heapq.heappush(ready, dependent)
        return tuple(ordered) if len(ordered) == len(by_id) else None

    def _to_plan_step(self, step: ProposedStep, prepared: _PreparedStep) -> PlanStep:
        return PlanStep(
            step_id=step.proposal_step_id,
            kind=StepKind.CAPABILITY,
            capability_id=step.capability_id,
            operation_id=step.operation_id,
            objective=step.objective,
            objective_class=step.objective_class,
            perspective=step.perspective,
            inputs=step.inputs,
            dependencies=tuple(sorted(step.dependencies)),
            output_type=prepared.operation.output_type,
            criticality=(StepCriticality.REQUIRED if step.required else StepCriticality.OPTIONAL),
            verification=step.verification,
            timeout_seconds=min(
                self._default_timeout_seconds,
                self._limits.max_step_timeout_seconds,
            ),
            requires_external_access=prepared.requires_external_access,
            effect=prepared.operation.effect,
            requires_consent=prepared.requires_consent,
            state=StepState.PENDING,
            authorization_state=AuthorizationState.PENDING,
        )

    def _synthesis_step(self, steps: tuple[PlanStep, ...]) -> PlanStep:
        return PlanStep(
            step_id="synthesis",
            kind=StepKind.LOCAL_SYNTHESIS,
            capability_id=LOCAL_SYNTHESIS_CAPABILITY_ID,
            operation_id=LOCAL_SYNTHESIS_OPERATION_ID,
            objective="compose the validated specialist results",
            objective_class="synthesis",
            perspective="integrator",
            inputs=tuple(
                ProposedInput(
                    name=f"result_{step.step_id}",
                    value_type=step.output_type,
                    source="step",
                    reference=step.step_id,
                    required=step.criticality is StepCriticality.REQUIRED,
                )
                for step in steps
            ),
            dependencies=tuple(sorted(step.step_id for step in steps)),
            output_type="task_result",
            criticality=StepCriticality.REQUIRED,
            verification=False,
            timeout_seconds=min(
                self._synthesis_timeout_seconds,
                self._limits.max_step_timeout_seconds,
            ),
            requires_external_access=False,
            effect=ActionCategory.NONE,
            requires_consent=False,
            state=StepState.PENDING,
            authorization_state=AuthorizationState.NOT_REQUIRED,
        )

    def _validate_finalization(
        self,
        finalization: FinalizationStrategy,
        steps: tuple[PlanStep, ...],
        proposal_steps: tuple[ProposedStep, ...],
    ) -> PlanValidationResult | None:
        synthesis = [step for step in steps if step.kind is StepKind.LOCAL_SYNTHESIS]
        if finalization is FinalizationStrategy.LOCAL_SYNTHESIS:
            if len(synthesis) != 1:
                return self._reject("PLAN_SYNTHESIS_COUNT_INVALID")
            synthesis_step = synthesis[0]
            expected = {step.proposal_step_id for step in proposal_steps}
            if set(synthesis_step.dependencies) != expected:
                return self._reject("PLAN_SYNTHESIS_DEPENDENCIES_INVALID")
            if any(
                any(dependency == synthesis_step.step_id for dependency in step.dependencies)
                for step in steps
                if step.kind is StepKind.CAPABILITY
            ):
                return self._reject("PLAN_SYNTHESIS_NOT_TERMINAL")
        elif synthesis:
            return self._reject("PLAN_SYNTHESIS_NOT_ALLOWED")
        return None

    def _validate_limits(
        self,
        steps: tuple[PlanStep, ...],
        prepared: list[_PreparedStep],
        finalization: FinalizationStrategy,
    ) -> PlanValidationResult | None:
        if len(steps) > self._limits.max_plan_steps:
            return self._reject("PLAN_LIMIT_MAX_PLAN_STEPS")
        specialist_count = sum(
            item.descriptor.kind is CapabilityKind.SPECIALIST for item in prepared
        )
        research_count = sum(item.descriptor.kind is CapabilityKind.RESEARCH for item in prepared)
        provider_calls = sum(item.requires_external_access for item in prepared)
        synthesis_count = sum(step.kind is StepKind.LOCAL_SYNTHESIS for step in steps)
        if specialist_count > self._limits.max_specialist_executions:
            return self._reject("PLAN_LIMIT_SPECIALIST_EXECUTIONS")
        if research_count > self._limits.max_research_executions:
            return self._reject("PLAN_LIMIT_RESEARCH_EXECUTIONS")
        if synthesis_count > self._limits.max_synthesis_executions:
            return self._reject("PLAN_LIMIT_SYNTHESIS_EXECUTIONS")
        if provider_calls > self._limits.max_provider_calls:
            return self._reject("PLAN_LIMIT_PROVIDER_CALLS")
        if finalization is FinalizationStrategy.LOCAL_SYNTHESIS and synthesis_count != 1:
            return self._reject("PLAN_SYNTHESIS_COUNT_INVALID")
        levels = self._levels(steps)
        level_counts: dict[int, int] = {}
        for level in levels.values():
            level_counts[level] = level_counts.get(level, 0) + 1
        width = max(level_counts.values(), default=0)
        if width > self._limits.max_concurrency or width > self._limits.max_parallel_steps:
            return self._reject("PLAN_LIMIT_PARALLELISM")
        critical_path = self._critical_path(steps)
        if critical_path > self._limits.max_total_timeout_seconds + 1e-9:
            return self._reject("PLAN_LIMIT_TOTAL_TIMEOUT")
        return None

    @staticmethod
    def _levels(steps: tuple[PlanStep, ...]) -> dict[str, int]:
        levels: dict[str, int] = {}
        for step in steps:
            levels[step.step_id] = (
                max((levels[dependency] for dependency in step.dependencies), default=-1) + 1
            )
        return levels

    @staticmethod
    def _critical_path(steps: tuple[PlanStep, ...]) -> float:
        longest: dict[str, float] = {}
        for step in steps:
            longest[step.step_id] = max(
                (longest[dependency] for dependency in step.dependencies),
                default=0.0,
            ) + float(step.timeout_seconds)
        return max(longest.values(), default=0.0)

    @staticmethod
    def _proposal_payload(proposal: ExecutionProposal) -> dict[str, object]:
        return {
            "schema_version": proposal.schema_version,
            "disposition": proposal.disposition.value,
            "finalization": proposal.finalization.value,
            "steps": [
                {
                    "step_id": step.proposal_step_id,
                    "capability_id": step.capability_id,
                    "operation_id": step.operation_id,
                    "objective": normalize_objective(step.objective),
                    "objective_class": step.objective_class,
                    "perspective": step.perspective,
                    "inputs": [
                        {
                            "name": item.name,
                            "value_type": item.value_type,
                            "source": item.source,
                            "reference": item.reference,
                            "required": item.required,
                        }
                        for item in sorted(step.inputs, key=lambda value: value.name)
                    ],
                    "dependencies": sorted(step.dependencies),
                    "expected_output_type": step.expected_output_type,
                    "required": step.required,
                    "verification": step.verification,
                    "requires_current_information": step.requires_current_information,
                    "requires_external_access": step.requires_external_access,
                }
                for step in sorted(proposal.steps, key=lambda value: value.proposal_step_id)
            ],
        }

    def _generated_plan_id(
        self,
        proposal: ExecutionProposal,
        task_id: str,
        revision: int,
        parent_plan_id: str | None,
    ) -> str:
        canonical = json.dumps(
            {
                "task_id": task_id,
                "revision": revision,
                "parent_plan_id": parent_plan_id,
                "catalog_version": self._catalog_version,
                "proposal": self._proposal_payload(proposal),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return "plan-" + hashlib.sha256(canonical).hexdigest()[:24]

    @staticmethod
    def _reject(reason_code: str, *diagnostics: str) -> PlanValidationResult:
        return PlanValidationResult(False, reason_code, diagnostics=tuple(diagnostics))


PlanValidator = PlanBuilder


__all__ = ["PlanBuilder", "PlanValidator"]
