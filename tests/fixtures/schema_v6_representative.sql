PRAGMA foreign_keys=ON;

CREATE TABLE schema_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL
);
INSERT INTO schema_meta(id, version) VALUES (1, 6);

CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    persistence_mode TEXT NOT NULL,
    cloud_mode TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    stored_body INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_messages_session ON messages(session_id, id);

CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    route_category TEXT NOT NULL DEFAULT 'local_conversation',
    selected_capability_id TEXT,
    selected_operation TEXT NOT NULL DEFAULT '',
    selection_reason_code TEXT NOT NULL DEFAULT '',
    routing_contract_version TEXT NOT NULL DEFAULT 'v2-legacy',
    candidate_count INTEGER NOT NULL DEFAULT 0,
    rejected_candidate_reason_codes_json TEXT NOT NULL DEFAULT '[]',
    clarification_required INTEGER NOT NULL DEFAULT 0,
    freshness_affected_selection INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_tasks_status ON tasks(status);

CREATE TABLE profile_items (
    item_id TEXT PRIMARY KEY,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    source TEXT NOT NULL,
    sensitivity TEXT NOT NULL,
    confirmed INTEGER NOT NULL CHECK (confirmed = 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT
);
CREATE TABLE profile_tombstones (
    item_id TEXT PRIMARY KEY,
    deleted_at TEXT NOT NULL
);

CREATE TABLE audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    at TEXT NOT NULL,
    route TEXT,
    task_status TEXT,
    error_class TEXT,
    detail TEXT NOT NULL
);
CREATE INDEX idx_audit_task ON audit_events(task_id, id);

CREATE TABLE task_sources (
    task_id TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(task_id, source)
);

CREATE TABLE task_operations (
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
CREATE INDEX idx_task_operations_task ON task_operations(task_id);

CREATE TABLE task_provenance (
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    kind TEXT NOT NULL,
    reference_id TEXT NOT NULL,
    recorded_at TEXT,
    PRIMARY KEY(task_id, kind, reference_id)
);

CREATE TABLE task_results (
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
    updated_at TEXT NOT NULL,
    route_category TEXT NOT NULL DEFAULT 'local_conversation',
    selected_capability_id TEXT,
    selected_operation TEXT NOT NULL DEFAULT '',
    selection_reason_code TEXT NOT NULL DEFAULT '',
    routing_contract_version TEXT NOT NULL DEFAULT 'v2-legacy',
    candidate_count INTEGER NOT NULL DEFAULT 0,
    rejected_candidate_reason_codes_json TEXT NOT NULL DEFAULT '[]',
    clarification_required INTEGER NOT NULL DEFAULT 0,
    freshness_affected_selection INTEGER NOT NULL DEFAULT 0
);

INSERT INTO sessions(
    session_id, persistence_mode, cloud_mode, created_at, updated_at, version
) VALUES (
    'v6-fixture-session', 'store_with_retention', 'local_only',
    '2026-08-15T12:00:00+00:00', '2026-08-15T12:00:00+00:00', 1
);

INSERT INTO messages(session_id, role, content, stored_body, created_at) VALUES
    ('v6-fixture-session', 'user', 'Review the stored fixture', 1,
     '2026-08-15T12:00:01+00:00'),
    ('v6-fixture-session', 'assistant', 'Fixture review completed', 1,
     '2026-08-15T12:00:02+00:00');

INSERT INTO tasks(
    task_id, session_id, status, started_at, updated_at, route_category,
    selected_capability_id, selected_operation, selection_reason_code,
    routing_contract_version, candidate_count,
    rejected_candidate_reason_codes_json, clarification_required,
    freshness_affected_selection
) VALUES (
    'v6-fixture-task', 'v6-fixture-session', 'completed',
    '2026-08-15T12:00:01+00:00', '2026-08-15T12:00:02+00:00',
    'registered_capability', 'security_review', 'security.inspect',
    'CATALOG_SINGLE_MATCH', 'v2.5-routing-v1', 1, '[]', 0, 0
);

INSERT INTO task_results(
    task_id, task_status, outcome_code, epistemic_status, validation_status,
    answer, answer_retained, route, claims_json, citations_json,
    partial_work_json, failures_json, next_actions_json, updated_at,
    route_category, selected_capability_id, selected_operation,
    selection_reason_code, routing_contract_version, candidate_count,
    rejected_candidate_reason_codes_json, clarification_required,
    freshness_affected_selection
) VALUES (
    'v6-fixture-task', 'completed', 'success', 'known', 'validated',
    'Stored fixture review completed', 1, 'registered_capability',
    '["fixture claim"]', '[]', '[]', '[]', '[]',
    '2026-08-15T12:00:02+00:00', 'registered_capability',
    'security_review', 'security.inspect', 'CATALOG_SINGLE_MATCH',
    'v2.5-routing-v1', 1, '[]', 0, 0
);

INSERT INTO audit_events(
    task_id, session_id, event_type, at, route, task_status, error_class, detail
) VALUES (
    'v6-fixture-task', 'v6-fixture-session', 'task.completed',
    '2026-08-15T12:00:02+00:00', 'registered_capability', 'completed', NULL,
    'capability=security_review operation=security.inspect'
);

INSERT INTO task_provenance(task_id, kind, reference_id, recorded_at) VALUES
    ('v6-fixture-task', 'capability', 'security_review',
     '2026-08-15T12:00:02+00:00');
