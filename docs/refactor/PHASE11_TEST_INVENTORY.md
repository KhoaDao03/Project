# Revised Phase 11 — Pre-Consolidation Test Inventory

This inventory was created before deleting, moving, renaming, or merging any
test. It records the clean Phase 10 baseline and the proposed treatment of
each test module.

## Baseline

| Item | Value |
|---|---|
| Commit | `6a294645a94eadc3458b6801e13849475195c270` |
| Branch | `main` |
| Python | 3.12.3 |
| Test files | 66 |
| Test cases | 497 |
| Test classes | 153 |
| Historical/version-named files | 36 |
| Current-concept-named files | 30 |
| Pre-cleanup Ruff | Pass after five Phase 10 import-order fixes |
| Pre-cleanup MyPy | Pass: 135 source files |
| Pre-cleanup unittest | Pass: 497 tests |
| Pre-cleanup compileall | Pass |
| Pre-cleanup diff check | Pass |

The editable development install regenerated tracked `src/elly.egg-info`
metadata. That generated directory is a Phase 11 hygiene target and is not
part of the behavioral baseline.

## Classification vocabulary

- `CANONICAL_BEHAVIOR`: protects current service/application behavior.
- `PUBLIC_COMPATIBILITY`: protects established API/CLI contracts.
- `PERSISTED_COMPATIBILITY`: protects old database rows, plans, or results.
- `SECURITY_INVARIANT`: protects privacy, authorization, validation, or safety.
- `LEGACY_IMPLEMENTATION_BOUND`: directly instantiates the retired
  `ConversationOrchestrator` and must migrate before that module is deleted.
- `DUPLICATE`: candidate overlap requiring assertion-by-assertion review before
  consolidation; this label is not permission to delete by itself.
- `UNIQUE_REGRESSION`: narrow behavior with no safe duplicate identified.

## Complete file inventory

