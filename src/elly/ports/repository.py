"""SessionRepositoryPort — session/message persistence contract (DESIGN §6.7).

Responsibility: persist and read back sessions and messages, honoring
PersistenceMode (DATA-001). This is a REAL capability in M1, backed by SQLite.

Contract:
- create_session / get_session: manage the conversation boundary record.
- append_message: append a turn. If the session is NO_STORE, message BODIES must
  not be persisted (the implementation stores nothing or a redacted placeholder);
  callers must not rely on reloading no-store bodies (DATA-001).
- recent_messages: return up to `limit` most-recent messages for context building
  (FR-002 / AI-006). No-store sessions return only what is available in-process.
- apply_migrations: create/upgrade schema transactionally (OPS-004 initial).
- failures: StorageFailureError on transaction/corruption problems — never a
  silent empty success (FR-006 fail-closed).

Replacement strategy: an alternate store (e.g., Postgres, ADR alternatives) would
implement this same port; tests point the SQLite adapter at ":memory:".

Related: DATA-001, DATA-004 (audit is a separate port), OPS-004.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from ..domain.models import AuditEvent, Message, OperationLease, ProvenanceReference, SessionRecord
from ..memory import ProfileItem


@runtime_checkable
class SessionRepositoryPort(Protocol):
    """Contract for session/message persistence."""

    def apply_migrations(self) -> None:
        """Ensure the schema exists/upgraded; transactional. Raise StorageFailureError on failure."""
        ...

    def create_session(self, session: SessionRecord) -> None:
        """Persist a new session record. Raise StorageFailureError on failure."""
        ...

    def get_session(self, session_id: str) -> SessionRecord | None:
        """Return the session record or None if unknown."""
        ...

    def append_message(self, session_id: str, message: Message) -> None:
        """Append a turn, honoring the session's PersistenceMode (DATA-001)."""
        ...

    def recent_messages(self, session_id: str, limit: int) -> list[Message]:
        """Return up to `limit` most-recent persisted messages, oldest-first."""
        ...

    def purge_sessions(self, before: datetime) -> int:
        """Delete expired sessions and dependent records transactionally."""
        ...

    def purge_task_sources(self, before: datetime) -> int:
        """Delete source metadata older than the evidence-retention cutoff."""
        ...

    def purge_task_provenance(self, before: datetime) -> int:
        ...

    def purge_audit_events(self, before: datetime) -> int:
        """Delete audit metadata older than the audit-retention cutoff."""
        ...

    def healthcheck(self) -> None:
        """Raise StorageFailureError unless the connection and schema are usable."""
        ...

    def start_task(self, task_id: str, session_id: str, at: datetime) -> bool:
        """Start a task and return whether this request created a new task row."""
        ...

    def finish_task(self, task_id: str, status: str, at: datetime) -> None:
        ...

    def task_status(self, task_id: str) -> str | None:
        ...

    def mark_interrupted_tasks(self, at: datetime) -> int:
        ...

    def append_audit(self, event: AuditEvent) -> None:
        ...

    def add_task_source(self, task_id: str, source: str, at: datetime) -> None:
        ...

    def add_task_provenance(self, task_id: str, reference: ProvenanceReference) -> None:
        ...

    def audit_by_task(self, task_id: str) -> list[AuditEvent]:
        ...

    def task_sources(self, task_id: str) -> tuple[str, ...]:
        ...

    def list_sessions(self) -> list[SessionRecord]:
        ...

    def delete_session(self, session_id: str) -> bool:
        ...

    def add_profile_item(self, item: ProfileItem) -> None:
        ...

    def list_profile_items(self) -> list[ProfileItem]:
        ...

    def get_profile_item(self, item_id: str) -> ProfileItem | None:
        ...

    def update_profile_item(self, item: ProfileItem) -> None:
        ...

    def delete_profile_item(self, item_id: str, at: datetime) -> bool:
        ...

    def purge_expired_profile(self, now: datetime) -> int:
        ...

    def quarantine_profile_store(self, at: datetime) -> str:
        ...

    def close(self) -> None:
        ...

    def claim_operation(
        self, *, task_id: str, request_id: str, capability_id: str,
        request_digest: str, at: datetime,
    ) -> OperationLease:
        ...

    def complete_operation(self, operation_id: str, *, at: datetime) -> None:
        ...

    def fail_operation(
        self, operation_id: str, *, at: datetime, possible_duplicate: bool = False
    ) -> None:
        ...
