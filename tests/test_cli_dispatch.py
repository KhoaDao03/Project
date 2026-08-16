"""Fake-backed behavior: CLI command dispatch (FR-001 surface, UC-10 initial).

Drives Cli.dispatch directly (no stdin). Confirms intentionally-unavailable paths
fail explicitly and the owner-exercise path is surfaced (not faked).
"""

from __future__ import annotations

import os
import tempfile
import unittest

from elly.composition import build
from elly.domain.enums import PersistenceMode
from elly.presentation.cli import EXIT, Cli


class CliDispatchTests(unittest.TestCase):
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
        self.cli = Cli.start(build(None))
        self.addCleanup(self.cli.app.close)

    def test_help(self) -> None:
        self.assertIn("/status", self.cli.dispatch("/help"))

    def test_exit_sentinel(self) -> None:
        self.assertEqual(self.cli.dispatch("/exit"), EXIT)

    def test_status_shows_health(self) -> None:
        out = self.cli.dispatch("/status")
        self.assertIn("storage(sqlite)", out)
        self.assertIn("Mode:", out)
        self.assertIn("Limits:", out)
        self.assertIn("generalist=fake/fake-generalist-v1", out)
        self.assertIn("research=openai_web_search/gpt-5.6-luna", out)
        self.assertIn("remote reservation=$0.0100/call", out)

    def test_request_scoped_guardrail_reservation_does_not_leak_between_tasks(self) -> None:
        self.cli.app.guardrails.ledger.reserve(
            provider_calls=self.cli.app.config.max_provider_calls
        )
        out = self.cli.dispatch("this must be blocked by the guardrail")
        self.assertIn("fake-generalist", out)

    def test_new_no_store_switches_session(self) -> None:
        out = self.cli.dispatch("/new --no-store")
        self.assertIn("no_store", out)
        self.assertIs(self.cli.session.persistence_mode, PersistenceMode.NO_STORE)

    def test_mode_cloud_permits_policy_controlled_research(self) -> None:
        self.assertIn("cloud_permitted", self.cli.dispatch("/mode cloud"))

    def test_cancel_unavailable(self) -> None:
        self.assertIn("cancel", self.cli.dispatch("/cancel").lower())

    def test_empty_input_ignored_no_error(self) -> None:
        self.assertIn("empty", self.cli.dispatch("   ").lower())

    def test_oversized_input_rejected_before_orchestration(self) -> None:
        big = "x" * (self.cli.app.config.max_input_chars + 1)
        out = self.cli.dispatch(big)
        self.assertIn("rejected", out.lower())

    def test_plain_text_returns_rendered_response(self) -> None:
        # Full entry-point-to-response path (FR-001 -> UC-01 -> UX-001 layout).
        out = self.cli.dispatch("hello elly")
        self.assertIn("[fake-generalist]", out)
        self.assertIn("Evidence: inferred", out)
        self.assertIn("Route: local_conversation", out)

    def test_trace_surfaces_redacted_route_and_execution_detail(self) -> None:
        self.cli.dispatch("hello trace")
        task_id = self.cli.app.repository._conn.execute(
            "SELECT task_id FROM tasks ORDER BY started_at DESC LIMIT 1"
        ).fetchone()[0]
        out = self.cli.dispatch(f"/trace {task_id}")
        self.assertIn("route=local_conversation", out)
        self.assertIn("provider_calls=1", out)
        self.assertIn("tools=none", out)


if __name__ == "__main__":
    unittest.main()
