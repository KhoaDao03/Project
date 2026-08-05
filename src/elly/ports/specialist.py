"""Specialist execution port (M5); application policy owns authorization."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import HealthReport
from ..specialists.contracts import SpecialistResult, SpecialistTask


class Specialist(Protocol):
    """A specialist implementation paired with a validated manifest."""

    async def can_handle(self, task: SpecialistTask) -> float:
        """Return a suitability score in the inclusive range 0..1."""
        ...

    async def execute(self, task: SpecialistTask, context: str) -> SpecialistResult:
        """Return a contract-valid result; application policy owns execution."""
        ...


@runtime_checkable
class SpecialistProviderPort(Protocol):
    def health(self) -> HealthReport:
        ...

    def execute(self, task: SpecialistTask, *, model: str, prompt_version: str,
                output_limit: int) -> SpecialistResult:
        ...
