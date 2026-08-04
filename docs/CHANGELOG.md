# Changelog

All notable, completed behavior. This project is pre-release; milestones gate scope.

## [Unreleased]

### Milestone M0 (Decision, Feasibility & Contract-Freeze Gate) — **Complete 2026-08-04**
- Owner decisions **OQ-01…OQ-09** recorded (`docs/DECISIONS.md`), incl. hosted
  OpenAI `web_search` behind a `WebResearchProvider` + app-side citation validation,
  qwen3:14b/8b local models, terra/luna/sol tiering, DEC-OQ-05 limits, DEC-OQ-08
  storage/retention with automatic encrypted daily backups.
- Drafted `docs/CONTRACTS.md` (frozen contract catalog `v1.0`), `docs/THREAT_MODEL.md`,
  `docs/TEST_SPECS.md` (AT-01…15 + EVAL-001…030 + new AT-10.8 citation validator).
- `.env`/`.env.example` secrets mechanism (stdlib loader; gitignored).
- **OpenAI/`web_search` feasibility smoke PASSED** (`scripts/openai_smoke.py`,
  2026-08-04): `store:false` + `web_search` + Structured Outputs in one Responses call
  on `gpt-5.6-terra`; account exposes terra/luna/sol. **RSK-02 retired.**
- **Deferred (carried risk):** NFR-003 hardware benchmark → M2 (RSK-01).

### Milestone M1 (Walking Skeleton) — **Complete 2026-08-04** (owner-reviewed, fake-backed)

Fake-backed by design (real Ollama = M2); not "Verified" against acceptance tests (M7).

### Added
- Deterministic local conversation (UC-01) end-to-end through the terminal: input
  validation, minimum-context assembly, fake generalist call, output validation,
  three-axis result, session persistence (honoring no-store), and redacted audit.
- `ConversationOrchestrator.handle` with application-owned lifecycle transitions
  via the task state machine (AI-002, FR-006).
- Ports/adapters skeleton with a deterministic `FakeGeneralist`, SQLite repository,
  redacted structured audit, config loader, and health/`/status`.
- Test suite (stdlib `unittest`): **77 tests** across models, contracts, fakes,
  persistence/no-store, redaction, config, CLI dispatch, orchestrator behavior,
  session isolation, and the `.env` loader.
- Docs: README, `IMPLEMENTATION_GUIDE.md`, `TRACEABILITY.md`, updated
  `M1_IMPLEMENTATION_STATUS.md`.

### Notes / limitations
- The generalist is a **fake** (real Ollama = M2); answer quality and true
  in-session reference resolution are not yet demonstrable.
- Web/RAG, cloud specialists/consent, memory/profile, and the limits/retry framework
  are later milestones and intentionally unavailable.
# 2026-08-04

- Implemented the M2 localhost Ollama adapter, health check, typed failures,
  cooperative cancellation, real-model configuration, and deterministic adapter
  contract tests. M2 completion is recorded below; qwen3:14b remains opt-in.
- Set qwen3:8b as the development/testing default; qwen3:14b is explicit opt-in.
- Added validated, configuration-driven specialist manifest discovery as an M5
  foundation; no specialist execution is enabled in M2.
- Added [`M2_QWEN3_8B_BENCHMARK.md`](M2_QWEN3_8B_BENCHMARK.md) documenting the
  qwen3:8b live adapter smoke and its evidence limitations.
- Completed M2 cancellation handling: streamed partial work is preserved, the
  result is explicitly `CANCELLED`, and cancellation cannot emit global success.
- Documentation verification is synchronized to `90 passed` tests.
- M2 is complete as of 2026-08-04: qwen3:8b performance was owner-approved,
  real CLI smoke passed, and cancellation evidence is recorded. qwen3:14b remains
  explicit opt-in; M7 retains final release evaluation.
