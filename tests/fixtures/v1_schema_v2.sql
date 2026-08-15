-- Sanitized representative Elly V1 schema-version-2 database dump.
PRAGMA foreign_keys=ON;

CREATE TABLE schema_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1), version INTEGER NOT NULL
);
INSERT INTO schema_meta(id, version) VALUES (1, 2);

CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY, persistence_mode TEXT NOT NULL,
    cloud_mode TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    role TEXT NOT NULL, content TEXT NOT NULL, stored_body INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_messages_session ON messages(session_id, id);
CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(session_id),
    status TEXT NOT NULL, started_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX idx_tasks_status ON tasks(status);

CREATE TABLE profile_items (
    item_id TEXT PRIMARY KEY, key TEXT NOT NULL, value TEXT NOT NULL,
    source TEXT NOT NULL, sensitivity TEXT NOT NULL,
    confirmed INTEGER NOT NULL CHECK (confirmed=1),
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, expires_at TEXT
);
CREATE TABLE profile_tombstones (
    item_id TEXT PRIMARY KEY, deleted_at TEXT NOT NULL
);
CREATE TABLE audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
    session_id TEXT NOT NULL, event_type TEXT NOT NULL, at TEXT NOT NULL,
    route TEXT, task_status TEXT, error_class TEXT, detail TEXT NOT NULL
);
CREATE INDEX idx_audit_task ON audit_events(task_id, id);
CREATE TABLE task_sources (
    task_id TEXT NOT NULL, source TEXT NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY(task_id, source)
);

INSERT INTO sessions VALUES (
    'legacy-session', 'store_with_retention', 'local_only',
    '2026-08-03T12:00:00+00:00'
);
INSERT INTO messages(session_id,role,content,stored_body,created_at) VALUES
    ('legacy-session','user','legacy question',1,'2026-08-03T12:00:00+00:00'),
    ('legacy-session','assistant','legacy answer',1,'2026-08-03T12:00:01+00:00');
INSERT INTO tasks VALUES (
    'legacy-task','legacy-session','completed',
    '2026-08-03T12:00:00+00:00','2026-08-03T12:00:01+00:00'
);
INSERT INTO profile_items VALUES (
    'profile-legacy','preferred_name','Owner','owner_confirmed','local',1,
    '2026-08-03T12:00:00+00:00','2026-08-03T12:00:00+00:00',NULL
);
INSERT INTO profile_tombstones VALUES (
    'profile-deleted','2026-08-03T12:00:00+00:00'
);
INSERT INTO audit_events(
    task_id,session_id,event_type,at,route,task_status,error_class,detail
) VALUES (
    'legacy-task','legacy-session','task.completed',
    '2026-08-03T12:00:01+00:00','local_generalist','completed',NULL,
    'provider=fake tools=none'
);
INSERT INTO task_sources VALUES (
    'legacy-task','https://example.com/legacy','2026-08-03T12:00:01+00:00'
);
