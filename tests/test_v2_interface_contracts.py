"""Phase 1 interface parity tests for the public application façade."""

from __future__ import annotations

import os
import tempfile
import time
import unittest

from elly.api.contracts import (
    ChangeModeRequest,
    CreateSessionRequest,
    SourcesQuery,
    SubmitRequest,
    TraceQuery,
)
from elly.composition import build_application
from elly.domain.enums import CloudMode
from elly.presentation.cli import Cli
from tests.support.interface_adapters import (
    DesktopMobileTestAdapter,
    RestTestAdapter,
    WebTestAdapter,
)


class V2InterfaceParityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.previous = {
            name: os.environ.get(name)
            for name in (
                "ELLY_DB_PATH",
                "ELLY_LOG_LEVEL",
                "ELLY_GENERALIST_PROVIDER",
                "ELLY_GENERALIST_MODEL_ID",
                "ELLY_RESEARCH_PROVIDER",
                "ELLY_SPECIALIST_PROVIDER",
            )
        }
        os.environ.update(
            {
                "ELLY_DB_PATH": os.path.join(self.directory.name, "elly.db"),
                "ELLY_LOG_LEVEL": "WARNING",
                "ELLY_GENERALIST_PROVIDER": "fake",
                "ELLY_GENERALIST_MODEL_ID": "fake-generalist-v1",
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

    def test_web_desktop_and_rest_adapters_share_application_outcomes(self) -> None:
        session = self.application.create_session(CreateSessionRequest())
        assert session.value is not None
        adapters = (
            WebTestAdapter(self.application),
            DesktopMobileTestAdapter(self.application),
            RestTestAdapter(self.application),
        )
        outcomes = []
        for index, adapter in enumerate(adapters):
            accepted = adapter.submit(
                SubmitRequest(
                    request_id=f"parity-{index}",
                    session_id=session.value.session_id,
                    text="Explain dependency injection",
                )
            )
            self.assertTrue(accepted.is_success)
            assert accepted.value is not None
            task_id = accepted.value.task_id
            status = adapter.status(task_id)
            # The unified local path persists and executes a validated plan
            # before terminal task projection; allow the same bounded polling
            # window used by the routing-metadata parity coverage.
            for _ in range(100):
                if (
                    status.is_success
                    and status.value is not None
                    and status.value.status.value
                    in {"completed", "failed", "blocked", "partial", "cancelled"}
                ):
                    break
                time.sleep(0.01)
                status = adapter.status(task_id)
            self.assertTrue(status.is_success)
            assert status.value is not None
            self.assertEqual("completed", status.value.status.value)
            self.assertEqual("local_conversation", status.value.route.value)
            sources = adapter.sources(task_id)
            self.assertTrue(sources.is_success)
            cancelled = adapter.cancel(task_id)
            self.assertTrue(cancelled.is_success)
            outcomes.append((status.value.status, status.value.outcome_code, status.value.route))
        self.assertEqual(outcomes[0], outcomes[1])
        self.assertEqual(outcomes[1], outcomes[2])

    def test_cli_web_desktop_and_rest_share_cloud_policy_and_source_views(self) -> None:
        def cloud_session():  # type: ignore[no-untyped-def]
            session_result = self.application.create_session(CreateSessionRequest())
            assert session_result.value is not None
            changed = self.application.change_session_mode(
                ChangeModeRequest(
                    session_result.value.session_id,
                    session_result.value.version,
                    CloudMode.CLOUD_PERMITTED,
                )
            )
            assert changed.value is not None
            return changed.value

        text = "What is the current gold price?"
        outcomes = []
        adapters = (
            WebTestAdapter(self.application),
            DesktopMobileTestAdapter(self.application),
            RestTestAdapter(self.application),
        )
        for index, adapter in enumerate(adapters):
            session = cloud_session()
            accepted = adapter.submit(
                SubmitRequest(f"cloud-parity-{index}", session.session_id, text)
            )
            assert accepted.value is not None
            task_id = accepted.value.task_id
            status = adapter.status(task_id)
            for _ in range(50):
                if status.value is not None and status.value.status.value in {
                    "completed",
                    "failed",
                    "blocked",
                    "partial",
                    "cancelled",
                }:
                    break
                time.sleep(0.01)
                status = adapter.status(task_id)
            assert status.value is not None
            sources = adapter.sources(task_id)
            trace = adapter.trace(task_id)
            assert sources.value is not None
            assert trace.value is not None
            authorization = tuple(
                (event.event_type, event.detail)
                for event in trace.value.events
                if event.event_type == "authorization.approved"
            )
            outcomes.append(
                (
                    status.value.status,
                    status.value.outcome_code,
                    status.value.route,
                    sources.value.sources,
                    authorization,
                )
            )

        cli = Cli(api=self.application, session=cloud_session())
        cli.dispatch(text)
        assert cli.last_task_id is not None
        cli_status = self.application.get_task(cli.last_task_id)
        cli_sources = self.application.get_sources(SourcesQuery(cli.last_task_id))
        cli_trace = self.application.get_trace(TraceQuery(cli.last_task_id))
        assert cli_status.value is not None
        assert cli_sources.value is not None
        assert cli_trace.value is not None
        outcomes.append(
            (
                cli_status.value.status,
                cli_status.value.outcome_code,
                cli_status.value.route,
                cli_sources.value.sources,
                tuple(
                    (event.event_type, event.detail)
                    for event in cli_trace.value.events
                    if event.event_type == "authorization.approved"
                ),
            )
        )
        self.assertTrue(all(outcome == outcomes[0] for outcome in outcomes[1:]))
        self.assertIn("classification=remote_allowed", outcomes[0][4][0][1])
        self.assertIn("capability=web_research", outcomes[0][4][0][1])


if __name__ == "__main__":
    unittest.main()
