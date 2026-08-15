"""Pure classification and cloud-authorization policy tests."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from elly.application.authorization import (
    CloudAuthorizationPolicy,
    CloudAuthorizationRequest,
)
from elly.domain.enums import CloudMode
from elly.privacy import ConsentWorkflow, PrivacyClass, PrivacyPolicy

UTC = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


def _policy():
    return CloudAuthorizationPolicy(), PrivacyPolicy(), ConsentWorkflow()


def _request(
    *,
    payload: str,
    classification,
    cloud_mode: CloudMode = CloudMode.CLOUD_PERMITTED,
    consent: ConsentWorkflow | None = None,
    approval_id: str | None = None,
    capability_available: bool = True,
) -> CloudAuthorizationRequest:
    return CloudAuthorizationRequest(
        task_id="task-1",
        payload=payload,
        classification=classification,
        cloud_mode=cloud_mode,
        destination="research",
        model="fixture",
        capability_id="web_research",
        purpose="research",
        consent=consent,
        approval_id=approval_id,
        max_cost=.25,
        now=UTC,
        capability_available=capability_available,
    )


class AuthorizationTests(unittest.TestCase):
    def test_classification_does_not_grant_authorization(self) -> None:
        auth, privacy, consent = _policy()
        classification = privacy.classify("What is the latest gold price?")
        self.assertEqual(classification.classification, PrivacyClass.REMOTE_ALLOWED)
        decision = auth.authorize(
            _request(
                payload="What is the latest gold price?",
                classification=classification,
                cloud_mode=CloudMode.LOCAL_ONLY,
                consent=consent,
            )
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "CLOUD_MODE_DENIED")

    def test_unclassified_payload_fails_closed_without_provider_call(self) -> None:
        auth, privacy, consent = _policy()
        decision = auth.authorize(
            _request(
                payload="Explain this thing",
                classification=privacy.classify("Explain this thing"),
                consent=consent,
            )
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "UNCLASSIFIED_CONTENT")

    def test_public_payload_is_allowed_only_after_cloud_mode_check(self) -> None:
        auth, privacy, consent = _policy()
        decision = auth.authorize(
            _request(
                payload="What is the latest gold price?",
                classification=privacy.classify("What is the latest gold price?"),
                consent=consent,
            )
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason_code, "PUBLIC_PAYLOAD_ALLOWED")

    def test_owner_specific_payload_requires_exact_scoped_consent(self) -> None:
        auth, privacy, consent = _policy()
        payload = "Research the latest news about my family"
        classification = privacy.classify(payload)
        pending = auth.authorize(
            _request(payload=payload, classification=classification, consent=consent)
        )
        self.assertFalse(pending.allowed)
        self.assertEqual(pending.reason_code, "EXACT_CONSENT_REQUIRED")
        assert pending.consent_proposal is not None
        consent.approve(pending.consent_proposal.proposal_id, now=UTC)
        approved = auth.authorize(
            _request(
                payload=payload,
                classification=classification,
                consent=consent,
                approval_id=pending.consent_proposal.proposal_id,
            )
        )
        self.assertTrue(approved.allowed)

    def test_missing_capability_is_denied_before_consent(self) -> None:
        auth, privacy, consent = _policy()
        decision = auth.authorize(
            _request(
                payload="What is the latest gold price?",
                classification=privacy.classify("What is the latest gold price?"),
                consent=consent,
                capability_available=False,
            )
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "CAPABILITY_UNAVAILABLE")

    def test_missing_classification_fails_closed(self) -> None:
        auth, _privacy, consent = _policy()
        decision = auth.authorize(
            _request(payload="Explain this thing", classification=None, consent=consent)
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "CLASSIFICATION_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
