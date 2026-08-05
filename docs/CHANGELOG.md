# Changelog

All notable, completed behavior. This project is pre-release; milestones gate scope.

The complete chronological record of improvements made during the independent
verification and owner test conversation is in
[CONVERSATION_IMPROVEMENT_LOG.md](CONVERSATION_IMPROVEMENT_LOG.md).

## Unified conversational awareness — 2026-08-05

- Added one bounded, role-aware conversation resolver shared by local generalist,
  hosted research, specialist execution, and route selection.
- Dependent turns carry the nearest relevant user/assistant exchange plus the
  original user intent, enabling multi-step follow-ups without keyword-specific
  routing patches.
- Prior assistant replies are labeled untrusted and cannot create web-routing
  authority. The current user request takes precedence.
- Independent hosted requests do not inherit unrelated history. Dependent hosted
  requests privacy-classify the complete outbound context and still require exact
  consent when prior owner content is local/private.
- Strict suite: **203 passing**.

## Qualified hosted research summaries — 2026-08-05

- Hosted research now requires the `web_search` tool, requests the provider's
  complete consulted-source metadata, retries incomplete/uncited responses once,
  and uses a configurable 1,024-token research output ceiling instead of a
  hard-coded 512-token ceiling.
- Valid relevant citation metadata without claim passages now produces a useful,
  explicitly unverified `inferred` provider summary rather than an empty abstention.
- Verified facts remain a separate empty region, verified claims remain empty,
  conflicts stay `unknown`, and injection-shaped text/free-form URLs are removed.
- Fixed market-query routing and evidence matching for `S&P500`/`S&P 500`,
  `index`/`indexes`, status/points/quote wording, and explicit “look it up” requests.
- Public commodity and market-price requests such as “price of gold” are now
  eligible for hosted research, while owner-specific holdings remain local.
- Rendered research sources now honor `research.max_results`, and common
  tracking-only URL variants collapse before selection.
- Ambiguous research follow-ups now carry one prior public user subject into the
  hosted query; combined private context still requires exact consent and
  unclassified context fails closed.
- Routing now evaluates dependent turns against that same bounded prior-user
  context. Follow-ups inherit current-information intent when appropriate, while
  follow-ups to timeless conversations remain on the local generalist.
- Live rerun retained one validated citation and returned a useful `inferred`
  S&P 500 summary with zero verified claims. Superseded strict-suite total: **203 passing**.

## Centralized runtime configuration — 2026-08-05

- Added one operational configuration surface: `[providers]`, `[models]`, and
  `[pricing]` in `config.local.toml` now control every generalist, research, and
  specialist runtime choice.
- Specialist manifests retain capability/security policy but can no longer carry
  a hidden provider model. A central default model applies to all specialists,
  with optional per-specialist overrides in the same main TOML.
- Normal startup auto-loads `config.local.toml`; `/status` displays the resolved
  providers, models, reservation price, consent maximum, and monthly budget.
- Legacy TOML locations remain accepted for migration, while central values take
  precedence.

## Independent V1 verification — 2026-08-04

- Repaired localhost-origin validation, exact one-shot consent and preview
  redaction, hosted-research consent, citation URL filtering, local output limits,
  assistant-turn persistence, specialist contract mismatch/type validation,
  audit secret/approval handling, claim-support honesty, and bounded cancellation.
- Corrected the M7 release harness so it executes regression tests and defaults
  unrun hardware/deterministic gates to pending rather than pass.
- Real application checks passed for qwen3:8b success, output ceiling,
  unavailable/missing-model mapping, and timeout. Live coding specialist passed
  after repair; hosted research now abstains when claim-level support is absent.
- Closure correction: M0–M2 remain closed; M3–M6 are reopened; M7 remains open.
  See `docs/V1_VERIFICATION_REPORT.md`.

### Historical M6 implementation claim — **superseded by 2026-08-04 verification**
- Added confirmed-only profile storage with sensitivity filtering, correction,
  deletion tombstones, expiry, and context injection; inferred values have no
  persistence path.
- Added SQLite schema v2 for durable redacted audit metadata, task sources,
  profile records, and transactional session/dependent-record deletion.
- Added `/profile`, `/history`, `/trace`, `/sources`, `/backup`, and `/restore`;
  startup retention maintenance and optional authenticated daily backups are wired
  through `ELLY_BACKUP_KEY` and `[storage]` configuration.
- Added M6 acceptance tests for no-store restart behavior, profile lifecycle,
  durable trace/source metadata, deletion scope, and backup authentication/
  integrity. Full suite is now **129 passing**.
- Added profile-store quarantine, failed-migration rollback evidence, WAL-safe
  backup checkpointing, and recovery-time coverage. Focused M6 coverage is now
  **8 tests** and the full suite is **132 passing**.
- Documented the backup envelope as a replaceable prototype crypto boundary;
  semantic memory, vector retrieval, portable trace export, and final UAT remain
  deferred to their approved milestones.

### Historical M7 implementation claim — **superseded by 2026-08-04 verification**
- Added a frozen EVAL-001…030 catalog and pinned release-evidence runner.
- Added a network-free release-gate command that maps deterministic regression
  coverage and explicitly reports live-quality, hardware, and owner-UAT gaps.
- M7 is not release-complete: no live quality, hardware re-confirmation, or owner
  UAT evidence is being represented as passed. The regression suite is now **135
  passing** with the M7 catalog contract tests. Subsequent M7 evidence and
  verification additions bring the current strict suite to **172 passing**.
- Collected real qwen3:8b provider/hardware evidence and one live hosted-search
  evidence sample with application-side citation validation. Full threshold review
  and owner UAT remain open.

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

### Milestone M3 — Guardrail Spine — **Complete 2026-08-04**
- Added application-owned atomic limits, bounded retry/backoff, circuit breaking,
  timeout cancellation, deterministic fake-cost reservation/reconciliation, and
  restart interruption with no replay.
- Added deterministic boundary, concurrency, failure, cost, timeout, queue, and
  recovery tests. Final suite: **105 tests passed**.

### Milestone M4 — Web Research, Evidence & Epistemic Honesty — **Complete 2026-08-04**
- Added freshness routing, hosted OpenAI `web_search`, deterministic fixture search,
  application-side citation validation, evidence/claim contracts, injection quarantine,
  explicit cloud-mode gating, and safe source rendering.
- Live adapter smoke returned a current answer and three citation URLs; deterministic
  M4 coverage brought the strict suite to **116 tests passed**.
- Brave, local page reading, page-body hashes, and full local-reader SSRF/content
  controls remain deferred under DEC-OQ-07.

### Milestone M5 — Cloud Specialists, Routing, Privacy & Consent — **Complete 2026-08-04**
- Added research/coding specialist execution through the registry, deterministic
  routing, typed structured results, exact hash-bound consent, privacy classification,
  depth-one/tool/high-impact authorization, fake provider coverage, and the live
  OpenAI Structured Outputs adapter.
- Added `/approve` and `/deny` consent commands. Final deterministic suite: **124 tests**;
  live `gpt-5.6-luna` specialist smoke returned a valid result.
