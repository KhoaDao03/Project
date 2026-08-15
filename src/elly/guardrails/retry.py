"""Deterministic bounded retry and circuit-breaker policies (NFR-002)."""

from __future__ import annotations

from dataclasses import dataclass
from random import Random
from threading import Lock

from ..domain.errors import CircuitOpenError


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_retries: int = 1
    base_delay_seconds: float = 0.05
    max_delay_seconds: float = 1.0
    jitter_seconds: float = 0.01
    seed: int = 0

    def delay_for(self, retry_number: int) -> float:
        if retry_number <= 0:
            return 0.0
        rng = Random(self.seed + retry_number)
        exponential = min(self.max_delay_seconds, self.base_delay_seconds * (2 ** (retry_number - 1)))
        return float(exponential + rng.uniform(0.0, self.jitter_seconds))


class CircuitBreaker:
    """Thread-safe closed/open circuit with deterministic failure threshold."""

    def __init__(self, *, failure_threshold: int = 3, reset_after_seconds: float = 30.0) -> None:
        self.failure_threshold = failure_threshold
        self.reset_after_seconds = reset_after_seconds
        self._failures = 0
        self._opened_at: float | None = None
        self._lock = Lock()

    def allow(self, now: float) -> None:
        with self._lock:
            if self._opened_at is not None:
                if now - self._opened_at < self.reset_after_seconds:
                    raise CircuitOpenError("provider circuit is open")
                self._opened_at = None
                self._failures = 0

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None

    def record_failure(self, now: float) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._opened_at = now

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._opened_at is not None
