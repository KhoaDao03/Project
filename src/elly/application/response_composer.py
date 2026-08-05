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


def compose_success(*, task_id: str, answer: str, route: Route = Route.LOCAL_GENERALIST) -> TaskResult:
    """Compose a COMPLETED local conversational result."""
    return TaskResult(
        task_id=task_id,
        task_status=TaskStatus.COMPLETED,
        epistemic_status=EpistemicStatus.INFERRED,
        validation_status=ValidationStatus.VALIDATED,
        answer=answer,
        route_summary=route,
    )


def compose_blocked(*, task_id: str, reason: str, route: Route = Route.LOCAL_GENERALIST) -> TaskResult:
    """Compose a BLOCKED result carrying a safe, non-sensitive reason."""
    return TaskResult(
        task_id=task_id,
        task_status=TaskStatus.BLOCKED,
        epistemic_status=EpistemicStatus.BLOCKED,
        validation_status=ValidationStatus.REJECTED,
        answer="",
        route_summary=route,
        failures=(reason,),
        next_actions=("retry", "check /status"),
    )


def compose_cancelled(*, task_id: str, partial_work: str = "", route: Route = Route.LOCAL_GENERALIST) -> TaskResult:
    """Compose an honest owner-cancelled result with no fabricated answer."""
    return TaskResult(
        task_id=task_id,
        task_status=TaskStatus.CANCELLED,
        epistemic_status=EpistemicStatus.BLOCKED,
        validation_status=ValidationStatus.REJECTED,
        answer="",
        route_summary=route,
        partial_work=(partial_work,) if partial_work else (),
        failures=("local generation cancelled",),
        next_actions=("submit a new request",),
    )


def compose_research(*, task_id: str, answer: str, citations: tuple[str, ...], claims: tuple[str, ...],
                     epistemic: EpistemicStatus, validation: ValidationStatus = ValidationStatus.QUALIFIED) -> TaskResult:
    """Compose a research result whose sources were validated by the application."""
    return TaskResult(
        task_id=task_id, task_status=TaskStatus.COMPLETED, epistemic_status=epistemic,
        validation_status=validation, answer=answer, route_summary=Route.WEB_RESEARCH,
        claims=claims, citations=citations,
    )


def compose_specialist(*, task_id: str, answer: str, route: Route, epistemic: EpistemicStatus,
                       assumptions: tuple[str, ...] = (), uncertainties: tuple[str, ...] = (),
                       sources: tuple[str, ...] = (), partial: bool = False) -> TaskResult:
    return TaskResult(
        task_id=task_id, task_status=TaskStatus.PARTIAL if partial else TaskStatus.COMPLETED,
        epistemic_status=epistemic, validation_status=ValidationStatus.VALIDATED,
        answer=answer, route_summary=route, citations=sources,
        claims=assumptions, next_actions=uncertainties,
    )


def compose_consent_required(*, task_id: str, proposal, route: Route) -> TaskResult:
    """Render every material field of an exact cloud-disclosure proposal."""
    return TaskResult(
        task_id=task_id, task_status=TaskStatus.AWAITING_CONSENT,
        epistemic_status=EpistemicStatus.BLOCKED, validation_status=ValidationStatus.QUALIFIED,
        answer=(
            "Consent required before sending this payload. "
            f"Proposal: {proposal.proposal_id}; provider={proposal.provider}; model={proposal.model}; "
            f"purpose={proposal.purpose}; categories={','.join(proposal.categories)}; "
            f"preview={proposal.redacted_preview}; max_cost=${proposal.max_reserved_cost:.2f}"
        ),
        route_summary=route,
        next_actions=(f"/approve {proposal.proposal_id}", f"/deny {proposal.proposal_id}"),
    )
