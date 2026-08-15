"""Dependency wiring + structural smoke path (M1).

Proves the architecture CONNECTS end-to-end EXCEPT the orchestrator's `handle`,
which is the owner exercise. This is deliberately NOT a full-conversation test —
it verifies structural readiness (composition, ports, adapters, persistence,
audit) so a green run here does not imply the milestone's behavior is complete.
"""

from __future__ import annotations

import os
import tempfile
import threading
import unittest

from elly.adapters.fake_generalist import FailureMode
from elly.composition import Application, build
from elly.domain.enums import CloudMode, HealthState, PersistenceMode
from elly.domain.models import GeneralistRequest, Message, TaskRequest


class CompositionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["ELLY_DB_PATH"] = os.path.join(self._tmp.name, "elly.db")
        os.environ["ELLY_LOG_LEVEL"] = "WARNING"
        os.environ["ELLY_GENERALIST_PROVIDER"] = "fake"
        os.environ["ELLY_GENERALIST_MODEL_ID"] = "fake-generalist-v1"
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(os.environ.pop, "ELLY_DB_PATH", None)
        self.addCleanup(os.environ.pop, "ELLY_LOG_LEVEL", None)
        self.addCleanup(os.environ.pop, "ELLY_GENERALIST_PROVIDER", None)
        self.addCleanup(os.environ.pop, "ELLY_GENERALIST_MODEL_ID", None)
        self.app: Application = build(None)
        self.addCleanup(self.app.close)

    def test_app_is_wired(self) -> None:
        self.assertIsNotNone(self.app.orchestrator)
        components = {r.component for r in self.app.health()}
        self.assertTrue(any(c.startswith("generalist") for c in components))
        self.assertIn("storage(sqlite)", components)

    def test_generalist_reports_healthy(self) -> None:
        gen = next(r for r in self.app.health() if r.component.startswith("generalist"))
        self.assertIs(gen.state, HealthState.HEALTHY)

    def test_new_session_persists(self) -> None:
        rec = self.app.new_session(persistence_mode=PersistenceMode.STORE_WITH_RETENTION)
        got = self.app.repository.get_session(rec.session_id)
        self.assertIsNotNone(got)

    def test_structural_smoke_path_without_orchestrator(self) -> None:
        # CLI -> orchestrator is exercised elsewhere; here we prove the lower
        # boundary composes: model port -> repository -> audit.
        session = self.app.new_session()
        response = self.app.generalist.generate(
            GeneralistRequest(prompt="ping", model_id=self.app.config.generalist_model_id, max_output_tokens=32)
        )
        self.assertTrue(response.text.startswith("[fake-generalist]"))
        self.app.repository.append_message(
            session.session_id, Message("assistant", response.text, self.app.clock.now())
        )
        loaded = self.app.repository.recent_messages(session.session_id, 5)
        self.assertEqual(loaded[-1].content, response.text)

    def test_full_local_turn_through_orchestrator(self) -> None:
        # End-to-end through the wired app: a local turn completes and both turns
        # persist (UC-01, DATA-001).
        session = self.app.new_session()
        request = TaskRequest(
            request_id="req-x",
            session_id=session.session_id,
            text="hi",
            cloud_mode=CloudMode.LOCAL_ONLY,
            persistence_mode=session.persistence_mode,
            submitted_at=self.app.clock.now(),
        )
        outcome = self.app.orchestrator.handle(request)
        self.assertTrue(outcome.result.answer.startswith("[fake-generalist]"))
        roles = [m.role for m in self.app.repository.recent_messages(session.session_id, 10)]
        self.assertEqual(roles, ["user", "assistant"])

    def test_local_output_ceiling_does_not_inherit_specialist_limit(self) -> None:
        self.assertEqual(
            self.app.config.generalist_max_output_tokens,
            self.app.orchestrator._max_output_tokens,
        )

    def test_central_config_is_wired_into_remote_models_and_pricing(self) -> None:
        self.assertEqual(
            self.app.config.remote_call_reservation_usd,
            self.app.research.call_cost_usd,
        )
        self.assertEqual(
            self.app.config.remote_call_reservation_usd,
            self.app.specialist_workflow.call_cost_usd,
        )
        self.assertEqual(
            self.app.config.specialist_model_id("coding"),
            self.app.specialist_registry.get("coding").provider_model,
        )
        self.assertEqual(
            self.app.config.specialist_provider,
            self.app.specialist_workflow.provider_name,
        )

    def test_completed_local_trace_contains_model_usage_and_request_limits(self) -> None:
        session = self.app.new_session()
        request = TaskRequest(
            request_id="req-trace", session_id=session.session_id, text="hello",
            cloud_mode=CloudMode.LOCAL_ONLY,
            persistence_mode=session.persistence_mode, submitted_at=self.app.clock.now(),
        )
        self.app.orchestrator.handle(request)
        completed = next(
            event for event in self.app.repository.audit_by_task("task-req-trace")
            if event.event_type == "task.completed"
        )
        self.assertIn("model=fake-generalist-v1", completed.detail)
        self.assertIn("tools=none", completed.detail)
        self.assertIn("duration_ms=", completed.detail)
        self.assertIn("output_tokens=", completed.detail)
        self.assertIn("provider_calls=1", completed.detail)

    def test_failed_trace_contains_duration_and_request_limits(self) -> None:
        self.app.generalist._failure = FailureMode.PERMANENT
        session = self.app.new_session()
        request = TaskRequest(
            request_id="req-failed-trace", session_id=session.session_id, text="hello",
            cloud_mode=CloudMode.LOCAL_ONLY,
            persistence_mode=session.persistence_mode, submitted_at=self.app.clock.now(),
        )
        self.app.orchestrator.handle(request)
        failed = next(
            event for event in self.app.repository.audit_by_task("task-req-failed-trace")
            if event.event_type == "generalist.failed"
        )
        self.assertIn("duration_ms=", failed.detail)
        self.assertIn("provider_calls=1", failed.detail)

    def test_periodic_maintenance_runs_until_shutdown(self) -> None:
        self.app._maintenance_stop.set()
        self.app._maintenance_thread.join(timeout=1)
        self.app._maintenance_stop = threading.Event()
        self.app._maintenance_thread = None
        called = threading.Event()
        self.app.maintain_storage = called.set
        self.app.start_maintenance_scheduler(interval_seconds=0.01)
        self.assertTrue(called.wait(0.2))

    def test_audit_health_probe_reports_schema_failure(self) -> None:
        self.app.repository._conn.execute("DROP TABLE audit_events")
        reports = {report.component: report for report in self.app.health()}
        self.assertEqual("unavailable", reports["audit"].state.value)


if __name__ == "__main__":
    unittest.main()
