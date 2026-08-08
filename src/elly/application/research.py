"""Application-owned M4 research pipeline (AI-009/010/011/012)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..domain.enums import EpistemicStatus
from ..domain.errors import CancelledError, EllyError, MalformedResultError
from ..domain.models import ClaimSupport, EvidenceObject
from ..guardrails.controller import GuardrailController
from ..ports.clock import ClockPort
from ..ports.web_research import ResearchBudget, WebResearchProvider
from ..research.citation_validator import ValidatedCitationSet, validate_citations
from ..research.evidence_policy import EvidencePolicy
from ..research.freshness import needs_current_information
from ..research.selection import select_evidence
from .execution import CancellationToken


@dataclass(frozen=True, slots=True)
class ResearchExecution:
    """Application-validated research result plus provider provenance."""

    answer: str
    evidence: tuple[EvidenceObject, ...]
    rejected: tuple[str, ...]
    epistemic: EpistemicStatus
    claims: tuple[str, ...]
    provider: str
    model: str
    claim_supports: tuple[ClaimSupport, ...] = ()


_INJECTION = re.compile(r"(?im)^.*(?:ignore\s+(?:all\s+)?(?:previous|policy)|reveal\s+(?:the\s+)?(?:key|secret)|call\s+a\s+tool).*$")
_MARKDOWN_LINK = re.compile(r"\[[^\]\r\n]{1,200}\]\(https?://[^)\s]+\)", re.IGNORECASE)
_FREE_URL = re.compile(r"https?://[^\s)\]]+", re.IGNORECASE)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MAX_UNVERIFIED_SUMMARY_CHARS = 2000


class ResearchPipeline:
    """Fetch untrusted hosted-search metadata, then validate before rendering."""

    def __init__(self, *, provider: WebResearchProvider, clock: ClockPort, max_results: int,
                 timeout_seconds: float, guardrails: GuardrailController | None = None,
                 resolve_hosts: bool = False, evidence_token_budget: int = 256,
                 call_cost_usd: float = 0.0, max_output_tokens: int = 2048,
                 evidence_policy: EvidencePolicy | None = None) -> None:
        self.provider = provider
        self.clock = clock
        self.max_results = max_results
        self.timeout_seconds = timeout_seconds
        self.guardrails = guardrails
        self.resolve_hosts = resolve_hosts
        self.evidence_token_budget = evidence_token_budget
        self.call_cost_usd = call_cost_usd
        self.max_output_tokens = max_output_tokens
        self.evidence_policy = evidence_policy or EvidencePolicy()

    def execute(
        self, query: str, *, request_guardrails: GuardrailController | None = None,
        cancellation: CancellationToken | None = None,
    ) -> ResearchExecution:
        """Research a query under the caller's shared per-task guardrail context."""
        budget = ResearchBudget(max_results=self.max_results, timeout_seconds=self.timeout_seconds)
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        if request_guardrails is None and self.guardrails is not None:
            request_guardrails = self.guardrails.for_request()
        cancel_provider = getattr(self.provider, "cancel", None)
        unregister = (
            cancellation.register(cancel_provider)
            if cancellation is not None and callable(cancel_provider)
            else None
        )
        try:
            if request_guardrails is None:
                response = self.provider.research(query, budget)
            else:
                attempt = 0

                def call_provider():
                    nonlocal attempt
                    if cancellation is not None:
                        cancellation.raise_if_cancelled()
                    attempt += 1
                    provider_query = query
                    if attempt > 1:
                        provider_query = (
                            f"{query}\n\n"
                            "Retry requirement: the earlier attempt returned no cited "
                            "sources. Search again using a direct, timely, authoritative "
                            "source and return at least one inline citation. If the exact "
                            "current value is unavailable, return a cited unavailability "
                            "statement rather than an uncited estimate."
                        )
                    return self.provider.research(provider_query, budget)

                response = request_guardrails.execute(
                    call_provider,
                    cancel=cancel_provider if callable(cancel_provider) else None,
                    output_tokens=self.max_output_tokens,
                    cost_usd=self.call_cost_usd,
                )
            if cancellation is not None:
                cancellation.raise_if_cancelled()
        except EllyError as exc:
            if cancellation is not None and cancellation.cancelled:
                raise CancelledError("hosted research cancelled") from exc
            raise
        finally:
            if unregister is not None:
                unregister()
        validated: ValidatedCitationSet = validate_citations(
            response.citations, now=self.clock.now(), resolve_hosts=self.resolve_hosts
        )
        selection = select_evidence(
            query, validated.evidence, now=self.clock.now(),
            current_information=needs_current_information(query),
            token_budget=self.evidence_token_budget,
        )
        evidence = selection.selected[:self.max_results]
        overflow = selection.selected[self.max_results:]
        rejected = (
            validated.rejected
            + selection.excluded
            + tuple(f"{item.evidence_id}: max results" for item in overflow)
        )
        if not evidence:
            return ResearchExecution(
                answer="I could not verify this with publicly valid sources.", evidence=(),
                rejected=rejected, epistemic=EpistemicStatus.UNKNOWN, claims=(),
                provider=response.provider, model=response.model,
            )
        # Only an explicit/provider-validatable claim passage can support a
        # displayed factual claim. Search metadata and arbitrary snippets remain
        # discovery leads and are never upgraded to ``known``.
        supported = tuple(
            (eligible.evidence, eligible.evidence.supporting_passage)
            for item in evidence
            if (
                (eligible := self.evidence_policy.evaluate(
                    item, provider_answer=response.answer_text,
                    now=self.clock.now(), cancellation=cancellation,
                    current_information=needs_current_information(query),
                )).evidence is not None
                and eligible.evidence is not None
                and _supported_passage(eligible.evidence.supporting_passage)
            )
        )
        supported_ids = {item.evidence_id for item, _snippet in supported}
        evidence_rejected = tuple(
            item.evidence_id + ": ineligible claim evidence"
            for item in evidence
            if item.evidence_id not in supported_ids
        )
        rejected = rejected + evidence_rejected
        if not supported:
            summary = _unverified_summary(response.answer_text)
            if not summary:
                return ResearchExecution(
                    answer="I found source metadata, but the provider returned no safe summary or claim-supporting passage.",
                    evidence=evidence, rejected=rejected,
                    epistemic=EpistemicStatus.UNKNOWN, claims=(),
                    provider=response.provider, model=response.model,
                )
            conflict = _has_conflict(response.answer_text)
            return ResearchExecution(
                answer=(
                    "Unverified provider summary "
                    f"({'conflicting; ' if conflict else ''}not established as fact):\n"
                    f"{summary}\n\n"
                    "Verified facts:\n"
                    "None — the provider returned validated source metadata, but no "
                    "claim-supporting passage."
                ),
                evidence=evidence, rejected=rejected,
                epistemic=(
                    EpistemicStatus.UNKNOWN if conflict else EpistemicStatus.INFERRED
                ),
                claims=(),
                provider=response.provider, model=response.model,
            )
        claims = tuple(f"{snippet} [{item.evidence_id}]" for item, snippet in supported)
        conflicted = _has_conflict(response.answer_text) or _has_structured_conflict(
            query, supported
        )
        claim_supports = tuple(
            ClaimSupport(
                claim_id=f"claim-{index}", text=snippet,
                support_status="conflicted" if conflicted else "supported",
                evidence_ids=(item.evidence_id,),
                note="independent evidence values disagree" if conflicted else "",
            )
            for index, (item, snippet) in enumerate(supported, start=1)
        )
        answer = " ".join(dict.fromkeys(snippet for _item, snippet in supported))
        if not answer:
            raise MalformedResultError("research provider returned no safe cited answer")
        epistemic = EpistemicStatus.UNKNOWN if conflicted else EpistemicStatus.KNOWN
        return ResearchExecution(
            answer=answer, evidence=tuple(item for item, _snippet in supported), rejected=rejected,
            epistemic=epistemic, claims=claims, claim_supports=claim_supports,
            provider=response.provider, model=response.model,
        )


