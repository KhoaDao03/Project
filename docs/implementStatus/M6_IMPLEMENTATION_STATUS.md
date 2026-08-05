# M6 Implementation Status — Memory, Data Controls & Operations

Status: **Reopened by independent verification (2026-08-04).** The original
2026-08-05 completion claim below is future-dated relative to this audit and does
not prove closure. Post-audit repairs implement independent 30-day session,
7-day evidence, and 90-day audit retention; hourly maintenance/daily-backup
scheduling; schema-backed storage/audit health probes; and richer correlated
execution traces. The owner accepts the current basic authenticated prototype
backup envelope; vetted AEAD/key management is deferred to a later version.

## Delivered

- Confirmed profile items are separate from inference, require owner confirmation,
  support correction/deletion, sensitivity filtering, and expiry. Restricted items
  never enter model context; deletion records a non-sensitive tombstone.
- SQLite schema version 2 adds profile, audit, source, and tombstone tables.
  Startup marks interrupted tasks, purges expired profile items and sessions, and
  optionally creates one authenticated daily backup when `ELLY_BACKUP_KEY` is set.
- Audit records are durably stored after redaction and remain metadata-only; task
  sources are queryable through `/sources`. `/trace` exposes correlation-safe
  metadata without prompts, answers, secrets, or chain-of-thought.
- Retention and backup checks run periodically until orderly shutdown rather than
  only at process startup; session deletion removes dependent rows transactionally.
- `/profile`, `/history`, `/trace`, `/sources`, `/backup`, and `/restore` are
  available in the CLI. Restore validates the authenticated envelope and SQLite
  integrity; restart is required after restore so the live connection reloads it.
- Development/testing remains `qwen3:8b`; `qwen3:14b` remains explicit opt-in.
- Corrupt profile tables are renamed to timestamped quarantine tables, replaced
  with empty validated tables, and reported as degraded while base sessions and
  behavior remain available.
- Failed migrations roll back all schema changes and leave the prior schema
  version usable. Backup restore checkpoints WAL data and has a local recovery
  test with a five-second development bound.

## Verification evidence

- M6-focused tests: 8 passing (`tests/test_m6_data_controls.py`).
- Full suite: 132 passing, 0 skipped, with local socket permission required by
  the Ollama adapter contract tests.
- `compileall`: passed. Remaining release work is M7 evaluation/UAT and final gates.

## Security and limitations

The backup envelope is an authenticated SHA-256 keystream prototype isolated in
`operations.py`; it is accepted for this personal prototype only. Production
deployment should replace it with a vetted AEAD/KMS implementation before
high-value data. Backups are opt-in until an owner key is
configured. Restore is an operator action and requires restart. Semantic/episodic
memory, vector retrieval, and portable trace export remain deferred as planned.
