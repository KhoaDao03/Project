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
from types import MappingProxyType
from typing import TYPE_CHECKING, Mapping, TypeAlias

from .enums import (
    ActionCategory,
    ActionDataSensitivity,
    ActionImpactFlag,
    ActionProposalSource,
    ActionReversibility,
    ActionSideEffect,
    CloudMode,
    EpistemicStatus,
    ErrorClass,
    HealthState,
    IntentAmbiguity,
    IntentEntitySource,
    OutcomeCode,
    PersistenceMode,
    Route,
    RouteReasonCode,
    TaskStatus,
    ValidationStatus,
)
from .errors import InputInvalidError

IntentScalar: TypeAlias = str | int | float | bool | None

if TYPE_CHECKING:
    from ..application.routing_contracts import CapabilitySelectionProposal, TaskIntent
    from ..privacy import ConsentProposal


def _require_nonempty(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InputInvalidError(f"{name} must be a non-empty string")
    return value


def _require_aware_utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise InputInvalidError(f"{name} must be a timezone-aware UTC datetime")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class IntentEntity:
    """A bounded entity extracted from an untrusted capability proposal."""

    kind: str
    value: str
    source: IntentEntitySource

    def __post_init__(self) -> None:
        _require_nonempty(self.kind, "intent entity kind")
        _require_nonempty(self.value, "intent entity value")
        if not isinstance(self.source, IntentEntitySource):
            raise InputInvalidError("intent entity source must be an IntentEntitySource")


@dataclass(frozen=True, slots=True)
class CapabilityIntent:
    """Structured, untrusted capability proposal used by deterministic routing."""

    proposed_capability_id: str | None
    operation: str
    entities: tuple[IntentEntity, ...] = ()
    arguments: Mapping[str, IntentScalar] = field(default_factory=dict)
    confidence: float = 0.0
    ambiguity: IntentAmbiguity = IntentAmbiguity.NONE_PROPOSED
    rationale_code: str = ""

    def __post_init__(self) -> None:
        if self.proposed_capability_id is not None:
            _require_nonempty(self.proposed_capability_id, "intent capability id")
        if not isinstance(self.operation, str):
            raise InputInvalidError("intent operation must be text")
        if not isinstance(self.entities, tuple) or any(
            not isinstance(entity, IntentEntity) for entity in self.entities
        ):
            raise InputInvalidError("intent entities must contain IntentEntity values")
        if not isinstance(self.arguments, Mapping):
            raise InputInvalidError("intent arguments must be a mapping")
        normalized: dict[str, IntentScalar] = {}
        for key, value in self.arguments.items():
            _require_nonempty(key, "intent argument name")
            if not isinstance(value, (str, int, float, bool)) and value is not None:
                raise InputInvalidError("intent arguments must contain scalar values")
            normalized[key] = value
        object.__setattr__(self, "arguments", MappingProxyType(normalized))
        if isinstance(self.confidence, bool) or not 0 <= self.confidence <= 1:
            raise InputInvalidError("intent confidence must be between 0 and 1")
        if not isinstance(self.ambiguity, IntentAmbiguity):
            raise InputInvalidError("intent ambiguity must be an IntentAmbiguity")
        _require_nonempty(self.rationale_code, "intent rationale_code")
        if self.ambiguity is IntentAmbiguity.NONE_PROPOSED:
            if self.proposed_capability_id is not None:
                raise InputInvalidError("none-proposed intent cannot name a capability")
        elif self.ambiguity is IntentAmbiguity.CLEAR and self.proposed_capability_id is None:
            raise InputInvalidError("selected intent must name a capability")


@dataclass(frozen=True, slots=True)
class ActionTarget:
    """Bounded, safe reference to an action target; never a raw payload."""

    kind: str
    reference: str

    def __post_init__(self) -> None:
        _require_nonempty(self.kind, "action target kind")
        _require_nonempty(self.reference, "action target reference")
        if any(char in self.kind or char in self.reference for char in ("\n", "\r")):
            raise InputInvalidError("action target must be single-line metadata")
        if len(self.kind) > 64 or len(self.reference) > 256:
            raise InputInvalidError("action target metadata exceeds its bound")

    @property
    def normalized(self) -> tuple[str, str]:
        return (self.kind.strip().casefold(), self.reference.strip().casefold())


@dataclass(frozen=True, slots=True)
class ActionProposal:
    """Typed, untrusted description of a possible consequential action."""

    category: ActionCategory
    target: ActionTarget | None = None
    side_effect: ActionSideEffect = ActionSideEffect.NONE
    reversibility: ActionReversibility = ActionReversibility.REVERSIBLE
    data_sensitivity: ActionDataSensitivity = ActionDataSensitivity.PUBLIC
    impact_flags: tuple[ActionImpactFlag, ...] = ()
    confirmation_required: bool = False
    source: ActionProposalSource = ActionProposalSource.CAPABILITY_DECLARED

    def __post_init__(self) -> None:
        if not isinstance(self.category, ActionCategory):
            raise InputInvalidError("action category must be an ActionCategory")
        if self.target is not None and not isinstance(self.target, ActionTarget):
            raise InputInvalidError("action target has an invalid type")
        if not isinstance(self.side_effect, ActionSideEffect):
            raise InputInvalidError("action side_effect must be an ActionSideEffect")
        if not isinstance(self.reversibility, ActionReversibility):
            raise InputInvalidError("action reversibility must be an ActionReversibility")
        if not isinstance(self.data_sensitivity, ActionDataSensitivity):
            raise InputInvalidError("action data_sensitivity must be an ActionDataSensitivity")
        if not isinstance(self.impact_flags, tuple) or any(
            not isinstance(flag, ActionImpactFlag) for flag in self.impact_flags
        ):
            raise InputInvalidError("action impact_flags must contain ActionImpactFlag values")
        if len(set(self.impact_flags)) != len(self.impact_flags):
            raise InputInvalidError("action impact_flags must be unique")
        if not isinstance(self.confirmation_required, bool):
            raise InputInvalidError("action confirmation_required must be a bool")
        if not isinstance(self.source, ActionProposalSource):
            raise InputInvalidError("action source must be an ActionProposalSource")
        if self.category is ActionCategory.NONE:
            if self.target is not None or self.side_effect is not ActionSideEffect.NONE:
                raise InputInvalidError("none action cannot have a target or side effect")
            if self.impact_flags or self.confirmation_required:
                raise InputInvalidError("none action cannot require confirmation or impact flags")
        if (
            self.category is ActionCategory.CONTENT_DRAFT
            and self.side_effect is not ActionSideEffect.NONE
        ):
            raise InputInvalidError("content drafts must not declare a state-changing effect")

    @classmethod
    def none(
        cls,
        *,
        source: ActionProposalSource = ActionProposalSource.CAPABILITY_DECLARED,
    ) -> "ActionProposal":
        return cls(category=ActionCategory.NONE, source=source)

    @property
    def is_consequential(self) -> bool:
        return self.category not in {
            ActionCategory.NONE,
            ActionCategory.CONTENT_DRAFT,
        }


@dataclass(frozen=True, slots=True)
class ActionConfirmationProposal:
    """Exact, one-time approval request for one normalized action."""

    confirmation_id: str
    task_id: str
    capability_id: str
    operation: str
    proposal: ActionProposal
    action_digest: str
    created_at: datetime
    expires_at: datetime
    nonce: str
    plan_id: str = ""
    step_id: str = ""

    def __post_init__(self) -> None:
        for value, name in (
            (self.confirmation_id, "confirmation_id"),
            (self.task_id, "task_id"),
            (self.capability_id, "capability_id"),
            (self.operation, "operation"),
            (self.action_digest, "action_digest"),
            (self.nonce, "nonce"),
        ):
            _require_nonempty(value, f"action confirmation {name}")
        for value, name in (
            (self.plan_id, "action confirmation plan_id"),
            (self.step_id, "action confirmation step_id"),
        ):
            if not isinstance(value, str):
                raise InputInvalidError(f"{name} must be text")
        if not isinstance(self.proposal, ActionProposal):
            raise InputInvalidError("action confirmation proposal is invalid")
        object.__setattr__(
            self,
            "created_at",
            _require_aware_utc(self.created_at, "action confirmation created_at"),
        )
        object.__setattr__(
            self,
            "expires_at",
            _require_aware_utc(self.expires_at, "action confirmation expires_at"),
        )
        if self.expires_at <= self.created_at:
            raise InputInvalidError("action confirmation expiry must be after creation")


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
    route_proposal: "RouteProposal | None" = None
    capability_intent: "CapabilityIntent | None" = None
    action_confirmation_id: str | None = None

    def __post_init__(self) -> None:
        _require_nonempty(self.request_id, "request_id")
        _require_nonempty(self.session_id, "session_id")
        _require_nonempty(self.text, "text")
        if not isinstance(self.cloud_mode, CloudMode):
            raise InputInvalidError("cloud_mode must be a CloudMode")
        if not isinstance(self.persistence_mode, PersistenceMode):
            raise InputInvalidError("persistence_mode must be a PersistenceMode")
        if self.route_proposal is not None and not isinstance(self.route_proposal, RouteProposal):
            raise InputInvalidError("route_proposal must be a RouteProposal or null")
        if self.action_confirmation_id is not None:
            _require_nonempty(self.action_confirmation_id, "action_confirmation_id")
        if self.capability_intent is not None and not isinstance(
            self.capability_intent, CapabilityIntent
        ):
            raise InputInvalidError("capability_intent must be a CapabilityIntent or null")
        object.__setattr__(
            self, "submitted_at", _require_aware_utc(self.submitted_at, "submitted_at")
        )


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
    outcome_code: OutcomeCode = OutcomeCode.SUCCESS
    provenance: tuple["ProvenanceReference", ...] = ()
    claim_supports: tuple["ClaimSupport", ...] = ()
    answer_retained: bool = True
    # V2.5 routing metadata is additive. New results use a generic
    # ``route_summary`` and persist selected capability identity separately.
    route_category: Route | None = None
    capability_id: str | None = None
    operation: str = ""
    selection_reason_code: str = ""
    routing_contract_version: str = ""
    candidate_count: int = 0
    rejected_candidate_reason_codes: tuple[str, ...] = ()
    clarification_required: bool = False
    freshness_affected_selection: bool = False

    def __post_init__(self) -> None:
        _require_nonempty(self.task_id, "task_id")
        if not isinstance(self.route_summary, Route):
            raise InputInvalidError("route_summary must be a Route")
        if not isinstance(self.outcome_code, OutcomeCode):
            raise InputInvalidError("outcome_code must be an OutcomeCode")
        if not isinstance(self.answer_retained, bool):
            raise InputInvalidError("answer_retained must be a bool")
        if self.route_category is not None and not isinstance(self.route_category, Route):
            raise InputInvalidError("route_category must be a Route or null")
        if self.capability_id is not None:
            _require_nonempty(self.capability_id, "task result capability_id")
        if not isinstance(self.operation, str):
            raise InputInvalidError("task result operation must be text")
        if not isinstance(self.selection_reason_code, str):
            raise InputInvalidError("task result selection_reason_code must be text")
        if not isinstance(self.routing_contract_version, str):
            raise InputInvalidError("task result routing_contract_version must be text")
        if isinstance(self.candidate_count, bool) or not isinstance(self.candidate_count, int):
            raise InputInvalidError("task result candidate_count must be an integer")
        if not 0 <= self.candidate_count <= 10000:
            raise InputInvalidError("task result candidate_count is out of range")
        if (
            not isinstance(self.rejected_candidate_reason_codes, tuple)
            or len(self.rejected_candidate_reason_codes) > 64
        ):
            raise InputInvalidError(
                "task result rejected_candidate_reason_codes must be a bounded tuple"
            )
        for code in self.rejected_candidate_reason_codes:
            if (
                not isinstance(code, str)
                or not code
                or len(code) > 64
                or not code[0].isalpha()
                or not all(char.isalnum() or char in "._-" for char in code)
            ):
                raise InputInvalidError(
                    "task result rejected candidate reason codes must be safe codes"
                )
        if not isinstance(self.clarification_required, bool):
            raise InputInvalidError("task result clarification_required must be a bool")
        if not isinstance(self.freshness_affected_selection, bool):
            raise InputInvalidError("task result freshness_affected_selection must be a bool")
        if any(not isinstance(item, ProvenanceReference) for item in self.provenance):
            raise InputInvalidError("provenance must contain ProvenanceReference values")
        if any(not isinstance(item, ClaimSupport) for item in self.claim_supports):
            raise InputInvalidError("claim_supports must contain ClaimSupport values")
        # answer may be empty ONLY for a typed failure/blocked result.
        if (
            not self.answer.strip()
            and self.answer_retained
            and self.task_status
            not in (
                TaskStatus.FAILED,
                TaskStatus.BLOCKED,
                TaskStatus.CANCELLED,
                TaskStatus.PARTIAL,
            )
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
    supporting_passage: str = ""
    validation_status: str = "metadata_only"
    source_published_at: datetime | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.evidence_id, "evidence_id"),
            (self.url, "url"),
            (self.title, "title"),
        ):
            _require_nonempty(value, name)
        object.__setattr__(
            self, "retrieved_at", _require_aware_utc(self.retrieved_at, "retrieved_at")
        )
        if self.source_published_at is not None:
            object.__setattr__(
                self,
                "source_published_at",
                _require_aware_utc(self.source_published_at, "source_published_at"),
            )


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
        if self.support_status not in {
            "direct",
            "indirect",
            "supported",
            "conflicted",
            "unsupported",
            "unverified",
            "absent",
            "contradicted",
        }:
            raise InputInvalidError("support_status is invalid")


