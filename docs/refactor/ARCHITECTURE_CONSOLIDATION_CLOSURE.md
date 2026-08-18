# Architecture Consolidation Closure

## Status

COMPLETE

## Baseline

Phase 11 commit:

`76fa8929eeb72159c2480cc6cea4048b5fca129a`

## Final Canonical Architecture

```text
Public API / CLI
    -> AssistantRuntime
    -> PlanningService
    -> ExecutionPlan
    -> TaskExecutionService
    -> CapabilityRegistry
    -> ResponseCompositionService
    -> TaskResult
```

`PlanRunner`, `StepRunner`, and `PlanFinalizer` remain execution internals.

## Retired Internal Architectures

- `ConversationOrchestrator`
- `PlanOrchestrator`
- `PlanExecutor` compatibility
- model-generating synthesis runtime

## Intentional Compatibility Remaining

| Category | Why it remains | Boundary and retirement condition |
|---|---|---|
| Public API | V2 clients still depend on the published contracts. | API façade; retire only through an explicit API-version decision. |
| Routing | Historical `Route` values and metadata remain in stored rows and compatibility inputs. | Routing compatibility boundary; retire after clients and persisted rows migrate. |
| Config input | Deprecated spellings are needed during the configuration migration window. | Loader-only compatibility; retire after the migration window closes. |
| Persistence | SQLite schema V1–V7, historical task results, execution plans, route records, and `synthesis_results` remain supported data. | SQLite repository/migration boundary; retire after retention and upgrade policy completion. |
| Old-data execution | `LOCAL_SYNTHESIS` is required to recover persisted legacy plans deterministically. | `task_execution/legacy.py`; retire after the supported legacy-data window closes. |

## Final Corrective Patch

- Preserved provider `CancelledError.partial_work` in the final cancelled
  `TaskResult` without adding cancelled steps to the eligible-result set.
- Strengthened the canonical runtime cancellation regression with the exact
  useful provider value, cancelled status, non-completion, and audit assertions.
- Added an aggregation regression proving cancelled claims and citations are
  not promoted.
- Corrected the permanent-failure test name to describe the persisted safe
  blocked assistant turn.
- Updated `docs/PROJECT_CONTEXT.md` to describe committed Phase 11 status.

## Verification

- Ruff: `All checks passed!` from `ruff check src tests`.
- strict MyPy: `Success: no issues found in 134 source files` from `mypy src`.
- unittest: `Ran 494 tests` followed by `OK`.
- compileall: passed from `python -m compileall -q src tests`.
- `git diff --check`: passed.
- The full unittest run used the local loopback-fixture permission required by
  the environment; no test failure was hidden by that permission.
- GitHub Actions: not queried; no push was performed for this local closure.

## Closure Decision

`ARCHITECTURE CONSOLIDATION COMPLETE`

Future work should proceed through normal product requirements and design, not
another consolidation phase.
