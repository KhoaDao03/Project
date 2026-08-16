"""Public V2 application request, response, and view contracts.

The DTOs in this module deliberately contain only immutable public data. They
do not expose repositories, provider objects, exceptions, mutable services, or
database rows. Conversion from internal models happens in ``api.application``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Generic, TypeVar

from ..domain.enums import (
    ActionCategory,
    ActionDataSensitivity,
    ActionImpactFlag,
    ActionReversibility,
    ActionSideEffect,
    CloudMode,
    EpistemicStatus,
    HealthState,
    OutcomeCode,
    PersistenceMode,
    Route,
    TaskStatus,
    ValidationStatus,
)
from ..planning.contracts import FinalizationStrategy, PlanStatus, StepCriticality, StepState

T = TypeVar("T")
IntentValue = str | int | float | bool | None
API_VERSION = "v2"


class ApiFailureCode(str, Enum):
    """Stable public application failure vocabulary."""

    INVALID_INPUT = "INVALID_INPUT"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    BLOCKED = "BLOCKED"
    UNAVAILABLE = "UNAVAILABLE"
    CANCELLED = "CANCELLED"
    INTERNAL_FAILURE = "INTERNAL_FAILURE"


@dataclass(frozen=True, slots=True)
class ApiFailure:
    """Safe, transport-neutral application failure."""

    code: ApiFailureCode
    safe_message: str
    retryable: bool
    correlation_id: str


@dataclass(frozen=True, slots=True)
class ApiResult(Generic[T]):
    """Exactly one successful value or typed public failure."""

    value: T | None = None
    failure: ApiFailure | None = None

    def __post_init__(self) -> None:
        if (self.value is None) == (self.failure is None):
            raise ValueError("ApiResult must contain exactly one value or failure")

    @classmethod
    def success(cls, value: T) -> "ApiResult[T]":
        return cls(value=value)

    @classmethod
    def failed(cls, failure: ApiFailure) -> "ApiResult[T]":
        return cls(failure=failure)

    @property
    def is_success(self) -> bool:
        return self.failure is None


@dataclass(frozen=True, slots=True)
class SessionView:
    session_id: str
    persistence_mode: PersistenceMode
    cloud_mode: CloudMode
    created_at: datetime
    updated_at: datetime
    version: int


@dataclass(frozen=True, slots=True)
class CreateSessionRequest:
    persistence_mode: PersistenceMode = PersistenceMode.STORE_WITH_RETENTION
    cloud_mode: CloudMode = CloudMode.LOCAL_ONLY


@dataclass(frozen=True, slots=True)
class ChangeModeRequest:
    session_id: str
    expected_version: int
    cloud_mode: CloudMode
    actor_id: str = "owner"


@dataclass(frozen=True, slots=True)
class IntentEntityInput:
    kind: str
    value: str
    source: str = "explicit"


@dataclass(frozen=True, slots=True)
class CapabilityIntentInput:
    proposed_capability_id: str | None
    operation: str
    entities: tuple[IntentEntityInput, ...] = ()
    arguments: tuple[tuple[str, IntentValue], ...] = ()
    confidence: float = 0.0
    ambiguity: str = "none_proposed"
    rationale_code: str = "PUBLIC_PROPOSAL"


@dataclass(frozen=True, slots=True)
class RouteProposalInput:
    route: Route | None = None
    capability_id: str | None = None
    request_schema: str = ""


@dataclass(frozen=True, slots=True)
class SubmitRequest:
    request_id: str
    session_id: str
    text: str
    route_proposal: RouteProposalInput | None = None
    approval_id: str | None = None
    capability_intent: CapabilityIntentInput | None = None
    action_confirmation_id: str | None = None


@dataclass(frozen=True, slots=True)
class TaskAccepted:
    task_id: str
    request_id: str
    session_id: str
    status: TaskStatus


@dataclass(frozen=True, slots=True)
class TaskView:
    task_id: str
    session_id: str
    status: TaskStatus
    outcome_code: OutcomeCode | None = None
    epistemic_status: EpistemicStatus | None = None
    validation_status: ValidationStatus | None = None
    route: Route | None = None
    answer: str = ""
    failures: tuple[str, ...] = ()
    partial_work: tuple[str, ...] = ()
    next_actions: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    action_confirmation: "ActionConfirmationView | None" = None
    # Additive V2.5 routing metadata. ``route`` remains the historical/public
    # view for V2 clients; the category and selected identity are explicit.
    route_category: Route | None = None
    capability_id: str | None = None
    operation: str = ""
    selection_reason_code: str = ""
    routing_contract_version: str = ""
    candidate_count: int = 0
    rejected_candidate_reason_codes: tuple[str, ...] = ()
    clarification_required: bool = False
    freshness_affected_selection: bool = False
    # Additive V3 plan/result views. Existing V2/V2.5 fields remain the
    # compatibility surface for clients that do not request plan details.
    plan_id: str | None = None
    plan_status: PlanStatus | None = None
    plan: "PlanView | None" = None
    plan_result: "PlanResultView | None" = None


@dataclass(frozen=True, slots=True)
class PlanUsageView:
    """Safe provider-neutral usage metadata for one plan step."""

    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    provider_calls: int = 0
    cost_usd: float = 0.0


@dataclass(frozen=True, slots=True)
class PlanStepView:
    """Bounded public view of one validated plan step."""

    step_id: str
    capability_id: str
    operation: str
    dependencies: tuple[str, ...]
    state: StepState
    criticality: StepCriticality
    reason_code: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None
    usage: PlanUsageView | None = None
    result_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DisagreementView:
    """Public, non-resolving view of conflicting specialist findings."""

    disagreement_id: str
    claim_id: str
    source_kind: str
    step_ids: tuple[str, ...]
    statements: tuple[str, ...]
    evidence_ids: tuple[str, ...] = ()
    reason_code: str = ""


@dataclass(frozen=True, slots=True)
class PlanSynthesisView:
    """Safe metadata for a retained local-synthesis record."""

    plan_id: str
    strategy: FinalizationStrategy
    validation_state: str
    referenced_result_ids: tuple[str, ...]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class PlanView:
    """Plan identity, status, finalization strategy, and bounded step views."""

    plan_id: str
    task_id: str
    revision: int
    status: PlanStatus
    finalization: FinalizationStrategy
    steps: tuple[PlanStepView, ...]
    parent_plan_id: str | None = None
    catalog_version: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    synthesis: PlanSynthesisView | None = None


@dataclass(frozen=True, slots=True)
class PlanResultView:
    """Additive result summary that retains plan status and conflicts."""

    plan_id: str
    task_id: str
    status: PlanStatus
    finalization: FinalizationStrategy
    answer: str = ""
    eligible_step_ids: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()
    disagreements: tuple[DisagreementView, ...] = ()


@dataclass(frozen=True, slots=True)
class PlanQuery:
    plan_id: str
    actor_id: str = "owner"


@dataclass(frozen=True, slots=True)
class PlanTraceQuery:
    plan_id: str
    actor_id: str = "owner"


@dataclass(frozen=True, slots=True)
class PlanTraceEventView:
    event_type: str
    reason_code: str
    detail: str
    at: datetime


@dataclass(frozen=True, slots=True)
class PlanTraceView:
    plan_id: str
    task_id: str
    events: tuple[PlanTraceEventView, ...]
    contributing_result_ids: tuple[str, ...] = ()
    contributing_evidence_ids: tuple[str, ...] = ()
    authorization_ids: tuple[str, ...] = ()
    revision: int = 0
    parent_plan_id: str | None = None
    lineage_plan_ids: tuple[str, ...] = ()
    replacement_plan_ids: tuple[str, ...] = ()
    synthesis_result_id: str | None = None


@dataclass(frozen=True, slots=True)
class ProfileView:
    item_id: str
    key: str
    value: str
    sensitivity: str
    confirmed: bool
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class ProfileQuery:
    actor_id: str = "owner"


class ProfileCommandKind(str, Enum):
    ADD = "add"
    CORRECT = "correct"
    DELETE = "delete"


@dataclass(frozen=True, slots=True)
class ProfileCommand:
    operation: ProfileCommandKind
    item_id: str
    key: str = ""
    value: str = ""
    sensitivity: str = "local"
    actor_id: str = "owner"


@dataclass(frozen=True, slots=True)
class HistoryQuery:
    session_id: str | None = None
    actor_id: str = "owner"


@dataclass(frozen=True, slots=True)
class HistoryView:
    sessions: tuple[SessionView, ...]


@dataclass(frozen=True, slots=True)
class TraceQuery:
    task_id: str
    actor_id: str = "owner"


@dataclass(frozen=True, slots=True)
class TraceEventView:
    event_type: str
    at: datetime
    route: Route | None
    task_status: TaskStatus | None
    error_class: str | None
    detail: str


@dataclass(frozen=True, slots=True)
class TraceView:
    task_id: str
    events: tuple[TraceEventView, ...]
    route_category: Route | None = None
    capability_id: str | None = None
    operation: str = ""
    selection_reason_code: str = ""
    routing_contract_version: str = ""
    candidate_count: int = 0
    rejected_candidate_reason_codes: tuple[str, ...] = ()
    clarification_required: bool = False
    freshness_affected_selection: bool = False


@dataclass(frozen=True, slots=True)
class SourcesQuery:
    task_id: str
    actor_id: str = "owner"


@dataclass(frozen=True, slots=True)
class SourcesView:
    task_id: str
    sources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConsentView:
    proposal_id: str
    task_id: str
    capability_id: str
    provider: str
    model: str
    purpose: str
    categories: tuple[str, ...]
    redacted_preview: str
    max_reserved_cost: float
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ConsentQuery:
    actor_id: str = "owner"


@dataclass(frozen=True, slots=True)
class ActionConfirmationView:
    """Redacted public view of one exact consequential-action approval."""

    confirmation_id: str
    task_id: str
    capability_id: str
    operation: str
    category: ActionCategory
    target_kind: str | None
    target_reference: str | None
    side_effect: ActionSideEffect
    reversibility: ActionReversibility
    data_sensitivity: ActionDataSensitivity
    impact_flags: tuple[ActionImpactFlag, ...]
    action_digest: str
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ConsentDecisionRequest:
    proposal_id: str
    approve: bool
    actor_id: str = "owner"


@dataclass(frozen=True, slots=True)
class ActionDecisionRequest:
    confirmation_id: str
    approve: bool
    actor_id: str = "owner"


@dataclass(frozen=True, slots=True)
class BackupRequest:
    destination: str
    actor_id: str = "owner"


@dataclass(frozen=True, slots=True)
class RestoreRequest:
    backup_path: str
    actor_id: str = "owner"


@dataclass(frozen=True, slots=True)
class BackupView:
    path: str
    restart_required: bool = False


@dataclass(frozen=True, slots=True)
class HealthView:
    component: str
    state: HealthState
    detail: str


@dataclass(frozen=True, slots=True)
class CapabilityStatusView:
    capability_id: str
    state: str
    reason: str


@dataclass(frozen=True, slots=True)
class LocalModelRoleView:
    """Effective non-secret configuration for one local-model role."""

    role: str
    profile_name: str
    provider: str
    model_id: str
    endpoint_host: str
    max_output_tokens: int
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class RuntimeStatusView:
    """Safe provider/model labels used by presentation status views."""

    generalist_provider: str
    generalist_model_id: str
    research_provider: str
    research_model_id: str
    specialist_provider: str
    specialist_model_id: str
    local_model_roles: tuple[LocalModelRoleView, ...] = ()


@dataclass(frozen=True, slots=True)
class LimitsStatusView:
    """Configured execution limits safe to expose to an interface."""

    max_steps: int
    max_provider_calls: int
    max_retries: int
    max_concurrency: int
    max_queue_size: int
    tool_timeout_seconds: float
    total_timeout_seconds: float


@dataclass(frozen=True, slots=True)
class PricingStatusView:
    """Configured reservation and budget ceilings, never provider secrets."""

    remote_call_reservation_usd: float
    consent_max_cost_usd: float
    monthly_budget_usd: float


@dataclass(frozen=True, slots=True)
class BudgetStatusView:
    """Current application-scoped cost ledger state."""

    reserved_usd: float
    remaining_usd: float
    warning_level: str


@dataclass(frozen=True, slots=True)
class ApplicationStatusView:
    health: tuple[HealthView, ...]
    capabilities: tuple[CapabilityStatusView, ...]
    runtime: RuntimeStatusView | None = None
    limits: LimitsStatusView | None = None
    pricing: PricingStatusView | None = None
    budget: BudgetStatusView | None = None
