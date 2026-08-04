"""Response composer (PAIR work, M1) — builds the user-facing TaskResult.

Responsibility: turn validated generalist text + routing/status decisions into the
frozen three-axis TaskResult (DESIGN §6.2). Keeps composition in one tested place
so the orchestrator stays focused on sequencing.

M1 mapping rules:
- successful validated local answer -> task COMPLETED, epistemic KNOWN? No:
  a bare conversational reply is not an evidence-backed factual claim, so M1 maps
  ordinary local answers to epistemic INFERRED (reasoned, not evidence-verified),
  reserving KNOWN for evidence-backed research (M4). This is a conservative,
  reviewable default — OWNER REVIEW invited (see M1 status doc).
- rejected/empty output -> task BLOCKED, epistemic BLOCKED, validation REJECTED.

Non-responsibilities: does not persist, does not decide routing.
"""

from __future__ import annotations

from ..domain.enums import (
    EpistemicStatus,
    Route,
    TaskStatus,
    ValidationStatus,
)
from ..domain.models import TaskResult


def compose_success(*, task_id: str, answer: str) -> TaskResult:
    """Compose a COMPLETED local conversational result."""
    return TaskResult(
        task_id=task_id,
        task_status=TaskStatus.COMPLETED,
        epistemic_status=EpistemicStatus.INFERRED,
        validation_status=ValidationStatus.VALIDATED,
        answer=answer,
        route_summary=Route.LOCAL_GENERALIST,
    )


def compose_blocked(*, task_id: str, reason: str) -> TaskResult:
    """Compose a BLOCKED result carrying a safe, non-sensitive reason."""
    return TaskResult(
        task_id=task_id,
        task_status=TaskStatus.BLOCKED,
        epistemic_status=EpistemicStatus.BLOCKED,
        validation_status=ValidationStatus.REJECTED,
        answer="",
        route_summary=Route.LOCAL_GENERALIST,
        failures=(reason,),
        next_actions=("retry", "check /status"),
    )
