# Traceability — Milestone M1

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
