"""Common V3.5 post-aggregation response-composition pipeline.

This module is the application-owned boundary between validated workflow
results and the local response-composer model.  It builds bounded reference
contracts, invokes the composer once, validates every selected reference, and
assembles canonical content deterministically.  A failed composition leaves
the original task status and epistemic metadata untouched.
"""

from __future__ import annotations

import hashlib
import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

from ..domain.enums import PresentationMode
from ..domain.errors import InputInvalidError, MalformedResultError
from ..domain.models import TaskRequest, TaskResult
from ..planning.contracts import StepKind
from ..ports.local_response_composer import (
    RESPONSE_COMPOSITION_INPUT_SCHEMA_VERSION,
    LocalResponseComposerPort,
    ResponseCitationSummary,
    ResponseClaimSummary,
    ResponseCompositionDraft,
    ResponseCompositionInput,
    ResponseCompositionRequest,
    ResponseDisagreementSummary,
    ResponseResultSummary,
    ResponseWarningSummary,
    decode_response_composition_draft,
)
from .plan_results import PlanAggregation, finalize_plan
from .presentation_policy import mode_for_plan_aggregation, select_presentation_mode
from .step_results import ActionExecutionReceipt, StepClaim, StepResultEnvelope

if TYPE_CHECKING:
    from .execution import CancellationToken