| File | Primary behavior | Level | Classification | Overlap | Proposed action |
|---|---|---|---|---|---|
| `test_audit_redaction.py` | Audit protocol, truncation, correlation, redaction | security/unit | SECURITY_INVARIANT | Low | Retain; current security name |
| `test_authorization.py` | Cloud/privacy classification and consent policy | security/unit | SECURITY_INVARIANT | Medium with V2 authorization tests | Retain pure policy; merge only exact duplicates |
| `test_capabilities.py` | Registry availability and dispatch | contract/application | CANONICAL_BEHAVIOR | Two tests use legacy orchestrator | Migrate those tests to canonical runtime; retain registry coverage |
| `test_centralized_config.py` | TOML/provider/model/pricing wiring | integration | CANONICAL_BEHAVIOR | High with `test_config.py` | Merge into canonical config module |
| `test_cli_dispatch.py` | Current CLI command behavior | application | CANONICAL_BEHAVIOR | Medium with V2 CLI tests | Merge duplicate command assertions; retain current end-to-end checks |
| `test_composition_and_smoke.py` | Composition and canonical local turn | application/integration | CANONICAL_BEHAVIOR | Low | Retain as canonical runtime smoke coverage; clean stale wording |
| `test_composition_validation.py` | Startup dependency validation | application/unit | CANONICAL_BEHAVIOR | Low | Retain |
| `test_config.py` | Canonical config, invalid input, aliases | unit/security | SECURITY_INVARIANT | Medium with phase-role config | Make canonical config owner; absorb non-duplicate cases |
| `test_context_and_validation.py` | Context bounds, no-store context, input validation | unit/security | SECURITY_INVARIANT | Medium with input validation | Merge only overlapping input cases; retain context cases |
| `test_conversation_integration.py` | Old orchestrator failures, audit, sessions, CLI | integration | LEGACY_IMPLEMENTATION_BOUND | High with canonical runtime tests | Migrate behavior cases to canonical runtime; remove old imports |
| `test_document_retrieval.py` | URL safety, bounds, hashing, timeout | security/contract | SECURITY_INVARIANT | Low | Retain |
| `test_dotenv.py` | Environment loader behavior | unit | CANONICAL_BEHAVIOR | Low | Retain or merge with config only if readable |
| `test_enums_errors.py` | Stable enum/error contracts | unit/contract | PUBLIC_COMPATIBILITY | Low | Retain |
| `test_evidence_policy.py` | Claim-level evidence eligibility | security/unit | SECURITY_INVARIANT | Low | Retain |
| `test_external_cancellation_v15.py` | Cancellation at external boundaries | concurrency/security | UNIQUE_REGRESSION | Low | Retain; rename to current cancellation concept if useful |
| `test_fake_generalist_contract.py` | Fake local provider contract/failures | contract | CANONICAL_BEHAVIOR | Low | Retain |
| `test_guardrails.py` | Limits, retries, cost, timeout, concurrency | security/concurrency | SECURITY_INVARIANT | Medium with execution tests | Retain distinct guardrail dimensions |
| `test_idempotency.py` | Operation ledger, duplicate requests, partial completion | security/integration | LEGACY_IMPLEMENTATION_BOUND | Some setup uses old orchestrator | Migrate direct callers; retain all failure/idempotency assertions |
| `test_input_validation.py` | Input normalization and size limits | security/unit | SECURITY_INVARIANT | Medium with context validation | Merge exact duplicates only |
| `test_local_conversation.py` | Local capability use-case/provider validation | unit | CANONICAL_BEHAVIOR | Low | Retain |
| `test_m6_data_controls.py` | Profile, no-store, retention, backup, quarantine | persistence/security | PERSISTED_COMPATIBILITY | Low | Rename to current data-controls concept; retain |
| `test_m7_release.py` | Release evidence catalog/reporting | contract | UNIQUE_REGRESSION | Low | Retain |
| `test_migrations_v15.py` | Historical migration and migrated execution | persistence | LEGACY_IMPLEMENTATION_BOUND | Direct old orchestrator setup | Migrate execution portion; retain migration cases |
| `test_models.py` | Domain model validation/privacy shape | unit/contract | CANONICAL_BEHAVIOR | Low | Retain |
| `test_ollama_generalist.py` | Local adapter HTTP contract and cancellation | integration/contract | CANONICAL_BEHAVIOR | Low | Retain |
| `test_orchestrator_conversation.py` | Old direct conversation lifecycle | integration | LEGACY_IMPLEMENTATION_BOUND | Replaced by canonical runtime conversation tests | Migrate all behavior assertions, then delete module |
| `test_research.py` | Research pipeline, freshness, evidence, failures | application/security | CANONICAL_BEHAVIOR | Medium with V2.5 web tests | Consolidate only proven duplicate cases |
| `test_response_composer_v15.py` | Earlier response composition contract | unit | DUPLICATE | High with V3.5 composer tests | Merge exact contracts into current response-composition tests |
| `test_revised_phase8_sqlite.py` | SQLite one-connection/decomposition invariants | persistence | UNIQUE_REGRESSION | Low | Rename to current SQLite architecture; retain |
| `test_routing_policy.py` | Routing policy decisions and safety | unit/contract | CANONICAL_BEHAVIOR | Medium with V2.5 routing tests | Consolidate current routing contract coverage |
| `test_specialist_registry.py` | Specialist manifest/registry behavior | contract | CANONICAL_BEHAVIOR | Medium with specialist milestone tests | Retain unique registry checks; merge exact duplicates |
| `test_specialists_m5.py` | Specialist workflow, schema, privacy, failures | application/security | SECURITY_INVARIANT | Medium with capability workflow tests | Retain security/failure dimensions; consolidate duplicates carefully |
| `test_sqlite_repository.py` | Repository contract, state, persistence | persistence/integration | PERSISTED_COMPATIBILITY | Medium with migration/data-control tests | Retain transaction/contract cases; merge exact duplicates only |
| `test_state_machine.py` | Task state transition invariants | unit | CANONICAL_BEHAVIOR | Low | Retain |
| `test_v2_5_phase0_characterization.py` | V2.5 public/routing baseline | compatibility | PUBLIC_COMPATIBILITY | Medium with current API/routing tests | Move retained cases to compatibility modules |
| `test_v2_5_phase1_routing_contracts.py` | Routing contract versions and adapters | contract | PUBLIC_COMPATIBILITY | Medium with routing policy | Rename/move retained compatibility cases |
| `test_v2_5_phase2_catalog_selector.py` | Catalog selection and availability | application | CANONICAL_BEHAVIOR | Medium with routing/capability tests | Consolidate exact selector cases |
| `test_v2_5_phase3_manifest_specialists.py` | Manifest-backed specialist selection | contract/security | CANONICAL_BEHAVIOR | Medium with specialist registry | Consolidate exact manifest cases |
| `test_v2_5_phase4_web_freshness.py` | Web freshness and research routing | application/security | SECURITY_INVARIANT | Medium with research tests | Consolidate only exact duplicate assertions |
| `test_v2_5_phase5_route_persistence.py` | Historical route persistence/readability | persistence | PERSISTED_COMPATIBILITY | Low/medium with persistence tests | Move to persistence compatibility module |
| `test_v2_5_phase6_boundaries.py` | Static architectural forbidden-boundary checks | contract | CANONICAL_BEHAVIOR | Medium with phase characterization | Retain checks that protect current boundary; remove redundant checks only with evidence |
| `test_v2_5_phase6_observability.py` | Public trace/status observability | public/integration | PUBLIC_COMPATIBILITY | Medium with API tests | Merge current public observability cases |
| `test_v2_api.py` | Public API submit/query/cancel/status | public/application | PUBLIC_COMPATIBILITY | Medium with interface tests | Keep as canonical public API owner |
| `test_v2_capability_workflow_failures.py` | Capability workflow failure mapping | application/security | SECURITY_INVARIANT | Medium with capabilities/specialists | Consolidate exact failure cases |
| `test_v2_interface_contracts.py` | Public interface parity and contracts | public/integration | PUBLIC_COMPATIBILITY | Medium with API/CLI tests | Retain parity contract; remove only duplicate setup |
| `test_v2_phase0_characterization.py` | Historical local routing, ordering, cancellation | integration | LEGACY_IMPLEMENTATION_BOUND | Direct old orchestrator callers | Migrate behavior to canonical runtime and compatibility boundary |
| `test_v2_phase2_architecture.py` | Old orchestrator architecture/capability injection | architecture/integration | LEGACY_IMPLEMENTATION_BOUND | Direct old orchestrator callers | Replace with canonical architecture assertions; delete old-layout checks |
| `test_v2_phase3_authorization.py` | Shared cloud authorization policy | security | SECURITY_INVARIANT | Medium with authorization tests | Retain unique policy dimensions; consolidate duplicate setup |
| `test_v2_phase4_intent.py` | Structured intent and capability preparation | application/security | LEGACY_IMPLEMENTATION_BOUND | One direct old orchestrator path | Migrate direct path; retain catalog validation cases |
| `test_v2_phase5_action_authorization.py` | Consequential-action confirmation | security/application | SECURITY_INVARIANT | Low | Retain all negative/approval/concurrency cases |
| `test_v2_phase6_cli.py` | Command registry and public CLI adapter | public/application | PUBLIC_COMPATIBILITY | Medium with CLI dispatch | Merge duplicate CLI assertions |
| `test_v2_sessions.py` | Durable session CAS/mode behavior | persistence/public | PERSISTED_COMPATIBILITY | Medium with data controls | Retain session CAS cases |
| `test_v3_5_adversarial.py` | Hostile composer output and fallback | security/application | SECURITY_INVARIANT | Medium with response composer | Retain all adversarial cases |
| `test_v3_5_recovery.py` | Restart, exactly-once, legacy plan/result recovery | persistence/recovery | PERSISTED_COMPATIBILITY | Medium with Phase 8 recovery | Retain unique restart/legacy cases; rename current concept |
| `test_v3_5_response_composer.py` | Response composition, fallback, wiring | application/security | CANONICAL_BEHAVIOR | High with older composer tests | Make current response-composition owner |
| `test_v3_phase0_characterization.py` | V3 boundary, API, persistence, cancellation | integration/compatibility | LEGACY_IMPLEMENTATION_BOUND | Direct old orchestrator cases | Split/migrate direct cases; retain public/persistence cases |
| `test_v3_phase1_local_model_roles.py` | Local role/profile configuration | config/security | CANONICAL_BEHAVIOR | High with config tests | Merge canonical config cases; retain legacy-input cases |
| `test_v3_phase2_local_planner.py` | Planner contracts, catalog, fallback, DAG proposal | planning/contract | CANONICAL_BEHAVIOR | Medium with plan validation | Rename to current planning; retain distinct planner cases |
| `test_v3_phase3_persistence.py` | Schema 7 and atomic plan persistence | persistence | PERSISTED_COMPATIBILITY | Medium with SQLite tests | Merge exact persistence cases; retain migration-specific cases |
| `test_v3_phase3_plan_validation.py` | Plan/DAG validation, limits, redundancy | planning/unit | CANONICAL_BEHAVIOR | Medium with planner tests | Retain as canonical plan validation owner |
| `test_v3_phase4_scheduler.py` | DAG scheduling, bounds, cancellation, CAS | execution/concurrency | CANONICAL_BEHAVIOR | Low | Retain as canonical execution scheduler owner |
| `test_v3_phase5_authorization_results.py` | Step authorization, typed results, envelopes | execution/security | SECURITY_INVARIANT | Medium with action/authorization tests | Retain typed result and execution-boundary cases |
| `test_v3_phase6_aggregation.py` | Task truth, aggregation, finalization views | execution/presentation | CANONICAL_BEHAVIOR | Medium with response composer | Retain truth/finalization cases |
| `test_v3_phase7_synthesis.py` | Persisted `LOCAL_SYNTHESIS` shim | persistence/compatibility | PERSISTED_COMPATIBILITY | Low | Rename to `test_persisted_synthesis_compatibility.py` |
| `test_v3_phase8_replan_recovery.py` | Bounded replan, recovery, provenance | execution/persistence | PERSISTED_COMPATIBILITY | Medium with V3.5 recovery | Retain unique replan/recovery cases |
| `test_v3_phase9_end_to_end.py` | Public planner-to-plan and mixed capabilities | integration | CANONICAL_BEHAVIOR | Low | Retain as canonical end-to-end coverage |

