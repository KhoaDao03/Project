"""SQLite schema version 7 and transactional migration authority."""

from __future__ import annotations

import re
import sqlite3

from elly.domain.errors import StorageFailureError

from .connection import _SerializedConnection

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



def apply_migrations(
    connection: _SerializedConnection,
    *,
    migration_v1: str = _MIGRATION_V1,
    migrations: tuple[tuple[int, tuple[str, ...]], ...] | None = None,
) -> None:
    """Apply V1–V7 using the repository-owned connection and transactions."""

    try:
        # V1 creates the original database when needed. Later versions are
        # executed one statement at a time inside an explicit transaction so
        # schema_meta never advances after a failed migration.
        connection.executescript(migration_v1)
        row = connection.execute("SELECT version FROM schema_meta WHERE id=1").fetchone()
        current_version = int(row[0]) if row is not None else 1
        if current_version > _SCHEMA_VERSION:
            raise StorageFailureError(
                "database schema is newer than this Elly version supports"
            )
        migration_sequence = migrations or (
            (2, _MIGRATION_V2_STATEMENTS),
            (3, _MIGRATION_V3_STATEMENTS),
            (4, _MIGRATION_V4_STATEMENTS),
            (5, _MIGRATION_V5_STATEMENTS),
            (6, _MIGRATION_V6_STATEMENTS),
            (7, _MIGRATION_V7_STATEMENTS),
        )
        for version, statements in migration_sequence:
            if current_version >= version:
                continue
            connection.execute("BEGIN")
            try:
                for statement in statements:
                    connection.execute(statement)
                if row is None:
                    connection.execute(
                        "INSERT INTO schema_meta (id, version) VALUES (1, ?)", (version,)
                    )
                    row = (version,)
                else:
                    connection.execute(
                        "UPDATE schema_meta SET version=? WHERE id=1", (version,)
                    )
                connection.commit()
                current_version = version
            except sqlite3.Error:
                connection.rollback()
                raise
    except sqlite3.Error as exc:
        raise StorageFailureError(f"migration failed: {type(exc).__name__}") from exc
