"""Response rendering (UX-001 initial) — DESIGN §6.1 response layout.

Renders the compact regions that apply in M1:
  1. Outcome (answer or direct status first)
  2. Evidence state (Known/Inferred/Unknown/Blocked) when material
  3. Route (local in M1)
  4. Sources (empty in M1 — no research path yet)
  5. Limit/failure/next step (only when present, separated from facts)

Never renders chain-of-thought. Sources are always empty here because M1 has no
retrieval; the region is intentionally omitted rather than faked.
"""

from __future__ import annotations

from ..domain.models import HealthReport, TaskResult


def render_result(result: TaskResult) -> str:
    lines: list[str] = []
    if result.answer.strip():
        lines.append(result.answer)
    else:
        lines.append(f"[{result.task_status.value}]")
    lines.append(f"Evidence: {result.epistemic_status.value}")
    lines.append(f"Route: {result.route_summary.value}")
    if result.failures:
        lines.append("Failure: " + "; ".join(result.failures))
    if result.partial_work:
        lines.append("Partial work received: " + " ".join(result.partial_work))
    if result.next_actions:
        lines.append("Next: " + ", ".join(result.next_actions))
    return "\n".join(lines)


def render_health(reports: list[HealthReport]) -> str:
    lines = ["Status:"]
    for r in reports:
        suffix = f" ({r.detail})" if r.detail else ""
        lines.append(f"  - {r.component}: {r.state.value}{suffix}")
    return "\n".join(lines)
