# Elly Architecture Refactor Roadmap

## 1. Goal

Converge the existing Elly codebase on the target architecture described in `01_TARGET_ARCHITECTURE.md` without a rewrite and without changing user-visible behavior unnecessarily.

This is a **controlled architectural consolidation**, not a feature release.

The work must be incremental, test-gated, and reversible.

---

# 2. Current architecture hotspots to inspect first

The implementation agent should verify the current repository before changing anything, but the known high-value areas are:

```text
src/elly/composition.py
src/elly/application/plan_executor.py
src/elly/application/response_pipeline.py
src/elly/api/application.py
src/elly/adapters/sqlite_repository.py
src/elly/routing.py
src/elly/catalog_routing.py
src/elly/config.py
src/elly/ports/local_synthesis.py
src/elly/ports/local_response_composer.py
```

Also inspect:

- planning contracts;
- plan/result/step contracts;
- capability registry and capability execution workflow;
- `ConversationOrchestrator`;
- `PlanOrchestrator`;
- `CompletionService`;
- `ReplanService`;
- `PlanRecovery`;
- authorization/consent workflow;
- all version-era tests that freeze V2/V2.5/V3/V3.5 internals.

Do not assume this list is exhaustive.

---

# 3. Execution rules for all phases

1. Inspect before editing.
2. Establish the current behavior and test baseline.
3. Make one conceptual change at a time.
4. Preserve public behavior unless the phase explicitly changes an architectural route.
5. Prefer moving existing behavior over rewriting it.
6. Do not create a replacement abstraction while leaving the old runtime path active indefinitely.
7. Compatibility code must have a reason and retirement condition.
8. Run targeted tests after each small change.
9. Run the full deterministic suite at the end of every phase.
10. Run lint/type/compile checks at the end of every phase.
11. Keep commits phase-scoped if git commits are authorized.
12. Do not bundle opportunistic feature work with the refactor.
13. If a phase reveals a safety/correctness defect, fix it and document why.
14. If a compatibility requirement prevents deletion, isolate it from the normal runtime path.

---

# 4. Phase 0 — Baseline and characterization

## Objective

Create enough safety coverage that architecture can be changed without guessing.

## Work

- Record current repository HEAD.
- Run the full current test suite.
- Run static checks currently used by the repository.
- Inspect current request paths for:
  - ordinary local conversation;
  - web/research;
  - specialist execution;
  - multi-step plan execution;
  - cancellation;
  - timeout;
  - consent pause/resume;
  - action authorization;
  - recovery;
  - response composition;
  - persisted legacy result decoding.
- Add behavior-level characterization tests only where current behavior is insufficiently protected.

## Characterization tests should prefer

```text
request -> task state/result
request -> plan
plan -> capability execution order
dependency -> parallel readiness
cancel -> terminal state
consent -> pause/resume
failed composer -> deterministic fallback
legacy persisted payload -> readable current result
```

Avoid adding tests that merely freeze private class layout.

## Acceptance criteria

- Baseline test count/result recorded.
- Current deterministic suite passes.
- Major user-visible flows have behavior-level protection.
- No production behavior changed.

---

# 5. Phase 1 — Retire obsolete runtime synthesis generation

## Objective

Remove the duplicate V3 runtime synthesis path and make V3.5-style response composition the single normal finalization path.

## Why first

Keeping two generations of final-response behavior infects the executor, composition root, config, ports, tests, and result pipeline.

Removing it early reduces complexity for every later phase.

## Work

- Trace every use of:
  - `local_synthesis`;
  - synthesis executor/port;
  - synthesis-role configuration;
  - synthesis finalization branches;
  - legacy synthesis result types.
- Separate:
  - **runtime behavior still used for new requests**;
  - **legacy persisted-data decoding required for old stored records**.
- Remove obsolete runtime execution of synthesis.
- Route normal answer-bearing tasks through `ResponseCompositionService`.
- Preserve only the minimum legacy reader/decoder required for old persisted data.
- Mark compatibility helpers with an explicit retirement condition/version.

## Do not

- delete legacy decoders before migration/read tests prove safety;
- replace response composition with arbitrary local-model reasoning;
- change task truth based on composer wording.

## Acceptance criteria

