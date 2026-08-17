"""Pure SQLite serialization codecs for provider-neutral records."""

from __future__ import annotations

from datetime import datetime, timezone

from elly.domain.enums import EpistemicStatus, OutcomeCode, Route, TaskStatus, ValidationStatus
from elly.domain.models import ClaimSupport, ProvenanceReference, TaskResult


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse(dt: str) -> datetime:
    return datetime.fromisoformat(dt).astimezone(timezone.utc)


def _task_result_payload(
    result: TaskResult,
    *,
    answer: str,
    answer_retained: bool,
    claims: tuple[str, ...],
    partial_work: tuple[str, ...],
) -> dict[str, object]:
    """Encode the provider-neutral result contract for ``step_results``."""

    return {
        "task_id": result.task_id,
        "task_status": result.task_status.value,
        "outcome_code": result.outcome_code.value,
        "epistemic_status": result.epistemic_status.value,
        "validation_status": result.validation_status.value,
        "answer": answer,
        "answer_retained": answer_retained,
        "route_summary": result.route_summary.value,
        "claims": list(claims),
        "citations": list(result.citations),
        "partial_work": list(partial_work),
        "failures": list(result.failures),
        "next_actions": list(result.next_actions),
        "provenance": [
            {
                "kind": item.kind,
                "reference_id": item.reference_id,
                "recorded_at": item.recorded_at.isoformat()
                if item.recorded_at is not None
                else None,
            }
            for item in result.provenance
        ],
        "claim_supports": [
            {
                "claim_id": item.claim_id,
                "text": item.text,
                "support_status": item.support_status,
                "evidence_ids": list(item.evidence_ids),
                "note": item.note,
            }
            for item in result.claim_supports
        ],
        "route_category": result.route_category.value
        if result.route_category is not None
        else None,
        "capability_id": result.capability_id,
        "operation": result.operation,
        "selection_reason_code": result.selection_reason_code,
        "routing_contract_version": result.routing_contract_version,
        "candidate_count": result.candidate_count,
        "rejected_candidate_reason_codes": list(result.rejected_candidate_reason_codes),
        "clarification_required": result.clarification_required,
        "freshness_affected_selection": result.freshness_affected_selection,
    }


def _task_result_from_payload(payload: object) -> TaskResult:
    if not isinstance(payload, dict):
        raise ValueError("step result payload must be an object")
    provenance = tuple(
        ProvenanceReference(
            kind=item["kind"],
            reference_id=item["reference_id"],
            recorded_at=_parse(item["recorded_at"]) if item.get("recorded_at") else None,
        )
        for item in payload.get("provenance", [])
    )
    claim_supports = tuple(
        ClaimSupport(
            claim_id=item["claim_id"],
            text=item["text"],
            support_status=item["support_status"],
            evidence_ids=tuple(item.get("evidence_ids", [])),
            note=item.get("note", ""),
        )
        for item in payload.get("claim_supports", [])
    )
    return TaskResult(
        task_id=payload["task_id"],
        task_status=TaskStatus(payload["task_status"]),
        outcome_code=OutcomeCode(payload["outcome_code"]),
        epistemic_status=EpistemicStatus(payload["epistemic_status"]),
        validation_status=ValidationStatus(payload["validation_status"]),
        answer=payload.get("answer", ""),
        answer_retained=bool(payload.get("answer_retained", True)),
        route_summary=Route(payload["route_summary"]),
        claims=tuple(payload.get("claims", [])),
        citations=tuple(payload.get("citations", [])),
        partial_work=tuple(payload.get("partial_work", [])),
        failures=tuple(payload.get("failures", [])),
        next_actions=tuple(payload.get("next_actions", [])),
        provenance=provenance,
        claim_supports=claim_supports,
        route_category=(
            Route(payload["route_category"]) if payload.get("route_category") else None
        ),
        capability_id=payload.get("capability_id"),
        operation=payload.get("operation", ""),
        selection_reason_code=payload.get("selection_reason_code", ""),
        routing_contract_version=payload.get("routing_contract_version", ""),
        candidate_count=int(payload.get("candidate_count", 0)),
        rejected_candidate_reason_codes=tuple(payload.get("rejected_candidate_reason_codes", [])),
        clarification_required=bool(payload.get("clarification_required", False)),
        freshness_affected_selection=bool(payload.get("freshness_affected_selection", False)),
    )


