# Elly V3 Phase 0 — Contract Freeze and Characterization Record

**Date:** 2026-08-15  
**Baseline:** Closed V2.5 registry-driven routing  
**Status:** Completed; requirements and Phase 1 migration decisions approved

## 1. Authority and interpretation

The v3 requirements, technical design, and implementation plan are now marked
**Approved**. That approval authorizes implementation within the documented
scope; it does not move model authority across the deterministic application
boundary or authorize any behavior listed as a v3 non-goal.

For this Phase 0 record:

1. `REQUIREMENTS.md` defines the proposed v3 behavior and requirement IDs.
2. `TECHNICAL_DESIGN.md` defines the proposed architecture and its authority
   boundaries.
3. `IMPLEMENTATION_PLAN.md` defines the phased work and exit gates.
4. V2.5 source code and executable tests are the evidence for current behavior.
5. This record freezes observations and approved compatibility defaults; it does
   not replace the authoritative project SRS.

## 2. Requirement disposition

The approved documents authorize implementation of all thirteen requirements
within the phased plan. The table records that disposition explicitly so later
implementation does not treat a requirement as deferred accidentally.

| Requirement | Phase 0 disposition | Planned implementation phase |
| --- | --- | --- |
| V3-ROUTE-001 | Approved for implementation | 2–3 |
| V3-ROUTE-002 | Approved for implementation | 2, 5 |
| V3-CONFIG-001 | Approved for implementation | 1, 2, 7 |
| V3-PLAN-001 | Approved for implementation | 3 |
| V3-PLAN-002 | Approved for implementation | 4 |
| V3-PLAN-003 | Approved for implementation | 3, 6 |
| V3-EXEC-001 | Approved for implementation | 4–5 |
| V3-EXEC-002 | Approved for implementation | 5 |
| V3-SYN-001 | Approved for implementation | 7 |
| V3-SYN-002 | Approved for implementation | 6–7 |
| V3-RES-001 | Approved for implementation | 4, 6 |
| V3-REPLAN-001 | Approved for implementation | 8 |
| V3-OBS-001 | Approved for implementation | 3, 8 |

The confirmed direction in `REQUIREMENTS.md` is the implementation boundary;
model output remains advisory and deterministic validation, authorization,
dispatch, status, and presentation policy remain authoritative.

## 3. Frozen V2.5 behavior

The Phase 0 characterization suite freezes these current seams for later
regression comparison:

| Area | Current V2.5 behavior |
| --- | --- |
| Local conversation | A request without a validated registered-capability selection uses `local_conversation` and `LOCAL_DEFAULT`; the local generalist is called through `GeneralistPort`, and there is no silent cloud fallback. |
| Single-capability routing | `CapabilityRegistry` publishes an immutable routing catalog. `RoutingPolicy` selects a capability and operation, then returns the generic `registered_capability` route plus bounded selection metadata. Provider identity is resolved by the registered handler after selection. |
| Invalid/unavailable selection | Unknown, malformed, unsupported, or unavailable selections are rejected or rendered unavailable by deterministic policy; a rejected or unavailable capability is not executed. |
| Consent | Cloud disclosure uses the existing exact, one-use consent workflow bound to the task, provider/capability/purpose, payload, and expiry. Consent is distinct from consequential-action confirmation. |
| Cancellation | Application cancellation uses a request-scoped token, prevents successful completion, and interrupts a supported active provider. The public task state is `cancelled` with outcome `cancelled`. |
| Result persistence | Schema version 6 persists generic route metadata, selected capability/operation, selection reason, candidate diagnostics, and task results. No-store sessions do not persist answer bodies. Historical route rows remain readable. |
| Task and trace views | The shared application API exposes task and trace views with bounded routing metadata and redacted event detail. Interface adapters do not own routing policy. |
| Restart recovery | Startup calls `mark_interrupted_tasks`; previously running tasks are marked `interrupted` and are not automatically replayed. Existing operation records retain duplicate-execution information where applicable. |

The detailed behavior remains covered by the V2/V2.5 suites; the v3 suite is a
small compatibility layer rather than a second implementation of every matrix.

## 4. Representative storage fixture

`tests/fixtures/schema_v6_representative.sql` records a representative schema-v6
database containing:

- one retained session and user/assistant history;
- a completed generic-capability task with selected identity and routing
  diagnostics;
- a redacted audit event and task provenance; and
- the schema-v6 tables required to load the database and execute a new local
  V2.5 task.

The Phase 0 test loads the fixture through `SqliteSessionRepository`, verifies
the historical result, runs migrations idempotently, and executes a new local
conversation against the same database. No provider or network access is
required.

Schema v6 remains the V2.5 storage baseline. V3's additive schema-v7 plan tables
are intentionally not created in Phase 0.

## 5. Initial v3 contract identifiers

These identifiers are frozen as the initial v3 contract baseline. They are not
runtime schemas until their owning implementation phase adds and tests them:

| Contract | Identifier |
| --- | --- |
| Execution proposal | `elly.execution-proposal.v1` |
| Validated execution plan | `elly.execution-plan.v1` |
| Typed specialist step result | `elly.step-result.v1` |
| Synthesis input | `elly.synthesis-input.v1` |
| Synthesis draft | `elly.synthesis-draft.v1` |