@dataclass(frozen=True, slots=True)
class ProvenanceReference:
    """Safe reference to approved context or evidence that influenced a result."""

    kind: str
    reference_id: str
    recorded_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_nonempty(self.kind, "provenance kind")
        _require_nonempty(self.reference_id, "provenance reference_id")
        if self.recorded_at is not None:
            object.__setattr__(
                self, "recorded_at", _require_aware_utc(self.recorded_at, "recorded_at")
            )


@dataclass(frozen=True, slots=True)
class RouteRequest:
    """Typed input to routing policy; contains no model authorization."""

    request_id: str
    text: str
    contextual_text: str | None = None
    cloud_mode: CloudMode = CloudMode.LOCAL_ONLY

    def __post_init__(self) -> None:
        _require_nonempty(self.request_id, "route request_id")
        _require_nonempty(self.text, "route text")
        if self.contextual_text is not None and not isinstance(self.contextual_text, str):
            raise InputInvalidError("contextual_text must be text or null")
        if not isinstance(self.cloud_mode, CloudMode):
            raise InputInvalidError("route cloud_mode must be a CloudMode")


@dataclass(frozen=True, slots=True)
class RouteProposal:
    """Untrusted route/capability suggestion from a model or classifier."""

    route: Route | None = None
    capability_id: str | None = None
    request_schema: str = ""

    def __post_init__(self) -> None:
        if self.route is None and not self.capability_id:
            raise InputInvalidError("route proposal must name a route or capability")
        if self.route is not None and not isinstance(self.route, Route):
            raise InputInvalidError("route proposal route must be a Route")
        if self.capability_id is not None:
            _require_nonempty(self.capability_id, "route proposal capability_id")
        if self.route is Route.REGISTERED_CAPABILITY and self.capability_id is None:
            raise InputInvalidError("registered-capability route proposal must name a capability")


