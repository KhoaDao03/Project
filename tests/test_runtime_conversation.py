"""Canonical local-conversation lifecycle through the current runtime path."""

from __future__ import annotations

import threading
import unittest
from datetime import datetime, timezone

from elly.adapters.audit_log import StructuredAuditLog
from elly.adapters.fake_generalist import FailureMode, FakeGeneralist
from elly.adapters.sqlite_repository import SqliteSessionRepository
from elly.adapters.system_clock import FixedClock
from elly.composition import Application
from elly.config import load_config
from elly.domain.enums import (
    CloudMode,
    EpistemicStatus,
    PersistenceMode,
    Route,
    TaskStatus,
    ValidationStatus,
)
from elly.domain.errors import CancelledError
from elly.domain.models import SessionRecord, TaskRequest
from elly.presentation.cli import Cli

UTC = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


def _application(
    *,
    failure: FailureMode = FailureMode.NONE,
    persistence: PersistenceMode,
    provider: FakeGeneralist | None = None,
    session_id: str = "runtime-conversation",
) -> tuple[Application, SqliteSessionRepository, StructuredAuditLog, str]:
    repository = SqliteSessionRepository(":memory:")
    repository.apply_migrations()
    repository.create_session(
        SessionRecord(
            session_id=session_id,
            persistence_mode=persistence,
            cloud_mode=CloudMode.LOCAL_ONLY,
            created_at=UTC,
        )
    )
    audit = StructuredAuditLog()
    application = Application(
        config=load_config(None),
        clock=FixedClock(UTC, step_seconds=1),
        generalist=provider or FakeGeneralist(failure=failure),
        repository=repository,
        audit=audit,
    )
    return application, repository, audit, session_id


def _request(session_id: str, text: str, *, persistence: PersistenceMode) -> TaskRequest:
    return TaskRequest(
        request_id=f"req-{text[:6]}",
        session_id=session_id,
        text=text,
        cloud_mode=CloudMode.LOCAL_ONLY,
        persistence_mode=persistence,
        submitted_at=UTC,
    )


