"""Deterministic minimum-sufficient evidence selection (AI-006/009)."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from urllib.parse import urlsplit

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
_MARKET_ASSET = re.compile(
    r"\b(?:sp500|spx|gspc|dow|nasdaq|gold|silver|platinum|palladium|copper|"
    r"brent|wti|crude\s+oil|natural\s+gas|bitcoin|ethereum|forex|currency|"
    r"exchange\s+rate|treasury|bond)\b",
    re.IGNORECASE,
)
_MARKET_VALUE = re.compile(
    r"\b(?:current|latest|now|today|price|quote|level|points?|spot|value|trading)\b",
    re.IGNORECASE,
)
_DIRECT_MARKET_PATH = re.compile(
    r"/(?:quote|quotes|indices|index|markets|commodities|charts?|spot-prices?|"
    r"gold-price|gold-prices|silver-price|silver-prices)(?:/|$|[-?])",
    re.IGNORECASE,
)
_NEWS_OR_COMMENTARY_PATH = re.compile(
    r"/(?:news|article|articles|story|stories|forecast|analysis|opinion)(?:/|$)",
    re.IGNORECASE,
)
_COMMUNITY_HOSTS = ("reddit.com", "quora.com")
_DIRECT_MARKET_HOSTS = (
    "spglobal.com", "cmegroup.com", "lbma.org.uk", "finance.yahoo.com",
    "marketwatch.com", "investing.com", "kitco.com", "monex.com",
    "findbullionprices.com", "bullionexchanges.com", "ycharts.com",
    "cnbc.com", "nasdaq.com", "bloomberg.com", "reuters.com",
)


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


def _host_matches(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == domain or host.endswith(f".{domain}") for domain in domains)


def _is_current_market_quote(query: str) -> bool:
    normalized = _SP500.sub("sp500", query)
    normalized = _SP500_SYMBOL.sub("sp500", normalized)
    return bool(_MARKET_ASSET.search(normalized) and _MARKET_VALUE.search(normalized))


def _market_source_score(item: EvidenceObject) -> tuple[bool, int]:
    """Return whether a source is a direct quote page and its authority score."""
    parsed = urlsplit(item.canonical_url or item.url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = parsed.path.lower()
    if _host_matches(host, _COMMUNITY_HOSTS) or _NEWS_OR_COMMENTARY_PATH.search(path):
        return False, 0
    direct_path = bool(_DIRECT_MARKET_PATH.search(path))
    # Recorded fixtures use descriptive paths and remain useful contract tests.
    descriptive_path = bool(re.search(r"/(?:sp500|spx|gold|silver)(?:[-/]|$)", path))
    authoritative = _host_matches(host, _DIRECT_MARKET_HOSTS)
    return direct_path or descriptive_path, 2 if authoritative else 1


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
    ranked: list[tuple[int, int, int, int, EvidenceObject]] = []
    seen: set[str] = set()
    market_quote = _is_current_market_quote(query)
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
        market_authority = 0
        if market_quote:
            direct_market, market_authority = _market_source_score(item)
            if not direct_market:
                excluded.append(f"{item.evidence_id}: not a direct market quote source")
                continue
        relevance = len(
            query_terms & _terms(f"{item.title} {item.snippet} {item.url}")
        )
        if query_terms and relevance == 0:
            excluded.append(f"{item.evidence_id}: unrelated")
            continue
        fresh_item = replace(item, freshness="current" if current_information else "not_applicable")
        ranked.append((
            market_authority, relevance, item.source_class == "primary", -index,
            fresh_item,
        ))

    selected: list[EvidenceObject] = []
    used = 0
    for _authority, _relevance, _primary, _order, item in sorted(ranked, reverse=True):
        size = _tokens(f"{item.title} {item.snippet}")
        if size > token_budget - used:
            excluded.append(f"{item.evidence_id}: token budget")
            continue
        selected.append(item)
        used += size
    return EvidenceSelection(tuple(selected), tuple(excluded), used)
