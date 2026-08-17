"""Typed boundary for evidence-bounded local final synthesis.

The synthesis adapter receives only this module's provider-neutral input and
returns an outline made of references into that input.  It cannot create
claims, citations, receipts, or executable instructions.  The application
validates and renders the outline before it becomes a user-facing result.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from ..domain.errors import InputInvalidError, MalformedResultError
from ..domain.models import HealthReport
from ..planning.contracts import FinalizationStrategy, PlanStatus, StepState

SYNTHESIS_INPUT_SCHEMA_VERSION = "elly.synthesis-input.v1"
SYNTHESIS_DRAFT_SCHEMA_VERSION = "elly.synthesis-draft.v1"
SYNTHESIS_SCHEMA_VERSION = SYNTHESIS_DRAFT_SCHEMA_VERSION
MAX_SYNTHESIS_BYTES = 32_768
MAX_SYNTHESIS_DRAFT_BYTES = MAX_SYNTHESIS_BYTES
MAX_SYNTHESIS_TEXT = 20_000
MAX_SYNTHESIS_ITEMS = 64
MAX_SYNTHESIS_SECTIONS = 16

_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")


def _text(
    value: object,
    name: str,
    *,
    maximum: int = MAX_SYNTHESIS_TEXT,
    allow_empty: bool = False,
    single_line: bool = False,
    error: type[Exception] = InputInvalidError,
) -> str:
    if not isinstance(value, str):
        raise error(f"synthesis {name} must be text")
    if len(value) > maximum or (single_line and ("\n" in value or "\r" in value)):
        raise error(f"synthesis {name} exceeds its safe bound")
    normalized = value.strip()
    if not allow_empty and not normalized:
        raise error(f"synthesis {name} must be non-empty")
    return normalized


def _identifier(value: object, name: str, *, error: type[Exception] = InputInvalidError) -> str:
    normalized = _text(value, name, maximum=128, single_line=True, error=error)
    if _IDENTIFIER.fullmatch(normalized) is None:
        raise error(f"synthesis {name} has an invalid format")
    return normalized


def _tuple_text(
    value: object,
    name: str,
    *,
    maximum: int = MAX_SYNTHESIS_ITEMS,
    single_line: bool = False,
    error: type[Exception] = InputInvalidError,
) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise error(f"synthesis {name} must be an immutable tuple")
    if len(value) > maximum:
        raise error(f"synthesis {name} exceeds its item limit")
    normalized = tuple(
        _text(
            item,
            f"{name} item",
            maximum=MAX_SYNTHESIS_TEXT,
            single_line=single_line,
            error=error,
        )
        for item in value
    )
    if len(set(normalized)) != len(normalized):
        raise error(f"synthesis {name} must not contain duplicates")
    return normalized


def _enum(value: object, enum_type: type[Any], name: str, *, error: type[Exception]) -> Any:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise error(f"synthesis {name} is invalid") from exc


@dataclass(frozen=True, slots=True)
class SynthesisClaim:
    """Canonical claim available to the local presentation model."""

    claim_id: str
    text: str
    step_id: str
    evidence_ids: tuple[str, ...] = ()
    citation_ids: tuple[str, ...] = ()
    support_status: str = "unverified"

    def __post_init__(self) -> None:
        object.__setattr__(self, "claim_id", _identifier(self.claim_id, "claim_id"))
        object.__setattr__(self, "text", _text(self.text, "claim text"))
        object.__setattr__(self, "step_id", _identifier(self.step_id, "claim step_id"))
        object.__setattr__(
            self, "evidence_ids", _tuple_text(self.evidence_ids, "claim evidence_ids")
        )
        object.__setattr__(
            self, "citation_ids", _tuple_text(self.citation_ids, "claim citation_ids")
        )
        object.__setattr__(
            self,
            "support_status",
            _text(self.support_status, "claim support_status", maximum=32, single_line=True),
        )


@dataclass(frozen=True, slots=True)
class SynthesisCitation:
    """A citation record that can only be referenced by its stable ID."""

    citation_id: str
    text: str
    step_id: str
    claim_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "citation_id", _identifier(self.citation_id, "citation_id"))
        object.__setattr__(self, "text", _text(self.text, "citation text", maximum=2048))
        object.__setattr__(self, "step_id", _identifier(self.step_id, "citation step_id"))
        object.__setattr__(self, "claim_ids", _tuple_text(self.claim_ids, "citation claim_ids"))


@dataclass(frozen=True, slots=True)
class SynthesisWarning:
    """A mandatory warning selected from an approved specialist result."""

    warning_id: str
    text: str
    step_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "warning_id", _identifier(self.warning_id, "warning_id"))
        object.__setattr__(self, "text", _text(self.text, "warning text", maximum=2048))
        object.__setattr__(self, "step_id", _identifier(self.step_id, "warning step_id"))


@dataclass(frozen=True, slots=True)
class SynthesisDisagreement:
    """An explicit conflict; the model may organize it but never erase it."""

    disagreement_id: str
    claim_id: str
    step_ids: tuple[str, ...]
    statements: tuple[str, ...]
    evidence_ids: tuple[str, ...] = ()
    source_kind: str = "claim"
    reason_code: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "disagreement_id", _identifier(self.disagreement_id, "disagreement_id")
        )
        object.__setattr__(self, "claim_id", _identifier(self.claim_id, "disagreement claim_id"))
        object.__setattr__(self, "step_ids", _tuple_text(self.step_ids, "disagreement step_ids"))
        object.__setattr__(
            self, "statements", _tuple_text(self.statements, "disagreement statements")
        )
        object.__setattr__(
            self, "evidence_ids", _tuple_text(self.evidence_ids, "disagreement evidence_ids")
        )
        object.__setattr__(
            self,
            "source_kind",
            _text(self.source_kind, "disagreement source_kind", maximum=32, single_line=True),
        )
        object.__setattr__(
            self,
            "reason_code",
            _text(
                self.reason_code,
                "disagreement reason_code",
                maximum=128,
                single_line=True,
                allow_empty=True,
            ),
        )


@dataclass(frozen=True, slots=True)
class SynthesisStepSummary:
    """Presentation-safe summary of one plan step."""

    result_id: str
    step_id: str
    status: StepState
    summary: str = ""
    limitations: tuple[str, ...] = ()
    claim_ids: tuple[str, ...] = ()
    citation_ids: tuple[str, ...] = ()
    warning_ids: tuple[str, ...] = ()
    action_receipt: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "result_id", _identifier(self.result_id, "step summary result_id"))
        object.__setattr__(self, "step_id", _identifier(self.step_id, "step summary step_id"))
        object.__setattr__(
            self,
            "status",
            _enum(self.status, StepState, "step summary status", error=InputInvalidError),
        )
        object.__setattr__(
            self,
            "summary",
            _text(self.summary, "step summary", maximum=MAX_SYNTHESIS_TEXT, allow_empty=True),
        )
        object.__setattr__(
            self,
            "limitations",
            _tuple_text(self.limitations, "step summary limitations", maximum=MAX_SYNTHESIS_ITEMS),
        )
        object.__setattr__(self, "claim_ids", _tuple_text(self.claim_ids, "step summary claim_ids"))
        object.__setattr__(
            self, "citation_ids", _tuple_text(self.citation_ids, "step summary citation_ids")
        )
        object.__setattr__(
            self, "warning_ids", _tuple_text(self.warning_ids, "step summary warning_ids")
        )
        object.__setattr__(
            self,
            "action_receipt",
            _text(
                self.action_receipt, "step summary action_receipt", maximum=1024, allow_empty=True
            ),
        )


@dataclass(frozen=True, slots=True)
class SynthesisInput:
    """Bounded, approved data supplied to a synthesis adapter."""

    schema_version: str
    request_id: str
    task_id: str
    plan_id: str
    request_text: str
    approved_context: str
    plan_summary: str
    plan_status: PlanStatus
    finalization: FinalizationStrategy
    step_summaries: tuple[SynthesisStepSummary, ...]
    claims: tuple[SynthesisClaim, ...] = ()
    citations: tuple[SynthesisCitation, ...] = ()
    warnings: tuple[SynthesisWarning, ...] = ()
    disagreements: tuple[SynthesisDisagreement, ...] = ()
    uncertainties: tuple[str, ...] = ()
    presentation_instructions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != SYNTHESIS_INPUT_SCHEMA_VERSION:
            raise InputInvalidError("unsupported synthesis input schema version")
        for value, name in (
            (self.request_id, "request_id"),
            (self.task_id, "task_id"),
            (self.plan_id, "plan_id"),
        ):
            object.__setattr__(self, name, _identifier(value, name))
        for value, name, maximum in (
            (self.request_text, "request_text", MAX_SYNTHESIS_TEXT),
            (self.approved_context, "approved_context", MAX_SYNTHESIS_TEXT),
            (self.plan_summary, "plan_summary", 4096),
        ):
            object.__setattr__(self, name, _text(value, name, maximum=maximum))
        object.__setattr__(
            self,
            "plan_status",
            _enum(self.plan_status, PlanStatus, "plan_status", error=InputInvalidError),
        )
        object.__setattr__(
            self,
            "finalization",
            _enum(self.finalization, FinalizationStrategy, "finalization", error=InputInvalidError),
        )
        if not isinstance(self.step_summaries, tuple) or not self.step_summaries:
            raise InputInvalidError("synthesis step_summaries must be non-empty")
        if len(self.step_summaries) > MAX_SYNTHESIS_ITEMS or any(
            not isinstance(item, SynthesisStepSummary) for item in self.step_summaries
        ):
            raise InputInvalidError("synthesis step_summaries are invalid")
        if len({item.result_id for item in self.step_summaries}) != len(self.step_summaries):
            raise InputInvalidError("synthesis result IDs must be unique")
        for name, values, item_type in (
            ("claims", self.claims, SynthesisClaim),
            ("citations", self.citations, SynthesisCitation),
            ("warnings", self.warnings, SynthesisWarning),
            ("disagreements", self.disagreements, SynthesisDisagreement),
        ):
            if (
                not isinstance(values, tuple)
                or len(values) > MAX_SYNTHESIS_ITEMS
                or any(not isinstance(item, item_type) for item in values)
            ):
                raise InputInvalidError(f"synthesis {name} are invalid")
        if len({item.claim_id for item in self.claims}) != len(self.claims):
            raise InputInvalidError("synthesis claim IDs must be unique")
        if len({item.citation_id for item in self.citations}) != len(self.citations):
            raise InputInvalidError("synthesis citation IDs must be unique")
        if len({item.warning_id for item in self.warnings}) != len(self.warnings):
            raise InputInvalidError("synthesis warning IDs must be unique")
        if len({item.disagreement_id for item in self.disagreements}) != len(self.disagreements):
            raise InputInvalidError("synthesis disagreement IDs must be unique")
        object.__setattr__(self, "uncertainties", _tuple_text(self.uncertainties, "uncertainties"))
        object.__setattr__(
            self,
            "presentation_instructions",
            _tuple_text(self.presentation_instructions, "presentation_instructions", maximum=16),
        )

    @property
    def status(self) -> PlanStatus:
        """Short alias used by adapters and tests."""

        return self.plan_status

    @property
    def result_ids(self) -> tuple[str, ...]:
        return tuple(item.result_id for item in self.step_summaries)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "task_id": self.task_id,
            "plan_id": self.plan_id,
            "request_text": self.request_text,
            "approved_context": self.approved_context,
            "plan_summary": self.plan_summary,
            "plan_status": self.plan_status.value,
            "finalization": self.finalization.value,
            "step_summaries": [_step_summary_to_dict(item) for item in self.step_summaries],
            "claims": [_claim_to_dict(item) for item in self.claims],
            "citations": [_citation_to_dict(item) for item in self.citations],
            "warnings": [_warning_to_dict(item) for item in self.warnings],
            "disagreements": [_disagreement_to_dict(item) for item in self.disagreements],
            "uncertainties": list(self.uncertainties),
            "presentation_instructions": list(self.presentation_instructions),
        }


@dataclass(frozen=True, slots=True)
class SynthesisSection:
    """Model-selected order of approved result, claim, and citation records."""

    section_id: str
    title: str
    result_ids: tuple[str, ...] = ()
    claim_ids: tuple[str, ...] = ()
    citation_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "section_id", _identifier(self.section_id, "section_id"))
        object.__setattr__(
            self,
            "title",
            _text(self.title, "section title", maximum=160, allow_empty=True, single_line=True),
        )
        for name in ("result_ids", "claim_ids", "citation_ids"):
            object.__setattr__(self, name, _tuple_text(getattr(self, name), f"section {name}"))
        if not self.result_ids and not self.claim_ids:
            raise InputInvalidError("synthesis section must reference a result or claim")

    def to_dict(self) -> dict[str, object]:
        return {
            "section_id": self.section_id,
            "title": self.title,
            "result_ids": list(self.result_ids),
            "claim_ids": list(self.claim_ids),
            "citation_ids": list(self.citation_ids),
        }


@dataclass(frozen=True, slots=True)
class SynthesisDraft:
    """Strict model output containing references only, never new evidence."""

    schema_version: str
    status: PlanStatus
    sections: tuple[SynthesisSection, ...]
    included_warning_ids: tuple[str, ...]
    included_disagreement_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != SYNTHESIS_DRAFT_SCHEMA_VERSION:
            raise InputInvalidError("unsupported synthesis draft schema version")
        object.__setattr__(
            self, "status", _enum(self.status, PlanStatus, "draft status", error=InputInvalidError)
        )
        if (
            not isinstance(self.sections, tuple)
            or not self.sections
            or len(self.sections) > MAX_SYNTHESIS_SECTIONS
        ):
            raise InputInvalidError("synthesis draft sections are invalid")
        if any(not isinstance(item, SynthesisSection) for item in self.sections):
            raise InputInvalidError("synthesis draft contains an invalid section")
        if len({item.section_id for item in self.sections}) != len(self.sections):
            raise InputInvalidError("synthesis section IDs must be unique")
        object.__setattr__(
            self,
            "included_warning_ids",
            _tuple_text(self.included_warning_ids, "included_warning_ids"),
        )
        object.__setattr__(
            self,
            "included_disagreement_ids",
            _tuple_text(self.included_disagreement_ids, "included_disagreement_ids"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "status": self.status.value,
            "sections": [item.to_dict() for item in self.sections],
            "included_warning_ids": list(self.included_warning_ids),
            "included_disagreement_ids": list(self.included_disagreement_ids),
        }

    @classmethod
    def from_dict(cls, payload: object) -> "SynthesisDraft":
        if not isinstance(payload, (str, bytes, Mapping)):
            raise MalformedResultError("synthesis draft payload is invalid")
        return decode_synthesis_draft(payload)

    def to_json(self) -> str:
        return encode_synthesis_draft(self)


@dataclass(frozen=True, slots=True)
class SynthesisRequest:
    """One bounded generation request for a local synthesis role."""

    request_id: str
    synthesis_input: SynthesisInput
    max_output_tokens: int
    timeout_seconds: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _identifier(self.request_id, "request_id"))
        if not isinstance(self.synthesis_input, SynthesisInput):
            raise InputInvalidError("synthesis request input is invalid")
        if self.request_id != self.synthesis_input.request_id:
            raise InputInvalidError("synthesis request identity does not match its input")
        if (
            isinstance(self.max_output_tokens, bool)
            or not isinstance(self.max_output_tokens, int)
            or self.max_output_tokens <= 0
        ):
            raise InputInvalidError("synthesis max_output_tokens must be positive")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(float(self.timeout_seconds))
            or self.timeout_seconds <= 0
        ):
            raise InputInvalidError("synthesis timeout_seconds must be positive")


def _object(value: object, name: str, allowed: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MalformedResultError(f"synthesis {name} must be an object")
    data = dict(value)
    if any(not isinstance(key, str) for key in data):
        raise MalformedResultError(f"synthesis {name} contains a non-text field")
    unknown = set(data) - allowed
    if unknown:
        raise MalformedResultError(
            f"synthesis {name} contains unsupported fields: " + ", ".join(sorted(unknown))
        )
    return data


def _required(data: Mapping[str, Any], keys: frozenset[str], name: str) -> None:
    missing = keys - set(data)
    if missing:
        raise MalformedResultError(
            f"synthesis {name} is missing required fields: " + ", ".join(sorted(missing))
        )


def _array(value: object, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise MalformedResultError(f"synthesis {name} must be an array")
    return value


def _string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise MalformedResultError(f"synthesis {name} must be text")
    return value


def _section(value: object) -> SynthesisSection:
    data = _object(
        value,
        "section",
        frozenset({"section_id", "title", "result_ids", "claim_ids", "citation_ids"}),
    )
    required = frozenset({"section_id", "title", "result_ids", "claim_ids", "citation_ids"})
    _required(data, required, "section")
    try:
        return SynthesisSection(
            section_id=_string(data["section_id"], "section.section_id"),
            title=_string(data["title"], "section.title"),
            result_ids=tuple(
                _string(item, "section.result_id")
                for item in _array(data["result_ids"], "section.result_ids")
            ),
            claim_ids=tuple(
                _string(item, "section.claim_id")
                for item in _array(data["claim_ids"], "section.claim_ids")
            ),
            citation_ids=tuple(
                _string(item, "section.citation_id")
                for item in _array(data["citation_ids"], "section.citation_ids")
            ),
        )
    except (InputInvalidError, TypeError, ValueError) as exc:
        raise MalformedResultError("synthesis section is invalid") from exc


def decode_synthesis_draft(payload: str | bytes | Mapping[str, object]) -> SynthesisDraft:
    """Decode strict JSON draft output and reject unknown or oversized data."""

    if isinstance(payload, bytes):
        if len(payload) > MAX_SYNTHESIS_BYTES:
            raise MalformedResultError("synthesis draft exceeds its size limit")
        try:
            decoded: object = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MalformedResultError("synthesis draft is not valid JSON") from exc
    elif isinstance(payload, str):
        if len(payload.encode("utf-8")) > MAX_SYNTHESIS_BYTES:
            raise MalformedResultError("synthesis draft exceeds its size limit")
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise MalformedResultError("synthesis draft is not valid JSON") from exc
    elif isinstance(payload, Mapping):
        decoded = dict(payload)
    else:
        raise MalformedResultError("synthesis draft must be JSON text")
    try:
        encoded_size = len(
            json.dumps(decoded, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
    except (TypeError, ValueError) as exc:
        raise MalformedResultError("synthesis draft contains non-JSON values") from exc
    if encoded_size > MAX_SYNTHESIS_BYTES:
        raise MalformedResultError("synthesis draft exceeds its size limit")
    data = _object(
        decoded,
        "draft",
        frozenset(
            {
                "schema_version",
                "status",
                "sections",
                "included_warning_ids",
                "included_disagreement_ids",
            }
        ),
    )
    required = frozenset(
        {
            "schema_version",
            "status",
            "sections",
            "included_warning_ids",
            "included_disagreement_ids",
        }
    )
    _required(data, required, "draft")
    try:
        return SynthesisDraft(
            schema_version=_string(data["schema_version"], "draft.schema_version"),
            status=PlanStatus(_string(data["status"], "draft.status")),
            sections=tuple(_section(item) for item in _array(data["sections"], "draft.sections")),
            included_warning_ids=tuple(
                _string(item, "draft.warning_id")
                for item in _array(data["included_warning_ids"], "draft.included_warning_ids")
            ),
            included_disagreement_ids=tuple(
                _string(item, "draft.disagreement_id")
                for item in _array(
                    data["included_disagreement_ids"], "draft.included_disagreement_ids"
                )
            ),
        )
    except (InputInvalidError, TypeError, ValueError, KeyError) as exc:
        raise MalformedResultError("synthesis draft is invalid") from exc


def encode_synthesis_draft(draft: SynthesisDraft) -> str:
    if not isinstance(draft, SynthesisDraft):
        raise InputInvalidError("synthesis draft must be a SynthesisDraft")
    encoded = json.dumps(draft.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    if len(encoded.encode("utf-8")) > MAX_SYNTHESIS_BYTES:
        raise InputInvalidError("synthesis draft exceeds its size limit")
    return encoded


def synthesis_json_schema(
    synthesis_input: SynthesisInput | None = None,
) -> dict[str, object]:
    """Return the closed JSON schema supplied to Ollama's structured output."""

    def string_array(values: tuple[str, ...] | None = None) -> dict[str, object]:
        items: dict[str, object] = {"type": "string"}
        if values:
            items["enum"] = list(values)
        return {
            "type": "array",
            "items": items,
            "maxItems": len(values) if values is not None else MAX_SYNTHESIS_ITEMS,
        }

    result_ids = synthesis_input.result_ids if synthesis_input is not None else None
    claim_ids = (
        tuple(item.claim_id for item in synthesis_input.claims)
        if synthesis_input is not None
        else None
    )
    citation_ids = (
        tuple(item.citation_id for item in synthesis_input.citations)
        if synthesis_input is not None
        else None
    )
    warning_ids = (
        tuple(item.warning_id for item in synthesis_input.warnings)
        if synthesis_input is not None
        else None
    )
    disagreement_ids = (
        tuple(item.disagreement_id for item in synthesis_input.disagreements)
        if synthesis_input is not None
        else None
    )
    safe_titles = ["", "Summary", "Findings", "Sources", "Limitations", "Disagreements"]
    if synthesis_input is not None:
        safe_titles.extend(item.step_id for item in synthesis_input.step_summaries)
        safe_titles.extend(f"Step {item.step_id}" for item in synthesis_input.step_summaries)
    status_schema: dict[str, object] = (
        {"const": synthesis_input.plan_status.value}
        if synthesis_input is not None
        else {"type": "string", "enum": [item.value for item in PlanStatus]}
    )
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "status",
            "sections",
            "included_warning_ids",
            "included_disagreement_ids",
        ],
        "properties": {
            "schema_version": {"const": SYNTHESIS_DRAFT_SCHEMA_VERSION},
            "status": status_schema,
            "sections": {
                "type": "array",
                "maxItems": MAX_SYNTHESIS_SECTIONS,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["section_id", "title", "result_ids", "claim_ids", "citation_ids"],
                    "properties": {
                        "section_id": {
                            "type": "string",
                            "pattern": r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$",
                        },
                        "title": {"type": "string", "enum": safe_titles},
                        "result_ids": string_array(result_ids),
                        "claim_ids": string_array(claim_ids),
                        "citation_ids": string_array(citation_ids),
                    },
                },
            },
            "included_warning_ids": string_array(warning_ids),
            "included_disagreement_ids": string_array(disagreement_ids),
        },
    }


