"""Deterministic recorded-search provider for M4 tests (never network)."""

from __future__ import annotations

from datetime import datetime, timezone

from ..domain.enums import HealthState
from ..domain.models import HealthReport
from ..ports.web_research import ProviderCitation, ResearchBudget, ResearchResponse


class FixtureWebResearchProvider:
    """Fixture-backed implementation of ``WebResearchProvider``.

    Query matching is intentionally simple and deterministic. The fixture corpus
    contains both safe and hostile citation metadata so policy can be tested without
    contacting a network or sending owner data anywhere.
    """

    def __init__(self, *, answer: str | None = None, citations: tuple[ProviderCitation, ...] | None = None) -> None:
        self.calls: list[str] = []
        self.answer = answer or "The fixture reports a current result supported by the cited source."
        self.citations = citations or (
            ProviderCitation("https://www.example.com/current", "Fixture current source", "Example", "Current result."),
        )

    def health(self) -> HealthReport:
        return HealthReport(component="research(fixtures)", state=HealthState.HEALTHY)

    def cancel(self) -> None:
        return None

    def research(self, query: str, budget: ResearchBudget) -> ResearchResponse:
        self.calls.append(query)
        return ResearchResponse(
            answer_text=self.answer,
            citations=self.citations[: budget.max_results],
            provider="fixtures",
            model="fixture-web-v1",
            retrieved_at=datetime.now(timezone.utc),
        )
