"""Deterministic current-information detection (FR-003, AI-005)."""

from __future__ import annotations

import re

_CURRENT = re.compile(
    r"\b(today|currently|current|latest|recent|now|this week|this month|as of|newest|who is the .*\b(?:ceo|president|leader)|price|stock|weather|news)\b",
    re.IGNORECASE,
)
_RESEARCH = re.compile(
    r"\b(search|research|look up|cite|sources?|according to the web|verify online)\b", re.IGNORECASE
)
_LOOKUP = re.compile(
    r"\b(?:look\s+(?:it\s+)?up|go\s+look|check\s+(?:online|the\s+web)|"
    r"find\s+(?:it\s+)?(?:online|on\s+the\s+web))\b",
    re.IGNORECASE,
)
_MARKET_STATUS = re.compile(
    r"(?:\b(?:s\s*&\s*p|sp)\s*500\b|\b(?:dow|nasdaq|stock\s+market)\b).{0,40}"
    r"\b(?:status|level|points?|price|value|quote|find)\b|"
    r"\b(?:status|level|points?|price|value|quote|find)\b.{0,40}"
    r"(?:\b(?:s\s*&\s*p|sp)\s*500\b|\b(?:dow|nasdaq|stock\s+market)\b)",
    re.IGNORECASE,
)


def needs_current_information(text: str) -> bool:
    """Return true only for explicit research or time-sensitive wording."""
    return bool(
        _CURRENT.search(text)
        or _RESEARCH.search(text)
        or _LOOKUP.search(text)
        or _MARKET_STATUS.search(text)
    )