def _claim_to_dict(item: SynthesisClaim) -> dict[str, object]:
    return {
        "claim_id": item.claim_id,
        "text": item.text,
        "step_id": item.step_id,
        "evidence_ids": list(item.evidence_ids),
        "citation_ids": list(item.citation_ids),
        "support_status": item.support_status,
    }


def _citation_to_dict(item: SynthesisCitation) -> dict[str, object]:
    return {
        "citation_id": item.citation_id,
        "text": item.text,
        "step_id": item.step_id,
        "claim_ids": list(item.claim_ids),
    }


def _warning_to_dict(item: SynthesisWarning) -> dict[str, object]:
    return {"warning_id": item.warning_id, "text": item.text, "step_id": item.step_id}


def _disagreement_to_dict(item: SynthesisDisagreement) -> dict[str, object]:
    return {
        "disagreement_id": item.disagreement_id,
        "claim_id": item.claim_id,
        "step_ids": list(item.step_ids),
        "statements": list(item.statements),
        "evidence_ids": list(item.evidence_ids),
        "source_kind": item.source_kind,
        "reason_code": item.reason_code,
    }


def _step_summary_to_dict(item: SynthesisStepSummary) -> dict[str, object]:
    return {
        "result_id": item.result_id,
        "step_id": item.step_id,
        "status": item.status.value,
        "summary": item.summary,
        "limitations": list(item.limitations),
        "claim_ids": list(item.claim_ids),
        "citation_ids": list(item.citation_ids),
        "warning_ids": list(item.warning_ids),
        "action_receipt": item.action_receipt,
    }


