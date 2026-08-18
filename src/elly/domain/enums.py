"""Controlled vocabularies (enums) for Elly's contracts.

Design source: DESIGN.md §2.3 (task vs epistemic status), §6.2 (TaskResult),
§6.8 (error taxonomy). These enums are stable contract vocabulary; compatibility
members are retained rather than repurposed (NFR-006).

Non-responsibilities: these enums carry no behavior/policy. Transition rules live
in `state_machine.py`; error handling lives in `errors.py`.
"""

from __future__ import annotations

from enum import Enum


class CloudMode(str, Enum):
    """Session privacy mode (AI-014).

    ``LOCAL_ONLY`` and ``CLOUD_PERMITTED`` are explicit privacy modes. Cloud
    execution remains subject to application authorization and consent; it must
    never silently behave like local execution.
    """

    LOCAL_ONLY = "local_only"
    CLOUD_PERMITTED = "cloud_permitted"


class PersistenceMode(str, Enum):
    """Whether message bodies may be stored (DATA-001)."""

    STORE_WITH_RETENTION = "store_with_retention"
    NO_STORE = "no_store"


class Route(str, Enum):
    """Route categories plus retained V2 historical compatibility values.

    ``LOCAL_CONVERSATION`` and ``REGISTERED_CAPABILITY`` are the generic V2.5
    categories. The capability-specific values remain readable for stored V2
    tasks and existing interface clients, but no new capability identity should
    be encoded only in one of those historical members.
    """

    LOCAL_GENERALIST = "local_generalist"
    LOCAL_CONVERSATION = "local_conversation"
    REGISTERED_CAPABILITY = "registered_capability"
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
    CATALOG_NO_MATCH = "CATALOG_NO_MATCH"
    CATALOG_SINGLE_MATCH = "CATALOG_SINGLE_MATCH"
    CATALOG_AMBIGUOUS = "CATALOG_AMBIGUOUS"
    REQUIRED_ENTITY_MISSING = "REQUIRED_ENTITY_MISSING"
    FRESHNESS_UNSUPPORTED = "FRESHNESS_UNSUPPORTED"
    OPERATION_UNSUPPORTED = "OPERATION_UNSUPPORTED"
    ACTION_UNSUPPORTED = "ACTION_UNSUPPORTED"
    SELECTION_PROPOSAL_REJECTED = "SELECTION_PROPOSAL_REJECTED"


class PresentationMode(str, Enum):
    """Application-owned policy for presenting validated workflow output.

    This is deliberately separate from the legacy V3 ``FinalizationStrategy``.
    A planner may propose work, but it cannot select or bypass the final
    conversational presentation policy.
    """

    COMPOSED = "composed"
    EXACT_WITH_COMPOSED_CONTEXT = "exact_with_composed_context"
    DETERMINISTIC_ONLY = "deterministic_only"


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

    The full lifecycle vocabulary is fixed here. Runtime transitions are guarded
    by ``state_machine.py`` and preserve separate partial, blocked, failed, and
    cancelled outcomes.
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

    The complete taxonomy is declared so audit and error contracts remain stable
    across capabilities and persisted traces.
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
    """Dependency health for OPS-002 `/status`."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"
