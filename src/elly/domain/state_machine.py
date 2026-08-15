"""Task lifecycle state machine (DESIGN §5.4).

Responsibility: define and enforce the ALLOWED task-status transitions so the
orchestrator cannot drive a task into an illegal state (e.g., completed -> running
or a false success after failure). This is deterministic domain logic with no I/O.

Status: Implemented + Tested (M1). Used by `ConversationOrchestrator.handle`, which
drives the M1 transitions QUEUED->RUNNING->(COMPLETED|BLOCKED) through
`ensure_transition`. Later milestones drive the remaining edges (AWAITING_CONSENT
in M5, CANCELLED/PARTIAL in M2/M3).

Requirements: AI-002 (deterministic control), FR-006 (no false success).
Non-responsibilities: does not perform the work of a state; only guards moves.
"""

from __future__ import annotations

from .enums import ErrorClass, TaskStatus
from .errors import EllyError

# Allowed forward transitions. Mirrors the DESIGN §5.4 diagram. AWAITING_CONSENT,
# CANCELLED, and PARTIAL edges exist in the contract but are unreachable in M1.
_ALLOWED: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.QUEUED: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED}),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.AWAITING_CONSENT,
            TaskStatus.COMPLETED,
            TaskStatus.PARTIAL,
            TaskStatus.CANCELLED,
            TaskStatus.FAILED,
            TaskStatus.BLOCKED,
        }
    ),
    TaskStatus.AWAITING_CONSENT: frozenset({TaskStatus.RUNNING, TaskStatus.BLOCKED}),
    # Terminal states have no outgoing transitions.
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.PARTIAL: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.BLOCKED: frozenset(),
}

TERMINAL: frozenset[TaskStatus] = frozenset(
    s for s, nexts in _ALLOWED.items() if not nexts
)


class IllegalTransitionError(EllyError):
    """Raised when code attempts a disallowed task-status transition."""

    error_class = ErrorClass.CONFIG_INVALID


def can_transition(current: TaskStatus, target: TaskStatus) -> bool:
    """Return True iff `current -> target` is an allowed transition."""
    return target in _ALLOWED.get(current, frozenset())


def ensure_transition(current: TaskStatus, target: TaskStatus) -> TaskStatus:
    """Return `target` if the transition is legal, else raise IllegalTransitionError."""
    if not can_transition(current, target):
        raise IllegalTransitionError(f"illegal transition {current.value} -> {target.value}")
    return target


def is_terminal(status: TaskStatus) -> bool:
    """Return True iff `status` is a terminal state."""
    return status in TERMINAL