@runtime_checkable
class LocalSynthesisPort(Protocol):
    """Local-only boundary that has no registry, provider, or tool access."""

    def synthesize(self, request: SynthesisRequest) -> SynthesisDraft:
        """Return a typed reference-only draft."""
        ...

    def health(self) -> HealthReport:
        """Report local synthesis readiness."""
        ...

    def cancel(self) -> None:
        """Request cancellation of an active local generation."""
        ...


# Friendly aliases for callers that use the shorter codec names.
decode_draft = decode_synthesis_draft
encode_draft = encode_synthesis_draft
draft_json_schema = synthesis_json_schema

# V3.5 canonical response-composer contracts are re-exported here as a small
# migration aid for integrations that imported the former synthesis port.
from .local_response_composer import (  # noqa: E402
    LocalResponseComposerPort,
    MemoryContextPlaceholder,
    PersonalityContextPlaceholder,
    ResponseCitationSummary,
    ResponseClaimSummary,
    ResponseCompositionDraft,
    ResponseCompositionInput,
    ResponseCompositionRequest,
    ResponseDisagreementSummary,
    ResponseResultSummary,
    ResponseSection,
    ResponseWarningSummary,
    decode_response_composition_draft,
    response_composer_json_schema,
)

__all__ = [
    "LocalSynthesisPort",
    "MAX_SYNTHESIS_BYTES",
    "MAX_SYNTHESIS_DRAFT_BYTES",
    "SYNTHESIS_DRAFT_SCHEMA_VERSION",
    "SYNTHESIS_INPUT_SCHEMA_VERSION",
    "SYNTHESIS_SCHEMA_VERSION",
    "SynthesisClaim",
    "SynthesisCitation",
    "SynthesisDisagreement",
    "SynthesisDraft",
    "SynthesisInput",
    "SynthesisRequest",
    "SynthesisSection",
    "SynthesisStepSummary",
    "SynthesisWarning",
    "decode_draft",
    "decode_synthesis_draft",
    "draft_json_schema",
    "encode_draft",
    "encode_synthesis_draft",
    "synthesis_json_schema",
    "LocalResponseComposerPort",
    "MemoryContextPlaceholder",
    "PersonalityContextPlaceholder",
    "ResponseClaimSummary",
    "ResponseCitationSummary",
    "ResponseCompositionDraft",
    "ResponseCompositionInput",
    "ResponseCompositionRequest",
    "ResponseDisagreementSummary",
    "ResponseResultSummary",
    "ResponseSection",
    "ResponseWarningSummary",
    "decode_response_composition_draft",
    "response_composer_json_schema",
]
