"""Result composition helpers for the response pipeline.

Responsibility: turn validated generalist text + routing/status decisions into the
frozen three-axis TaskResult (DESIGN §6.2). The surrounding
``ResponseCompositionService`` owns presentation policy while these helpers keep
typed result construction deterministic.

Mapping rules:
- successful validated local answer -> task COMPLETED, epistemic KNOWN? No:
  a bare conversational reply is not an evidence-backed factual claim, so local
  ordinary answers map to epistemic INFERRED (reasoned, not evidence-verified),
  reserving KNOWN for evidence-backed research. This is a conservative,
  reviewable default.
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
from ..domain.models import (
    ActionConfirmationProposal,
    ClaimSupport,
    ProvenanceReference,
    TaskResult,
)
from ..privacy import ConsentProposal
from .action_authorization import safe_action_target_reference


def compose_success(
    *,
    task_id: str,
    answer: str,
    route: Route = Route.LOCAL_CONVERSATION,
    provenance: tuple[ProvenanceReference, ...] = (),
) -> TaskResult:
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


def compose_blocked(
    *,
    task_id: str,
    reason: str,
    route: Route = Route.LOCAL_CONVERSATION,
    outcome_code: OutcomeCode = OutcomeCode.BLOCKED,
) -> TaskResult:
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
    *, task_id: str, reason: str, route: Route = Route.LOCAL_CONVERSATION
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
    route: Route = Route.LOCAL_CONVERSATION,
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


def compose_cancelled(
    *, task_id: str, partial_work: str = "", route: Route = Route.LOCAL_CONVERSATION
) -> TaskResult:
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


def compose_research(
    *,
    task_id: str,
    answer: str,
    citations: tuple[str, ...],
    claims: tuple[str, ...],
    epistemic: EpistemicStatus,
    validation: ValidationStatus = ValidationStatus.QUALIFIED,
    claim_supports: tuple[ClaimSupport, ...] = (),
    provenance: tuple[ProvenanceReference, ...] = (),
) -> TaskResult:
    """Compose a research result whose sources were validated by the application."""
    return TaskResult(
        task_id=task_id,
        task_status=TaskStatus.COMPLETED,
        epistemic_status=epistemic,
        validation_status=validation,
        answer=answer,
        route_summary=Route.REGISTERED_CAPABILITY,
        claims=claims,
        citations=citations,
        outcome_code=OutcomeCode.UNKNOWN
        if epistemic is EpistemicStatus.UNKNOWN
        else OutcomeCode.SUCCESS,
        claim_supports=claim_supports,
        provenance=provenance,
    )


def compose_specialist(
    *,
    task_id: str,
    answer: str,
    route: Route,
    epistemic: EpistemicStatus,
    assumptions: tuple[str, ...] = (),
    uncertainties: tuple[str, ...] = (),
    sources: tuple[str, ...] = (),
    partial: bool = False,
    provenance: tuple[ProvenanceReference, ...] = (),
) -> TaskResult:
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
            OutcomeCode.SUCCESS if epistemic is EpistemicStatus.KNOWN else OutcomeCode.UNKNOWN
        )
        validation_status = (
            ValidationStatus.VALIDATED
            if epistemic is EpistemicStatus.KNOWN
            else ValidationStatus.QUALIFIED
        )
    return TaskResult(
        task_id=task_id,
        task_status=task_status,
        epistemic_status=epistemic,
        validation_status=validation_status,
        answer=answer,
        route_summary=route,
        citations=sources,
        partial_work=tuple(f"Assumption: {item}" for item in assumptions),
        next_actions=uncertainties,
        outcome_code=outcome_code,
        provenance=provenance,
    )


def compose_consent_required(
    *, task_id: str, proposal: ConsentProposal, route: Route
) -> TaskResult:
    """Render every material field of an exact cloud-disclosure proposal."""
    return TaskResult(
        task_id=task_id,
        task_status=TaskStatus.AWAITING_CONSENT,
        epistemic_status=EpistemicStatus.BLOCKED,
        validation_status=ValidationStatus.QUALIFIED,
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


def compose_clarification(
    *, task_id: str, fields: tuple[str, ...], route: Route = Route.LOCAL_CONVERSATION
) -> TaskResult:
    """Compose a typed clarification without selecting or executing a provider."""
    safe_fields = tuple(dict.fromkeys(field for field in fields if field.strip()))
    labels = ", ".join(safe_fields) if safe_fields else "the requested capability"
    return TaskResult(
        task_id=task_id,
        task_status=TaskStatus.BLOCKED,
        epistemic_status=EpistemicStatus.BLOCKED,
        validation_status=ValidationStatus.QUALIFIED,
        answer=f"I need clarification before proceeding: {labels}.",
        route_summary=route,
        next_actions=tuple(f"provide {field}" for field in safe_fields),
        outcome_code=OutcomeCode.CLARIFICATION_REQUIRED,
    )


def compose_action_confirmation(
    *,
    task_id: str,
    proposal: ActionConfirmationProposal,
    route: Route,
) -> TaskResult:
    """Compose a redacted pause for one exact consequential-action approval."""
    target = (
        f"{proposal.proposal.target.kind}={safe_action_target_reference(proposal.proposal.target)}"
        if proposal.proposal.target is not None
        else "unspecified"
    )
    return TaskResult(
        task_id=task_id,
        task_status=TaskStatus.AWAITING_CONFIRMATION,
        epistemic_status=EpistemicStatus.BLOCKED,
        validation_status=ValidationStatus.QUALIFIED,
        answer=(
            "Confirmation required before performing this action. "
            f"category={proposal.proposal.category.value}; target={target}; "
            f"confirmation={proposal.confirmation_id}; expires={proposal.expires_at.isoformat()}"
        ),
        route_summary=route,
        next_actions=(
            f"/approve-action {proposal.confirmation_id}",
            f"/deny-action {proposal.confirmation_id}",
        ),
        outcome_code=OutcomeCode.AWAITING_CONFIRMATION,
    )
