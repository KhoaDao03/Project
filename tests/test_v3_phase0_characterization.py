"""V3 Phase 0 characterization of the closed V2.5 application surface."""

from __future__ import annotations

import ast
import os
import sqlite3
import tempfile
import threading
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from elly.adapters.audit_log import StructuredAuditLog
from elly.adapters.fake_generalist import FakeGeneralist
from elly.adapters.sqlite_repository import SqliteSessionRepository
from elly.adapters.system_clock import FixedClock
from elly.api.contracts import CreateSessionRequest, SubmitRequest, TraceQuery
from elly.application.authorization import (
    CloudAuthorizationPolicy,
    CloudAuthorizationRequest,
)
from elly.application.capabilities import (
    CapabilityAvailability,
    CapabilityDescriptor,
    CapabilityExecution,
    CapabilityMatch,
    CapabilityPreparation,
    CapabilityRegistry,
    CapabilityRequest,
    CapabilityRoutingDescriptor,
    CapabilityStatus,
    FreshnessSupport,
    OperationIntentContract,
)
from elly.application.routing import RoutingPolicy
from elly.composition import Application, build_application
from elly.config import load_config
from elly.domain.enums import (
    ActionCategory,
    CloudMode,
    OutcomeCode,
    PersistenceMode,
    Route,
    RouteReasonCode,
    TaskStatus,
)
from elly.domain.errors import CancelledError
from elly.domain.models import RouteRequest, SessionRecord, TaskRequest
from elly.privacy import ConsentWorkflow, PrivacyPolicy

ROOT = Path(__file__).resolve().parents[1]
UTC = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


def _task_request(
    session_id: str,
    request_id: str,
    text: str = "Explain dependency injection",
) -> TaskRequest:
    return TaskRequest(
        request_id=request_id,
        session_id=session_id,
        text=text,
        cloud_mode=CloudMode.LOCAL_ONLY,
        persistence_mode=PersistenceMode.STORE_WITH_RETENTION,
        submitted_at=UTC,
    )


class _CatalogCapability:
    """Provider-free capability used to characterize the V2.5 registry seam."""

    def __init__(self) -> None:
        operation = OperationIntentContract(
            operation_id="security.inspect",
            description="Inspect a bounded security-control request",
            domains=("security",),
            accepted_inputs=("text",),
            required_entities=(),
            freshness=FreshnessSupport.STATIC,
            effect=ActionCategory.NONE,
            specificity=85,
            examples=("Inspect security controls",),
        )
        self.descriptor = CapabilityDescriptor(
            capability_id="security_review",
            description="Provider-free security inspection capability",
            routes=(Route.REGISTERED_CAPABILITY,),
            request_schema="security-review-v1",
            operations=(operation.operation_id,),
            routing=CapabilityRoutingDescriptor(
                capability_id="security_review",
                description="Provider-free security inspection capability",
                operations=(operation,),
                priority=70,
            ),
        )

    def status(self) -> CapabilityStatus:
        return CapabilityStatus(CapabilityAvailability.AVAILABLE)

    def can_handle(self, _request: CapabilityRequest) -> CapabilityMatch:
        return CapabilityMatch(True, "TEST_MATCH")

    def prepare(self, _intent: object, _request: CapabilityRequest) -> CapabilityPreparation:
        return CapabilityPreparation(True, "TEST_PREPARED")

    def propose_action(self, _request: CapabilityRequest):  # type: ignore[no-untyped-def]
        return self.descriptor.declared_action

    def execute(self, _request: CapabilityRequest) -> CapabilityExecution:
        raise AssertionError("Phase 0 routing characterization must not execute")


class V3Phase0BoundaryTests(unittest.TestCase):
    def test_current_configuration_and_orchestration_owners_are_explicit(self) -> None:
        composition = (ROOT / "src/elly/composition.py").read_text(encoding="utf-8")
        config = (ROOT / "src/elly/config.py").read_text(encoding="utf-8")
        conversation = ROOT / "src/elly/application/conversation.py"

        self.assertIn("from .config import Config, load_config", composition)
        self.assertIn("AssistantRuntime", composition)
        self.assertIn("OllamaGeneralist", composition)
        self.assertIn("def load_config", config)
        self.assertFalse(conversation.exists())
        self.assertNotIn("ConversationOrchestrator", composition)

    def test_generic_routing_has_no_provider_or_storage_boundary(self) -> None:
        for filename in ("routing.py", "catalog_routing.py"):
            tree = ast.parse((ROOT / "src/elly/application" / filename).read_text(encoding="utf-8"))
            imported: list[str] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.append(node.module)
            self.assertFalse(
                [
                    module
                    for module in imported
                    if any(
                        forbidden in module.casefold()
                        for forbidden in ("provider", "repository", "composition", "sqlite")
                    )
                ],
                filename,
            )


