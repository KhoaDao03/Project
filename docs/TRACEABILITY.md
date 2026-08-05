# Traceability — Version 1

**Independent verification status (2026-08-04):** M0–M2 closed; M3–M6 reopened;
M7 open. “Implemented + Tested” addenda below are historical implementation
claims, not proof that every acceptance-test clause is verified. The controlling
defect/evidence matrix is [V1_VERIFICATION_REPORT.md](V1_VERIFICATION_REPORT.md).

| Milestone | Current closure | Blocking defects/evidence |
|---|---|---|
| M0 | Closed | None |
| M1 | Closed | None after V1-012 repair |
| M2 | Closed | None after V1-002/006/010 repair and real CLI verification |
| M3 | Reopened | V1-015, V1-016 |
| M4 | Reopened | V1-017; live claim support remains `unknown` |
| M5 | Reopened | V1-018; V1-003/005/008/013/014 repaired |
| M6 | Reopened | V1-019, V1-020 |
| M7 | Open | V1-021; quality/UAT pending |

**Scope:** Milestone M1 (Walking Skeleton: Deterministic Local Conversation).
**Status legend:** Not started · Planned · Scaffolded · Partially implemented ·
Implemented · Tested · Owner reviewed · Verified · Blocked · Deferred.

> "Tested" = automated tests pass against the **fake-backed** M1 build. **M1 is
> Owner-reviewed (2026-08-04)** — the "Tested" rows below are owner-accepted for M1.
> "Verified" remains reserved for M7 acceptance against ATs with real providers;
> nothing is "Verified" yet.

## Requirement → implementation map (M1 slice)

| Req | UC | AT | Design | Component | Source (file · symbol) | Tests | Status |
|---|---|---|---|---|---|---|---|
| FR-001 text surface / input validation | UC-01, UC-10 | AT-01.1/.2/.3 | §6.1 | Presentation | `presentation/validators.py:normalize_and_validate`, `presentation/cli.py:Cli.dispatch` | `test_input_validation`, `test_cli_dispatch` | Tested |
| FR-002 multi-turn context (initial) | UC-01 | AT-01.4/.5 | §5.6 | Domain | `domain/context.py:build_context`; `application/conversation.py:handle` | `test_context_and_validation`, `test_orchestrator_conversation`, `test_conversation_integration:SessionIsolationTests` | Partially implemented (assembly Tested; real reference = M2) |
| FR-006 failure/partial (initial, local) | UC-01, UC-07/08 (later) | AT-14.1 (partial) | §6.8 | Application/Domain | `application/conversation.py:handle` (blocked path); `domain/errors.py` | `test_conversation_integration:FailureMappingTests`, `test_orchestrator_conversation` | Implemented + Tested |
| AI-002 deterministic orchestration (initial) | UC-01 | AT-03.5 | ADR-004, §5.4 | Application/Domain | `application/conversation.py:handle`; `domain/state_machine.py:ensure_transition` | `test_state_machine`, `test_orchestrator_conversation` | Implemented + Tested |
| AI-006 minimum context (initial) | UC-01 | AT-07 (partial) | §5.6, §6.6 | Domain | `domain/context.py`; `domain/models.py:ContextManifest` | `test_context_and_validation` | Implemented + Tested |
| AI-010 three-axis status (initial) | UC-01, UC-05 (later) | AT-08 (partial) | ADR-016, §6.2 | Domain | `domain/models.py:TaskResult`; `application/response_composer.py` | `test_models`, `test_orchestrator_conversation` | Implemented + Tested |
| DATA-001 session/no-store (partial) | UC-01, UC-09 (later) | AT-12.1 | §5.9, ADR-013 | Adapter | `adapters/sqlite_repository.py` | `test_sqlite_repository`, `test_orchestrator_conversation:no_store` | Implemented + Tested |
| DATA-004 audit records (initial) | UC-11 (later) | AT-13.1 | §5.8, ADR-015 | Adapter/Domain | `adapters/audit_log.py`; `domain/models.py:AuditEvent` | `test_audit_redaction`, `test_conversation_integration:AuditCorrelationTests` | Implemented + Tested |
| OPS-001 logging (initial) | UC-11 (later) | AT-13.5 | §5.8 | Adapter | `adapters/audit_log.py` | `test_audit_redaction` | Implemented + Tested |
| OPS-002 config/health (initial) | UC-10 | AT-13.2 | §6.1 | App/Config | `config.py:load_config`; `composition.py:Application.health` | `test_config`, `test_cli_dispatch:status` | Implemented + Tested |
| SEC-005 no high-impact / model-is-proposal (seam) | UC-03/04 (later) | AT-03.1/AT-10.5 (later) | §5.8 | Application | `application/conversation.py` (text treated as data); `cli.py` (`/mode cloud` denied) | `test_cli_dispatch:mode_cloud` | Scaffolded (seam) |
| SEC-007 log redaction (initial) | all | AT-10.6/.7 | §5.8 | Adapter/Domain | `adapters/audit_log.py:_redact_detail`; `AuditEvent` (no body field) | `test_audit_redaction`, `test_models:AuditEventPrivacyTests` | Implemented + Tested |
| NFR-006 portability (initial) | UC-12 (later) | AT-03.5 | ADR-003 | Ports/Adapters | `ports/*`; `composition.py` | `test_fake_generalist_contract`, `test_sqlite_repository:satisfies_port` | Implemented + Tested |
| AI-001 / API-001 local generalist | UC-01 | AT-02, AT-15 | ADR-007 | Adapter | `adapters/fake_generalist.py` (**FAKE**) | `test_fake_generalist_contract` | **Not started** (fake only; real = M2) |

