"""Session, message, task, and task-result persistence implementation."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from elly.application.routing.compatibility import ROUTING_CONTRACT_VERSION, generic_route_for
from elly.domain.enums import (
    CloudMode,
    EpistemicStatus,
    OutcomeCode,
    PersistenceMode,
    Route,
    TaskStatus,
    ValidationStatus,
)
from elly.domain.errors import ConflictError, StorageFailureError
from elly.domain.models import AuditEvent, Message, SessionRecord, TaskResult

from .codecs import _iso, _parse
from .connection import _SerializedConnection


class _SessionTaskStore:
    """Internal session/task persistence surface mixed into the façade."""

    _conn: _SerializedConnection

    def create_session(self, session: SessionRecord) -> None:
        if session.updated_at is None:
            raise StorageFailureError("session updated_at is required")
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO sessions "
                    "(session_id, persistence_mode, cloud_mode, created_at, updated_at, version)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        session.session_id,
                        session.persistence_mode.value,
                        session.cloud_mode.value,
                        _iso(session.created_at),
                        _iso(session.updated_at),
                        session.version,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise StorageFailureError("session already exists") from exc
        except sqlite3.Error as exc:
            raise StorageFailureError(f"create_session failed: {type(exc).__name__}") from exc

    def get_session(self, session_id: str) -> SessionRecord | None:
        try:
            row = self._conn.execute(
                "SELECT session_id, persistence_mode, cloud_mode, created_at, updated_at, version"
                " FROM sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise StorageFailureError(f"get_session failed: {type(exc).__name__}") from exc
        if row is None:
            return None
        return SessionRecord(
            session_id=row[0],
            persistence_mode=PersistenceMode(row[1]),
            cloud_mode=CloudMode(row[2]),
            created_at=_parse(row[3]),
            updated_at=_parse(row[4]) if row[4] else _parse(row[3]),
            version=int(row[5]),
        )

    def update_cloud_mode(
        self,
        session_id: str,
        expected_version: int,
        new_mode: CloudMode,
        at: datetime,
        audit_event: AuditEvent | None = None,
    ) -> SessionRecord:
        """Atomically compare-and-set a session mode and optional audit event."""
        if expected_version < 1:
            raise ConflictError("session version is invalid")
        try:
            with self._conn:
                cursor = self._conn.execute(
                    "UPDATE sessions SET cloud_mode=?, updated_at=?, version=version+1 "
                    "WHERE session_id=? AND version=?",
                    (new_mode.value, _iso(at), session_id, expected_version),
                )
                if cursor.rowcount != 1:
                    exists = self._conn.execute(
                        "SELECT 1 FROM sessions WHERE session_id=?", (session_id,)
                    ).fetchone()
                    if exists is None:
                        raise StorageFailureError("session not found")
                    raise ConflictError("session version conflict")
                if audit_event is not None:
                    self._insert_audit_event(audit_event)  # type: ignore[attr-defined]
                row = self._conn.execute(
                    "SELECT session_id, persistence_mode, cloud_mode, created_at, updated_at, version "
                    "FROM sessions WHERE session_id=?",
                    (session_id,),
                ).fetchone()
                if row is None:
                    raise StorageFailureError("updated session could not be read")
                return SessionRecord(
                    session_id=row[0],
                    persistence_mode=PersistenceMode(row[1]),
                    cloud_mode=CloudMode(row[2]),
                    created_at=_parse(row[3]),
                    updated_at=_parse(row[4]),
                    version=int(row[5]),
                )
        except ConflictError:
            raise
        except StorageFailureError:
            raise
        except sqlite3.Error as exc:
            raise StorageFailureError(f"update cloud mode failed: {type(exc).__name__}") from exc

    def append_message(self, session_id: str, message: Message) -> None:
        session = self.get_session(session_id)
        if session is None:
            raise StorageFailureError("append to unknown session")
        no_store = session.persistence_mode is PersistenceMode.NO_STORE
        # DATA-001: never persist bodies for no-store sessions.
        stored_body = 0 if no_store else 1
        body = "" if no_store else message.content
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO messages (session_id, role, content, stored_body, created_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (session_id, message.role, body, stored_body, _iso(message.created_at)),
                )
        except sqlite3.Error as exc:
            raise StorageFailureError(f"append_message failed: {type(exc).__name__}") from exc

    def start_task(self, task_id: str, session_id: str, at: datetime) -> bool:
        """Record an in-flight task and identify whether this is a new request.

        A completed task is left untouched so a repeated request ID cannot reset
        its durable state.  retryable terminal states are reopened; the
        operation ledger makes the subsequent provider call idempotent.
        """
        try:
            with self._conn:
                cursor = self._conn.execute(
                    "INSERT OR IGNORE INTO tasks(task_id, session_id, status, started_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (task_id, session_id, "running", _iso(at), _iso(at)),
                )
                if cursor.rowcount == 1:
                    return True
                row = self._conn.execute(
                    "SELECT status FROM tasks WHERE task_id=?", (task_id,)
                ).fetchone()
                if row is None:
                    raise StorageFailureError("task start was not recorded")
                if row[0] in {"failed", "blocked", "cancelled", "interrupted", "awaiting_consent"}:
                    self._conn.execute(
                        "UPDATE tasks SET status='running', updated_at=? WHERE task_id=?",
                        (_iso(at), task_id),
                    )
                return False
        except sqlite3.Error as exc:
            raise StorageFailureError(f"start_task failed: {type(exc).__name__}") from exc

    def finish_task(self, task_id: str, status: str, at: datetime) -> None:
        try:
            with self._conn:
                self._conn.execute(
                    "UPDATE tasks SET status=?, updated_at=? WHERE task_id=?",
                    (status, _iso(at), task_id),
                )
        except sqlite3.Error as exc:
            raise StorageFailureError(f"finish_task failed: {type(exc).__name__}") from exc

    def mark_interrupted_tasks(self, at: datetime) -> int:
        """Mark prior running tasks interrupted; deliberately performs no replay."""
        try:
            with self._conn:
                cursor = self._conn.execute(
                    "UPDATE tasks SET status='interrupted', updated_at=? WHERE status='running'",
                    (_iso(at),),
                )
                return cursor.rowcount
        except sqlite3.Error as exc:
            raise StorageFailureError(f"reconcile tasks failed: {type(exc).__name__}") from exc

    def task_status(self, task_id: str) -> str | None:
        try:
            row = self._conn.execute(
                "SELECT status FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()
        except sqlite3.Error as exc:
            raise StorageFailureError(f"task lookup failed: {type(exc).__name__}") from exc
        return row[0] if row else None

    def task_session_id(self, task_id: str) -> str | None:
        try:
            row = self._conn.execute(
                "SELECT session_id FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()
        except sqlite3.Error as exc:
            raise StorageFailureError(f"task session lookup failed: {type(exc).__name__}") from exc
        return row[0] if row else None

    def save_task_result(self, result: TaskResult, at: datetime) -> None:
        """Persist the normalized result while honoring no-store answer privacy."""
        try:
            session_row = self._conn.execute(
                "SELECT persistence_mode FROM sessions WHERE session_id=(SELECT session_id FROM tasks WHERE task_id=?)",
                (result.task_id,),
            ).fetchone()
            if session_row is None:
                raise StorageFailureError("task result session was not found")
            retain_answer = session_row[0] == PersistenceMode.STORE_WITH_RETENTION.value
            answer = result.answer if retain_answer else ""
            claims = result.claims if retain_answer else ()
            citations = result.citations
            partial_work = result.partial_work if retain_answer else ()
            route_category = result.route_category or generic_route_for(
                result.route_summary, result.capability_id
            )
            public_route = result.route_summary
            contract_version = result.routing_contract_version or ROUTING_CONTRACT_VERSION
            with self._conn:
                self._conn.execute(
                    "UPDATE tasks SET route_category=?, selected_capability_id=?, "
                    "selected_operation=?, selection_reason_code=?, "
                    "routing_contract_version=?, candidate_count=?, "
                    "rejected_candidate_reason_codes_json=?, clarification_required=?, "
                    "freshness_affected_selection=? WHERE task_id=?",
                    (
                        route_category.value,
                        result.capability_id,
                        result.operation,
                        result.selection_reason_code,
                        contract_version,
                        result.candidate_count,
                        json.dumps(list(result.rejected_candidate_reason_codes)),
                        int(result.clarification_required),
                        int(result.freshness_affected_selection),
                        result.task_id,
                    ),
                )
                self._conn.execute(
                    "INSERT OR REPLACE INTO task_results "
                    "(task_id, task_status, outcome_code, epistemic_status, validation_status, "
                    "answer, answer_retained, route, claims_json, citations_json, partial_work_json, "
                    "failures_json, next_actions_json, updated_at, route_category, "
                    "selected_capability_id, selected_operation, selection_reason_code, "
                    "routing_contract_version, candidate_count, "
                    "rejected_candidate_reason_codes_json, clarification_required, "
                    "freshness_affected_selection) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        result.task_id,
                        result.task_status.value,
                        result.outcome_code.value,
                        result.epistemic_status.value,
                        result.validation_status.value,
                        answer,
                        int(retain_answer),
                        public_route.value,
                        json.dumps(list(claims)),
                        json.dumps(list(citations)),
                        json.dumps(list(partial_work)),
                        json.dumps(list(result.failures)),
                        json.dumps(list(result.next_actions)),
                        _iso(at),
                        route_category.value,
                        result.capability_id,
                        result.operation,
                        result.selection_reason_code,
                        contract_version,
                        result.candidate_count,
                        json.dumps(list(result.rejected_candidate_reason_codes)),
                        int(result.clarification_required),
                        int(result.freshness_affected_selection),
                    ),
                )
        except StorageFailureError:
            raise
        except (sqlite3.Error, TypeError, ValueError) as exc:
            raise StorageFailureError(f"save task result failed: {type(exc).__name__}") from exc

    def get_task_result(self, task_id: str) -> TaskResult | None:
        try:
            row = self._conn.execute(
                "SELECT task_id, task_status, outcome_code, epistemic_status, validation_status, "
                "answer, answer_retained, route, claims_json, citations_json, partial_work_json, "
                "failures_json, next_actions_json, route_category, selected_capability_id, "
                "selected_operation, selection_reason_code, routing_contract_version, "
                "candidate_count, rejected_candidate_reason_codes_json, clarification_required, "
                "freshness_affected_selection "
                "FROM task_results WHERE task_id=?",
                (task_id,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise StorageFailureError(f"get task result failed: {type(exc).__name__}") from exc
        if row is None:
            return None
        try:
            stored_route = Route(row[7])
            capability_id = row[14]
            return TaskResult(
                task_id=row[0],
                task_status=TaskStatus(row[1]),
                outcome_code=OutcomeCode(row[2]),
                epistemic_status=EpistemicStatus(row[3]),
                validation_status=ValidationStatus(row[4]),
                answer=row[5],
                answer_retained=bool(row[6]),
                route_summary=stored_route,
                claims=tuple(json.loads(row[8])),
                citations=tuple(json.loads(row[9])),
                partial_work=tuple(json.loads(row[10])),
                failures=tuple(json.loads(row[11])),
                next_actions=tuple(json.loads(row[12])),
                route_category=Route(row[13]) if row[13] else None,
                capability_id=capability_id,
                operation=row[15],
                selection_reason_code=row[16],
                routing_contract_version=row[17],
                candidate_count=int(row[18]),
                rejected_candidate_reason_codes=tuple(json.loads(row[19])),
                clarification_required=bool(row[20]),
                freshness_affected_selection=bool(row[21]),
            )
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise StorageFailureError("stored task result is invalid") from exc

    # ---- M6 profile/data controls ---------------------------------------


    def list_sessions(self) -> list[SessionRecord]:
        try:
            rows = self._conn.execute(
                "SELECT session_id,persistence_mode,cloud_mode,created_at,updated_at,version "
                "FROM sessions ORDER BY created_at"
            ).fetchall()
            return [
                SessionRecord(
                    r[0],
                    PersistenceMode(r[1]),
                    CloudMode(r[2]),
                    _parse(r[3]),
                    _parse(r[4]) if r[4] else _parse(r[3]),
                    int(r[5]),
                )
                for r in rows
            ]
        except sqlite3.Error as exc:
            raise StorageFailureError(f"list sessions failed: {type(exc).__name__}") from exc

    def delete_session(self, session_id: str) -> bool:
        try:
            with self._conn:
                # Foreign keys are enabled; delete dependents explicitly so
                # user-requested deletion is complete and transactional.
                self._conn.execute(
                    "DELETE FROM task_sources WHERE task_id IN (SELECT task_id FROM tasks WHERE session_id=?)",
                    (session_id,),
                )
                self._conn.execute(
                    "DELETE FROM task_operations WHERE task_id IN (SELECT task_id FROM tasks WHERE session_id=?)",
                    (session_id,),
                )
                self._conn.execute(
                    "DELETE FROM task_provenance WHERE task_id IN (SELECT task_id FROM tasks WHERE session_id=?)",
                    (session_id,),
                )
                self._conn.execute(
                    "DELETE FROM task_results WHERE task_id IN (SELECT task_id FROM tasks WHERE session_id=?)",
                    (session_id,),
                )
                self._conn.execute(
                    "DELETE FROM execution_plans WHERE task_id IN (SELECT task_id FROM tasks WHERE session_id=?)",
                    (session_id,),
                )
                self._conn.execute("DELETE FROM audit_events WHERE session_id=?", (session_id,))
                self._conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
                self._conn.execute("DELETE FROM tasks WHERE session_id=?", (session_id,))
                cursor = self._conn.execute(
                    "DELETE FROM sessions WHERE session_id=?", (session_id,)
                )
                return bool(cursor.rowcount)
        except sqlite3.Error as exc:
            raise StorageFailureError(f"delete session failed: {type(exc).__name__}") from exc

    def purge_sessions(self, before: datetime) -> int:
        """Delete expired sessions and all dependent task, source, and audit rows."""
        try:
            with self._conn:
                rows = self._conn.execute(
                    "SELECT session_id FROM sessions WHERE created_at < ?", (_iso(before),)
                ).fetchall()
                for (session_id,) in rows:
                    self._conn.execute(
                        "DELETE FROM task_sources WHERE task_id IN "
                        "(SELECT task_id FROM tasks WHERE session_id=?)",
                        (session_id,),
                    )
                    self._conn.execute(
                        "DELETE FROM task_operations WHERE task_id IN "
                        "(SELECT task_id FROM tasks WHERE session_id=?)",
                        (session_id,),
                    )
                    self._conn.execute(
                        "DELETE FROM task_provenance WHERE task_id IN "
                        "(SELECT task_id FROM tasks WHERE session_id=?)",
                        (session_id,),
                    )
                    self._conn.execute(
                        "DELETE FROM task_results WHERE task_id IN "
                        "(SELECT task_id FROM tasks WHERE session_id=?)",
                        (session_id,),
                    )
                    self._conn.execute(
                        "DELETE FROM execution_plans WHERE task_id IN "
                        "(SELECT task_id FROM tasks WHERE session_id=?)",
                        (session_id,),
                    )
                    self._conn.execute("DELETE FROM audit_events WHERE session_id=?", (session_id,))
                    self._conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
                    self._conn.execute("DELETE FROM tasks WHERE session_id=?", (session_id,))
                    self._conn.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
                return len(rows)
        except sqlite3.Error as exc:
            raise StorageFailureError(f"purge sessions failed: {type(exc).__name__}") from exc


    def recent_messages(self, session_id: str, limit: int) -> list[Message]:
        if limit <= 0:
            return []
        try:
            rows = self._conn.execute(
                "SELECT role, content, stored_body, created_at FROM messages"
                " WHERE session_id=? ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        except sqlite3.Error as exc:
            raise StorageFailureError(f"recent_messages failed: {type(exc).__name__}") from exc
        # Return oldest-first. Redacted (no_store) rows surface as empty content.
        return [Message(role=r[0], content=r[1], created_at=_parse(r[3])) for r in reversed(rows)]
