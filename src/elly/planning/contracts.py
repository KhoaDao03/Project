"""Versioned, provider-neutral planning contracts.

The values in this module are data only.  They do not contain handlers,
providers, authorization decisions, prompts, or executable callbacks.  Planner
output is untrusted and must be validated again by application policy before it
can influence routing or execution.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import Enum

from ..domain.enums import ActionCategory
from ..domain.errors import InputInvalidError

PROPOSAL_SCHEMA_VERSION = "elly.execution-proposal.v1"
PLAN_SCHEMA_VERSION = "elly.execution-plan.v1"
LOCAL_SYNTHESIS_CAPABILITY_ID = "local_synthesis"
LOCAL_SYNTHESIS_OPERATION_ID = "synthesis.compose"
COMPILED_MAX_REPLANNING_ATTEMPTS = 1
MAX_PROPOSAL_STEPS = 8
MAX_PROPOSAL_INPUTS = 16
MAX_PROPOSAL_DEPENDENCIES = 8
MAX_PROPOSAL_AMBIGUITIES = 8
MAX_PROPOSAL_BYTES = 32_768
MAX_PROPOSAL_TEXT = 512
MAX_PROPOSAL_JUSTIFICATION = 240
PROPOSED_INPUT_SOURCES = frozenset({"request", "context", "step"})

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_SAFE_CODE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")


class ProposalDisposition(str, Enum):
    """Safe high-level outcome proposed by the local planner."""

    LOCAL_ONLY = "local_only"
    CAPABILITY_PLAN = "capability_plan"
    CLARIFICATION_REQUIRED = "clarification_required"
    UNABLE = "unable"


class FinalizationStrategy(str, Enum):
    """Deterministic presentation strategy selected for a plan."""

    DIRECT = "direct"
    TEMPLATE = "template"
    LOCAL_SYNTHESIS = "local_synthesis"


class StepKind(str, Enum):
    """Kinds of nodes that may appear in a validated execution plan."""

    CAPABILITY = "capability"
    LOCAL_SYNTHESIS = "local_synthesis"


class StepCriticality(str, Enum):
    """Whether a step is required for the plan to produce its intended result."""

    REQUIRED = "required"
    OPTIONAL = "optional"


class PlanStatus(str, Enum):
    """Reserved plan-level status vocabulary for later execution phases."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class StepState(str, Enum):
    """Reserved step-state vocabulary for the Phase 4 scheduler."""

    PENDING = "pending"
    READY = "ready"
    AUTHORIZING = "authorizing"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    BLOCKED = "blocked"
    UNAVAILABLE = "unavailable"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    INTERRUPTED = "interrupted"


