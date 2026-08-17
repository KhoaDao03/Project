"""Audit, sources, provenance, leases, retention, and health persistence."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from elly.domain.errors import StorageFailureError
from elly.domain.models import AuditEvent, OperationLease, ProvenanceReference

from .codecs import _iso, _parse
from .connection import _SerializedConnection


class _MetadataStore:
    """Internal metadata/idempotency persistence surface mixed into the façade."""

    _conn: _SerializedConnection
    def purge_task_sources(self, before: datetime) -> int:
        """Delete source/evidence metadata older than DEC-OQ-08 retention."""
        try:
            with self._conn:
                cursor = self._conn.execute(
                    "DELETE FROM task_sources WHERE created_at < ?", (_iso(before),)
                )
                return cursor.rowcount
        except sqlite3.Error as exc:
            raise StorageFailureError(f"purge sources failed: {type(exc).__name__}") from exc

    def purge_task_provenance(self, before: datetime) -> int:
        try:
            with self._conn:
                cursor = self._conn.execute(
                    "DELETE FROM task_provenance WHERE recorded_at IS NOT NULL AND recorded_at < ?",
                    (_iso(before),),
                )
                return cursor.rowcount
        except sqlite3.Error as exc:
            raise StorageFailureError(f"purge provenance failed: {type(exc).__name__}") from exc

    def purge_audit_events(self, before: datetime) -> int:
        """Delete redacted audit metadata older than DEC-OQ-08 retention."""
        try:
            with self._conn:
                cursor = self._conn.execute(
                    "DELETE FROM audit_events WHERE at < ?", (_iso(before),)
                )
                return cursor.rowcount
        except sqlite3.Error as exc:
            raise StorageFailureError(f"purge audit failed: {type(exc).__name__}") from exc

    def healthcheck(self) -> None:
        """Verify the connection and every required schema-v2 table without mutation."""
        required = {
            "sessions",
            "messages",
            "tasks",
            "profile_items",
            "audit_events",
            "task_sources",
            "task_operations",
            "task_provenance",
            "task_results",
            "execution_plans",
            "plan_steps",
            "plan_dependencies",
            "step_results",
            "step_claims",
            "step_claim_supports",
            "plan_events",
            "synthesis_results",
        }
        try:
            self._conn.execute("SELECT 1").fetchone()
            rows = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        except sqlite3.Error as exc:
            raise StorageFailureError(f"storage healthcheck failed: {type(exc).__name__}") from exc
        missing = required - {row[0] for row in rows}
        if missing:
            raise StorageFailureError("storage healthcheck found an incomplete schema")

    # ---- M6 durable trace/source metadata -------------------------------

    def append_audit(self, event: AuditEvent) -> None:
        try:
            with self._conn:
                self._insert_audit_event(event)
        except sqlite3.Error as exc:
            raise StorageFailureError(f"append audit failed: {type(exc).__name__}") from exc

    def _insert_audit_event(self, event: AuditEvent) -> None:
        self._conn.execute(
            "INSERT INTO audit_events(task_id,session_id,event_type,at,route,task_status,error_class,detail) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                event.task_id,
                event.session_id,
                event.event_type,
                _iso(event.at),
                event.route.value if event.route else None,
                event.task_status.value if event.task_status else None,
                event.error_class.value if event.error_class else None,
                event.detail,
            ),
        )

    def audit_by_task(self, task_id: str) -> list[AuditEvent]:
        try:
            from ...domain.enums import ErrorClass, Route, TaskStatus

            rows = self._conn.execute(
                "SELECT task_id,session_id,event_type,at,route,task_status,error_class,detail FROM audit_events WHERE task_id=? ORDER BY id",
                (task_id,),
            ).fetchall()
            return [
                AuditEvent(
                    r[0],
                    r[1],
                    r[2],
                    _parse(r[3]),
                    Route(r[4]) if r[4] else None,
                    TaskStatus(r[5]) if r[5] else None,
                    ErrorClass(r[6]) if r[6] else None,
                    r[7],
                )
                for r in rows
            ]
        except sqlite3.Error as exc:
            raise StorageFailureError(f"query audit failed: {type(exc).__name__}") from exc

    def add_task_source(self, task_id: str, source: str, at: datetime) -> None:
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT OR IGNORE INTO task_sources(task_id,source,created_at) VALUES (?,?,?)",
                    (task_id, source, _iso(at)),
                )
        except sqlite3.Error as exc:
            raise StorageFailureError(f"add source failed: {type(exc).__name__}") from exc

    def add_task_provenance(self, task_id: str, reference: ProvenanceReference) -> None:
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT OR IGNORE INTO task_provenance(task_id,kind,reference_id,recorded_at) VALUES (?,?,?,?)",
                    (
                        task_id,
                        reference.kind,
                        reference.reference_id,
                        _iso(reference.recorded_at) if reference.recorded_at else None,
                    ),
                )
        except sqlite3.Error as exc:
            raise StorageFailureError(f"add provenance failed: {type(exc).__name__}") from exc

    def claim_operation(
        self,
        *,
        task_id: str,
        request_id: str,
        capability_id: str,
        request_digest: str,
        at: datetime,
    ) -> OperationLease:
        operation_id = f"op-{task_id}-{capability_id}-{request_digest[:16]}"
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT OR IGNORE INTO task_operations(operation_id,task_id,request_id,capability_id,request_digest,state,possible_duplicate,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        operation_id,
                        task_id,
                        request_id,
                        capability_id,
                        request_digest,
                        "running",
                        0,
                        _iso(at),
                        _iso(at),
                    ),
                )
                row = self._conn.execute(
                    "SELECT operation_id,state,possible_duplicate FROM task_operations WHERE task_id=? AND capability_id=? AND request_digest=?",
                    (task_id, capability_id, request_digest),
                ).fetchone()
                if row is None:
                    raise StorageFailureError("operation claim was not recorded")
                operation_id_in_db, state, possible_duplicate = row
                if state in {"failed", "cancelled"} and not possible_duplicate:
                    # No external operation was recorded as having started; a
                    # subsequent identical request may retry this failed work.
                    self._conn.execute(
                        "UPDATE task_operations SET state='running',updated_at=? WHERE operation_id=?",
                        (_iso(at), operation_id_in_db),
                    )
                    state = "running"
                    fresh = True
                else:
                    fresh = (
                        operation_id_in_db == operation_id
                        and state == "running"
                        and possible_duplicate == 0
                    )
                if not fresh:
                    self._conn.execute(
                        "UPDATE task_operations SET possible_duplicate=1,updated_at=? WHERE operation_id=?",
                        (_iso(at), operation_id_in_db),
                    )
                return OperationLease(
                    operation_id_in_db,
                    fresh,
                    state,
                    bool(possible_duplicate) or not fresh,
                )
        except sqlite3.Error as exc:
            raise StorageFailureError(f"claim operation failed: {type(exc).__name__}") from exc

    def complete_operation(self, operation_id: str, *, at: datetime) -> None:
        self._update_operation_state(operation_id, "completed", at)

    def fail_operation(
        self, operation_id: str, *, at: datetime, possible_duplicate: bool = False
    ) -> None:
        self._update_operation_state(
            operation_id, "failed", at, possible_duplicate=possible_duplicate
        )

    def _update_operation_state(
        self,
        operation_id: str,
        state: str,
        at: datetime,
        *,
        possible_duplicate: bool = False,
    ) -> None:
        try:
            with self._conn:
                if possible_duplicate:
                    cursor = self._conn.execute(
                        "UPDATE task_operations SET state=?,possible_duplicate=1,updated_at=? WHERE operation_id=?",
                        (state, _iso(at), operation_id),
                    )
                else:
                    cursor = self._conn.execute(
                        "UPDATE task_operations SET state=?,updated_at=? WHERE operation_id=?",
                        (state, _iso(at), operation_id),
                    )
                if cursor.rowcount != 1:
                    raise StorageFailureError("operation record not found")
        except sqlite3.Error as exc:
            raise StorageFailureError(f"update operation failed: {type(exc).__name__}") from exc

    def task_sources(self, task_id: str) -> tuple[str, ...]:
        try:
            return tuple(
                row[0]
                for row in self._conn.execute(
                    "SELECT source FROM task_sources WHERE task_id=? ORDER BY source", (task_id,)
                ).fetchall()
            )
        except sqlite3.Error as exc:
            raise StorageFailureError(f"query sources failed: {type(exc).__name__}") from exc