## Deferred / unavailable in M1 (must remain so)

`/mode cloud` (M5), `/cancel` (M2/M3); web/RAG (M4), OpenAI specialists/consent (M5),
memory/profile (M6), limits/retry/circuit (M3), streaming/web-UI/trace-export
(optional). Enforced by explicit CLI messages and absence of the corresponding
ports/adapters.

## Verification evidence

- `PYTHONPATH=src python3 -W error::ResourceWarning -m unittest discover -s tests -t .` → **73 passed, 0 skipped**.
- `PYTHONPATH=src python3 -m compileall -q src tests` → OK.
- Entry-point smoke (`python -m elly`) → multi-turn render, `/status`, `/new --no-store`, explicit-unavailable paths.

## M2 implementation addendum

| Req | Design | Source | Tests/evidence | Status |
|---|---|---|---|---|
| AI-001 / API-001 local generalist | UC-01, §6.7 | `adapters/ollama_generalist.py:OllamaGeneralist` | `test_ollama_generalist`; live qwen3:8b smoke | Implemented + Tested; M2 complete |
| BUS-002 local-only | DEC-OQ-01/06, AT-02 | `composition.py:build`, localhost URL validation | composition health; no cloud adapter exists | Implemented + Tested |
| FR-006 typed local failure | §6.8 | `domain/errors.py`, `OllamaGeneralist.generate` | missing-model/malformed adapter tests | Implemented + Tested |
| FR-005 local cancellation | UC-07, AT-01.6 | `OllamaGeneralist.cancel`, `compose_cancelled` | cancellation error mapping path | Partially implemented |
| OPS-002 health | UC-10 | `OllamaGeneralist.health` | live health smoke | Implemented + Tested |
| NFR-003 hardware fit | AT-15.1/.2 | [`M2_QWEN3_8B_BENCHMARK.md`](M2_QWEN3_8B_BENCHMARK.md), DEC-M2-03 | qwen3:8b 2450 ms development smoke; owner-approved; qwen3:14b opt-in | Owner approved + Tested; final release gate M7 |
| AI-001/API-001 model selection | DEC-M2-01 | `config.example.toml`, `config.qwen3-14b.example.toml`, `config.py` | `test_config` | Implemented + Tested |
| BUS-003 specialist registration | DEC-M2-02, UC-12 | `specialists/manifest.py`, `specialists/registry.py`, `ports/specialist.py` | `test_specialist_registry` | Foundation implemented + Tested; execution deferred M5 |

## M3 implementation addendum

| Req | UC/AT | Source | Tests/evidence | Status |
|---|---|---|---|---|
| AI-019 / NFR-001 limits | UC-08, AT-11.1/.2 | `guardrails/limits.py:ReservationLedger`, `guardrails/executor.py:BoundedTaskExecutor` | `test_guardrails`, CLI limit test | Implemented + Tested |
| NFR-002 retry/circuit/timeout | UC-07/08, AT-11.3/.4 | `guardrails/controller.py`, `guardrails/retry.py` | retry, permanent, circuit, timeout tests | Implemented + Tested |
| OPS-003 fake cost | UC-08, AT-11.5/.6 | `guardrails/cost.py:FakeCostLedger`, `ports/cost.py:CostPort` | reserve/reconcile/over-budget tests | Implemented + Tested |
| OPS-004 interruption | UC-08, AT-14.3 | `sqlite_repository.py:tasks`, `mark_interrupted_tasks` | reopen/reconcile tests | Implemented + Tested |
| FR-005/FR-006 failure/cancel | AT-01.6, AT-14.1 | `conversation.py`, `response_composer.py`, `cli.py` | cancellation, typed failure, no-success tests | Implemented + Tested |

## M4 implementation addendum

