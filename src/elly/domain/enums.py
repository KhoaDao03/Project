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


class TaskStatus(str, Enum):
    """Execution outcome of a task (DESIGN §2.3, §5.4).

    The full lifecycle vocabulary is fixed here. M1 only drives a subset
    (queued -> running -> completed | failed | blocked); AWAITING_CONSENT (M5),
    CANCELLED (M2/M3), and PARTIAL (M3/M4) are reserved and unreachable in M1.
    """

    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_CONSENT = "awaiting_consent"
    COMPLETED = "completed"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    FAILED = "failed"
    BLOCKED = "blocked"


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


class HealthState(str, Enum):
    """Dependency health for OPS-002 `/status` (initial in M1)."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"
