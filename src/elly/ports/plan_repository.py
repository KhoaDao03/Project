"""Persistence port for validated V3 execution plans."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ..domain.models import TaskResult
from ..planning.contracts import (
    AuthorizationState,
    ExecutionPlan,
    FinalizationStrategy,
    PlanStatus,
    StepState,
)

if TYPE_CHECKING:
    from ..application.results.step import StepResultEnvelope


@dataclass(frozen=True, slots=True)
class PlanEvent:
    """Safe, bounded provenance for one plan or step transition."""

    plan_id: str
    event_type: str
    reason_code: str
    detail: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SynthesisResultRecord:
    """Retained, provider-neutral synthesis validation/presentation record."""

    plan_id: str
    strategy: FinalizationStrategy
    validation_state: str
    referenced_result_ids: tuple[str, ...]
    output: Mapping[str, object]
    created_at: datetime
    updated_at: datetime


@runtime_checkable
class PlanRepositoryPort(Protocol):
    """Atomic storage contract used after pure plan validation."""

    def save_plan(self, plan: ExecutionPlan, *, at: datetime | None = None) -> None:
        """Persist a complete plan, its steps, and dependency edges atomically."""
        ...

    def get_plan(self, plan_id: str) -> ExecutionPlan | None:
        """Return one immutable plan with its validated graph, if present."""
        ...

    def list_plans_for_task(self, task_id: str) -> tuple[ExecutionPlan, ...]:
        """Return plan revisions in deterministic revision/identity order."""
        ...

    def list_nonterminal_plans(self) -> tuple[ExecutionPlan, ...]:
        """Return pending/running plans that require startup reconciliation."""
        ...

    def delete_plans_for_task(self, task_id: str) -> int:
        """Delete all plan revisions associated with one task atomically."""
        ...

    def transition_plan(
        self,
        plan_id: str,
        status: PlanStatus,
        *,
        expected_status: PlanStatus | None = None,
        reason_code: str = "",
        at: datetime | None = None,
    ) -> ExecutionPlan:
        """Compare-and-set a plan status and return the updated plan."""
        ...

    def transition_step(
        self,
        plan_id: str,
        step_id: str,
        state: StepState,
        *,
        expected_state: StepState | None = None,
        authorization_state: AuthorizationState | None = None,
        reason_code: str = "",
        at: datetime | None = None,
    ) -> ExecutionPlan:
        """Compare-and-set one step state and return the updated plan."""
        ...

    def reconcile_plan(
        self,
        plan_id: str,
        status: PlanStatus,
        *,
        expected_status: PlanStatus | None = None,
        reason_code: str = "",
        at: datetime | None = None,
    ) -> ExecutionPlan:
        """Apply a crash-recovery status without treating it as normal flow."""
        ...

    def reconcile_step(
        self,
        plan_id: str,
        step_id: str,
        state: StepState,
        *,
        expected_state: StepState | None = None,
        reason_code: str = "",
        at: datetime | None = None,
    ) -> ExecutionPlan:
        """Apply a crash-recovery step state without replaying external work."""
        ...

    def save_step_result(
        self,
        plan_id: str,
        step_id: str,
        result: TaskResult,
        *,
        retained: bool = True,
        at: datetime | None = None,
    ) -> None:
        """Persist one normalized result for a validated plan step."""
        ...

    def save_step_envelope(
        self,
        plan_id: str,
        step_id: str,
        envelope: StepResultEnvelope,
        *,
        retained: bool = True,
        at: datetime | None = None,
    ) -> None:
        """Persist the versioned result envelope for one plan step."""
        ...

    def get_step_result(self, plan_id: str, step_id: str) -> TaskResult | None:
        """Return a persisted step result, if one exists."""
        ...

    def get_step_envelope(self, plan_id: str, step_id: str) -> StepResultEnvelope | None:
        """Return a persisted versioned result envelope, if present."""
        ...

    def append_plan_event(
        self,
        plan_id: str,
        event_type: str,
        reason_code: str,
        detail: str = "",
        *,
        at: datetime | None = None,
    ) -> None:
        """Append safe plan provenance without payload or prompt bodies."""
        ...

    def plan_events(self, plan_id: str) -> tuple[PlanEvent, ...]:
        """Read plan transition provenance in insertion order."""
        ...

    def save_synthesis_result(
        self,
        plan_id: str,
        strategy: FinalizationStrategy,
        validation_state: str,
        referenced_result_ids: tuple[str, ...],
        output: Mapping[str, object],
        *,
        at: datetime | None = None,
    ) -> None:
        """Persist the bounded synthesis validation state and presentation."""
        ...

    def get_synthesis_result(self, plan_id: str) -> SynthesisResultRecord | None:
        """Read one retained synthesis record, if one exists."""
        ...


__all__ = ["PlanEvent", "PlanRepositoryPort", "SynthesisResultRecord"]
