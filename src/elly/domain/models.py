"""Typed contract models for Elly (DESIGN §6.2–6.6).

These are the stable data contracts the whole system agrees on. They are plain
stdlib dataclasses (no third-party dependency) with explicit validation in
`__post_init__`, raising typed `EllyError`s on violation.

Status: Implemented through M5. Research and specialist fields are populated only
when their application-owned workflows successfully produce them.
Subject to M0 contract-freeze.

Security/privacy:
- AuditEvent deliberately has NO free-text body field — audit records store
  metadata only, so raw prompts/answers/secrets/chain-of-thought cannot leak
  (SEC-007, DATA-004).
- Message bodies are held here in-process only; persistence honors
  PersistenceMode at the repository boundary (DATA-001).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Mapping

from .enums import (
    CloudMode,
    EpistemicStatus,
    ErrorClass,
    HealthState,
    PersistenceMode,
    Route,
    TaskStatus,
    ValidationStatus,
)
from .errors import InputInvalidError


def _require_nonempty(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InputInvalidError(f"{name} must be a non-empty string")
    return value


def _require_aware_utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise InputInvalidError(f"{name} must be a timezone-aware UTC datetime")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class TaskRequest:
    """A validated request entering the application (DESIGN §6.2).

    Inputs: client-generated `request_id`, `session_id`, already size-checked
    `text` (presentation layer enforces FR-001 size/empty limits BEFORE this is
    built), the session `cloud_mode`/`persistence_mode`, and a UTC timestamp.

    Validation: ids/text non-empty; timestamp tz-aware UTC; enums well-typed.
    Failures: raises InputInvalidError.
    Side effects: none (immutable value object).
    Non-responsibilities: does not enforce max length (that is the presentation
    boundary) and does not decide routing.
    """

    request_id: str
    session_id: str
    text: str
    cloud_mode: CloudMode
    persistence_mode: PersistenceMode
    submitted_at: datetime
    approval_id: str | None = None

    def __post_init__(self) -> None:
        _require_nonempty(self.request_id, "request_id")
        _require_nonempty(self.session_id, "session_id")
        _require_nonempty(self.text, "text")
        if not isinstance(self.cloud_mode, CloudMode):
            raise InputInvalidError("cloud_mode must be a CloudMode")
        if not isinstance(self.persistence_mode, PersistenceMode):
            raise InputInvalidError("persistence_mode must be a PersistenceMode")
        object.__setattr__(self, "submitted_at", _require_aware_utc(self.submitted_at, "submitted_at"))


@dataclass(frozen=True, slots=True)
class TaskResult:
    """The three-axis result contract (DESIGN §6.2, ADR-016).

    Separates execution (`task_status`) from answer confidence
    (`epistemic_status`) from validation (`validation_status`) so partial failure
    and honest uncertainty never collapse into a false success (AI-010/011/012).

    M1 fills: task_id, the three statuses, answer, route_summary. The
    research-oriented lists stay empty (no evidence path until M4).
    """

    task_id: str
    task_status: TaskStatus
    epistemic_status: EpistemicStatus
    validation_status: ValidationStatus
    answer: str
    route_summary: Route
    claims: tuple[str, ...] = ()
    citations: tuple[str, ...] = ()
    partial_work: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()
    next_actions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_nonempty(self.task_id, "task_id")
        # answer may be empty ONLY for a typed failure/blocked result.
        if not self.answer.strip() and self.task_status not in (
            TaskStatus.FAILED,
            TaskStatus.BLOCKED,
            TaskStatus.CANCELLED,
            TaskStatus.PARTIAL,
        ):
            raise InputInvalidError("answer may be empty only for a failed/blocked task")


@dataclass(frozen=True, slots=True)
class EvidenceObject:
    """Validated hosted-search provenance (DATA-003, DEC-OQ-07).

    Hosted search cannot provide an application-fetched content hash or page body;
    those fields are therefore optional and remain empty on this M4 path. Citation
    metadata is still validated by the application before it is rendered.
    """

    evidence_id: str
    url: str
    title: str
    publisher: str
    retrieved_at: datetime
    source_class: str = "secondary"
    snippet: str = ""
    canonical_url: str = ""
    content_hash: str = ""
    freshness: str = "not_applicable"
    safety_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for value, name in ((self.evidence_id, "evidence_id"), (self.url, "url"), (self.title, "title")):
            _require_nonempty(value, name)
        object.__setattr__(self, "retrieved_at", _require_aware_utc(self.retrieved_at, "retrieved_at"))


@dataclass(frozen=True, slots=True)
class ClaimSupport:
    """Claim-to-evidence binding used by research responses (AI-011/012)."""

    claim_id: str
    text: str
    support_status: str
    evidence_ids: tuple[str, ...] = ()
    note: str = ""

    def __post_init__(self) -> None:
        _require_nonempty(self.claim_id, "claim_id")
        _require_nonempty(self.text, "text")
        if self.support_status not in {"direct", "indirect", "conflicted", "unsupported"}:
            raise InputInvalidError("support_status is invalid")


@dataclass(frozen=True, slots=True)
class Message:
    """A single turn in a session (DESIGN §13.1).

    `role` is "user" or "assistant". `content` is the raw body held in-process;
    whether it is persisted depends on PersistenceMode at the repository.
    """

    role: str
    content: str
    created_at: datetime

    def __post_init__(self) -> None:
        if self.role not in ("user", "assistant"):
            raise InputInvalidError("role must be 'user' or 'assistant'")
        object.__setattr__(self, "created_at", _require_aware_utc(self.created_at, "created_at"))


@dataclass(frozen=True, slots=True)
class SessionRecord:
    """Conversation boundary metadata (DATA-001)."""

    session_id: str
    persistence_mode: PersistenceMode
    cloud_mode: CloudMode
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ContextManifest:
    """Auditable record of what context a model call received (DESIGN §6.6, AI-006).

    Records metadata (which item ids were included/excluded and why) — NOT raw
    content — so "minimum sufficient context" is observable without logging
    sensitive bodies. M1 records a minimal manifest (recent messages, budget).
    """

    included_message_ids: tuple[int, ...]
    excluded_reason_counts: dict[str, int]
    reserved_output_tokens: int
    input_token_estimate: int


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Redacted, correlated operational record (DATA-004, SEC-007).

    NOTE THE ABSENCE of any message-body / prompt / answer field: audit stores
    metadata only. `detail` is a short, allowlisted, non-sensitive summary.
    """

    task_id: str
    session_id: str
    event_type: str
    at: datetime
    route: Route | None = None
    task_status: TaskStatus | None = None
    error_class: ErrorClass | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        _require_nonempty(self.task_id, "task_id")
        _require_nonempty(self.session_id, "session_id")
        _require_nonempty(self.event_type, "event_type")
        object.__setattr__(self, "at", _require_aware_utc(self.at, "at"))


