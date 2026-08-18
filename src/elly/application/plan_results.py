"""Typed plan-result aggregation and deterministic finalization.

Phase 6 keeps two responsibilities deliberately separate from scheduling:

* :class:`PlanStatusPolicy` derives a plan status from immutable step states and
  criticality.  It never asks a model to decide whether work is complete.
* The deterministic finalizers turn the resulting, already validated data into
  the existing ``TaskResult`` presentation contract.  They do not add claims,
  citations, receipts, or agreement that is not present in a step result.

Persisted ``LOCAL_SYNTHESIS`` plans receive a safe deterministic template.
Model-authored presentation is owned solely by ``ResponseCompositionService``.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import TypeVar

from ..domain.enums import (
    EpistemicStatus,
    OutcomeCode,
    Route,
    TaskStatus,
    ValidationStatus,
)
from ..domain.errors import InputInvalidError
from ..domain.models import ClaimSupport, ProvenanceReference, TaskResult
from ..planning.contracts import (
    ExecutionPlan,
    FinalizationStrategy,
    PlanStatus,
    PlanStep,
    StepCriticality,
    StepKind,
    StepState,
)
from .plan_state import STEP_ELIGIBLE_STATES, STEP_TERMINAL_STATES
from .step_results import ActionExecutionReceipt, StepResultEnvelope

_SAFE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
_DISAGREEMENT_KINDS = frozenset({"claim", "finding"})
_T = TypeVar("_T")


def legacy_source_aggregation(
    plan: ExecutionPlan,
    step_results: Mapping[str, TaskResult],
    step_envelopes: Mapping[str, StepResultEnvelope],
    states: Mapping[str, StepState],
) -> "PlanAggregation":
    """Decode a persisted V3 synthesis node into its canonical source aggregate.

    This compatibility boundary can be retired when persisted V3 execution
    plans have been migrated or are outside the supported recovery window.
    It never invokes a model and is not used while constructing new plans.
    """

    source_steps = tuple(
        step for step in plan.steps if step.kind is not StepKind.LOCAL_SYNTHESIS
    )
    if not source_steps:
        raise InputInvalidError("legacy synthesis requires at least one source step")
    source_plan = replace(plan, steps=source_steps, finalization=FinalizationStrategy.TEMPLATE)
    source_ids = {step.step_id for step in source_steps}
    return aggregate_plan_results(
        source_plan,
        {key: value for key, value in step_results.items() if key in source_ids},
        {key: value for key, value in step_envelopes.items() if key in source_ids},
        states={key: value for key, value in states.items() if key in source_ids},
        finalization_complete=True,
    )


def _safe_id(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or _SAFE_ID.fullmatch(value.strip()) is None:
        raise InputInvalidError(f"{name} is invalid")
    return value.strip()


def _unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _normalized_statement(value: str) -> str:
    """Return a comparison-only form; the original statement is retained."""

    return " ".join(value.casefold().strip().rstrip(".!?").split())


@dataclass(frozen=True, slots=True)
class DisagreementRecord:
    """An explicit conflict between typed findings from distinct steps.

    ``claim_id`` is a canonical claim identifier for claim records and a
    deterministic ordinal identifier (``finding-1``) for unkeyed findings.
    Statements are never reduced to a consensus value.  Consumers can display
    every candidate together with its contributing step and evidence IDs.
    """

    disagreement_id: str
    claim_id: str
    step_ids: tuple[str, ...]
    statements: tuple[str, ...]
    evidence_ids: tuple[str, ...] = ()
    source_kind: str = "claim"
    reason_code: str = "SPECIALIST_CLAIMS_CONFLICT"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "disagreement_id", _safe_id(self.disagreement_id, "disagreement_id")
        )
        object.__setattr__(self, "claim_id", _safe_id(self.claim_id, "disagreement claim_id"))
        if self.source_kind not in _DISAGREEMENT_KINDS:
            raise InputInvalidError("disagreement source_kind is invalid")
        if not isinstance(self.step_ids, tuple) or not self.step_ids:
            raise InputInvalidError("disagreement step_ids must be a non-empty tuple")
        normalized_steps = tuple(_safe_id(item, "disagreement step_id") for item in self.step_ids)
        if len(set(normalized_steps)) != len(normalized_steps):
            raise InputInvalidError("disagreement step_ids must be unique")
        object.__setattr__(self, "step_ids", normalized_steps)
        if not isinstance(self.statements, tuple) or len(self.statements) < 2:
            raise InputInvalidError("disagreement must retain at least two statements")
        if any(not isinstance(item, str) or not item.strip() for item in self.statements):
            raise InputInvalidError("disagreement statements must be non-empty text")
        object.__setattr__(self, "statements", _unique(self.statements))
        if len(self.statements) < 2:
            raise InputInvalidError("disagreement statements must differ")
        if not isinstance(self.evidence_ids, tuple) or any(
            not isinstance(item, str) or not item.strip() for item in self.evidence_ids
        ):
            raise InputInvalidError("disagreement evidence_ids are invalid")
        object.__setattr__(self, "evidence_ids", _unique(self.evidence_ids))
        if not isinstance(self.reason_code, str) or not self.reason_code.strip():
            raise InputInvalidError("disagreement reason_code is invalid")

    @property
    def subject_id(self) -> str:
        """Alias used by callers that call claims/findings subjects."""

        return self.claim_id

    @property
    def candidate_statements(self) -> tuple[str, ...]:
        return self.statements

    @property
    def claim_ids(self) -> tuple[str, ...]:
        return (self.claim_id,) if self.source_kind == "claim" else ()

    def to_dict(self) -> dict[str, object]:
        return {
            "disagreement_id": self.disagreement_id,
            "claim_id": self.claim_id,
            "source_kind": self.source_kind,
            "step_ids": list(self.step_ids),
            "statements": list(self.statements),
            "evidence_ids": list(self.evidence_ids),
            "reason_code": self.reason_code,
        }


class PlanStatusPolicy:
    """Pure status policy for the Phase 6 plan decision table."""

    # The order is part of the contract.  A cancellation observed before the
    # terminal plan commit wins over all otherwise-ready outcomes.
    DECISION_TABLE = (
        ("cancellation accepted", PlanStatus.CANCELLED),
        ("a step remains nonterminal", PlanStatus.RUNNING),
        ("required step blocked", PlanStatus.BLOCKED),
        ("required capability unavailable", PlanStatus.UNAVAILABLE),
        ("required step cancelled", PlanStatus.CANCELLED),
        ("required step failed/skipped/interrupted without eligible result", PlanStatus.FAILED),
        ("required step has a partial or otherwise eligible result", PlanStatus.PARTIAL),
        ("optional step is not completed", PlanStatus.PARTIAL),
        ("eligible results materially disagree", PlanStatus.PARTIAL),
        ("finalization is incomplete", PlanStatus.PARTIAL),
        ("all required steps and finalization complete", PlanStatus.COMPLETED),
    )

    @classmethod
    def decision_table(cls) -> tuple[tuple[str, PlanStatus], ...]:
        """Return the immutable, human-readable precedence table."""

        return cls.DECISION_TABLE

    @classmethod
    def derive(
        cls,
        steps: Sequence[PlanStep],
        states: Mapping[str, StepState],
        *,
        cancellation_accepted: bool = False,
        eligible_result_ids: Collection[str] = (),
        has_disagreement: bool = False,
        finalization_complete: bool = True,
    ) -> PlanStatus:
        """Derive one plan status without consulting provider/model output."""

        if not isinstance(states, Mapping):
            raise InputInvalidError("plan status states must be a mapping")
        step_ids = tuple(step.step_id for step in steps)
        if set(states) != set(step_ids):
            raise InputInvalidError("plan status states do not match the plan")
        if any(not isinstance(states[step_id], StepState) for step_id in step_ids):
            raise InputInvalidError("plan status contains an invalid step state")
        eligible = set(eligible_result_ids)

        if cancellation_accepted:
            return PlanStatus.CANCELLED

        if any(states[step.step_id] not in STEP_TERMINAL_STATES for step in steps):
            return PlanStatus.RUNNING

        required = tuple(step for step in steps if step.criticality is StepCriticality.REQUIRED)

        if any(states[step.step_id] is StepState.BLOCKED for step in required):
            return PlanStatus.BLOCKED
        if any(states[step.step_id] is StepState.UNAVAILABLE for step in required):
            return PlanStatus.UNAVAILABLE
        if any(states[step.step_id] is StepState.CANCELLED for step in required):
            return PlanStatus.CANCELLED

        required_without_result = any(
            states[step.step_id] in {StepState.FAILED, StepState.SKIPPED, StepState.INTERRUPTED}
            and step.step_id not in eligible
            for step in required
        )
        if required_without_result:
            return PlanStatus.FAILED

        if any(
            states[step.step_id] is StepState.PARTIAL
            or (states[step.step_id] is not StepState.COMPLETED and step.step_id in eligible)
            for step in required
        ):
            return PlanStatus.PARTIAL

        if any(
            states[step.step_id] is not StepState.COMPLETED
            for step in steps
            if step.criticality is StepCriticality.OPTIONAL
        ):
            return PlanStatus.PARTIAL

        if has_disagreement:
            return PlanStatus.PARTIAL
        if not finalization_complete:
            return PlanStatus.PARTIAL
        return PlanStatus.COMPLETED


def derive_plan_status(
    steps: Sequence[PlanStep],
    states: Mapping[str, StepState],
    *,
    cancellation_accepted: bool = False,
    eligible_result_ids: Collection[str] = (),
    has_disagreement: bool = False,
    finalization_complete: bool = True,
) -> PlanStatus:
    """Functional alias for :class:`PlanStatusPolicy` callers and tests."""

    return PlanStatusPolicy.derive(
        steps,
        states,
        cancellation_accepted=cancellation_accepted,
        eligible_result_ids=eligible_result_ids,
        has_disagreement=has_disagreement,
        finalization_complete=finalization_complete,
    )


@dataclass(frozen=True, slots=True)
class PlanAggregation:
    """Typed, provider-neutral result of aggregating one executed plan."""

    plan: ExecutionPlan
    status: PlanStatus
    step_states: Mapping[str, StepState]
    step_results: Mapping[str, TaskResult] = field(default_factory=dict)
    step_envelopes: Mapping[str, StepResultEnvelope] = field(default_factory=dict)
    disagreements: tuple[DisagreementRecord, ...] = ()
    eligible_step_ids: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()
    cancellation_accepted: bool = False
    finalization_complete: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.plan, ExecutionPlan):
            raise InputInvalidError("plan aggregation plan is invalid")
        if not isinstance(self.status, PlanStatus):
            raise InputInvalidError("plan aggregation status is invalid")
        expected_ids = tuple(step.step_id for step in self.plan.steps)
        if not isinstance(self.step_states, Mapping):
            raise InputInvalidError("plan aggregation step_states must be a mapping")
        if set(self.step_states) != set(expected_ids):
            raise InputInvalidError("plan aggregation step_states do not match the plan")
        if any(not isinstance(value, StepState) for value in self.step_states.values()):
            raise InputInvalidError("plan aggregation contains an invalid step state")
        object.__setattr__(self, "step_states", MappingProxyType(dict(self.step_states)))
        for name, values, expected_type in (
            ("step_results", self.step_results, TaskResult),
            ("step_envelopes", self.step_envelopes, StepResultEnvelope),
        ):
            if not isinstance(values, Mapping):
                raise InputInvalidError(f"plan aggregation {name} must be a mapping")
            if any(
                key not in expected_ids or not isinstance(value, expected_type)
                for key, value in values.items()
            ):
                raise InputInvalidError(f"plan aggregation {name} contains an invalid item")
            object.__setattr__(self, name, MappingProxyType(dict(values)))
        if any(step_id not in expected_ids for step_id in self.eligible_step_ids):
            raise InputInvalidError("plan aggregation eligible step is unknown")
        if len(set(self.eligible_step_ids)) != len(self.eligible_step_ids):
            raise InputInvalidError("plan aggregation eligible steps must be unique")
        if any(not isinstance(item, DisagreementRecord) for item in self.disagreements):
            raise InputInvalidError("plan aggregation disagreements are invalid")
        for item_name, item_values in (
            ("failures", self.failures),
            ("warnings", self.warnings),
            ("uncertainties", self.uncertainties),
        ):
            if not isinstance(item_values, tuple) or any(
                not isinstance(item, str) or not item.strip() for item in item_values
            ):
                raise InputInvalidError(f"plan aggregation {item_name} are invalid")
            object.__setattr__(self, item_name, _unique(item_values))
        if not isinstance(self.cancellation_accepted, bool):
            raise InputInvalidError("plan aggregation cancellation flag is invalid")
        if not isinstance(self.finalization_complete, bool):
            raise InputInvalidError("plan aggregation finalization flag is invalid")

    @property
    def plan_id(self) -> str:
        return self.plan.plan_id

    @property
    def task_id(self) -> str:
        return self.plan.task_id

    @property
    def finalization(self) -> FinalizationStrategy:
        return self.plan.finalization

    @property
    def step_statuses(self) -> Mapping[str, StepState]:
        """Compatibility/readability alias for public plan-result views."""

        return self.step_states

    @property
    def eligible_envelopes(self) -> Mapping[str, StepResultEnvelope]:
        return MappingProxyType(
            {
                step_id: self.step_envelopes[step_id]
                for step_id in self.eligible_step_ids
                if step_id in self.step_envelopes
            }
        )

    def ids_for_state(self, state: StepState) -> tuple[str, ...]:
        return tuple(step_id for step_id, current in self.step_states.items() if current is state)

    @property
    def completed_step_ids(self) -> tuple[str, ...]:
        return self.ids_for_state(StepState.COMPLETED)

    @property
    def partial_step_ids(self) -> tuple[str, ...]:
        return self.ids_for_state(StepState.PARTIAL)

    @property
    def failed_step_ids(self) -> tuple[str, ...]:
        return self.ids_for_state(StepState.FAILED)

    @property
    def blocked_step_ids(self) -> tuple[str, ...]:
        return self.ids_for_state(StepState.BLOCKED)

    @property
    def unavailable_step_ids(self) -> tuple[str, ...]:
        return self.ids_for_state(StepState.UNAVAILABLE)

    @property
    def skipped_step_ids(self) -> tuple[str, ...]:
        return self.ids_for_state(StepState.SKIPPED)

    @property
    def cancelled_step_ids(self) -> tuple[str, ...]:
        return self.ids_for_state(StepState.CANCELLED)

    @property
    def interrupted_step_ids(self) -> tuple[str, ...]:
        return self.ids_for_state(StepState.INTERRUPTED)

    def to_dict(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "task_id": self.task_id,
            "status": self.status.value,
            "finalization": self.finalization.value,
            "step_states": {key: value.value for key, value in self.step_states.items()},
            "eligible_step_ids": list(self.eligible_step_ids),
            "disagreements": [item.to_dict() for item in self.disagreements],
            "failures": list(self.failures),
            "warnings": list(self.warnings),
            "uncertainties": list(self.uncertainties),
            "cancellation_accepted": self.cancellation_accepted,
            "finalization_complete": self.finalization_complete,
        }


def _disagreement_id(source_kind: str, subject_id: str) -> str:
    digest = hashlib.sha256(f"{source_kind}:{subject_id}".encode("utf-8")).hexdigest()[:16]
    return f"disagreement-{source_kind}-{digest}"


@dataclass(frozen=True, slots=True)
class _Observation:
    step_id: str
    statement: str
    support_status: str
    evidence_ids: tuple[str, ...]


def _observations_for(
    step_id: str, envelope: StepResultEnvelope
) -> tuple[tuple[str, str, _Observation], ...]:
    observations: list[tuple[str, str, _Observation]] = []
    for claim in envelope.claims:
        observations.append(
            (
                "claim",
                claim.claim_id,
                _Observation(step_id, claim.text, claim.support_status, claim.evidence_ids),
            )
        )
    # Findings are a typed ordered collection in v1.  Until a future schema
    # adds finding IDs, ordinal IDs are the only safe deterministic join key.
    for index, finding in enumerate(envelope.findings, start=1):
        observations.append(
            (
                "finding",
                f"finding-{index}",
                _Observation(step_id, finding, "unverified", ()),
            )
        )
    return tuple(observations)


def detect_disagreements(
    envelopes: Mapping[str, StepResultEnvelope],
    *,
    eligible_step_ids: Collection[str] | None = None,
) -> tuple[DisagreementRecord, ...]:
    """Find explicit conflicts without inferring agreement from free text.

    Claims join by their canonical ``claim_id``.  Findings join by their
    typed ordinal within each envelope because the Phase 5 result schema does
    not yet carry a separate finding identifier.  Only distinct statements or
    a supported-versus-contradicted support conflict across distinct steps is
    reported.
    """

    if not isinstance(envelopes, Mapping):
        raise InputInvalidError("disagreement envelopes must be a mapping")
    allowed = set(eligible_step_ids) if eligible_step_ids is not None else None
    groups: dict[tuple[str, str], list[_Observation]] = {}
    for step_id in sorted(envelopes):
        envelope = envelopes[step_id]
        if not isinstance(step_id, str) or not isinstance(envelope, StepResultEnvelope):
            raise InputInvalidError("disagreement envelopes contain an invalid item")
        if allowed is not None and step_id not in allowed:
            continue
        for source_kind, subject_id, observation in _observations_for(step_id, envelope):
            groups.setdefault((source_kind, subject_id), []).append(observation)

    records: list[DisagreementRecord] = []
    for (source_kind, subject_id), observations in sorted(groups.items()):
        step_ids = tuple(sorted({item.step_id for item in observations}))
        if len(step_ids) < 2:
            continue
        statement_variants: list[str] = []
        normalized_variants: set[str] = set()
        support_by_text: dict[str, set[str]] = {}
        evidence_ids: list[str] = []
        for item in observations:
            normalized = _normalized_statement(item.statement)
            if normalized not in normalized_variants:
                normalized_variants.add(normalized)
                statement_variants.append(item.statement)
            support_by_text.setdefault(normalized, set()).add(item.support_status)
            evidence_ids.extend(item.evidence_ids)
        supported_statuses = {
            "supported",
            "direct",
            "indirect",
        }
        support_conflict = any(
            "contradicted" in statuses and statuses & supported_statuses
            for statuses in support_by_text.values()
        )
        if len(normalized_variants) < 2 and not support_conflict:
            continue
        if len(statement_variants) < 2:
            statement_variants = [
                f"{statement_variants[0]} (support status candidate {index})"
                for index in range(1, 3)
            ]
        records.append(
            DisagreementRecord(
                disagreement_id=_disagreement_id(source_kind, subject_id),
                claim_id=subject_id,
                step_ids=step_ids,
                statements=tuple(statement_variants),
                evidence_ids=tuple(sorted(set(evidence_ids))),
                source_kind=source_kind,
                reason_code=(
                    "SPECIALIST_CLAIMS_CONFLICT"
                    if source_kind == "claim"
                    else "SPECIALIST_FINDINGS_CONFLICT"
                ),
            )
        )
    return tuple(records)


def aggregate_plan_results(
    plan: ExecutionPlan,
    step_results: Mapping[str, TaskResult] | None = None,
    step_envelopes: Mapping[str, StepResultEnvelope] | None = None,
    states: Mapping[str, StepState] | None = None,
    *,
    cancellation_accepted: bool = False,
    finalization_complete: bool = True,
) -> PlanAggregation:
    """Aggregate one plan's safe step outputs into a typed plan result."""

    if not isinstance(plan, ExecutionPlan):
        raise InputInvalidError("plan aggregation requires an ExecutionPlan")
    expected_ids = {step.step_id for step in plan.steps}
    normalized_states = dict(
        states if states is not None else {step.step_id: step.state for step in plan.steps}
    )
    if set(normalized_states) != expected_ids:
        raise InputInvalidError("plan aggregation states do not match the plan")
    normalized_results = dict(step_results or {})
    normalized_envelopes = dict(step_envelopes or {})
    if any(step_id not in expected_ids for step_id in normalized_results):
        raise InputInvalidError("plan aggregation contains an unknown step result")
    if any(step_id not in expected_ids for step_id in normalized_envelopes):
        raise InputInvalidError("plan aggregation contains an unknown step envelope")
    for step_id, validated_result in normalized_results.items():
        if not isinstance(validated_result, TaskResult) or validated_result.task_id != plan.task_id:
            raise InputInvalidError("plan aggregation contains an invalid step result")
    for step_id, validated_envelope in normalized_envelopes.items():
        step = next(item for item in plan.steps if item.step_id == step_id)
        if not isinstance(validated_envelope, StepResultEnvelope):
            raise InputInvalidError("plan aggregation contains an invalid step envelope")
        if (
            validated_envelope.plan_id != plan.plan_id
            or validated_envelope.task_id != plan.task_id
            or validated_envelope.step_id != step_id
            or validated_envelope.capability_id != step.capability_id
            or validated_envelope.operation_id != step.operation_id
        ):
            raise InputInvalidError("plan aggregation envelope identity does not match the plan")
        normalized_results.setdefault(step_id, validated_envelope.to_task_result())

    eligible: list[str] = []
    for step in plan.steps:
        result = normalized_results.get(step.step_id)
        envelope = normalized_envelopes.get(step.step_id)
        retained = (
            envelope.answer_retained
            if envelope is not None
            else result.answer_retained
            if result is not None
            else False
        )
        if (
            normalized_states[step.step_id] in STEP_ELIGIBLE_STATES
            and result is not None
            and retained
        ):
            eligible.append(step.step_id)

    disagreements = detect_disagreements(
        normalized_envelopes,
        eligible_step_ids=eligible,
    )
    status = derive_plan_status(
        plan.steps,
        normalized_states,
        cancellation_accepted=cancellation_accepted,
        eligible_result_ids=eligible,
        has_disagreement=bool(disagreements),
        finalization_complete=finalization_complete,
    )

    failures: list[str] = []
    warnings: list[str] = []
    uncertainties: list[str] = []
    for step in plan.steps:
        result = normalized_results.get(step.step_id)
        envelope = normalized_envelopes.get(step.step_id)
        if result is not None:
            failures.extend(f"{step.step_id}: {item}" for item in result.failures)
        if envelope is not None and envelope.answer_retained:
            warnings.extend(f"{step.step_id}: {item}" for item in envelope.warnings)
            uncertainties.extend(f"{step.step_id}: {item}" for item in envelope.uncertainties)
    return PlanAggregation(
        plan=plan,
        status=status,
        step_states=normalized_states,
        step_results=normalized_results,
        step_envelopes=normalized_envelopes,
        disagreements=disagreements,
        eligible_step_ids=tuple(eligible),
        failures=tuple(failures),
        warnings=tuple(warnings),
        uncertainties=tuple(uncertainties),
        cancellation_accepted=cancellation_accepted,
        finalization_complete=finalization_complete,
    )


