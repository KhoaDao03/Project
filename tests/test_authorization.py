"""Pure classification and cloud-authorization policy tests."""

from __future__ import annotations

from datetime import datetime, timezone
import unittest

from elly.application.authorization import CloudAuthorizationPolicy
from elly.domain.enums import CloudMode
from elly.privacy import ConsentWorkflow, PrivacyClass, PrivacyPolicy

UTC = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


def _policy():
    return CloudAuthorizationPolicy(), PrivacyPolicy(), ConsentWorkflow()


class AuthorizationTests(unittest.TestCase):
    def test_classification_does_not_grant_authorization(self) -> None:
        auth, privacy, consent = _policy()
        classification = privacy.classify("What is the latest gold price?")
        self.assertEqual(classification.classification, PrivacyClass.REMOTE_ALLOWED)
        decision = auth.authorize(
            task_id="task-1", payload="What is the latest gold price?",
            classification=classification, cloud_mode=CloudMode.LOCAL_ONLY,
            destination="research", model="fixture", capability_id="web_research",
            purpose="research", consent=consent, approval_id=None,
            max_cost=.25, now=UTC,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "CLOUD_MODE_DENIED")

    def test_unclassified_payload_fails_closed_without_provider_call(self) -> None:
        auth, privacy, consent = _policy()
        decision = auth.authorize(
            task_id="task-1", payload="Explain this thing",
            classification=privacy.classify("Explain this thing"),
            cloud_mode=CloudMode.CLOUD_PERMITTED, destination="research", model="fixture",
            capability_id="web_research", purpose="research", consent=consent,
            approval_id=None, max_cost=.25, now=UTC,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "UNCLASSIFIED_CONTENT")

    def test_public_payload_is_allowed_only_after_cloud_mode_check(self) -> None:
        auth, privacy, consent = _policy()
        decision = auth.authorize(
            task_id="task-1", payload="What is the latest gold price?",
            classification=privacy.classify("What is the latest gold price?"),
            cloud_mode=CloudMode.CLOUD_PERMITTED, destination="research", model="fixture",
            capability_id="web_research", purpose="research", consent=consent,
            approval_id=None, max_cost=.25, now=UTC,
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason_code, "PUBLIC_PAYLOAD_ALLOWED")

    def test_owner_specific_payload_requires_exact_scoped_consent(self) -> None:
        auth, privacy, consent = _policy()
        payload = "Research the latest news about my family"
        classification = privacy.classify(payload)
        pending = auth.authorize(
            task_id="task-1", payload=payload, classification=classification,
            cloud_mode=CloudMode.CLOUD_PERMITTED, destination="research", model="fixture",
            capability_id="web_research", purpose="research", consent=consent,
            approval_id=None, max_cost=.25, now=UTC,
        )
        self.assertFalse(pending.allowed)
        self.assertEqual(pending.reason_code, "EXACT_CONSENT_REQUIRED")
        assert pending.consent_proposal is not None
        consent.approve(pending.consent_proposal.proposal_id, now=UTC)
        approved = auth.authorize(
            task_id="task-1", payload=payload, classification=classification,
            cloud_mode=CloudMode.CLOUD_PERMITTED, destination="research", model="fixture",
            capability_id="web_research", purpose="research", consent=consent,
            approval_id=pending.consent_proposal.proposal_id, max_cost=.25, now=UTC,
        )
        self.assertTrue(approved.allowed)

    def test_missing_capability_is_denied_before_consent(self) -> None:
        auth, privacy, consent = _policy()
        decision = auth.authorize(
            task_id="task-1", payload="What is the latest gold price?",
            classification=privacy.classify("What is the latest gold price?"),
            cloud_mode=CloudMode.CLOUD_PERMITTED, destination="research", model="fixture",
            capability_id="web_research", purpose="research", consent=consent,
            approval_id=None, max_cost=.25, now=UTC, capability_available=False,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "CAPABILITY_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
