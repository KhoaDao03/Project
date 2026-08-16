"""Pure execution-plan state transition rules.

Phase 3 persists the state fields on plans and steps.  This module gives Phase
4 one small, provider-free authority for deciding which persisted transitions
are legal.  Storage adapters use the same rules as the scheduler so a stale
worker cannot silently overwrite a newer step state.
"""

from __future__ import annotations

from ..domain.errors import ConflictError
from ..planning.contracts import PlanStatus, StepState

STEP_TERMINAL_STATES = frozenset(
    {
        StepState.COMPLETED,
        StepState.PARTIAL,
        StepState.FAILED,
        StepState.BLOCKED,
        StepState.UNAVAILABLE,
        StepState.CANCELLED,
        StepState.SKIPPED,
        StepState.INTERRUPTED,
    }
)
STEP_ELIGIBLE_STATES = frozenset({StepState.COMPLETED, StepState.PARTIAL})

_STEP_TRANSITIONS: dict[StepState, frozenset[StepState]] = {
    StepState.PENDING: frozenset(
        {
            StepState.READY,
            StepState.BLOCKED,
            StepState.SKIPPED,
            StepState.CANCELLED,
            StepState.INTERRUPTED,
        }
    ),
    StepState.READY: frozenset(
        {
            StepState.AUTHORIZING,
            StepState.BLOCKED,
            StepState.SKIPPED,
            StepState.CANCELLED,
            StepState.INTERRUPTED,
        }
    ),
    StepState.AUTHORIZING: frozenset(
        {
            StepState.RUNNING,
            StepState.BLOCKED,
            StepState.UNAVAILABLE,
            StepState.FAILED,
            StepState.CANCELLED,
            StepState.INTERRUPTED,
        }
    ),
    StepState.RUNNING: frozenset(
        {
            StepState.COMPLETED,
            StepState.PARTIAL,
            StepState.FAILED,
            StepState.BLOCKED,
            StepState.UNAVAILABLE,
            StepState.CANCELLED,
            StepState.INTERRUPTED,
        }
    ),
    StepState.COMPLETED: frozenset(),
    StepState.PARTIAL: frozenset(),
    StepState.FAILED: frozenset(),
    # A blocked step may be resumed only by the application-owned exact
    # authorization workflow. The scheduler never takes this edge itself.
    StepState.BLOCKED: frozenset({StepState.PENDING}),
    StepState.UNAVAILABLE: frozenset(),
    StepState.CANCELLED: frozenset(),
    StepState.SKIPPED: frozenset(),
    StepState.INTERRUPTED: frozenset(),
}

_PLAN_TRANSITIONS: dict[PlanStatus, frozenset[PlanStatus]] = {
    PlanStatus.PENDING: frozenset(
        {
            PlanStatus.RUNNING,
            PlanStatus.COMPLETED,
            PlanStatus.PARTIAL,
            PlanStatus.BLOCKED,
            PlanStatus.FAILED,
            PlanStatus.UNAVAILABLE,
            PlanStatus.CANCELLED,
            PlanStatus.INTERRUPTED,
        }
    ),
    PlanStatus.RUNNING: frozenset(
        {
            PlanStatus.COMPLETED,
            PlanStatus.PARTIAL,
            PlanStatus.BLOCKED,
            PlanStatus.FAILED,
            PlanStatus.UNAVAILABLE,
            PlanStatus.CANCELLED,
            PlanStatus.INTERRUPTED,
        }
    ),
    PlanStatus.COMPLETED: frozenset(),
    PlanStatus.PARTIAL: frozenset(),
    # Same-revision authorization resume is an explicit application action,
    # not replanning or a provider-controlled retry.
    PlanStatus.BLOCKED: frozenset({PlanStatus.PENDING}),
    PlanStatus.FAILED: frozenset(),
    PlanStatus.UNAVAILABLE: frozenset(),
    PlanStatus.CANCELLED: frozenset(),
    PlanStatus.INTERRUPTED: frozenset(),
}


def can_transition_step(current: StepState, target: StepState) -> bool:
    """Return whether one step state may move to another state."""

    return target in _STEP_TRANSITIONS.get(current, frozenset())


def ensure_step_transition(current: StepState, target: StepState) -> StepState:
    """Return ``target`` or raise a typed conflict for an illegal move."""

    if not can_transition_step(current, target):
        raise ConflictError(f"illegal plan step transition {current.value} -> {target.value}")
    return target


def can_transition_plan(current: PlanStatus, target: PlanStatus) -> bool:
    """Return whether a persisted plan status may move to another status."""

    return target in _PLAN_TRANSITIONS.get(current, frozenset())


def ensure_plan_transition(current: PlanStatus, target: PlanStatus) -> PlanStatus:
    """Return ``target`` or raise a typed conflict for an illegal move."""

    if not can_transition_plan(current, target):
        raise ConflictError(f"illegal execution plan transition {current.value} -> {target.value}")
    return target


__all__ = [
    "STEP_ELIGIBLE_STATES",
    "STEP_TERMINAL_STATES",
    "can_transition_plan",
    "can_transition_step",
    "ensure_plan_transition",
    "ensure_step_transition",
]
