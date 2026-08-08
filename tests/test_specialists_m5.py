"""M5 privacy, consent, specialist-contract, and OpenAI adapter tests."""

from __future__ import annotations

import json
from io import BytesIO
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from elly.adapters.openai_specialist import OpenAISpecialistProvider
from elly.domain.enums import CloudMode
from elly.domain.errors import (
    AuthenticationProviderError, ConsentRequiredError, ConfigInvalidError,
    ModelUnavailableError, PermissionDeniedError, ProviderQuotaError,
    ProviderTimeoutError, RateLimitProviderError,
)
from elly.privacy import ConsentWorkflow, PrivacyClass, classify_payload
from elly.specialists.contracts import SpecialistResult, SpecialistTask
from elly.specialists.fake_provider import FakeSpecialistProvider
from elly.specialists.manifest import SpecialistManifest
from elly.application.specialists import SpecialistWorkflow

UTC = datetime(2026, 8, 4, tzinfo=timezone.utc)


def _manifest(role: str = "coding", *, tools=frozenset()) -> SpecialistManifest:
    return SpecialistManifest(
        id=role, version="1.0", description=role, role=role,
        capabilities=frozenset({"review"}), accepted_inputs=frozenset({"text"}),
        requires_current_data=False, preferred_runtime="cloud", risk_level="low",
        estimated_cost="medium", timeout_seconds=30, allowed_tools=tools,
    )


def _task(context: str = "Review this public function") -> SpecialistTask:
    return SpecialistTask(task_id="task-1", specialist_id="coding", goal="review", context=context, privacy_class=classify_payload(context).value)


class PrivacyTests(unittest.TestCase):
    def test_approved_mapping_is_conservative(self) -> None:
        self.assertIs(classify_payload("Review this public function"), PrivacyClass.REMOTE_ALLOWED)
        self.assertIs(classify_payload("Review my private notes"), PrivacyClass.LOCAL)
        self.assertIs(classify_payload("api_key=do-not-send"), PrivacyClass.RESTRICTED)
        self.assertIs(classify_payload("Review this function"), PrivacyClass.UNCLASSIFIED)

    def test_public_market_index_is_remote_allowed_but_owner_portfolio_is_local(self) -> None:
        self.assertIs(
            classify_payload("Tell me the status of the S&P500 index"),
            PrivacyClass.REMOTE_ALLOWED,
        )
        self.assertIs(
            classify_payload("Tell me the status of my S&P500 portfolio"),
            PrivacyClass.LOCAL,
        )

    def test_public_commodity_price_is_remote_allowed_but_owner_holdings_are_local(self) -> None:
        self.assertIs(
            classify_payload("What is the price of gold?"),
            PrivacyClass.REMOTE_ALLOWED,
        )
        self.assertIs(
            classify_payload("What is my gold portfolio worth?"),
            PrivacyClass.LOCAL,
        )


class ConsentTests(unittest.TestCase):
    def test_exact_hash_approval_and_mutation_binding(self) -> None:
        workflow = ConsentWorkflow(ttl_seconds=60)
        proposal = workflow.propose(task_id="t", provider="openai", model="m", purpose="review", payload="my code", categories=("local",), max_cost=.25, now=UTC)
        workflow.approve(proposal.proposal_id, now=UTC)
        self.assertTrue(workflow.check(proposal_id=proposal.proposal_id, payload="my code", now=UTC))
        self.assertFalse(workflow.check(proposal_id=proposal.proposal_id, payload="my changed code", now=UTC))

    def test_approval_is_one_shot_and_bound_to_provider_metadata(self) -> None:
        workflow = ConsentWorkflow(ttl_seconds=60)
        proposal = workflow.propose(
            task_id="t", provider="openai", model="approved-model", purpose="review",
            payload="my code", categories=("local",), max_cost=.25, now=UTC,
        )
        workflow.approve(proposal.proposal_id, now=UTC)
        self.assertFalse(workflow.check(
            proposal_id=proposal.proposal_id, payload="my code", provider="openai",
            model="changed-model", purpose="review", categories=("local",), max_cost=.25,
            now=UTC,
        ))
        self.assertTrue(workflow.check(
            proposal_id=proposal.proposal_id, payload="my code", provider="openai",
            model="approved-model", purpose="review", categories=("local",), max_cost=.25,
            now=UTC,
        ))
        self.assertFalse(workflow.check(
            proposal_id=proposal.proposal_id, payload="my code", provider="openai",
            model="approved-model", purpose="review", categories=("local",), max_cost=.25,
            now=UTC,
        ))

    def test_approval_cannot_be_reused_for_another_capability(self) -> None:
        workflow = ConsentWorkflow(ttl_seconds=60)
        proposal = workflow.propose(
            task_id="t", provider="openai", model="m", purpose="same-purpose",
            capability_id="web_research", payload="my code", categories=("local",),
            max_cost=.25, now=UTC,
        )
        workflow.approve(proposal.proposal_id, now=UTC)
        self.assertFalse(workflow.check(
            proposal_id=proposal.proposal_id, payload="my code", provider="openai",
            model="m", purpose="same-purpose", capability_id="coding",
            categories=("local",), max_cost=.25, now=UTC,
        ))
        self.assertTrue(workflow.check(
            proposal_id=proposal.proposal_id, payload="my code", provider="openai",
            model="m", purpose="same-purpose", capability_id="web_research",
            categories=("local",), max_cost=.25, now=UTC,
        ))

    def test_consent_preview_redacts_the_secret_value(self) -> None:
        workflow = ConsentWorkflow()
        proposal = workflow.propose(
            task_id="t", provider="openai", model="m", purpose="review",
            payload="api_key=CANARY-DO-NOT-SHOW", categories=("restricted",), max_cost=.25,
            now=UTC,
        )
        self.assertNotIn("CANARY-DO-NOT-SHOW", proposal.redacted_preview)

    def test_expired_approval_is_invalid(self) -> None:
        workflow = ConsentWorkflow(ttl_seconds=1)
        proposal = workflow.propose(task_id="t", provider="openai", model="m", purpose="review", payload="my code", categories=("local",), max_cost=.25, now=UTC)
        workflow.approve(proposal.proposal_id, now=UTC)
        self.assertFalse(workflow.check(proposal_id=proposal.proposal_id, payload="my code", now=UTC + timedelta(seconds=2)))


class SpecialistWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = FakeSpecialistProvider()
        self.consent = ConsentWorkflow()
        self.workflow = SpecialistWorkflow(provider=self.provider, consent=self.consent)

    def test_public_payload_proceeds_without_consent(self) -> None:
        result = self.workflow.execute(task=_task(), manifest=_manifest(), cloud_mode=CloudMode.CLOUD_PERMITTED, now=UTC)
        self.assertEqual(result.result.status, "inferred")
        self.assertEqual(len(self.provider.calls), 1)

    def test_local_payload_requires_then_accepts_exact_consent(self) -> None:
        local_task = _task("Review my private code")
        with self.assertRaises(ConsentRequiredError) as caught:
            self.workflow.execute(task=local_task, manifest=_manifest(), cloud_mode=CloudMode.CLOUD_PERMITTED, now=UTC)
        proposal = caught.exception.proposal
        self.consent.approve(proposal.proposal_id, now=UTC)
        approved = SpecialistTask(**{**local_task.__dict__} if hasattr(local_task, "__dict__") else {
            "task_id": local_task.task_id, "specialist_id": local_task.specialist_id,
            "goal": local_task.goal, "context": local_task.context,
            "privacy_class": local_task.privacy_class, "approval_id": proposal.proposal_id,
        })
        result = self.workflow.execute(task=approved, manifest=_manifest(), cloud_mode=CloudMode.CLOUD_PERMITTED, now=UTC)
        self.assertEqual(result.result.status, "inferred")

    def test_restricted_local_only_and_tools_are_blocked(self) -> None:
        with self.assertRaises(PermissionDeniedError):
            self.workflow.execute(task=_task("api_key=secret"), manifest=_manifest(), cloud_mode=CloudMode.CLOUD_PERMITTED, now=UTC)
        with self.assertRaises(PermissionDeniedError):
            self.workflow.execute(task=_task(), manifest=_manifest(), cloud_mode=CloudMode.LOCAL_ONLY, now=UTC)
        with self.assertRaises(PermissionDeniedError):
            self.workflow.execute(task=_task(), manifest=_manifest(tools=frozenset({"shell"})), cloud_mode=CloudMode.CLOUD_PERMITTED, now=UTC)

    def test_high_impact_action_and_malformed_result_are_blocked(self) -> None:
        action = FakeSpecialistProvider(result=SpecialistResult(status="known", answer="answer", recommended_action="execute this command"))
        with self.assertRaises(PermissionDeniedError):
            SpecialistWorkflow(provider=action, consent=self.consent).execute(task=_task(), manifest=_manifest(), cloud_mode=CloudMode.CLOUD_PERMITTED, now=UTC)
        malformed = FakeSpecialistProvider(fail="malformed")
        with self.assertRaises(Exception):
            SpecialistWorkflow(provider=malformed, consent=self.consent).execute(task=_task(), manifest=_manifest(), cloud_mode=CloudMode.CLOUD_PERMITTED, now=UTC)

    def test_clearly_out_of_scope_task_is_rejected_before_provider(self) -> None:
        with self.assertRaises(PermissionDeniedError):
            self.workflow.execute(
                task=_task("Use this coding specialist for a public medical diagnosis"),
                manifest=_manifest(), cloud_mode=CloudMode.CLOUD_PERMITTED, now=UTC,
            )
        self.assertEqual([], self.provider.calls)

    def test_unrelated_task_is_rejected_before_provider(self) -> None:
        with self.assertRaises(PermissionDeniedError):
            self.workflow.execute(
                task=_task("Plan a public garden party"), manifest=_manifest(),
                cloud_mode=CloudMode.CLOUD_PERMITTED, now=UTC,
            )
        self.assertEqual([], self.provider.calls)

    def test_fake_output_token_ceiling_returns_partial(self) -> None:
        provider = FakeSpecialistProvider(
            result=SpecialistResult(status="known", answer="one two three four")
        )
        workflow = SpecialistWorkflow(
            provider=provider, consent=ConsentWorkflow(), max_output_tokens=2
        )
        result = workflow.execute(
            task=_task(), manifest=_manifest(),
            cloud_mode=CloudMode.CLOUD_PERMITTED, now=UTC,
        ).result
        self.assertEqual("partial", result.status)
        self.assertEqual("one two", result.answer)
        self.assertTrue(result.truncated)


