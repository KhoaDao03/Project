# V3 Phase 6 — Aggregation and Deterministic Finalization

**Status:** Implemented and verified

Phase 6 adds the application-owned boundary that turns terminal step states and
validated typed results into one honest plan result. It does not delegate plan
status, disagreement handling, or exact-record rendering to a model.

## Implemented behavior

- `PlanStatusPolicy` and `derive_plan_status` implement the documented
  cancellation-first precedence table. Required blocked, unavailable, failed,
  skipped, interrupted, cancelled, and partial branches remain distinct;
  optional incomplete work and material disagreement produce `PARTIAL`.
- `PlanAggregation` retains every step state, eligible result ID, typed result
  envelope, failure, warning, uncertainty, and disagreement record.
- `DisagreementRecord` joins canonical claim IDs and the Phase 5 typed finding
  ordinals across distinct steps. It retains every competing statement and
  evidence ID; it never creates a consensus value.
- `DirectFinalizer` passes through one completed presentation-ready result
  without rewriting it. Non-complete or malformed-shape cases use the same
  bounded deterministic status template.
- `TemplateFinalizer` renders plan/step status, incomplete branches,
  limitations, warnings, disagreements, and verified action receipts with
  stable application-owned text. `LOCAL_SYNTHESIS` currently uses this safe
  fallback until Phase 7 adds the evidence-bounded draft contract.
- `PlanExecutionResult` now exposes additive aggregate and final-result views.
  The orchestrator persists the final task result when a task row exists while
  preserving the precise plan status in the plan repository.
- Public API contracts add `PlanView`, `PlanStepView`, `PlanResultView`,
  `PlanTraceView`, and related query/event DTOs. `TaskView` gains optional plan
  and plan-result fields without changing existing V2/V2.5 fields.

## Main implementation seams

- `src/elly/application/plan_results.py` contains pure status policy,
  aggregation, disagreement detection, and deterministic finalizers.
- `src/elly/application/plan_executor.py` aggregates after all scheduler
  transitions and exposes the final result alongside legacy step mappings.
- `src/elly/application/plan_orchestrator.py` publishes the additive task-level
  result and maps plan-only `UNAVAILABLE` to the legacy task lifecycle safely.
- `src/elly/api/contracts.py` defines the bounded public plan/result/trace DTOs.
- `src/elly/api/application.py` translates persisted plan state, safe events,
  usage, result IDs, evidence IDs, and disagreements into those DTOs.

## Verification

`tests/test_v3_phase6_aggregation.py` covers every decision-table row,
cancellation precedence, retained partial work, explicit disagreement, direct
passthrough, template fallback, cancellation status preservation, receipts, and
public plan/trace views. Phase 4, Phase 5, and V2 API suites remain green in
targeted runs. The prescribed repository-wide gate passed 444 tests,
compilation, and `git diff --check`; Ruff and mypy were not installed and were
therefore skipped by the gate command.
