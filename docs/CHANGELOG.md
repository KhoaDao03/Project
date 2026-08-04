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