Changing an identifier after Phase 0 requires an explicit compatibility note and
fixtures for any persisted or exchanged representation.

## 6. Initial enum vocabularies

The following strings are reserved for the first v3 contract version. They are
documented now so later phases do not invent overlapping spellings.

### Plan status

`PENDING`, `RUNNING`, `COMPLETED`, `PARTIAL`, `BLOCKED`, `FAILED`,
`UNAVAILABLE`, `CANCELLED`, `INTERRUPTED`

### Step state

`PENDING`, `READY`, `AUTHORIZING`, `RUNNING`, `COMPLETED`, `PARTIAL`, `FAILED`,
`BLOCKED`, `UNAVAILABLE`, `CANCELLED`, `SKIPPED`, `INTERRUPTED`

`POSSIBLE_DUPLICATE` is a recovery/operation marker, not a successful step
state.

### Step criticality

`REQUIRED`, `OPTIONAL`

### Finalization strategy

`DIRECT`, `TEMPLATE`, `LOCAL_SYNTHESIS`

### Proposal disposition

`LOCAL_ONLY`, `CAPABILITY_PLAN`, `CLARIFICATION_REQUIRED`, `UNABLE`

### Safe rejection and recovery codes

`PROPOSAL_MALFORMED`, `PROPOSAL_CAPABILITY_UNKNOWN`,
`PROVIDER_IDENTIFIER_NOT_ALLOWED`, `PLAN_CYCLE`,
`PLAN_DEPENDENCY_MISSING`, `PLAN_TYPE_MISMATCH`, `PLAN_LIMIT_EXCEEDED`,
`PLAN_REDUNDANT_STEP`, `STEP_AUTHORIZATION_DENIED`,
`STEP_DEPENDENCY_FAILED`, `STEP_RESULT_MALFORMED`,
`SYNTHESIS_REFERENCE_INVALID`, `SYNTHESIS_STATUS_MISMATCH`,
`REPLAN_NOT_ELIGIBLE`, `REPLAN_LIMIT_REACHED`,
`RECOVERY_EXTERNAL_OUTCOME_UNCERTAIN`

These safe codes are diagnostics only. They do not authorize a step and do not
replace the existing V2.5 `TaskStatus`, `OutcomeCode`, or `ErrorClass` values.

## 7. Local-model configuration migration baseline

V2.5 behavior remains unchanged by the Phase 0 work:

- built-in defaults are loaded first;
- an explicitly selected TOML file overrides defaults; and
- `ELLY_*` environment variables override TOML.

The current generalist keys and central provider/model tables remain compatible
through the Phase 1 migration window:

- when no v3 profile catalog or role bindings are supplied, old generalist
  settings may populate a generated `v2_generalist` profile and bind
  conversation, planner, and synthesis to it;
- when old and new values coexist, the named v3 profile catalog is authoritative
  and one redacted deprecation warning is emitted; and
- later versions may remove old-key parsing only after the owner accepts the
  deprecation window.

This is the approved compatibility default for Phase 1. Remote research and
specialist settings remain separate.

## 8. Restart and recovery baseline

Phase 0 freezes conservative recovery:

- startup marks stale running V2.5 tasks as `interrupted`;
- no uncertain external operation is automatically reissued;
- any future local read-only retry or hosted retry must be policy-controlled;
- a possible duplicate or uncertain consequential outcome cannot be presented
  as successful; and
- future v3 recovery must emit safe provenance without storing prompts, payloads,
  provider bodies, or hidden reasoning.

## 9. Current ownership boundaries

The current codebase has these ownership seams, which Phase 0 tests characterize
without introducing new v3 modules:

| Boundary | Current owner |
| --- | --- |
| Configuration loading and concrete adapter wiring | `src/elly/composition.py` and `src/elly/config.py` |
| Request lifecycle, cancellation, and workflow handoff | `src/elly/application/conversation.py` |
| Capability catalog and deterministic route selection | `src/elly/application/capabilities.py`, `catalog_routing.py`, and `routing.py` |
| Per-capability authorization and dispatch | `src/elly/application/capability_workflow.py` and registered handlers |
| Public task/status/trace boundary | `src/elly/api/application.py` and `src/elly/api/contracts.py` |
| Durable state and schema migrations | `src/elly/adapters/sqlite_repository.py` |

Application services do not resolve concrete providers from model output, and
the composition root is the only runtime wiring point for provider adapters.

## 10. Phase 0 exit status

Implemented evidence:

- current V2.5 behavior is covered by the existing regression suite and the new
  v3 characterization tests;
- a representative schema-v6 fixture loads, migrates idempotently, and supports
  a new local V2.5 task;
- current configuration, orchestration, routing, API, and persistence owners
  are recorded through static boundary assertions; and
- no v3 runtime planner, plan executor, schema-v7 migration, or synthesis
  implementation was added.

The Phase 0 implementation exit gate is **complete**. The approved requirement
disposition, contract identifiers, role-migration rule, restart policy, schema-v6
fixture, and characterization tests are recorded. Phase 1 is implemented and
verified in [PHASE_1_LOCAL_MODEL_ROLES.md](PHASE_1_LOCAL_MODEL_ROLES.md); Phase 2
may now proceed.
