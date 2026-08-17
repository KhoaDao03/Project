"""Typed boundary for Elly V3.5's local response composer.

The composer is a presentation-only local model.  Its input is assembled by
application code after result validation and contains bounded references to
canonical records.  Its output is an outline plus explicitly bounded framing;
the application remains the source of truth for facts, status, citations,
warnings, disagreements, authorization, and exact records.

Persisted V3 synthesis plans are decoded by the execution layer as deterministic
migration shims. This module is the sole runtime model-composition port and
intentionally has no provider or capability dependencies.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from ..domain.enums import PresentationMode, TaskStatus
from ..domain.errors import InputInvalidError, MalformedResultError
from ..domain.models import HealthReport

RESPONSE_COMPOSITION_INPUT_SCHEMA_VERSION = "elly.response-composition-input.v1"
RESPONSE_COMPOSITION_DRAFT_SCHEMA_VERSION = "elly.response-composition-draft.v1"
RESPONSE_COMPOSITION_SCHEMA_VERSION = RESPONSE_COMPOSITION_DRAFT_SCHEMA_VERSION
MAX_RESPONSE_COMPOSITION_BYTES = 32_768
MAX_RESPONSE_COMPOSITION_TEXT = 20_000
MAX_RESPONSE_COMPOSITION_ITEMS = 64
MAX_RESPONSE_COMPOSITION_SECTIONS = 16

_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")


def _text(
    value: object,
    name: str,
    *,
    maximum: int = MAX_RESPONSE_COMPOSITION_TEXT,
    allow_empty: bool = False,
    single_line: bool = False,
    error: type[Exception] = InputInvalidError,
) -> str:
    if not isinstance(value, str):
        raise error(f"response composition {name} must be text")
    if len(value) > maximum or (single_line and ("\n" in value or "\r" in value)):
        raise error(f"response composition {name} exceeds its safe bound")
    normalized = value.strip()
    if not allow_empty and not normalized:
        raise error(f"response composition {name} must be non-empty")
    return normalized


def _identifier(value: object, name: str, *, error: type[Exception] = InputInvalidError) -> str:
    normalized = _text(value, name, maximum=128, single_line=True, error=error)
    if _IDENTIFIER.fullmatch(normalized) is None:
        raise error(f"response composition {name} has an invalid format")
    return normalized


def _refs(
    value: object,
    name: str,
    *,
    maximum: int = MAX_RESPONSE_COMPOSITION_ITEMS,
    error: type[Exception] = InputInvalidError,
) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise error(f"response composition {name} must be an immutable tuple")
    if len(value) > maximum:
        raise error(f"response composition {name} exceeds its item limit")
    normalized = tuple(_identifier(item, f"{name} item", error=error) for item in value)
    if len(set(normalized)) != len(normalized):
        raise error(f"response composition {name} must not contain duplicates")
    return normalized


def _text_refs(
    value: object,
    name: str,
    *,
    maximum: int = MAX_RESPONSE_COMPOSITION_ITEMS,
    error: type[Exception] = InputInvalidError,
) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise error(f"response composition {name} must be an immutable tuple")
    if len(value) > maximum:
        raise error(f"response composition {name} exceeds its item limit")
    normalized = tuple(
        _text(item, f"{name} item", maximum=256, single_line=True, error=error)
        for item in value
    )
    if len(set(normalized)) != len(normalized):
        raise error(f"response composition {name} must not contain duplicates")
    return normalized


def _enum(value: object, enum_type: type[Any], name: str) -> Any:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise InputInvalidError(f"response composition {name} is invalid") from exc


@dataclass(frozen=True, slots=True)
class PersonalityContextPlaceholder:
    """Inert V3.5 extension point; no personality data is loaded or stored."""

    context_id: str = ""

    def __post_init__(self) -> None:
        _text(self.context_id, "personality context_id", maximum=128, allow_empty=True)
        if self.context_id:
            raise InputInvalidError("personality context is inert in V3.5")


@dataclass(frozen=True, slots=True)
class MemoryContextPlaceholder:
    """Inert V3.5 extension point; no durable memory is retrieved or transmitted."""

    context_id: str = ""

    def __post_init__(self) -> None:
        _text(self.context_id, "memory context_id", maximum=128, allow_empty=True)
        if self.context_id:
            raise InputInvalidError("memory context is inert in V3.5")


@dataclass(frozen=True, slots=True)
class ResponseResultSummary:
    """Bounded application-owned summary for one canonical result reference."""

    result_ref: str
    task_id: str
    status: str
    summary: str = ""
    epistemic_status: str = "unknown"
    claim_refs: tuple[str, ...] = ()
    citation_refs: tuple[str, ...] = ()
    warning_refs: tuple[str, ...] = ()
    immutable_record_refs: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "result_ref", _identifier(self.result_ref, "result_ref"))
        object.__setattr__(self, "task_id", _identifier(self.task_id, "result task_id"))
        if isinstance(self.status, TaskStatus):
            object.__setattr__(self, "status", self.status.value)
        object.__setattr__(
            self, "status", _text(self.status, "result status", maximum=64, single_line=True)
        )
        object.__setattr__(
            self,
            "epistemic_status",
            _text(self.epistemic_status, "result epistemic_status", maximum=64, single_line=True),
        )
        object.__setattr__(
            self, "summary", _text(self.summary, "result summary", allow_empty=True)
        )
        for name in (
            "claim_refs",
            "citation_refs",
            "warning_refs",
            "immutable_record_refs",
        ):
            object.__setattr__(self, name, _refs(getattr(self, name), f"result {name}"))
        object.__setattr__(self, "limitations", _text_refs(self.limitations, "result limitations"))


@dataclass(frozen=True, slots=True)
class ResponseClaimSummary:
    """Canonical claim metadata available by reference to the composer."""

    claim_ref: str
    task_id: str
    result_ref: str
    text: str
    support_status: str = "unverified"
    evidence_refs: tuple[str, ...] = ()
    citation_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for attribute, value, label in (
            ("claim_ref", self.claim_ref, "claim_ref"),
            ("task_id", self.task_id, "claim task_id"),
            ("result_ref", self.result_ref, "claim result_ref"),
        ):
            object.__setattr__(self, attribute, _identifier(value, label))
        object.__setattr__(self, "text", _text(self.text, "claim text"))
        object.__setattr__(
            self,
            "support_status",
            _text(self.support_status, "claim support_status", maximum=64, single_line=True),
        )
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs, "claim evidence_refs"))
        object.__setattr__(self, "citation_refs", _refs(self.citation_refs, "claim citation_refs"))


@dataclass(frozen=True, slots=True)
class ResponseCitationSummary:
    """Canonical citation metadata available by reference to the composer."""

    citation_ref: str
    task_id: str
    result_ref: str
    text: str
    claim_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for attribute, value, label in (
            ("citation_ref", self.citation_ref, "citation_ref"),
            ("task_id", self.task_id, "citation task_id"),
            ("result_ref", self.result_ref, "citation result_ref"),
        ):
            object.__setattr__(self, attribute, _identifier(value, label))
        object.__setattr__(self, "text", _text(self.text, "citation text", maximum=2048))
        object.__setattr__(self, "claim_refs", _refs(self.claim_refs, "citation claim_refs"))


@dataclass(frozen=True, slots=True)
class ResponseWarningSummary:
    """Mandatory warning that cannot be dropped by a composer draft."""

    warning_ref: str
    task_id: str
    result_ref: str
    text: str

    def __post_init__(self) -> None:
        for attribute, value, label in (
            ("warning_ref", self.warning_ref, "warning_ref"),
            ("task_id", self.task_id, "warning task_id"),
            ("result_ref", self.result_ref, "warning result_ref"),
        ):
            object.__setattr__(self, attribute, _identifier(value, label))
        object.__setattr__(self, "text", _text(self.text, "warning text", maximum=2048))


@dataclass(frozen=True, slots=True)
class ResponseDisagreementSummary:
    """Canonical disagreement record; no consensus value is supplied."""

    disagreement_ref: str
    task_id: str
    result_refs: tuple[str, ...]
    statements: tuple[str, ...]
    claim_ref: str = ""
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "disagreement_ref", _identifier(self.disagreement_ref, "disagreement_ref")
        )
        object.__setattr__(self, "task_id", _identifier(self.task_id, "disagreement task_id"))
        object.__setattr__(self, "result_refs", _refs(self.result_refs, "disagreement result_refs"))
        object.__setattr__(
            self, "statements", _text_refs(self.statements, "disagreement statements")
        )
        if len(self.statements) < 2:
            raise InputInvalidError("disagreement must retain at least two statements")
        object.__setattr__(
            self,
            "claim_ref",
            _identifier(self.claim_ref, "disagreement claim_ref") if self.claim_ref else "",
        )
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs, "disagreement evidence_refs"))


@dataclass(frozen=True, slots=True)
class ResponseCompositionInput:
    """Immutable, bounded, reference-based input for the local composer."""

    schema_version: str
    task_id: str
    request_text: str
    presentation_mode: PresentationMode
    task_status: str
    result_refs: tuple[str, ...]
    claim_refs: tuple[str, ...] = ()
    citation_refs: tuple[str, ...] = ()
    warning_refs: tuple[str, ...] = ()
    disagreement_refs: tuple[str, ...] = ()
    immutable_record_refs: tuple[str, ...] = ()
    personality_context: PersonalityContextPlaceholder | None = None
    memory_context: MemoryContextPlaceholder | None = None
    request_id: str = ""
    approved_context: str = ""
    result_summaries: tuple[ResponseResultSummary, ...] = ()
    claim_summaries: tuple[ResponseClaimSummary, ...] = ()
    citation_summaries: tuple[ResponseCitationSummary, ...] = ()
    warning_summaries: tuple[ResponseWarningSummary, ...] = ()
    disagreement_summaries: tuple[ResponseDisagreementSummary, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != RESPONSE_COMPOSITION_INPUT_SCHEMA_VERSION:
            raise InputInvalidError("unsupported response composition input schema version")
        object.__setattr__(self, "task_id", _identifier(self.task_id, "task_id"))
        if self.request_id:
            object.__setattr__(self, "request_id", _identifier(self.request_id, "request_id"))
        object.__setattr__(self, "request_text", _text(self.request_text, "request_text"))
        object.__setattr__(
            self,
            "presentation_mode",
            _enum(self.presentation_mode, PresentationMode, "presentation_mode"),
        )
        if isinstance(self.task_status, TaskStatus):
            object.__setattr__(self, "task_status", self.task_status.value)
        object.__setattr__(
            self, "task_status", _text(self.task_status, "task_status", maximum=64, single_line=True)
        )
        for name in (
            "result_refs",
            "claim_refs",
            "citation_refs",
            "warning_refs",
            "disagreement_refs",
            "immutable_record_refs",
        ):
            object.__setattr__(self, name, _refs(getattr(self, name), name))
        object.__setattr__(
            self,
            "approved_context",
            _text(self.approved_context, "approved_context", allow_empty=True),
        )
        for name, item_type in (
            ("result_summaries", ResponseResultSummary),
            ("claim_summaries", ResponseClaimSummary),
            ("citation_summaries", ResponseCitationSummary),
            ("warning_summaries", ResponseWarningSummary),
            ("disagreement_summaries", ResponseDisagreementSummary),
        ):
            values = getattr(self, name)
            if not isinstance(values, tuple) or len(values) > MAX_RESPONSE_COMPOSITION_ITEMS:
                raise InputInvalidError(f"response composition {name} are invalid")
            if any(not isinstance(item, item_type) for item in values):
                raise InputInvalidError(f"response composition {name} contain an invalid item")
            ref_name = {
                "result_summaries": "result_ref",
                "claim_summaries": "claim_ref",
                "citation_summaries": "citation_ref",
                "warning_summaries": "warning_ref",
                "disagreement_summaries": "disagreement_ref",
            }[name]
            refs_name = {
                "result_summaries": "result_refs",
                "claim_summaries": "claim_refs",
                "citation_summaries": "citation_refs",
                "warning_summaries": "warning_refs",
                "disagreement_summaries": "disagreement_refs",
            }[name]
            refs = tuple(getattr(item, ref_name) for item in values)
            if len(set(refs)) != len(refs):
                raise InputInvalidError(f"response composition {name} contain duplicate references")
            if any(getattr(item, "task_id", self.task_id) != self.task_id for item in values):
                raise InputInvalidError(f"response composition {name} cross the task boundary")
            if not set(refs).issubset(set(getattr(self, refs_name))):
                raise InputInvalidError(f"response composition {name} contain an unknown reference")
        result_ref_set = set(self.result_refs)
        claim_ref_set = set(self.claim_refs)
        citation_ref_set = set(self.citation_refs)
        warning_ref_set = set(self.warning_refs)
        for result_summary in self.result_summaries:
            if not set(result_summary.claim_refs).issubset(claim_ref_set):
                raise InputInvalidError("response result summary contains an unknown claim")
            if not set(result_summary.citation_refs).issubset(citation_ref_set):
                raise InputInvalidError("response result summary contains an unknown citation")
            if not set(result_summary.warning_refs).issubset(warning_ref_set):
                raise InputInvalidError("response result summary contains an unknown warning")
            if not set(result_summary.immutable_record_refs).issubset(
                set(self.immutable_record_refs)
            ):
                raise InputInvalidError("response result summary contains an unknown record")
        for claim_summary in self.claim_summaries:
            if claim_summary.result_ref not in result_ref_set:
                raise InputInvalidError("response claim summary contains an unknown result")
            if not set(claim_summary.citation_refs).issubset(citation_ref_set):
                raise InputInvalidError("response claim summary contains an unknown citation")
        for citation_summary in self.citation_summaries:
            if citation_summary.result_ref not in result_ref_set or not set(
                citation_summary.claim_refs
            ).issubset(claim_ref_set):
                raise InputInvalidError("response citation summary contains an unknown reference")
        for warning_summary in self.warning_summaries:
            if warning_summary.result_ref not in result_ref_set:
                raise InputInvalidError("response warning summary contains an unknown result")
        for disagreement_summary in self.disagreement_summaries:
            if not set(disagreement_summary.result_refs).issubset(result_ref_set):
                raise InputInvalidError("response disagreement summary contains an unknown result")
            if disagreement_summary.claim_ref and disagreement_summary.claim_ref not in claim_ref_set:
                raise InputInvalidError("response disagreement summary contains an unknown claim")
        if self.personality_context is not None and not isinstance(
            self.personality_context, PersonalityContextPlaceholder
        ):
            raise InputInvalidError("personality_context is invalid")
        if self.memory_context is not None and not isinstance(
            self.memory_context, MemoryContextPlaceholder
        ):
            raise InputInvalidError("memory_context is invalid")
        # The only valid V3.5 placeholder is empty. Normalize it to absence so
        # explicitly supplying the placeholder cannot expand a model/provider
        # payload or create a persistence distinction.
        if isinstance(self.personality_context, PersonalityContextPlaceholder):
            object.__setattr__(self, "personality_context", None)
        if isinstance(self.memory_context, MemoryContextPlaceholder):
            object.__setattr__(self, "memory_context", None)
        try:
            encoded = json.dumps(
                self.to_dict(),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise InputInvalidError("response composition input is not serializable") from exc
        if len(encoded) > MAX_RESPONSE_COMPOSITION_BYTES:
            raise InputInvalidError("response composition input exceeds its size limit")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "request_id": self.request_id,
            "request_text": self.request_text,
            "presentation_mode": self.presentation_mode.value,
            "task_status": self.task_status,
            "result_refs": list(self.result_refs),
            "claim_refs": list(self.claim_refs),
            "citation_refs": list(self.citation_refs),
            "warning_refs": list(self.warning_refs),
            "disagreement_refs": list(self.disagreement_refs),
            "immutable_record_refs": list(self.immutable_record_refs),
            "approved_context": self.approved_context,
            "personality_context": (
                {"context_id": self.personality_context.context_id}
                if self.personality_context is not None
                else None
            ),
            "memory_context": (
                {"context_id": self.memory_context.context_id}
                if self.memory_context is not None
                else None
            ),
            "result_summaries": [
                {
                    "result_ref": item.result_ref,
                    "task_id": item.task_id,
                    "status": item.status,
                    "summary": item.summary,
                    "epistemic_status": item.epistemic_status,
                    "claim_refs": list(item.claim_refs),
                    "citation_refs": list(item.citation_refs),
                    "warning_refs": list(item.warning_refs),
                    "immutable_record_refs": list(item.immutable_record_refs),
                    "limitations": list(item.limitations),
                }
                for item in self.result_summaries
            ],
            "claim_summaries": [
                {
                    "claim_ref": item.claim_ref,
                    "task_id": item.task_id,
                    "result_ref": item.result_ref,
                    "text": item.text,
                    "support_status": item.support_status,
                    "evidence_refs": list(item.evidence_refs),
                    "citation_refs": list(item.citation_refs),
                }
                for item in self.claim_summaries
            ],
            "citation_summaries": [
                {
                    "citation_ref": item.citation_ref,
                    "task_id": item.task_id,
                    "result_ref": item.result_ref,
                    "text": item.text,
                    "claim_refs": list(item.claim_refs),
                }
                for item in self.citation_summaries
            ],
            "warning_summaries": [
                {
                    "warning_ref": item.warning_ref,
                    "task_id": item.task_id,
                    "result_ref": item.result_ref,
                    "text": item.text,
                }
                for item in self.warning_summaries
            ],
            "disagreement_summaries": [
                {
                    "disagreement_ref": item.disagreement_ref,
                    "task_id": item.task_id,
                    "result_refs": list(item.result_refs),
                    "statements": list(item.statements),
                    "claim_ref": item.claim_ref,
                    "evidence_refs": list(item.evidence_refs),
                }
                for item in self.disagreement_summaries
            ],
        }


@dataclass(frozen=True, slots=True)
class ResponseSection:
    """Model-selected outline plus bounded, non-authoritative framing."""

    section_id: str
    title: str = ""
    result_refs: tuple[str, ...] = ()
    claim_refs: tuple[str, ...] = ()
    citation_refs: tuple[str, ...] = ()
    immutable_record_refs: tuple[str, ...] = ()
    narrative: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "section_id", _identifier(self.section_id, "section_id"))
        object.__setattr__(
            self, "title", _text(self.title, "section title", maximum=160, allow_empty=True, single_line=True)
        )
        for name in ("result_refs", "claim_refs", "citation_refs", "immutable_record_refs"):
            object.__setattr__(self, name, _refs(getattr(self, name), f"section {name}"))
        object.__setattr__(
            self,
            "narrative",
            _text(self.narrative, "section narrative", maximum=1024, allow_empty=True),
        )
        if not any((self.result_refs, self.claim_refs, self.immutable_record_refs)):
            raise InputInvalidError("response section must reference approved material")

    # V3 synthesis-compatible read aliases.
    @property
    def result_ids(self) -> tuple[str, ...]:
        return self.result_refs

    @property
    def claim_ids(self) -> tuple[str, ...]:
        return self.claim_refs

    @property
    def citation_ids(self) -> tuple[str, ...]:
        return self.citation_refs

    def to_dict(self) -> dict[str, object]:
        return {
            "section_id": self.section_id,
            "title": self.title,
            "result_refs": list(self.result_refs),
            "claim_refs": list(self.claim_refs),
            "citation_refs": list(self.citation_refs),
            "immutable_record_refs": list(self.immutable_record_refs),
            "narrative": self.narrative,
        }


@dataclass(frozen=True, slots=True)
class ResponseCompositionDraft:
    """Strict composer output containing references and bounded framing only."""

    schema_version: str
    sections: tuple[ResponseSection, ...]
    referenced_result_ids: tuple[str, ...] = ()
    referenced_claim_ids: tuple[str, ...] = ()
    referenced_citation_ids: tuple[str, ...] = ()
    acknowledged_warning_ids: tuple[str, ...] = ()
    acknowledged_disagreement_ids: tuple[str, ...] = ()
    referenced_immutable_record_ids: tuple[str, ...] = ()
    task_status: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != RESPONSE_COMPOSITION_DRAFT_SCHEMA_VERSION:
            raise InputInvalidError("unsupported response composition draft schema version")
        if (
            not isinstance(self.sections, tuple)
            or not self.sections
            or len(self.sections) > MAX_RESPONSE_COMPOSITION_SECTIONS
        ):
            raise InputInvalidError("response composition draft sections are invalid")
        if any(not isinstance(item, ResponseSection) for item in self.sections):
            raise InputInvalidError("response composition draft contains an invalid section")
        if len({item.section_id for item in self.sections}) != len(self.sections):
            raise InputInvalidError("response composition section IDs must be unique")
        for name in (
            "referenced_result_ids",
            "referenced_claim_ids",
            "referenced_citation_ids",
            "acknowledged_warning_ids",
            "acknowledged_disagreement_ids",
            "referenced_immutable_record_ids",
        ):
            object.__setattr__(self, name, _refs(getattr(self, name), name))
        if self.task_status is not None:
            if isinstance(self.task_status, TaskStatus):
                object.__setattr__(self, "task_status", self.task_status.value)
            object.__setattr__(
                self,
                "task_status",
                _text(self.task_status, "draft task_status", maximum=64, single_line=True),
            )

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": self.schema_version,
            "sections": [item.to_dict() for item in self.sections],
            "referenced_result_ids": list(self.referenced_result_ids),
            "referenced_claim_ids": list(self.referenced_claim_ids),
            "referenced_citation_ids": list(self.referenced_citation_ids),
            "acknowledged_warning_ids": list(self.acknowledged_warning_ids),
            "acknowledged_disagreement_ids": list(self.acknowledged_disagreement_ids),
            "referenced_immutable_record_ids": list(self.referenced_immutable_record_ids),
        }
        if self.task_status is not None:
            value["task_status"] = self.task_status
        return value

    def to_json(self) -> str:
        encoded = json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        if len(encoded.encode("utf-8")) > MAX_RESPONSE_COMPOSITION_BYTES:
            raise InputInvalidError("response composition draft exceeds its size limit")
        return encoded

    @classmethod
    def from_dict(cls, payload: object) -> "ResponseCompositionDraft":
        if not isinstance(payload, (str, bytes, Mapping)):
            raise InputInvalidError("response composition draft payload is invalid")
        return decode_response_composition_draft(payload)


@dataclass(frozen=True, slots=True)
class ResponseCompositionRequest:
    """One bounded, exactly-once local composer invocation."""

    request_id: str
    composition_input: ResponseCompositionInput
    max_output_tokens: int
    timeout_seconds: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _identifier(self.request_id, "request_id"))
        if not isinstance(self.composition_input, ResponseCompositionInput):
            raise InputInvalidError("response composition request input is invalid")
        if self.composition_input.request_id and self.request_id != self.composition_input.request_id:
            raise InputInvalidError("response composition request identity does not match input")
        if (
            isinstance(self.max_output_tokens, bool)
            or not isinstance(self.max_output_tokens, int)
            or not 0 < self.max_output_tokens <= 100_000
        ):
            raise InputInvalidError("response composition max_output_tokens must be positive")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(float(self.timeout_seconds))
            or not 0 < self.timeout_seconds <= 3_600
        ):
            raise InputInvalidError("response composition timeout_seconds must be positive")


def _object(value: object, name: str, allowed: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MalformedResultError(f"response composition {name} must be an object")
    data = dict(value)
    if any(not isinstance(key, str) for key in data):
        raise MalformedResultError(f"response composition {name} contains a non-text field")
    unknown = set(data) - allowed
    if unknown:
        raise MalformedResultError(
            f"response composition {name} contains unsupported fields: " + ", ".join(sorted(unknown))
        )
    return data


def _array(value: object, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise MalformedResultError(f"response composition {name} must be an array")
    return value


def _string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise MalformedResultError(f"response composition {name} must be text")
    return value


def _section(value: object) -> ResponseSection:
    data = _object(
        value,
        "section",
        frozenset(
            {
                "section_id",
                "title",
                "result_refs",
                "claim_refs",
                "citation_refs",
                "immutable_record_refs",
                "narrative",
            }
        ),
    )
    required = frozenset(
        {"section_id", "title", "result_refs", "claim_refs", "citation_refs", "immutable_record_refs", "narrative"}
    )
    missing = required - set(data)
    if missing:
        raise MalformedResultError("response composition section is missing required fields")
    try:
        return ResponseSection(
            section_id=_string(data["section_id"], "section.section_id"),
            title=_string(data["title"], "section.title"),
            result_refs=tuple(_string(item, "section.result_ref") for item in _array(data["result_refs"], "section.result_refs")),
            claim_refs=tuple(_string(item, "section.claim_ref") for item in _array(data["claim_refs"], "section.claim_refs")),
            citation_refs=tuple(_string(item, "section.citation_ref") for item in _array(data["citation_refs"], "section.citation_refs")),
            immutable_record_refs=tuple(_string(item, "section.immutable_record_ref") for item in _array(data["immutable_record_refs"], "section.immutable_record_refs")),
            narrative=_string(data["narrative"], "section.narrative"),
        )
    except (InputInvalidError, TypeError, ValueError) as exc:
        raise MalformedResultError("response composition section is invalid") from exc


def decode_response_composition_draft(
    payload: str | bytes | Mapping[str, object],
) -> ResponseCompositionDraft:
    """Decode a closed, bounded JSON composer draft."""

    if isinstance(payload, bytes):
        if len(payload) > MAX_RESPONSE_COMPOSITION_BYTES:
            raise MalformedResultError("response composition draft exceeds its size limit")
        try:
            decoded: object = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MalformedResultError("response composition draft is not valid JSON") from exc
    elif isinstance(payload, str):
        if len(payload.encode("utf-8")) > MAX_RESPONSE_COMPOSITION_BYTES:
            raise MalformedResultError("response composition draft exceeds its size limit")
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise MalformedResultError("response composition draft is not valid JSON") from exc
    elif isinstance(payload, Mapping):
        decoded = dict(payload)
    else:
        raise MalformedResultError("response composition draft must be JSON text or an object")
    try:
        if len(json.dumps(decoded, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > MAX_RESPONSE_COMPOSITION_BYTES:
            raise MalformedResultError("response composition draft exceeds its size limit")
    except (TypeError, ValueError) as exc:
        raise MalformedResultError("response composition draft contains non-JSON values") from exc
    data = _object(
        decoded,
        "draft",
        frozenset(
            {
                "schema_version",
                "sections",
                "referenced_result_ids",
                "referenced_claim_ids",
                "referenced_citation_ids",
                "acknowledged_warning_ids",
                "acknowledged_disagreement_ids",
                "referenced_immutable_record_ids",
                "task_status",
            }
        ),
    )
    required = frozenset(
        {
            "schema_version",
            "sections",
            "referenced_result_ids",
            "referenced_claim_ids",
            "referenced_citation_ids",
            "acknowledged_warning_ids",
            "acknowledged_disagreement_ids",
            "referenced_immutable_record_ids",
        }
    )
    missing = required - set(data)
    if missing:
        raise MalformedResultError("response composition draft is missing required fields")
    try:
        return ResponseCompositionDraft(
            schema_version=_string(data["schema_version"], "draft.schema_version"),
            sections=tuple(_section(item) for item in _array(data["sections"], "draft.sections")),
            referenced_result_ids=tuple(_string(item, "draft.result_ref") for item in _array(data["referenced_result_ids"], "draft.referenced_result_ids")),
            referenced_claim_ids=tuple(_string(item, "draft.claim_ref") for item in _array(data["referenced_claim_ids"], "draft.referenced_claim_ids")),
            referenced_citation_ids=tuple(_string(item, "draft.citation_ref") for item in _array(data["referenced_citation_ids"], "draft.referenced_citation_ids")),
            acknowledged_warning_ids=tuple(_string(item, "draft.warning_ref") for item in _array(data["acknowledged_warning_ids"], "draft.acknowledged_warning_ids")),
            acknowledged_disagreement_ids=tuple(_string(item, "draft.disagreement_ref") for item in _array(data["acknowledged_disagreement_ids"], "draft.acknowledged_disagreement_ids")),
            referenced_immutable_record_ids=tuple(_string(item, "draft.immutable_record_ref") for item in _array(data["referenced_immutable_record_ids"], "draft.referenced_immutable_record_ids")),
            task_status=(
                _string(data["task_status"], "draft.task_status") if "task_status" in data else None
            ),
        )
    except (InputInvalidError, TypeError, ValueError, KeyError) as exc:
        raise MalformedResultError("response composition draft is invalid") from exc


def response_composer_json_schema(
    composition_input: ResponseCompositionInput | None = None,
) -> dict[str, object]:
    """Return a closed schema, optionally constraining refs to approved IDs."""

    def ref_array(values: tuple[str, ...] | None) -> dict[str, object]:
        items: dict[str, object] = {"type": "string"}
        if values is not None:
            items["enum"] = list(values)
        return {
            "type": "array",
            "items": items,
            "maxItems": len(values) if values is not None else MAX_RESPONSE_COMPOSITION_ITEMS,
        }

    result_refs = composition_input.result_refs if composition_input is not None else None
    claim_refs = composition_input.claim_refs if composition_input is not None else None
    citation_refs = composition_input.citation_refs if composition_input is not None else None
    warning_refs = composition_input.warning_refs if composition_input is not None else None
    disagreement_refs = composition_input.disagreement_refs if composition_input is not None else None
    record_refs = composition_input.immutable_record_refs if composition_input is not None else None
    task_status: dict[str, object] = (
        {"const": composition_input.task_status}
        if composition_input is not None
        else {"type": "string"}
    )
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "sections",
            "referenced_result_ids",
            "referenced_claim_ids",
            "referenced_citation_ids",
            "acknowledged_warning_ids",
            "acknowledged_disagreement_ids",
            "referenced_immutable_record_ids",
        ],
        "properties": {
            "schema_version": {"const": RESPONSE_COMPOSITION_DRAFT_SCHEMA_VERSION},
            "task_status": task_status,
            "sections": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_RESPONSE_COMPOSITION_SECTIONS,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "section_id",
                        "title",
                        "result_refs",
                        "claim_refs",
                        "citation_refs",
                        "immutable_record_refs",
                        "narrative",
                    ],
                    "properties": {
                        "section_id": {"type": "string", "pattern": r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$"},
                        "title": {"const": ""},
                        "result_refs": ref_array(result_refs),
                        "claim_refs": ref_array(claim_refs),
                        "citation_refs": ref_array(citation_refs),
                        "immutable_record_refs": ref_array(record_refs),
                        "narrative": {"const": ""},
                    },
                },
            },
            "referenced_result_ids": ref_array(result_refs),
            "referenced_claim_ids": ref_array(claim_refs),
            "referenced_citation_ids": ref_array(citation_refs),
            "acknowledged_warning_ids": ref_array(warning_refs),
            "acknowledged_disagreement_ids": ref_array(disagreement_refs),
            "referenced_immutable_record_ids": ref_array(record_refs),
        },
    }


@runtime_checkable
class LocalResponseComposerPort(Protocol):
    """Local-only, presentation-only response-composer boundary."""

    def compose(self, request: ResponseCompositionRequest) -> ResponseCompositionDraft:
        """Return a bounded reference-bound draft exactly once per request."""
        ...

    def health(self) -> HealthReport:
        """Report local response-composer readiness."""
        ...

    def cancel(self) -> None:
        """Request cancellation of active local generation."""
        ...


# Short aliases used by callers that omit the word "composition".
ResponseComposerRequest = ResponseCompositionRequest
ResponseComposerPort = LocalResponseComposerPort
decode_draft = decode_response_composition_draft
draft_json_schema = response_composer_json_schema


__all__ = [
    "LocalResponseComposerPort",
    "MAX_RESPONSE_COMPOSITION_BYTES",
    "MAX_RESPONSE_COMPOSITION_ITEMS",
    "MAX_RESPONSE_COMPOSITION_SECTIONS",
    "MAX_RESPONSE_COMPOSITION_TEXT",
    "MemoryContextPlaceholder",
    "PersonalityContextPlaceholder",
    "ResponseClaimSummary",
    "ResponseCitationSummary",
    "ResponseCompositionDraft",
    "ResponseCompositionInput",
    "ResponseCompositionRequest",
    "ResponseComposerPort",
    "ResponseComposerRequest",
    "ResponseDisagreementSummary",
    "ResponseResultSummary",
    "ResponseSection",
    "ResponseWarningSummary",
    "RESPONSE_COMPOSITION_DRAFT_SCHEMA_VERSION",
    "RESPONSE_COMPOSITION_INPUT_SCHEMA_VERSION",
    "RESPONSE_COMPOSITION_SCHEMA_VERSION",
    "decode_draft",
    "decode_response_composition_draft",
    "draft_json_schema",
    "response_composer_json_schema",
]
