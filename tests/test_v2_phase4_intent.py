"""Phase 4 structured-intent, preparation, and clarification contracts."""

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
    CapabilityPreparation,
    CapabilityRegistry,
    CapabilityRequest,
    CapabilityStatus,
)
from elly.application.capability_workflow import CapabilityExecutionWorkflow
from elly.application.completion import CompletionService
from elly.application.conversation import ConversationOrchestrator
from elly.application.local_conversation import LocalConversationUseCase
from elly.application.routing import RoutingPolicy
from elly.domain.enums import (
    CloudMode,
    EpistemicStatus,
    IntentAmbiguity,
    PersistenceMode,
    Route,
    RouteReasonCode,
    TaskStatus,
    ValidationStatus,
)
from elly.domain.models import (
    CapabilityIntent,
    ContextManifest,
    RouteRequest,
    SessionRecord,
    TaskRequest,
    TaskResult,
)

UTC = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


class _PreparedCapability:
    descriptor = CapabilityDescriptor(
        capability_id="phase4.test",
        description="Phase 4 deterministic capability",
        routes=(Route.REGISTERED_CAPABILITY,),
        request_schema="phase4-test-v1",
        operations=("test.inspect",),
        requires_external_boundary=False,
    )

    def status(self) -> CapabilityStatus:
        return CapabilityStatus(CapabilityAvailability.AVAILABLE)

    def prepare(
        self, intent: CapabilityIntent, _request: CapabilityRequest
    ) -> CapabilityPreparation:
        if intent.operation != "test.inspect":
            return CapabilityPreparation(False, "OPERATION_NOT_SUPPORTED")
        if not intent.arguments.get("subject"):
            return CapabilityPreparation(False, "SUBJECT_REQUIRED", ("subject",))
        return CapabilityPreparation(True, "TEST_PREPARED")

    def can_handle(self, _request: CapabilityRequest) -> CapabilityMatch:
        return CapabilityMatch(True, "TEST_MATCH")

    def execute(self, request: CapabilityRequest) -> CapabilityExecution:
        return CapabilityExecution(
            TaskResult(
                task_id=request.task_id,
                task_status=TaskStatus.COMPLETED,
                epistemic_status=EpistemicStatus.INFERRED,
                validation_status=ValidationStatus.VALIDATED,
                answer="prepared",
                route_summary=Route.REGISTERED_CAPABILITY,
            ),
            request.context_manifest,
        )


