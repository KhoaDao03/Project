"""Phase 0 characterization tests for the V1.5 behavior being preserved.

These tests intentionally describe the current observable boundary before the
V2 façade, durable sessions, extracted capability workflow, and modular CLI are
introduced. Detailed feature matrices remain in the existing V1/V1.5 suites.
"""

from __future__ import annotations

import os
import tempfile
import threading
import unittest
from datetime import datetime, timezone

from elly.adapters.audit_log import StructuredAuditLog
from elly.adapters.fake_generalist import FailureMode, FakeGeneralist
from elly.adapters.sqlite_repository import SqliteSessionRepository
from elly.adapters.system_clock import FixedClock
from elly.application.authorization import (
    CloudAuthorizationPolicy,
    CloudAuthorizationRequest,
)
from elly.application.routing import RoutingPolicy
from elly.composition import Application, build
from elly.config import load_config
from elly.domain.enums import (
    CloudMode,
    EpistemicStatus,
    OutcomeCode,
    PersistenceMode,
    Route,
    RouteReasonCode,
    TaskStatus,
    ValidationStatus,
)
from elly.domain.errors import CancelledError
from elly.domain.models import Message, RouteRequest, SessionRecord, TaskRequest
from elly.presentation.cli import Cli
from elly.privacy import ConsentWorkflow, PrivacyPolicy

UTC = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


def _request(session_id: str, request_id: str = "req-phase0", text: str = "hello") -> TaskRequest:
    return TaskRequest(
        request_id=request_id,
        session_id=session_id,
        text=text,
        cloud_mode=CloudMode.LOCAL_ONLY,
        persistence_mode=PersistenceMode.STORE_WITH_RETENTION,
        submitted_at=UTC,
    )


class _RecordingGeneralist(FakeGeneralist):
    def __init__(self, events: list[str], *, failure: FailureMode = FailureMode.NONE) -> None:
        super().__init__(failure=failure)
        self.events = events

    def generate(self, request):  # type: ignore[no-untyped-def]
        self.events.append("provider.generate")
        return super().generate(request)


class _RecordingRepository(SqliteSessionRepository):
    def __init__(self, events: list[str]) -> None:
        super().__init__(":memory:")
        self.events = events

    def recent_messages(self, session_id: str, limit: int):  # type: ignore[no-untyped-def]
        self.events.append("recent_messages")
        return super().recent_messages(session_id, limit)

    def start_task(self, task_id: str, session_id: str, at: datetime) -> bool:
        self.events.append("start_task")
        return super().start_task(task_id, session_id, at)

    def claim_operation(self, **kwargs):  # type: ignore[no-untyped-def]
        self.events.append("claim_operation")
        return super().claim_operation(**kwargs)

    def append_audit(self, event):  # type: ignore[no-untyped-def]
        self.events.append(f"audit:{event.event_type}")
        return super().append_audit(event)

    def append_message(self, session_id: str, message: Message) -> None:
        self.events.append(f"message:{message.role}")
        return super().append_message(session_id, message)

    def add_task_provenance(self, task_id: str, reference):  # type: ignore[no-untyped-def]
        self.events.append("add_task_provenance")
        return super().add_task_provenance(task_id, reference)

    def finish_task(self, task_id: str, status: str, at: datetime) -> None:
        self.events.append(f"finish_task:{status}")
        return super().finish_task(task_id, status, at)

    def complete_operation(self, operation_id: str, *, at: datetime) -> None:
        self.events.append("complete_operation")
        return super().complete_operation(operation_id, at=at)


class _RecordingAudit:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.delegate = StructuredAuditLog()

    def append(self, event) -> None:  # type: ignore[no-untyped-def]
        self.events.append(f"audit:{event.event_type}")
        self.delegate.append(event)

    def by_task(self, task_id: str):
        return self.delegate.by_task(task_id)

    def health(self):  # type: ignore[no-untyped-def]
        return self.delegate.health()


