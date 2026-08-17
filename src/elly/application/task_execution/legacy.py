"""Compatibility execution for persisted legacy synthesis steps.

Current planning ends with post-aggregation response composition.  This
adapter remains deliberately small so old persisted plans can still be read
and completed without making synthesis a normal capability path.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from elly.application.plan_results import TemplateFinalizer, legacy_source_aggregation
from elly.application.step_results import StepResultEnvelope
from elly.domain.models import TaskResult
from elly.planning.contracts import ExecutionPlan, PlanStep


def execute_legacy_synthesis(
    plan: ExecutionPlan,
    step: PlanStep,
    results: Mapping[str, TaskResult],
    envelopes: Mapping[str, StepResultEnvelope],
    before_dispatch: Callable[[], None],
) -> TaskResult:
    """Complete one persisted ``LOCAL_SYNTHESIS`` step deterministically."""

    before_dispatch()
    source_result = legacy_source_aggregation(
        plan,
        results,
        envelopes,
        {item.step_id: item.state for item in plan.steps},
    )
    return TemplateFinalizer().finalize(source_result)
