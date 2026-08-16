"""Cancellation regressions for every V1.5 external execution boundary."""

from __future__ import annotations

import threading
import unittest
from datetime import datetime, timezone

from elly.adapters.http_document_retriever import HttpDocumentRetriever
from elly.application.execution import CancellationToken
from elly.application.research import ResearchPipeline
from elly.application.specialist_policy import SpecialistPolicyRequest
from elly.application.specialists import SpecialistWorkflow
from elly.domain.enums import HealthState
from elly.domain.errors import CancelledError, TransientProviderError
from elly.domain.models import EvidenceObject, HealthReport
from elly.guardrails.controller import GuardrailController
from elly.guardrails.limits import LimitPolicy
from elly.privacy import classify_payload
from elly.specialists.contracts import SpecialistTask
from elly.specialists.manifest import SpecialistManifest

UTC = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


class _Clock:
    def now(self):
        return UTC


def _run_and_cancel(operation, token: CancellationToken, started: threading.Event):
    result = []

    def run() -> None:
        try:
            operation()
        except Exception as exc:  # test captures the typed boundary result
            result.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    if not started.wait(timeout=1):
        token.cancel()
        worker.join(timeout=1)
        raise AssertionError("provider did not start")
    token.cancel()
    worker.join(timeout=2)
    if worker.is_alive():
        raise AssertionError("cancelled provider did not stop")
    return result


class _BlockingResearchProvider:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.released = threading.Event()
        self.calls = 0

    def health(self) -> HealthReport:
        return HealthReport("research(blocking)", HealthState.HEALTHY)

    def research(self, _query, _budget):
        self.calls += 1
        self.started.set()
        self.released.wait(timeout=2)
        raise TransientProviderError("research connection closed")

    def cancel(self) -> None:
        self.released.set()


class ExternalCancellationTests(unittest.TestCase):
    def test_cancellation_during_hosted_research_is_typed(self) -> None:
        provider = _BlockingResearchProvider()
        pipeline = ResearchPipeline(
            provider=provider, clock=_Clock(), max_results=2, timeout_seconds=2
        )
        token = CancellationToken()

        failures = _run_and_cancel(
            lambda: pipeline.execute("latest public result", cancellation=token),
            token,
            provider.started,
        )

        self.assertEqual(1, len(failures))
        self.assertIsInstance(failures[0], CancelledError)
        self.assertEqual(1, provider.calls)

    def test_cancellation_between_retries_prevents_second_dispatch(self) -> None:
        token = CancellationToken()

        class CancelOnFirstAttempt(_BlockingResearchProvider):
            def research(self, _query, _budget):
                self.calls += 1
                token.cancel()
                raise TransientProviderError("retryable provider failure")

        provider = CancelOnFirstAttempt()
        guardrails = GuardrailController(
            policy=LimitPolicy(max_provider_calls=2, max_retries=1, max_output_tokens=4096),
            tool_timeout_seconds=1,
            total_timeout_seconds=2,
            sleep=lambda _delay: None,
        )
        pipeline = ResearchPipeline(
            provider=provider, clock=_Clock(), max_results=2, timeout_seconds=1
        )

        with self.assertRaises(CancelledError):
            pipeline.execute(
                "latest public result",
                request_guardrails=guardrails,
                cancellation=token,
            )
        self.assertEqual(1, provider.calls)

    def test_cancellation_during_document_retrieval_closes_connection(self) -> None:
        started = threading.Event()
        released = threading.Event()

        class Connection:
            def request(self, _method, _target, headers):
                started.set()
                released.wait(timeout=2)
                raise OSError("socket closed")

            def getresponse(self):
                raise AssertionError("cancelled request must not produce a response")

            def close(self):
                released.set()

        connection = Connection()

        def resolver(*_args, **_kwargs):
            return [(2, 1, 6, "", ("93.184.216.34", 443))]

        retriever = HttpDocumentRetriever(
            resolver=resolver,
            connection_factory=lambda _host, _address, timeout: connection,
        )
        evidence = EvidenceObject(
            evidence_id="E1",
            url="https://example.com/source",
            title="Source",
            publisher="Example",
            retrieved_at=UTC,
        )
        token = CancellationToken()

        failures = _run_and_cancel(
            lambda: retriever.retrieve(evidence, timeout_seconds=2, cancellation=token),
            token,
            started,
        )

        self.assertEqual(1, len(failures))
        self.assertIsInstance(failures[0], CancelledError)
        self.assertTrue(released.is_set())

    def test_cancellation_during_specialist_execution_is_typed(self) -> None:
        started = threading.Event()
        released = threading.Event()

        class Provider:
            def health(self):
                return HealthReport("specialist(blocking)", HealthState.HEALTHY)

            def execute(self, _task, *, model, prompt_version, output_limit):
                started.set()
                released.wait(timeout=2)
                raise TransientProviderError("specialist connection closed")

            def cancel(self):
                released.set()

        context = "Review this public Python function"
        task = SpecialistTask(
            task_id="task-specialist-cancel",
            specialist_id="coding",
            goal="review",
            context=context,
            privacy_class=classify_payload(context).value,
        )
        manifest = SpecialistManifest(
            id="coding",
            version="1.0",
            description="coding",
            role="coding",
            capabilities=frozenset({"review"}),
            accepted_inputs=frozenset({"text"}),
            requires_current_data=False,
            preferred_runtime="cloud",
            risk_level="low",
            estimated_cost="medium",
            timeout_seconds=30,
        )
        workflow = SpecialistWorkflow(provider=Provider())
        token = CancellationToken()

        failures = _run_and_cancel(
            lambda: workflow.execute(
                request=SpecialistPolicyRequest(task=task, manifest=manifest),
                cancellation=token,
            ),
            token,
            started,
        )

        self.assertEqual(1, len(failures))
        self.assertIsInstance(failures[0], CancelledError)
        self.assertTrue(released.is_set())


if __name__ == "__main__":
    unittest.main()
