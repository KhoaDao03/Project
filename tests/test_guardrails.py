from __future__ import annotations

import threading
import time
import unittest

from elly.application.capabilities.research import ResearchPipeline
from elly.domain.errors import (
    CircuitOpenError,
    LimitExceededError,
    PermanentProviderError,
    ProviderTimeoutError,
    TransientProviderError,
)
from elly.guardrails.controller import GuardrailController
from elly.guardrails.cost import FakeCostLedger
from elly.guardrails.executor import BoundedTaskExecutor
from elly.guardrails.limits import LimitPolicy, ReservationLedger
from elly.guardrails.retry import CircuitBreaker
from elly.research.fake_provider import FixtureWebResearchProvider


class _Clock:
    def now(self):
        return __import__("datetime").datetime.now(__import__("datetime").timezone.utc)


class LimitLedgerTests(unittest.TestCase):
    def test_boundary_at_limit_succeeds_above_limit_fails(self) -> None:
        ledger = ReservationLedger(
            LimitPolicy(max_steps=2, max_provider_calls=2, max_concurrency=1)
        )
        ledger.reserve(steps=2)
        with self.assertRaises(LimitExceededError):
            ledger.reserve(steps=1)

    def test_concurrency_reservation_is_atomic(self) -> None:
        ledger = ReservationLedger(
            LimitPolicy(max_steps=10, max_provider_calls=10, max_concurrency=1)
        )
        barrier = threading.Barrier(2)
        results: list[str] = []

        def race() -> None:
            barrier.wait()
            try:
                reservation = ledger.reserve(concurrency=1)
                results.append("won")
                time.sleep(0.02)
                ledger.release(reservation)
            except LimitExceededError:
                results.append("rejected")

        threads = [threading.Thread(target=race) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(results), ["rejected", "won"])