| Req | UC/AT | Source | Tests/evidence | Status |
|---|---|---|---|---|
| FR-003 / AI-005 freshness routing | UC-02, AT-06.1 | `research/freshness.py`, `conversation.py` | `test_research:FreshnessTests`, CLI routing | Implemented + Tested |
| FR-004 / DATA-003 evidence and citations | UC-02, AT-06.2/.3/.6 | `ports/web_research.py`, `domain/models.py:EvidenceObject`, `presentation/render.py` | ten fixture questions, live adapter smoke | Implemented + Tested for hosted path |
| AI-009 / AI-012 evidence state and conflicts | UC-05, AT-07/08 | `application/research.py`, `response_composer.py` | conflict, absent, citation tests | Implemented + Tested for hosted path |
| SEC-003 injection quarantine | AT-10.1/.8 | `application/research.py:_quarantine_instructions` | hostile fixture test | Implemented + Tested |
| SEC-006 citation URL boundary | AT-10.2/.8 | `research/citation_validator.py` | HTTPS/private/DNS/duplicate tests | Implemented + Tested for hosted metadata |
| API-003 / DEC-OQ-07 hosted search | UC-02, AT-06 | `adapters/openai_web_research.py` | live `gpt-5.6-luna` web-search smoke | Implemented + Smoke-tested |

## Current M4 verification evidence

- Strict suite: **116 passed, 0 skipped**.
- Compileall and `git diff --check`: OK.
- Live provider: authentication/model inventory passed; actual hosted adapter returned
  a current answer and three citation URLs. Combined structured+web feasibility probe
  had provider HTTP 500; isolated web-search-only passed.
- Brave/local page-reader behavior remains deferred by DEC-OQ-07.

## M5 implementation addendum

| Req | UC/AT | Source | Tests/evidence | Status |
|---|---|---|---|---|
| AI-003/AI-005 specialist routing | UC-03/12, AT-03/04 | `conversation.py:route`, `specialists/registry.py` | registry and workflow tests | Implemented + Tested |
| AI-007/AI-008 result contract | AT-04/05 | `specialists/contracts.py`, `adapters/openai_specialist.py` | fake malformed/truncation and adapter tests | Implemented + Tested |
| AI-013 depth-one/tool authorization | AT-03.1/.2 | `application/specialists.py`, manifests | tool/high-impact denial tests | Implemented + Tested |
| AI-014/SEC-001/002 privacy + consent | UC-04, AT-09 | `privacy.py`, CLI `/approve`/`/deny` | classification/hash/expiry/mutation tests | Implemented + Tested |
| API-002/AI-004 OpenAI specialist | AT-05 | `adapters/openai_specialist.py` | `store:false`/Structured Outputs/no-tools test + live smoke | Implemented + Smoke-tested |
| OPS-003 usage/cost | AT-13.3 | `openai_specialist.py:last_usage`, M3 guardrails | live usage capture; configured estimate reconciliation | Implemented; billing pricing configured |

M5 strict verification: **124 passed, 0 skipped**. Live smoke returned a valid
`known` result from `gpt-5.6-luna` using public non-sensitive input.

## M6 implementation addendum

| Req | UC/AT | Source | Tests/evidence | Status |
|---|---|---|---|---|
| DATA-002 / DATA-005 profile continuity and deletion | UC-06/09, AT-12 | `memory.py:ProfileService`, `sqlite_repository.py` | `test_m6_data_controls:test_corrupt_profile_is_quarantined...`, profile lifecycle test | Implemented + Tested; Owner approved |
| DATA-001 no-store and retention | UC-06/09, AT-12.1/.2 | `sqlite_repository.py`, `composition.py:maintain_storage` | M6 no-store/restart and expiry tests | Implemented + Tested |
| DATA-004 / SEC-007 durable trace redaction | UC-11, AT-13.1/.5 | `audit_log.py`, `sqlite_repository.py` | durable audit/source test | Implemented + Tested |
| OPS-002 / OPS-003 status and budget | UC-10, AT-13.2/.3 | `composition.py:Application.health`, guardrails | existing health/budget tests | Implemented + Tested |
| OPS-004 quarantine, migration rollback, backup/restore | UC-06, AT-14.4/.5 | `sqlite_repository.py`, `operations.py` | quarantine, failed-migration rollback, recovery-time tests | Implemented + Tested |

M6 focused verification: **8 passed**. Current strict verification: **172 passed, 0 skipped**.
M6 is owner-approved and M7 release hardening is now in progress.

## M7 implementation addendum

| Req | UC/AT | Source | Tests/evidence | Status |
|---|---|---|---|---|
| NFR-004 permanent evaluation suite | AT-15.3, EVAL-001…030 | `evaluation/catalog.py`, `evaluation/runner.py` | `test_m7_release`; release-evidence JSON format | Implemented + Tested; live evidence pending |
| AT-15.4 deterministic release gate | AT-15.4 | `scripts/run_release_gate.py` | 172-test strict regression; deterministic gate passes | Tested |
| AT-15.5 quality thresholds | AT-15.5 | `docs/M7_RELEASE_CHECKLIST.md` | Harness reports provider-quality/live gates pending | Not yet verified |
| AT-15.6 owner UAT | AT-15.6, UC-01…UC-12 | `docs/M7_RELEASE_CHECKLIST.md` | Owner record not yet supplied | Pending |
| NFR-006 final adapter portability | AT-03.5/AT-15.4 | existing ports and contract tests | current regression suite | Tested; final M7 review pending |
