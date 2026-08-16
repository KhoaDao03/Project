"""Provider-neutral, versioned results for validated execution-plan steps.

The capability registry intentionally remains a small optional extension point.
This module is the application-owned boundary on the other side of that
registry: provider DTOs and provider exceptions are converted into a bounded
``StepResultEnvelope`` before a result can be persisted or passed to another
step.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import TypeAlias

from ..domain.enums import (
    EpistemicStatus,
    OutcomeCode,
    Route,
    TaskStatus,
    ValidationStatus,
)
from ..domain.errors import MalformedResultError
from ..domain.models import ClaimSupport, ProvenanceReference, TaskResult

RESULT_SCHEMA_VERSION = "elly.step-result.v1"
SUPPORTED_RESULT_SCHEMA_VERSIONS = frozenset({RESULT_SCHEMA_VERSION})
MAX_RESULT_TEXT = 32_000
MAX_RESULT_ITEMS = 64
MAX_STRUCTURED_OUTPUT_BYTES = 16_384
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SAFE_STATUS = frozenset(
    {"supported", "direct", "indirect", "unverified", "absent", "contradicted"}
)
_JSON_SCALAR: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = _JSON_SCALAR | list["JSONValue"] | dict[str, "JSONValue"]
_ENVELOPE_KEYS = frozenset(
    {
        "schema_version",
        "plan_id",
        "task_id",
        "step_id",
        "capability_id",
        "operation_id",
        "status",
        "summary",
        "answer",
        "findings",
        "claims",
        "claim_supports",
        "citations",
        "assumptions",
        "uncertainties",
        "warnings",
        "structured_output",
        "recommended_presentation_structure",
        "provenance",
        "usage",
        "failures",
        "epistemic_status",
        "validation_status",
        "outcome_code",
        "answer_retained",
        "action_receipt",
    }
)


class EvidenceStatus(str, Enum):
    """Explicit claim/evidence relationship, including two negative states."""

    SUPPORTED = "supported"
    DIRECT = "direct"
    INDIRECT = "indirect"
    UNVERIFIED = "unverified"
    ABSENT = "absent"
    CONTRADICTED = "contradicted"


def _text(
    value: object,
    name: str,
    *,
    maximum: int = MAX_RESULT_TEXT,
    allow_empty: bool = False,
    single_line: bool = False,
) -> str:
    if not isinstance(value, str):
        raise MalformedResultError(f"result {name} must be text")
    if len(value) > maximum or (single_line and ("\n" in value or "\r" in value)):
        raise MalformedResultError(f"result {name} exceeds its safe bound")
    normalized = value.strip()
    if not allow_empty and not normalized:
        raise MalformedResultError(f"result {name} must be non-empty")
    return normalized


def _items(values: object, name: str, *, maximum: int = MAX_RESULT_ITEMS) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise MalformedResultError(f"result {name} must be an immutable tuple")
    if len(values) > maximum:
        raise MalformedResultError(f"result {name} exceeds its item limit")
    normalized = tuple(
        _text(
            value,
            f"{name} item",
            maximum=MAX_RESULT_TEXT,
            single_line=name == "failures",
        )
        for value in values
    )
    if len(set(normalized)) != len(normalized):
        raise MalformedResultError(f"result {name} must not contain duplicates")
    return normalized


def _identifier(value: object, name: str) -> str:
    normalized = _text(value, name, maximum=128, single_line=True)
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{0,127}", normalized) is None:
        raise MalformedResultError(f"result {name} has an invalid format")
    return normalized


def _utc(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise MalformedResultError(f"result {name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _validate_json(value: object, *, depth: int = 0) -> JSONValue:
    if depth > 8:
        raise MalformedResultError("result structured_output is too deeply nested")
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            raise MalformedResultError("result structured_output contains a non-finite number")
        return value
    if isinstance(value, list):
        if len(value) > MAX_RESULT_ITEMS:
            raise MalformedResultError("result structured_output list is too large")
        return [_validate_json(item, depth=depth + 1) for item in value]
    if isinstance(value, Mapping):
        if len(value) > MAX_RESULT_ITEMS:
            raise MalformedResultError("result structured_output object is too large")
        normalized: dict[str, JSONValue] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip() or len(key) > 128:
                raise MalformedResultError("result structured_output keys are invalid")
            normalized[key] = _validate_json(item, depth=depth + 1)
        return normalized
    raise MalformedResultError("result structured_output contains a non-JSON value")


@dataclass(frozen=True, slots=True)
class StepClaim:
    """Canonical claim with an explicit evidence relationship."""

    claim_id: str
    text: str
    evidence_ids: tuple[str, ...] = ()
    support_status: str = EvidenceStatus.UNVERIFIED.value

    def __post_init__(self) -> None:
        object.__setattr__(self, "claim_id", _identifier(self.claim_id, "claim_id"))
        object.__setattr__(self, "text", _text(self.text, "claim text"))
        object.__setattr__(self, "evidence_ids", _items(self.evidence_ids, "claim evidence_ids"))
        if self.support_status not in _SAFE_STATUS:
            raise MalformedResultError("claim support_status is invalid")


@dataclass(frozen=True, slots=True)
class StepUsage:
    """Provider-neutral timing and usage information permitted for audit."""

    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    provider_calls: int = 1
    cost_usd: float = 0.0

    def __post_init__(self) -> None:
        for value, name, maximum in (
            (self.input_tokens, "input_tokens", 10_000_000),
            (self.output_tokens, "output_tokens", 10_000_000),
            (self.latency_ms, "latency_ms", 86_400_000),
            (self.provider_calls, "provider_calls", 1000),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
                raise MalformedResultError(f"result usage {name} is invalid")
        if isinstance(self.cost_usd, bool) or not isinstance(self.cost_usd, (int, float)):
            raise MalformedResultError("result usage cost_usd is invalid")
        if self.cost_usd < 0 or self.cost_usd > 1_000_000:
            raise MalformedResultError("result usage cost_usd is out of range")


@dataclass(frozen=True, slots=True)
class ActionExecutionReceipt:
    """Application-verifiable receipt for a consequential action."""

    receipt_id: str
    action_digest: str
    capability_id: str
    operation_id: str
    completed_at: datetime
    status: str = "succeeded"
    provider_reference: str = ""

    def __post_init__(self) -> None:
        for value, name in (
            (self.receipt_id, "receipt_id"),
            (self.capability_id, "capability_id"),
            (self.operation_id, "operation_id"),
        ):
            object.__setattr__(self, name, _identifier(value, name))
        if not isinstance(self.action_digest, str) or _DIGEST.fullmatch(self.action_digest) is None:
            raise MalformedResultError("action receipt digest is invalid")
        object.__setattr__(
            self, "completed_at", _utc(self.completed_at, "action receipt completed_at")
        )
        if self.status != "succeeded":
            raise MalformedResultError("action receipt status is not successful")
        object.__setattr__(
            self,
            "provider_reference",
            _text(
                self.provider_reference,
                "action receipt provider_reference",
                maximum=256,
                allow_empty=True,
                single_line=True,
            ),
        )

    def verify(
        self,
        *,
        action_digest: str,
        capability_id: str,
        operation_id: str,
    ) -> bool:
        return (
            self.status == "succeeded"
            and self.action_digest == action_digest
            and self.capability_id == capability_id
            and self.operation_id == operation_id
        )


# Short compatibility name for adapters that call the object an ``ActionReceipt``.
ActionReceipt = ActionExecutionReceipt


@dataclass(frozen=True, slots=True)
class StepResultEnvelope:
    """The only result shape eligible for downstream plan execution."""

    schema_version: str
    plan_id: str
    task_id: str
    step_id: str
    capability_id: str
    operation_id: str
    status: TaskStatus
    summary: str
    answer: str = ""
    findings: tuple[str, ...] = ()
    claims: tuple[StepClaim, ...] = ()
    claim_supports: tuple[ClaimSupport, ...] = ()
    citations: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    structured_output: Mapping[str, JSONValue] = field(default_factory=dict)
    recommended_presentation_structure: tuple[str, ...] = ()
    provenance: tuple[ProvenanceReference, ...] = ()
    usage: StepUsage | None = None
    failures: tuple[str, ...] = ()
    epistemic_status: EpistemicStatus = EpistemicStatus.UNKNOWN
    validation_status: ValidationStatus = ValidationStatus.QUALIFIED
    outcome_code: OutcomeCode = OutcomeCode.SUCCESS
    answer_retained: bool = True
    action_receipt: ActionExecutionReceipt | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.schema_version, str)
            or self.schema_version not in SUPPORTED_RESULT_SCHEMA_VERSIONS
        ):
            raise MalformedResultError(f"unsupported step result schema: {self.schema_version}")
        for value, name in (
            (self.plan_id, "plan_id"),
            (self.task_id, "task_id"),
            (self.step_id, "step_id"),
            (self.capability_id, "capability_id"),
            (self.operation_id, "operation_id"),
        ):
            object.__setattr__(self, name, _identifier(value, name))
        if not isinstance(self.status, TaskStatus):
            raise MalformedResultError("result status must be a TaskStatus")
        object.__setattr__(self, "summary", _text(self.summary, "summary", allow_empty=True))
        object.__setattr__(self, "answer", _text(self.answer, "answer", allow_empty=True))
        for item_values, item_name in (
            (self.findings, "findings"),
            (self.citations, "citations"),
            (self.assumptions, "assumptions"),
            (self.uncertainties, "uncertainties"),
            (self.warnings, "warnings"),
            (self.recommended_presentation_structure, "recommended_presentation_structure"),
            (self.failures, "failures"),
        ):
            object.__setattr__(self, item_name, _items(item_values, item_name))
        if any(not isinstance(item, StepClaim) for item in self.claims):
            raise MalformedResultError("result claims must contain StepClaim values")
        if len(self.claims) > MAX_RESULT_ITEMS:
            raise MalformedResultError("result claims exceed their item limit")
        if any(not isinstance(item, ClaimSupport) for item in self.claim_supports):
            raise MalformedResultError("result claim_supports contain an invalid value")
        if len(self.claim_supports) > MAX_RESULT_ITEMS:
            raise MalformedResultError("result claim_supports exceed their item limit")
        claim_ids = {claim.claim_id for claim in self.claims}
        if any(item.claim_id not in claim_ids for item in self.claim_supports):
            raise MalformedResultError("result support references an unknown claim")
        supports_by_claim: dict[str, set[str]] = {}
        for item in self.claim_supports:
            supports_by_claim.setdefault(item.claim_id, set()).update(item.evidence_ids)
        for claim in self.claims:
            evidence_ids = set(claim.evidence_ids) | supports_by_claim.get(claim.claim_id, set())
            if claim.support_status == EvidenceStatus.ABSENT.value and evidence_ids:
                raise MalformedResultError("absent evidence claim cannot cite evidence")
            if (
                claim.support_status
                in {
                    EvidenceStatus.SUPPORTED.value,
                    EvidenceStatus.DIRECT.value,
                    EvidenceStatus.INDIRECT.value,
                    EvidenceStatus.CONTRADICTED.value,
                }
                and not evidence_ids
            ):
                raise MalformedResultError(
                    "supported or contradicted claim must reference evidence"
                )
        if any(not isinstance(item, ProvenanceReference) for item in self.provenance):
            raise MalformedResultError("result provenance contains an invalid value")
        if len(self.provenance) > MAX_RESULT_ITEMS:
            raise MalformedResultError("result provenance exceeds its item limit")
        if self.usage is not None and not isinstance(self.usage, StepUsage):
            raise MalformedResultError("result usage has an invalid type")
        if not isinstance(self.epistemic_status, EpistemicStatus):
            raise MalformedResultError("result epistemic_status is invalid")
        if not isinstance(self.validation_status, ValidationStatus):
            raise MalformedResultError("result validation_status is invalid")
        if not isinstance(self.outcome_code, OutcomeCode):
            raise MalformedResultError("result outcome_code is invalid")
        if not isinstance(self.answer_retained, bool):
            raise MalformedResultError("result answer_retained is invalid")
        if self.action_receipt is not None and not isinstance(
            self.action_receipt, ActionExecutionReceipt
        ):
            raise MalformedResultError("result action_receipt has an invalid type")
        if (
            self.status is TaskStatus.COMPLETED
            and self.answer_retained
            and not self.summary
            and not self.structured_output
        ):
            raise MalformedResultError(
                "completed result must contain a summary or structured output"
            )
        if (
            self.status is TaskStatus.COMPLETED
            and not self.answer
            and not self.structured_output
            and self.answer_retained
        ):
            raise MalformedResultError("completed result must contain an answer")
        normalized_output = _validate_json(self.structured_output)
        if not isinstance(normalized_output, dict):
            raise MalformedResultError("result structured_output must be an object")
        encoded_size = len(json.dumps(normalized_output, ensure_ascii=False, separators=(",", ":")))
        if encoded_size > MAX_STRUCTURED_OUTPUT_BYTES:
            raise MalformedResultError("result structured_output exceeds its byte limit")
        object.__setattr__(self, "structured_output", MappingProxyType(normalized_output))

    @property
    def task_status(self) -> TaskStatus:
        """Compatibility alias matching ``TaskResult``."""

        return self.status

    @property
    def canonical_findings(self) -> tuple[str, ...]:
        return self.findings

    def to_task_result(self) -> TaskResult:
        """Project the typed envelope into the legacy presentation contract."""

        claims = tuple(claim.text for claim in self.claims)
        answer = self.answer or self.summary
        return TaskResult(
            task_id=self.task_id,
            task_status=self.status,
            epistemic_status=self.epistemic_status,
            validation_status=self.validation_status,
            answer=answer,
            route_summary=Route.REGISTERED_CAPABILITY,
            claims=claims,
            citations=self.citations,
            partial_work=self.assumptions,
            failures=self.failures or self.warnings,
            next_actions=self.uncertainties,
            outcome_code=self.outcome_code,
            provenance=self.provenance,
            claim_supports=self.claim_supports,
            answer_retained=self.answer_retained,
            capability_id=self.capability_id,
            operation=self.operation_id,
        )

    def to_dict(self) -> dict[str, object]:
        """Serialize only provider-neutral, JSON-safe fields."""

        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "task_id": self.task_id,
            "step_id": self.step_id,
            "capability_id": self.capability_id,
            "operation_id": self.operation_id,
            "status": self.status.value,
            "summary": self.summary,
            "answer": self.answer,
            "findings": list(self.findings),
            "claims": [
                {
                    "claim_id": claim.claim_id,
                    "text": claim.text,
                    "evidence_ids": list(claim.evidence_ids),
                    "support_status": claim.support_status,
                }
                for claim in self.claims
            ],
            "claim_supports": [
                {
                    "claim_id": item.claim_id,
                    "text": item.text,
                    "support_status": item.support_status,
                    "evidence_ids": list(item.evidence_ids),
                    "note": item.note,
                }
                for item in self.claim_supports
            ],
            "citations": list(self.citations),
            "assumptions": list(self.assumptions),
            "uncertainties": list(self.uncertainties),
            "warnings": list(self.warnings),
            "structured_output": dict(self.structured_output),
            "recommended_presentation_structure": list(self.recommended_presentation_structure),
            "provenance": [
                {
                    "kind": item.kind,
                    "reference_id": item.reference_id,
                    "recorded_at": item.recorded_at.isoformat() if item.recorded_at else None,
                }
                for item in self.provenance
            ],
            "usage": (
                {
                    "input_tokens": self.usage.input_tokens,
                    "output_tokens": self.usage.output_tokens,
                    "latency_ms": self.usage.latency_ms,
                    "provider_calls": self.usage.provider_calls,
                    "cost_usd": self.usage.cost_usd,
                }
                if self.usage is not None
                else None
            ),
            "failures": list(self.failures),
            "epistemic_status": self.epistemic_status.value,
            "validation_status": self.validation_status.value,
            "outcome_code": self.outcome_code.value,
            "answer_retained": self.answer_retained,
            "action_receipt": (
                {
                    "receipt_id": self.action_receipt.receipt_id,
                    "action_digest": self.action_receipt.action_digest,
                    "capability_id": self.action_receipt.capability_id,
                    "operation_id": self.action_receipt.operation_id,
                    "completed_at": self.action_receipt.completed_at.isoformat(),
                    "status": self.action_receipt.status,
                    "provider_reference": self.action_receipt.provider_reference,
                }
                if self.action_receipt is not None
                else None
            ),
        }

    @classmethod
    def from_dict(cls, payload: object) -> "StepResultEnvelope":
        if not isinstance(payload, dict):
            raise MalformedResultError("step result payload must be an object")
        unknown = set(payload) - _ENVELOPE_KEYS
        if any(not isinstance(key, str) for key in payload) or unknown:
            raise MalformedResultError("step result payload contains unsupported fields")
        schema_version = payload.get("schema_version")
        if (
            not isinstance(schema_version, str)
            or schema_version not in SUPPORTED_RESULT_SCHEMA_VERSIONS
        ):
            raise MalformedResultError(
                f"unsupported step result schema: {payload.get('schema_version', '<missing>')}"
            )
        try:
            claims = tuple(
                StepClaim(
                    claim_id=item["claim_id"],
                    text=item["text"],
                    evidence_ids=tuple(item.get("evidence_ids", ())),
                    support_status=item.get("support_status", EvidenceStatus.UNVERIFIED.value),
                )
                for item in payload.get("claims", ())
            )
            supports = tuple(
                ClaimSupport(
                    claim_id=item["claim_id"],
                    text=item["text"],
                    support_status=item["support_status"],
                    evidence_ids=tuple(item.get("evidence_ids", ())),
                    note=item.get("note", ""),
                )
                for item in payload.get("claim_supports", ())
            )
            provenance = tuple(
                ProvenanceReference(
                    kind=item["kind"],
                    reference_id=item["reference_id"],
                    recorded_at=(
                        datetime.fromisoformat(item["recorded_at"])
                        if item.get("recorded_at")
                        else None
                    ),
                )
                for item in payload.get("provenance", ())
            )
            usage_payload = payload.get("usage")
            usage = StepUsage(**usage_payload) if usage_payload is not None else None
            receipt_payload = payload.get("action_receipt")
            receipt = (
                ActionExecutionReceipt(
                    receipt_id=receipt_payload["receipt_id"],
                    action_digest=receipt_payload["action_digest"],
                    capability_id=receipt_payload["capability_id"],
                    operation_id=receipt_payload["operation_id"],
                    completed_at=datetime.fromisoformat(receipt_payload["completed_at"]),
                    status=receipt_payload.get("status", "succeeded"),
                    provider_reference=receipt_payload.get("provider_reference", ""),
                )
                if receipt_payload is not None
                else None
            )
            return cls(
                schema_version=payload["schema_version"],
                plan_id=payload["plan_id"],
                task_id=payload["task_id"],
                step_id=payload["step_id"],
                capability_id=payload["capability_id"],
                operation_id=payload["operation_id"],
                status=TaskStatus(payload["status"]),
                summary=payload.get("summary", ""),
                answer=payload.get("answer", ""),
                findings=tuple(payload.get("findings", ())),
                claims=claims,
                claim_supports=supports,
                citations=tuple(payload.get("citations", ())),
                assumptions=tuple(payload.get("assumptions", ())),
                uncertainties=tuple(payload.get("uncertainties", ())),
                warnings=tuple(payload.get("warnings", ())),
                structured_output=payload.get("structured_output", {}),
                recommended_presentation_structure=tuple(
                    payload.get("recommended_presentation_structure", ())
                ),
                provenance=provenance,
                usage=usage,
                failures=tuple(payload.get("failures", ())),
                epistemic_status=EpistemicStatus(
                    payload.get("epistemic_status", EpistemicStatus.UNKNOWN.value)
                ),
                validation_status=ValidationStatus(
                    payload.get("validation_status", ValidationStatus.QUALIFIED.value)
                ),
                outcome_code=OutcomeCode(payload.get("outcome_code", OutcomeCode.SUCCESS.value)),
                answer_retained=bool(payload.get("answer_retained", True)),
                action_receipt=receipt,
            )
        except MalformedResultError:
            raise
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise MalformedResultError("step result payload is malformed") from exc


def normalize_step_result(
    result: StepResultEnvelope | TaskResult,
    *,
    plan_id: str,
    task_id: str,
    step_id: str,
    capability_id: str,
    operation_id: str,
    supported_schema_versions: frozenset[str] = SUPPORTED_RESULT_SCHEMA_VERSIONS,
    expected_action_digest: str | None = None,
    require_action_receipt: bool = False,
) -> StepResultEnvelope:
    """Normalize a legacy or typed result and enforce the step identity fence."""

    if isinstance(result, TaskResult):
        claims = tuple(
            StepClaim(
                claim_id=f"claim-{index}",
                text=text,
                support_status=EvidenceStatus.UNVERIFIED.value,
            )
            for index, text in enumerate(result.claims, start=1)
        )
        envelope = StepResultEnvelope(
            schema_version=RESULT_SCHEMA_VERSION,
            plan_id=plan_id,
            task_id=result.task_id,
            step_id=step_id,
            capability_id=capability_id,
            operation_id=operation_id,
            status=result.task_status,
            summary=result.answer
            or (result.failures[0] if result.failures else result.task_status.value),
            answer=result.answer,
            findings=result.claims,
            claims=claims,
            claim_supports=result.claim_supports,
            citations=result.citations,
            assumptions=result.partial_work,
            uncertainties=result.next_actions,
            warnings=(),
            provenance=result.provenance,
            failures=result.failures,
            epistemic_status=result.epistemic_status,
            validation_status=result.validation_status,
            outcome_code=result.outcome_code,
            answer_retained=result.answer_retained,
        )
    elif isinstance(result, StepResultEnvelope):
        envelope = result
    else:
        raise MalformedResultError("capability returned an invalid result type")

    if envelope.schema_version not in supported_schema_versions:
        raise MalformedResultError(
            f"unsupported result schema for capability: {envelope.schema_version}"
        )

    expected = {
        "plan_id": plan_id,
        "task_id": task_id,
        "step_id": step_id,
        "capability_id": capability_id,
        "operation_id": operation_id,
    }
    if any(getattr(envelope, name) != value for name, value in expected.items()):
        raise MalformedResultError("capability result identity does not match its step")
    if (
        require_action_receipt
        and expected_action_digest is not None
        and envelope.status is TaskStatus.COMPLETED
    ):
        receipt = envelope.action_receipt
        if receipt is None or not receipt.verify(
            action_digest=expected_action_digest,
            capability_id=capability_id,
            operation_id=operation_id,
        ):
            raise MalformedResultError("completed action has no verified execution receipt")
    return envelope


def failed_step_result(
    *,
    plan_id: str,
    task_id: str,
    step_id: str,
    capability_id: str,
    operation_id: str,
    reason: str,
) -> StepResultEnvelope:
    """Create a safe failure envelope without exposing provider exception text."""

    safe_reason = _text(reason, "failure", maximum=240)
    return StepResultEnvelope(
        schema_version=RESULT_SCHEMA_VERSION,
        plan_id=plan_id,
        task_id=task_id,
        step_id=step_id,
        capability_id=capability_id,
        operation_id=operation_id,
        status=TaskStatus.FAILED,
        summary=safe_reason,
        failures=(safe_reason,),
        epistemic_status=EpistemicStatus.UNKNOWN,
        validation_status=ValidationStatus.REJECTED,
        outcome_code=OutcomeCode.FAILED,
    )


__all__ = [
    "ActionExecutionReceipt",
    "ActionReceipt",
    "EvidenceStatus",
    "JSONValue",
    "RESULT_SCHEMA_VERSION",
    "SUPPORTED_RESULT_SCHEMA_VERSIONS",
    "StepClaim",
    "StepResultEnvelope",
    "StepUsage",
    "failed_step_result",
    "normalize_step_result",
]
