"""Generic hosted web-research contracts (M4, API-003/004, DEC-OQ-07)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from ..domain.models import EvidenceObject


@dataclass(frozen=True, slots=True)
class ResearchBudget:
    max_results: int = 5
    timeout_seconds: float = 60.0


@dataclass(frozen=True, slots=True)
class ProviderCitation:
    url: str
    title: str = ""
    publisher: str = ""
    snippet: str = ""
    retrieved_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ResearchResponse:
    answer_text: str
    citations: tuple[ProviderCitation, ...]
    provider: str
    model: str
    retrieved_at: datetime
    failures: tuple[str, ...] = ()


@runtime_checkable
class WebResearchProvider(Protocol):
    """Return untrusted current-information text and citation metadata.

    The application owns authorization, limits, citation validation, and rendering.
    Implementations must not expose provider-specific exceptions across this port.
    """

    def health(self):
        ...

    def research(self, query: str, budget: ResearchBudget) -> ResearchResponse:
        ...


@runtime_checkable
class CitationValidator(Protocol):
    def validate(self, citations: tuple[ProviderCitation, ...]) -> tuple[tuple[EvidenceObject, ...], tuple[str, ...]]:
        ...