class _Response:
    def __init__(self, value: dict) -> None:
        self.value = value
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def read(self): return json.dumps(self.value).encode()


class OpenAISpecialistAdapterTests(unittest.TestCase):
    def test_request_is_structured_store_false_and_tool_free(self) -> None:
        body = {"output_text": json.dumps({"status": "known", "answer": "ok", "assumptions": [], "uncertainties": [], "key_evidence": [], "sources": [], "recommended_action": None})}
        provider = OpenAISpecialistProvider(api_key="test-key")
        task = _task()
        with patch("elly.adapters.openai_specialist.urllib.request.urlopen", return_value=_Response(body)) as mocked:
            result = provider.execute(task, model="gpt-5.6-luna", prompt_version="v1", output_limit=100)
        self.assertEqual(result.status, "known")
        request_body = json.loads(mocked.call_args.args[0].data)
        self.assertFalse(request_body["store"])
        self.assertNotIn("tools", request_body)
        self.assertEqual(request_body["model"], "gpt-5.6-luna")

    def test_wrong_typed_structured_fields_are_rejected_not_coerced(self) -> None:
        body = {"output_text": json.dumps({
            "status": "known", "answer": 123, "assumptions": [], "uncertainties": [],
            "key_evidence": [], "sources": [], "recommended_action": None,
        })}
        provider = OpenAISpecialistProvider(api_key="test-key")
        with patch("elly.adapters.openai_specialist.urllib.request.urlopen", return_value=_Response(body)):
            with self.assertRaises(Exception):
                provider.execute(_task(), model="gpt-5.6-luna", prompt_version="v1", output_limit=100)

    def test_provider_incomplete_status_is_preserved_as_truncation(self) -> None:
        body = {
            "status": "incomplete",
            "output_text": json.dumps({
                "status": "partial", "answer": "bounded partial", "assumptions": [],
                "uncertainties": ["output ceiling reached"], "key_evidence": [],
                "sources": [], "recommended_action": None,
            }),
        }
        provider = OpenAISpecialistProvider(api_key="test-key")
        with patch(
            "elly.adapters.openai_specialist.urllib.request.urlopen",
            return_value=_Response(body),
        ):
            result = provider.execute(
                _task(), model="gpt-5.6-luna", prompt_version="v1", output_limit=10
            )
        self.assertTrue(result.truncated)
        self.assertEqual("partial", result.status)

    def test_false_action_success_claim_is_rejected(self) -> None:
        provider = FakeSpecialistProvider(result=SpecialistResult(status="known", answer="I deleted the file."))
        with self.assertRaises(ConfigInvalidError):
            SpecialistWorkflow(provider=provider, consent=ConsentWorkflow()).execute(
                task=_task(), manifest=_manifest(), cloud_mode=CloudMode.CLOUD_PERMITTED, now=UTC,
            )

    def test_distinct_http_and_timeout_failures(self) -> None:
        provider = OpenAISpecialistProvider(api_key="test-key")

        def http_error(code: int, error_code: str = ""):
            body = BytesIO(json.dumps({"error": {"code": error_code}}).encode())
            return __import__("urllib.error").error.HTTPError(
                "https://api.openai.com/v1/responses", code, "failure", {}, body
            )

        cases = (
            (http_error(401), AuthenticationProviderError),
            (http_error(404), ModelUnavailableError),
            (http_error(429), RateLimitProviderError),
            (http_error(429, "insufficient_quota"), ProviderQuotaError),
            (TimeoutError(), ProviderTimeoutError),
        )
        for failure, expected in cases:
            with self.subTest(expected=expected.__name__):
                with patch(
                    "elly.adapters.openai_specialist.urllib.request.urlopen",
                    side_effect=failure,
                ):
                    with self.assertRaises(expected):
                        provider.execute(
                            _task(), model="gpt-5.6-luna",
                            prompt_version="v1", output_limit=100,
                        )


if __name__ == "__main__":
    unittest.main()
