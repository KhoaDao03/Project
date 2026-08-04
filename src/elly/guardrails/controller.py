"""Application-owned guardrail orchestration around provider calls."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from collections.abc import Callable
from typing import TypeVar

from ..domain.errors import CancelledError, EllyError, ProviderTimeoutError, TransientProviderError
from .cost import FakeCostLedger
from .limits import LimitPolicy, ReservationLedger
from .retry import CircuitBreaker, RetryPolicy

T = TypeVar("T")


class GuardrailController:
    """Reserves resources before calls and maps retry/timeout policy deterministically."""

    def __init__(self, *, policy: LimitPolicy, tool_timeout_seconds: float, total_timeout_seconds: float, provider_call_cost_usd: float = 0.0, sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> None:
        self.policy = policy
        self.ledger = ReservationLedger(policy)
        self.cost = FakeCostLedger(policy.monthly_budget_usd)
        self.retry = RetryPolicy(max_retries=policy.max_retries)
        self.circuit = CircuitBreaker()
        self.tool_timeout_seconds = tool_timeout_seconds
        self.total_timeout_seconds = total_timeout_seconds
        self.provider_call_cost_usd = provider_call_cost_usd
        self._sleep = sleep
        self._clock = clock

    def execute(self, operation: Callable[[], T], *, cancel: Callable[[], None] | None = None, output_tokens: int = 0) -> T:
        reservation = self.ledger.reserve(steps=1, concurrency=1, output_tokens=output_tokens)
        reserved_cost = self.provider_call_cost_usd
        settled = False
        try:
            self.cost.reserve(reserved_cost)
            self.circuit.allow(self._clock())
            started = self._clock()
            for attempt in range(self.policy.max_retries + 1):
                if self._clock() - started > self.total_timeout_seconds:
                    raise ProviderTimeoutError("total request timeout exceeded")
                try:
                    call_reservation = self.ledger.reserve(provider_calls=1)
                    try:
                        value = self._run_with_timeout(operation, cancel)
                    finally:
                        self.ledger.release(call_reservation)
                    self.circuit.record_success()
                    self.cost.reconcile(reserved_cost, reserved_cost)
                    settled = True
                    return value
                except CancelledError:
                    self.cost.reconcile(reserved_cost, 0.0)
                    settled = True
                    raise
                except TransientProviderError:
                    self.circuit.record_failure(self._clock())
                    if attempt >= self.policy.max_retries:
                        self.cost.reconcile(reserved_cost, 0.0)
                        settled = True
                        raise
                    self._sleep(self.retry.delay_for(attempt + 1))
            raise RuntimeError("retry loop exhausted without a result")
        except EllyError:
            if not settled:
                self.cost.reconcile(reserved_cost, 0.0)
            raise
        finally:
            self.ledger.release(reservation)

    def _run_with_timeout(self, operation: Callable[[], T], cancel: Callable[[], None] | None) -> T:
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="elly-guardrail")
        future = executor.submit(operation)
        try:
            return future.result(timeout=self.tool_timeout_seconds)
        except FutureTimeout as exc:
            if cancel is not None:
                cancel()
            raise ProviderTimeoutError("provider call timeout exceeded") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