class Phase0CliCharacterizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.previous = {
            name: os.environ.get(name)
            for name in (
                "ELLY_DB_PATH",
                "ELLY_LOG_LEVEL",
                "ELLY_LOCAL_MODELS_QWEN_DEFAULT_PROVIDER",
                "ELLY_LOCAL_MODELS_QWEN_DEFAULT_MODEL_ID",
            )
        }
        os.environ.update(
            {
                "ELLY_DB_PATH": os.path.join(self.temp.name, "phase0.db"),
                "ELLY_LOG_LEVEL": "WARNING",
                "ELLY_LOCAL_MODELS_QWEN_DEFAULT_PROVIDER": "fake",
                "ELLY_LOCAL_MODELS_QWEN_DEFAULT_MODEL_ID": "fake-generalist-v1",
            }
        )
        self.app = build(None)
        self.cli = Cli.start(self.app)

    def tearDown(self) -> None:
        self.app.close()
        for name, value in self.previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        self.temp.cleanup()

    def test_current_command_surface_and_local_turn(self) -> None:
        self.assertIn("/status", self.cli.dispatch("/help"))
        self.assertIn("no_store", self.cli.dispatch("/new --no-store"))
        self.assertIn("cloud_permitted", self.cli.dispatch("/mode cloud"))
        self.assertIn("Route: local_conversation", self.cli.dispatch("hello"))
        self.assertIn("Cancellation requested", self.cli.dispatch("/cancel"))


class Phase0RouteAndOutcomeCharacterizationTests(unittest.TestCase):
    def test_current_route_signals_and_reason_codes(self) -> None:
        policy = RoutingPolicy()
        cases = (
            "Explain dependency injection",
            "What is the latest Python release?",
            "debug this Python function",
            "analyze the evidence",
        )
        for text in cases:
            with self.subTest(text=text):
                decision = policy.decide(RouteRequest(request_id="route", text=text))
                self.assertIs(decision.route, Route.LOCAL_CONVERSATION)
                self.assertIs(decision.reason_code, RouteReasonCode.LOCAL_DEFAULT)

    def test_local_success_and_provider_failure_keep_separate_axes(self) -> None:
        for failure, expected_status, expected_outcome in (
            (FailureMode.NONE, TaskStatus.COMPLETED, OutcomeCode.SUCCESS),
            (FailureMode.TRANSIENT, TaskStatus.BLOCKED, OutcomeCode.BLOCKED),
        ):
            with self.subTest(failure=failure):
                repository = SqliteSessionRepository(":memory:")
                repository.apply_migrations()
                repository.create_session(
                    SessionRecord(
                        "phase0-session",
                        PersistenceMode.STORE_WITH_RETENTION,
                        CloudMode.LOCAL_ONLY,
                        UTC,
                    )
                )
                application = Application(
                    config=load_config(None),
                    clock=FixedClock(UTC),
                    generalist=FakeGeneralist(failure=failure),
                    repository=repository,
                    audit=StructuredAuditLog(),
                )
                try:
                    result = application.runtime.handle(
                        _request("phase0-session", request_id=f"req-{failure.value}")
                    ).result
                    self.assertIs(result.task_status, expected_status)
                    self.assertIs(result.outcome_code, expected_outcome)
                    if failure is FailureMode.NONE:
                        self.assertIs(result.validation_status, ValidationStatus.VALIDATED)
                        self.assertIs(result.epistemic_status, EpistemicStatus.INFERRED)
                    else:
                        self.assertIs(result.validation_status, ValidationStatus.REJECTED)
                        self.assertIs(result.epistemic_status, EpistemicStatus.BLOCKED)
                        self.assertIn("Plan status: blocked", result.answer)
                finally:
                    application.close()
                    repository.close()


class Phase0PersistenceOrderCharacterizationTests(unittest.TestCase):
    def test_local_turn_persistence_and_provider_order(self) -> None:
        events: list[str] = []
        repository = _RecordingRepository(events)
        repository.apply_migrations()
        repository.create_session(
            SessionRecord(
                "phase0-order",
                PersistenceMode.STORE_WITH_RETENTION,
                CloudMode.LOCAL_ONLY,
                UTC,
            )
        )
        application = Application(
            config=load_config(None),
            clock=FixedClock(UTC),
            generalist=_RecordingGeneralist(events),
            repository=repository,
            audit=_RecordingAudit(events),
        )
        try:
            result = application.runtime.handle(_request("phase0-order")).result
            self.assertIs(result.task_status, TaskStatus.COMPLETED)
            self.assertLess(events.index("recent_messages"), events.index("start_task"))
            self.assertLess(events.index("start_task"), events.index("claim_operation"))
            self.assertLess(events.index("message:user"), events.index("provider.generate"))
            self.assertLess(events.index("provider.generate"), events.index("audit:task.completed"))
            self.assertLess(events.index("audit:task.completed"), events.index("message:assistant"))
            self.assertIn("finish_task:completed", events)
            self.assertIn("complete_operation", events)
        finally:
            application.close()
            repository.close()


