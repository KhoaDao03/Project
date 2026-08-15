"""Claim-level evidence eligibility tests."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from elly.domain.errors import PermanentProviderError
from elly.domain.models import EvidenceObject
from elly.ports.document_retrieval import RetrievedDocument
from elly.research.evidence_policy import EvidencePolicy

UTC = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


def _evidence(*, snippet: str = "", passage: str = "") -> EvidenceObject:
    return EvidenceObject(
        evidence_id="E1", url="https://example.com/source",
        canonical_url="https://example.com/source", title="Source",
        publisher="Example", retrieved_at=UTC, snippet=snippet,
        supporting_passage=passage,
    )


class _Retriever:
    def __init__(self, content: str = "") -> None:
        self.content = content

    def retrieve(self, evidence, *, timeout_seconds):
        if self.content == "ERROR":
            raise PermanentProviderError("page unavailable")
        raw = self.content.encode()
        import hashlib
        return RetrievedDocument(
            canonical_url=evidence.canonical_url,
            content=self.content,
            retrieved_at=UTC,
            content_hash=hashlib.sha256(raw).hexdigest(),
        )


class EvidencePolicyTests(unittest.TestCase):
    def test_metadata_or_misleading_snippet_is_not_eligible(self) -> None:
        result = EvidencePolicy().evaluate(
            _evidence(snippet="Misleading search headline"),
            provider_answer="The provider returned a different unverified summary.",
            now=UTC,
        )
        self.assertIsNone(result.evidence)

    def test_exact_provider_snippet_is_still_not_claim_level_evidence(self) -> None:
        result = EvidencePolicy().evaluate(
            _evidence(snippet="The verified passage."),
            provider_answer="The verified passage.",
            now=UTC,
        )
        self.assertIsNone(result.evidence)

    def test_retrieved_document_must_contain_supporting_passage(self) -> None:
        policy = EvidencePolicy(retriever=_Retriever("Page says another thing."))
        result = policy.evaluate(
            _evidence(passage="The claim."), provider_answer="The claim.", now=UTC
        )
        self.assertIsNone(result.evidence)

    def test_retrieved_passage_gets_hash_and_validation_status(self) -> None:
        policy = EvidencePolicy(retriever=_Retriever("The claim. Extra context."))
        result = policy.evaluate(
            _evidence(passage="The claim."), provider_answer="The claim.", now=UTC
        )
        self.assertIsNotNone(result.evidence)
        assert result.evidence is not None
        self.assertEqual(result.evidence.validation_status, "validated_passage")
        self.assertTrue(result.evidence.content_hash)

    def test_inaccessible_source_is_ineligible(self) -> None:
        policy = EvidencePolicy(retriever=_Retriever("ERROR"))
        result = policy.evaluate(
            _evidence(passage="The claim."), provider_answer="The claim.", now=UTC
        )
        self.assertIsNone(result.evidence)


if __name__ == "__main__":
    unittest.main()
