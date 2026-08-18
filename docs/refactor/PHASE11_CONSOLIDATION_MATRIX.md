# Revised Phase 11 — Consolidation Matrix

This matrix records the test changes made after the complete pre-cleanup
inventory in [`PHASE11_TEST_INVENTORY.md`](PHASE11_TEST_INVENTORY.md). No
behavior was removed without a retained owner or an explicit lower-level
contract replacement.

## Removed or migrated coverage

| Removed or migrated historical test | Retained replacement | Behavior preserved |
|---|---|---|
| `test_orchestrator_conversation.py` | `test_runtime_conversation.py` | Success axes, provider/permanent/malformed failures, no fabricated success, persistence, `NO_STORE`, multi-turn context, cancellation, provider cancellation, audit correlation, local routing, and session isolation now run through `Application.runtime`. |
| `test_conversation_integration.py` | `test_runtime_conversation.py`; `test_runtime_compatibility` cases in `test_v2_phase0_characterization.py`; `test_idempotency.py`; `test_data_controls.py` | Integration failure mapping, CLI rendering, task correlation, persistence privacy, and idempotency remain covered at their current application boundaries. |
| Two direct-orchestrator tests in `test_capabilities.py` | Remaining registry contract tests plus `test_runtime_conversation.py` and `test_v2_capability_workflow_failures.py` | Registry availability/registration and canonical dispatch remain covered; implementation-bound orchestration assertions were removed. |
| Direct-orchestrator local lifecycle cases in `test_v2_phase0_characterization.py` | Same module through `Application.runtime` | Route metadata, typed result axes, persistence order, consent, and cancellation remain covered without the retired class. |
| Direct-orchestrator cases in `test_v2_phase4_intent.py` | `test_planning.py` and remaining `test_v2_phase4_intent.py` catalog/preparation cases | Planner fallback, live catalog validation, unknown capability rejection, and provider-bypass prevention remain covered. |
| Direct-orchestrator migrated-database execution in `test_migrations_v15.py` | Same test through `Application.runtime` | Old schema readability and a new canonical task on the migrated store remain covered. |
| Direct-orchestrator V3 boundary cases in `test_v3_phase0_characterization.py` | Same module through `Application.runtime` | Schema-v6 fixture readability, `NO_STORE`, cancellation, API views, and restart behavior remain covered. |
| Direct-orchestrator reliability setup in `test_idempotency.py` | Same module through `Application.runtime` plus the operation-ledger tests | Duplicate prevention, retryable-vs-uncertain leases, audit/persistence partial outcomes, and no duplicate user turn remain covered. |
| `test_v2_phase2_architecture.py` | `test_v2_capability_workflow_failures.py::test_registered_capability_completes_through_the_workflow_contract` | A registered capability still completes through the workflow contract, persists task truth, and is not coupled to a request orchestrator. |
| `test_response_composer_v15.py` | `test_v3_5_response_composer.py::SpecialistResultCompositionTests` | Specialist unknown/blocked/assumption three-axis mappings remain tested at the current response-composition owner. |

## Current-concept renames

| Historical filename | Current filename | Ownership clarified |
|---|---|---|
| `test_v3_phase2_local_planner.py` | `test_planning.py` | Planning contracts, catalog validation, and deterministic planner fallback. |
| `test_v3_phase3_plan_validation.py` | `test_plan_validation.py` | Execution-plan limits, graph validation, and redundancy rules. |
| `test_v3_phase4_scheduler.py` | `test_execution_scheduler.py` | Bounded DAG scheduling, concurrency, cancellation, timeout, and CAS. |
| `test_v3_phase5_authorization_results.py` | `test_execution_authorization.py` | Execution-time consent/action authorization and typed result envelopes. |
| `test_v3_phase6_aggregation.py` | `test_execution_aggregation.py` | Task truth aggregation and finalization. |
| `test_v3_5_recovery.py` | `test_execution_recovery.py` | Restart, exactly-once, persisted plan, and synthesis-result recovery. |
| `test_v3_phase8_replan_recovery.py` | `test_replan_recovery.py` | Bounded replan and startup recovery policy. |
| `test_v3_phase9_end_to_end.py` | `test_runtime_end_to_end.py` | Public runtime planning/execution and mixed-capability workflows. |
| `test_v3_phase7_synthesis.py` | `test_persisted_synthesis_compatibility.py` | Deterministic persisted `LOCAL_SYNTHESIS` compatibility shim. |
| `test_v2_api.py` | `test_api.py` | Public V2 façade contracts. |
| `test_v2_phase6_cli.py` | `test_cli_commands.py` | Command registry and public-API CLI contracts. |
| `test_m6_data_controls.py` | `test_data_controls.py` | Profile, trace, retention, backup, and privacy controls. |
| `test_v3_phase3_persistence.py` | `test_persistence.py` | Schema-v7 and atomic plan persistence. |
| `test_v2_5_phase5_route_persistence.py` | `test_routing_persistence_compatibility.py` | Historical route metadata and additive persistence. |

## Final required-behavior owners

The required matrix remains explicit after consolidation:

- trivial/complex planning, live catalog revalidation, cycles, bounded inputs:
  `test_planning.py`, `test_plan_validation.py`;
- sequential, parallel, downstream-result bounds, cancellation, timeouts, and
  state transitions: `test_execution_scheduler.py`, `test_external_cancellation_v15.py`;
- consent/action pause, exact continuation, denial, and protected-call
  suppression: `test_execution_authorization.py`, `test_api.py`,
  `test_runtime_end_to_end.py`;
- recovery/replan and restart-safe response composition:
  `test_replan_recovery.py`, `test_execution_recovery.py`;
- response truth/fallback and hostile composer output:
  `test_v3_5_response_composer.py`, `test_v3_5_adversarial.py`,
  `test_execution_aggregation.py`;
- old results/plans, schema migrations, `LOCAL_SYNTHESIS`, and
  `synthesis_results`: `test_migrations_v15.py`, `test_persistence.py`,
  `test_persisted_synthesis_compatibility.py`, `test_execution_recovery.py`;
- canonical local conversation and message persistence:
  `test_runtime_conversation.py`, `test_composition_and_smoke.py`;
- mixed capabilities and one authoritative public task state:
  `test_runtime_end_to_end.py`, `test_api.py`, `test_v2_interface_contracts.py`;
- `NO_STORE`, redaction, endpoint validation, privacy, and consent:
  `test_data_controls.py`, `test_audit_redaction.py`, `test_config.py`,
  `test_document_retrieval.py`, `test_authorization.py`;
- operation leases/idempotency and partial completion:
  `test_idempotency.py`, `test_v2_capability_workflow_failures.py`;
- public/routing/config compatibility:
  `test_api.py`, `test_v2_interface_contracts.py`,
  `test_routing_persistence_compatibility.py`, `test_v2_5_phase0_characterization.py`,
  `test_config.py`, `test_v3_phase1_local_model_roles.py`.

