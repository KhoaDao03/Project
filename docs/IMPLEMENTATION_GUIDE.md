# Elly Implementation Guide — Milestone M1

**Objective (M1):** prove the architecture end-to-end with a local conversation
answered by a **deterministic fake** generalist — establishing the deterministic
orchestrator, ports/adapters seams, three-axis status, persistence, and audit,
before any real provider (Ollama = M2).

Read the code in this order:
`domain/models.py` → `ports/*` → `application/conversation.py` →
`domain/state_machine.py` → `adapters/*` → `presentation/cli.py` → `composition.py`.

---

## 1. Where execution begins

`src/elly/__main__.py:main` — parses `--config`, calls `composition.build()` to
wire the app, then `Cli.start(app).run()`. Config errors fail closed (exit 2).

## 2. Runtime path (happy turn)

1. `presentation/cli.py:Cli.run` reads a line → `Cli.dispatch`.
2. Plain text → `Cli._submit`: `validators.normalize_and_validate` (NFC, empty/size).
3. Builds a `TaskRequest` (`domain/models.py`) with a fresh `request_id`, the active
   session's modes, and `clock.now()`.
4. `application/conversation.py:ConversationOrchestrator.handle`:
   - `ensure_transition(QUEUED→RUNNING)` + audit `task.received`;
   - `repository.recent_messages` (prior turns) → `context.build_context` → prompt + `ContextManifest`;
   - `repository.append_message` (user turn — repo honors no-store);
   - `_call_generalist` → `GeneralistPort.generate` (the **fake**);
   - `validation.validate_generalist_text`;
   - success → append assistant turn, `compose_success` (COMPLETED/INFERRED/VALIDATED), `ensure_transition`, audit `task.completed`.
5. `presentation/render.py:render_result` prints Outcome / Evidence / Route.

## 3. How input is validated

At the boundary, before any orchestration (`validators.py`): reject empty/whitespace
and over-limit input, normalize Unicode NFC. `TaskRequest.__post_init__` re-validates
ids/text/timestamp defensively. Untrusted webpage/model content does not exist yet
in M1; model output is still treated as data, never executed (SEC-005 seam).

## 4. How data changes across components

`str` line → `TaskRequest` (validated value object) → `prompt: str` + `ContextManifest`
(context layer) → `GeneralistRequest` → `GeneralistResponse.text` → `ValidationStatus`
→ `TaskResult` (three axes) → `ConversationOutcome` → rendered `str`. Persisted:
`Message` rows and `AuditEvent` rows (metadata only).

## 5. Contracts used

`ports/generalist.py:GeneralistPort`, `ports/repository.py:SessionRepositoryPort`,
`ports/audit.py:AuditPort`, `ports/clock.py:ClockPort`; data contracts in
`domain/models.py`; error taxonomy in `domain/errors.py` / `enums.ErrorClass`.

## 6. How dependencies are selected

`composition.py:build` is the **only** place that binds concrete adapters to ports:
`FakeGeneralist`, `SqliteSessionRepository`, `StructuredAuditLog`, `SystemClock`.
Swapping the fake for Ollama in M2 changes this file + config only.

## 7. Where fakes / real adapters are invoked

Fake: `adapters/fake_generalist.py` (via `GeneralistPort`). Real: SQLite repo, audit
log, system clock. `FakeGeneralist` is deterministic, offline, and can be
constructed with a `FailureMode` to exercise typed failures.

## 8. Persistence & no-store

`SqliteSessionRepository` (WAL). On `append_message`, if the session is `NO_STORE`,
the body is stored as `""` with `stored_body=0`, so `recent_messages` returns empty
content — the body never lands on disk (DATA-001).

## 9. Logging & audit

`StructuredAuditLog` appends `AuditEvent`s (which have **no** body/prompt/answer
field) and logs allowlisted fields only; `detail` is single-lined and truncated
(SEC-007). Events share the `task_id` correlation. No chain-of-thought is logged.

## 10. Errors → structured statuses

Adapters raise typed `EllyError`s (`errors.py`). `handle` catches `EllyError` around
the model call/validation and maps to `compose_blocked` → `TaskResult`
(BLOCKED/BLOCKED/REJECTED) with a safe reason; success maps to COMPLETED/INFERRED/
VALIDATED. No fabricated success ever (FR-006).

## 11. How results return to the user

`handle` → `ConversationOutcome.result` → `render.render_result` → stdout. Blocked
results render `[blocked]` + `Failure:` + `Next:` lines, separated from any answer.

## 12. Why each boundary exists

- **Presentation/Application:** keep UI concerns (parsing, rendering) out of policy.
- **Ports/Adapters:** make providers replaceable and testable (NFR-006); the fake
  and the future Ollama adapter share one contract.
- **Domain purity:** models/validation/state machine run with no I/O, so policy is
  unit-testable without a DB or network.
- **Application-owned lifecycle:** the state machine + orchestrator (not the model)
  decide status and transitions (AI-002).

## 13. Alternatives considered

- pydantic vs stdlib dataclasses → **dataclasses** (zero deps, offline).
- Model-owned agent loop → rejected (ADR-004): can't enforce policy/limits.
- Durable audit store now → deferred to M6; M1 uses in-process + structured logs.
- Making `handle` fully data-driven/state-machine-per-step → deferred; M1's two
  transitions don't warrant it yet.

## 14. Replacing adapters later

Implement the port Protocol in a new adapter, add its config, add bounded
timeout/retry/error mapping, write contract tests mirroring
`test_fake_generalist_contract`, then bind it in `composition.build`. Domain and
application code do not change.

---

## Walkthroughs

- **Invalid input:** `""` → `normalize_and_validate` raises `InputInvalidError` →
  `_submit` returns "Input rejected: input is empty" — **no** model call
  (`test_input_validation`, AT-01.2).
- **Expected dependency failure:** `FakeGeneralist(TRANSIENT)` → `generate` raises
  `TransientProviderError` → `handle` catches → `compose_blocked` (BLOCKED) + audit
  `generalist.failed`; **no** `task.completed` (`test_conversation_integration`).
- **Unexpected internal failure:** a storage error in `append_message` raises
  `StorageFailureError` (an `EllyError`); it reaches `Cli._submit`'s `except
  EllyError` → "Blocked: …" — surfaced, not swallowed.
- **Security/limit scenario:** oversized input (> `max_input_chars`) is rejected at
  the boundary before any model call, naming the limit (`test_cli_dispatch`,
  AT-01.3). `/mode cloud` is denied explicitly (no cloud path exists) — application,
  not model, controls capability (SEC-005/AI-014 seam).

## Learning checkpoints

1. Trace one turn from `__main__` to `render_result` and name every boundary crossed.
2. Explain why `handle` loads history **before** persisting the current user turn.
3. Show why a blocked turn cannot render an answer (`TaskResult.__post_init__` +
   `render_result`).
4. Swap `FakeGeneralist` for a second fake in `composition.build` and confirm no
   test outside the adapter changes — that is NFR-006 in action.
