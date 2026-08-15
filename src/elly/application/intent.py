"""Structured capability-intent interpretation and compatibility mapping."""

from __future__ import annotations

import re

from ..domain.enums import IntentAmbiguity, IntentEntitySource
from ..domain.models import (
    CapabilityIntent,
    IntentEntity,
    RouteProposal,
    RouteRequest,
)
from ..ports.intent import IntentInterpreterPort
from ..research.freshness import needs_current_information


class DeterministicIntentInterpreter(IntentInterpreterPort):
    """Produce typed intent from stable signals without treating text as authority."""

    _LEGACY_OPERATIONS = {
        "web_research": "research.search",
        "coding": "specialist.analyze",
        "research": "specialist.analyze",
    }

    def interpret(
        self,
        request: RouteRequest,
        *,
        proposal: RouteProposal | None = None,
    ) -> CapabilityIntent:
        if proposal is not None:
            return self._from_legacy_proposal(proposal)

        text = request.text.strip()
        contextual_text = request.contextual_text or text
        lowered = text.lower()

        if self._is_coding_request(lowered):
            return self._selected(
                "coding",
                "specialist.analyze",
                text,
                "CODING_REQUEST",
            )
        if self._is_research_specialist_request(lowered):
            return self._selected(
                "research",
                "specialist.analyze",
                text,
                "RESEARCH_SPECIALIST_REQUEST",
            )
        if needs_current_information(contextual_text):
            return self._selected(
                "web_research",
                "research.search",
                contextual_text,
                "CURRENT_INFORMATION_REQUIRED",
            )
        if "specialist" in lowered and not self._is_coding_request(lowered):
            return CapabilityIntent(
                proposed_capability_id=None,
                operation="",
                arguments={},
                confidence=0.35,
                ambiguity=IntentAmbiguity.AMBIGUOUS,
                rationale_code="SPECIALIST_SCOPE_AMBIGUOUS",
            )
        return CapabilityIntent(
            proposed_capability_id=None,
            operation="conversation.respond",
            arguments={},
            confidence=1.0,
            ambiguity=IntentAmbiguity.NONE_PROPOSED,
            rationale_code="LOCAL_DEFAULT",
        )

    @staticmethod
    def _from_legacy_proposal(proposal: RouteProposal) -> CapabilityIntent:
        if proposal.capability_id is None:
            return CapabilityIntent(
                proposed_capability_id=None,
                operation="conversation.respond",
                arguments={},
                confidence=1.0,
                ambiguity=IntentAmbiguity.NONE_PROPOSED,
                rationale_code="PROPOSAL_ACCEPTED",
            )
        operation = DeterministicIntentInterpreter._LEGACY_OPERATIONS.get(
            proposal.capability_id, ""
        )
        return CapabilityIntent(
            proposed_capability_id=proposal.capability_id,
            operation=operation,
            arguments={},
            confidence=1.0,
            ambiguity=(
                IntentAmbiguity.CLEAR
                if operation
                else IntentAmbiguity.MISSING_FIELDS
            ),
            rationale_code="LEGACY_ROUTE_PROPOSAL",
        )

    @staticmethod
    def _selected(
        capability_id: str,
        operation: str,
        text: str,
        rationale_code: str,
    ) -> CapabilityIntent:
        return CapabilityIntent(
            proposed_capability_id=capability_id,
            operation=operation,
            entities=(IntentEntity("subject", text, IntentEntitySource.EXPLICIT),),
            arguments={"subject": text},
            confidence=0.9,
            ambiguity=IntentAmbiguity.CLEAR,
            rationale_code=rationale_code,
        )

    @staticmethod
    def _is_coding_request(text: str) -> bool:
        """Require a request-shaped utterance, not two unrelated keywords.

        Capability preparation still validates the typed operation and schema;
        this deterministic interpreter only proposes coding when the user has
        expressed an imperative or explicit desire for a coding-analysis task.
        """
        request_shape = re.search(
            r"^(?:(?:please\s+)?(?:can|could|would|will)\s+you\s+|"
            r"(?:please\s+)?|i\s+(?:want|need|would like)\s+(?:you\s+)?to\s+)"
            r"(?:help\s+(?:me\s+)?(?:to\s+)?)?"
            r"(review|inspect|debug|fix|analy[sz]e|improve|refactor|find|identify|check)\b",
            text,
        )
        if request_shape is None:
            return False
        return bool(
            re.search(
                r"\b(code|coding|python|function|algorithm|implementation|"
                r"software|program|debug|bug|defect|refactor|source)\b",
                text,
            )
        )

    @staticmethod
    def _is_research_specialist_request(text: str) -> bool:
        return bool(
            re.search(
                r"\b(research specialist|specialist.*(evidence|sources)|"
                r"synthesize the sources|analy[sz]e the evidence)\b",
                text,
            )
        )