## Required coverage matrix before consolidation

| Required behavior | Existing evidence before consolidation | Planned retained owner |
|---|---|---|
| Trivial request creates deterministic one-step plan | `test_composition_and_smoke.py`, `test_v3_phase2_local_planner.py` | `test_runtime_conversation.py`, `test_planning.py` |
| Complex request creates multi-step plan | `test_v3_phase2_local_planner.py`, `test_v3_phase9_end_to_end.py` | `test_planning.py`, `test_runtime_end_to_end.py` |
| Sequential dependencies execute in order | `test_v3_phase4_scheduler.py` | `test_execution_scheduler.py` |
| Independent ready steps execute concurrently | `test_v3_phase4_scheduler.py` | `test_execution_scheduler.py` |
| Downstream receives bounded upstream results | `test_v3_phase4_scheduler.py`, `test_v3_phase2_local_planner.py` | `test_execution_scheduler.py` |
| Unavailable capability is rejected safely | `test_capabilities.py`, `test_v3_phase2_local_planner.py`, `test_v2_phase4_intent.py` | `test_capability_registry.py`, `test_planning.py` |
| Cyclic plans are rejected | `test_v3_phase3_plan_validation.py`, `test_v3_phase2_local_planner.py` | `test_planning.py` |
| Consent-required step pauses safely | `test_v2_phase3_authorization.py`, `test_v3_phase9_end_to_end.py` | `test_execution_authorization.py` |
| Authorized consent resumes exact plan/step | `test_v3_phase9_end_to_end.py` | `test_execution_authorization.py` |
| Consequential action confirmation pauses | `test_v2_phase5_action_authorization.py` | `test_execution_authorization.py` |
| Approval resumes exact action once | `test_v2_phase5_action_authorization.py` | `test_execution_authorization.py` |
| Denial dispatches no protected call | `test_v2_phase5_action_authorization.py`, `test_v3_phase4_scheduler.py` | `test_execution_authorization.py` |
| Cancellation reaches running/pending work | `test_v3_phase4_scheduler.py`, `test_external_cancellation_v15.py`, old conversation tests | `test_execution_cancellation.py` |
| Timeout produces correct state | `test_guardrails.py`, `test_v3_phase4_scheduler.py` | `test_execution_scheduler.py`, `test_guardrails.py` |
| Interrupted persisted plans recover safely | `test_v3_phase8_replan_recovery.py`, `test_v3_5_recovery.py` | `test_execution_recovery.py` |
| Bounded replan preserves policy | `test_v3_phase8_replan_recovery.py` | `test_execution_recovery.py` |
| Composer cannot change execution truth | `test_v3_5_adversarial.py`, `test_v3_phase6_aggregation.py` | `test_response_composition.py` |
| Composer failure uses deterministic fallback | `test_v3_5_adversarial.py`, `test_v3_5_response_composer.py` | `test_response_composition.py` |
| Legacy TaskResults remain readable | `test_v3_phase5_authorization_results.py`, `test_migrations_v15.py` | `test_persistence_compatibility.py` |
| Legacy ExecutionPlans remain readable | `test_v3_phase3_persistence.py`, `test_v3_5_recovery.py` | `test_persistence_compatibility.py` |
| Persisted `LOCAL_SYNTHESIS` remains executable | `test_v3_phase7_synthesis.py`, `test_v3_5_recovery.py` | `test_persisted_synthesis_compatibility.py` |
| `synthesis_results` remains readable | `test_v3_5_recovery.py`, SQLite repository tests | `test_persistence_compatibility.py` |
| Ordinary local conversation uses canonical path | `test_composition_and_smoke.py`, `test_v3_phase9_end_to_end.py` | `test_runtime_conversation.py` |
| Research + specialist + local reasoning can combine | `test_v3_phase9_end_to_end.py` | `test_runtime_end_to_end.py` |
| API/runtime expose one task truth | `test_v2_api.py`, `test_v2_interface_contracts.py`, `test_v3_phase9_end_to_end.py` | `test_api.py`, `test_runtime_end_to_end.py` |
| `NO_STORE` suppresses sensitive bodies | `test_m6_data_controls.py`, `test_v3_phase0_characterization.py`, old conversation tests | `test_security_privacy.py`, `test_persistence_compatibility.py` |
| Leases/idempotency prevent unsafe duplicates | `test_idempotency.py`, `test_v3_5_adversarial.py`, recovery tests | `test_idempotency.py` |
| Old routing metadata remains readable | V2.5 route persistence, V3 boundary, API tests | `test_persistence_compatibility.py`, `test_api.py` |
| New routing uses generic route/capability/operation | V2.5 routing and V3 phase 0 tests | `test_routing.py` |
| Planner proposals are revalidated live | `test_v3_phase2_local_planner.py` | `test_planning.py` |
| Provider identifiers cannot bypass capability validation | `test_v2_phase4_intent.py`, `test_v3_phase2_local_planner.py` | `test_routing.py`, `test_capability_registry.py` |
| Legacy config remains loader-only and fail-closed | `test_config.py`, `test_v3_phase1_local_model_roles.py`, composer config tests | `test_config.py` |
| Canonical roles remain conversation/planner/response_composer | `test_config.py`, role tests, composer wiring | `test_config.py` |