# --- Provider DTOs (GeneralistPort surface, DESIGN §6.7) --------------------


@dataclass(frozen=True, slots=True)
class GeneralistRequest:
    """Bounded request handed to a generalist model adapter (real or fake).

    `prompt` is the already-context-built text; `model_id` and `max_output_tokens`
    come from configuration. No tools, no authority tokens (SEC-005): a model may
    produce text only, never authorize actions.
    """

    prompt: str
    model_id: str
    max_output_tokens: int


@dataclass(frozen=True, slots=True)
class GeneralistUsage:
    """Usage/timing metadata normalized across adapters (OPS-001/003 initial)."""

    output_tokens: int
    latency_ms: int


@dataclass(frozen=True, slots=True)
class GeneralistResponse:
    """Normalized generalist output (DESIGN §6.7).

    `text` is untrusted model output treated as a PROPOSAL, never an instruction
    (SEC-003/SEC-005). Validation happens in the orchestrator, not here.
    """

    text: str
    usage: GeneralistUsage


@dataclass(frozen=True, slots=True)
class HealthReport:
    """One dependency's health for `/status` (OPS-002 initial)."""

    component: str
    state: HealthState
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ConversationOutcome:
    """What the orchestrator returns to the presentation layer.

    Bundles the user-facing `result` with the `manifest` used, so the CLI can
    render the response and (later) traces without reaching into internals.

    `assistant_message` is None on a blocked/failed turn (there is no assistant
    reply to persist) and set to the persisted Message on success.
    """

    result: TaskResult
    manifest: ContextManifest
    assistant_message: Message | None = None
    consent_proposal: object | None = None
