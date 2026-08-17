"""Deterministic V3.5 presentation-mode policy.

The policy consumes application-owned result metadata only.  In particular, it
does not inspect planner prose or a planner-selected finalization value.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..domain.enums import PresentationMode, TaskStatus
from ..planning.contracts import FinalizationStrategy


def select_presentation_mode(
    *,
    task_status: TaskStatus | str,
    has_immutable_record: bool = False,
    protocol_output: bool = False,
    exact_record: bool = False,
) -> PresentationMode:
    """Select a presentation mode from validated application state.

    ``protocol_output`` and ``exact_record`` are application-owned flags.  They
    are never read from planner output.  Consent/confirmation and other
    protocol pauses remain deterministic; ordinary blocked/failed work is
    still eligible for a useful composed explanation.
    """

    status = task_status.value if isinstance(task_status, TaskStatus) else str(task_status)
    if protocol_output or status in {
        TaskStatus.AWAITING_CONSENT.value,
        TaskStatus.AWAITING_CONFIRMATION.value,
    }:
        return PresentationMode.DETERMINISTIC_ONLY
    if exact_record or has_immutable_record:
        return PresentationMode.EXACT_WITH_COMPOSED_CONTEXT
    return PresentationMode.COMPOSED


def presentation_mode_for_finalization(
    finalization: FinalizationStrategy | str,
    *,
    task_status: TaskStatus | str,
    has_immutable_record: bool = False,
    protocol_output: bool = False,
) -> PresentationMode:
    """Compatibility helper that deliberately ignores the legacy value.

    Old V3 values remain parseable for recovery, but they do not regain
    authority over V3.5 policy.  The argument is accepted only so migration
    callers can make that boundary explicit.
    """

    del finalization
    return select_presentation_mode(
        task_status=task_status,
        has_immutable_record=has_immutable_record,
        protocol_output=protocol_output,
    )


def mode_for_plan_aggregation(aggregation: object) -> PresentationMode:
    """Classify a validated ``PlanAggregation`` without importing it eagerly."""

    step_envelopes = getattr(aggregation, "step_envelopes", {})
    has_receipt = any(
        getattr(envelope, "action_receipt", None) is not None
        for envelope in step_envelopes.values()
    ) if isinstance(step_envelopes, Mapping) else False
    status = getattr(aggregation, "status", "failed")
    return select_presentation_mode(task_status=status.value if hasattr(status, "value") else status, has_immutable_record=has_receipt)


__all__ = [
    "mode_for_plan_aggregation",
    "presentation_mode_for_finalization",
    "select_presentation_mode",
]
