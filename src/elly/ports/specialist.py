"""Future specialist execution seam (M5); not wired into M2 routing."""

from __future__ import annotations

from typing import Any, Protocol


class Specialist(Protocol):
    """A specialist implementation paired with a validated manifest."""

    async def can_handle(self, task: Any) -> float:
        """Return a suitability score in the inclusive range 0..1."""
        ...

    async def execute(self, task: Any, context: Any) -> Any:
        """Return a contract-valid result; application policy owns execution."""
        ...