def _result_items(aggregation: PlanAggregation) -> tuple[tuple[PlanStep, TaskResult], ...]:
    by_id = {step.step_id: step for step in aggregation.plan.steps}
    return tuple(
        (by_id[step_id], aggregation.step_results[step_id])
        for step_id in aggregation.eligible_step_ids
        if step_id in aggregation.step_results
    )


def _dedupe_items(items: Sequence[_T]) -> tuple[_T, ...]:
    result: list[_T] = []
    for item in items:
        if item not in result:
            result.append(item)
    return tuple(result)


def _presentation_data(
    aggregation: PlanAggregation,
) -> tuple[
    tuple[str, ...],
    tuple[str, ...],
    tuple[ClaimSupport, ...],
    tuple[str, ...],
    tuple[ProvenanceReference, ...],
    tuple[str, ...],
    tuple[str, ...],
]:
    claims: list[str] = []
    citations: list[str] = []
    claim_supports: list[ClaimSupport] = []
    assumptions: list[str] = []
    provenance: list[ProvenanceReference] = []
    uncertainties: list[str] = list(aggregation.uncertainties)
    warnings: list[str] = list(aggregation.warnings)
    for step_id in aggregation.eligible_step_ids:
        envelope = aggregation.step_envelopes.get(step_id)
        result = aggregation.step_results.get(step_id)
        if envelope is not None:
            claims.extend(claim.text for claim in envelope.claims)
            citations.extend(envelope.citations)
            claim_supports.extend(envelope.claim_supports)
            assumptions.extend(envelope.assumptions)
            provenance.extend(envelope.provenance)
            uncertainties.extend(envelope.uncertainties)
            warnings.extend(envelope.warnings)
        elif result is not None:
            claims.extend(result.claims)
            citations.extend(result.citations)
            claim_supports.extend(result.claim_supports)
            assumptions.extend(result.partial_work)
            provenance.extend(result.provenance)
            uncertainties.extend(result.next_actions)
    return (
        _dedupe_items(claims),
        _dedupe_items(citations),
        _dedupe_items(claim_supports),
        _dedupe_items(assumptions),
        _dedupe_items(provenance),
        _dedupe_items(uncertainties),
        _dedupe_items(warnings),
    )


