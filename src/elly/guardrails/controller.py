"""Application-owned guardrail orchestration around provider calls."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from collections.abc import Callable
from typing import TypeVar

from ..domain.errors import CancelledError, ProviderTimeoutError, TransientProviderError
from .cost import FakeCostLedger
from .limits import LimitPolicy, ReservationLedger
from .retry import CircuitBreaker, RetryPolicy

T = TypeVar("T")


class GuardrailController:
    """Reserves resources before calls and maps retry/timeout policy deterministically."""

    def __init__(self, *, policy: LimitPolicy, tool_timeout_seconds: float, total_timeout_seconds: float, provider_call_cost_usd: float = 0.0, sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic, _cost: FakeCostLedger | None = None, _circuit: CircuitBreaker | None = None) -> None:
        self.policy = policy
        self.ledger = ReservationLedger(policy)
        self.cost = _cost or FakeCostLedger(policy.monthly_budget_usd)
        self.retry = RetryPolicy(max_retries=policy.max_retries)
        self.circuit = _circuit or CircuitBreaker()
        self.tool_timeout_seconds = tool_timeout_seconds
        self.total_timeout_seconds = total_timeout_seconds
        self.provider_call_cost_usd = provider_call_cost_usd
        self._sleep = sleep
        self._clock = clock
        self.retry_count = 0
        self.request_cost_usd = 0.0

    def for_request(self) -> "GuardrailController":
        """Create request-scoped reservations while retaining monthly state."""
        return GuardrailController(
            policy=self.policy, tool_timeout_seconds=self.tool_timeout_seconds,
            total_timeout_seconds=self.total_timeout_seconds,
            provider_call_cost_usd=self.provider_call_cost_usd, sleep=self._sleep,
            clock=self._clock, _cost=self.cost, _circuit=self.circuit,
        )

    def execute(
        self, operation: Callable[[], T], *, cancel: Callable[[], None] | None = None,
        output_tokens: int = 0, cost_usd: float | None = None,
    ) -> T:
        """Run one bounded operation with an optional provider-specific cost.

        Local Ollama calls pass ``cost_usd=0``; remote research/specialist calls
        use the configured conservative reservation. This keeps one shared
        reservation mechanic without charging local inference as cloud spend.
        """
        reservation = self.ledger.reserve(steps=1, concurrency=1, output_tokens=output_tokens)
        reserved_cost = self.provider_call_cost_usd if cost_usd is None else cost_usd
        try:
            self.circuit.allow(self._clock())
            started = self._clock()
            for attempt in range(self.policy.max_retries + 1):
                if self._clock() - started > self.total_timeout_seconds:
                    raise ProviderTimeoutError("total request timeout exceeded")
                try:
                    call_reservation = self.ledger.reserve(provider_calls=1)
                    try:
                        remaining = self.total_timeout_seconds - (self._clock() - started)
                        if remaining <= 0:
                            raise ProviderTimeoutError("total request timeout exceeded")
                        # Reserve every attempted call independently. Once a call
                        # is sent, retain the conservative estimate even if the
                        # provider times out or rejects it; such calls may bill.
                        self.cost.reserve(reserved_cost)
                        self.request_cost_usd += reserved_cost
                        value = self._run_with_timeout(
                            operation, cancel, timeout_seconds=min(self.tool_timeout_seconds, remaining)
                        )
                    finally:
                        self.ledger.release(call_reservation)
                    self.circuit.record_success()
                    self.cost.reconcile(reserved_cost, reserved_cost)
                    return value
                except CancelledError:
                    raise
                except TransientProviderError:
                    self.circuit.record_failure(self._clock())
                    if (attempt >= self.policy.max_retries
                            or self.ledger.snapshot[1] >= self.policy.max_provider_calls):
                        raise
                    self.retry_count += 1
                    delay = self.retry.delay_for(attempt + 1)
                    if self._clock() - started + delay >= self.total_timeout_seconds:
                        raise ProviderTimeoutError("total request timeout exceeded")
                    self._sleep(delay)
                except ProviderTimeoutError:
                    # Retry a timed-out operation only when the adapter exposes a
                    # cancellation hook, avoiding overlapping unknown live calls.
                    self.circuit.record_failure(self._clock())
                    if (cancel is None or attempt >= self.policy.max_retries
                            or self.ledger.snapshot[1] >= self.policy.max_provider_calls):
                        raise
                    self.retry_count += 1
                    delay = self.retry.delay_for(attempt + 1)
                    if self._clock() - started + delay >= self.total_timeout_seconds:
                        raise ProviderTimeoutError("total request timeout exceeded")
                    self._sleep(delay)
            raise RuntimeError("retry loop exhausted without a result")
        finally:
            self.ledger.release(reservation)

    def _run_with_timeout(
        self, operation: Callable[[], T], cancel: Callable[[], None] | None,
        *, timeout_seconds: float,
    ) -> T:
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="elly-guardrail")
        future = executor.submit(operation)
        try:
            return future.result(timeout=timeout_seconds)
        except FutureTimeout as exc:
            if cancel is not None:
                cancel()
            raise ProviderTimeoutError("provider call timeout exceeded") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