class Phase4IntentTests(unittest.TestCase):
    @staticmethod
    def _route_request(text: str) -> RouteRequest:
        return RouteRequest(
            request_id="phase4-request",
            text=text,
            cloud_mode=CloudMode.LOCAL_ONLY,
        )

    def test_structured_intent_resolves_through_the_live_catalog(self) -> None:
        policy = RoutingPolicy(capabilities=CapabilityRegistry((_PreparedCapability(),)))
        decision = policy.decide(
            self._route_request("inspect this implementation"),
            intent=CapabilityIntent(
                proposed_capability_id="phase4.test",
                operation="test.inspect",
                arguments={"subject": "this implementation"},
                confidence=1.0,
                ambiguity=IntentAmbiguity.CLEAR,
                rationale_code="TEST",
            ),
        )
        self.assertEqual(Route.REGISTERED_CAPABILITY, decision.route)
        self.assertEqual("phase4.test", decision.capability_id)

    def test_misleading_specialist_wording_is_clarified_not_executed(self) -> None:
        decision = RoutingPolicy(capabilities=CapabilityRegistry()).decide(
            self._route_request("Can a specialist help with this?"),
            intent=CapabilityIntent(
                proposed_capability_id=None,
                operation="task.unspecified",
                confidence=0.2,
                ambiguity=IntentAmbiguity.AMBIGUOUS,
                rationale_code="TEST_AMBIGUOUS",
            ),
        )
        self.assertTrue(decision.clarification_required)
        self.assertEqual(RouteReasonCode.CATALOG_AMBIGUOUS, decision.reason_code)

    def test_unrelated_keyword_combinations_do_not_select_coding(self) -> None:
        for text in (
            "I found a software review in a book.",
            "The source code is printed on the package; find the store hours.",
        ):
            with self.subTest(text=text):
                decision = RoutingPolicy(
                    capabilities=CapabilityRegistry((_PreparedCapability(),))
                ).decide(self._route_request(text))
                self.assertNotEqual("phase4.test", decision.capability_id)

    def test_unknown_capability_and_operation_are_rejected_deterministically(self) -> None:
        registry = CapabilityRegistry((_PreparedCapability(),))
        policy = RoutingPolicy(capabilities=registry)
        unknown = policy.decide(
            self._route_request("inspect this"),
            intent=CapabilityIntent(
                proposed_capability_id="missing",
                operation="test.inspect",
                arguments={"subject": "inspect this"},
                confidence=1.0,
                ambiguity=IntentAmbiguity.CLEAR,
                rationale_code="TEST",
            ),
        )
        unsupported = policy.decide(
            self._route_request("inspect this"),
            intent=CapabilityIntent(
                proposed_capability_id="phase4.test",
                operation="test.delete",
                arguments={"subject": "inspect this"},
                confidence=1.0,
                ambiguity=IntentAmbiguity.CLEAR,
                rationale_code="TEST",
            ),
        )
        self.assertEqual(RouteReasonCode.SELECTION_PROPOSAL_REJECTED, unknown.reason_code)
        self.assertEqual("CAPABILITY_NOT_REGISTERED", unknown.diagnostic)
        self.assertEqual(RouteReasonCode.SELECTION_PROPOSAL_REJECTED, unsupported.reason_code)
        self.assertEqual("OPERATION_UNSUPPORTED", unsupported.diagnostic)

    def test_prepare_validates_input_without_provider_execution(self) -> None:
        handler = _PreparedCapability()
        request = CapabilityRequest(
            task=TaskRequest(
                request_id="phase4-prepare",
                session_id="session",
                text="inspect",
                cloud_mode=CloudMode.LOCAL_ONLY,
                persistence_mode=PersistenceMode.STORE_WITH_RETENTION,
                submitted_at=UTC,
            ),
            route_request=self._route_request("inspect"),
            context_text="inspect",
            context_manifest=ContextManifest((), {}, 16, 1),
        )
        missing = handler.prepare(
            CapabilityIntent(
                proposed_capability_id="phase4.test",
                operation="test.inspect",
                arguments={},
                confidence=1.0,
                ambiguity=IntentAmbiguity.CLEAR,
                rationale_code="TEST",
            ),
            request,
        )
        self.assertFalse(missing.accepted)
        self.assertEqual(("subject",), missing.clarification_fields)

    def test_unmatched_request_uses_local_conversation_without_provider_capability_call(
        self,
    ) -> None:
        repository = SqliteSessionRepository(":memory:")
        repository.apply_migrations()
        repository.create_session(
            SessionRecord(
                "phase4-session",
                PersistenceMode.STORE_WITH_RETENTION,
                CloudMode.LOCAL_ONLY,
                UTC,
            )
        )
        audit = StructuredAuditLog()
        clock = FixedClock(UTC)
        completion = CompletionService(
            clock=clock,
            repository=repository,
            audit=audit,
        )
        orchestrator = ConversationOrchestrator(
            clock=clock,
            repository=repository,
            audit=audit,
            context_window=20,
            local_conversation=LocalConversationUseCase(
                generalist=FakeGeneralist(),
                model_id="phase4-local",
                max_output_tokens=16,
            ),
            completion=completion,
            capability_workflow=CapabilityExecutionWorkflow(
                clock=clock,
                capability_registry=CapabilityRegistry((_PreparedCapability(),)),
                completion=completion,
            ),
            routing_policy=RoutingPolicy(capabilities=CapabilityRegistry((_PreparedCapability(),))),
        )
        try:
            outcome = orchestrator.handle(
                TaskRequest(
                    request_id="phase4-ambiguous",
                    session_id="phase4-session",
                    text="Can a specialist help with this?",
                    cloud_mode=CloudMode.LOCAL_ONLY,
                    persistence_mode=PersistenceMode.STORE_WITH_RETENTION,
                    submitted_at=UTC,
                )
            )
            self.assertEqual("success", outcome.result.outcome_code.value)
            self.assertEqual("completed", repository.task_status("task-phase4-ambiguous"))
            self.assertFalse(
                any(
                    event.event_type == "intent.clarification_required"
                    for event in audit.by_task("task-phase4-ambiguous")
                )
            )
        finally:
            repository.close()


if __name__ == "__main__":
    unittest.main()