class RetryCircuitCostTests(unittest.TestCase):
    def test_local_override_does_not_reserve_cloud_cost(self) -> None:
        controller = GuardrailController(
            policy=LimitPolicy(monthly_budget_usd=1),
            tool_timeout_seconds=1,
            total_timeout_seconds=2,
            remote_call_reservation_usd=0.01,
        )
        self.assertEqual(controller.execute(lambda: "local", cost_usd=0.0), "local")
        self.assertEqual(controller.cost.reserved_usd, 0.0)

    def test_only_transient_failure_retries_with_bounded_deterministic_delay(self) -> None:
        sleeps: list[float] = []
        attempts = 0

        def operation() -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise TransientProviderError("temporary")
            return "ok"

        controller = GuardrailController(
            policy=LimitPolicy(max_provider_calls=2, max_retries=1),
            tool_timeout_seconds=1,
            total_timeout_seconds=2,
            sleep=sleeps.append,
        )
        self.assertEqual(controller.execute(operation), "ok")
        self.assertEqual(attempts, 2)
        self.assertEqual(len(sleeps), 1)
        self.assertLessEqual(sleeps[0], 1.0)

    def test_permanent_failure_does_not_retry(self) -> None:
        attempts = 0

        def operation() -> None:
            nonlocal attempts
            attempts += 1
            raise PermanentProviderError("permanent")

        controller = GuardrailController(
            policy=LimitPolicy(max_provider_calls=2, max_retries=1),
            tool_timeout_seconds=1,
            total_timeout_seconds=2,
            sleep=lambda _: self.fail("permanent error was retried"),
        )
        with self.assertRaises(PermanentProviderError):
            controller.execute(operation)
        self.assertEqual(attempts, 1)

    def test_circuit_opens_after_threshold(self) -> None:
        circuit = CircuitBreaker(failure_threshold=2, reset_after_seconds=10)
        circuit.record_failure(1.0)
        circuit.record_failure(2.0)
        with self.assertRaises(CircuitOpenError):
            circuit.allow(2.1)

    def test_budget_is_reserved_before_call_and_over_budget_is_rejected(self) -> None:
        ledger = FakeCostLedger(1.0)
        ledger.reserve(1.0)
        with self.assertRaises(LimitExceededError):
            ledger.reserve(0.01)
        ledger.reconcile(1.0, 0.5)
        self.assertEqual(ledger.reserved_usd, 0.5)
        self.assertEqual("50%", ledger.warning_level)

    def test_each_retry_attempt_retains_its_conservative_cost(self) -> None:
        attempts = 0

        def operation() -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise TransientProviderError("temporary")
            return "ok"

        controller = GuardrailController(
            policy=LimitPolicy(max_provider_calls=2, max_retries=1, monthly_budget_usd=1),
            tool_timeout_seconds=1,
            total_timeout_seconds=2,
            remote_call_reservation_usd=0.25,
            sleep=lambda _delay: None,
        )
        self.assertEqual("ok", controller.execute(operation))
        self.assertEqual(0.5, controller.request_cost_usd)
        self.assertEqual(0.5, controller.cost.reserved_usd)

    def test_rejected_cost_reservation_does_not_reduce_prior_spend(self) -> None:
        controller = GuardrailController(
            policy=LimitPolicy(monthly_budget_usd=0.25),
            tool_timeout_seconds=1,
            total_timeout_seconds=1,
            remote_call_reservation_usd=0.25,
        )
        self.assertEqual("ok", controller.execute(lambda: "ok"))
        with self.assertRaises(LimitExceededError):
            controller.for_request().execute(lambda: "must not run")
        self.assertEqual(0.25, controller.cost.reserved_usd)

    def test_timeout_requests_cancellation_and_returns_typed_failure(self) -> None:
        cancelled = threading.Event()

        def operation() -> None:
            time.sleep(0.1)

        controller = GuardrailController(
            policy=LimitPolicy(max_provider_calls=1),
            tool_timeout_seconds=0.01,
            total_timeout_seconds=1,
        )
        with self.assertRaises(ProviderTimeoutError):
            controller.execute(operation, cancel=cancelled.set)
        self.assertTrue(cancelled.is_set())

    def test_total_timeout_caps_a_longer_tool_timeout(self) -> None:
        cancelled = threading.Event()
        controller = GuardrailController(
            policy=LimitPolicy(max_provider_calls=1),
            tool_timeout_seconds=1,
            total_timeout_seconds=0.01,
        )
        started = time.monotonic()
        with self.assertRaises(ProviderTimeoutError):
            controller.execute(lambda: time.sleep(0.1), cancel=cancelled.set)
        self.assertLess(time.monotonic() - started, 0.05)
        self.assertTrue(cancelled.is_set())

    def test_timeout_retries_only_with_cancellation_support(self) -> None:
        attempts = 0

        def timed_out() -> None:
            nonlocal attempts
            attempts += 1
            raise ProviderTimeoutError("timed out")

        controller = GuardrailController(
            policy=LimitPolicy(max_provider_calls=2, max_retries=1),
            tool_timeout_seconds=1,
            total_timeout_seconds=2,
            sleep=lambda _delay: None,
        )
        with self.assertRaises(ProviderTimeoutError):
            controller.execute(timed_out, cancel=lambda: None)
        self.assertEqual(2, attempts)
        self.assertEqual(1, controller.retry_count)

        attempts = 0
        without_cancel = controller.for_request()
        with self.assertRaises(ProviderTimeoutError):
            without_cancel.execute(timed_out)
        self.assertEqual(1, attempts)

    def test_provider_call_ceiling_blocks_the_next_call(self) -> None:
        calls = 0

        def operation() -> str:
            nonlocal calls
            calls += 1
            return "ok"

        controller = GuardrailController(
            policy=LimitPolicy(max_provider_calls=1),
            tool_timeout_seconds=1,
            total_timeout_seconds=1,
        )
        self.assertEqual(controller.execute(operation), "ok")
        with self.assertRaises(LimitExceededError):
            controller.execute(operation)
        self.assertEqual(calls, 1)

    def test_output_token_ceiling_is_enforced_before_operation(self) -> None:
        controller = GuardrailController(
            policy=LimitPolicy(max_output_tokens=8),
            tool_timeout_seconds=1,
            total_timeout_seconds=1,
        )
        with self.assertRaises(LimitExceededError):
            controller.execute(lambda: "must not run", output_tokens=9)

    def test_bounded_executor_rejects_above_worker_and_queue_capacity(self) -> None:
        executor = BoundedTaskExecutor(workers=1, queue_size=1)
        release = threading.Event()
        first = executor.submit(lambda: release.wait(1))
        second = executor.submit(lambda: "queued")
        with self.assertRaises(LimitExceededError):
            executor.submit(lambda: "rejected")
        release.set()
        self.assertTrue(first.result(timeout=1))
        self.assertEqual(second.result(timeout=1), "queued")
        executor.shutdown()

    def test_nested_research_uses_callers_shared_request_ledger(self) -> None:
        controller = GuardrailController(
            policy=LimitPolicy(max_provider_calls=1),
            tool_timeout_seconds=1,
            total_timeout_seconds=1,
        )
        controller.ledger.reserve(provider_calls=1)
        pipeline = ResearchPipeline(
            provider=FixtureWebResearchProvider(),
            clock=_Clock(),
            max_results=1,
            timeout_seconds=1,
        )
        with self.assertRaises(LimitExceededError):
            pipeline.execute("latest public result", request_guardrails=controller)
        self.assertEqual([], pipeline.provider.calls)


if __name__ == "__main__":
    unittest.main()
