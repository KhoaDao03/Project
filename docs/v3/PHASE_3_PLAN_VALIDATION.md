# V3 Phase 3 — Pure Plan Validation and Persistence

**Status:** Implemented and verified

Phase 3 converts an accepted `ExecutionProposal` into an immutable,
application-owned `ExecutionPlan`. The implementation is pure until the
validated plan is explicitly handed to the repository; it does not call a
model, resolve a provider, execute a capability, or schedule work.

## Implemented boundaries

- `PlanBuilder` snapshots the descriptive routing catalog and deterministically
  validates capability availability, operations, typed inputs and outputs,
  freshness, external-access/effect metadata, dependencies, cycles, finalization,
  timeout, parallelism, and configured execution ceilings.
- Kahn topological sorting uses stable step IDs for tie-breaking, so registry
  insertion order cannot change the resulting plan.
- `RedundancyPolicy` creates the V3 fingerprint from capability, operation,
  objective class, perspective, normalized input references, and output type.
  Exact duplicates are rejected. A verification marker is accepted only when
  validated request metadata explicitly authorizes independent verification.
- `LOCAL_SYNTHESIS` creates one internal terminal step that depends on every
  proposed result. Direct and template finalization create no synthesis step.
- `PlanRepositoryPort` separates plan persistence from the existing session
  repository contract. `SqliteSessionRepository.save_plan` inserts the plan,
  ordered steps, typed input bindings, and dependency edges in one transaction.
- Schema migration 7 is additive, forward-only, idempotent, and retains the
  normalized result, claim-support, event, and synthesis table seams for later
  execution phases. Existing schema-v6 tasks remain readable and receive no
  synthetic plans.

## Configuration

The V3 plan ceilings are now represented by `Config.execution_plan_limits()`.
They are read from `[orchestration]` and corresponding `ELLY_*` environment
variables. V3 limits cannot silently expand the existing global step,
provider-call, concurrency, or timeout ceilings. Recursive planning and
specialist-created delegation remain disabled by default.

## Verification

Targeted Phase 3 coverage includes linear, diamond, and parallel DAGs; direct
and indirect cycles; missing and unavailable capabilities; unsupported
operations; typed producer/consumer mismatches; freshness and effect metadata;
limit boundaries; synthesis terminality; redundancy and verification policy;
catalog-order independence; schema-v6 to v7 migration; idempotent reruns;
rollback on migration failure; atomic save; and plan round trips.

No Phase 4 scheduler or capability execution is enabled by this phase.
