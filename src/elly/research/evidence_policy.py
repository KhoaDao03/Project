"""Deterministic claim-level evidence eligibility policy."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime

from ..application.execution import CancellationToken
from ..domain.errors import CancelledError, EllyError
from ..domain.models import EvidenceObject
from ..ports.document_retrieval import DocumentRetrievalPort


@dataclass(frozen=True, slots=True)
class EvidenceEligibility:
    evidence: EvidenceObject | None
    reason_code: str


class EvidencePolicy:
    """Requires an identifiable supporting passage before a claim is known."""

    def __init__(
        self,
        *,
        retriever: DocumentRetrievalPort | None = None,
        retrieval_timeout_seconds: float = 10.0,
    ) -> None:
        self._retriever = retriever
        self._retrieval_timeout_seconds = retrieval_timeout_seconds

    def evaluate(
        self,
        evidence: EvidenceObject,
        *,
        provider_answer: str,
        now: datetime,
        cancellation: CancellationToken | None = None,
        current_information: bool = False,
    ) -> EvidenceEligibility:
        passage = evidence.supporting_passage.strip()
        if not passage:
            # Search snippets and provider metadata remain discovery leads.  They
            # are intentionally not promoted even when the provider repeats the
            # same text in its answer; only an explicit claim-level passage or a
            # passage independently found in retrieved content is eligible.
            return EvidenceEligibility(None, f"{evidence.evidence_id}: no supporting passage")
        if current_information and evidence.freshness == "source_time_unknown":
            return EvidenceEligibility(
                None, f"{evidence.evidence_id}: source publication time unavailable"
            )

        if self._retriever is None:
            return EvidenceEligibility(
                replace(
                    evidence,
                    supporting_passage=passage,
                    validation_status="provider_passage",
                    safety_flags=tuple(dict.fromkeys(evidence.safety_flags + ("claim_level_passage",))),
                ),
                "eligible_provider_passage",
            )

        try:
            if cancellation is not None:
                document = self._retriever.retrieve(
                    evidence,
                    timeout_seconds=self._retrieval_timeout_seconds,
                    cancellation=cancellation,
                )
            else:
                document = self._retriever.retrieve(
                    evidence, timeout_seconds=self._retrieval_timeout_seconds
                )
        except CancelledError:
            raise
        except (OSError, ValueError):
            return EvidenceEligibility(
                None, f"{evidence.evidence_id}: retrieval_failed"
            )
        except EllyError as exc:
            return EvidenceEligibility(None, f"{evidence.evidence_id}: {exc.error_class.value}")
        if not document.content.strip():
            return EvidenceEligibility(None, f"{evidence.evidence_id}: empty source content")
        if not self._contains_passage(document.content, passage):
            return EvidenceEligibility(
                None, f"{evidence.evidence_id}: passage not found in retrieved source"
            )
        return EvidenceEligibility(
            replace(
                evidence,
                supporting_passage=passage,
                content_hash=document.content_hash,
                retrieved_at=document.retrieved_at,
                validation_status="validated_passage",
                safety_flags=tuple(dict.fromkeys(evidence.safety_flags + ("retrieved_document",))),
            ),
            "eligible_retrieved_passage",
        )

    @staticmethod
    def _contains_passage(content: str, passage: str) -> bool:
        def normalize(value: str) -> str:
            return " ".join(re.sub(r"\s+", " ", value).split()).casefold()

        return normalize(passage) in normalize(content)
