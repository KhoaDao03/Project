"""Contract tests for the typed optional-capability registry."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from elly.adapters.audit_log import StructuredAuditLog
from elly.adapters.fake_generalist import FakeGeneralist
from elly.adapters.sqlite_repository import SqliteSessionRepository
from elly.adapters.system_clock import FixedClock
from elly.application.capabilities import (
    CapabilityAvailability,
    CapabilityDescriptor,
    CapabilityExecution,
    CapabilityMatch,
    CapabilityRegistry,
    CapabilityRequest,
    CapabilityStatus,
)
from elly.application.conversation import ConversationOrchestrator
from elly.domain.enums import (
    CloudMode,
    EpistemicStatus,
    PersistenceMode,
    Route,
    TaskStatus,
    ValidationStatus,
)
from elly.domain.errors import ConfigInvalidError
from elly.domain.models import (
    ContextManifest,
    RouteProposal,
    RouteRequest,
    SessionRecord,
    TaskRequest,
    TaskResult,
)

UTC = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


class _Capability:
    descriptor = CapabilityDescriptor(
        capability_id="test-capability",
        description="A deterministic test capability",
        routes=(Route.CODING_SPECIALIST,),
        request_schema="test-task-v1",
    )

    def __init__(self, available: bool = True) -> None:
        self._available = available

    def status(self) -> CapabilityStatus:
        return CapabilityStatus(
            CapabilityAvailability.AVAILABLE if self._available else CapabilityAvailability.UNAVAILABLE,
            "" if self._available else "TEST_DISABLED",
        )

    def can_handle(self, _request: CapabilityRequest) -> CapabilityMatch:
        return CapabilityMatch(True, "TEST_MATCH")

    def execute(self, request: CapabilityRequest) -> CapabilityExecution:
        result = TaskResult(
            task_id=request.task_id,
            task_status=TaskStatus.COMPLETED,
            epistemic_status=EpistemicStatus.INFERRED,
            validation_status=ValidationStatus.VALIDATED,
            answer="handled",
            route_summary=Route.CODING_SPECIALIST,
        )
        return CapabilityExecution(result, request.context_manifest)


def _request() -> CapabilityRequest:
    task = TaskRequest(
        request_id="req-1", session_id="session-1", text="test",
        cloud_mode=CloudMode.LOCAL_ONLY,
        persistence_mode=PersistenceMode.STORE_WITH_RETENTION,
        submitted_at=UTC,
    )
    return CapabilityRequest(
        task=task,
        route_request=RouteRequest(request_id="req-1", text="test"),
        context_text="test context",
        context_manifest=ContextManifest((), {}, 32, 1),
    )


class CapabilityRegistryTests(unittest.TestCase):
    def test_registers_descriptor_and_exposes_availability(self) -> None:
        registry = CapabilityRegistry((_Capability(),))
        self.assertEqual(registry.get("test-capability").descriptor.capability_id, "test-capability")  # type: ignore[union-attr]
        self.assertTrue(registry.status("test-capability").available)
        self.assertEqual(len(registry.available()), 1)

    def test_disabled_capability_is_visible_without_being_dispatchable(self) -> None:
        registry = CapabilityRegistry((_Capability(available=False),))
        self.assertFalse(registry.status("test-capability").available)
        self.assertEqual(registry.available(), ())
        self.assertEqual(registry.status("missing").reason_code, "CAPABILITY_NOT_REGISTERED")

    def test_duplicate_ids_are_rejected(self) -> None:
        with self.assertRaises(ConfigInvalidError):
            CapabilityRegistry((_Capability(), _Capability()))

    def test_contract_can_execute_without_orchestrator_changes(self) -> None:
        handler = _Capability()
        registry = CapabilityRegistry((handler,))
        request = _request()
        self.assertTrue(handler.can_handle(request).accepted)
        self.assertEqual(registry.get("test-capability").execute(request).result.answer, "handled")  # type: ignore[union-attr]

    def test_registered_capability_dispatches_without_orchestrator_changes(self) -> None:
        repo = SqliteSessionRepository(":memory:")
        repo.apply_migrations()
        repo.create_session(
            SessionRecord(
                "session-capability",
                PersistenceMode.STORE_WITH_RETENTION,
                CloudMode.LOCAL_ONLY,
                UTC,
            )
        )
        self.addCleanup(repo.close)
        orchestrator = ConversationOrchestrator(
            clock=FixedClock(UTC),
            generalist=FakeGeneralist(),
            repository=repo,
            audit=StructuredAuditLog(),
            context_window=20,
            model_id="unused-local-model",
            max_output_tokens=32,
            capability_registry=CapabilityRegistry((_Capability(),)),
        )
        outcome = orchestrator.handle(
            TaskRequest(
                request_id="capability-request",
                session_id="session-capability",
                text="test",
                cloud_mode=CloudMode.LOCAL_ONLY,
                persistence_mode=PersistenceMode.STORE_WITH_RETENTION,
                submitted_at=UTC,
                route_proposal=RouteProposal(
                    route=Route.CODING_SPECIALIST,
                    capability_id="test-capability",
                    request_schema="test-task-v1",
                ),
            )
        )
        self.assertEqual(outcome.result.answer, "handled")
        self.assertEqual(outcome.result.task_id, "task-capability-request")


if __name__ == "__main__":
    unittest.main()