def _step_detail(aggregation: PlanAggregation, step: PlanStep) -> str:
    result = aggregation.step_results.get(step.step_id)
    envelope = aggregation.step_envelopes.get(step.step_id)
    if envelope is not None:
        detail = envelope.answer or envelope.summary
    elif result is not None:
        detail = result.answer
    else:
        detail = "no result retained"
    detail = detail.strip()
    return detail or "no presentation content retained"


def render_template(aggregation: PlanAggregation) -> str:
    """Render the stable, non-generative plan template."""

    lines = [f"Plan status: {aggregation.status.value}."]
    for step in aggregation.plan.steps:
        state = aggregation.step_states[step.step_id]
        lines.append(f"Step {step.step_id} [{state.value}]: {_step_detail(aggregation, step)}")

    if aggregation.disagreements:
        lines.append("Disagreements:")
        for record in aggregation.disagreements:
            lines.append(
                f"- {record.disagreement_id} ({record.claim_id}): " + " | ".join(record.statements)
            )
    if aggregation.failures:
        lines.append("Failures and limitations:")
        lines.extend(f"- {item}" for item in aggregation.failures)
    missing = tuple(
        step.step_id
        for step in aggregation.plan.steps
        if aggregation.step_states[step.step_id] not in STEP_ELIGIBLE_STATES
    )
    if missing:
        lines.append("Incomplete steps:")
        lines.append("- " + ", ".join(missing))
    if aggregation.warnings:
        lines.append("Warnings:")
        lines.extend(f"- {item}" for item in aggregation.warnings)
    if aggregation.uncertainties:
        lines.append("Uncertainties:")
        lines.extend(f"- {item}" for item in aggregation.uncertainties)
    receipts: list[ActionExecutionReceipt] = []
    for step in aggregation.plan.steps:
        envelope = aggregation.step_envelopes.get(step.step_id)
        if (
            envelope is not None
            and envelope.action_receipt is not None
            and envelope.answer_retained
        ):
            receipts.append(envelope.action_receipt)
    if receipts:
        lines.append("Action receipts:")
        for receipt in receipts:
            provider_reference = (
                f"; provider_reference={receipt.provider_reference}"
                if receipt.provider_reference
                else ""
            )
            lines.append(
                f"- {receipt.receipt_id}: succeeded; capability={receipt.capability_id}; "
                f"operation={receipt.operation_id}; digest={receipt.action_digest}{provider_reference}"
            )
    return "\n".join(lines)