- New requests have exactly one response-composition/finalization path.
- No new plan schedules legacy synthesis.
- Legacy stored synthesis/result payloads remain readable where required.
- Full tests and static checks pass.
- Executor constructor and composition root have materially fewer synthesis-era dependencies.

---

# 6. Phase 2 — Establish the canonical PlanningService boundary

## Objective

Make `PlanningService` the single architectural place where work selection/decomposition occurs.

## Desired rule

> Every request goes through PlanningService; not every request needs LLM planning.

## Work

- Map current responsibilities across:
  - routing;
  - catalog routing;
  - plan interpretation;
  - plan building;
  - planner;
  - plan validation;
  - conversation routing.
- Define one public planning entry point.
- Reuse existing sound planning contracts wherever possible.
- Introduce a deterministic fast path for obvious one-step requests if the current code does not already provide one cleanly.
- Preserve the local LLM planner for genuinely complex decomposition.
- Ensure both strategies return the same canonical `ExecutionPlan` contract.
- Validate capability existence and dependencies before execution.

## Examples that must be possible

### Trivial

```text
"Explain dependency injection"
-> one step: local reasoning/conversation
```

### Sequential

```text
"Research NVIDIA earnings and analyze them"
-> web_research -> local_analysis
```

### Parallel + merge

```text
web_research
     |
 +---+---+
 |       |
stock   research specialist
 |       |
 +---+---+
     |
 local_compare
```

## Acceptance criteria

- There is one application-level planning boundary.
- Fast-path and LLM planning are internal strategies, not separate orchestration systems.
- Both produce validated plans.
- Planner output cannot bypass authorization or capability registry constraints.
- Full tests pass.

---

# 7. Phase 3 — Make conversation a capability, not a second orchestrator

## Objective

Eliminate the peer `ConversationOrchestrator` architecture.

Normal conversation should be a trivial plan executed through the same task execution system.

## Work

- Identify logic in `ConversationOrchestrator` and local conversation use cases that is:
  - actual capability behavior;
  - request lifecycle behavior;
  - persistence/session behavior;
  - cancellation behavior.
- Move/reuse actual conversation/model invocation behavior behind an executable local capability.
- Route simple conversation planning to that capability.
- Move shared lifecycle/cancellation/state behavior to the canonical runtime/execution owner.
- Remove duplicated cancel paths once behavior is covered.

## Important performance rule

Do not make:

```text
"hi"
```

require expensive agentic planning.

A trivial deterministic plan is sufficient.

## Acceptance criteria

- Ordinary chat uses:
  - `PlanningService`;
  - a one-step plan;
  - `TaskExecutionService`;
  - a local capability;
  - `ResponseCompositionService` or an explicitly justified minimal equivalent finalization path.
- `ConversationOrchestrator` is deleted or reduced to a temporary compatibility shim with no independent lifecycle authority.
- Cancelling a task does not require calling two orchestration systems.
- Full tests pass.

---

# 8. Phase 4 — Refactor PlanExecutor into TaskExecutionService

## Objective

Create one clear execution authority without replacing the current scheduler with a generic workflow framework.

## Current problem

The existing plan executor carries too many responsibilities in one large module.

## Target

```text
TaskExecutionService
    +-- PlanRunner
    +-- StepRunner
    +-- PlanFinalizer
```

These may be classes, modules, or cohesive private components depending on what best fits the code.

## Extract responsibility, not line count

### PlanRunner

- state machine;
- dependency readiness;
- worker scheduling;
- bounded parallelism;
- cancellation propagation;
- completion detection.

### StepRunner

- capability lookup;
- authorization boundary;
- step input;
- timeout/retry;
- invocation;
- result normalization;
- step persistence.

### PlanFinalizer

- terminal aggregation;
- response-composition handoff;
- task final state;
- deterministic fallback.

## Recovery/replanning

Keep recovery behavior explicit.

Do not hide it in a generic retry library.

Bounded replan should preserve:

- maximum attempts;
- policy checks;
- existing evidence;
- authorization boundaries;
- cancellation.

## Acceptance criteria

- One service owns plan execution lifecycle.
- Main execution module is substantially easier to read.
- The scheduler is not duplicated.
- No new orchestration framework is introduced.
- Concurrency/cancellation/recovery tests pass.
- Full suite passes.

