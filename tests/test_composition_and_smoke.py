"""Dependency wiring + structural smoke path (M1).

Proves the architecture CONNECTS end-to-end EXCEPT the orchestrator's `handle`,
which is the owner exercise. This is deliberately NOT a full-conversation test —
it verifies structural readiness (composition, ports, adapters, persistence,
audit) so a green run here does not imply the milestone's behavior is complete.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from elly.composition import Application, build
from elly.domain.enums import HealthState, PersistenceMode
from elly.domain.models import GeneralistRequest, Message, TaskRequest
from elly.domain.enums import CloudMode


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


if __name__ == "__main__":
    unittest.main()