def _quarantine_instructions(text: str) -> str:
    """Remove instruction-shaped web content; never execute or repeat it as policy."""
    return _INJECTION.sub("", text or "").strip()


def _supported_passage(text: str) -> str:
    """Return cited factual text, excluding citation-marker-only annotations."""
    safe = _quarantine_instructions(text)
    if not safe or safe.startswith(("([", "[http", "(http")):
        return ""
    return safe


def _unverified_summary(text: str) -> str:
    """Return bounded provider prose safe for an explicitly unverified region.

    Free-form URLs are omitted because only application-validated citations may
    be rendered as links. Instruction-shaped lines and terminal control bytes are
    removed before display. This does not promote the prose into a verified claim.
    """
    safe = _quarantine_instructions(text)
    safe = _MARKDOWN_LINK.sub("[unverified link omitted]", safe)
    safe = _FREE_URL.sub("[unverified link omitted]", safe)
    safe = _CONTROL.sub("", safe)
    safe = " ".join(safe.split())
    return safe[:_MAX_UNVERIFIED_SUMMARY_CHARS].strip()


def _has_conflict(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in (
        "conflict", "disagree", "different quote", "quotes vary", "prices vary",
    ))


_CURRENT_MARKET = re.compile(
    r"(?i)(?:\b(?:gold|silver|platinum|palladium|bitcoin|ethereum|spx|gspc|dow|nasdaq)\b|"
    r"\bs\s*&?\s*p\s*500\b).{0,80}"
    r"\b(?:current|latest|now|today|price|quote|level|points?|spot|value)\b|"
    r"\b(?:current|latest|now|today|price|quote|level|points?|spot|value)\b.{0,80}"
    r"(?:\b(?:gold|silver|platinum|palladium|bitcoin|ethereum|spx|gspc|dow|nasdaq)\b|"
    r"\bs\s*&?\s*p\s*500\b)"
)
_LEADING_VALUE = re.compile(
    r"(?<![A-Za-z])(?:[$€£]\s*)?(-?\d[\d,]*(?:\.\d+)?)"
)


def _has_structured_conflict(query: str, supported) -> bool:
    """Detect differing primary numeric values across current-market evidence."""
    if not _CURRENT_MARKET.search(query) or len(supported) < 2:
        return False
    values: list[str] = []
    for _item, passage in supported:
        match = _LEADING_VALUE.search(passage)
        if match:
            values.append(match.group(1).replace(",", ""))
    return len(values) >= 2 and len(set(values)) > 1