---

# 9. Phase 5 — Runtime ownership consolidation (completed)

## Objective

Establish one genuine application runtime boundary so composition builds the
system while the runtime coordinates the outer request lifecycle.

## Work

- Introduce `application.runtime.AssistantRuntime` as the owner of request handling
  and bounded submission.
- Move context construction, `PlanningService` invocation, validated-plan
  persistence, `TaskExecutionService` invocation, normal final task/result/message
  completion, and in-process authorization continuation into that runtime.
- Make cancellation coordination explicit: planning cancellation remains in
  `PlanningService`; execution cancellation remains in `TaskExecutionService`;
  `AssistantRuntime` delegates to both.
- Keep dependency construction, startup migration/recovery, health, maintenance,
  backup/profile operational wiring, and shutdown in composition.
- Remove normal final-result persistence from the public API future callback so
  there is one authoritative application-layer persistence owner.
- Preserve API consent/action state and denial completion as bounded compatibility
  until Phase 6; do not redesign public DTOs or future tracking here.

## Composition root should primarily

- create adapters;
- create registries;
- create policies;
- create services;
- connect dependencies;
- return the runtime/application façade.

## AssistantRuntime owns after Phase 5

- request handling and bounded submission;
- request-scoped context and planning coordination;
- validated-plan persistence and execution invocation;
- normal final task/result/message completion;
- in-process authorization/consent/action continuation identity and context;
- planning/execution cancellation delegation;
- session creation and execution/replan/recovery entry points.

It does not own planner strategies, DAG scheduling, capability execution,
response-composition policy, repository implementation, or operational maintenance.

## Compatibility boundary

`composition.Application`, `_ConversationCompatibilityFacade`, `PlanOrchestrator`,
and the `plan_executor` attribute remain compatibility surfaces. They delegate to
the canonical services and own no competing request/execution lifecycle. Their
retirement condition is migration of API/CLI and legacy callers in Phase 6 or the
later compatibility-removal phase.

Consent/action continuation is currently process-local. Plans and tasks survive a
restart, but authorization-ID mappings and the request context required to resume
do not. Restart-safe authorization continuation was not an established supported
contract, so this phase does not introduce a speculative schema or persistence
subsystem.

## Acceptance criteria

- **Passed:** a clear runtime/use-case boundary owns the outer request lifecycle.
- **Passed:** `composition.py` contains wiring and operational lifecycle, not the
  detailed request implementation.
- **Passed:** planning, execution, registry-backed capability resolution, DAG
  behavior, authorization, evidence, and response composition retain their
  existing canonical owners.
- **Passed:** normal final `TaskResult` persistence and task completion have one
  authoritative owner (`AssistantRuntime`, via `CompletionService`).
- **Passed:** no SQLite schema change or speculative manager abstraction was added.
- **Passed:** public behavior and bounded compatibility surfaces remain intact.
- **Passed:** targeted tests, 491-test deterministic suite, Ruff, strict MyPy,
  compilation, whitespace, concurrency, cancellation, and recovery gates pass.

Later phases are preserved below but remain subject to post-Phase-5 review.

---

# 10. Revised Phase 6 — Public API Boundary and Authorization Lifecycle Consolidation

## Objective

Make `EllyApplication` a thin public interface adapter and remove the remaining
authorization/task-lifecycle ownership collision between the API façade and
`AssistantRuntime`.

## Implemented work

- `AssistantRuntime.decide_consent` owns consent approval, denial, invalidation,
  cancellation while paused, exact-plan resume, audit emission, task result
  persistence, task completion, and continuation cleanup.
- `AssistantRuntime.decide_action` owns the equivalent consequential-action
  confirmation lifecycle and preserves the exact action target/digest boundary.
- Approval resumes the retained plan/step through
  `TaskExecutionService.resume_authorized_step`; it does not re-plan the request.
- Denial and cancellation dispatch no protected provider/action, persist one
  terminal result through `CompletionService`, emit the application audit event,
  and remove the process-local continuation.
- Concurrent decisions claim an authorization ID once; stale/replayed IDs fail
  safely after the runtime releases the continuation.
