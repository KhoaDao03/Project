"""Configured fake-price monthly cost ledger (OPS-003 initial)."""

from __future__ import annotations

from threading import Lock

from ..domain.errors import LimitExceededError


class FakeCostLedger:
    """Atomic monthly budget ledger; no live pricing or network calls."""

    def __init__(self, monthly_budget_usd: float) -> None:
        if monthly_budget_usd < 0:
            raise ValueError("monthly budget must be non-negative")
        self._budget = monthly_budget_usd
        self._reserved = 0.0
        self._lock = Lock()

    def reserve(self, amount_usd: float) -> None:
        if amount_usd < 0:
            raise LimitExceededError("negative cost reservation")
        with self._lock:
            if self._reserved + amount_usd > self._budget:
                raise LimitExceededError("monthly budget exceeded")
            self._reserved += amount_usd

    def reconcile(self, reserved_usd: float, actual_usd: float) -> None:
        if min(reserved_usd, actual_usd) < 0:
            raise ValueError("cost values must be non-negative")
        with self._lock:
            self._reserved = max(0.0, self._reserved - reserved_usd + actual_usd)

    @property
    def reserved_usd(self) -> float:
        with self._lock:
            return self._reserved