## ConversationOrchestrator caller evidence

Repository-wide search found no production/public construction outside the class
definition itself. Direct test callers occur in:

- `test_orchestrator_conversation.py`;
- `test_conversation_integration.py`;
- `test_capabilities.py`;
- `test_v2_phase0_characterization.py`;
- `test_v2_phase2_architecture.py`;
- `test_v2_phase4_intent.py`;
- `test_migrations_v15.py`;
- `test_v3_phase0_characterization.py`;
- `test_idempotency.py`.

These callers protect real behavior, but not a supported production/public
Python contract. They must be migrated to the canonical runtime or to the
appropriate lower-level boundary before `src/elly/application/conversation.py`
is deleted. The legacy class is not deleted merely because it is old.

Post-consolidation outcome: all nine caller groups were migrated or removed with
replacement evidence, and `src/elly/application/conversation.py` was deleted.
The final deletion/rename mapping and actual current test owners are recorded in
[`PHASE11_CONSOLIDATION_MATRIX.md`](PHASE11_CONSOLIDATION_MATRIX.md).

## Consolidation decision rule

No test is deleted solely because it shares a final status or filename theme
with another test. A deletion requires an entry in the final consolidation
matrix naming the retained replacement and the preserved edge-case dimensions:
failure mode, privacy mode, persistence mode, concurrency, authorization,
recovery, or compatibility.
