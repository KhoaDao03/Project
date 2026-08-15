"""Deterministic specialist provider for M5 contract tests."""

from __future__ import annotations

from ..domain.enums import HealthState
from ..domain.models import HealthReport
from .contracts import SpecialistResult, SpecialistTask


class FakeSpecialistProvider:
    def __init__(self, *, result: SpecialistResult | None = None, fail: str | None = None) -> None:
        self.result = result or SpecialistResult(
            status="inferred", answer="The supplied material supports a bounded specialist assessment.",
            assumptions=("Only the supplied context was considered.",),
        )
        self.fail = fail
        self.calls: list[dict[str, object]] = []

    def health(self) -> HealthReport:
        return HealthReport(component="specialist(fake)", state=HealthState.HEALTHY)

    def cancel(self) -> None:
        return None

    def execute(self, task: SpecialistTask, *, model: str, prompt_version: str, output_limit: int) -> SpecialistResult:
        self.calls.append({
            "specialist_id": task.specialist_id,
            "model": model,
            "prompt_version": prompt_version,
            "goal": task.goal,
            "context": task.context,
        })
        if self.fail == "malformed":
            # This is deliberately converted to a typed failure by the workflow.
            raise ValueError("fake malformed result")
        if self.fail == "out_of_scope":
            return SpecialistResult(status="known", answer="I executed the requested tool.")
        words = self.result.answer.split()
        if len(words) > output_limit:
            return SpecialistResult(
                status="partial", answer=" ".join(words[:output_limit]), truncated=True
            )
        return self.result
