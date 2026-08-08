"""StructuredAuditLog — redacted, correlated audit sink (M6).

Implements `ports.audit.AuditPort`. Behavior is real (append/query/redaction);
When constructed with a repository, events are also durably stored as redacted
metadata. Without one, the in-process mode remains useful for isolated tests.

Redaction (SEC-007): the AuditEvent model has no body/secret fields by design.
This sink additionally strips newlines and truncates `detail` so a long or
multi-line summary cannot smuggle raw content into logs. It never logs prompts,
answers, message bodies, credentials, or chain-of-thought.

Status: Implemented + Tested (M6).
"""

from __future__ import annotations

import logging
import re

from ..domain.enums import HealthState
from ..domain.models import AuditEvent, HealthReport
from ..ports.repository import SessionRepositoryPort

_MAX_DETAIL = 200
_SECRET_VALUE = re.compile(
    r"(?i)\b(api[_ -]?key|secret|password|token)\b\s*[:=]\s*([^\s,;]+)"
)


def _redact_detail(detail: str) -> str:
    redacted = _SECRET_VALUE.sub(lambda match: f"{match.group(1)}=[REDACTED]", detail)
    single_line = " ".join(redacted.split())
    return single_line[:_MAX_DETAIL]


class StructuredAuditLog:
    """In-process, redacting audit sink that also emits structured log lines."""

    def __init__(self, logger: logging.Logger | None = None, repository: SessionRepositoryPort | None = None) -> None:
        self._events: list[AuditEvent] = []
        self._log = logger or logging.getLogger("elly.audit")
        self._repository = repository

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
        if self._repository is not None:
            self._repository.append_audit(safe)
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
        if self._repository is not None:
            return self._repository.audit_by_task(task_id)
        return [e for e in self._events if e.task_id == task_id]

    def health(self) -> HealthReport:
        """Probe the durable sink when configured; never writes a synthetic event."""
        if self._repository is None:
            return HealthReport(component="audit(memory)", state=HealthState.HEALTHY)
        try:
            self._repository.healthcheck()
            return HealthReport(component="audit", state=HealthState.HEALTHY)
        except Exception as exc:  # noqa: BLE001 - health must report, not raise
            return HealthReport(
                component="audit", state=HealthState.UNAVAILABLE,
                detail=type(exc).__name__,
            )