class RuntimeConversationTests(unittest.TestCase):
    def test_success_three_axis_and_persistence(self) -> None:
        application, repository, audit, session_id = _application(
            persistence=PersistenceMode.STORE_WITH_RETENTION
        )
        self.addCleanup(application.close)

        outcome = application.runtime.handle(
            _request(session_id, "hello", persistence=PersistenceMode.STORE_WITH_RETENTION)
        )

        self.assertIs(outcome.result.task_status, TaskStatus.COMPLETED)
        self.assertIs(outcome.result.epistemic_status, EpistemicStatus.INFERRED)
        self.assertIs(outcome.result.validation_status, ValidationStatus.VALIDATED)
        self.assertIs(outcome.result.route_summary, Route.LOCAL_CONVERSATION)
        self.assertTrue(outcome.result.answer.startswith("[fake-generalist]"))
        self.assertEqual(
            [message.role for message in repository.recent_messages(session_id, 10)],
            ["user", "assistant"],
        )
        self.assertTrue(
            any(
                event.task_status is TaskStatus.COMPLETED
                for event in audit.by_task(outcome.result.task_id)
            )
        )

    def test_provider_failure_blocks_without_fake_success(self) -> None:
        application, _repository, audit, session_id = _application(
            failure=FailureMode.TRANSIENT,
            persistence=PersistenceMode.STORE_WITH_RETENTION,
        )
        self.addCleanup(application.close)

        outcome = application.runtime.handle(
            _request(session_id, "hello", persistence=PersistenceMode.STORE_WITH_RETENTION)
        )

        self.assertIs(outcome.result.task_status, TaskStatus.BLOCKED)
        self.assertIs(outcome.result.epistemic_status, EpistemicStatus.BLOCKED)
        self.assertIn("Plan status: blocked", outcome.result.answer)
        self.assertTrue(outcome.result.failures)
        self.assertFalse(
            any(
                event.task_status is TaskStatus.COMPLETED
                for event in audit.by_task(outcome.result.task_id)
            )
        )

    def test_no_store_does_not_persist_bodies(self) -> None:
        application, repository, _audit, session_id = _application(
            persistence=PersistenceMode.NO_STORE
        )
        self.addCleanup(application.close)

        application.runtime.handle(
            _request(session_id, "secret", persistence=PersistenceMode.NO_STORE)
        )

        for message in repository.recent_messages(session_id, 10):
            self.assertEqual(message.content, "")

    def test_multi_turn_context_manifest(self) -> None:
        application, _repository, _audit, session_id = _application(
            persistence=PersistenceMode.STORE_WITH_RETENTION
        )
        self.addCleanup(application.close)

        application.runtime.handle(
            _request(session_id, "first", persistence=PersistenceMode.STORE_WITH_RETENTION)
        )
        outcome = application.runtime.handle(
            _request(session_id, "second", persistence=PersistenceMode.STORE_WITH_RETENTION)
        )

        self.assertGreaterEqual(len(outcome.manifest.included_message_ids), 1)

    def test_cancellation_is_not_success_and_preserves_partial_work(self) -> None:
        class CancelledGeneralist(FakeGeneralist):
            def generate(self, _request):  # type: ignore[no-untyped-def]
                raise CancelledError("local generation cancelled", partial_work="received prefix")

        application, _repository, audit, session_id = _application(
            persistence=PersistenceMode.STORE_WITH_RETENTION,
            provider=CancelledGeneralist(),
        )
        self.addCleanup(application.close)

        outcome = application.runtime.handle(
            _request(session_id, "hello", persistence=PersistenceMode.STORE_WITH_RETENTION)
        )

        self.assertIs(outcome.result.task_status, TaskStatus.CANCELLED)
        self.assertTrue(outcome.result.partial_work)
        self.assertIn("cancel", outcome.result.partial_work[0])
        self.assertFalse(
            any(
                event.task_status is TaskStatus.COMPLETED
                for event in audit.by_task(outcome.result.task_id)
            )
        )

    def test_cancel_active_interrupts_the_bound_provider(self) -> None:
        class BlockingGeneralist(FakeGeneralist):
            def __init__(self) -> None:
                super().__init__()
                self.started = threading.Event()
                self.cancelled = threading.Event()

            def generate(self, _request):  # type: ignore[no-untyped-def]
                self.started.set()
                self.cancelled.wait(timeout=2)
                raise CancelledError("provider interrupted")

            def cancel(self) -> None:
                self.cancelled.set()

        provider = BlockingGeneralist()
        application, _repository, _audit, session_id = _application(
            persistence=PersistenceMode.STORE_WITH_RETENTION,
            provider=provider,
        )
        self.addCleanup(application.close)
        outcomes = []
        worker = threading.Thread(
            target=lambda: outcomes.append(
                application.runtime.handle(
                    _request(
                        session_id,
                        "interrupt",
                        persistence=PersistenceMode.STORE_WITH_RETENTION,
                    )
                )
            )
        )

        worker.start()
        self.assertTrue(provider.started.wait(timeout=1))
        self.assertTrue(application.runtime.cancel_active())
        worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(1, len(outcomes))
        self.assertIs(outcomes[0].result.task_status, TaskStatus.CANCELLED)

    def test_malformed_output_blocks_without_completed_audit(self) -> None:
        application, _repository, audit, session_id = _application(
            failure=FailureMode.MALFORMED,
            persistence=PersistenceMode.STORE_WITH_RETENTION,
        )
        self.addCleanup(application.close)

        outcome = application.runtime.handle(
            _request(session_id, "hello", persistence=PersistenceMode.STORE_WITH_RETENTION)
        )

        self.assertIs(outcome.result.task_status, TaskStatus.BLOCKED)
        self.assertIs(outcome.result.epistemic_status, EpistemicStatus.BLOCKED)
        self.assertIsNotNone(outcome.assistant_message)
        self.assertIn("Plan status: blocked", outcome.result.answer)
        self.assertFalse(
            any(
                event.task_status is TaskStatus.COMPLETED
                for event in audit.by_task(outcome.result.task_id)
            )
        )

    def test_permanent_failure_keeps_user_turn_without_assistant_turn(self) -> None:
        application, repository, _audit, session_id = _application(
            failure=FailureMode.PERMANENT,
            persistence=PersistenceMode.STORE_WITH_RETENTION,
        )
        self.addCleanup(application.close)

        outcome = application.runtime.handle(
            _request(session_id, "hello", persistence=PersistenceMode.STORE_WITH_RETENTION)
        )

        self.assertIs(outcome.result.task_status, TaskStatus.BLOCKED)
        self.assertEqual(
            [message.role for message in repository.recent_messages(session_id, 10)],
            ["user", "assistant"],
        )

    def test_success_audit_events_share_the_runtime_task_id(self) -> None:
        application, _repository, audit, session_id = _application(
            persistence=PersistenceMode.STORE_WITH_RETENTION
        )
        self.addCleanup(application.close)

        outcome = application.runtime.handle(
            _request(session_id, "hello", persistence=PersistenceMode.STORE_WITH_RETENTION)
        )
        events = audit.by_task(outcome.result.task_id)

        self.assertIn("task.completed", {event.event_type for event in events})
        self.assertTrue(all(event.task_id == outcome.result.task_id for event in events))

    def test_local_request_reports_canonical_route(self) -> None:
        application, _repository, _audit, session_id = _application(
            persistence=PersistenceMode.STORE_WITH_RETENTION
        )
        self.addCleanup(application.close)

        outcome = application.runtime.handle(
            _request(session_id, "hello", persistence=PersistenceMode.STORE_WITH_RETENTION)
        )

        self.assertIs(outcome.result.route_summary, Route.LOCAL_CONVERSATION)

    def test_new_session_has_no_inherited_context(self) -> None:
        application, repository, _audit, session_a = _application(
            persistence=PersistenceMode.STORE_WITH_RETENTION,
            session_id="session-a",
        )
        self.addCleanup(application.close)
        session_b = "session-b"
        repository.create_session(
            SessionRecord(
                session_id=session_b,
                persistence_mode=PersistenceMode.STORE_WITH_RETENTION,
                cloud_mode=CloudMode.LOCAL_ONLY,
                created_at=UTC,
            )
        )

        application.runtime.handle(
            _request(session_a, "fact from A", persistence=PersistenceMode.STORE_WITH_RETENTION)
        )
        outcome = application.runtime.handle(
            _request(session_b, "hi", persistence=PersistenceMode.STORE_WITH_RETENTION)
        )

        self.assertEqual(len(outcome.manifest.included_message_ids), 0)
        self.assertEqual(repository.recent_messages(session_a, 10)[0].content, "fact from A")

    def test_cli_renders_blocked_on_provider_failure(self) -> None:
        application, _repository, _audit, _session_id = _application(
            failure=FailureMode.TRANSIENT,
            persistence=PersistenceMode.STORE_WITH_RETENTION,
            session_id="s1",
        )
        self.addCleanup(application.close)

        output = Cli.start(application).dispatch("hello")

        self.assertIn("blocked", output.lower())
        self.assertIn("Failure:", output)


if __name__ == "__main__":
    unittest.main()
