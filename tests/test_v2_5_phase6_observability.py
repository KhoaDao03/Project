"""V2.5 Phase 6 observability, redaction, and interface-parity coverage."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from datetime import datetime, timezone

from elly.adapters.sqlite_repository import SqliteSessionRepository
from elly.api.contracts import CreateSessionRequest, SubmitRequest
from elly.application.route_compatibility import enrich_task_result
from elly.application.routing_contracts import (
    CandidateMatch,
    CapabilitySelectionProposal,
    FreshnessRequirement,
    MatchStrength,
    TaskIntent,
)
from elly.composition import build_application
from elly.domain.enums import (
    CloudMode,
    EpistemicStatus,
    IntentAmbiguity,
    OutcomeCode,
    PersistenceMode,
    Route,
    RouteReasonCode,
    TaskStatus,
    ValidationStatus,
)
from elly.domain.models import RouteDecision, SessionRecord, TaskResult
from elly.presentation.cli import Cli
from elly.trace_safety import redact_trace_detail
from tests.support.interface_adapters import (
    DesktopMobileTestAdapter,
    RestTestAdapter,
    WebTestAdapter,
)

UTC = datetime(2026, 8, 15, tzinfo=timezone.utc)


def _result() -> TaskResult:
    return TaskResult(
        task_id="phase6-task",
        task_status=TaskStatus.COMPLETED,
        outcome_code=OutcomeCode.SUCCESS,
        epistemic_status=EpistemicStatus.KNOWN,
        validation_status=ValidationStatus.VALIDATED,
        answer="selection complete",
        route_summary=Route.RESEARCH_SPECIALIST,
    )


class Phase6RoutingTraceTests(unittest.TestCase):
    def test_enrichment_keeps_only_bounded_selection_metadata(self) -> None:
        selected = CandidateMatch(
            capability_id="security_review",
            operation_id="security.inspect",
            compatible=True,
            required_inputs_satisfied=True,
            operation_match=MatchStrength.EXACT,
            freshness_match=MatchStrength.EXACT,
            domain_specificity=90,
            declared_priority=70,
        )
        rejected = CandidateMatch(
            capability_id="static_review",
            operation_id="security.inspect",
            compatible=False,
            required_inputs_satisfied=False,
            operation_match=MatchStrength.EXACT,
            freshness_match=MatchStrength.NONE,
            domain_specificity=50,
            declared_priority=50,
            rejection_codes=("REQUIRED_ENTITY_MISSING", "FRESHNESS_UNSUPPORTED"),
        )
        intent = TaskIntent(
            requested_operation="security.inspect",
            domain="security",
            freshness=FreshnessRequirement.CURRENT,
            confidence=0.95,
            ambiguity=IntentAmbiguity.CLEAR,
            rationale_code="CATALOG_OPERATION_MATCH",
        )
        selection = CapabilitySelectionProposal(
            capability_id="security_review",
            operation_id="security.inspect",
            confidence=0.95,
            ambiguity=IntentAmbiguity.CLEAR,
            rationale_code="SELECTION_VALIDATED",
            ranked_alternatives=(selected, rejected),
        )
        decision = RouteDecision(
            Route.REGISTERED_CAPABILITY,
            RouteReasonCode.CATALOG_SINGLE_MATCH,
            capability_id="security_review",
            operation="security.inspect",
            intent=intent,
            selection=selection,
            candidate_count=2,
            rejected_candidate_reason_codes=(
                "REQUIRED_ENTITY_MISSING",
                "FRESHNESS_UNSUPPORTED",
            ),
            freshness_affected_selection=True,
        )

        enriched = enrich_task_result(_result(), decision)

        self.assertEqual(Route.REGISTERED_CAPABILITY, enriched.route_category)
        self.assertEqual("security_review", enriched.capability_id)
        self.assertEqual("security.inspect", enriched.operation)
        self.assertEqual("CATALOG_SINGLE_MATCH", enriched.selection_reason_code)
        self.assertEqual(2, enriched.candidate_count)
        self.assertEqual(
            ("REQUIRED_ENTITY_MISSING", "FRESHNESS_UNSUPPORTED"),
            enriched.rejected_candidate_reason_codes,
        )
        self.assertFalse(enriched.clarification_required)
        self.assertTrue(enriched.freshness_affected_selection)

    def test_selection_trace_metadata_round_trips_through_schema_v6(self) -> None:
        repository = SqliteSessionRepository(":memory:")
        self.addCleanup(repository.close)
        repository.apply_migrations()
        repository.create_session(
            SessionRecord(
                "phase6-session",
                PersistenceMode.STORE_WITH_RETENTION,
                CloudMode.LOCAL_ONLY,
                UTC,
            )
        )
        repository.start_task("phase6-task", "phase6-session", UTC)

        selected = CandidateMatch(
            capability_id="security_review",
            operation_id="security.inspect",
            compatible=True,
            required_inputs_satisfied=True,
            operation_match=MatchStrength.EXACT,
            freshness_match=MatchStrength.EXACT,
            domain_specificity=90,
            declared_priority=70,
        )
        intent = TaskIntent(
            requested_operation="security.inspect",
            domain="security",
            freshness=FreshnessRequirement.CURRENT,
            confidence=0.95,
            ambiguity=IntentAmbiguity.CLEAR,
            rationale_code="CATALOG_OPERATION_MATCH",
        )
        decision = RouteDecision(
            Route.REGISTERED_CAPABILITY,
            RouteReasonCode.CATALOG_SINGLE_MATCH,
            capability_id="security_review",
            operation="security.inspect",
            intent=intent,
            selection=CapabilitySelectionProposal(
                capability_id="security_review",
                operation_id="security.inspect",
                confidence=0.95,
                ambiguity=IntentAmbiguity.CLEAR,
                rationale_code="SELECTION_VALIDATED",
                ranked_alternatives=(selected,),
            ),
            candidate_count=1,
            rejected_candidate_reason_codes=("FRESHNESS_UNSUPPORTED",),
            freshness_affected_selection=True,
        )
        repository.save_task_result(enrich_task_result(_result(), decision), UTC)

        version = repository._conn.execute("SELECT version FROM schema_meta WHERE id=1").fetchone()[
            0
        ]
        raw = repository._conn.execute(
            "SELECT candidate_count, rejected_candidate_reason_codes_json, "
            "clarification_required, freshness_affected_selection FROM task_results"
        ).fetchone()
        loaded = repository.get_task_result("phase6-task")

        self.assertEqual(7, version)
        self.assertEqual((1, '["FRESHNESS_UNSUPPORTED"]', 0, 1), tuple(raw))
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(1, loaded.candidate_count)
        self.assertEqual(("FRESHNESS_UNSUPPORTED",), loaded.rejected_candidate_reason_codes)
        self.assertTrue(loaded.freshness_affected_selection)

    def test_trace_redaction_removes_payloads_prompts_and_model_rationale(self) -> None:
        detail = (
            "prompt=complete private customer prompt "
            "token=secret-token payload='restricted body' "
            "model_rationale=hidden chain_of_thought=private reasoning "
            "provider_calls=2 tools=none"
        )

        safe = redact_trace_detail(detail)

        for value in (
            "complete private customer prompt",
            "secret-token",
            "restricted body",
            "hidden",
            "private reasoning",
        ):
            self.assertNotIn(value, safe)
        self.assertIn("provider_calls=2", safe)
        self.assertIn("tools=none", safe)


class Phase6InterfaceParityTests(unittest.TestCase):
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
        self.application = build_application(None)

    def tearDown(self) -> None:
        self.application.close()
        for name, value in self.previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        self.directory.cleanup()

    def _adapter_metadata(self, adapter, index: int) -> tuple[object, ...]:  # type: ignore[no-untyped-def]
        session = self.application.create_session(
            CreateSessionRequest(cloud_mode=CloudMode.LOCAL_ONLY)
        )
        self.assertTrue(session.is_success)
        assert session.value is not None
        accepted = adapter.submit(
            SubmitRequest(
                request_id=f"phase6-parity-{index}",
                session_id=session.value.session_id,
                text="Analyze Apple's valuation",
            )
        )
        self.assertTrue(accepted.is_success)
        assert accepted.value is not None
        task_id = accepted.value.task_id
        status = adapter.status(task_id)
        for _ in range(100):
            if status.value is not None and status.value.status in {
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.BLOCKED,
                TaskStatus.PARTIAL,
                TaskStatus.CANCELLED,
            }:
                break
            time.sleep(0.01)
            status = adapter.status(task_id)
        self.assertTrue(status.is_success)
        assert status.value is not None
        trace = adapter.trace(task_id)
        self.assertTrue(trace.is_success)
        assert trace.value is not None
        view = status.value
        trace_view = trace.value
        return (
            view.route,
            view.route_category,
            view.capability_id,
            view.operation,
            view.selection_reason_code,
            view.candidate_count,
            view.rejected_candidate_reason_codes,
            view.clarification_required,
            view.freshness_affected_selection,
            trace_view.route_category,
            trace_view.capability_id,
            trace_view.operation,
            trace_view.selection_reason_code,
            trace_view.candidate_count,
            trace_view.rejected_candidate_reason_codes,
            trace_view.clarification_required,
            trace_view.freshness_affected_selection,
        )

    def test_web_desktop_mobile_rest_and_cli_share_routing_metadata(self) -> None:
        adapters = (
            WebTestAdapter(self.application),
            DesktopMobileTestAdapter(self.application),
            RestTestAdapter(self.application),
        )
        outcomes = [
            self._adapter_metadata(adapter, index) for index, adapter in enumerate(adapters)
        ]

        cli = Cli.start(self.application)
        cli_output = cli.dispatch("Analyze Apple's valuation")
        self.assertIsNotNone(cli.last_task_id)
        assert cli.last_task_id is not None
        cli_status = self.application.get_task(cli.last_task_id)
        self.assertTrue(cli_status.is_success)
        assert cli_status.value is not None
        cli_view = cli_status.value
        cli_metadata = (
            cli_view.route,
            cli_view.route_category,
            cli_view.capability_id,
            cli_view.operation,
            cli_view.selection_reason_code,
            cli_view.candidate_count,
            cli_view.rejected_candidate_reason_codes,
            cli_view.clarification_required,
            cli_view.freshness_affected_selection,
        )

        self.assertTrue(all(outcome == outcomes[0] for outcome in outcomes[1:]))
        self.assertEqual(outcomes[0][:9], cli_metadata)
        self.assertIn("Routing:", cli_output)
        self.assertIn("reason=CATALOG_SINGLE_MATCH", cli_output)
        self.assertEqual("stock_analysis", outcomes[0][2])
        self.assertEqual("valuation.analyze", outcomes[0][3])


if __name__ == "__main__":
    unittest.main()
