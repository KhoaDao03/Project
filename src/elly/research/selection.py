"""Deterministic minimum-sufficient evidence selection (AI-006/009)."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from ..domain.models import EvidenceObject

_WORD = re.compile(r"[a-z0-9]{2,}", re.IGNORECASE)
_SP500 = re.compile(r"\b(?:s\s*&\s*p|s\s+and\s+p|sp)\s*[- ]?\s*500\b", re.IGNORECASE)
_SP500_SYMBOL = re.compile(r"\b(?:spx|gspc)\b", re.IGNORECASE)
_STOP = {
    "about", "according", "current", "give", "latest", "look", "now",
    "please", "research", "right", "source", "sources", "status", "tell",
    "the", "this", "what", "with",
}
_CANONICAL = {
    "indexes": "index", "indices": "index", "stocks": "stock",
    "points": "point", "prices": "price", "values": "value",
}


@dataclass(frozen=True, slots=True)
class EvidenceSelection:
    selected: tuple[EvidenceObject, ...]
    excluded: tuple[str, ...]
    token_estimate: int


def _terms(text: str) -> set[str]:
    # Financial symbols are commonly formatted several incompatible ways across
    # queries and headlines. Expand the canonical form into the generic terms a
    # relevant market headline is also likely to contain.
    normalized = _SP500.sub("sp500 stock index", text)
    normalized = _SP500_SYMBOL.sub("sp500 stock index", normalized)
    terms: set[str] = set()
    for raw in _WORD.findall(normalized):
        word = _CANONICAL.get(raw.lower(), raw.lower())
        if word not in _STOP:
            terms.add(word)
    return terms


def _tokens(text: str) -> int:
    return len(_WORD.findall(text))


def select_evidence(
    query: str,
    candidates: tuple[EvidenceObject, ...],
    *,
    now: datetime,
    current_information: bool,
    token_budget: int = 256,
    stale_after: timedelta = timedelta(days=30),
) -> EvidenceSelection:
    """Rank public citation passages and pack only the minimum useful set.

    Hosted-search citations do not provide page bodies, so this selection is
    intentionally lexical and conservative. Current-information candidates with
    an explicitly old provider timestamp are rejected; missing passage relevance
    is rejected; canonical duplicates are collapsed; primary sources win ties.
    """
    query_terms = _terms(query)
    excluded: list[str] = []
    ranked: list[tuple[int, int, int, EvidenceObject]] = []
    seen: set[str] = set()
    for index, item in enumerate(candidates):
        identity = item.canonical_url or item.content_hash or item.url
        if identity in seen:
            excluded.append(f"{item.evidence_id}: duplicate")
            continue
        seen.add(identity)
        age = now - item.retrieved_at
        if current_information and age > stale_after:
            excluded.append(f"{item.evidence_id}: stale")
            continue
        relevance = len(
            query_terms & _terms(f"{item.title} {item.snippet} {item.url}")
        )
        if query_terms and relevance == 0:
            excluded.append(f"{item.evidence_id}: unrelated")
            continue
        fresh_item = replace(item, freshness="current" if current_information else "not_applicable")
        ranked.append((relevance, item.source_class == "primary", -index, fresh_item))

    selected: list[EvidenceObject] = []
    used = 0
    for _relevance, _primary, _order, item in sorted(ranked, reverse=True):
        size = _tokens(f"{item.title} {item.snippet}")
        if size > token_budget - used:
            excluded.append(f"{item.evidence_id}: token budget")
            continue
        selected.append(item)
        used += size
    return EvidenceSelection(tuple(selected), tuple(excluded), used)
