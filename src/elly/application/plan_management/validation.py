"""Pure result and error contracts for V3 execution-plan validation."""

from __future__ import annotations

from dataclasses import dataclass

from ...domain.errors import PlanValidationError
from ...planning.contracts import ExecutionPlan


@dataclass(frozen=True, slots=True)
class PlanValidationResult:
    """Typed, display-safe outcome of proposal-to-plan validation."""

    accepted: bool
    reason_code: str
    plan: ExecutionPlan | None = None
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.accepted, bool):
            raise TypeError("plan validation accepted must be a bool")
        if not isinstance(self.reason_code, str) or not self.reason_code.strip():
            raise TypeError("plan validation reason_code is required")
        if self.accepted and self.plan is None:
            raise TypeError("accepted plan validation must contain a plan")
        if not self.accepted and self.plan is not None:
            raise TypeError("rejected plan validation cannot contain a plan")
        if not isinstance(self.diagnostics, tuple) or any(
            not isinstance(item, str) or not item.strip() for item in self.diagnostics
        ):
            raise TypeError("plan validation diagnostics must be safe text")

    @property
    def rejection_code(self) -> str:
        """Compatibility alias used by callers that name failures explicitly."""

        return "" if self.accepted else self.reason_code


__all__ = ["PlanValidationError", "PlanValidationResult"]
