# M1 — Walking Skeleton: Implementation Status

**Milestone:** M1 (Walking Skeleton: Deterministic Local Conversation)
**Document status:** **COMPLETE — owner-reviewed 2026-08-04** (fake-backed by design; see §11 for what "complete" does and does not mean here).
**Date:** 2026-08-03 (updated 2026-08-04)
**Authoritative sources:** `docs/REQUIREMENT.md` (SRS 1.0), `docs/DESIGN.md` (0.1), `docs/MILESTONE_PLAN.md` (Finalized)

> Everything here is **fake-backed by design**: M1's outcome is a local conversation
> answered by a **deterministic fake generalist**. The real Ollama model is M2.
> No contract, fake, or directory is a completed real-provider capability.

---

## 1. What changed this pass

The M1 owner exercise (`ConversationOrchestrator.handle`) was **waived by the owner
on 2026-08-03** and implemented. The previously-skipped behavior spec is now active.

- Implemented `ConversationOrchestrator.handle` (UC-01 sequencing).
- Wired `state_machine.ensure_transition` into the lifecycle (AI-002/FR-006).
- Removed the `OrchestratorNotImplemented` stub and the CLI's owner-exercise branch.
- Made `ConversationOutcome.assistant_message` optional (None on blocked turns).
- Activated the 4 behavior-spec tests; added `test_conversation_integration.py`.

## 2. Decisions recorded this pass

- **DEC-M1-01** Owner waived the M1 "Owner implements with guidance" exercise and
  authorized the agent to implement `handle`. *Consequence:* M1 behavior is agent-
  authored; owner review still required before closure.
- **DEC-M1-02** `ConversationOutcome.assistant_message` changed from required to
  `Message | None` (default None). *Rationale:* a blocked/failed turn has no
  assistant reply to carry. *Blast radius:* additive/optional; no caller broke.

Both are non-authoritative implementation decisions; they do not alter the SRS,
DESIGN, or MILESTONE_PLAN.

## 3. Runtime path (UC-01)

`python -m elly` → `Cli.dispatch` → validate input (`presentation/validators.py`)
→ build `TaskRequest` → `ConversationOrchestrator.handle`:
receipt (QUEUED→RUNNING via state machine) → `build_context` from prior history →
persist user turn (repo honors no-store) → `GeneralistPort.generate` (fake) →
`validate_generalist_text` → success: persist assistant turn, `compose_success`
(COMPLETED/INFERRED/VALIDATED), audit `task.completed`; failure: `compose_blocked`
(BLOCKED), audit `generalist.failed` → `render.render_result` → terminal.

## 4. Install / run / test

```bash
PYTHONPATH=src python3 -m elly                       # run (uses defaults / ELLY_* env)
ELLY_DB_PATH=":memory:" PYTHONPATH=src python3 -m elly   # ephemeral DB
PYTHONPATH=src python3 -m unittest discover -s tests -t .            # 73 tests
PYTHONPATH=src python3 -W error::ResourceWarning -m unittest discover -s tests -t .  # strict
PYTHONPATH=src python3 -m compileall -q src tests    # syntax
```

Observed: **73 passed, 0 skipped** (strict). `ruff`/`mypy` declared in
`pyproject.toml [dev]` but **not installed** here → lint/type-check **deferred**.

## 5. Real vs fake

| Component | Kind |
|---|---|
| SQLite repository, audit (redacted, non-durable), system clock, config, CLI, composition, **orchestrator** | **REAL** |
| `FakeGeneralist` (the model) | **FAKE** — real Ollama is M2 |
| `FixedClock` | test fake |

## 6. Intentionally unavailable (fail explicitly)

`/mode cloud` (M5), `/cancel` (M2/M3). No web/RAG, OpenAI/specialists, memory/
profile, or limits/retry framework — later milestones, not scaffolded.

## 7. Fake-backed limitations (important)

- Answer quality / true in-session **reference resolution** cannot be demonstrated
  with a fake that only echoes. Context is **assembled and passed within budget**
  (tested via the manifest), but resolving "relate it to X" needs a real model (M2).
- No hardware/latency evidence (NFR-003 is M0/M2). No AT-15 release gate (M7).

## 8. Requirement status (M1 slice)

| Req | Status | Evidence |
|---|---|---|
| FR-001 text surface + input validation | Implemented + Tested | `presentation/*`, `test_input_validation`, `test_cli_dispatch` |
| FR-002 multi-turn context (initial) | Implemented + Tested (assembly); real reference = M2 | `domain/context.py`, `test_orchestrator_conversation` |
| FR-006 failure/partial (initial, local) | Implemented + Tested | `handle` blocked path, `test_conversation_integration` |
| AI-002 deterministic orchestration (initial) | Implemented + Tested | `handle`, `state_machine`, `test_state_machine` |
| AI-006 minimum context (initial) | Implemented + Tested | `context.py`, `ContextManifest` |
| AI-010 three-axis status (initial) | Implemented + Tested | `models.TaskResult`, `response_composer` |
| DATA-001 session/no-store (partial) | Implemented + Tested | `sqlite_repository`, `test_sqlite_repository` |
| DATA-004 audit (initial) | Implemented + Tested | `audit_log`, `test_audit_redaction` |
| OPS-001 logging / OPS-002 health (initial) | Implemented + Tested | `audit_log`, `composition.health`, `/status` |
| SEC-007 redaction / SEC-005 seam | Implemented + Tested | `audit_log`, `test_audit_redaction` |
| NFR-006 ports/adapters portability (initial) | Implemented + Tested | port Protocols, contract tests |
| AI-001 / API-001 real local model | **Not started** (fake only) | — (M2) |

None is "Verified" against ATs (that is M7); none is "Owner reviewed" yet.

## 9. Next implementation step

Owner reviews this implementation. Then, per plan, close M1 or proceed — but **only
after M0 (§11) records decisions and freezes contracts**, which M2+ depends on.

## 10. Owner reading order

`domain/models.py` → `ports/*` → `application/conversation.py` (`handle`) →
`domain/state_machine.py` → `adapters/*` → `presentation/cli.py` → `composition.py`.

## 11. Closure (2026-08-04) — what "complete" means here

M1 is **closed**: all six technical exit criteria pass (see MILESTONE_PLAN M1), the
prior blockers are resolved, and the owner has reviewed and accepted it.

- **M0 gate resolved:** decisions OQ-01…09 recorded (`docs/DECISIONS.md`); contracts
  frozen (`docs/CONTRACTS.md`); threat model + test specs authored. Contracts here
  conform to the frozen `v1.0` catalog.
- **Owner review:** completed 2026-08-04.

**What "complete" does NOT mean:** it is **fake-backed** — the generalist is a
deterministic fake, so genuine answer quality and true in-session reference
resolution are **not** demonstrated (that needs the real Ollama model, M2). Nothing
here is **"Verified"** against acceptance tests with real providers — that is M7. The
OpenAI/`web_search` feasibility smoke **passed** (RSK-02 retired); the NFR-003 hardware
benchmark is **deferred** to M2 — RSK-01 remains a carried risk.

**Next eligible milestone:** M2 (Real Local Generalist & Local-Only). Ollama + the
qwen3 models are installed; the NFR-003 benchmark is the first M2 task.
