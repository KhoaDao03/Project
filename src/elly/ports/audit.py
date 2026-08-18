"""AuditPort — append-only, redacted operational records (DESIGN §6.7, §5.8).

Responsibility: durably record correlated, REDACTED audit events (DATA-004,
SEC-007). The event model itself carries no bodies/secrets; this port must not
add any.

Contract:
- append: store one AuditEvent. Audit-write failure must be surfaced, not
  swallowed (DATA-004): raise StorageFailureError. High-impact workflows may
  fail closed when their audit boundary is unavailable.
- by_task: return events for a task_id in chronological order (UC-11 initial).

Related: DATA-004, SEC-007, OPS-001.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import AuditEvent, HealthReport


@runtime_checkable
class AuditPort(Protocol):
    """Contract for append-only redacted audit storage."""

    def append(self, event: AuditEvent) -> None:
        """Durably append one redacted event. Raise StorageFailureError on failure."""
        ...

    def by_task(self, task_id: str) -> list[AuditEvent]:
        """Return all events for a task, chronological order."""
        ...

    def health(self) -> HealthReport:
        """Probe the sink without writing an event or exposing sensitive data."""
        ...
