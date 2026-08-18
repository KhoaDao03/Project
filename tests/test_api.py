"""Public application API contract tests."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from elly.api.contracts import (
    API_VERSION,
    ChangeModeRequest,
    ConsentDecisionRequest,
    CreateSessionRequest,
    HistoryQuery,
    ProfileCommand,
    ProfileCommandKind,
    ProfileQuery,
    SourcesQuery,
    SubmitRequest,
    TraceQuery,
)
from elly.composition import build_application
from elly.domain.enums import CloudMode, PersistenceMode, TaskStatus
from elly.domain.models import AuditEvent


class V2ApplicationApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.previous = {
            name: os.environ.get(name)
            for name in (
                "ELLY_DB_PATH",
                "ELLY_LOG_LEVEL",
                "ELLY_LOCAL_MODELS_QWEN_DEFAULT_PROVIDER",
                "ELLY_LOCAL_MODELS_QWEN_DEFAULT_MODEL_ID",
                "ELLY_RESEARCH_PROVIDER",
                "ELLY_SPECIALIST_PROVIDER",
            )
        }
        os.environ.update(
            {
                "ELLY_DB_PATH": os.path.join(self.directory.name, "elly.db"),
                "ELLY_LOG_LEVEL": "WARNING",
                "ELLY_LOCAL_MODELS_QWEN_DEFAULT_PROVIDER": "fake",
                "ELLY_LOCAL_MODELS_QWEN_DEFAULT_MODEL_ID": "fake-generalist-v1",
                "ELLY_RESEARCH_PROVIDER": "fixtures",
                "ELLY_SPECIALIST_PROVIDER": "fake",
            }
        )
        self.api = build_application(None)

    def tearDown(self) -> None:
        self.api.close()
        for name, value in self.previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        self.directory.cleanup()

    def test_facade_does_not_expose_internal_collaborators(self) -> None:
        self.assertFalse(hasattr(self.api, "repository"))
        self.assertFalse(hasattr(self.api, "orchestrator"))
        self.assertFalse(hasattr(self.api, "profile"))
        self.assertFalse(hasattr(self.api, "consent"))

    def test_public_contract_is_versioned_and_does_not_import_domain_models(self) -> None:
        self.assertEqual("v2", API_VERSION)
        source = Path("src/elly/api/contracts.py").read_text(encoding="utf-8")
        self.assertNotIn("from ..domain.models", source)

    def test_trace_is_redacted_again_at_the_public_boundary(self) -> None:
        created = self.api.create_session()
        assert created.value is not None
        task = self.api.submit_and_wait(
            SubmitRequest("api-redaction-1", created.value.session_id, "hello")
        )
        assert task.value is not None
        self.api._scope.repository.append_audit(
            AuditEvent(
                task.value.task_id,
                created.value.session_id,
                "adversarial.fixture",
                self.api._scope.clock.now(),
                detail="token=CANARY-DO-NOT-SHOW\nnext-line",
            )
        )
        trace = self.api.get_trace(TraceQuery(task.value.task_id))
        assert trace.value is not None
        rendered = " ".join(event.detail for event in trace.value.events)
        self.assertNotIn("CANARY-DO-NOT-SHOW", rendered)
        self.assertNotIn("\n", rendered)

    def test_session_mode_is_durable_and_conflicts_are_typed(self) -> None:
        created = self.api.create_session(CreateSessionRequest())
        self.assertTrue(created.is_success)
        assert created.value is not None
        session = created.value

        changed = self.api.change_session_mode(
            ChangeModeRequest(session.session_id, session.version, CloudMode.CLOUD_PERMITTED)
        )
        self.assertTrue(changed.is_success)
        assert changed.value is not None
        self.assertEqual(CloudMode.CLOUD_PERMITTED, changed.value.cloud_mode)
        self.assertEqual(2, changed.value.version)

        stale = self.api.change_session_mode(
            ChangeModeRequest(session.session_id, session.version, CloudMode.LOCAL_ONLY)
        )
        self.assertFalse(stale.is_success)
        assert stale.failure is not None
        self.assertEqual("CONFLICT", stale.failure.code.value)

        self.api.close()
        self.api = build_application(None)
        reloaded = self.api.get_session(session.session_id)
        self.assertTrue(reloaded.is_success)
        assert reloaded.value is not None
        self.assertEqual(CloudMode.CLOUD_PERMITTED, reloaded.value.cloud_mode)
        self.assertEqual(2, reloaded.value.version)

    def test_invalid_mode_is_rejected_at_the_public_boundary(self) -> None:
        created = self.api.create_session(CreateSessionRequest())
        self.assertTrue(created.is_success)
        assert created.value is not None
        invalid = self.api.change_session_mode(
            ChangeModeRequest(created.value.session_id, 1, "cloud_permitted")  # type: ignore[arg-type]
        )
        self.assertFalse(invalid.is_success)
        assert invalid.failure is not None
        self.assertEqual("INVALID_INPUT", invalid.failure.code.value)

    def test_submit_status_result_trace_sources_and_profile_use_public_dtos(self) -> None:
        created = self.api.create_session(CreateSessionRequest())
        assert created.value is not None
        session = created.value
        added = self.api.change_profile(
            ProfileCommand(ProfileCommandKind.ADD, "profile-name", "name", "Elly owner")
        )
        self.assertTrue(added.is_success)
        listed = self.api.get_profile(ProfileQuery())
        self.assertTrue(listed.is_success)
        assert listed.value is not None
        self.assertEqual("profile-name", listed.value[0].item_id)

        outcome = self.api.submit_and_wait(
            SubmitRequest("api-local-1", session.session_id, "Explain dependency injection")
        )
        self.assertTrue(outcome.is_success)
        assert outcome.value is not None
        task = outcome.value
        self.assertEqual(TaskStatus.COMPLETED, task.status)
        self.assertEqual("success", task.outcome_code.value)
        self.assertIn("fake-generalist", task.answer)

        status = self.api.get_task(task.task_id)
        self.assertTrue(status.is_success)
        assert status.value is not None
        self.assertEqual(task.task_id, status.value.task_id)
        trace = self.api.get_trace(TraceQuery(task.task_id))
        self.assertTrue(trace.is_success)
        assert trace.value is not None
        self.assertTrue(any(event.event_type == "task.completed" for event in trace.value.events))
        sources = self.api.get_sources(SourcesQuery(task.task_id))
        self.assertTrue(sources.is_success)
        history = self.api.list_history(HistoryQuery())
        self.assertTrue(history.is_success)
        assert history.value is not None
        self.assertTrue(
            any(item.session_id == session.session_id for item in history.value.sessions)
        )

    def test_submit_uses_persisted_session_mode_not_client_supplied_state(self) -> None:
        created = self.api.create_session(
            CreateSessionRequest(
                cloud_mode=CloudMode.LOCAL_ONLY, persistence_mode=PersistenceMode.NO_STORE
            )
        )
        assert created.value is not None
        result = self.api.submit_and_wait(
            SubmitRequest("api-authoritative-1", created.value.session_id, "hello")
        )
        self.assertTrue(result.is_success)
        assert result.value is not None
        self.assertEqual(TaskStatus.COMPLETED, result.value.status)
        task_id = result.value.task_id
        self.api.close()
        self.api = build_application(None)
        persisted = self.api.get_task(task_id)
        self.assertTrue(persisted.is_success)
        assert persisted.value is not None
        self.assertEqual("", persisted.value.answer)

    def test_cloud_consent_can_be_listed_and_decided_through_the_facade(self) -> None:
        created = self.api.create_session(
            CreateSessionRequest(cloud_mode=CloudMode.CLOUD_PERMITTED)
        )
        assert created.value is not None
        pending = self.api.submit_and_wait(
            SubmitRequest(
                "api-consent-1",
                created.value.session_id,
                "Research the latest news about my family",
            )
        )
        self.assertTrue(pending.is_success)
        consents = self.api.list_consents()
        self.assertTrue(consents.is_success)
        assert consents.value is not None
        self.assertEqual(1, len(consents.value))
        proposal = consents.value[0]
        decided = self.api.decide_consent(
            ConsentDecisionRequest(proposal.proposal_id, approve=True)
        )
        self.assertTrue(decided.is_success)
        assert decided.value is not None
        self.assertEqual(TaskStatus.COMPLETED, decided.value.status)
        self.assertEqual((), self.api.list_consents().value)

    def test_api_callback_does_not_duplicate_runtime_result_persistence(self) -> None:
        created = self.api.create_session()
        assert created.value is not None
        repository = self.api._scope.repository
        save_result = repository.save_task_result
        with patch.object(repository, "save_task_result", wraps=save_result) as save:
            completed = self.api.submit_and_wait(
                SubmitRequest(
                    "api-runtime-persistence",
                    created.value.session_id,
                    "hello",
                )
            )
        self.assertTrue(completed.is_success, completed.failure)
        save.assert_called_once()

    def test_repeated_consent_resume_uses_runtime_persistence_owner(self) -> None:
        for index in range(30):
            created = self.api.create_session(
                CreateSessionRequest(cloud_mode=CloudMode.CLOUD_PERMITTED)
            )
            assert created.value is not None
            pending = self.api.submit_and_wait(
                SubmitRequest(
                    f"api-consent-stress-{index}",
                    created.value.session_id,
                    "Research the latest news about my family",
                )
            )
            self.assertTrue(pending.is_success)
            proposals = self.api.list_consents().value
            assert proposals is not None
            proposal = next(
                item for item in proposals if item.task_id == f"task-api-consent-stress-{index}"
            )
            decided = self.api.decide_consent(
                ConsentDecisionRequest(proposal.proposal_id, approve=True)
            )
            self.assertTrue(decided.is_success, decided.failure)

    def test_consent_denial_is_runtime_owned_and_cleans_continuation(self) -> None:
        created = self.api.create_session(
            CreateSessionRequest(cloud_mode=CloudMode.CLOUD_PERMITTED)
        )
        assert created.value is not None
        pending = self.api.submit_and_wait(
            SubmitRequest(
                "api-consent-denied",
                created.value.session_id,
                "Research the latest news about my family",
            )
        )
        self.assertTrue(pending.is_success)
        consents = self.api.list_consents()
        assert consents.value is not None
        self.assertEqual(1, len(consents.value))
        proposal = consents.value[0]
        provider = self.api._scope.research.provider

        repository = self.api._scope.repository
        with patch.object(repository, "save_task_result", wraps=repository.save_task_result) as save:
            denied = self.api.decide_consent(
                ConsentDecisionRequest(proposal.proposal_id, approve=False)
            )

        self.assertTrue(denied.is_success, denied.failure)
        assert denied.value is not None
        self.assertEqual(TaskStatus.BLOCKED, denied.value.status)
        self.assertEqual([], provider.calls)
        self.assertEqual(1, save.call_count)
        self.assertEqual((), self.api.list_consents().value)
        self.assertIsNone(
            self.api._scope.runtime.authorization_task_id(proposal.proposal_id)
        )
        replay = self.api.decide_consent(
            ConsentDecisionRequest(proposal.proposal_id, approve=False)
        )
        self.assertFalse(replay.is_success)
        assert replay.failure is not None
        self.assertEqual("NOT_FOUND", replay.failure.code.value)

    def test_cancellation_while_awaiting_consent_invalidates_without_dispatch(self) -> None:
        created = self.api.create_session(
            CreateSessionRequest(cloud_mode=CloudMode.CLOUD_PERMITTED)
        )
        assert created.value is not None
        pending = self.api.submit_and_wait(
            SubmitRequest(
                "api-consent-cancelled",
                created.value.session_id,
                "Research the latest news about my family",
            )
        )
        assert pending.value is not None
        consents = self.api.list_consents()
        assert consents.value is not None
        proposal = consents.value[0]

        cancelled = self.api.cancel_task(pending.value.task_id)

        self.assertTrue(cancelled.is_success, cancelled.failure)
        assert cancelled.value is not None
        self.assertEqual(TaskStatus.CANCELLED, cancelled.value.status)
        self.assertEqual((), self.api.list_consents().value)
        self.assertIsNone(
            self.api._scope.runtime.authorization_task_id(proposal.proposal_id)
        )
        decision = self.api.decide_consent(
            ConsentDecisionRequest(proposal.proposal_id, approve=True)
        )
        self.assertFalse(decision.is_success)


if __name__ == "__main__":
    unittest.main()
