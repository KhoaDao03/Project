"""ClockPort — injectable time source (DESIGN §6.7).

Responsibility: provide UTC "now" so time is testable and deterministic. Domain
and application code must obtain time through this port, never by calling
datetime.now() directly, so tests can pin time (FixedClock).

Contract:
- now(): timezone-aware UTC datetime.
- side effects: none. failures: none.

Replacement: `adapters.system_clock.SystemClock` (real) and `FixedClock` (test).
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class ClockPort(Protocol):
    """Contract for a UTC time source."""

    def now(self) -> datetime:
        """Return the current time as a timezone-aware UTC datetime."""
        ...