class V3Phase0RoutingTests(unittest.TestCase):
    def test_timeless_request_keeps_the_local_v2_5_route(self) -> None:
        decision = RoutingPolicy().decide(
            RouteRequest("v3-phase0-local", "Explain dependency injection")
        )

        self.assertIs(decision.route, Route.LOCAL_CONVERSATION)
        self.assertIs(decision.reason_code, RouteReasonCode.LOCAL_DEFAULT)
        self.assertIsNone(decision.capability_id)

    def test_registered_capability_selection_is_generic_and_provider_free(self) -> None:
        decision = RoutingPolicy(capabilities=CapabilityRegistry((_CatalogCapability(),))).decide(
            RouteRequest("v3-phase0-capability", "Inspect security controls")
        )

        self.assertIs(decision.route, Route.REGISTERED_CAPABILITY)
        self.assertEqual("security_review", decision.capability_id)
        self.assertEqual("security.inspect", decision.operation)
        self.assertIs(decision.reason_code, RouteReasonCode.CATALOG_SINGLE_MATCH)


class V3Phase0AuthorizationAndRecoveryTests(unittest.TestCase):
    def test_cloud_consent_remains_exact_and_one_use(self) -> None:
        payload = "Research the latest news about my family"
        consent = ConsentWorkflow()
        authorization = CloudAuthorizationPolicy()
        request = CloudAuthorizationRequest(
            task_id="v3-phase0-consent",
            payload=payload,
            classification=PrivacyPolicy().classify(payload),
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

        pending = authorization.authorize(request)
        self.assertFalse(pending.allowed)
        self.assertEqual("EXACT_CONSENT_REQUIRED", pending.reason_code)
        assert pending.consent_proposal is not None
        consent.approve(pending.consent_proposal.proposal_id, now=UTC)

        approved = authorization.authorize(
            replace(request, approval_id=pending.consent_proposal.proposal_id)
        )
        self.assertTrue(approved.allowed)
        replay = authorization.authorize(
            replace(request, approval_id=pending.consent_proposal.proposal_id)
        )
        self.assertFalse(replay.allowed)
        self.assertEqual("EXACT_CONSENT_REQUIRED", replay.reason_code)

    def test_restart_marks_running_task_interrupted_without_replay(self) -> None:
        repository = SqliteSessionRepository(":memory:")
        self.addCleanup(repository.close)
        repository.apply_migrations()
        repository.create_session(
            SessionRecord(
                "v3-phase0-recovery",
                PersistenceMode.STORE_WITH_RETENTION,
                CloudMode.LOCAL_ONLY,
                UTC,
            )
        )
        repository.start_task("v3-phase0-running", "v3-phase0-recovery", UTC)

        self.assertEqual(1, repository.mark_interrupted_tasks(UTC))
        self.assertEqual("interrupted", repository.task_status("v3-phase0-running"))
        self.assertIsNone(repository.get_task_result("v3-phase0-running"))


class V3Phase0PersistenceTests(unittest.TestCase):
    def test_schema_v6_fixture_loads_and_accepts_a_new_v2_5_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "schema-v6.db"
            source = ROOT / "tests/fixtures/schema_v6_representative.sql"
            connection = sqlite3.connect(database_path)
            try:
                connection.executescript(source.read_text(encoding="utf-8"))
                connection.commit()
            finally:
                connection.close()

            repository = SqliteSessionRepository(str(database_path))
            self.addCleanup(repository.close)
            repository.apply_migrations()
            self.assertEqual(
                7,
                repository._conn.execute("SELECT version FROM schema_meta WHERE id=1").fetchone()[
                    0
                ],
            )
            historical = repository.get_task_result("v6-fixture-task")
            self.assertIsNotNone(historical)
            assert historical is not None
            self.assertIs(historical.route_summary, Route.REGISTERED_CAPABILITY)
            self.assertEqual("security_review", historical.capability_id)

            application = Application(
                config=load_config(None),
                clock=FixedClock(UTC),
                generalist=FakeGeneralist(),
                repository=repository,
                audit=StructuredAuditLog(repository=repository),
            )
            self.addCleanup(application.close)
            outcome = application.runtime.handle(
                _task_request("v6-fixture-session", "v3-phase0-new")
            )

            self.assertIs(outcome.result.task_status, TaskStatus.COMPLETED)
            self.assertIs(outcome.result.route_summary, Route.LOCAL_CONVERSATION)
            self.assertEqual("LOCAL_DEFAULT", outcome.result.selection_reason_code)
            persisted = repository.get_task_result("task-v3-phase0-new")
            self.assertIsNotNone(persisted)
            assert persisted is not None
            self.assertTrue(persisted.answer.startswith("[fake-generalist]"))

    def test_no_store_result_body_is_not_persisted(self) -> None:
        repository = SqliteSessionRepository(":memory:")
        self.addCleanup(repository.close)
        repository.apply_migrations()
        repository.create_session(
            SessionRecord(
                "v3-phase0-no-store",
                PersistenceMode.NO_STORE,
                CloudMode.LOCAL_ONLY,
                UTC,
            )
        )
        application = Application(
            config=load_config(None),
            clock=FixedClock(UTC),
            generalist=FakeGeneralist(),
            repository=repository,
            audit=StructuredAuditLog(repository=repository),
        )
        self.addCleanup(application.close)

        outcome = application.runtime.handle(
            _task_request("v3-phase0-no-store", "v3-phase0-no-store-request")
        )
        loaded = repository.get_task_result("task-v3-phase0-no-store-request")

        self.assertTrue(outcome.result.answer)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertFalse(loaded.answer_retained)
        self.assertEqual("", loaded.answer)


class V3Phase0CancellationTests(unittest.TestCase):
    def test_cancellation_does_not_become_success(self) -> None:
        repository = SqliteSessionRepository(":memory:")
        self.addCleanup(repository.close)
        repository.apply_migrations()
        repository.create_session(
            SessionRecord(
                "v3-phase0-cancel",
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
            audit=StructuredAuditLog(repository=repository),
        )
        self.addCleanup(application.close)
        outcomes = []
        worker = threading.Thread(
            target=lambda: outcomes.append(
                application.runtime.handle(
                    _task_request("v3-phase0-cancel", "v3-phase0-cancel-request")
                )
            )
        )
        worker.start()
        self.assertTrue(provider.started.wait(timeout=1))
        self.assertTrue(application.runtime.cancel_task("task-v3-phase0-cancel-request"))
        worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(1, len(outcomes))
        self.assertIs(outcomes[0].result.task_status, TaskStatus.CANCELLED)
        self.assertIs(outcomes[0].result.outcome_code, OutcomeCode.CANCELLED)


class V3Phase0ApiViewTests(unittest.TestCase):
    def test_task_and_trace_views_preserve_bounded_v2_5_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            names = (
                "ELLY_DB_PATH",
                "ELLY_LOG_LEVEL",
                "ELLY_LOCAL_MODELS_QWEN_DEFAULT_PROVIDER",
                "ELLY_LOCAL_MODELS_QWEN_DEFAULT_MODEL_ID",
            )
            previous = {name: os.environ.get(name) for name in names}
            os.environ.update(
                {
                    "ELLY_DB_PATH": str(Path(directory) / "elly.db"),
                    "ELLY_LOG_LEVEL": "WARNING",
                    "ELLY_LOCAL_MODELS_QWEN_DEFAULT_PROVIDER": "fake",
                    "ELLY_LOCAL_MODELS_QWEN_DEFAULT_MODEL_ID": "fake-generalist-v1",
                }
            )
            application = build_application(None)
            try:
                session = application.create_session(CreateSessionRequest())
                self.assertTrue(session.is_success)
                assert session.value is not None
                result = application.submit_and_wait(
                    SubmitRequest(
                        request_id="v3-phase0-api",
                        session_id=session.value.session_id,
                        text="Explain dependency injection",
                    )
                )
                self.assertTrue(result.is_success)
                assert result.value is not None
                task = result.value
                trace = application.get_trace(TraceQuery(task.task_id))
                self.assertTrue(trace.is_success)
                assert trace.value is not None

                self.assertIs(task.route_category, Route.LOCAL_CONVERSATION)
                self.assertIsNone(task.capability_id)
                self.assertEqual("LOCAL_DEFAULT", task.selection_reason_code)
                self.assertIs(trace.value.route_category, Route.LOCAL_CONVERSATION)
                self.assertEqual("LOCAL_DEFAULT", trace.value.selection_reason_code)
                self.assertNotIn(
                    "Explain dependency injection",
                    " ".join(event.detail for event in trace.value.events),
                )
            finally:
                application.close()
                for name, value in previous.items():
                    if value is None:
                        os.environ.pop(name, None)
                    else:
                        os.environ[name] = value


if __name__ == "__main__":
    unittest.main()