class AuthorizationState(str, Enum):
    """Application-owned authorization state persisted for each plan step."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    NOT_REQUIRED = "not_required"


def _text(value: object, name: str, *, maximum: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise InputInvalidError(f"{name} must be text")
    if len(value) > maximum or "\n" in value or "\r" in value:
        raise InputInvalidError(f"{name} exceeds its safe bound")
    normalized = value.strip()
    if not allow_empty and not normalized:
        raise InputInvalidError(f"{name} must be non-empty")
    return normalized


def _identifier(value: object, name: str) -> str:
    normalized = _text(value, name, maximum=64)
    if _IDENTIFIER.fullmatch(normalized) is None:
        raise InputInvalidError(f"{name} has an invalid format")
    return normalized


def _code(value: object, name: str) -> str:
    normalized = _text(value, name, maximum=64)
    if _SAFE_CODE.fullmatch(normalized) is None:
        raise InputInvalidError(f"{name} has an invalid format")
    return normalized


def _tuple_of(
    value: object,
    name: str,
    item_type: type[object],
    maximum: int,
) -> tuple[object, ...]:
    if not isinstance(value, tuple):
        raise InputInvalidError(f"{name} must be an immutable tuple")
    if len(value) > maximum:
        raise InputInvalidError(f"{name} exceeds its item limit")
    if any(not isinstance(item, item_type) for item in value):
        raise InputInvalidError(f"{name} contains an invalid item")
    return value


@dataclass(frozen=True, slots=True)
class ProposedInput:
    """A typed input reference proposed for one capability step.

    ``reference`` is an identifier or safe metadata reference only; it is never
    a raw payload supplied by the planner.
    """

    name: str
    value_type: str
    source: str = "request"
    reference: str = ""
    required: bool = True

    def __post_init__(self) -> None:
        _identifier(self.name, "proposed input name")
        _identifier(self.value_type, "proposed input value_type")
        _code(self.source, "proposed input source")
        if self.source not in PROPOSED_INPUT_SOURCES:
            raise InputInvalidError("proposed input source is not allowed")
        _text(self.reference, "proposed input reference", maximum=128, allow_empty=True)
        if not isinstance(self.required, bool):
            raise InputInvalidError("proposed input required must be a bool")
        if self.source == "step" and not self.reference.strip():
            raise InputInvalidError("step input references must name a prior step")


# The plan contract uses the same immutable shape after proposal validation.
InputBinding = ProposedInput


@dataclass(frozen=True, slots=True)
class ClarificationField:
    """A bounded field that must be supplied before safe planning can continue."""

    field_id: str
    reason_code: str
    question: str = ""
    required: bool = True

    def __post_init__(self) -> None:
        _code(self.field_id, "clarification field_id")
        _code(self.reason_code, "clarification reason_code")
        _text(self.question, "clarification question", maximum=MAX_PROPOSAL_TEXT, allow_empty=True)
        if not isinstance(self.required, bool):
            raise InputInvalidError("clarification required must be a bool")


@dataclass(frozen=True, slots=True)
class ProposedStep:
    """One untrusted capability proposal with no provider identity."""

    proposal_step_id: str
    capability_id: str
    operation_id: str
    objective: str
    objective_class: str
    perspective: str
    inputs: tuple[ProposedInput, ...] = ()
    dependencies: tuple[str, ...] = ()
    expected_output_type: str = "task_result"
    required: bool = True
    verification: bool = False
    requires_current_information: bool = False
    requires_external_access: bool = False

    def __post_init__(self) -> None:
        _identifier(self.proposal_step_id, "proposal step_id")
        _identifier(self.capability_id, "proposal capability_id")
        _identifier(self.operation_id, "proposal operation_id")
        _text(self.objective, "proposal objective", maximum=MAX_PROPOSAL_TEXT)
        _code(self.objective_class, "proposal objective_class")
        _code(self.perspective, "proposal perspective")
        _tuple_of(self.inputs, "proposal inputs", ProposedInput, MAX_PROPOSAL_INPUTS)
        input_names = tuple(item.name for item in self.inputs)
        if len(set(input_names)) != len(input_names):
            raise InputInvalidError("proposal input names must be unique per step")
        _tuple_of(self.dependencies, "proposal dependencies", str, MAX_PROPOSAL_DEPENDENCIES)
        for dependency in self.dependencies:
            _identifier(dependency, "proposal dependency")
        if self.proposal_step_id in self.dependencies:
            raise InputInvalidError("proposal step cannot depend on itself")
        _identifier(self.expected_output_type, "proposal expected_output_type")
        for value, name in (
            (self.required, "proposal required"),
            (self.verification, "proposal verification"),
            (self.requires_current_information, "proposal requires_current_information"),
            (self.requires_external_access, "proposal requires_external_access"),
        ):
            if not isinstance(value, bool):
                raise InputInvalidError(f"{name} must be a bool")


@dataclass(frozen=True, slots=True)
class ExecutionProposal:
    """Versioned, immutable planner output awaiting deterministic validation."""

    schema_version: str
    disposition: ProposalDisposition
    steps: tuple[ProposedStep, ...]
    finalization: FinalizationStrategy
    ambiguities: tuple[ClarificationField, ...]
    confidence: float
    reason_code: str
    justification: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != PROPOSAL_SCHEMA_VERSION:
            raise InputInvalidError("unsupported execution proposal schema version")
        if not isinstance(self.disposition, ProposalDisposition):
            raise InputInvalidError("proposal disposition is invalid")
        _tuple_of(self.steps, "proposal steps", ProposedStep, MAX_PROPOSAL_STEPS)
        step_ids = tuple(step.proposal_step_id for step in self.steps)
        if len(set(step_ids)) != len(step_ids):
            raise InputInvalidError("proposal step IDs must be unique")
        step_id_set = set(step_ids)
        for step in self.steps:
            if any(dependency not in step_id_set for dependency in step.dependencies):
                raise InputInvalidError("proposal dependency references an unknown step")
        if not isinstance(self.finalization, FinalizationStrategy):
            raise InputInvalidError("proposal finalization is invalid")
        _tuple_of(
            self.ambiguities,
            "proposal ambiguities",
            ClarificationField,
            MAX_PROPOSAL_AMBIGUITIES,
        )
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)):
            raise InputInvalidError("proposal confidence must be numeric")
        if not math.isfinite(float(self.confidence)) or not 0 <= self.confidence <= 1:
            raise InputInvalidError("proposal confidence must be between 0 and 1")
        _code(self.reason_code, "proposal reason_code")
        _text(
            self.justification,
            "proposal justification",
            maximum=MAX_PROPOSAL_JUSTIFICATION,
            allow_empty=True,
        )
        if self.disposition is ProposalDisposition.CAPABILITY_PLAN and not self.steps:
            raise InputInvalidError("capability proposal must contain at least one step")
        if self.disposition is ProposalDisposition.CLARIFICATION_REQUIRED:
            if self.steps:
                raise InputInvalidError("clarification proposal cannot contain executable steps")
            if not self.ambiguities:
                raise InputInvalidError("clarification proposal must name missing fields")
        if (
            self.disposition
            in {
                ProposalDisposition.LOCAL_ONLY,
                ProposalDisposition.UNABLE,
            }
            and self.steps
        ):
            raise InputInvalidError("non-executable proposal cannot contain steps")
        if self.disposition is not ProposalDisposition.CAPABILITY_PLAN and (
            self.finalization is FinalizationStrategy.LOCAL_SYNTHESIS
        ):
            raise InputInvalidError("local synthesis requires a capability plan")


@dataclass(frozen=True, slots=True)
class PlanLimitsSnapshot:
    """Immutable execution ceilings captured when a plan is validated."""

    max_plan_steps: int = 5
    max_specialist_executions: int = 2
    max_research_executions: int = 1
    max_synthesis_executions: int = 1
    max_provider_calls: int = 3
    max_concurrency: int = 2
    max_replanning_attempts: int = 1
    max_parallel_steps: int = 2
    max_step_timeout_seconds: float = 60.0
    max_total_timeout_seconds: float = 180.0

    def __post_init__(self) -> None:
        for value, name in (
            (self.max_plan_steps, "max_plan_steps"),
            (self.max_specialist_executions, "max_specialist_executions"),
            (self.max_research_executions, "max_research_executions"),
            (self.max_synthesis_executions, "max_synthesis_executions"),
            (self.max_provider_calls, "max_provider_calls"),
            (self.max_concurrency, "max_concurrency"),
            (self.max_replanning_attempts, "max_replanning_attempts"),
            (self.max_parallel_steps, "max_parallel_steps"),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise InputInvalidError(f"{name} must be an integer")
            if name in {"max_plan_steps", "max_concurrency", "max_parallel_steps"}:
                valid = value > 0
            else:
                valid = value >= 0
            if not valid:
                raise InputInvalidError(
                    f"{name} must be {'positive' if name in {'max_plan_steps', 'max_concurrency', 'max_parallel_steps'} else 'non-negative'}"
                )
        for timeout_value, timeout_name in (
            (self.max_step_timeout_seconds, "max_step_timeout_seconds"),
            (self.max_total_timeout_seconds, "max_total_timeout_seconds"),
        ):
            if isinstance(timeout_value, bool) or not isinstance(timeout_value, (int, float)):
                raise InputInvalidError(f"{timeout_name} must be numeric")
            if not math.isfinite(float(timeout_value)) or timeout_value <= 0:
                raise InputInvalidError(f"{timeout_name} must be positive and finite")


@dataclass(frozen=True, slots=True)
class PlanStep:
    """Provider-neutral step shape reserved for Phase 3 plan construction."""

    step_id: str
    kind: StepKind
    capability_id: str
    operation_id: str
    objective: str
    objective_class: str
    perspective: str
    inputs: tuple[InputBinding, ...]
    dependencies: tuple[str, ...]
    output_type: str
    criticality: StepCriticality
    verification: bool
    timeout_seconds: float
    requires_external_access: bool = False
    effect: ActionCategory = ActionCategory.NONE
    requires_consent: bool = False
    state: StepState = StepState.PENDING
    authorization_state: AuthorizationState = AuthorizationState.PENDING

    def __post_init__(self) -> None:
        _identifier(self.step_id, "plan step_id")
        if not isinstance(self.kind, StepKind):
            raise InputInvalidError("plan step kind is invalid")
        _identifier(self.capability_id, "plan capability_id")
        _identifier(self.operation_id, "plan operation_id")
        _text(self.objective, "plan objective", maximum=MAX_PROPOSAL_TEXT)
        _code(self.objective_class, "plan objective_class")
        _code(self.perspective, "plan perspective")
        _tuple_of(self.inputs, "plan inputs", ProposedInput, MAX_PROPOSAL_INPUTS)
        _tuple_of(self.dependencies, "plan dependencies", str, MAX_PROPOSAL_DEPENDENCIES)
        for dependency in self.dependencies:
            _identifier(dependency, "plan dependency")
        if self.step_id in self.dependencies:
            raise InputInvalidError("plan step cannot depend on itself")
        _identifier(self.output_type, "plan output_type")
        if not isinstance(self.criticality, StepCriticality):
            raise InputInvalidError("plan step criticality is invalid")
        if not isinstance(self.verification, bool):
            raise InputInvalidError("plan step verification must be a bool")
        if isinstance(self.timeout_seconds, bool) or not isinstance(
            self.timeout_seconds, (int, float)
        ):
            raise InputInvalidError("plan step timeout must be numeric")
        if not math.isfinite(float(self.timeout_seconds)) or self.timeout_seconds <= 0:
            raise InputInvalidError("plan step timeout must be positive and finite")
        if not isinstance(self.requires_external_access, bool):
            raise InputInvalidError("plan step requires_external_access must be a bool")
        if not isinstance(self.effect, ActionCategory):
            raise InputInvalidError("plan step effect is invalid")
        if not isinstance(self.requires_consent, bool):
            raise InputInvalidError("plan step requires_consent must be a bool")
        if not isinstance(self.state, StepState):
            raise InputInvalidError("plan step state is invalid")
        if not isinstance(self.authorization_state, AuthorizationState):
            raise InputInvalidError("plan step authorization_state is invalid")


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    """Immutable validated-plan envelope used by later phases."""

    plan_id: str
    task_id: str
    schema_version: str
    revision: int
    parent_plan_id: str | None
    steps: tuple[PlanStep, ...]
    finalization: FinalizationStrategy
    limits: PlanLimitsSnapshot
    catalog_version: str
    status: PlanStatus = PlanStatus.PENDING

    def __post_init__(self) -> None:
        _identifier(self.plan_id, "plan_id")
        _identifier(self.task_id, "task_id")
        if self.schema_version != PLAN_SCHEMA_VERSION:
            raise InputInvalidError("unsupported execution plan schema version")
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 0
        ):
            raise InputInvalidError("plan revision must be a non-negative integer")
        if self.parent_plan_id is not None:
            _identifier(self.parent_plan_id, "parent_plan_id")
        _tuple_of(self.steps, "plan steps", PlanStep, 64)
        step_ids = tuple(step.step_id for step in self.steps)
        if len(set(step_ids)) != len(step_ids):
            raise InputInvalidError("plan step IDs must be unique")
        if any(
            dependency not in set(step_ids)
            for step in self.steps
            for dependency in step.dependencies
        ):
            raise InputInvalidError("plan dependency references an unknown step")
        if not isinstance(self.finalization, FinalizationStrategy):
            raise InputInvalidError("plan finalization is invalid")
        if not isinstance(self.limits, PlanLimitsSnapshot):
            raise InputInvalidError("plan limits snapshot is invalid")
        _identifier(self.catalog_version, "catalog_version")
        if not isinstance(self.status, PlanStatus):
            raise InputInvalidError("plan status is invalid")


__all__ = [
    "ClarificationField",
    "AuthorizationState",
    "COMPILED_MAX_REPLANNING_ATTEMPTS",
    "ExecutionPlan",
    "ExecutionProposal",
    "FinalizationStrategy",
    "InputBinding",
    "LOCAL_SYNTHESIS_CAPABILITY_ID",
    "LOCAL_SYNTHESIS_OPERATION_ID",
    "MAX_PROPOSAL_AMBIGUITIES",
    "MAX_PROPOSAL_BYTES",
    "MAX_PROPOSAL_DEPENDENCIES",
    "MAX_PROPOSAL_INPUTS",
    "MAX_PROPOSAL_STEPS",
    "PLAN_SCHEMA_VERSION",
    "PlanLimitsSnapshot",
    "PlanStatus",
    "PlanStep",
    "PROPOSAL_SCHEMA_VERSION",
    "PROPOSED_INPUT_SOURCES",
    "ProposalDisposition",
    "ProposedInput",
    "ProposedStep",
    "StepCriticality",
    "StepKind",
    "StepState",
]