@dataclass(frozen=True, slots=True)
class RouteDecision:
    """Final deterministic route decision with an auditable reason code."""

    route: Route
    reason_code: RouteReasonCode
    capability_id: str | None = None
    diagnostic: str = ""
    available: bool = True
    operation: str = ""
    intent: "CapabilityIntent | TaskIntent | None" = None
    clarification_required: bool = False
    clarification_fields: tuple[str, ...] = ()
    selection: "CapabilitySelectionProposal | None" = None
    candidate_count: int = 0
    rejected_candidate_reason_codes: tuple[str, ...] = ()
    freshness_affected_selection: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.route, Route):
            raise InputInvalidError("route decision route must be a Route")
        if not isinstance(self.reason_code, RouteReasonCode):
            raise InputInvalidError("route decision reason_code must be a RouteReasonCode")
        if self.capability_id is not None:
            _require_nonempty(self.capability_id, "route decision capability_id")
        if self.route is Route.REGISTERED_CAPABILITY and self.capability_id is None:
            raise InputInvalidError("registered-capability route must name a capability")
        if not isinstance(self.operation, str):
            raise InputInvalidError("route decision operation must be text")
        if self.intent is not None and not isinstance(self.intent, CapabilityIntent):
            # Import lazily to keep the domain model independent of the
            # application routing-contract module during module initialization.
            from ..application.routing_contracts import TaskIntent

            if not isinstance(self.intent, TaskIntent):
                raise InputInvalidError("route decision intent has an invalid type")
        if not isinstance(self.clarification_required, bool):
            raise InputInvalidError("route decision clarification_required must be a bool")
        if not isinstance(self.clarification_fields, tuple) or any(
            not isinstance(field, str) or not field.strip() for field in self.clarification_fields
        ):
            raise InputInvalidError("route decision clarification fields are invalid")
        if self.clarification_required and not self.clarification_fields:
            raise InputInvalidError("clarification-required route must name missing fields")
        if self.selection is not None:
            from ..application.routing_contracts import CapabilitySelectionProposal

            if not isinstance(self.selection, CapabilitySelectionProposal):
                raise InputInvalidError("route decision selection has an invalid type")
        if isinstance(self.candidate_count, bool) or not isinstance(self.candidate_count, int):
            raise InputInvalidError("route decision candidate_count must be an integer")
        if not 0 <= self.candidate_count <= 10000:
            raise InputInvalidError("route decision candidate_count is out of range")
        if (
            not isinstance(self.rejected_candidate_reason_codes, tuple)
            or len(self.rejected_candidate_reason_codes) > 64
        ):
            raise InputInvalidError(
                "route decision rejected_candidate_reason_codes must be a bounded tuple"
            )
        for code in self.rejected_candidate_reason_codes:
            if (
                not isinstance(code, str)
                or not code
                or len(code) > 64
                or not code[0].isalpha()
                or not all(char.isalnum() or char in "._-" for char in code)
            ):
                raise InputInvalidError(
                    "route decision rejected candidate reason codes must be safe codes"
                )
        if not isinstance(self.freshness_affected_selection, bool):
            raise InputInvalidError("route decision freshness_affected_selection must be a bool")

    @property
    def generic_route(self) -> Route:
        """Return the route category used for execution and persistence."""

        from ..application.route_compatibility import generic_route_for

        return generic_route_for(self.route, self.capability_id)


@dataclass(frozen=True, slots=True)
class OperationLease:
    """Idempotency claim for one externally meaningful operation."""

    operation_id: str
    fresh: bool
    state: str
    possible_duplicate: bool = False


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
    updated_at: datetime | None = None
    version: int = 1

    def __post_init__(self) -> None:
        _require_nonempty(self.session_id, "session_id")
        if not isinstance(self.persistence_mode, PersistenceMode):
            raise InputInvalidError("persistence_mode must be a PersistenceMode")
        if not isinstance(self.cloud_mode, CloudMode):
            raise InputInvalidError("cloud_mode must be a CloudMode")
        created_at = _require_aware_utc(self.created_at, "created_at")
        updated_at = _require_aware_utc(
            self.updated_at if self.updated_at is not None else created_at,
            "updated_at",
        )
        if self.version < 1:
            raise InputInvalidError("session version must be at least 1")
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", updated_at)


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
    consent_proposal: "ConsentProposal | None" = None
    action_confirmation: ActionConfirmationProposal | None = None
