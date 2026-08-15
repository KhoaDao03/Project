"""Controlled vocabularies (enums) for Elly's contracts.

Design source: DESIGN.md §2.3 (task vs epistemic status), §6.2 (TaskResult),
§6.8 (error taxonomy). These enums are the frozen surface that later milestones
extend by ADDING members, never by repurposing existing ones (NFR-006).

Status: Scaffolded (M1). Subject to M0 contract-freeze.

Non-responsibilities: these enums carry no behavior/policy. Transition rules live
in `state_machine.py`; error handling lives in `errors.py`.
"""

from __future__ import annotations

from enum import Enum


class CloudMode(str, Enum):
    """Session privacy mode (AI-014).

    M1 supports LOCAL_ONLY only. CLOUD_PERMITTED is defined because it is part of
    the frozen contract, but no cloud path exists until M5; selecting it in M1
    must fail explicitly (never silently behave like local). See presentation/cli.
    """

    LOCAL_ONLY = "local_only"
    CLOUD_PERMITTED = "cloud_permitted"


class PersistenceMode(str, Enum):
    """Whether message bodies may be stored (DATA-001)."""

    STORE_WITH_RETENTION = "store_with_retention"
    NO_STORE = "no_store"


class Route(str, Enum):
    """Which execution path handled the request (AI-005).

    Local conversation and M4 hosted web research are implemented; coding remains
    deferred to M5.
    """

    LOCAL_GENERALIST = "local_generalist"
    WEB_RESEARCH = "web_research"
    RESEARCH_SPECIALIST = "research_specialist"
    CODING_SPECIALIST = "coding_specialist"


class RouteReasonCode(str, Enum):
    """Safe diagnostic reason for an application-owned route decision."""

    LOCAL_DEFAULT = "LOCAL_DEFAULT"
    CURRENT_INFORMATION_REQUIRED = "CURRENT_INFORMATION_REQUIRED"
    CODING_REQUEST = "CODING_REQUEST"
    RESEARCH_SPECIALIST_REQUEST = "RESEARCH_SPECIALIST_REQUEST"
    PROPOSAL_ACCEPTED = "PROPOSAL_ACCEPTED"
    PROPOSAL_REJECTED = "PROPOSAL_REJECTED"
    CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"
    AUTHORIZATION_DENIED = "AUTHORIZATION_DENIED"
    INVALID_REQUEST = "INVALID_REQUEST"
    INTENT_CLARIFICATION_REQUIRED = "INTENT_CLARIFICATION_REQUIRED"
    INTENT_REJECTED = "INTENT_REJECTED"


class IntentAmbiguity(str, Enum):
    """Deterministic interpretation state for an untrusted capability proposal."""

    CLEAR = "clear"
    AMBIGUOUS = "ambiguous"
    MISSING_FIELDS = "missing_fields"
    NONE_PROPOSED = "none_proposed"


class IntentEntitySource(str, Enum):
    """How an intent entity was obtained; never treated as authorization."""

    EXPLICIT = "explicit"
    CONTEXTUAL = "contextual"
    INFERRED = "inferred"


class ActionCategory(str, Enum):
    """Normalized category for a proposed side effect."""

    NONE = "none"
    CONTENT_DRAFT = "content_draft"
    EXTERNAL_COMMUNICATION = "external_communication"
    DELETE = "delete"
    FINANCIAL_TRANSACTION = "financial_transaction"
    ACCOUNT_CHANGE = "account_change"
    EXTERNAL_WRITE = "external_write"
    IRREVERSIBLE_OPERATION = "irreversible_operation"


class ActionSideEffect(str, Enum):
    """Where a proposed action would change state, if executed."""

    NONE = "none"
    LOCAL_STATE = "local_state"
    EXTERNAL_STATE = "external_state"


class ActionReversibility(str, Enum):
    """How safely a proposed side effect can be undone."""

    REVERSIBLE = "reversible"
    PARTIALLY_REVERSIBLE = "partially_reversible"
    IRREVERSIBLE = "irreversible"
    UNKNOWN = "unknown"


class ActionDataSensitivity(str, Enum):
    """Sensitivity of data involved in a proposed action."""

    PUBLIC = "public"
    LOCAL = "local"
    RESTRICTED = "restricted"
    UNCLASSIFIED = "unclassified"


class ActionImpactFlag(str, Enum):
    """Independent impact dimensions used by the deterministic risk policy."""

    FINANCIAL = "financial"
    LEGAL = "legal"
    ACCOUNT = "account"
    COMMUNICATION = "communication"
    DELETION = "deletion"


class ActionProposalSource(str, Enum):
    """Whether an action description came from application code or a model."""

    CAPABILITY_DECLARED = "capability_declared"
    MODEL_PROPOSED = "model_proposed"


class TaskStatus(str, Enum):
    """Execution outcome of a task (DESIGN §2.3, §5.4).

    The full lifecycle vocabulary is fixed here. M1 only drives a subset
    (queued -> running -> completed | failed | blocked); AWAITING_CONSENT (M5),
    CANCELLED (M2/M3), and PARTIAL (M3/M4) are reserved and unreachable in M1.
    """

    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_CONSENT = "awaiting_consent"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    COMPLETED = "completed"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    FAILED = "failed"
    BLOCKED = "blocked"
    INTERRUPTED = "interrupted"


class OutcomeCode(str, Enum):
    """Stable reason/outcome vocabulary independent of task lifecycle."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"
    CANCELLED = "cancelled"
    AWAITING_CONSENT = "awaiting_consent"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    CLARIFICATION_REQUIRED = "clarification_required"
    POSSIBLE_DUPLICATE_EXECUTION = "possible_duplicate_execution"


class EpistemicStatus(str, Enum):
    """Answer-confidence axis, independent of execution status (AI-010, ADR-016)."""

    KNOWN = "known"
    INFERRED = "inferred"
    UNKNOWN = "unknown"
    BLOCKED = "blocked"


class ValidationStatus(str, Enum):
    """Result-validation axis (AI-012, ADR-016)."""

    VALIDATED = "validated"
    QUALIFIED = "qualified"
    REJECTED = "rejected"


class ErrorClass(str, Enum):
    """Typed failure taxonomy (DESIGN §6.8).

    The complete taxonomy is declared so audit/error contracts are stable across
    milestones. Only a subset is REACHABLE in M1 (see errors.py):
    INPUT_INVALID, CONFIG_INVALID, STORAGE_FAILURE, MALFORMED_RESULT,
    TRANSIENT_PROVIDER, PERMANENT_PROVIDER, PERMISSION_DENIED. The remainder
    (LIMIT_EXCEEDED, TIMEOUT, UNSAFE_URL, UNSUPPORTED_CONTENT, CANCELLED) belong
    to M3/M4 and must not be raised by M1 code.
    """

    INPUT_INVALID = "INPUT_INVALID"
    CONFIG_INVALID = "CONFIG_INVALID"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    TRANSIENT_PROVIDER = "TRANSIENT_PROVIDER"
    PERMANENT_PROVIDER = "PERMANENT_PROVIDER"
    TIMEOUT = "TIMEOUT"
    MALFORMED_RESULT = "MALFORMED_RESULT"
    UNSAFE_URL = "UNSAFE_URL"
    UNSUPPORTED_CONTENT = "UNSUPPORTED_CONTENT"
    STORAGE_FAILURE = "STORAGE_FAILURE"
    CANCELLED = "CANCELLED"
    CONFLICT = "CONFLICT"


class HealthState(str, Enum):
    """Dependency health for OPS-002 `/status` (initial in M1)."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"
