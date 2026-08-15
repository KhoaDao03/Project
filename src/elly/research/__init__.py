"""M4 deterministic research policy and provider support."""

from .citation_validator import ValidatedCitationSet, validate_citations
from .fake_provider import FixtureWebResearchProvider
from .freshness import needs_current_information
from .selection import EvidenceSelection, select_evidence

__all__ = [
    "EvidenceSelection", "FixtureWebResearchProvider", "ValidatedCitationSet",
    "needs_current_information", "select_evidence", "validate_citations",
]
