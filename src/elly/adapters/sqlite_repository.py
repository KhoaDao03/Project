"""SqliteSessionRepository — REAL M1 persistence (DESIGN §5.9, ADR-006).

Implements `ports.repository.SessionRepositoryPort` on stdlib sqlite3 (WAL mode).
This is a genuine capability in M1, not a fake: sessions and (when permitted)
message bodies are stored transactionally.

Privacy (DATA-001): when a session's PersistenceMode is NO_STORE, message BODIES
are not written — only a redacted placeholder row is kept so counts/metadata
remain consistent, and `recent_messages` returns the placeholder content as empty.

Failures: any sqlite error is wrapped as StorageFailureError (FR-006 fail-closed);
provider-specific exceptions never cross the port boundary.

Tests point `db_path` at ":memory:" for a fast, isolated real database.

M6 adds profile/session retention, durable redacted audit metadata, and source/task
metadata. Backup encryption remains in `operations.py` so storage transactions stay
inside this adapter.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from types import TracebackType

from ..application.plan_state import ensure_plan_transition, ensure_step_transition
from ..application.route_compatibility import (
    ROUTING_CONTRACT_VERSION,
    generic_route_for,
)
from ..application.step_results import StepResultEnvelope
from ..domain.enums import (
    ActionCategory,
    CloudMode,
    EpistemicStatus,
    OutcomeCode,
    PersistenceMode,
    Route,
    TaskStatus,
    ValidationStatus,
)
from ..domain.errors import (
    ConflictError,
    InputInvalidError,
    MalformedResultError,
    StorageFailureError,
)
from ..domain.models import (
    AuditEvent,
    ClaimSupport,
    Message,
    OperationLease,
    ProvenanceReference,
    SessionRecord,
    TaskResult,
)
from ..memory import ProfileItem
from ..planning.contracts import (
    AuthorizationState,
    ExecutionPlan,
    FinalizationStrategy,
    InputBinding,
    PlanLimitsSnapshot,
    PlanStatus,
    PlanStep,
    StepCriticality,
    StepKind,
    StepState,
)
from ..ports.plan_repository import PlanEvent, SynthesisResultRecord
from ..trace_safety import redact_trace_detail

_SCHEMA_VERSION = 7
_SAFE_EVENT_CODE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")

_MIGRATION_V1 = """
CREATE TABLE IF NOT EXISTS schema_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    session_id       TEXT PRIMARY KEY,
    persistence_mode TEXT NOT NULL,
    cloud_mode       TEXT NOT NULL,
    created_at       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES sessions(session_id),
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    stored_body INTEGER NOT NULL,   -- 1 if body persisted, 0 if redacted (no_store)
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
CREATE TABLE IF NOT EXISTS tasks (
    task_id    TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    status     TEXT NOT NULL,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
"""

_MIGRATION_V2 = """
CREATE TABLE IF NOT EXISTS profile_items (
    item_id TEXT PRIMARY KEY, key TEXT NOT NULL, value TEXT NOT NULL,
    source TEXT NOT NULL, sensitivity TEXT NOT NULL, confirmed INTEGER NOT NULL CHECK (confirmed=1),
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, expires_at TEXT
);
CREATE TABLE IF NOT EXISTS profile_tombstones (
    item_id TEXT PRIMARY KEY, deleted_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, session_id TEXT NOT NULL,
    event_type TEXT NOT NULL, at TEXT NOT NULL, route TEXT, task_status TEXT,
    error_class TEXT, detail TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_task ON audit_events(task_id, id);
CREATE TABLE IF NOT EXISTS task_sources (
    task_id TEXT NOT NULL, source TEXT NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY(task_id, source)
);
"""
_MIGRATION_V2_STATEMENTS = tuple(
    statement.strip() for statement in _MIGRATION_V2.split(";") if statement.strip()
)
_MIGRATION_V3 = """
CREATE TABLE IF NOT EXISTS task_operations (
    operation_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    request_id TEXT NOT NULL,
    capability_id TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    state TEXT NOT NULL,
    possible_duplicate INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(task_id, capability_id, request_digest)
);
CREATE INDEX IF NOT EXISTS idx_task_operations_task ON task_operations(task_id);
CREATE TABLE IF NOT EXISTS task_provenance (
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    kind TEXT NOT NULL,
    reference_id TEXT NOT NULL,
    recorded_at TEXT,
    PRIMARY KEY(task_id, kind, reference_id)
);
"""
_MIGRATION_V3_STATEMENTS = tuple(
    statement.strip() for statement in _MIGRATION_V3.split(";") if statement.strip()
)
_MIGRATION_V4 = """
ALTER TABLE sessions ADD COLUMN updated_at TEXT;
UPDATE sessions SET updated_at=created_at WHERE updated_at IS NULL;
ALTER TABLE sessions ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
CREATE TABLE IF NOT EXISTS task_results (
    task_id TEXT PRIMARY KEY REFERENCES tasks(task_id),
    task_status TEXT NOT NULL,
    outcome_code TEXT NOT NULL,
    epistemic_status TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    answer TEXT NOT NULL,
    answer_retained INTEGER NOT NULL DEFAULT 1,
    route TEXT NOT NULL,
    claims_json TEXT NOT NULL,
    citations_json TEXT NOT NULL,
    partial_work_json TEXT NOT NULL,
    failures_json TEXT NOT NULL,
    next_actions_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""
_MIGRATION_V4_STATEMENTS = tuple(
    statement.strip() for statement in _MIGRATION_V4.split(";") if statement.strip()
)
_MIGRATION_V5 = """
ALTER TABLE tasks ADD COLUMN route_category TEXT NOT NULL DEFAULT 'local_conversation';
ALTER TABLE tasks ADD COLUMN selected_capability_id TEXT;
ALTER TABLE tasks ADD COLUMN selected_operation TEXT NOT NULL DEFAULT '';
ALTER TABLE tasks ADD COLUMN selection_reason_code TEXT NOT NULL DEFAULT '';
ALTER TABLE tasks ADD COLUMN routing_contract_version TEXT NOT NULL DEFAULT 'v2-legacy';
ALTER TABLE task_results ADD COLUMN route_category TEXT NOT NULL DEFAULT 'local_conversation';
ALTER TABLE task_results ADD COLUMN selected_capability_id TEXT;
ALTER TABLE task_results ADD COLUMN selected_operation TEXT NOT NULL DEFAULT '';
ALTER TABLE task_results ADD COLUMN selection_reason_code TEXT NOT NULL DEFAULT '';
ALTER TABLE task_results ADD COLUMN routing_contract_version TEXT NOT NULL DEFAULT 'v2-legacy';
UPDATE task_results
SET route_category = CASE
    WHEN route = 'local_generalist' THEN 'local_conversation'
    ELSE 'registered_capability'
END,
selected_capability_id = CASE route
    WHEN 'web_research' THEN 'web_research'
    WHEN 'coding_specialist' THEN 'coding'
    WHEN 'research_specialist' THEN 'research'
    ELSE selected_capability_id
END,
selected_operation = CASE route
    WHEN 'web_research' THEN 'research.search'
    WHEN 'coding_specialist' THEN 'specialist.analyze'
    WHEN 'research_specialist' THEN 'specialist.analyze'
    ELSE selected_operation
END,
selection_reason_code = CASE
    WHEN route = 'local_generalist' THEN 'LOCAL_DEFAULT'
    ELSE 'LEGACY_ROUTE'
END
WHERE routing_contract_version = 'v2-legacy';
UPDATE tasks
SET route_category = COALESCE(
        (
            SELECT CASE
                WHEN audit.route = 'local_generalist' THEN 'local_conversation'
                ELSE 'registered_capability'
            END
            FROM audit_events AS audit
            WHERE audit.task_id = tasks.task_id AND audit.route IS NOT NULL
            ORDER BY audit.id DESC
            LIMIT 1
        ),
        route_category
    )
WHERE routing_contract_version = 'v2-legacy';
"""
_MIGRATION_V5_STATEMENTS = tuple(
    statement.strip() for statement in _MIGRATION_V5.split(";") if statement.strip()
)
_MIGRATION_V6 = """
ALTER TABLE tasks ADD COLUMN candidate_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE tasks ADD COLUMN rejected_candidate_reason_codes_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE tasks ADD COLUMN clarification_required INTEGER NOT NULL DEFAULT 0;
ALTER TABLE tasks ADD COLUMN freshness_affected_selection INTEGER NOT NULL DEFAULT 0;
ALTER TABLE task_results ADD COLUMN candidate_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE task_results ADD COLUMN rejected_candidate_reason_codes_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE task_results ADD COLUMN clarification_required INTEGER NOT NULL DEFAULT 0;
ALTER TABLE task_results ADD COLUMN freshness_affected_selection INTEGER NOT NULL DEFAULT 0;
"""
_MIGRATION_V6_STATEMENTS = tuple(
    statement.strip() for statement in _MIGRATION_V6.split(";") if statement.strip()
)
_MIGRATION_V7 = """
CREATE TABLE IF NOT EXISTS execution_plans (
    plan_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    revision INTEGER NOT NULL,
    parent_plan_id TEXT,
    catalog_version TEXT NOT NULL,
    finalization TEXT NOT NULL,
    status TEXT NOT NULL,
    max_plan_steps INTEGER NOT NULL,
    max_specialist_executions INTEGER NOT NULL,
    max_research_executions INTEGER NOT NULL,
    max_synthesis_executions INTEGER NOT NULL,
    max_provider_calls INTEGER NOT NULL,
    max_concurrency INTEGER NOT NULL,
    max_replanning_attempts INTEGER NOT NULL,
    max_parallel_steps INTEGER NOT NULL,
    max_step_timeout_seconds REAL NOT NULL,
    max_total_timeout_seconds REAL NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(task_id, revision)
);
CREATE INDEX IF NOT EXISTS idx_execution_plans_task
    ON execution_plans(task_id, revision, plan_id);
CREATE TABLE IF NOT EXISTS plan_steps (
    plan_id TEXT NOT NULL REFERENCES execution_plans(plan_id) ON DELETE CASCADE,
    step_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    kind TEXT NOT NULL,
    capability_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    objective TEXT NOT NULL,
    objective_class TEXT NOT NULL,
    perspective TEXT NOT NULL,
    inputs_json TEXT NOT NULL,
    output_type TEXT NOT NULL,
    criticality TEXT NOT NULL,
    verification INTEGER NOT NULL,
    timeout_seconds REAL NOT NULL,
    requires_external_access INTEGER NOT NULL,
    effect TEXT NOT NULL,
    requires_consent INTEGER NOT NULL,
    state TEXT NOT NULL,
    authorization_state TEXT NOT NULL,
    PRIMARY KEY(plan_id, step_id),
    UNIQUE(plan_id, position)
);
CREATE TABLE IF NOT EXISTS plan_dependencies (
    plan_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    dependency_step_id TEXT NOT NULL,
    PRIMARY KEY(plan_id, step_id, dependency_step_id),
    FOREIGN KEY(plan_id, step_id)
        REFERENCES plan_steps(plan_id, step_id) ON DELETE CASCADE,
    FOREIGN KEY(plan_id, dependency_step_id)
        REFERENCES plan_steps(plan_id, step_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_plan_dependencies_dependency
    ON plan_dependencies(plan_id, dependency_step_id);
CREATE TABLE IF NOT EXISTS step_results (
    plan_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    result_id TEXT NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT NOT NULL,
    retained INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(plan_id, step_id),
    UNIQUE(plan_id, result_id),
    FOREIGN KEY(plan_id, step_id)
        REFERENCES plan_steps(plan_id, step_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS step_claims (
    claim_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    claim_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(plan_id, step_id)
        REFERENCES plan_steps(plan_id, step_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS step_claim_supports (
    claim_id TEXT NOT NULL REFERENCES step_claims(claim_id) ON DELETE CASCADE,
    support_id TEXT NOT NULL,
    support_json TEXT NOT NULL,
    PRIMARY KEY(claim_id, support_id)
);
CREATE TABLE IF NOT EXISTS plan_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id TEXT NOT NULL REFERENCES execution_plans(plan_id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    detail TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_plan_events_plan ON plan_events(plan_id, event_id);
CREATE TABLE IF NOT EXISTS synthesis_results (
    plan_id TEXT PRIMARY KEY REFERENCES execution_plans(plan_id) ON DELETE CASCADE,
    strategy TEXT NOT NULL,
    validation_state TEXT NOT NULL,
    referenced_result_ids_json TEXT NOT NULL,
    output_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""
_MIGRATION_V7_STATEMENTS = tuple(
    statement.strip() for statement in _MIGRATION_V7.split(";") if statement.strip()
)
_PROFILE_TABLES = {
    "profile_items": """CREATE TABLE profile_items (
        item_id TEXT PRIMARY KEY, key TEXT NOT NULL, value TEXT NOT NULL,
        source TEXT NOT NULL, sensitivity TEXT NOT NULL, confirmed INTEGER NOT NULL CHECK (confirmed=1),
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, expires_at TEXT
    )""",
    "profile_tombstones": """CREATE TABLE profile_tombstones (
        item_id TEXT PRIMARY KEY, deleted_at TEXT NOT NULL
    )""",
}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse(dt: str) -> datetime:
    return datetime.fromisoformat(dt).astimezone(timezone.utc)


def _task_result_payload(
    result: TaskResult,
    *,
    answer: str,
    answer_retained: bool,
    claims: tuple[str, ...],
    partial_work: tuple[str, ...],
) -> dict[str, object]:
    """Encode the provider-neutral result contract for ``step_results``."""

    return {
        "task_id": result.task_id,
        "task_status": result.task_status.value,
        "outcome_code": result.outcome_code.value,
        "epistemic_status": result.epistemic_status.value,
        "validation_status": result.validation_status.value,
        "answer": answer,
        "answer_retained": answer_retained,
        "route_summary": result.route_summary.value,
        "claims": list(claims),
        "citations": list(result.citations),
        "partial_work": list(partial_work),
        "failures": list(result.failures),
        "next_actions": list(result.next_actions),
        "provenance": [
            {
                "kind": item.kind,
                "reference_id": item.reference_id,
                "recorded_at": item.recorded_at.isoformat()
                if item.recorded_at is not None
                else None,
            }
            for item in result.provenance
        ],
        "claim_supports": [
            {
                "claim_id": item.claim_id,
                "text": item.text,
                "support_status": item.support_status,
                "evidence_ids": list(item.evidence_ids),
                "note": item.note,
            }
            for item in result.claim_supports
        ],
        "route_category": result.route_category.value
        if result.route_category is not None
        else None,
        "capability_id": result.capability_id,
        "operation": result.operation,
        "selection_reason_code": result.selection_reason_code,
        "routing_contract_version": result.routing_contract_version,
        "candidate_count": result.candidate_count,
        "rejected_candidate_reason_codes": list(result.rejected_candidate_reason_codes),
        "clarification_required": result.clarification_required,
        "freshness_affected_selection": result.freshness_affected_selection,
    }


def _task_result_from_payload(payload: object) -> TaskResult:
    if not isinstance(payload, dict):
        raise ValueError("step result payload must be an object")
    provenance = tuple(
        ProvenanceReference(
            kind=item["kind"],
            reference_id=item["reference_id"],
            recorded_at=_parse(item["recorded_at"]) if item.get("recorded_at") else None,
        )
        for item in payload.get("provenance", [])
    )
    claim_supports = tuple(
        ClaimSupport(
            claim_id=item["claim_id"],
            text=item["text"],
            support_status=item["support_status"],
            evidence_ids=tuple(item.get("evidence_ids", [])),
            note=item.get("note", ""),
        )
        for item in payload.get("claim_supports", [])
    )
    return TaskResult(
        task_id=payload["task_id"],
        task_status=TaskStatus(payload["task_status"]),
        outcome_code=OutcomeCode(payload["outcome_code"]),
        epistemic_status=EpistemicStatus(payload["epistemic_status"]),
        validation_status=ValidationStatus(payload["validation_status"]),
        answer=payload.get("answer", ""),
        answer_retained=bool(payload.get("answer_retained", True)),
        route_summary=Route(payload["route_summary"]),
        claims=tuple(payload.get("claims", [])),
        citations=tuple(payload.get("citations", [])),
        partial_work=tuple(payload.get("partial_work", [])),
        failures=tuple(payload.get("failures", [])),
        next_actions=tuple(payload.get("next_actions", [])),
        provenance=provenance,
        claim_supports=claim_supports,
        route_category=(
            Route(payload["route_category"]) if payload.get("route_category") else None
        ),
        capability_id=payload.get("capability_id"),
        operation=payload.get("operation", ""),
        selection_reason_code=payload.get("selection_reason_code", ""),
        routing_contract_version=payload.get("routing_contract_version", ""),
        candidate_count=int(payload.get("candidate_count", 0)),
        rejected_candidate_reason_codes=tuple(payload.get("rejected_candidate_reason_codes", [])),
        clarification_required=bool(payload.get("clarification_required", False)),
        freshness_affected_selection=bool(payload.get("freshness_affected_selection", False)),
    )


class _SerializedConnection:
    """Serialize a shared SQLite connection across asynchronous task workers."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._lock = RLock()

    def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._connection.execute(sql, parameters)

    def executescript(self, sql_script: str) -> sqlite3.Cursor:
        with self._lock:
            return self._connection.executescript(sql_script)

    def commit(self) -> None:
        with self._lock:
            self._connection.commit()

    def rollback(self) -> None:
        with self._lock:
            self._connection.rollback()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> "_SerializedConnection":
        self._lock.acquire()
        self._connection.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        try:
            return self._connection.__exit__(exc_type, exc_value, traceback)
        finally:
            self._lock.release()


class SqliteSessionRepository:
    """SQLite-backed session/message repository (real, M1)."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        try:
            if db_path != ":memory:":
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(db_path, check_same_thread=False)
            self._conn = _SerializedConnection(connection)
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA foreign_keys=ON;")
        except sqlite3.Error as exc:  # pragma: no cover - construction failure is rare
            raise StorageFailureError(f"cannot open database: {type(exc).__name__}") from exc

    def apply_migrations(self) -> None:
        try:
            # V1 creates the original database when needed. V2 is executed one
            # statement at a time inside an explicit transaction: a failed step
            # rolls back and the schema_meta version is not advanced.
            self._conn.executescript(_MIGRATION_V1)
            row = self._conn.execute("SELECT version FROM schema_meta WHERE id=1").fetchone()
            current_version = int(row[0]) if row is not None else 1
            if current_version > _SCHEMA_VERSION:
                raise StorageFailureError(
                    "database schema is newer than this Elly version supports"
                )
            migrations = (
                (2, _MIGRATION_V2_STATEMENTS),
                (3, _MIGRATION_V3_STATEMENTS),
                (4, _MIGRATION_V4_STATEMENTS),
                (5, _MIGRATION_V5_STATEMENTS),
                (6, _MIGRATION_V6_STATEMENTS),
                (7, _MIGRATION_V7_STATEMENTS),
            )
            for version, statements in migrations:
                if current_version >= version:
                    continue
                self._conn.execute("BEGIN")
                try:
                    for statement in statements:
                        self._conn.execute(statement)
                    if row is None:
                        self._conn.execute(
                            "INSERT INTO schema_meta (id, version) VALUES (1, ?)", (version,)
                        )
                        row = (version,)
                    else:
                        self._conn.execute(
                            "UPDATE schema_meta SET version=? WHERE id=1", (version,)
                        )
                    self._conn.commit()
                    current_version = version
                except sqlite3.Error:
                    self._conn.rollback()
                    raise
        except sqlite3.Error as exc:
            raise StorageFailureError(f"migration failed: {type(exc).__name__}") from exc

    # ---- V3 validated plan persistence ----------------------------------

    def save_plan(self, plan: ExecutionPlan, *, at: datetime | None = None) -> None:
        """Insert one complete validated plan in a single SQLite transaction."""
        if not isinstance(plan, ExecutionPlan):
            raise StorageFailureError("plan persistence requires an ExecutionPlan")
        recorded_at = at or datetime.now(timezone.utc)
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO execution_plans ("
                    "plan_id,task_id,schema_version,revision,parent_plan_id,catalog_version,"
                    "finalization,status,max_plan_steps,max_specialist_executions,"
                    "max_research_executions,max_synthesis_executions,max_provider_calls,"
                    "max_concurrency,max_replanning_attempts,max_parallel_steps,"
                    "max_step_timeout_seconds,max_total_timeout_seconds,created_at,updated_at"
                    ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        plan.plan_id,
                        plan.task_id,
                        plan.schema_version,
                        plan.revision,
                        plan.parent_plan_id,
                        plan.catalog_version,
                        plan.finalization.value,
                        plan.status.value,
                        plan.limits.max_plan_steps,
                        plan.limits.max_specialist_executions,
                        plan.limits.max_research_executions,
                        plan.limits.max_synthesis_executions,
                        plan.limits.max_provider_calls,
                        plan.limits.max_concurrency,
                        plan.limits.max_replanning_attempts,
                        plan.limits.max_parallel_steps,
                        plan.limits.max_step_timeout_seconds,
                        plan.limits.max_total_timeout_seconds,
                        _iso(recorded_at),
                        _iso(recorded_at),
                    ),
                )
                for position, step in enumerate(plan.steps):
                    self._conn.execute(
                        "INSERT INTO plan_steps ("
                        "plan_id,step_id,position,kind,capability_id,operation_id,objective,"
                        "objective_class,perspective,inputs_json,output_type,criticality,"
                        "verification,timeout_seconds,requires_external_access,effect,"
                        "requires_consent,state,authorization_state"
                        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            plan.plan_id,
                            step.step_id,
                            position,
                            step.kind.value,
                            step.capability_id,
                            step.operation_id,
                            step.objective,
                            step.objective_class,
                            step.perspective,
                            json.dumps(
                                [
                                    {
                                        "name": item.name,
                                        "value_type": item.value_type,
                                        "source": item.source,
                                        "reference": item.reference,
                                        "required": item.required,
                                    }
                                    for item in step.inputs
                                ],
                                ensure_ascii=False,
                                separators=(",", ":"),
                                sort_keys=True,
                            ),
                            step.output_type,
                            step.criticality.value,
                            int(step.verification),
                            step.timeout_seconds,
                            int(step.requires_external_access),
                            step.effect.value,
                            int(step.requires_consent),
                            step.state.value,
                            step.authorization_state.value,
                        ),
                    )
                for step in plan.steps:
                    for dependency in step.dependencies:
                        self._conn.execute(
                            "INSERT INTO plan_dependencies(plan_id,step_id,dependency_step_id) "
                            "VALUES (?,?,?)",
                            (plan.plan_id, step.step_id, dependency),
                        )
                self._insert_plan_event(
                    plan.plan_id,
                    "plan.created",
                    "PLAN_VALIDATED",
                    (
                        f"revision={plan.revision} schema={plan.schema_version} "
                        f"catalog={plan.catalog_version} finalization={plan.finalization.value}"
                    ),
                    recorded_at,
                )
        except sqlite3.IntegrityError as exc:
            raise StorageFailureError("plan already exists or has conflicting graph rows") from exc
        except sqlite3.Error as exc:
            raise StorageFailureError(f"save plan failed: {type(exc).__name__}") from exc

    def persist_plan_atomic(self, plan: ExecutionPlan, *, at: datetime | None = None) -> None:
        """Explicit-name alias documenting the all-or-nothing persistence boundary."""
        self.save_plan(plan, at=at)

    def get_plan(self, plan_id: str) -> ExecutionPlan | None:
        try:
            row = self._conn.execute(
                "SELECT plan_id,task_id,schema_version,revision,parent_plan_id,catalog_version,"
                "finalization,status,max_plan_steps,max_specialist_executions,"
                "max_research_executions,max_synthesis_executions,max_provider_calls,"
                "max_concurrency,max_replanning_attempts,max_parallel_steps,"
                "max_step_timeout_seconds,max_total_timeout_seconds "
                "FROM execution_plans WHERE plan_id=?",
                (plan_id,),
            ).fetchone()
            if row is None:
                return None
            step_rows = self._conn.execute(
                "SELECT plan_id,step_id,kind,capability_id,operation_id,objective,"
                "objective_class,perspective,inputs_json,output_type,criticality,"
                "verification,timeout_seconds,requires_external_access,effect,"
                "requires_consent,state,authorization_state "
                "FROM plan_steps WHERE plan_id=? ORDER BY position",
                (plan_id,),
            ).fetchall()
            dependency_rows = self._conn.execute(
                "SELECT step_id,dependency_step_id FROM plan_dependencies "
                "WHERE plan_id=? ORDER BY step_id,dependency_step_id",
                (plan_id,),
            ).fetchall()
        except sqlite3.Error as exc:
            raise StorageFailureError(f"get plan failed: {type(exc).__name__}") from exc

        dependencies: dict[str, list[str]] = {}
        for step_id, dependency in dependency_rows:
            dependencies.setdefault(step_id, []).append(dependency)
        try:
            steps = tuple(
                PlanStep(
                    step_id=step_row[1],
                    kind=StepKind(step_row[2]),
                    capability_id=step_row[3],
                    operation_id=step_row[4],
                    objective=step_row[5],
                    objective_class=step_row[6],
                    perspective=step_row[7],
                    inputs=tuple(
                        InputBinding(
                            name=item["name"],
                            value_type=item["value_type"],
                            source=item.get("source", "request"),
                            reference=item.get("reference", ""),
                            required=bool(item.get("required", True)),
                        )
                        for item in json.loads(step_row[8])
                    ),
                    dependencies=tuple(dependencies.get(step_row[1], ())),
                    output_type=step_row[9],
                    criticality=StepCriticality(step_row[10]),
                    verification=bool(step_row[11]),
                    timeout_seconds=float(step_row[12]),
                    requires_external_access=bool(step_row[13]),
                    effect=ActionCategory(step_row[14]),
                    requires_consent=bool(step_row[15]),
                    state=StepState(step_row[16]),
                    authorization_state=AuthorizationState(step_row[17]),
                )
                for step_row in step_rows
            )
            limits = PlanLimitsSnapshot(
                max_plan_steps=int(row[8]),
                max_specialist_executions=int(row[9]),
                max_research_executions=int(row[10]),
                max_synthesis_executions=int(row[11]),
                max_provider_calls=int(row[12]),
                max_concurrency=int(row[13]),
                max_replanning_attempts=int(row[14]),
                max_parallel_steps=int(row[15]),
                max_step_timeout_seconds=float(row[16]),
                max_total_timeout_seconds=float(row[17]),
            )
            return ExecutionPlan(
                plan_id=row[0],
                task_id=row[1],
                schema_version=row[2],
                revision=int(row[3]),
                parent_plan_id=row[4],
                steps=steps,
                finalization=FinalizationStrategy(row[6]),
                limits=limits,
                catalog_version=row[5],
                status=PlanStatus(row[7]),
            )
        except (InputInvalidError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise StorageFailureError("stored execution plan is invalid") from exc

    def list_plans_for_task(self, task_id: str) -> tuple[ExecutionPlan, ...]:
        try:
            rows = self._conn.execute(
                "SELECT plan_id FROM execution_plans WHERE task_id=? ORDER BY revision,plan_id",
                (task_id,),
            ).fetchall()
        except sqlite3.Error as exc:
            raise StorageFailureError(f"list plans failed: {type(exc).__name__}") from exc
        plans: list[ExecutionPlan] = []
        for (plan_id,) in rows:
            plan = self.get_plan(plan_id)
            if plan is None:
                raise StorageFailureError("plan disappeared while listing revisions")
            plans.append(plan)
        return tuple(plans)

    def list_nonterminal_plans(self) -> tuple[ExecutionPlan, ...]:
        """Return plans that may have been left active by a process restart."""
        try:
            rows = self._conn.execute(
                "SELECT plan_id FROM execution_plans "
                "WHERE status IN (?,?) ORDER BY task_id,revision,plan_id",
                (PlanStatus.PENDING.value, PlanStatus.RUNNING.value),
            ).fetchall()
        except sqlite3.Error as exc:
            raise StorageFailureError(
                f"list nonterminal plans failed: {type(exc).__name__}"
            ) from exc
        plans: list[ExecutionPlan] = []
        for (plan_id,) in rows:
            plan = self.get_plan(plan_id)
            if plan is None:
                raise StorageFailureError("nonterminal plan disappeared while listing")
            plans.append(plan)
        return tuple(plans)

    def delete_plans_for_task(self, task_id: str) -> int:
        try:
            with self._conn:
                cursor = self._conn.execute(
                    "DELETE FROM execution_plans WHERE task_id=?", (task_id,)
                )
                return cursor.rowcount
        except sqlite3.Error as exc:
            raise StorageFailureError(f"delete plans failed: {type(exc).__name__}") from exc

    def transition_plan(
        self,
        plan_id: str,
        status: PlanStatus,
        *,
        expected_status: PlanStatus | None = None,
        reason_code: str = "",
        at: datetime | None = None,
    ) -> ExecutionPlan:
        """Compare-and-set a plan status and record the safe transition."""
        if not isinstance(status, PlanStatus):
            raise StorageFailureError("plan status transition is invalid")
        recorded_at = at or datetime.now(timezone.utc)
        try:
            with self._conn:
                row = self._conn.execute(
                    "SELECT status FROM execution_plans WHERE plan_id=?", (plan_id,)
                ).fetchone()
                if row is None:
                    raise StorageFailureError("plan not found")
                current = PlanStatus(row[0])
                if expected_status is not None and current is not expected_status:
                    raise ConflictError("plan status changed before transition")
                ensure_plan_transition(current, status)
                self._conn.execute(
                    "UPDATE execution_plans SET status=?,updated_at=? WHERE plan_id=?",
                    (status.value, _iso(recorded_at), plan_id),
                )
                self._insert_plan_event(
                    plan_id,
                    "plan.transition",
                    reason_code or status.value.upper(),
                    f"status={status.value}",
                    recorded_at,
                )
        except (ConflictError, StorageFailureError):
            raise
        except (sqlite3.Error, ValueError) as exc:
            raise StorageFailureError(f"plan transition failed: {type(exc).__name__}") from exc
        updated = self.get_plan(plan_id)
        if updated is None:  # pragma: no cover - guarded by the transaction above
            raise StorageFailureError("plan disappeared after transition")
        return updated

    def transition_step(
        self,
        plan_id: str,
        step_id: str,
        state: StepState,
        *,
        expected_state: StepState | None = None,
        authorization_state: AuthorizationState | None = None,
        reason_code: str = "",
        at: datetime | None = None,
    ) -> ExecutionPlan:
        """Compare-and-set one step state in the same transaction as its event."""
        if not isinstance(state, StepState):
            raise StorageFailureError("plan step state transition is invalid")
        if authorization_state is not None and not isinstance(
            authorization_state, AuthorizationState
        ):
            raise StorageFailureError("plan step authorization state is invalid")
        recorded_at = at or datetime.now(timezone.utc)
        try:
            with self._conn:
                row = self._conn.execute(
                    "SELECT state,authorization_state FROM plan_steps "
                    "WHERE plan_id=? AND step_id=?",
                    (plan_id, step_id),
                ).fetchone()
                if row is None:
                    raise StorageFailureError("plan step not found")
                current = StepState(row[0])
                if expected_state is not None and current is not expected_state:
                    raise ConflictError("plan step state changed before transition")
                ensure_step_transition(current, state)
                auth_value = (
                    authorization_state.value if authorization_state is not None else row[1]
                )
                self._conn.execute(
                    "UPDATE plan_steps SET state=?,authorization_state=? "
                    "WHERE plan_id=? AND step_id=?",
                    (state.value, auth_value, plan_id, step_id),
                )
                self._conn.execute(
                    "UPDATE execution_plans SET updated_at=? WHERE plan_id=?",
                    (_iso(recorded_at), plan_id),
                )
                self._insert_plan_event(
                    plan_id,
                    "step.transition",
                    reason_code or state.value.upper(),
                    f"step={step_id} state={state.value}",
                    recorded_at,
                )
        except (ConflictError, StorageFailureError):
            raise
        except (sqlite3.Error, ValueError) as exc:
            raise StorageFailureError(f"step transition failed: {type(exc).__name__}") from exc
        updated = self.get_plan(plan_id)
        if updated is None:  # pragma: no cover - guarded by the transaction above
            raise StorageFailureError("plan disappeared after step transition")
        return updated

    def reconcile_plan(
        self,
        plan_id: str,
        status: PlanStatus,
        *,
        expected_status: PlanStatus | None = None,
        reason_code: str = "",
        at: datetime | None = None,
    ) -> ExecutionPlan:
        """Reset a pending/running plan during startup reconciliation.

        Normal lifecycle transitions intentionally do not permit RUNNING back
        to PENDING. Recovery is a separate, explicit operation so a restart
        cannot accidentally become a general-purpose status mutation.
        """
        if status not in {PlanStatus.PENDING, PlanStatus.INTERRUPTED}:
            raise StorageFailureError("recovery plan status is invalid")
        recorded_at = at or datetime.now(timezone.utc)
        try:
            with self._conn:
                row = self._conn.execute(
                    "SELECT status FROM execution_plans WHERE plan_id=?", (plan_id,)
                ).fetchone()
                if row is None:
                    raise StorageFailureError("plan not found")
                current = PlanStatus(row[0])
                if expected_status is not None and current is not expected_status:
                    raise ConflictError("plan status changed before recovery")
                if current not in {PlanStatus.PENDING, PlanStatus.RUNNING}:
                    raise ConflictError("plan is no longer recoverable")
                self._conn.execute(
                    "UPDATE execution_plans SET status=?,updated_at=? WHERE plan_id=?",
                    (status.value, _iso(recorded_at), plan_id),
                )
                self._insert_plan_event(
                    plan_id,
                    "recovery.plan",
                    reason_code or "PLAN_RECOVERED",
                    f"from={current.value} status={status.value}",
                    recorded_at,
                )
        except (ConflictError, StorageFailureError):
            raise
        except (sqlite3.Error, ValueError) as exc:
            raise StorageFailureError(f"plan recovery failed: {type(exc).__name__}") from exc
        updated = self.get_plan(plan_id)
        if updated is None:  # pragma: no cover - guarded by the transaction above
            raise StorageFailureError("plan disappeared after recovery")
        return updated

    def reconcile_step(
        self,
        plan_id: str,
        step_id: str,
        state: StepState,
        *,
        expected_state: StepState | None = None,
        reason_code: str = "",
        at: datetime | None = None,
    ) -> ExecutionPlan:
        """Reset a crash-interrupted step without invoking a provider."""
        if state not in {StepState.PENDING, StepState.INTERRUPTED}:
            raise StorageFailureError("recovery step state is invalid")
        recorded_at = at or datetime.now(timezone.utc)
        try:
            with self._conn:
                row = self._conn.execute(
                    "SELECT state FROM plan_steps WHERE plan_id=? AND step_id=?",
                    (plan_id, step_id),
                ).fetchone()
                if row is None:
                    raise StorageFailureError("plan step not found")
                current = StepState(row[0])
                if expected_state is not None and current is not expected_state:
                    raise ConflictError("plan step state changed before recovery")
                if current not in {
                    StepState.AUTHORIZING,
                    StepState.RUNNING,
                    StepState.INTERRUPTED,
                }:
                    raise ConflictError("plan step is no longer recoverable")
                self._conn.execute(
                    "UPDATE plan_steps SET state=? WHERE plan_id=? AND step_id=?",
                    (state.value, plan_id, step_id),
                )
                self._conn.execute(
                    "UPDATE execution_plans SET updated_at=? WHERE plan_id=?",
                    (_iso(recorded_at), plan_id),
                )
                self._insert_plan_event(
                    plan_id,
                    "recovery.step",
                    reason_code or "STEP_RECOVERED",
                    f"step={step_id} from={current.value} state={state.value}",
                    recorded_at,
                )
        except (ConflictError, StorageFailureError):
            raise
        except (sqlite3.Error, ValueError) as exc:
            raise StorageFailureError(f"step recovery failed: {type(exc).__name__}") from exc
        updated = self.get_plan(plan_id)
        if updated is None:  # pragma: no cover - guarded by the transaction above
            raise StorageFailureError("plan disappeared after step recovery")
        return updated

    def save_step_result(
        self,
        plan_id: str,
        step_id: str,
        result: TaskResult,
        *,
        retained: bool = True,
        at: datetime | None = None,
    ) -> None:
        """Persist a normalized result without making it a task-level result."""
        if not isinstance(result, TaskResult):
            raise StorageFailureError("step result must be a TaskResult")
        if not isinstance(retained, bool):
            raise StorageFailureError("step result retained flag is invalid")
        recorded_at = at or datetime.now(timezone.utc)
        try:
            plan_row = self._conn.execute(
                "SELECT task_id FROM execution_plans WHERE plan_id=?", (plan_id,)
            ).fetchone()
            if plan_row is None:
                raise StorageFailureError("plan not found")
            if result.task_id != plan_row[0]:
                raise StorageFailureError("step result task identity does not match plan")
            step_row = self._conn.execute(
                "SELECT 1 FROM plan_steps WHERE plan_id=? AND step_id=?",
                (plan_id, step_id),
            ).fetchone()
            if step_row is None:
                raise StorageFailureError("plan step not found")
            session_row = self._conn.execute(
                "SELECT persistence_mode FROM sessions WHERE session_id=("
                "SELECT session_id FROM tasks WHERE task_id=?)",
                (result.task_id,),
            ).fetchone()
            session_retains = (
                session_row is None or session_row[0] == PersistenceMode.STORE_WITH_RETENTION.value
            )
            answer_retained = bool(retained and result.answer_retained and session_retains)
            payload = _task_result_payload(
                result,
                answer=result.answer if answer_retained else "",
                answer_retained=answer_retained,
                claims=result.claims if answer_retained else (),
                partial_work=result.partial_work if answer_retained else (),
            )
            result_id = f"result-{step_id}"
            with self._conn:
                self._conn.execute(
                    "INSERT OR REPLACE INTO step_results "
                    "(plan_id,step_id,result_id,status,result_json,retained,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (
                        plan_id,
                        step_id,
                        result_id,
                        result.task_status.value,
                        json.dumps(
                            payload,
                            ensure_ascii=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                        int(answer_retained),
                        _iso(recorded_at),
                        _iso(recorded_at),
                    ),
                )
                self._insert_plan_event(
                    plan_id,
                    "step.result",
                    "STEP_RESULT_RETAINED" if answer_retained else "STEP_RESULT_METADATA_ONLY",
                    f"step={step_id} result_id={result_id} status={result.task_status.value}",
                    recorded_at,
                )
        except StorageFailureError:
            raise
        except (sqlite3.Error, TypeError, ValueError) as exc:
            raise StorageFailureError(f"save step result failed: {type(exc).__name__}") from exc

    def get_step_result(self, plan_id: str, step_id: str) -> TaskResult | None:
        try:
            row = self._conn.execute(
                "SELECT result_json FROM step_results WHERE plan_id=? AND step_id=?",
                (plan_id, step_id),
            ).fetchone()
        except sqlite3.Error as exc:
            raise StorageFailureError(f"get step result failed: {type(exc).__name__}") from exc
        if row is None:
            return None
        try:
            payload = json.loads(row[0])
            if isinstance(payload, dict) and "schema_version" in payload:
                return StepResultEnvelope.from_dict(payload).to_task_result()
            return _task_result_from_payload(payload)
        except (TypeError, ValueError, KeyError, json.JSONDecodeError, MalformedResultError) as exc:
            raise StorageFailureError("stored step result is invalid") from exc

    def save_step_envelope(
        self,
        plan_id: str,
        step_id: str,
        envelope: StepResultEnvelope,
        *,
        retained: bool = True,
        at: datetime | None = None,
    ) -> None:
        """Persist a versioned result without creating a task-level completion."""
        if not isinstance(envelope, StepResultEnvelope):
            raise StorageFailureError("step result envelope has an invalid type")
        if not isinstance(retained, bool):
            raise StorageFailureError("step result retained flag is invalid")
        recorded_at = at or datetime.now(timezone.utc)
        try:
            plan_row = self._conn.execute(
                "SELECT task_id FROM execution_plans WHERE plan_id=?", (plan_id,)
            ).fetchone()
            if plan_row is None:
                raise StorageFailureError("plan not found")
            if envelope.plan_id != plan_id or envelope.task_id != plan_row[0]:
                raise StorageFailureError("step result envelope identity does not match plan")
            step_row = self._conn.execute(
                "SELECT 1 FROM plan_steps WHERE plan_id=? AND step_id=?",
                (plan_id, step_id),
            ).fetchone()
            if step_row is None or envelope.step_id != step_id:
                raise StorageFailureError("plan step not found")
            session_row = self._conn.execute(
                "SELECT persistence_mode FROM sessions WHERE session_id=("
                "SELECT session_id FROM tasks WHERE task_id=?)",
                (envelope.task_id,),
            ).fetchone()
            session_retains = (
                session_row is None or session_row[0] == PersistenceMode.STORE_WITH_RETENTION.value
            )
            answer_retained = bool(retained and envelope.answer_retained and session_retains)
            persisted = envelope
            if not answer_retained:
                persisted = replace(
                    envelope,
                    summary="",
                    answer="",
                    findings=(),
                    claims=(),
                    claim_supports=(),
                    assumptions=(),
                    uncertainties=(),
                    warnings=(),
                    structured_output={},
                    answer_retained=False,
                )
            payload = persisted.to_dict()
            with self._conn:
                self._conn.execute(
                    "INSERT OR REPLACE INTO step_results "
                    "(plan_id,step_id,result_id,status,result_json,retained,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (
                        plan_id,
                        step_id,
                        f"result-{step_id}",
                        persisted.status.value,
                        json.dumps(
                            payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                        ),
                        int(answer_retained),
                        _iso(recorded_at),
                        _iso(recorded_at),
                    ),
                )
                self._insert_plan_event(
                    plan_id,
                    "step.result",
                    "STEP_RESULT_RETAINED" if answer_retained else "STEP_RESULT_METADATA_ONLY",
                    f"step={step_id} result_id=result-{step_id} status={persisted.status.value}",
                    recorded_at,
                )
        except StorageFailureError:
            raise
        except (sqlite3.Error, TypeError, ValueError, MalformedResultError) as exc:
            raise StorageFailureError(
                f"save step result envelope failed: {type(exc).__name__}"
            ) from exc

    def get_step_envelope(self, plan_id: str, step_id: str) -> StepResultEnvelope | None:
        try:
            row = self._conn.execute(
                "SELECT result_json FROM step_results WHERE plan_id=? AND step_id=?",
                (plan_id, step_id),
            ).fetchone()
        except sqlite3.Error as exc:
            raise StorageFailureError(
                f"get step result envelope failed: {type(exc).__name__}"
            ) from exc
        if row is None:
            return None
        try:
            payload = json.loads(row[0])
            if not isinstance(payload, dict) or "schema_version" not in payload:
                return None
            return StepResultEnvelope.from_dict(payload)
        except (TypeError, ValueError, KeyError, json.JSONDecodeError, MalformedResultError) as exc:
            raise StorageFailureError("stored step result envelope is invalid") from exc

    def append_plan_event(
        self,
        plan_id: str,
        event_type: str,
        reason_code: str,
        detail: str = "",
        *,
        at: datetime | None = None,
    ) -> None:
        recorded_at = at or datetime.now(timezone.utc)
        try:
            with self._conn:
                self._insert_plan_event(plan_id, event_type, reason_code, detail, recorded_at)
        except sqlite3.Error as exc:
            raise StorageFailureError(f"append plan event failed: {type(exc).__name__}") from exc

    def _insert_plan_event(
        self,
        plan_id: str,
        event_type: str,
        reason_code: str,
        detail: str,
        at: datetime,
    ) -> None:
        if (
            not isinstance(event_type, str)
            or not isinstance(reason_code, str)
            or _SAFE_EVENT_CODE.fullmatch(event_type) is None
            or _SAFE_EVENT_CODE.fullmatch(reason_code) is None
        ):
            raise StorageFailureError("plan event codes are invalid")
        safe_detail = redact_trace_detail(detail)
        if len(safe_detail) > 256 or "\n" in safe_detail or "\r" in safe_detail:
            raise StorageFailureError("plan event detail exceeds its safe bound")
        self._conn.execute(
            "INSERT INTO plan_events(plan_id,event_type,reason_code,detail,created_at) "
            "VALUES (?,?,?,?,?)",
            (plan_id, event_type, reason_code, safe_detail, _iso(at)),
        )

    def plan_events(self, plan_id: str) -> tuple[PlanEvent, ...]:
        try:
            rows = self._conn.execute(
                "SELECT plan_id,event_type,reason_code,detail,created_at "
                "FROM plan_events WHERE plan_id=? ORDER BY event_id",
                (plan_id,),
            ).fetchall()
            return tuple(
                PlanEvent(
                    plan_id=row[0],
                    event_type=row[1],
                    reason_code=row[2],
                    detail=row[3],
                    created_at=_parse(row[4]),
                )
                for row in rows
            )
        except sqlite3.Error as exc:
            raise StorageFailureError(f"query plan events failed: {type(exc).__name__}") from exc

    def save_synthesis_result(
        self,
        plan_id: str,
        strategy: FinalizationStrategy,
        validation_state: str,
        referenced_result_ids: tuple[str, ...],
        output: Mapping[str, object],
        *,
        at: datetime | None = None,
    ) -> None:
        recorded_at = at or datetime.now(timezone.utc)
        if not isinstance(strategy, FinalizationStrategy):
            raise StorageFailureError("synthesis strategy is invalid")
        if (
            not isinstance(validation_state, str)
            or not validation_state.strip()
            or len(validation_state) > 128
            or "\n" in validation_state
            or "\r" in validation_state
        ):
            raise StorageFailureError("synthesis validation state is invalid")
        if not isinstance(referenced_result_ids, tuple) or any(
            not isinstance(item, str) or not item.strip() for item in referenced_result_ids
        ):
            raise StorageFailureError("synthesis result references are invalid")
        if not isinstance(output, Mapping):
            raise StorageFailureError("synthesis output is invalid")
        try:
            output_json = json.dumps(
                dict(output),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
                allow_nan=False,
            )
            if len(output_json.encode("utf-8")) > 32_768:
                raise StorageFailureError("synthesis output exceeds its size limit")
            validation_event_code = re.sub(r"[^A-Za-z0-9_.-]", "_", validation_state.strip())[:64]
            if not validation_event_code or not validation_event_code[0].isalpha():
                validation_event_code = "SYNTHESIS_" + validation_event_code[:54]
            with self._conn:
                self._conn.execute(
                    "INSERT INTO synthesis_results "
                    "(plan_id,strategy,validation_state,referenced_result_ids_json,output_json,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?,?) "
                    "ON CONFLICT(plan_id) DO UPDATE SET strategy=excluded.strategy, "
                    "validation_state=excluded.validation_state, "
                    "referenced_result_ids_json=excluded.referenced_result_ids_json, "
                    "output_json=excluded.output_json, updated_at=excluded.updated_at",
                    (
                        plan_id,
                        strategy.value,
                        validation_state.strip(),
                        json.dumps(list(referenced_result_ids), separators=(",", ":")),
                        output_json,
                        _iso(recorded_at),
                        _iso(recorded_at),
                    ),
                )
                self._insert_plan_event(
                    plan_id,
                    (
                        "response_composer.result"
                        if validation_state.startswith("response_composition:")
                        else "synthesis.result"
                    ),
                    validation_event_code,
                    (
                        f"strategy={strategy.value} refs={len(referenced_result_ids)} "
                        f"result_id=synthesis-{plan_id}"
                    ),
                    recorded_at,
                )
        except StorageFailureError:
            raise
        except (sqlite3.Error, TypeError, ValueError) as exc:
            raise StorageFailureError(
                f"save synthesis result failed: {type(exc).__name__}"
            ) from exc

    def get_synthesis_result(self, plan_id: str) -> SynthesisResultRecord | None:
        try:
            row = self._conn.execute(
                "SELECT plan_id,strategy,validation_state,referenced_result_ids_json,"
                "output_json,created_at,updated_at FROM synthesis_results WHERE plan_id=?",
                (plan_id,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise StorageFailureError(f"get synthesis result failed: {type(exc).__name__}") from exc
        if row is None:
            return None
        try:
            references = json.loads(row[3])
            output = json.loads(row[4])
            if not isinstance(references, list) or not isinstance(output, dict):
                raise ValueError
            return SynthesisResultRecord(
                plan_id=row[0],
                strategy=FinalizationStrategy(row[1]),
                validation_state=row[2],
                referenced_result_ids=tuple(references),
                output=output,
                created_at=_parse(row[5]),
                updated_at=_parse(row[6]),
            )
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise StorageFailureError("stored synthesis result is invalid") from exc

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
                    self._insert_audit_event(audit_event)
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

    def add_profile_item(self, item: ProfileItem) -> None:
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO profile_items(item_id,key,value,source,sensitivity,confirmed,created_at,updated_at,expires_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        item.item_id,
                        item.key,
                        item.value,
                        item.source,
                        item.sensitivity,
                        1,
                        _iso(item.created_at),
                        _iso(item.updated_at),
                        _iso(item.expires_at) if item.expires_at else None,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise StorageFailureError("profile item already exists") from exc
        except sqlite3.Error as exc:
            raise StorageFailureError(f"add profile failed: {type(exc).__name__}") from exc

    def list_profile_items(self) -> list[ProfileItem]:
        try:
            rows = self._conn.execute(
                "SELECT item_id,key,value,source,sensitivity,confirmed,created_at,updated_at,expires_at FROM profile_items ORDER BY key,item_id"
            ).fetchall()
            return [
                ProfileItem(
                    r[0],
                    r[1],
                    r[2],
                    r[3],
                    r[4],
                    bool(r[5]),
                    _parse(r[6]),
                    _parse(r[7]),
                    _parse(r[8]) if r[8] else None,
                )
                for r in rows
            ]
        except sqlite3.Error as exc:
            raise StorageFailureError(f"list profile failed: {type(exc).__name__}") from exc

    def get_profile_item(self, item_id: str) -> ProfileItem | None:
        return next((item for item in self.list_profile_items() if item.item_id == item_id), None)

    def update_profile_item(self, item: ProfileItem) -> None:
        try:
            with self._conn:
                cursor = self._conn.execute(
                    "UPDATE profile_items SET key=?,value=?,sensitivity=?,updated_at=?,expires_at=? WHERE item_id=?",
                    (
                        item.key,
                        item.value,
                        item.sensitivity,
                        _iso(item.updated_at),
                        _iso(item.expires_at) if item.expires_at else None,
                        item.item_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise StorageFailureError("profile item not found")
        except sqlite3.Error as exc:
            raise StorageFailureError(f"update profile failed: {type(exc).__name__}") from exc

    def delete_profile_item(self, item_id: str, at: datetime) -> bool:
        try:
            with self._conn:
                cursor = self._conn.execute("DELETE FROM profile_items WHERE item_id=?", (item_id,))
                if cursor.rowcount:
                    self._conn.execute(
                        "INSERT OR REPLACE INTO profile_tombstones(item_id,deleted_at) VALUES (?,?)",
                        (item_id, _iso(at)),
                    )
                    return True
                return False
        except sqlite3.Error as exc:
            raise StorageFailureError(f"delete profile failed: {type(exc).__name__}") from exc

    def purge_expired_profile(self, now: datetime) -> int:
        try:
            with self._conn:
                cursor = self._conn.execute(
                    "DELETE FROM profile_items WHERE expires_at IS NOT NULL AND expires_at <= ?",
                    (_iso(now),),
                )
                return cursor.rowcount
        except sqlite3.Error as exc:
            raise StorageFailureError(f"purge profile failed: {type(exc).__name__}") from exc

    def quarantine_profile_store(self, at: datetime) -> str:
        """Move corrupt profile tables aside and recreate empty profile tables.

        Only profile tables are isolated; sessions, tasks, audit records, and
        versioned behavior remain available. The quarantine name contains only
        UTC digits, so it is safe to interpolate as an SQLite identifier.
        """
        suffix = at.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        try:
            with self._conn:
                for name, create_sql in _PROFILE_TABLES.items():
                    exists = self._conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
                    ).fetchone()
                    if exists:
                        quarantine = f"{name}_quarantine_{suffix}"
                        self._conn.execute(f'ALTER TABLE "{name}" RENAME TO "{quarantine}"')
                    self._conn.execute(create_sql)
            return suffix
        except sqlite3.Error as exc:
            raise StorageFailureError(f"profile quarantine failed: {type(exc).__name__}") from exc

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
            from ..domain.enums import ErrorClass, Route, TaskStatus

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

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:  # pragma: no cover
            pass
