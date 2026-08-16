"""Application-owned construction, validation, rendering, and fallback for synthesis.

The local model is allowed to choose presentation order only.  Every factual
record in the final answer is copied from an eligible typed step result by this
module, which makes unsupported model prose impossible to present.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import replace

from ..domain.enums import Route
from ..domain.errors import InputInvalidError, MalformedResultError
from ..domain.models import TaskRequest, TaskResult
from ..planning.contracts import (
    ExecutionPlan,
    FinalizationStrategy,
    StepKind,
    StepState,
)
from ..ports.local_synthesis import (
    SYNTHESIS_INPUT_SCHEMA_VERSION,
    SynthesisCitation,
    SynthesisClaim,
    SynthesisDisagreement,
    SynthesisDraft,
    SynthesisInput,
    SynthesisStepSummary,
    SynthesisWarning,
    decode_synthesis_draft,
)
from .plan_results import PlanAggregation, TemplateFinalizer, aggregate_plan_results
from .step_results import StepClaim, StepResultEnvelope


def _unique(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return tuple(result)


def _safe_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def source_aggregation(
    plan: ExecutionPlan,
    step_results: Mapping[str, TaskResult],
    step_envelopes: Mapping[str, StepResultEnvelope],
    states: Mapping[str, StepState],
) -> PlanAggregation:
    """Aggregate capability results before the local synthesis node runs."""

    source_steps = tuple(step for step in plan.steps if step.kind is not StepKind.LOCAL_SYNTHESIS)
    if not source_steps:
        raise InputInvalidError("local synthesis requires at least one source step")
    source_plan = replace(
        plan,
        steps=source_steps,
        finalization=FinalizationStrategy.TEMPLATE,
    )
    source_ids = {step.step_id for step in source_steps}
    return aggregate_plan_results(
        source_plan,
        {key: value for key, value in step_results.items() if key in source_ids},
        {key: value for key, value in step_envelopes.items() if key in source_ids},
        states={key: value for key, value in states.items() if key in source_ids},
        finalization_complete=True,
    )


def _claim_reference_ids(
    envelopes: Mapping[str, StepResultEnvelope],
    eligible_ids: tuple[str, ...],
) -> dict[tuple[str, str], str]:
    counts: dict[str, int] = {}
    for step_id in eligible_ids:
        envelope = envelopes.get(step_id)
        if envelope is None:
            continue
        for claim in envelope.claims:
            counts[claim.claim_id] = counts.get(claim.claim_id, 0) + 1
    references: dict[tuple[str, str], str] = {}
    for step_id in eligible_ids:
        envelope = envelopes.get(step_id)
        if envelope is None:
            continue
        for claim in envelope.claims:
            references[(step_id, claim.claim_id)] = (
                claim.claim_id if counts[claim.claim_id] == 1 else f"{step_id}:{claim.claim_id}"
            )
    return references


def _receipt_text(envelope: StepResultEnvelope) -> str:
    receipt = envelope.action_receipt
    if receipt is None:
        return ""
    provider_reference = (
        f"; provider_reference={receipt.provider_reference}" if receipt.provider_reference else ""
    )
    return (
        f"{receipt.receipt_id}: succeeded; capability={receipt.capability_id}; "
        f"operation={receipt.operation_id}; digest={receipt.action_digest}{provider_reference}"
    )


def build_synthesis_input(
    plan: ExecutionPlan,
    request: TaskRequest,
    approved_context: str,
    step_results: Mapping[str, TaskResult],
    step_envelopes: Mapping[str, StepResultEnvelope],
    states: Mapping[str, StepState],
) -> tuple[SynthesisInput, PlanAggregation]:
    """Minimize approved execution output into the local synthesis contract."""

    if not isinstance(plan, ExecutionPlan) or not isinstance(request, TaskRequest):
        raise InputInvalidError("synthesis input requires a validated plan and request")
    if not isinstance(approved_context, str) or not approved_context.strip():
        raise InputInvalidError("synthesis approved context must be non-empty")
    aggregation = source_aggregation(plan, step_results, step_envelopes, states)
    eligible_ids = aggregation.eligible_step_ids
    references = _claim_reference_ids(aggregation.step_envelopes, eligible_ids)

    citation_ids_by_step: dict[tuple[str, str], str] = {}
    citation_values: list[SynthesisCitation] = []
    claims: list[SynthesisClaim] = []
    claim_ids_by_step: dict[str, list[str]] = {}
    for step_id in eligible_ids:
        envelope = aggregation.step_envelopes.get(step_id)
        result = aggregation.step_results.get(step_id)
        raw_claims = envelope.claims if envelope is not None else ()
        if envelope is None and result is not None:
            raw_claims = tuple(
                StepClaim(claim_id=f"claim-{index}", text=text)
                for index, text in enumerate(result.claims, start=1)
            )
        step_claim_ids = [
            references.get((step_id, claim.claim_id), f"{step_id}:{claim.claim_id}")
            for claim in raw_claims
        ]
        claim_ids_by_step[step_id] = step_claim_ids
        raw_citations = (
            envelope.citations if envelope is not None else result.citations if result else ()
        )
        for citation in raw_citations:
            citation_id = _safe_id("citation", step_id, citation)
            if (step_id, citation) not in citation_ids_by_step:
                citation_ids_by_step[(step_id, citation)] = citation_id
                citation_values.append(
                    SynthesisCitation(
                        citation_id=citation_id,
                        text=citation,
                        step_id=step_id,
                        claim_ids=tuple(step_claim_ids),
                    )
                )
        citation_ids = tuple(
            citation_ids_by_step[(step_id, citation)] for citation in raw_citations
        )
        for claim in raw_claims:
            claim_id = references.get((step_id, claim.claim_id), f"{step_id}:{claim.claim_id}")
            claims.append(
                SynthesisClaim(
                    claim_id=claim_id,
                    text=claim.text,
                    step_id=step_id,
                    evidence_ids=claim.evidence_ids,
                    citation_ids=citation_ids,
                    support_status=claim.support_status,
                )
            )

    warnings: list[SynthesisWarning] = []
    warning_ids_by_step: dict[str, list[str]] = {}
    for step_id in eligible_ids:
        envelope = aggregation.step_envelopes.get(step_id)
        warning_ids: list[str] = []
        for warning in envelope.warnings if envelope is not None else ():
            warning_id = _safe_id("warning", step_id, warning)
            warning_ids.append(warning_id)
            warnings.append(SynthesisWarning(warning_id, warning, step_id))
        warning_ids_by_step[step_id] = warning_ids

    disagreements = tuple(
        SynthesisDisagreement(
            disagreement_id=item.disagreement_id,
            claim_id=item.claim_id,
            step_ids=item.step_ids,
            statements=item.statements,
            evidence_ids=item.evidence_ids,
            source_kind=item.source_kind,
            reason_code=item.reason_code,
        )
        for item in aggregation.disagreements
    )

    summaries: list[SynthesisStepSummary] = []
    for step in tuple(item for item in plan.steps if item.kind is not StepKind.LOCAL_SYNTHESIS):
        state = states[step.step_id]
        envelope = aggregation.step_envelopes.get(step.step_id)
        result = aggregation.step_results.get(step.step_id)
        eligible = step.step_id in eligible_ids
        summary = ""
        limitations: list[str] = []
        if eligible and envelope is not None:
            summary = envelope.answer or envelope.summary
            limitations.extend(envelope.assumptions)
            limitations.extend(envelope.uncertainties)
            limitations.extend(envelope.failures)
        elif eligible and result is not None and result.answer_retained:
            summary = result.answer
            limitations.extend(result.partial_work)
            limitations.extend(result.next_actions)
            limitations.extend(result.failures)
        else:
            limitations.append(f"presentation content unavailable; step state={state.value}")
            if result is not None:
                limitations.extend(result.failures)
        source_citations = (
            envelope.citations
            if envelope is not None
            else result.citations
            if result is not None
            else ()
        )
        summaries.append(
            SynthesisStepSummary(
                result_id=f"result-{step.step_id}",
                step_id=step.step_id,
                status=state,
                summary=summary,
                limitations=_unique(tuple(limitations)),
                claim_ids=tuple(claim_ids_by_step.get(step.step_id, ())),
                citation_ids=tuple(
                    citation_ids_by_step[(step.step_id, value)] for value in source_citations
                ),
                warning_ids=tuple(warning_ids_by_step.get(step.step_id, ())),
                action_receipt=_receipt_text(envelope) if envelope is not None else "",
            )
        )

    instructions = (
        "Use only the supplied result, claim, citation, warning, and disagreement IDs.",
        "Every result and mandatory warning must be represented in the outline.",
        "Keep UNKNOWN, PARTIAL, FAILED, BLOCKED, UNAVAILABLE, and CANCELLED visible.",
        "Do not create factual prose, citations, actions, receipts, or consensus.",
    )
    plan_summary = "; ".join(
        (
            f"plan_id={plan.plan_id}",
            f"finalization={plan.finalization.value}",
            "steps="
            + ",".join(f"{item.step_id}:{states[item.step_id].value}" for item in summaries),
        )
    )
    synthesis_input = SynthesisInput(
        schema_version=SYNTHESIS_INPUT_SCHEMA_VERSION,
        request_id=request.request_id,
        task_id=plan.task_id,
        plan_id=plan.plan_id,
        request_text=request.text,
        approved_context=approved_context,
        plan_summary=plan_summary,
        plan_status=aggregation.status,
        finalization=plan.finalization,
        step_summaries=tuple(summaries),
        claims=tuple(claims),
        citations=tuple(citation_values),
        warnings=tuple(warnings),
        disagreements=disagreements,
        uncertainties=_unique(aggregation.uncertainties),
        presentation_instructions=instructions,
    )
    return synthesis_input, aggregation


def _references_in_draft(draft: SynthesisDraft) -> tuple[set[str], set[str], set[str]]:
    result_ids: set[str] = set()
    claim_ids: set[str] = set()
    citation_ids: set[str] = set()
    for section in draft.sections:
        result_ids.update(section.result_ids)
        claim_ids.update(section.claim_ids)
        citation_ids.update(section.citation_ids)
    return result_ids, claim_ids, citation_ids


def validate_synthesis_draft(
    synthesis_input: SynthesisInput,
    draft: SynthesisDraft | str | bytes | Mapping[str, object],
) -> SynthesisDraft:
    """Reject every reference, status, or mandatory-record violation."""

    if not isinstance(synthesis_input, SynthesisInput):
        raise InputInvalidError("synthesis validation input is invalid")
    parsed = draft if isinstance(draft, SynthesisDraft) else decode_synthesis_draft(draft)
    if parsed.status is not synthesis_input.plan_status:
        raise MalformedResultError("synthesis draft changes the plan status")
    result_ids, claim_ids, citation_ids = _references_in_draft(parsed)
    known_results = set(synthesis_input.result_ids)
    known_claims = {item.claim_id for item in synthesis_input.claims}
    known_citations = {item.citation_id for item in synthesis_input.citations}
    for name, values, known in (
        ("result", result_ids, known_results),
        ("claim", claim_ids, known_claims),
        ("citation", citation_ids, known_citations),
    ):
        unknown = values - known
        if unknown:
            raise MalformedResultError(f"synthesis draft references an unknown {name}")
    if result_ids != known_results:
        raise MalformedResultError("synthesis draft omits an approved step result")
    if claim_ids != known_claims:
        raise MalformedResultError("synthesis draft omits an approved claim")
    if citation_ids != known_citations:
        raise MalformedResultError("synthesis draft omits an approved citation")

    known_warnings = {item.warning_id for item in synthesis_input.warnings}
    known_disagreements = {item.disagreement_id for item in synthesis_input.disagreements}
    for reference_name, reference_values, expected_ids in (
        ("warning", parsed.included_warning_ids, known_warnings),
        ("disagreement", parsed.included_disagreement_ids, known_disagreements),
    ):
        if (
            len(set(reference_values)) != len(reference_values)
            or set(reference_values) != expected_ids
        ):
            raise MalformedResultError(f"synthesis draft does not preserve every {reference_name}")

    claims_by_id = {item.claim_id: item for item in synthesis_input.claims}
    citations_by_id = {item.citation_id: item for item in synthesis_input.citations}
    safe_titles = {"", "Summary", "Findings", "Sources", "Limitations", "Disagreements"}
    safe_titles.update(item.step_id for item in synthesis_input.step_summaries)
    safe_titles.update(f"Step {item.step_id}" for item in synthesis_input.step_summaries)
    for section in parsed.sections:
        if section.title not in safe_titles:
            raise MalformedResultError("synthesis draft contains an unsupported section title")
        section_citations = set(section.citation_ids)
        for claim_id in section.claim_ids:
            missing = set(claims_by_id[claim_id].citation_ids) - section_citations
            if missing:
                raise MalformedResultError("synthesis draft separates a claim from its citations")
        for citation_id in section.citation_ids:
            citation = citations_by_id[citation_id]
            if not citation.claim_ids:
                raise MalformedResultError("synthesis citation is not attached to a claim")
            if not set(citation.claim_ids).intersection(section.claim_ids):
                raise MalformedResultError("synthesis draft detaches a citation from its claim")
    return parsed


def render_synthesis_text(synthesis_input: SynthesisInput, draft: SynthesisDraft) -> str:
    """Render only canonical records selected by a validated outline."""

    validated = validate_synthesis_draft(synthesis_input, draft)
    summaries = {item.result_id: item for item in synthesis_input.step_summaries}
    claims = {item.claim_id: item for item in synthesis_input.claims}
    citations = {item.citation_id: item for item in synthesis_input.citations}
    warnings = {item.warning_id: item for item in synthesis_input.warnings}
    disagreements = {item.disagreement_id: item for item in synthesis_input.disagreements}
    lines = [f"Plan status: {synthesis_input.plan_status.value}."]
    for section in validated.sections:
        if section.title:
            lines.append(section.title)
        for result_id in section.result_ids:
            summary = summaries[result_id]
            detail = summary.summary or "no presentation content retained"
            lines.append(f"{summary.step_id} [{summary.status.value}]: {detail}")
            for limitation in summary.limitations:
                lines.append(f"- Limitation: {limitation}")
            if summary.action_receipt:
                lines.append(f"- Action receipt: {summary.action_receipt}")
        for claim_id in section.claim_ids:
            claim = claims[claim_id]
            lines.append(f"- {claim.text}")
            lines.append(f"  Evidence status: {claim.support_status}")
            for citation_id in claim.citation_ids:
                citation = citations[citation_id]
                lines.append(f"  Citation {citation.citation_id}: {citation.text}")
    if synthesis_input.disagreements:
        lines.append("Disagreements:")
        for disagreement_id in validated.included_disagreement_ids:
            item = disagreements[disagreement_id]
            lines.append(f"- {item.disagreement_id}: " + " | ".join(item.statements))
    if synthesis_input.warnings:
        lines.append("Warnings:")
        for warning_id in validated.included_warning_ids:
            lines.append(f"- {warnings[warning_id].text}")
    if synthesis_input.uncertainties:
        lines.append("Uncertainties:")
        lines.extend(f"- {item}" for item in synthesis_input.uncertainties)
    return "\n".join(lines)


def render_synthesis_draft(
    synthesis_input: SynthesisInput,
    draft: SynthesisDraft,
    aggregation: PlanAggregation | None = None,
) -> str | TaskResult:
    """Render text, or a complete result when an aggregation is supplied."""

    text = render_synthesis_text(synthesis_input, draft)
    if aggregation is None:
        return text
    if not isinstance(aggregation, PlanAggregation):
        raise InputInvalidError("synthesis rendering aggregation is invalid")
    result = TemplateFinalizer().finalize(aggregation)
    return replace(
        result,
        answer=text,
        answer_retained=True,
        route_summary=Route.LOCAL_CONVERSATION,
        route_category=Route.LOCAL_CONVERSATION,
        capability_id=None,
        operation="synthesis.compose",
        selection_reason_code="SYNTHESIS_VALIDATED",
    )


def deterministic_synthesis_fallback(
    aggregation: PlanAggregation,
    reason_code: str,
) -> TaskResult:
    """Return a visible, deterministic template when synthesis is unsafe/unavailable."""

    if not isinstance(aggregation, PlanAggregation):
        raise InputInvalidError("synthesis fallback aggregation is invalid")
    safe_reason = reason_code.strip() or "SYNTHESIS_FAILED"
    result = TemplateFinalizer().finalize(aggregation)
    failure = f"local synthesis fallback used: {safe_reason}"
    return replace(
        result,
        answer=result.answer + "\nSynthesis fallback: deterministic template used.",
        failures=_unique(tuple(result.failures) + (failure,)),
        route_summary=Route.LOCAL_CONVERSATION,
        route_category=Route.LOCAL_CONVERSATION,
        capability_id=None,
        operation="synthesis.compose",
        selection_reason_code="SYNTHESIS_FALLBACK",
    )


# Compatibility/readability aliases for callers using the design terminology.
build_bounded_synthesis_input = build_synthesis_input
validate_draft = validate_synthesis_draft
render_validated_synthesis = render_synthesis_draft


__all__ = [
    "build_bounded_synthesis_input",
    "build_synthesis_input",
    "deterministic_synthesis_fallback",
    "render_synthesis_draft",
    "render_synthesis_text",
    "render_validated_synthesis",
    "source_aggregation",
    "validate_draft",
    "validate_synthesis_draft",
]