class Phase0ConsentCharacterizationTests(unittest.TestCase):
    def test_owner_specific_cloud_payload_requires_exact_one_time_consent(self) -> None:
        policy = PrivacyPolicy()
        consent = ConsentWorkflow()
        authorization = CloudAuthorizationPolicy()
        payload = "Research the latest news about my family"
        classification = policy.classify(payload)
        pending = authorization.authorize(
            CloudAuthorizationRequest(
                task_id="phase0-consent",
                payload=payload,
                classification=classification,
                cloud_mode=CloudMode.CLOUD_PERMITTED,
                destination="openai_web_search",
                model="fixture-research",
                capability_id="web_research",
                purpose="research",
                consent=consent,
                approval_id=None,
                max_cost=0.25,
                now=UTC,
            )
        )
        self.assertFalse(pending.allowed)
        self.assertEqual(pending.reason_code, "EXACT_CONSENT_REQUIRED")
        self.assertIsNotNone(pending.consent_proposal)
        proposal = pending.consent_proposal
        assert proposal is not None
        consent.approve(proposal.proposal_id, now=UTC)
        approved = authorization.authorize(
            CloudAuthorizationRequest(
                task_id="phase0-consent",
                payload=payload,
                classification=classification,
                cloud_mode=CloudMode.CLOUD_PERMITTED,
                destination="openai_web_search",
                model="fixture-research",
                capability_id="web_research",
                purpose="research",
                consent=consent,
                approval_id=proposal.proposal_id,
                max_cost=0.25,
                now=UTC,
            )
        )
        self.assertTrue(approved.allowed)
        replay = authorization.authorize(
            CloudAuthorizationRequest(
                task_id="phase0-consent",
                payload=payload,
                classification=classification,
                cloud_mode=CloudMode.CLOUD_PERMITTED,
                destination="openai_web_search",
                model="fixture-research",
                capability_id="web_research",
                purpose="research",
                consent=consent,
                approval_id=proposal.proposal_id,
                max_cost=0.25,
                now=UTC,
            )
        )
        self.assertFalse(replay.allowed)
        self.assertEqual(replay.reason_code, "EXACT_CONSENT_REQUIRED")


class Phase0CancellationCharacterizationTests(unittest.TestCase):
    def test_active_cancellation_is_typed_and_interrupts_provider(self) -> None:
        repository = SqliteSessionRepository(":memory:")
        repository.apply_migrations()
        repository.create_session(
            SessionRecord(
                "phase0-cancel",
                PersistenceMode.STORE_WITH_RETENTION,
                CloudMode.LOCAL_ONLY,
                UTC,
            )
        )

        class BlockingGeneralist(FakeGeneralist):
            def __init__(self) -> None:
                super().__init__()
                self.started = threading.Event()
                self.cancelled = threading.Event()

            def generate(self, request):  # type: ignore[no-untyped-def]
                self.started.set()
                self.cancelled.wait(timeout=2)
                raise CancelledError("provider interrupted")

            def cancel(self) -> None:
                self.cancelled.set()

        provider = BlockingGeneralist()
        application = Application(
            config=load_config(None),
            clock=FixedClock(UTC),
            generalist=provider,
            repository=repository,
            audit=StructuredAuditLog(),
        )
        outcomes = []
        worker = threading.Thread(
            target=lambda: outcomes.append(
                application.runtime.handle(
                    _request("phase0-cancel", request_id="req-cancel")
                )
            )
        )
        worker.start()
        try:
            self.assertTrue(provider.started.wait(timeout=1))
            self.assertTrue(application.runtime.cancel_active())
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(len(outcomes), 1)
            self.assertIs(outcomes[0].result.task_status, TaskStatus.CANCELLED)
            self.assertIs(outcomes[0].result.outcome_code, OutcomeCode.CANCELLED)
        finally:
            application.close()
            repository.close()


if __name__ == "__main__":
    unittest.main()
