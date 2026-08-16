"""Atomic M3 resource reservations (AI-019, NFR-001)."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from ..domain.errors import ConfigInvalidError, LimitExceededError


@dataclass(frozen=True, slots=True)
class LimitPolicy:
    max_steps: int = 6
    max_provider_calls: int = 2
    max_retries: int = 1
    max_concurrency: int = 1
    monthly_budget_usd: float = 10.0
    max_output_tokens: int = 512

    def __post_init__(self) -> None:
        if (
            min(
                self.max_steps,
                self.max_provider_calls,
                self.max_concurrency,
                self.max_output_tokens,
            )
            <= 0
        ):
            raise ConfigInvalidError("positive guardrail limits are required")
        if self.max_retries < 0 or self.monthly_budget_usd < 0:
            raise ConfigInvalidError("retry and budget limits must be non-negative")


@dataclass(frozen=True, slots=True)
class Reservation:
    steps: int
    provider_calls: int
    concurrency: int
    output_tokens: int


class ReservationLedger:
    """Thread-safe per-request reservation ledger; rejection is fail-closed."""

    def __init__(self, policy: LimitPolicy) -> None:
        self.policy = policy
        self._lock = Lock()
        self._steps = 0
        self._provider_calls = 0
        self._active = 0

    def reserve(
        self,
        *,
        steps: int = 0,
        provider_calls: int = 0,
        concurrency: int = 0,
        output_tokens: int = 0,
    ) -> Reservation:
        if min(steps, provider_calls, concurrency, output_tokens) < 0:
            raise LimitExceededError("negative resource reservation")
        if output_tokens > self.policy.max_output_tokens:
            raise LimitExceededError("output token limit exceeded")
        with self._lock:
            if self._steps + steps > self.policy.max_steps:
                raise LimitExceededError("orchestration step limit exceeded")
            if self._provider_calls + provider_calls > self.policy.max_provider_calls:
                raise LimitExceededError("provider call limit exceeded")
            if self._active + concurrency > self.policy.max_concurrency:
                raise LimitExceededError("concurrency limit exceeded")
            self._steps += steps
            self._provider_calls += provider_calls
            self._active += concurrency
        return Reservation(steps, provider_calls, concurrency, output_tokens)

    def release(self, reservation: Reservation) -> None:
        with self._lock:
            self._active = max(0, self._active - reservation.concurrency)

    @property
    def snapshot(self) -> tuple[int, int, int]:
        with self._lock:
            return self._steps, self._provider_calls, self._active
