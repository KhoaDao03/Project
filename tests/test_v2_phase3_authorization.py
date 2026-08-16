"""Phase 3 contracts for centralized cloud and specialist authorization."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from elly.adapters.audit_log import StructuredAuditLog
from elly.adapters.sqlite_repository import SqliteSessionRepository
from elly.adapters.system_clock import FixedClock
from elly.application.authorization import (
    CloudAuthorizationPolicy,
    CloudAuthorizationRequest,
)
from elly.application.capabilities import CapabilityRegistry
from elly.application.capability_handlers import (
    ResearchCapabilityHandler,
    SpecialistCapabilityHandler,
)
from elly.application.capability_workflow import (
    CapabilityExecutionCommand,
    CapabilityExecutionWorkflow,
)
from elly.application.completion import CompletionService
from elly.application.execution import CancellationToken
from elly.application.research import ResearchPipeline
from elly.application.specialist_policy import (
    SpecialistExecutionPolicy,
    SpecialistPolicyRequest,
)
from elly.application.specialists import SpecialistWorkflow
from elly.domain.enums import (
    CloudMode,
    PersistenceMode,
    Route,
    RouteReasonCode,
    TaskStatus,
)
from elly.domain.models import (
    ContextManifest,
    RouteDecision,
    RouteRequest,
    SessionRecord,
    TaskRequest,
)
from elly.privacy import ConsentWorkflow, PrivacyPolicy
from elly.research.fake_provider import FixtureWebResearchProvider
from elly.specialists.contracts import SpecialistTask
from elly.specialists.fake_provider import FakeSpecialistProvider
from elly.specialists.manifest import SpecialistManifest

UTC = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


def _manifest() -> SpecialistManifest:
    return SpecialistManifest(
        id="coding",
        version="1.0",
        description="coding specialist",
        role="coding",
        capabilities=frozenset({"review"}),
        accepted_inputs=frozenset({"text"}),
        requires_current_data=False,
        preferred_runtime="cloud",
        risk_level="low",
        estimated_cost="medium",
        timeout_seconds=30,
    )


class Phase3AuthorizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = SqliteSessionRepository(":memory:")
        self.repository.apply_migrations()
        self.repository.create_session(
            SessionRecord(
                "phase3-session",
                PersistenceMode.STORE_WITH_RETENTION,
                CloudMode.LOCAL_ONLY,
                UTC,
            )
        )
        self.clock = FixedClock(UTC)
        self.audit = StructuredAuditLog()
        self.completion = CompletionService(
            clock=self.clock,
            repository=self.repository,
            audit=self.audit,
        )
        self.research_provider = FixtureWebResearchProvider()
        self.specialist_provider = FakeSpecialistProvider()
        research = ResearchPipeline(
            provider=self.research_provider,
            clock=self.clock,
            max_results=3,
            timeout_seconds=1,
        )
        specialist = SpecialistWorkflow(
            provider=self.specialist_provider,
            policy=SpecialistExecutionPolicy(max_output_tokens=32),
        )
        self.registry = CapabilityRegistry(
            (
                ResearchCapabilityHandler(
                    research,
                    provider_id="fixtures",
                    model_id="fixture-web-v1",
                ),
                SpecialistCapabilityHandler("coding", _manifest(), specialist),
            )
        )
        self.workflow = CapabilityExecutionWorkflow(
            clock=self.clock,
            capability_registry=self.registry,
            completion=self.completion,
            consent=ConsentWorkflow(),
        )
        self.addCleanup(self.repository.close)

    def _command(
        self,
        *,
        request_id: str,
        text: str,
        route: Route,
        capability_id: str,
        cloud_mode: CloudMode,
    ) -> CapabilityExecutionCommand:
        request = TaskRequest(
            request_id=request_id,
            session_id="phase3-session",
            text=text,
            cloud_mode=cloud_mode,
            persistence_mode=PersistenceMode.STORE_WITH_RETENTION,
            submitted_at=UTC,
        )
        task_id = f"task-{request_id}"
        self.repository.start_task(task_id, request.session_id, UTC)
        return CapabilityExecutionCommand(
            request=request,
            task_id=task_id,
            status=TaskStatus.RUNNING,
            route=route,
            route_request=RouteRequest(
                request_id=request_id,
                text=text,
                cloud_mode=cloud_mode,
            ),
            route_decision=RouteDecision(
                route,
                RouteReasonCode.PROPOSAL_ACCEPTED,
                capability_id=capability_id,
            ),
            context_text=text,
            context_manifest=ContextManifest((), {}, 32, 2),
            cancellation=CancellationToken(),
        )

    def test_shared_cloud_policy_denies_both_capabilities_in_local_mode(self) -> None:
        cases = (
            (
                "research-denied",
                "What is the latest gold price?",
                Route.REGISTERED_CAPABILITY,
                "web_research",
            ),
            (
                "specialist-denied",
                "Review this public Python function",
                Route.REGISTERED_CAPABILITY,
                "coding",
            ),
        )
        for request_id, text, route, capability_id in cases:
            with self.subTest(capability_id=capability_id):
                outcome = self.workflow.execute(
                    self._command(
                        request_id=request_id,
                        text=text,
                        route=route,
                        capability_id=capability_id,
                        cloud_mode=CloudMode.LOCAL_ONLY,
                    )
                )
                self.assertEqual(TaskStatus.BLOCKED, outcome.result.task_status)
        self.assertEqual([], self.research_provider.calls)
        self.assertEqual([], self.specialist_provider.calls)

    def test_shared_cloud_policy_allows_both_public_capabilities_in_cloud_mode(self) -> None:
        cases = (
            (
                "research-allowed",
                "What is the latest gold price?",
                Route.REGISTERED_CAPABILITY,
                "web_research",
            ),
            (
                "specialist-allowed",
                "Review this public Python function",
                Route.REGISTERED_CAPABILITY,
                "coding",
            ),
        )
        for request_id, text, route, capability_id in cases:
            with self.subTest(capability_id=capability_id):
                outcome = self.workflow.execute(
                    self._command(
                        request_id=request_id,
                        text=text,
                        route=route,
                        capability_id=capability_id,
                        cloud_mode=CloudMode.CLOUD_PERMITTED,
                    )
                )
                self.assertEqual(TaskStatus.COMPLETED, outcome.result.task_status)
        self.assertEqual(1, len(self.research_provider.calls))
        self.assertEqual(1, len(self.specialist_provider.calls))

    def test_specialist_policy_is_pure_and_does_not_replace_cloud_policy(self) -> None:
        task = SpecialistTask(
            task_id="task-policy",
            specialist_id="coding",
            goal="review",
            context="Review my private Python function",
            privacy_class="restricted",
        )
        decision = SpecialistExecutionPolicy(max_output_tokens=8).evaluate(
            SpecialistPolicyRequest(task=task, manifest=_manifest())
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(8, decision.output_limit)

    def test_cloud_request_is_typed_and_missing_classification_fails_closed(self) -> None:
        policy = CloudAuthorizationPolicy()
        request = CloudAuthorizationRequest(
            task_id="task-missing-classification",
            payload="Review this public Python function",
            classification=None,
            cloud_mode=CloudMode.CLOUD_PERMITTED,
            destination="specialist",
            model="coding-v1",
            capability_id="coding",
            purpose="execute coding specialist",
            consent=ConsentWorkflow(),
            approval_id=None,
            max_cost=0.25,
            now=UTC,
        )
        decision = policy.authorize(request)
        self.assertFalse(decision.allowed)
        self.assertEqual("CLASSIFICATION_UNAVAILABLE", decision.reason_code)
        self.assertEqual(
            "remote_allowed", PrivacyPolicy().classify(request.payload).classification.value
        )


if __name__ == "__main__":
    unittest.main()
