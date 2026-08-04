# M3 — Guardrail Spine: Implementation Status

**Status:** Complete — verified 2026-08-04.

## Implemented

- `guardrails/limits.py`: validated atomic step, provider-call, concurrency, and
  monthly-budget reservations.
- `guardrails/controller.py`: application-owned reservation, timeout, cancellation,
  retry, and cost reconciliation around every configured provider call.
- `guardrails/executor.py`: bounded in-process worker/queue admission; excess work
  is rejected before execution.
- `guardrails/retry.py`: transient-only bounded retry with deterministic jitter and
  circuit opening after repeated failures.
- `guardrails/cost.py`: deterministic fake-price monthly budget ledger.
- SQLite task lifecycle records and startup reconciliation mark prior `running`
  tasks `interrupted`; no task is replayed.
- `/status` displays effective guardrails; `/cancel` requests active provider
  cancellation.

## Security and correctness

Limits are enforced before provider execution by application code. Invalid config
fails closed. Provider/model output remains untrusted. Permanent, malformed, limit,
timeout, and circuit errors become typed blocked results; transient failures alone
may retry. No secret or prompt body is included in guardrail/audit details.

## Verification evidence

- Deterministic boundary, concurrency, retry, circuit, timeout, fake-cost, and
  restart tests are in `test_guardrails.py`, `test_config.py`, and
  `test_sqlite_repository.py`.
- Final command: `PYTHONPATH=src python3 -W error::ResourceWarning -m unittest discover -s tests -t .`
- Final strict suite: `105 passed, 0 failed`.

## Explicit limitations

M3 implements the local/provider-call guardrail subset. Web fetch, cloud pricing,
backup/restore, and migration rollback remain deferred to their approved milestones.
The monthly budget is authoritative; no separate daily budget is introduced.