def _ref(prefix: str, *parts: object) -> str:
    digest = hashlib.sha256("\x00".join(str(item) for item in parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _receipt_text(receipt: ActionExecutionReceipt) -> str:
    provider_reference = (
        f"; provider_reference={receipt.provider_reference}" if receipt.provider_reference else ""
    )
    return (
        f"{receipt.receipt_id}: succeeded; capability={receipt.capability_id}; "
        f"operation={receipt.operation_id}; digest={receipt.action_digest}{provider_reference}"
    )


def _aggregation_exact_records(aggregation: PlanAggregation) -> dict[str, str]:
    """Recover exact action records even when the bounded input is too large."""

    records: dict[str, str] = {}
    for step_id, envelope in aggregation.step_envelopes.items():
        receipt = envelope.action_receipt
        if receipt is None:
            continue
        result_ref = f"result-{step_id}"
        records[_ref("record", aggregation.task_id, result_ref, receipt.receipt_id)] = _receipt_text(
            receipt
        )
    return records


@dataclass(frozen=True, slots=True)
class _CompositionMaterial:
    """Canonical maps retained only inside the application assembler."""

    result_text: Mapping[str, str]
    result_status: Mapping[str, str]
    result_limitations: Mapping[str, tuple[str, ...]]
    claims: Mapping[str, ResponseClaimSummary]
    citations: Mapping[str, ResponseCitationSummary]
    warnings: Mapping[str, ResponseWarningSummary]
    disagreements: Mapping[str, ResponseDisagreementSummary]
    exact_records: Mapping[str, str]
    canonical_result: TaskResult


@dataclass(frozen=True, slots=True)
class ResponseCompositionObservation:
    """Safe structured telemetry for one presentation decision."""

    mode: PresentationMode
    outcome: str
    attempted: bool
    profile: str = ""
    model_version: str = ""
    result_refs: tuple[str, ...] = ()
    claim_refs: tuple[str, ...] = ()
    citation_refs: tuple[str, ...] = ()
    warning_refs: tuple[str, ...] = ()
    disagreement_refs: tuple[str, ...] = ()
    immutable_record_refs: tuple[str, ...] = ()
    reason_code: str = ""
    duration_ms: int = 0
    output_tokens: int = 0


@dataclass(frozen=True, slots=True)
class ResponsePipelineResult:
    """Final result plus composition contract and safe observation."""

    result: TaskResult
    mode: PresentationMode
    input: ResponseCompositionInput | None = None
    draft: ResponseCompositionDraft | None = None
    observation: ResponseCompositionObservation | None = None


def _result_summary(
    *,
    task_id: str,
    result_ref: str,
    result: TaskResult,
    envelope: StepResultEnvelope | None,
    claim_refs: tuple[str, ...],
    citation_refs: tuple[str, ...],
    warning_refs: tuple[str, ...],
    record_refs: tuple[str, ...],
) -> ResponseResultSummary:
    summary = envelope.answer or envelope.summary if envelope is not None else result.answer
    limitations = (
        tuple(envelope.assumptions) + tuple(envelope.uncertainties) + tuple(envelope.failures)
        if envelope is not None
        else tuple(result.partial_work) + tuple(result.next_actions) + tuple(result.failures)
    )
    return ResponseResultSummary(
        result_ref=result_ref,
        task_id=task_id,
        status=(envelope.status.value if envelope is not None else result.task_status.value),
        summary=summary,
        epistemic_status=(
            envelope.epistemic_status.value if envelope is not None else result.epistemic_status.value
        ),
        claim_refs=claim_refs,
        citation_refs=citation_refs,
        warning_refs=warning_refs,
        immutable_record_refs=record_refs,
        limitations=_unique(limitations),
    )


def _build_material_from_results(
    *,
    task_id: str,
    results: Sequence[tuple[str, TaskResult, StepResultEnvelope | None]],
    disagreements: Sequence[object] = (),
    canonical_result: TaskResult,
    exact_records: Mapping[str, str] | None = None,
) -> tuple[ResponseCompositionInput, _CompositionMaterial]:
    result_summaries: list[ResponseResultSummary] = []
    claims: dict[str, ResponseClaimSummary] = {}
    citations: dict[str, ResponseCitationSummary] = {}
    warnings: dict[str, ResponseWarningSummary] = {}
    records: dict[str, str] = dict(exact_records or {})
    result_text: dict[str, str] = {}
    result_status: dict[str, str] = {}
    limitations: dict[str, tuple[str, ...]] = {}
    for result_ref, result, envelope in results:
        raw_claims = envelope.claims if envelope is not None else ()
        if not raw_claims and result.claims:
            raw_claims = tuple(
                StepClaim(claim_id=f"claim-{index}", text=text)
                for index, text in enumerate(result.claims, start=1)
            )
        claim_refs: list[str] = []
        for claim in raw_claims:
            claim_ref = _ref("claim", task_id, result_ref, claim.claim_id)
            claim_refs.append(claim_ref)
            claim_support = next(
                (item for item in result.claim_supports if item.claim_id == claim.claim_id), None
            )
            evidence_refs = claim.evidence_ids
            support_status = claim.support_status
            if claim_support is not None:
                evidence_refs = _unique(tuple(evidence_refs) + tuple(claim_support.evidence_ids))
                support_status = claim_support.support_status
            claims[claim_ref] = ResponseClaimSummary(
                claim_ref=claim_ref,
                task_id=task_id,
                result_ref=result_ref,
                text=claim.text,
                support_status=support_status,
                evidence_refs=evidence_refs,
            )

        raw_citations = envelope.citations if envelope is not None else result.citations
        citation_refs: list[str] = []
        for citation in raw_citations:
            citation_ref = _ref("citation", task_id, result_ref, citation)
            citation_refs.append(citation_ref)
            citations[citation_ref] = ResponseCitationSummary(
                citation_ref=citation_ref,
                task_id=task_id,
                result_ref=result_ref,
                text=citation,
                claim_refs=tuple(claim_refs),
            )
        if citation_refs:
            for claim_ref in claim_refs:
                claims[claim_ref] = replace(
                    claims[claim_ref],
                    citation_refs=tuple(citation_refs),
                )

        raw_warnings = envelope.warnings if envelope is not None else ()
        warning_refs: list[str] = []
        for warning in raw_warnings:
            warning_ref = _ref("warning", task_id, result_ref, warning)
            warning_refs.append(warning_ref)
            warnings[warning_ref] = ResponseWarningSummary(
                warning_ref=warning_ref,
                task_id=task_id,
                result_ref=result_ref,
                text=warning,
            )

        record_refs: list[str] = []
        receipt = envelope.action_receipt if envelope is not None else None
        if receipt is not None:
            record_ref = _ref("record", task_id, result_ref, receipt.receipt_id)
            record_refs.append(record_ref)
            records[record_ref] = _receipt_text(receipt)

        summary = _result_summary(
            task_id=task_id,
            result_ref=result_ref,
            result=result,
            envelope=envelope,
            claim_refs=tuple(claim_refs),
            citation_refs=tuple(citation_refs),
            warning_refs=tuple(warning_refs),
            record_refs=tuple(record_refs),
        )
        result_summaries.append(summary)
        result_text[result_ref] = summary.summary
        result_status[result_ref] = summary.status
        limitations[result_ref] = summary.limitations

    disagreement_summaries: list[ResponseDisagreementSummary] = []
    for item in disagreements:
        disagreement_ref = _identifier_for_disagreement(getattr(item, "disagreement_id"))
        result_refs = tuple(
            f"result-{step_id}" for step_id in getattr(item, "step_ids", ()) if f"result-{step_id}" in result_text
        )
        if len(result_refs) < 2:
            continue
        disagreement_summaries.append(
            ResponseDisagreementSummary(
                disagreement_ref=disagreement_ref,
                task_id=task_id,
                result_refs=result_refs,
                statements=tuple(getattr(item, "statements", ())),
                claim_ref=(
                    next(
                        (
                            ref
                            for ref, claim in claims.items()
                            if claim.result_ref in result_refs
                            and claim.text == getattr(item, "claim_id", "")
                        ),
                        "",
                    )
                ),
                evidence_refs=tuple(getattr(item, "evidence_ids", ())),
            )
        )

    result_refs = tuple(item[0] for item in results)
    all_claim_refs = tuple(claims)
    all_citation_refs = tuple(citations)
    all_warning_refs = tuple(warnings)
    disagreement_refs = tuple(item.disagreement_ref for item in disagreement_summaries)
    all_record_refs = tuple(records)
    input_value = ResponseCompositionInput(
        schema_version=RESPONSE_COMPOSITION_INPUT_SCHEMA_VERSION,
        task_id=task_id,
        request_text=canonical_result.answer or "Present the validated result.",
        presentation_mode=select_presentation_mode(
            task_status=canonical_result.task_status,
            has_immutable_record=bool(all_record_refs),
        ),
        task_status=canonical_result.task_status.value,
        result_refs=result_refs,
        claim_refs=all_claim_refs,
        citation_refs=all_citation_refs,
        warning_refs=all_warning_refs,
        disagreement_refs=disagreement_refs,
        immutable_record_refs=all_record_refs,
        result_summaries=tuple(result_summaries),
        claim_summaries=tuple(claims.values()),
        citation_summaries=tuple(citations.values()),
        warning_summaries=tuple(warnings.values()),
        disagreement_summaries=tuple(disagreement_summaries),
    )
    return input_value, _CompositionMaterial(
        result_text=MappingProxyType(result_text),
        result_status=MappingProxyType(result_status),
        result_limitations=MappingProxyType(limitations),
        claims=MappingProxyType(claims),
        citations=MappingProxyType(citations),
        warnings=MappingProxyType(warnings),
        disagreements=MappingProxyType(
            {item.disagreement_ref: item for item in disagreement_summaries}
        ),
        exact_records=MappingProxyType(records),
        canonical_result=canonical_result,
    )


def _identifier_for_disagreement(value: object) -> str:
    if isinstance(value, str) and value and all(
        char.isalnum() or char in "_.:-" for char in value
    ):
        return value
    return _ref("disagreement", value)


def build_response_composition_input(
    aggregation: PlanAggregation,
    *,
    request_text: str,
    request_id: str = "",
    approved_context: str = "",
    presentation_mode: PresentationMode | None = None,
) -> tuple[ResponseCompositionInput, _CompositionMaterial]:
    """Build a bounded composer input from a validated plan aggregation."""

    if not isinstance(aggregation, PlanAggregation):
        raise InputInvalidError("response composition requires a plan aggregation")
    canonical = finalize_plan(aggregation)
    source: list[tuple[str, TaskResult, StepResultEnvelope | None]] = []
    plan_steps = {step.step_id: step for step in aggregation.plan.steps}
    for step_id in aggregation.eligible_step_ids:
        # A persisted V3 terminal synthesis result is a presentation artifact,
        # not a new source of authority in V3.5.  Re-compose the validated
        # capability results instead of feeding old model prose back in.
        if plan_steps.get(step_id) is not None and plan_steps[step_id].kind is StepKind.LOCAL_SYNTHESIS:
            continue
        result = aggregation.step_results.get(step_id)
        if result is None:
            continue
        source.append((f"result-{step_id}", result, aggregation.step_envelopes.get(step_id)))
    # A blocked/failed plan still receives one bounded result reference so the
    # composer can organize an explanation rather than being bypassed.
    if not source:
        source.append((f"result-{aggregation.task_id}", canonical, None))
    input_value, material = _build_material_from_results(
        task_id=aggregation.task_id,
        results=source,
        disagreements=aggregation.disagreements,
        canonical_result=canonical,
    )
    mode = presentation_mode or mode_for_plan_aggregation(aggregation)
    input_value = replace(
        input_value,
        request_id=request_id,
        request_text=request_text,
        approved_context=approved_context,
        presentation_mode=mode,
    )
    return input_value, material


def build_task_response_composition_input(
    result: TaskResult,
    *,
    request_text: str,
    request_id: str = "",
    approved_context: str = "",
    presentation_mode: PresentationMode | None = None,
    immutable_records: Mapping[str, str] | None = None,
) -> tuple[ResponseCompositionInput, _CompositionMaterial]:
    """Build the same contract for a local-only or direct specialist result."""

    if not isinstance(result, TaskResult):
        raise InputInvalidError("response composition requires a TaskResult")
    result_ref = f"result-{result.task_id}"
    input_value, material = _build_material_from_results(
        task_id=result.task_id,
        results=((result_ref, result, None),),
        canonical_result=result,
        exact_records=immutable_records,
    )
    mode = presentation_mode or select_presentation_mode(
        task_status=result.task_status,
        has_immutable_record=bool(immutable_records),
    )
    input_value = replace(
        input_value,
        request_id=request_id,
        request_text=request_text,
        approved_context=approved_context,
        presentation_mode=mode,
    )
    return input_value, material


def _section_refs(draft: ResponseCompositionDraft) -> tuple[set[str], set[str], set[str], set[str]]:
    results: set[str] = set()
    claims: set[str] = set()
    citations: set[str] = set()
    records: set[str] = set()
    for section in draft.sections:
        results.update(section.result_refs)
        claims.update(section.claim_refs)
        citations.update(section.citation_refs)
        records.update(section.immutable_record_refs)
    return results, claims, citations, records


def validate_response_composition_draft(
    composition_input: ResponseCompositionInput,
    draft: ResponseCompositionDraft | str | bytes | Mapping[str, object],
) -> ResponseCompositionDraft:
    """Reject unknown, duplicate, cross-task, or omitted mandatory references."""

    if not isinstance(composition_input, ResponseCompositionInput):
        raise InputInvalidError("response composition validation input is invalid")
    parsed = draft if isinstance(draft, ResponseCompositionDraft) else decode_response_composition_draft(draft)
    if parsed.task_status is not None and parsed.task_status != composition_input.task_status:
        raise MalformedResultError("response composition draft changes task status")
    section_results, section_claims, section_citations, section_records = _section_refs(parsed)
    expected = (
        ("result", section_results, set(composition_input.result_refs), parsed.referenced_result_ids),
        ("claim", section_claims, set(composition_input.claim_refs), parsed.referenced_claim_ids),
        ("citation", section_citations, set(composition_input.citation_refs), parsed.referenced_citation_ids),
        (
            "immutable record",
            section_records,
            set(composition_input.immutable_record_refs),
            parsed.referenced_immutable_record_ids,
        ),
    )
    for name, section_values, known, declared in expected:
        if section_values - known or set(declared) - known:
            raise MalformedResultError(f"response composition draft references an unknown {name}")
        if len(declared) != len(set(declared)):
            raise MalformedResultError(f"response composition draft duplicates a {name} reference")
        if set(declared) != section_values:
            raise MalformedResultError(
                f"response composition draft declarations do not match its {name} sections"
            )
        if section_values != known:
            raise MalformedResultError(
                f"response composition draft omits an approved {name} reference"
            )
    for attribute, label in (
        ("result_refs", "result"),
        ("claim_refs", "claim"),
        ("citation_refs", "citation"),
        ("immutable_record_refs", "immutable record"),
    ):
        values = [
            ref
            for section in parsed.sections
            for ref in getattr(section, attribute)
        ]
        if len(values) != len(set(values)):
            raise MalformedResultError(
                f"response composition draft duplicates a {label} reference"
            )

    claims = {item.claim_ref: item for item in composition_input.claim_summaries}
    citations = {item.citation_ref: item for item in composition_input.citation_summaries}
    results = set(composition_input.result_refs)
    for section in parsed.sections:
        # V3.5 cannot safely prove that arbitrary model prose is merely
        # presentational. Keep the fields in the migration-compatible wire
        # schema, but accept only empty values until a closed, deterministic
        # framing vocabulary is introduced.
        if section.title or section.narrative:
            raise MalformedResultError(
                "response composition draft contains unsupported model-authored prose"
            )
        for claim_ref in section.claim_refs:
            if claim_ref not in claims:
                raise MalformedResultError("response composition references an unknown claim")
            claim = claims[claim_ref]
            if claim.result_ref not in section.result_refs:
                raise MalformedResultError("response composition detaches a claim from its result")
            missing = set(claim.citation_refs) - set(section.citation_refs)
            if missing:
                raise MalformedResultError("response composition detaches a claim from its citations")
        for citation_ref in section.citation_refs:
            if citation_ref not in citations:
                raise MalformedResultError("response composition references an unknown citation")
            citation = citations[citation_ref]
            if citation.result_ref not in section.result_refs:
                raise MalformedResultError("response composition detaches a citation from its result")
            if citation.claim_refs and not set(citation.claim_refs).intersection(section.claim_refs):
                raise MalformedResultError("response composition detaches a citation from its claim")
        if not set(section.result_refs).issubset(results):
            raise MalformedResultError("response composition contains a cross-task result")
    expected_warnings = set(composition_input.warning_refs)
    expected_disagreements = set(composition_input.disagreement_refs)
    if set(parsed.acknowledged_warning_ids) != expected_warnings:
        raise MalformedResultError("response composition does not preserve every warning")
    if set(parsed.acknowledged_disagreement_ids) != expected_disagreements:
        raise MalformedResultError("response composition does not preserve every disagreement")
    if composition_input.immutable_record_refs:
        if section_records != set(composition_input.immutable_record_refs):
            raise MalformedResultError("response composition omits an immutable record")
    return parsed


def render_response_composition(
    composition_input: ResponseCompositionInput,
    draft: ResponseCompositionDraft,
    material: _CompositionMaterial,
) -> str:
    """Insert canonical content according to a validated model outline."""

    validated = validate_response_composition_draft(composition_input, draft)
    lines = (
        [material.canonical_result.answer]
        if len(composition_input.result_refs) == 1
        and material.canonical_result.answer.strip()
        else [f"Task status: {composition_input.task_status}."]
    )
    for section in validated.sections:
        for result_ref in section.result_refs:
            status = material.result_status[result_ref]
            detail = material.result_text[result_ref] or "no presentation content retained"
            lines.append(f"[{status}]: {detail}")
            for limitation in material.result_limitations[result_ref]:
                lines.append(f"- Limitation: {limitation}")
        for claim_ref in section.claim_refs:
            claim = material.claims[claim_ref]
            lines.append(f"- {claim.text}")
            lines.append(f"  Evidence status: {claim.support_status}")
        for citation_ref in section.citation_refs:
            citation = material.citations[citation_ref]
            lines.append(f"  Citation {citation.citation_ref}: {citation.text}")
        for record_ref in section.immutable_record_refs:
            # The exact record text is copied verbatim after validation.
            record = material.exact_records[record_ref]
            if record not in "\n".join(lines):
                lines.append(record)
    if composition_input.disagreement_refs:
        lines.append("Disagreements:")
        for ref in validated.acknowledged_disagreement_ids:
            item = material.disagreements[ref]
            lines.append(f"- {ref}: " + " | ".join(item.statements))
    if composition_input.warning_refs:
        lines.append("Warnings:")
        for ref in validated.acknowledged_warning_ids:
            lines.append(f"- {material.warnings[ref].text}")
    if composition_input.immutable_record_refs and not any(
        set(section.immutable_record_refs) for section in validated.sections
    ):
        lines.append("Exact records:")
        lines.extend(material.exact_records[ref] for ref in composition_input.immutable_record_refs)
    return "\n".join(lines)


class ResponseCompositionService:
    """Exactly-once local composition plus deterministic fallback."""

    def __init__(
        self,
        *,
        composer: object | None,
        max_output_tokens: int = 1600,
        timeout_seconds: float = 120.0,
        profile: str = "",
        model_version: str = "",
    ) -> None:
        if composer is not None and not callable(getattr(composer, "compose", None)):
            raise InputInvalidError("response composer must implement LocalResponseComposerPort")
        if (
            isinstance(max_output_tokens, bool)
            or not isinstance(max_output_tokens, int)
            or not 0 < max_output_tokens <= 100_000
        ):
            raise InputInvalidError("response composer output limit must be positive")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or not 0 < timeout_seconds <= 3_600
        ):
            raise InputInvalidError("response composer timeout must be positive")
        self._composer = composer
        self._max_output_tokens = max_output_tokens
        self._timeout_seconds = float(timeout_seconds)
        self._profile = profile
        self._model_version = model_version

    @property
    def composer(self) -> object | None:
        return self._composer

    def compose_aggregation(
        self,
        aggregation: PlanAggregation,
        *,
        request: TaskRequest,
        approved_context: str = "",
        presentation_mode: PresentationMode | None = None,
        cancellation: CancellationToken | None = None,
    ) -> ResponsePipelineResult:
        try:
            input_value, material = build_response_composition_input(
                aggregation,
                request_text=request.text,
                request_id=request.request_id,
                approved_context=approved_context,
                presentation_mode=presentation_mode,
            )
        except Exception:
            canonical = finalize_plan(aggregation)
            return self._input_fallback(
                canonical,
                presentation_mode or mode_for_plan_aggregation(aggregation),
                "RESPONSE_COMPOSER_INPUT_INVALID",
                immutable_records=_aggregation_exact_records(aggregation),
            )
        return self._compose(input_value, material, request.request_id, cancellation=cancellation)

    def compose_task_result(
        self,
        result: TaskResult,
        *,
        request: TaskRequest,
        approved_context: str = "",
        presentation_mode: PresentationMode | None = None,
        immutable_records: Mapping[str, str] | None = None,
        cancellation: CancellationToken | None = None,
    ) -> ResponsePipelineResult:
        try:
            input_value, material = build_task_response_composition_input(
                result,
                request_text=request.text,
                request_id=request.request_id,
                approved_context=approved_context,
                presentation_mode=presentation_mode,
                immutable_records=immutable_records,
            )
        except Exception:
            return self._input_fallback(
                result,
                presentation_mode
                or select_presentation_mode(
                    task_status=result.task_status,
                    has_immutable_record=bool(immutable_records),
                ),
                "RESPONSE_COMPOSER_INPUT_INVALID",
                immutable_records=immutable_records,
            )
        return self._compose(input_value, material, request.request_id, cancellation=cancellation)

    def _compose(
        self,
        input_value: ResponseCompositionInput,
        material: _CompositionMaterial,
        request_id: str,
        *,
        cancellation: CancellationToken | None = None,
    ) -> ResponsePipelineResult:
        mode = input_value.presentation_mode
        refs = input_value.result_refs
        claims = input_value.claim_refs
        citations = input_value.citation_refs
        if mode is PresentationMode.DETERMINISTIC_ONLY:
            observation = ResponseCompositionObservation(
                mode=mode,
                outcome="bypassed",
                attempted=False,
                profile=self._profile,
                model_version=self._model_version,
                result_refs=refs,
                claim_refs=claims,
                citation_refs=citations,
                warning_refs=input_value.warning_refs,
                disagreement_refs=input_value.disagreement_refs,
                immutable_record_refs=input_value.immutable_record_refs,
                reason_code="PRESENTATION_POLICY_DETERMINISTIC_ONLY",
            )
            return ResponsePipelineResult(material.canonical_result, mode, input_value, observation=observation)

        if self._composer is None:
            return self._fallback(input_value, material, "RESPONSE_COMPOSER_UNAVAILABLE", attempted=True)
        composer = cast(LocalResponseComposerPort, self._composer)
        composition_request = ResponseCompositionRequest(
            request_id=request_id,
            composition_input=input_value,
            max_output_tokens=self._max_output_tokens,
            timeout_seconds=self._timeout_seconds,
        )
        started = time.monotonic()
        unregister = (
            cancellation.register(self.cancel) if cancellation is not None else lambda: None
        )
        try:
            draft = composer.compose(composition_request)
            validated = validate_response_composition_draft(input_value, draft)
            answer = render_response_composition(input_value, validated, material)
            composed = replace(material.canonical_result, answer=answer, answer_retained=True)
            observation = ResponseCompositionObservation(
                mode=mode,
                outcome="accepted",
                attempted=True,
                profile=self._profile,
                model_version=self._model_version,
                result_refs=refs,
                claim_refs=claims,
                citation_refs=citations,
                warning_refs=input_value.warning_refs,
                disagreement_refs=input_value.disagreement_refs,
                immutable_record_refs=input_value.immutable_record_refs,
                reason_code="RESPONSE_COMPOSITION_ACCEPTED",
                duration_ms=int((time.monotonic() - started) * 1000),
                output_tokens=self._composer_output_tokens(),
            )
            return ResponsePipelineResult(composed, mode, input_value, validated, observation)
        except Exception as exc:  # provider and draft failures are isolated
            reason = self._reason_code(exc)
            return self._fallback(input_value, material, reason, attempted=True, started=started)
        finally:
            unregister()

    def cancel(self) -> None:
        """Forward one cooperative cancellation request to the active adapter."""

        cancel = getattr(self._composer, "cancel", None)
        if callable(cancel):
            cancel()

    def _fallback(
        self,
        input_value: ResponseCompositionInput,
        material: _CompositionMaterial,
        reason: str,
        *,
        attempted: bool,
        started: float | None = None,
    ) -> ResponsePipelineResult:
        canonical = material.canonical_result
        answer = canonical.answer
        if not answer:
            fallback_lines: list[str] = []
            for ref in input_value.result_refs:
                detail = material.result_text[ref]
                if detail:
                    fallback_lines.append(
                        f"{ref} [{material.result_status[ref]}]: {detail}"
                    )
                fallback_lines.extend(
                    f"- Limitation: {item}"
                    for item in material.result_limitations[ref]
                )
            if not fallback_lines:
                fallback_lines.append(f"Task status: {input_value.task_status}.")
                fallback_lines.extend(f"- Failure: {item}" for item in canonical.failures)
                fallback_lines.extend(f"- Next action: {item}" for item in canonical.next_actions)
            answer = "\n".join(fallback_lines)
        missing_records = tuple(
            record for record in material.exact_records.values() if record not in answer
        )
        if missing_records:
            answer += "\n" + "\n".join(missing_records)
        if material.claims:
            answer += "\nClaims:\n" + "\n".join(
                f"- {item.text} (evidence: {item.support_status})"
                for item in material.claims.values()
            )
        if material.citations:
            answer += "\nCitations:\n" + "\n".join(
                f"- {item.text}" for item in material.citations.values()
            )
        limitations = tuple(
            limitation
            for ref in input_value.result_refs
            for limitation in material.result_limitations[ref]
        )
        if limitations:
            answer += "\nLimitations:\n" + "\n".join(f"- {item}" for item in limitations)
        if material.disagreements:
            answer += "\nDisagreements:\n" + "\n".join(
                f"- {' | '.join(item.statements)}"
                for item in material.disagreements.values()
            )
        if material.warnings:
            answer += "\nWarnings:\n" + "\n".join(
                f"- {item.text}" for item in material.warnings.values()
            )
        result = replace(
            canonical,
            answer=answer,
            answer_retained=bool(answer.strip()),
        )
        observation = ResponseCompositionObservation(
            mode=input_value.presentation_mode,
            outcome="rejected" if attempted else "bypassed",
            attempted=attempted,
            profile=self._profile,
            model_version=self._model_version,
            result_refs=input_value.result_refs,
            claim_refs=input_value.claim_refs,
            citation_refs=input_value.citation_refs,
            warning_refs=input_value.warning_refs,
            disagreement_refs=input_value.disagreement_refs,
            immutable_record_refs=input_value.immutable_record_refs,
            reason_code=reason,
            duration_ms=int((time.monotonic() - started) * 1000) if started is not None else 0,
        )
        return ResponsePipelineResult(result, input_value.presentation_mode, input_value, observation=observation)

    def _input_fallback(
        self,
        canonical: TaskResult,
        mode: PresentationMode,
        reason: str,
        immutable_records: Mapping[str, str] | None = None,
    ) -> ResponsePipelineResult:
        """Keep oversized or otherwise invalid bounded inputs off the model path."""

        lines = [canonical.answer] if canonical.answer else []
        lines.append(f"Task status: {canonical.task_status.value}.")
        if canonical.claims:
            lines.append("Claims:")
            lines.extend(f"- {item}" for item in canonical.claims)
        if canonical.citations:
            lines.append("Citations:")
            lines.extend(f"- {item}" for item in canonical.citations)
        lines.extend(f"- Partial work: {item}" for item in canonical.partial_work)
        lines.extend(f"- Failure: {item}" for item in canonical.failures)
        lines.extend(f"- Next action: {item}" for item in canonical.next_actions)
        missing_records = tuple(
            record
            for record in (immutable_records or {}).values()
            if isinstance(record, str) and record not in "\n".join(lines)
        )
        if missing_records:
            lines.append("Exact records:")
            lines.extend(missing_records)
        answer = "\n".join(line for line in lines if line)
        result = replace(
            canonical,
            answer=answer,
            answer_retained=bool(answer.strip()),
        )
        observation = ResponseCompositionObservation(
            mode=mode,
            outcome="rejected",
            attempted=False,
            profile=self._profile,
            model_version=self._model_version,
            immutable_record_refs=tuple((immutable_records or {}).keys()),
            reason_code=reason,
        )
        return ResponsePipelineResult(result, mode, observation=observation)

    @staticmethod
    def _reason_code(error: Exception) -> str:
        name = type(error).__name__.upper()
        if "TIMEOUT" in name:
            return "RESPONSE_COMPOSER_TIMEOUT"
        if "MALFORMED" in name or "VALUE" in name or "TYPE" in name or "INPUT" in name:
            return "RESPONSE_COMPOSER_DRAFT_INVALID"
        if "UNAVAILABLE" in name or "PROVIDER" in name:
            return "RESPONSE_COMPOSER_UNAVAILABLE"
        return "RESPONSE_COMPOSER_FAILED"

    def _composer_output_tokens(self) -> int:
        value = getattr(self._composer, "last_output_tokens", 0)
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


# Vocabulary aliases for code that uses the design document's verbs.
build_composition_input = build_response_composition_input
validate_composition_draft = validate_response_composition_draft


__all__ = [
    "ResponseCompositionObservation",
    "ResponseCompositionService",
    "ResponsePipelineResult",
    "build_composition_input",
    "build_response_composition_input",
    "build_task_response_composition_input",
    "render_response_composition",
    "validate_composition_draft",
    "validate_response_composition_draft",
]