- The API retains only `_futures`, `_accepted_tasks`, `_outcomes`, and
  `_processed_futures` for interface-specific async publication. `_requests`,
  `_future_errors`, `_pending_submissions`, and `_pending_actions` were removed.
- API task cancellation and queued cancellation now delegate lifecycle writes to
  `AssistantRuntime`; query-side repository reads remain direct where no new
  use-case boundary is needed.
- No restart-safe continuation persistence, new SQLite table, durable future
  storage, workflow engine, or manager hierarchy was introduced.

## Acceptance criteria

- API façade delegates authorization and task lifecycle behavior.
- No duplicate authoritative task state exists in API and runtime layers.
- Consent/action approval, denial, replay, stale-ID, and paused-cancellation
  behavior remain safe and externally compatible.
- Existing local, research, specialist, DAG, idempotency, and public API tests
  remain passing, with focused Phase 6 persistence/cleanup coverage added.

---

# 11. Revised Phase 7 — Task Execution Decomposition and Legacy Execution Compatibility Isolation

## Objective

Physically separate the validated-plan execution implementation by cohesive
responsibility without rewriting the scheduler or changing runtime behavior.
`TaskExecutionService` remains the single public execution authority.

**Status: COMPLETE.** The full deterministic suite (494 tests), Ruff, strict
MyPy, compilation, and whitespace checks pass.

## Implemented structure

```text
application/task_execution/
  __init__.py       public execution exports and compatibility alias
  contracts.py      PlanExecutionRequest/Result contracts
  service.py        TaskExecutionService façade and active-run lifecycle
  plan_runner.py    DAG scheduling, bounds, transitions, cancellation
  step_runner.py    input resolution, registry dispatch, leases, persistence
  finalizer.py      aggregation-to-response-composition finalization
  legacy.py         isolated persisted LOCAL_SYNTHESIS compatibility

application/plan_executor.py
  documented compatibility re-export boundary only
```

The extraction moved the existing implementations without changing scheduling
ordering, worker bounds, timeout handling, cancellation propagation,
authorization pauses, compare-and-set transitions, operation leases, recovery,
or response-composition persistence. `AssistantRuntime` remains the normal
outer task-lifecycle owner.

## Legacy execution compatibility

- `PlanExecutor` and `PlanRunResult` remain documented aliases in the small
  `plan_executor.py` compatibility module because established tests and import
  paths still use them.
- `PlanOrchestrator` remains a compatibility façade and owns no execution
  state.
- `manage_task_lifecycle` remains available for direct/legacy callers; the
  canonical runtime path passes `False` and retains lifecycle ownership in
  `AssistantRuntime`.
- `LOCAL_SYNTHESIS` execution remains only for persisted/legacy plan and test
  compatibility; current planning uses post-aggregation response composition.
- Synthesis-named repository methods remain unchanged because they are the
  persistence compatibility boundary for stored records and response-
  composition observations.

## Explicit deferral

SQLite internal modularization is **not part of Revised Phase 7**. The SQLite
adapter, schema, migrations, transaction boundaries, and repository contracts
were intentionally left unchanged. SQLite modularization is deferred to the
next architectural review / expected Phase 8.

## Acceptance criteria

- Execution responsibilities are navigable through the small module set above.
- There is one scheduler and one canonical execution façade.
- Existing execution, authorization, recovery, persistence, and compatibility
  behavior remains covered by the deterministic suite.
- Required legacy persisted synthesis/result compatibility remains readable.
- No SQLite architecture or schema redesign is introduced.

---

# 12. Phase 8 — Split SQLite implementation internally (deferred)

## Objective

Reduce SQLite adapter file-level complexity without changing persistence
architecture. Begin only after a separate post-Revised-Phase-7 review.

## Work

Split the large adapter by cohesive storage concern while preserving one
database, one schema/versioning authority, current transactions, WAL/configuration
behavior, and repository contracts.

## Do not

- introduce SQLAlchemy;
- create a repository interface per table;
- create multiple DB connections with unclear transaction ownership;
- redesign schema unless required by an identified defect.

## Acceptance criteria

- Schema/migration code has one obvious owner.
- Transaction boundaries remain correct.
- Persistence tests pass.
- Existing stored databases remain readable/upgradable.
- Full suite passes.

