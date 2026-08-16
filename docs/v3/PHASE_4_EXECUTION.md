# Elly V3 Phase 4 — Bounded Dependency Execution

**Status:** Implemented and verified

Phase 4 executes a persisted Phase 3 `ExecutionPlan` through a separate
`PlanOrchestrator` and `PlanExecutor`. The existing conversation path remains
unchanged; plan execution is an additive application service and does not let
planner output select providers or handlers directly.

## Implemented boundaries

- `plan_state.py` defines the provider-free legal plan and step transitions:
  `PENDING -> READY -> AUTHORIZING -> RUNNING` followed by a terminal outcome.
- `PlanRepositoryPort` and SQLite persist compare-and-set plan/step transitions,
  authorization state, step results, and bounded safe plan events. Transition
  conflicts fail closed.
- `PlanExecutor` derives dependency-ready work, skips descendants of failed
  mandatory dependencies, allows eligible optional branches, and uses bounded
  worker slots from the captured plan limits.
- Specialist, research, and synthesis ceilings, provider-call ceilings,
  per-step timeout, total timeout, and parallelism are enforced in application
  code. The persisted plan snapshot is the authority for these limits.
- Each capability step is resolved from the live `CapabilityRegistry` just
  before dispatch and executed through `CapabilityExecutionWorkflow` in a
  plan-specific mode. Existing capability, privacy, consent, and action policy
  therefore remains mandatory while task-level completion is owned by the plan
  executor.
- Request cancellation is linked to every in-progress step, prevents new
  dispatch, and wins over a late result. Operation claims use the existing
  idempotency ledger before provider dispatch; stale claims do not re-run work.
- `PlanOrchestrator` owns the active-plan cancellation map and optionally hands
  the plan result back to the existing task lifecycle when a session/task row is
  available. `Application.execute_plan` exposes the composition-root boundary.

## Result and synthesis boundary

Phase 4 stores the existing provider-neutral `TaskResult` as a step result so
the scheduler can make dependency and status decisions. The versioned
`StepResultEnvelope`, evidence/disagreement aggregation, local synthesis, and
deterministic finalizers remain Phase 5–7 work. A synthesis step has a typed
executor injection seam and is bounded by the same scheduler; no provider or
registry access is granted to a synthesis callback by the plan contract.

## Verification

`tests/test_v3_phase4_scheduler.py` covers one-step dispatch equivalence,
sequential dependencies, bounded parallel ready steps, mandatory failure and
descendant skipping, optional failure with partial completion, cancellation
before queued dispatch and during active work, bounded timeout, external
authorization denial without provider dispatch, and persisted compare-and-set
transitions. Existing Phase 0–3, capability, migration, and V2.5 regression
suites remain part of the gate.

No recursive delegation, dynamic step creation, model-selected handler,
unbounded worker, or automatic replan is introduced by this phase.