def _outcome_for(
    status: PlanStatus,
) -> tuple[TaskStatus, OutcomeCode, EpistemicStatus, ValidationStatus]:
    if status is PlanStatus.COMPLETED:
        return (
            TaskStatus.COMPLETED,
            OutcomeCode.SUCCESS,
            EpistemicStatus.INFERRED,
            ValidationStatus.VALIDATED,
        )
    if status is PlanStatus.PARTIAL:
        return (
            TaskStatus.PARTIAL,
            OutcomeCode.PARTIAL,
            EpistemicStatus.UNKNOWN,
            ValidationStatus.QUALIFIED,
        )
    if status is PlanStatus.CANCELLED:
        return (
            TaskStatus.CANCELLED,
            OutcomeCode.CANCELLED,
            EpistemicStatus.BLOCKED,
            ValidationStatus.REJECTED,
        )
    if status is PlanStatus.BLOCKED:
        return (
            TaskStatus.BLOCKED,
            OutcomeCode.BLOCKED,
            EpistemicStatus.BLOCKED,
            ValidationStatus.REJECTED,
        )
    if status is PlanStatus.UNAVAILABLE:
        return (
            TaskStatus.BLOCKED,
            OutcomeCode.UNAVAILABLE,
            EpistemicStatus.BLOCKED,
            ValidationStatus.REJECTED,
        )
    return TaskStatus.FAILED, OutcomeCode.FAILED, EpistemicStatus.UNKNOWN, ValidationStatus.REJECTED


