"""Clock adapters: SystemClock (real) and FixedClock (deterministic test fake).

Implements `ports.clock.ClockPort`.
"""

from __future__ import annotations

from datetime import datetime, timezone


class SystemClock:
    """Real UTC clock."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FixedClock:
    """DETERMINISTIC FAKE clock — returns a pinned time; optionally advances.

    Test-only. Not used in production wiring.
    """

    def __init__(self, fixed: datetime, step_seconds: float = 0.0) -> None:
        if fixed.tzinfo is None:
            raise ValueError("FixedClock requires a timezone-aware datetime")
        self._current = fixed.astimezone(timezone.utc)
        self._step_seconds = step_seconds

    def now(self) -> datetime:
        value = self._current
        if self._step_seconds:
            from datetime import timedelta

            self._current = self._current + timedelta(seconds=self._step_seconds)
        return value
