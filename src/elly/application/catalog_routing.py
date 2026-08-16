"""Capability-neutral interpretation and deterministic catalog selection.

This module is deliberately metadata-only.  It knows how to interpret a
request against an immutable routing catalog, but it does not know about
handlers, providers, authorization, persistence, or capability-specific
identifiers.  The output remains an untrusted selection until the routing
policy validates it against the live catalog.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from ..domain.enums import ActionCategory, IntentAmbiguity, IntentEntitySource
from ..domain.errors import ConfigInvalidError, InputInvalidError
from ..domain.models import IntentEntity, RouteRequest
from ..research.freshness import needs_current_information
from .routing_contracts import (
    CandidateMatch,
    CapabilityAvailability,
    CapabilityRoutingDescriptor,
    CapabilitySelectionProposal,
    FreshnessRequirement,
    FreshnessSupport,
    MatchStrength,
    OperationIntentContract,
    RoutingCatalog,
    TaskIntent,
)

_TOKEN = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_TICKER = re.compile(r"\b[A-Z]{1,5}\b")
_EXPLICIT_ARGUMENT = re.compile(
    r"\b(?P<kind>ticker|company|location|person|organization|url|date|number)"
    r"\s*[:=]\s*(?P<value>[^,;\n]+)",
    re.IGNORECASE,
)
_TITLE_CASE = re.compile(r"\b[A-Z][a-z]{2,}(?:['’]s)?\b")
_MARKET_INDEX = re.compile(
    r"\b(?:S\s*&\s*P\s*500|S\s*P\s*500|SPX|Dow(?:\s+Jones)?|DJIA|"
    r"Nasdaq(?:\s+Composite)?|Russell\s+2000)\b",
    re.IGNORECASE,
)
_LOCATION = re.compile(r"\b(?:in|near|around|at)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})")

_STOP_WORDS = frozenset(
    {
        "a",
        "about",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "can",
        "could",
        "do",
        "for",
        "from",
        "general",
        "how",
        "i",
        "information",
        "in",
        "is",
        "it",
        "me",
        "my",
        "of",
        "on",
        "or",
        "please",
        "public",
        "request",
        "should",
        "that",
        "the",
        "this",
        "to",
        "up",
        "use",
        "what",
        "when",
        "which",
        "with",
        "would",
        "you",
        "your",
    }
)
_ENTITY_STOP_WORDS = frozenset(
    {
        "analyze",
        "analyse",
        "ask",
        "buy",
        "compare",
        "check",
        "find",
        "help",
        "inspect",
        "invest",
        "look",
        "purchase",
        "review",
        "search",
        "sell",
        "tell",
        "trade",
        "transfer",
        "today",
        "latest",
        "current",
        "recent",
        "news",
        "price",
        "quote",
        "weather",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "should",
        "use",
        "i",
    }
)

_CONSEQUENTIAL_SIGNALS: tuple[tuple[re.Pattern[str], ActionCategory], ...] = (
    (
        re.compile(r"\b(?:buy|purchase|sell|trade|invest|transfer)\b", re.IGNORECASE),
        ActionCategory.FINANCIAL_TRANSACTION,
    ),
    (
        re.compile(r"\b(?:delete|remove|erase|destroy)\b", re.IGNORECASE),
        ActionCategory.DELETE,
    ),
    (
        re.compile(r"\b(?:send|email|text|message|notify)\b", re.IGNORECASE),
        ActionCategory.EXTERNAL_COMMUNICATION,
    ),
    (
        re.compile(r"\b(?:change|reset|update)\s+(?:my\s+)?password\b", re.IGNORECASE),
        ActionCategory.ACCOUNT_CHANGE,
    ),
    (
        re.compile(r"\b(?:publish|submit|write|post)\b", re.IGNORECASE),
        ActionCategory.EXTERNAL_WRITE,
    ),
)


def _word_forms(value: str) -> frozenset[str]:
    """Return bounded, conservative forms for generic lexical matching."""
    forms: set[str] = set()
    for raw in _TOKEN.findall(value.casefold()):
        if raw in _STOP_WORDS or len(raw) < 2:
            continue
        forms.add(raw)
        if raw.endswith("ing") and len(raw) > 5:
            forms.add(raw[:-3])
            forms.add(raw[:-4])
        if raw.endswith("ed") and len(raw) > 4:
            forms.add(raw[:-2])
        if raw.endswith("ies") and len(raw) > 4:
            forms.add(raw[:-3] + "y")
        elif raw.endswith("s") and len(raw) > 3:
            forms.add(raw[:-1])
    return frozenset(forms)


def _freshness_for(text: str) -> FreshnessRequirement:
    lowered = text.casefold()
    if re.search(r"\b(?:live|real[- ]?time|trading\s+at|quote|quoted)\b", lowered):
        return FreshnessRequirement.LIVE
    # Search/research vocabulary identifies an operation, not necessarily a
    # freshness requirement. Remove those lexical hints before applying the
    # legacy current-information detector so a static evidence specialist can
    # still handle an explicit research-analysis request. Temporal and market
    # signals (including ``latest`` and ``price``) remain current requirements.
    freshness_signal_text = re.sub(
        r"\b(?:research|search|cite|sources?|according\s+to\s+the\s+web|"
        r"verify\s+online)\b",
        "",
        lowered,
    )
    if needs_current_information(freshness_signal_text):
        return FreshnessRequirement.CURRENT
    if re.search(r"\b(?:prefer|preferred|recently)\b", lowered):
        return FreshnessRequirement.PREFERRED
    return FreshnessRequirement.NONE


def _expected_effect(text: str) -> ActionCategory:
    for pattern, category in _CONSEQUENTIAL_SIGNALS:
        if pattern.search(text):
            return category
    return ActionCategory.NONE


def _catalog_operations(
    catalog: RoutingCatalog,
) -> tuple[tuple[CapabilityRoutingDescriptor, OperationIntentContract], ...]:
    return tuple(
        (descriptor, operation) for descriptor in catalog for operation in descriptor.operations
    )


def _operation_score(text: str, operation: OperationIntentContract) -> tuple[int, int]:
    """Return lexical evidence and domain-token evidence for one operation."""
    request_tokens = _word_forms(text)
    identifier_tokens = _word_forms(operation.operation_id.replace(".", " "))
    description_tokens = _word_forms(operation.description)
    domain_tokens = _word_forms(" ".join(operation.domains).replace("_", " "))
    example_tokens = _word_forms(" ".join(operation.examples))
    counterexample_tokens = _word_forms(" ".join(operation.counterexamples))

    identifier_overlap = request_tokens & identifier_tokens
    description_overlap = request_tokens & description_tokens
    domain_overlap = request_tokens & domain_tokens
    # Examples contribute only vocabulary not already represented by the
    # operation ID, description, or domains. This prevents a generic word such
    # as "specialist" from turning one of several equal contracts into a
    # capability-specific hidden tie-breaker.
    example_overlap = request_tokens & (
        example_tokens - identifier_tokens - description_tokens - domain_tokens
    )
    counterexample_overlap = request_tokens & counterexample_tokens

    score = (
        len(identifier_overlap) * 8
        + len(description_overlap) * 2
        + len(domain_overlap) * 3
        + len(example_overlap) * 3
        - len(counterexample_overlap) * 5
    )
    description_phrase = operation.description.casefold().strip()
    if len(description_phrase) >= 8 and description_phrase in text.casefold():
        score += 8
    return max(score, 0), len(domain_overlap)


class CatalogIntentInterpreter:
    """Interpret a request into a capability-neutral :class:`TaskIntent`.

    The catalog supplies vocabulary and operation metadata, but the result
    never names a capability.  When lexical evidence is insufficient, the
    interpreter returns an explicitly unproposed task intent so the caller can
    retain the existing local-conversation fallback.
    """

    def __init__(self, catalog: RoutingCatalog = ()) -> None:
        if not isinstance(catalog, tuple):
            raise InputInvalidError("routing catalog must be a tuple")
        self._catalog = catalog

    def interpret(
        self,
        request: RouteRequest,
        catalog: RoutingCatalog | None = None,
    ) -> TaskIntent:
        if not isinstance(request, RouteRequest):
            raise InputInvalidError("catalog intent request must be a RouteRequest")
        active_catalog = self._catalog if catalog is None else catalog
        if not isinstance(active_catalog, tuple):
            raise InputInvalidError("routing catalog must be a tuple")

        text = (request.contextual_text or request.text).strip()
        freshness = _freshness_for(text)
        expected_effect = _expected_effect(text)
        operations = _catalog_operations(active_catalog)
        scored = tuple(
            (score, domain_hits, descriptor, operation)
            for descriptor, operation in operations
            for score, domain_hits in (_operation_score(text, operation),)
            if score > 0
        )

        if not scored:
            entities, arguments = self._extract_entities(text, active_catalog)
            return TaskIntent(
                requested_operation="task.unspecified",
                domain="general",
                entities=entities,
                arguments=arguments,
                freshness=freshness,
                expected_effect=expected_effect,
                confidence=0.35 if freshness is not FreshnessRequirement.NONE else 1.0,
                ambiguity=IntentAmbiguity.NONE_PROPOSED,
                rationale_code="CATALOG_NO_MATCH",
            )

        scored = tuple(sorted(scored, key=lambda item: (-item[0], -item[1])))
        top_score, top_domain_hits, _top_descriptor, top_operation = scored[0]
        top_pairs = tuple(
            (descriptor.capability_id, operation.operation_id)
            for score, hits, descriptor, operation in scored
            if score == top_score and hits == top_domain_hits
        )
        # Multiple capabilities may intentionally publish the same operation;
        # leave that conflict to the selector's specificity/priority ranking.
        # Different top operation classes are genuinely ambiguous at the task
        # interpretation boundary.
        ambiguous = len({operation_id for _capability_id, operation_id in top_pairs}) > 1 or (
            len(top_pairs) > 1 and top_domain_hits == 0
        )
        # Scope extraction to the leading operation.  Extracting every entity
        # required anywhere in the catalog would put unrelated fields into the
        # selection proposal and make a valid operation fail input validation.
        entities, arguments = self._extract_entities(text, (top_operation,))
        domain = self._best_domain(text, top_operation)
        required_missing = self._missing_entities(top_operation, entities, arguments)
        ambiguity = (
            IntentAmbiguity.AMBIGUOUS
            if ambiguous
            else IntentAmbiguity.MISSING_FIELDS
            if required_missing
            else IntentAmbiguity.CLEAR
        )
        confidence = min(0.98, 0.58 + min(top_score, 20) / 50)
        if ambiguous:
            confidence = min(confidence, 0.49)
        return TaskIntent(
            requested_operation=top_operation.operation_id,
            domain=domain,
            entities=entities,
            arguments=arguments,
            freshness=freshness,
            expected_effect=expected_effect,
            confidence=confidence,
            ambiguity=ambiguity,
            rationale_code=(
                "CATALOG_OPERATION_AMBIGUOUS"
                if ambiguous
                else "CATALOG_REQUIRED_ENTITY_MISSING"
                if required_missing
                else "CATALOG_OPERATION_MATCH"
            ),
        )

    @staticmethod
    def _best_domain(text: str, operation: OperationIntentContract) -> str:
        request_tokens = _word_forms(text)
        if not any(
            request_tokens & _word_forms(domain.replace("_", " ")) for domain in operation.domains
        ):
            return "general"
        ranked = sorted(
            operation.domains,
            key=lambda domain: (
                -len(request_tokens & _word_forms(domain.replace("_", " "))),
                domain,
            ),
        )
        return ranked[0] if ranked else "general"

    @classmethod
    def _extract_entities(
        cls,
        text: str,
        catalog: RoutingCatalog | tuple[OperationIntentContract, ...],
    ) -> tuple[tuple[IntentEntity, ...], dict[str, str]]:
        if catalog and all(isinstance(item, OperationIntentContract) for item in catalog):
            operations = tuple(
                item for item in catalog if isinstance(item, OperationIntentContract)
            )
        else:
            descriptors = tuple(
                item for item in catalog if isinstance(item, CapabilityRoutingDescriptor)
            )
            operations = tuple(
                operation for descriptor in descriptors for operation in descriptor.operations
            )
        needed = {
            entity
            for operation in operations
            for entity in (*operation.required_entities, *operation.optional_entities)
        }
        entities: list[IntentEntity] = []
        arguments: dict[str, str] = {}

        if "subject" in needed and text:
            entities.append(IntentEntity("subject", text, IntentEntitySource.EXPLICIT))
            arguments["subject"] = text

        explicit: dict[str, str] = {}
        for match in _EXPLICIT_ARGUMENT.finditer(text):
            kind = match.group("kind").casefold()
            value = match.group("value").strip().strip("'\"")
            if value:
                explicit[kind] = value

        ticker = explicit.get("ticker")
        if ticker is None and needed & {"ticker", "ticker_or_company", "security"}:
            ticker_text = _MARKET_INDEX.sub(" ", text)
            for candidate in _TICKER.findall(ticker_text):
                if candidate.casefold() not in _ENTITY_STOP_WORDS:
                    ticker = candidate
                    break
        if ticker and needed & {"ticker", "ticker_or_company", "security"}:
            entities.append(IntentEntity("ticker", ticker.upper(), IntentEntitySource.EXPLICIT))
            arguments["ticker"] = ticker.upper()

        company = explicit.get("company")
        if company is None and needed & {"company", "ticker_or_company"}:
            for candidate in _TITLE_CASE.findall(text):
                normalized = candidate.rstrip("'’s")
                if normalized.casefold() not in _ENTITY_STOP_WORDS:
                    company = normalized
                    break
        if company and needed & {"company", "ticker_or_company"}:
            entities.append(IntentEntity("company", company, IntentEntitySource.EXPLICIT))
            arguments["company"] = company

        if "security" in needed:
            market_index = _MARKET_INDEX.search(text)
            if market_index:
                security = " ".join(market_index.group(0).split())
                entities.append(IntentEntity("security", security, IntentEntitySource.EXPLICIT))
                arguments["security"] = security

        location = explicit.get("location")
        if location is None:
            location_match = _LOCATION.search(text)
            if location_match:
                location = location_match.group(1).strip()
        if location and "location" in needed:
            entities.append(IntentEntity("location", location, IntentEntitySource.EXPLICIT))
            arguments["location"] = location

        for kind in ("person", "organization", "url", "date", "number"):
            value = explicit.get(kind)
            if value and kind in needed:
                entities.append(IntentEntity(kind, value, IntentEntitySource.EXPLICIT))
                arguments[kind] = value

        # Entity extraction is intentionally bounded and de-duplicated.  A
        # ticker plus company is useful for a ticker_or_company requirement, but
        # repeated captures must not change matching or ranking.
        unique_entities: list[IntentEntity] = []
        seen: set[tuple[str, str]] = set()
        for entity in entities:
            key = (entity.kind, entity.value.casefold())
            if key not in seen:
                seen.add(key)
                unique_entities.append(entity)
        return tuple(unique_entities), arguments

    @staticmethod
    def _missing_entities(
        operation: OperationIntentContract,
        entities: tuple[IntentEntity, ...],
        arguments: dict[str, str],
    ) -> tuple[str, ...]:
        available = {entity.kind for entity in entities} | set(arguments)
        missing = []
        for required in operation.required_entities:
            if required == "ticker_or_company":
                satisfied = bool({"ticker", "company", "ticker_or_company"} & available)
            elif required == "security":
                satisfied = bool({"security", "ticker", "company"} & available)
            else:
                satisfied = required in available
            if not satisfied:
                missing.append(required)
        return tuple(missing)


def _operation_match(
    intent: TaskIntent,
    operation: OperationIntentContract,
) -> MatchStrength:
    if intent.requested_operation == operation.operation_id:
        return MatchStrength.EXACT
    if intent.requested_operation in {"task.unspecified", "operation.ambiguous"}:
        return MatchStrength.NONE
    requested = _word_forms(intent.requested_operation.replace(".", " "))
    operation_words = _word_forms(
        " ".join(
            (
                operation.operation_id.replace(".", " "),
                operation.description,
                " ".join(operation.examples),
            )
        )
    )
    return MatchStrength.PARTIAL if requested & operation_words else MatchStrength.NONE


def _freshness_match(
    requirement: FreshnessRequirement,
    support: FreshnessSupport,
) -> MatchStrength:
    if requirement is FreshnessRequirement.NONE:
        # A live-only operation must not claim ordinary timeless questions
        # merely because an example or asset keyword overlaps. Current/live
        # data is selected when the task expresses a corresponding freshness
        # need; this keeps quote providers from answering static questions.
        if support is FreshnessSupport.LIVE:
            return MatchStrength.NONE
        return MatchStrength.EXACT
    if requirement is FreshnessRequirement.STATIC:
        return MatchStrength.EXACT if support is FreshnessSupport.STATIC else MatchStrength.PARTIAL
    if requirement is FreshnessRequirement.PREFERRED:
        return MatchStrength.PARTIAL if support is FreshnessSupport.STATIC else MatchStrength.EXACT
    if requirement is FreshnessRequirement.CURRENT:
        if support is FreshnessSupport.CURRENT:
            return MatchStrength.EXACT
        if support is FreshnessSupport.LIVE:
            return MatchStrength.PREFERRED
        return MatchStrength.NONE
    if requirement is FreshnessRequirement.LIVE:
        if support is FreshnessSupport.LIVE:
            return MatchStrength.EXACT
        if support is FreshnessSupport.CURRENT:
            return MatchStrength.PREFERRED
        return MatchStrength.NONE
    return MatchStrength.NONE


def _required_entities_satisfied(
    operation: OperationIntentContract,
    intent: TaskIntent,
) -> bool:
    available = {entity.kind for entity in intent.entities} | set(intent.arguments)
    for required in operation.required_entities:
        if required == "ticker_or_company":
            if not ({"ticker", "company", "ticker_or_company"} & available):
                return False
        elif required == "security":
            if not ({"security", "ticker", "company"} & available):
                return False
        elif required not in available:
            return False
    return True


def _domain_specificity(intent: TaskIntent, operation: OperationIntentContract) -> int:
    if intent.domain.casefold() in {domain.casefold() for domain in operation.domains}:
        return operation.specificity
    intent_tokens = _word_forms(intent.domain.replace("_", " "))
    domain_tokens = _word_forms(" ".join(operation.domains).replace("_", " "))
    if intent_tokens & domain_tokens:
        return max(1, operation.specificity // 2)
    return 0


_STRENGTH_RANK = {
    MatchStrength.NONE: 0,
    MatchStrength.PARTIAL: 1,
    MatchStrength.PREFERRED: 2,
    MatchStrength.EXACT: 3,
}


def _rank_key(match: CandidateMatch) -> tuple[int, int, int, int, int, int]:
    return (
        int(match.compatible),
        int(match.required_inputs_satisfied),
        _STRENGTH_RANK[match.operation_match],
        _STRENGTH_RANK[match.freshness_match],
        match.domain_specificity,
        match.declared_priority,
    )


def _rank_score(match: CandidateMatch) -> int:
    """Encode the lexicographic tuple without allowing a lower tier to win."""
    base = 101
    score = 0
    for value in _rank_key(match):
        score = score * base + value
    return score


@dataclass(frozen=True, slots=True)
class CatalogSelectionResult:
    """Deterministic selector result, including safe rejected alternatives."""

    matches: tuple[CandidateMatch, ...]
    selection: CapabilitySelectionProposal | None = None
    reason_code: str = "CATALOG_NO_MATCH"
    clarification_required: bool = False
    clarification_fields: tuple[str, ...] = ()
    best_candidate: CandidateMatch | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.matches, tuple) or any(
            not isinstance(match, CandidateMatch) for match in self.matches
        ):
            raise InputInvalidError("catalog selection matches are invalid")
        if self.selection is not None and not isinstance(
            self.selection, CapabilitySelectionProposal
        ):
            raise InputInvalidError("catalog selection proposal is invalid")
        if not isinstance(self.reason_code, str) or not self.reason_code.strip():
            raise InputInvalidError("catalog selection reason_code is required")
        if not isinstance(self.clarification_required, bool):
            raise InputInvalidError("catalog clarification flag is invalid")
        if not isinstance(self.clarification_fields, tuple) or any(
            not isinstance(field, str) or not field.strip() for field in self.clarification_fields
        ):
            raise InputInvalidError("catalog clarification fields are invalid")
        if self.clarification_required and not self.clarification_fields:
            raise InputInvalidError("catalog clarification fields are required")
        if self.best_candidate is not None and not isinstance(self.best_candidate, CandidateMatch):
            raise InputInvalidError("catalog best candidate is invalid")


@dataclass(frozen=True, slots=True)
class SelectionValidationResult:
    """Validation result for a proposed selection against one catalog snapshot."""

    accepted: bool
    reason_code: str
    selection: CapabilitySelectionProposal | None = None
    match: CandidateMatch | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.accepted, bool):
            raise InputInvalidError("selection validation accepted must be a bool")
        if not isinstance(self.reason_code, str) or not self.reason_code.strip():
            raise InputInvalidError("selection validation reason_code is required")
        if self.accepted and (self.selection is None or self.match is None):
            raise InputInvalidError("accepted selection validation must contain a match")


class CatalogCandidateSelector:
    """Match and rank catalog operations with a stable, auditable policy."""

    def __init__(
        self,
        *,
        ambiguity_threshold: int = 0,
        max_alternatives: int = 3,
        minimum_confidence: float = 0.5,
    ) -> None:
        if isinstance(ambiguity_threshold, bool) or ambiguity_threshold < 0:
            raise ConfigInvalidError("ambiguity_threshold must be a non-negative integer")
        if isinstance(max_alternatives, bool) or not 1 <= max_alternatives <= 8:
            raise ConfigInvalidError("max_alternatives must be between 1 and 8")
        if isinstance(minimum_confidence, bool) or not 0 <= minimum_confidence <= 1:
            raise ConfigInvalidError("minimum_confidence must be between 0 and 1")
        self._ambiguity_threshold = ambiguity_threshold
        self._max_alternatives = max_alternatives
        self._minimum_confidence = minimum_confidence

    def match(
        self,
        intent: TaskIntent,
        catalog: RoutingCatalog,
    ) -> tuple[CandidateMatch, ...]:
        if not isinstance(intent, TaskIntent):
            raise InputInvalidError("candidate matching requires a TaskIntent")
        if not isinstance(catalog, tuple):
            raise InputInvalidError("candidate matching requires a tuple catalog")
        matches = tuple(
            self._match_operation(descriptor, operation, intent)
            for descriptor, operation in _catalog_operations(catalog)
        )
        return tuple(
            sorted(
                matches,
                key=lambda match: (
                    -_rank_score(match),
                    # This ordering is presentation-only.  It is never used
                    # to select a winner; semantic ties are clarified below.
                    match.capability_id,
                    match.operation_id,
                ),
            )
        )

    def rank_candidates(
        self,
        intent: TaskIntent,
        catalog: RoutingCatalog,
    ) -> tuple[CandidateMatch, ...]:
        """Compatibility/readability alias for callers that want ranked evidence."""
        return self.match(intent, catalog)

    def select(self, intent: TaskIntent, catalog: RoutingCatalog) -> CatalogSelectionResult:
        matches = self.match(intent, catalog)
        if not matches:
            return CatalogSelectionResult(matches=(), reason_code="CATALOG_NO_MATCH")

        compatible = tuple(match for match in matches if match.compatible)
        if intent.ambiguity is IntentAmbiguity.AMBIGUOUS:
            best = compatible[0] if compatible else matches[0]
            return CatalogSelectionResult(
                matches=matches,
                selection=self._proposal(
                    intent,
                    best,
                    matches,
                    ambiguity=IntentAmbiguity.AMBIGUOUS,
                    rationale_code="CATALOG_AMBIGUOUS",
                ),
                reason_code="CATALOG_AMBIGUOUS",
                clarification_required=True,
                clarification_fields=("capability", "operation"),
                best_candidate=best,
            )
        if intent.confidence < self._minimum_confidence and compatible:
            return CatalogSelectionResult(
                matches=matches,
                selection=self._proposal(
                    intent,
                    compatible[0],
                    matches,
                    ambiguity=IntentAmbiguity.AMBIGUOUS,
                    rationale_code="LOW_CONFIDENCE",
                ),
                reason_code="LOW_CONFIDENCE",
                clarification_required=True,
                clarification_fields=("operation",),
                best_candidate=compatible[0],
            )
        if compatible:
            top = compatible[0]
            second = compatible[1] if len(compatible) > 1 else None
            if (
                second is not None
                and _rank_score(top) - _rank_score(second) <= self._ambiguity_threshold
            ):
                return CatalogSelectionResult(
                    matches=matches,
                    selection=self._proposal(
                        intent,
                        top,
                        matches,
                        ambiguity=IntentAmbiguity.AMBIGUOUS,
                        rationale_code="CATALOG_AMBIGUOUS",
                    ),
                    reason_code="CATALOG_AMBIGUOUS",
                    clarification_required=True,
                    clarification_fields=("capability", "operation"),
                    best_candidate=top,
                )
            proposal = self._proposal(intent, top, matches)
            return CatalogSelectionResult(
                matches=matches,
                selection=proposal,
                reason_code="CATALOG_SINGLE_MATCH",
                best_candidate=top,
            )

        reason, fields = self._incompatibility_reason(matches, catalog, intent)
        preview = None
        if reason != "CATALOG_NO_MATCH":
            preview = self._proposal(
                intent,
                matches[0],
                matches,
                ambiguity=(IntentAmbiguity.MISSING_FIELDS if fields else IntentAmbiguity.CLEAR),
                rationale_code=reason,
            )
        return CatalogSelectionResult(
            matches=matches,
            selection=preview,
            reason_code=reason,
            clarification_required=bool(fields),
            clarification_fields=fields,
            best_candidate=matches[0],
        )

    def validate_proposal(
        self,
        proposal: CapabilitySelectionProposal,
        catalog: RoutingCatalog,
        *,
        intent: TaskIntent | None = None,
    ) -> SelectionValidationResult:
        """Validate an untrusted proposal against the supplied catalog snapshot."""
        if not isinstance(proposal, CapabilitySelectionProposal):
            raise InputInvalidError("selection proposal has an invalid type")
        if not isinstance(catalog, tuple):
            raise InputInvalidError("selection validation requires a tuple catalog")
        descriptor = next(
            (item for item in catalog if item.capability_id == proposal.capability_id),
            None,
        )
        if descriptor is None:
            return SelectionValidationResult(False, "CAPABILITY_NOT_REGISTERED")
        operation = next(
            (item for item in descriptor.operations if item.operation_id == proposal.operation_id),
            None,
        )
        if operation is None:
            return SelectionValidationResult(False, "OPERATION_UNSUPPORTED")
        if proposal.ambiguity is not IntentAmbiguity.CLEAR:
            return SelectionValidationResult(False, "SELECTION_AMBIGUOUS")
        if proposal.confidence < self._minimum_confidence:
            return SelectionValidationResult(False, "LOW_CONFIDENCE")
        allowed_arguments = (
            set(operation.accepted_inputs)
            | set(operation.required_entities)
            | set(operation.optional_entities)
        )
        if "text" in operation.accepted_inputs or "subject" in (
            set(operation.required_entities) | set(operation.optional_entities)
        ):
            allowed_arguments.add("subject")
        if "ticker_or_company" in allowed_arguments:
            allowed_arguments.update({"ticker", "company"})
        if "security" in allowed_arguments:
            allowed_arguments.update({"security", "ticker", "company"})
        if any(key not in allowed_arguments for key in proposal.arguments):
            return SelectionValidationResult(False, "INPUT_UNSUPPORTED")
        allowed_entities = set(operation.required_entities) | set(operation.optional_entities)
        allowed_entities.update({"subject"})
        if "ticker_or_company" in allowed_entities:
            allowed_entities.update({"ticker", "company"})
        if "security" in allowed_entities:
            allowed_entities.update({"security", "ticker", "company"})
        if any(entity.kind not in allowed_entities for entity in proposal.entities):
            return SelectionValidationResult(False, "ENTITY_UNSUPPORTED")

        validation_intent = intent or TaskIntent(
            requested_operation=operation.operation_id,
            domain=operation.domains[0],
            entities=proposal.entities,
            arguments=proposal.arguments,
            confidence=proposal.confidence,
            ambiguity=IntentAmbiguity.CLEAR,
            rationale_code="SELECTION_VALIDATION",
        )
        match = self._match_operation(descriptor, operation, validation_intent)
        if not descriptor.available:
            return SelectionValidationResult(False, "CAPABILITY_UNAVAILABLE", match=match)
        if not match.required_inputs_satisfied:
            return SelectionValidationResult(False, "REQUIRED_ENTITY_MISSING", match=match)
        if match.freshness_match is MatchStrength.NONE:
            return SelectionValidationResult(False, "FRESHNESS_UNSUPPORTED", match=match)
        if match.operation_match is MatchStrength.NONE:
            return SelectionValidationResult(False, "OPERATION_UNSUPPORTED", match=match)
        if not match.compatible:
            reason = (
                match.rejection_codes[0] if match.rejection_codes else "SELECTION_PROPOSAL_REJECTED"
            )
            return SelectionValidationResult(False, reason, match=match)

        canonical = CapabilitySelectionProposal(
            capability_id=proposal.capability_id,
            operation_id=proposal.operation_id,
            arguments=proposal.arguments,
            entities=proposal.entities,
            confidence=proposal.confidence,
            ambiguity=IntentAmbiguity.CLEAR,
            rationale_code="SELECTION_VALIDATED",
            ranked_alternatives=(
                self.match(validation_intent, catalog)[: self._max_alternatives]
                if intent is not None
                else (match,)
            ),
        )
        return SelectionValidationResult(True, "SELECTION_VALIDATED", canonical, match)

    def proposal_for(
        self,
        intent: TaskIntent,
        candidate: CandidateMatch,
        matches: Iterable[CandidateMatch] = (),
    ) -> CapabilitySelectionProposal:
        """Create a bounded proposal view for diagnostics or unavailable state."""
        return self._proposal(intent, candidate, tuple(matches) or (candidate,))

    @staticmethod
    def _match_operation(
        descriptor: CapabilityRoutingDescriptor,
        operation: OperationIntentContract,
        intent: TaskIntent,
    ) -> CandidateMatch:
        operation_match = _operation_match(intent, operation)
        freshness_match = _freshness_match(intent.freshness, operation.freshness)
        required_inputs_satisfied = _required_entities_satisfied(operation, intent)
        rejection_codes: list[str] = []
        if descriptor.availability is not CapabilityAvailability.AVAILABLE:
            rejection_codes.append("CAPABILITY_UNAVAILABLE")
        if operation_match is MatchStrength.NONE:
            rejection_codes.append("OPERATION_UNSUPPORTED")
        if not required_inputs_satisfied:
            rejection_codes.append("REQUIRED_ENTITY_MISSING")
        if freshness_match is MatchStrength.NONE:
            rejection_codes.append("FRESHNESS_UNSUPPORTED")
        if (
            intent.expected_effect is not ActionCategory.NONE
            and operation.effect is not intent.expected_effect
        ):
            rejection_codes.append("ACTION_EFFECT_MISMATCH")
        return CandidateMatch(
            capability_id=descriptor.capability_id,
            operation_id=operation.operation_id,
            compatible=not rejection_codes,
            required_inputs_satisfied=required_inputs_satisfied,
            operation_match=operation_match,
            freshness_match=freshness_match,
            domain_specificity=_domain_specificity(intent, operation),
            declared_priority=descriptor.priority,
            rejection_codes=tuple(dict.fromkeys(rejection_codes)),
        )

    def _proposal(
        self,
        intent: TaskIntent,
        candidate: CandidateMatch,
        matches: tuple[CandidateMatch, ...],
        *,
        ambiguity: IntentAmbiguity = IntentAmbiguity.CLEAR,
        rationale_code: str = "CATALOG_SINGLE_MATCH",
    ) -> CapabilitySelectionProposal:
        return CapabilitySelectionProposal(
            capability_id=candidate.capability_id,
            operation_id=candidate.operation_id,
            arguments=intent.arguments,
            entities=intent.entities,
            confidence=intent.confidence,
            ambiguity=ambiguity,
            rationale_code=rationale_code,
            ranked_alternatives=matches[: self._max_alternatives],
        )

    @staticmethod
    def _incompatibility_reason(
        matches: tuple[CandidateMatch, ...],
        catalog: RoutingCatalog,
        intent: TaskIntent,
    ) -> tuple[str, tuple[str, ...]]:
        operation_matches = tuple(
            match for match in matches if match.operation_match is not MatchStrength.NONE
        )
        if operation_matches:
            if intent.expected_effect is not ActionCategory.NONE:
                effect_compatible = any(
                    operation.effect is intent.expected_effect
                    for match in operation_matches
                    for descriptor in catalog
                    if descriptor.capability_id == match.capability_id
                    for operation in descriptor.operations
                    if operation.operation_id == match.operation_id
                )
                if not effect_compatible:
                    return "ACTION_EFFECT_MISMATCH", ()
            missing = tuple(
                required
                for match in operation_matches
                for descriptor in catalog
                if descriptor.capability_id == match.capability_id
                for operation in descriptor.operations
                if operation.operation_id == match.operation_id
                for required in operation.required_entities
                if not _required_entities_satisfied(
                    OperationIntentContract(
                        operation_id=operation.operation_id,
                        description=operation.description,
                        domains=operation.domains,
                        accepted_inputs=operation.accepted_inputs,
                        required_entities=(required,),
                        optional_entities=(),
                        freshness=operation.freshness,
                        effect=operation.effect,
                        specificity=operation.specificity,
                        examples=operation.examples,
                        counterexamples=operation.counterexamples,
                        output_schema_versions=operation.output_schema_versions,
                    ),
                    intent,
                )
            )
            if missing:
                return "REQUIRED_ENTITY_MISSING", tuple(dict.fromkeys(missing))
            if any("FRESHNESS_UNSUPPORTED" in match.rejection_codes for match in operation_matches):
                return "FRESHNESS_UNSUPPORTED", ()
            if any(
                "CAPABILITY_UNAVAILABLE" in match.rejection_codes for match in operation_matches
            ):
                return "CAPABILITY_UNAVAILABLE", ()
            if any(
                "ACTION_EFFECT_MISMATCH" in match.rejection_codes for match in operation_matches
            ):
                return "ACTION_EFFECT_MISMATCH", ()
        return "CATALOG_NO_MATCH", ()


__all__ = [
    "CatalogCandidateSelector",
    "CatalogIntentInterpreter",
    "CatalogSelectionResult",
    "SelectionValidationResult",
]
