"""Port contracts for local model-assisted planning."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..domain.errors import InputInvalidError
from ..domain.models import HealthReport
from ..planning.catalog import PlannerCatalog
from ..planning.contracts import ExecutionProposal


@dataclass(frozen=True, slots=True)
class PlannerRequest:
    """Approved, bounded input supplied to a local planner adapter."""

    request_id: str
    text: str
    approved_context: str
    catalog: PlannerCatalog
    max_output_tokens: int
    timeout_seconds: float

    def __post_init__(self) -> None:
        for value, name in ((self.request_id, "planner request_id"), (self.text, "planner text")):
            if not isinstance(value, str) or not value.strip():
                raise InputInvalidError(f"{name} must be non-empty")
        if not isinstance(self.approved_context, str):
            raise InputInvalidError("planner approved_context must be text")
        if len(self.text) > 20_000 or len(self.approved_context) > 20_000:
            raise InputInvalidError("planner context exceeds its size limit")
        if not isinstance(self.catalog, PlannerCatalog):
            raise InputInvalidError("planner catalog is invalid")
        if (
            isinstance(self.max_output_tokens, bool)
            or not isinstance(self.max_output_tokens, int)
            or self.max_output_tokens <= 0
        ):
            raise InputInvalidError("planner max_output_tokens must be positive")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(float(self.timeout_seconds))
            or self.timeout_seconds <= 0
        ):
            raise InputInvalidError("planner timeout_seconds must be positive")


@runtime_checkable
class LocalPlannerPort(Protocol):
    """Local planner boundary; implementations return typed proposals only."""

    def propose(self, request: PlannerRequest) -> ExecutionProposal:
        """Produce an untrusted typed proposal without executing a capability."""
        ...

    def health(self) -> HealthReport:
        """Report local planner readiness without a generation call."""
        ...

    def cancel(self) -> None:
        """Request cancellation of an active planner generation."""
        ...


__all__ = ["LocalPlannerPort", "PlannerRequest"]