def _aggregate_failure_lines(aggregation: PlanAggregation) -> tuple[str, ...]:
    lines = list(aggregation.failures)
    for step in aggregation.plan.steps:
        state = aggregation.step_states[step.step_id]
        if state in STEP_ELIGIBLE_STATES:
            continue
        result = aggregation.step_results.get(step.step_id)
        if result is None and state not in {
            StepState.PENDING,
            StepState.READY,
            StepState.AUTHORIZING,
            StepState.RUNNING,
        }:
            lines.append(f"{step.step_id}: step {state.value}")
    lines.extend(f"disagreement {item.disagreement_id}" for item in aggregation.disagreements)
    return _dedupe_items(lines)


def _partial_work_lines(aggregation: PlanAggregation) -> tuple[str, ...]:
    lines: list[str] = []
    for step in aggregation.plan.steps:
        state = aggregation.step_states[step.step_id]
        if state not in STEP_ELIGIBLE_STATES:
            lines.append(f"{step.step_id}: {state.value}")
            if state is StepState.CANCELLED:
                result = aggregation.step_results.get(step.step_id)
                if result is not None:
                    lines.extend(result.partial_work)
    lines.extend(f"Warning: {item}" for item in aggregation.warnings)
    return _dedupe_items(lines)


def _build_aggregate_task_result(
    aggregation: PlanAggregation,
    *,
    answer: str,
    direct_source: TaskResult | None = None,
) -> TaskResult:
    task_status, outcome_code, default_epistemic, validation_status = _outcome_for(
        aggregation.status
    )
    claims, citations, supports, assumptions, provenance, uncertainties, warnings = (
        _presentation_data(aggregation)
    )
    source = direct_source
    epistemic = default_epistemic
    route = Route.REGISTERED_CAPABILITY
    capability_id: str | None = None
    operation = "plan.result"
    if source is not None and aggregation.status is PlanStatus.COMPLETED:
        epistemic = source.epistemic_status
        validation_status = source.validation_status
        route = source.route_summary
        capability_id = source.capability_id
        operation = source.operation or operation
    elif aggregation.status is PlanStatus.PARTIAL:
        # A disagreement or omitted branch makes the epistemic axis
        # conservative even when every individual result was confident.
        epistemic = EpistemicStatus.UNKNOWN
    partial_work = list(assumptions)
    partial_work.extend(_partial_work_lines(aggregation))
    partial_work.extend(f"Warning: {item}" for item in warnings)
    failures = _aggregate_failure_lines(aggregation)
    if aggregation.status is PlanStatus.CANCELLED and not failures:
        failures = ("plan cancellation accepted",)
    answer_retained = bool(answer.strip())
    return TaskResult(
        task_id=aggregation.task_id,
        task_status=task_status,
        epistemic_status=epistemic,
        validation_status=validation_status,
        answer=answer,
        route_summary=route,
        claims=claims,
        citations=citations,
        partial_work=tuple(partial_work),
        failures=failures,
        next_actions=uncertainties,
        outcome_code=outcome_code,
        provenance=provenance,
        claim_supports=supports,
        answer_retained=answer_retained,
        route_category=Route.REGISTERED_CAPABILITY,
        capability_id=capability_id,
        operation=operation,
        selection_reason_code="PLAN_RESULT_AGGREGATED",
    )


