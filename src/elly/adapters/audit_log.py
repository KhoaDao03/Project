"""StructuredAuditLog — redacted, correlated audit sink (M1, initial).

Implements `ports.audit.AuditPort`. Behavior is real (append/query/redaction);
DURABILITY is intentionally minimal in M1 — events are held in-process and
emitted as redacted structured log lines. A durable audit store is DATA-004/M6.

Redaction (SEC-007): the AuditEvent model has no body/secret fields by design.
This sink additionally strips newlines and truncates `detail` so a long or
multi-line summary cannot smuggle raw content into logs. It never logs prompts,
answers, message bodies, credentials, or chain-of-thought.

Status: Scaffolded + Tested (M1). Labeled non-durable; do not treat as the
finished DATA-004 capability.
"""

from __future__ import annotations

import logging

from ..domain.models import AuditEvent

_MAX_DETAIL = 200


def _redact_detail(detail: str) -> str:
    single_line = " ".join(detail.split())
    return single_line[:_MAX_DETAIL]


class StructuredAuditLog:
    """In-process, redacting audit sink that also emits structured log lines."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._events: list[AuditEvent] = []
        self._log = logger or logging.getLogger("elly.audit")

    def append(self, event: AuditEvent) -> None:
        safe = AuditEvent(
            task_id=event.task_id,
            session_id=event.session_id,
            event_type=event.event_type,
            at=event.at,
            route=event.route,
            task_status=event.task_status,
            error_class=event.error_class,
            detail=_redact_detail(event.detail),
        )
        self._events.append(safe)
        # Allowlisted fields only — never the raw detail beyond the redacted form.
        self._log.info(
            "audit event_type=%s task=%s session=%s route=%s status=%s error=%s",
            safe.event_type,
            safe.task_id,
            safe.session_id,
            safe.route.value if safe.route else "-",
            safe.task_status.value if safe.task_status else "-",
            safe.error_class.value if safe.error_class else "-",
        )

    def by_task(self, task_id: str) -> list[AuditEvent]:
        return [e for e in self._events if e.task_id == task_id]
