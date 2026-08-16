"""Response rendering (UX-001 initial) — DESIGN §6.1 response layout.

Renders the compact regions that apply in M1:
  1. Outcome (answer or direct status first)
  2. Evidence state (Known/Inferred/Unknown/Blocked) when material
  3. Route (local in M1)
  4. Sources (validated provenance for research)
  5. Limit/failure/next step (only when present, separated from facts)

Never renders chain-of-thought. Sources are always empty here because M1 has no
retrieval; the region is intentionally omitted rather than faked.
"""

from __future__ import annotations

from ..api.contracts import ApplicationStatusView, TaskView
from ..domain.models import HealthReport, TaskResult


def render_result(result: TaskResult) -> str:
    lines: list[str] = []
    if result.answer.strip():
        lines.append(result.answer)
    else:
        lines.append(f"[{result.task_status.value}]")
    lines.append(f"Outcome: {result.outcome_code.value}")
    lines.append(f"Evidence: {result.epistemic_status.value}")
    lines.append(f"Route: {result.route_summary.value}")
    if result.citations:
        lines.append("Sources:")
        for index, citation in enumerate(result.citations, start=1):
            lines.append(f"  [{index}] {citation}")
    if result.failures:
        lines.append("Failure: " + "; ".join(result.failures))
    if result.partial_work:
        lines.append("Partial work received: " + " ".join(result.partial_work))
    if result.next_actions:
        lines.append("Next: " + ", ".join(result.next_actions))
    return "\n".join(lines)


def render_task_view(task: TaskView) -> str:
    """Render the public task contract using the same layout as internal results."""
    lines: list[str] = []
    if task.answer.strip():
        lines.append(task.answer)
    else:
        lines.append(f"[{task.status.value}]")
    if task.outcome_code is not None:
        lines.append(f"Outcome: {task.outcome_code.value}")
    if task.epistemic_status is not None:
        lines.append(f"Evidence: {task.epistemic_status.value}")
    if task.route is not None:
        lines.append(f"Route: {task.route.value}")
    if task.route_category is not None:
        rejected = ",".join(task.rejected_candidate_reason_codes) or "none"
        lines.append(
            "Routing: "
            f"category={task.route_category.value} "
            f"capability={task.capability_id or '-'} "
            f"operation={task.operation or '-'} "
            f"reason={task.selection_reason_code or '-'} "
            f"candidates={task.candidate_count} "
            f"rejected={rejected} "
            f"clarification={str(task.clarification_required).lower()} "
            f"freshness_affected={str(task.freshness_affected_selection).lower()}"
        )
    if task.sources:
        lines.append("Sources:")
        for index, source in enumerate(task.sources, start=1):
            lines.append(f"  [{index}] {source}")
    if task.failures:
        lines.append("Failure: " + "; ".join(task.failures))
    if task.partial_work:
        lines.append("Partial work received: " + " ".join(task.partial_work))
    if task.next_actions:
        lines.append("Next: " + ", ".join(task.next_actions))
    return "\n".join(lines)


def render_status(status: ApplicationStatusView, *, active_mode: str | None = None) -> str:
    """Render status information returned by the public application façade."""
    lines = ["Status:"]
    for report in status.health:
        suffix = f" ({report.detail})" if report.detail else ""
        lines.append(f"  - {report.component}: {report.state.value}{suffix}")
    if active_mode is not None:
        lines.append(f"Mode: {active_mode}")
    if status.runtime is not None:
        runtime = status.runtime
        lines.append(
            f"Runtime: generalist={runtime.generalist_provider}/{runtime.generalist_model_id}; "
            f"research={runtime.research_provider}/{runtime.research_model_id}; "
            f"specialists={runtime.specialist_provider}/{runtime.specialist_model_id}"
        )
    if status.pricing is not None:
        pricing = status.pricing
        lines.append(
            f"Pricing: remote reservation=${pricing.remote_call_reservation_usd:.4f}/call; "
            f"consent max=${pricing.consent_max_cost_usd:.4f}; "
            f"monthly budget=${pricing.monthly_budget_usd:.2f}"
        )
    if status.limits is not None:
        limits = status.limits
        lines.append(
            f"Limits: steps={limits.max_steps}, provider_calls={limits.max_provider_calls}, "
            f"retries={limits.max_retries}, concurrency={limits.max_concurrency}, "
            f"queue={limits.max_queue_size}, "
            f"timeout={limits.tool_timeout_seconds:g}s/{limits.total_timeout_seconds:g}s"
        )
    if status.budget is not None:
        budget = status.budget
        lines.append(
            f"Budget used/reserved: ${budget.reserved_usd:.4f}; "
            f"remaining: ${budget.remaining_usd:.4f}; warning: {budget.warning_level}"
        )
    return "\n".join(lines)


def render_health(reports: list[HealthReport]) -> str:
    lines = ["Status:"]
    for r in reports:
        suffix = f" ({r.detail})" if r.detail else ""
        lines.append(f"  - {r.component}: {r.state.value}{suffix}")
    return "\n".join(lines)