class DirectFinalizer:
    """Present one validated result directly, with a safe template fallback."""

    def finalize(self, aggregation: PlanAggregation) -> TaskResult:
        if not isinstance(aggregation, PlanAggregation):
            raise InputInvalidError("direct finalizer requires a plan aggregation")
        items = _result_items(aggregation)
        if (
            aggregation.status is PlanStatus.COMPLETED
            and len(items) == 1
            and not aggregation.disagreements
            and not any(
                envelope.action_receipt is not None
                for envelope in aggregation.step_envelopes.values()
            )
        ):
            # Preserve the capability's already validated presentation result
            # byte-for-byte.  No direct finalizer prose is added in this case.
            return items[0][1]
        answer = render_template(aggregation)
        source = items[0][1] if len(items) == 1 else None
        return _build_aggregate_task_result(aggregation, answer=answer, direct_source=source)

    __call__ = finalize


class TemplateFinalizer:
    """Render exact statuses, failures, warnings, and receipts deterministically."""

    def finalize(self, aggregation: PlanAggregation) -> TaskResult:
        if not isinstance(aggregation, PlanAggregation):
            raise InputInvalidError("template finalizer requires a plan aggregation")
        return _build_aggregate_task_result(
            aggregation,
            answer=render_template(aggregation),
        )

    __call__ = finalize


