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
    OutcomeCode,
    Route,
    TaskStatus,
    ValidationStatus,
)
from ..domain.models import ClaimSupport, ProvenanceReference, TaskResult


def compose_success(*, task_id: str, answer: str, route: Route = Route.LOCAL_GENERALIST,
                    provenance: tuple[ProvenanceReference, ...] = ()) -> TaskResult:
    """Compose a COMPLETED local conversational result."""
    return TaskResult(
        task_id=task_id,
        task_status=TaskStatus.COMPLETED,
        epistemic_status=EpistemicStatus.INFERRED,
        validation_status=ValidationStatus.VALIDATED,
        answer=answer,
        route_summary=route,
        outcome_code=OutcomeCode.SUCCESS,
        provenance=provenance,
    )


def compose_blocked(*, task_id: str, reason: str, route: Route = Route.LOCAL_GENERALIST,
                    outcome_code: OutcomeCode = OutcomeCode.BLOCKED) -> TaskResult:
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
        outcome_code=outcome_code,
    )


def compose_failed(
    *, task_id: str, reason: str, route: Route = Route.LOCAL_GENERALIST
) -> TaskResult:
    """Compose an execution failure distinct from a policy block."""
    return TaskResult(
        task_id=task_id,
        task_status=TaskStatus.FAILED,
        epistemic_status=EpistemicStatus.UNKNOWN,
        validation_status=ValidationStatus.REJECTED,
        answer="",
        route_summary=route,
        failures=(reason,),
        next_actions=("retry", "check /status"),
        outcome_code=OutcomeCode.FAILED,
    )


def compose_partial(
    *,
    task_id: str,
    reason: str,
    route: Route = Route.LOCAL_GENERALIST,
    answer: str = "",
    partial_work: tuple[str, ...] = (),
) -> TaskResult:
    """Compose useful work whose durable completion is incomplete."""
    return TaskResult(
        task_id=task_id,
        task_status=TaskStatus.PARTIAL,
        epistemic_status=EpistemicStatus.UNKNOWN,
        validation_status=ValidationStatus.QUALIFIED,
        answer=answer,
        route_summary=route,
        partial_work=partial_work,
        failures=(reason,),
        next_actions=("inspect /trace", "retry if safe"),
        outcome_code=OutcomeCode.PARTIAL,
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
        outcome_code=OutcomeCode.CANCELLED,
    )


def compose_possible_duplicate(*, task_id: str, route: Route) -> TaskResult:
    """Report a repeated operation without invoking the provider again."""
    return TaskResult(
        task_id=task_id,
        task_status=TaskStatus.PARTIAL,
        epistemic_status=EpistemicStatus.UNKNOWN,
        validation_status=ValidationStatus.QUALIFIED,
        answer="",
        route_summary=route,
        failures=("operation already has a recorded execution",),
        next_actions=("inspect /trace before retrying",),
        outcome_code=OutcomeCode.POSSIBLE_DUPLICATE_EXECUTION,
    )


def compose_research(*, task_id: str, answer: str, citations: tuple[str, ...], claims: tuple[str, ...],
                     epistemic: EpistemicStatus, validation: ValidationStatus = ValidationStatus.QUALIFIED,
                     claim_supports: tuple[ClaimSupport, ...] = (),
                     provenance: tuple[ProvenanceReference, ...] = ()) -> TaskResult:
    """Compose a research result whose sources were validated by the application."""
    return TaskResult(
        task_id=task_id, task_status=TaskStatus.COMPLETED, epistemic_status=epistemic,
        validation_status=validation, answer=answer, route_summary=Route.WEB_RESEARCH,
        claims=claims, citations=citations,
        outcome_code=OutcomeCode.UNKNOWN if epistemic is EpistemicStatus.UNKNOWN else OutcomeCode.SUCCESS,
        claim_supports=claim_supports, provenance=provenance,
    )


def compose_specialist(*, task_id: str, answer: str, route: Route, epistemic: EpistemicStatus,
                       assumptions: tuple[str, ...] = (), uncertainties: tuple[str, ...] = (),
                       sources: tuple[str, ...] = (), partial: bool = False,
                       provenance: tuple[ProvenanceReference, ...] = ()) -> TaskResult:
    if epistemic is EpistemicStatus.BLOCKED:
        task_status = TaskStatus.BLOCKED
        outcome_code = OutcomeCode.BLOCKED
        validation_status = ValidationStatus.REJECTED
    elif partial or (epistemic is EpistemicStatus.UNKNOWN and not answer.strip()):
        task_status = TaskStatus.PARTIAL
        outcome_code = OutcomeCode.PARTIAL
        validation_status = ValidationStatus.QUALIFIED
    else:
        task_status = TaskStatus.COMPLETED
        outcome_code = (
            OutcomeCode.SUCCESS
            if epistemic is EpistemicStatus.KNOWN
            else OutcomeCode.UNKNOWN
        )
        validation_status = (
            ValidationStatus.VALIDATED
            if epistemic is EpistemicStatus.KNOWN
            else ValidationStatus.QUALIFIED
        )
    return TaskResult(
        task_id=task_id, task_status=task_status,
        epistemic_status=epistemic, validation_status=validation_status,
        answer=answer, route_summary=route, citations=sources,
        partial_work=tuple(f"Assumption: {item}" for item in assumptions),
        next_actions=uncertainties,
        outcome_code=outcome_code,
        provenance=provenance,
    )


def compose_consent_required(*, task_id: str, proposal, route: Route) -> TaskResult:
    """Render every material field of an exact cloud-disclosure proposal."""
    return TaskResult(
        task_id=task_id, task_status=TaskStatus.AWAITING_CONSENT,
        epistemic_status=EpistemicStatus.BLOCKED, validation_status=ValidationStatus.QUALIFIED,
        answer=(
            "Consent required before sending this payload. "
            f"Proposal: {proposal.proposal_id}; provider={proposal.provider}; model={proposal.model}; "
            f"capability={proposal.capability_id}; purpose={proposal.purpose}; "
            f"categories={','.join(proposal.categories)}; "
            f"preview={proposal.redacted_preview}; max_cost=${proposal.max_reserved_cost:.2f}"
        ),
        route_summary=route,
        next_actions=(f"/approve {proposal.proposal_id}", f"/deny {proposal.proposal_id}"),
        outcome_code=OutcomeCode.AWAITING_CONSENT,
    )