---

# 13. Phase 9 — Consolidate routing and contract vocabulary

## Objective

Remove duplicate representations accumulated across versions.

## Direction

Prefer a conceptual flow like:

```text
UserRequest
 -> TaskIntent
 -> ExecutionPlan / capability selections
 -> StepResult
 -> TaskResult
 -> ResponseCompositionInput
```

## Work

- inventory route proposal / capability intent / task intent / selection proposal types;
- identify semantic duplicates;
- select canonical types;
- adapt at compatibility boundaries;
- remove internal aliases once no longer needed.

## Important

Do this **after** the main execution architecture is stable.

Renaming contracts early creates large diffs with little immediate architectural value.

## Acceptance criteria

- Fewer semantically equivalent contract types.
- Compatibility adaptation occurs at boundaries, not throughout the core.
- No loss of type safety.
- Full suite passes.

---

# 14. Phase 10 — Configuration and compatibility cleanup

## Objective

Remove stale migration-era configuration surface.

## Work

Inspect compatibility aliases such as:

- synthesis -> response composer;
- synthesis role;
- old provider-call-cost names;
- old planning-limit aliases;
- old generalist names.

For every alias:

- identify whether external config still uses it;
- preserve if necessary;
- document retirement condition;
- otherwise remove.

## Acceptance criteria

- Active configuration matches current architecture terminology.
- Legacy aliases are either removed or clearly isolated/documented.
- Config tests pass.
- Full suite passes.

---

# 15. Phase 11 — Test-suite consolidation and repository cleanup

## Objective

Keep behavior safety while reducing milestone-era architectural fossilization.

## Work

- retain high-value regression tests;
- consolidate duplicate V2/V2.5/V3/V3.5 behavior tests;
- prefer behavior/contract naming over milestone-phase naming for maintained tests;
- delete tests only when coverage is demonstrably redundant;
- remove generated package metadata such as committed `*.egg-info` if still tracked;
- clean stale milestone comments/documentation.

## Acceptance criteria

- Coverage of critical behavior is not reduced.
- Test intent is easier to understand.
- Generated artifacts are not committed.
- Static/test suite passes.

---

# 16. Required architecture tests after consolidation

The repository should explicitly test:

1. trivial request -> deterministic one-step plan;
2. complex request -> multi-step plan;
3. sequential dependencies execute in order;
4. independent ready steps may execute concurrently;
5. downstream step receives bounded upstream results;
6. unavailable capability is rejected before unsafe execution;
7. cyclic plan is rejected;
8. consent-required step pauses safely;
9. authorized continuation resumes safely;
10. cancellation propagates to running/pending work;
11. timeout produces correct task/step state;
12. recovery handles interrupted persisted plans;
13. bounded replan cannot escape policy constraints;
14. composer cannot change execution truth;
15. composer failure triggers deterministic fallback;
16. legacy persisted results remain readable;
17. local conversation uses the unified planning/execution path;
18. a plan can combine web + specialist + local reasoning capabilities;
19. public API and runtime report one authoritative task state.

---

# 17. Stop conditions

The agent must stop the current phase and report instead of continuing if:

- baseline tests fail for reasons not caused by the current work;
- migration compatibility cannot be proven;
- a change requires deleting security/authorization controls;
- there are contradictory authoritative contracts that require a product decision;
- the refactor would require a public breaking API change not authorized by the requirements;
- the agent cannot explain which component owns task lifecycle after its proposed change;
- the proposed change would create two active execution architectures again.

A stopped phase should include:

- blocker;
- evidence;
- files involved;
- safest options;
- recommendation.

---

# 18. Definition of done

The architectural cleanup is complete when an engineer can explain Elly's core runtime with approximately these concepts:

```text
AssistantRuntime
PlanningService
ExecutionPlan
TaskExecutionService
CapabilityRegistry
ResponseCompositionService
Persistence
```

with cross-cutting:

```text
privacy
authorization
guardrails/budgets
evidence
audit
```

Adding a new ordinary capability should generally require:

- capability implementation;
- contract/metadata registration;
- tests;

and should **not** require:

- a new orchestrator;
- a second runtime;
- a second task-state owner;
- a new final response pipeline.