def finalize_plan(aggregation: PlanAggregation) -> TaskResult:
    """Select a deterministic finalizer for one aggregated plan.

    The legacy ``LOCAL_SYNTHESIS`` value has no model authority; persisted
    plans using it receive the deterministic template before canonical response
    composition.
    """

    if not isinstance(aggregation, PlanAggregation):
        raise InputInvalidError("plan finalization requires a plan aggregation")
    if aggregation.finalization is FinalizationStrategy.DIRECT:
        return DirectFinalizer().finalize(aggregation)
    if aggregation.finalization is FinalizationStrategy.LOCAL_SYNTHESIS:
        return TemplateFinalizer().finalize(aggregation)
    return TemplateFinalizer().finalize(aggregation)


deterministic_finalize = finalize_plan
PlanResult = PlanAggregation
AggregatedPlanResult = PlanAggregation


def finalize_direct(aggregation: PlanAggregation) -> TaskResult:
    return DirectFinalizer().finalize(aggregation)


def finalize_template(aggregation: PlanAggregation) -> TaskResult:
    return TemplateFinalizer().finalize(aggregation)


__all__ = [
    "DisagreementRecord",
    "DirectFinalizer",
    "AggregatedPlanResult",
    "PlanAggregation",
    "PlanResult",
    "PlanStatusPolicy",
    "TemplateFinalizer",
    "aggregate_plan_results",
    "derive_plan_status",
    "detect_disagreements",
    "deterministic_finalize",
    "finalize_direct",
    "finalize_plan",
    "finalize_template",
    "legacy_source_aggregation",
    "render_template",
]
