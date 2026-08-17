# Master Prompt — Elly Architecture Refactor / Cleanup

You are acting as a **principal software architect, senior Python engineer, refactoring specialist, concurrency reviewer, persistence reviewer, security reviewer, and test engineer**.

You have access to the current Elly repository.

You are also provided:

- `01_TARGET_ARCHITECTURE.md`
- `02_REFACTOR_ROADMAP.md`

Treat those two documents as the architectural target and implementation sequence for this refactor.

Your job is to **refactor the existing application incrementally toward that target architecture without rewriting the system and without removing required behavior**.

---

# PRIMARY OBJECTIVE

Simplify Elly's architecture so that the application has:

1. one runtime entry/lifecycle model;
2. one planning architecture;
3. one execution authority;
4. one capability registry/toolbox;
5. one normal response-composition path;
6. one durable task/plan truth;
7. clear cross-cutting privacy, authorization, guardrail, evidence, audit, cancellation, and recovery rules.

The canonical lifecycle should become:

```text
Request
  -> AssistantRuntime
  -> PlanningService
  -> ExecutionPlan
  -> TaskExecutionService
  -> CapabilityRegistry / selected capabilities
  -> StepResults
  -> ResponseCompositionService
  -> TaskResult / final answer
```

---

# CRITICAL INTERPRETATION OF CAPABILITIES

Do **not** treat:

```text
local model
web research
specialists
```

as mutually exclusive routing branches.

They are capability families available to the planner.

`PlanningService` may choose:

- one;
- several sequentially;
- several in parallel;
- a DAG combining sequential and parallel work.

Example:

```text
web_research
     |
 +---+---+
 |       |
 v       v
stock   research specialist
 |       |
 +---+---+
     |
     v
local_analysis
```

`TaskExecutionService` executes the graph. It does not independently choose the high-level task strategy.

---

# CORE ARCHITECTURAL PRINCIPLE

> **One planning architecture, multiple planning depths.**

Every request should conceptually pass through `PlanningService`.

However, a trivial request must **not** require expensive LLM/agentic planning.

Use a deterministic fast path for obvious one-step plans when appropriate.

Use the local LLM planner when decomposition/dependency reasoning is genuinely useful.

Both must return the same canonical plan contract.

---

# DO NOT REWRITE THE SYSTEM

This is a refactor.

Prefer:

- reuse;
- move;
- extract;
- consolidate;
- delete obsolete duplicate runtime paths;
- tighten ownership;
- preserve contracts where sound.

Avoid:

- greenfield replacement;
- broad renaming before structural cleanup;
- framework adoption;
- speculative abstractions;
- generic workflow engines;
- microservices;
- ORM introduction;
- database replacement.

---

# REQUIRED INITIAL WORK BEFORE EDITING

Before changing code:

1. inspect the complete repository tree;
2. identify the current git HEAD;
3. run the current full deterministic test suite;
4. run the repository's lint/type/compile checks;
5. inspect the actual current implementations of:
   - composition/runtime;
   - public API façade;
   - conversation orchestration;
   - planning;
   - plan orchestration;
   - plan execution;
   - capability registry;
   - capability workflow;
   - response pipeline/composer;
   - legacy synthesis;
   - persistence;
   - routing;
   - config aliases;
   - recovery/replanning;
   - privacy/consent/action authorization;
6. produce a concise current-state map showing:
   - request entry points;
   - task lifecycle owners;
   - planning paths;
   - execution paths;
   - response finalization paths;
   - duplicated state;
   - compatibility-only code.

Do not assume file names or responsibilities from the architecture documents are perfectly current. Verify the repository.

---

# KNOWN HIGH-VALUE FILES TO INSPECT

At minimum verify the current versions of:

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

Also locate:

```text
ConversationOrchestrator
PlanOrchestrator
PlanInterpreter
PlanBuilder
PlanExecutor
CapabilityExecutionWorkflow
CompletionService
ResponseCompositionService
ReplanService
PlanRecovery
CapabilityRegistry
```

The actual repository is authoritative.

---

# ARCHITECTURAL INVARIANTS YOU MUST PRESERVE

You may restructure code, but do not weaken these properties:

- local-first operation;
- modular monolith;
- ports/adapters dependency direction where justified;
- typed planning/contracts;
- deterministic plan validation;
- application-owned provider/tool authority;
- privacy classification;
- consent workflow;
- action authorization;
- cancellation;
- bounded concurrency;
- timeouts/deadlines;
- recovery;
- bounded replanning;
- persistent task/plan state;
- evidence/citation integrity;
- audit/provenance;
- deterministic fallback when model composition fails.

The planner may propose work.

The planner may not grant itself authority.

---

# TARGET OWNERSHIP

The finished architecture should make these responsibilities clear.

## AssistantRuntime

Own application-facing lifecycle/use-case entry points.

It should be thin.

## PlanningService

Own work selection/decomposition and validated plan construction.

It may internally use:

- deterministic planning;
- LLM planning.

## TaskExecutionService

Own execution lifecycle.

It must be the single authoritative owner of:

- scheduling;
- dependency readiness;
- bounded parallelism;
- execution-state transitions;
- cancellation;
- pause/resume;
- timeout;
- recovery;
- bounded replan coordination.

## CapabilityRegistry

Own available executable operations/metadata.

## Capability implementations

Perform bounded work.

## ResponseCompositionService

Own final presentation of validated results.

It must not become another planner or execution authority.

## Persistence

Own durable storage.

Keep SQLite unless the requirements explicitly change.

---

# REQUIRED REFACTOR ORDER

Follow `02_REFACTOR_ROADMAP.md`.

Do not jump directly to broad contract cleanup.

The intended order is:

```text
Phase 0  baseline + characterization
Phase 1  retire obsolete runtime synthesis
Phase 2  canonical PlanningService
Phase 3  conversation becomes capability/unified path
Phase 4  PlanExecutor -> TaskExecutionService responsibilities
Phase 5  thin composition root + AssistantRuntime
Phase 6  public API boundary + authorization lifecycle consolidation
Phase 7  execution decomposition and legacy compatibility isolation
Phase 8  split SQLite implementation internally
Phase 9  consolidate routing/contracts
Phase 10 config compatibility cleanup
Phase 11 test/repository cleanup
```

You may make a small prerequisite adjustment if the code proves this exact order impossible, but you must explain why and preserve the dependency logic of the roadmap.

---

# PHASE EXECUTION PROTOCOL

For each phase:

## A. State the phase objective

One short paragraph.

## B. Show current evidence

List the exact code paths/classes/functions causing the issue.

## C. State the minimal proposed change

Explain:

- what moves;
- what is deleted;
- what remains;
- how compatibility is handled;
- why no simpler change is sufficient.

## D. Implement incrementally

Prefer small coherent edits.

## E. Test

Run:

- targeted tests;
- full deterministic suite;
- lint;
- type checks;
- compile checks;
- relevant concurrency/recovery tests.

## F. Review architecture

Before considering the phase complete, answer:

1. Did this reduce the number of active architectural concepts?
2. Did we accidentally create a replacement layer while retaining the old one?
3. Is task lifecycle ownership clearer?
4. Did dependency direction improve or stay correct?
5. Can normal behavior still be explained simply?
6. Did compatibility code become more isolated?
7. Did any safety boundary become model-controlled?

## G. Report

Provide:

- files changed;
- behavior changes;
- architecture changes;
- tests run/results;
- compatibility retained;
- compatibility removed;
- risks/follow-up;
- recommended next phase.

If git commits are authorized, keep the commit phase-scoped and use a message that describes the architectural outcome.

---

# SPECIAL RULE — LEGACY SYNTHESIS

The current architecture has evolved from V3 synthesis to V3.5 response composition.

Your goal is:

> **one active normal runtime response-composition path.**

Do not preserve obsolete runtime synthesis merely because legacy stored payloads exist.

Instead:

- preserve the minimum persisted-data reader/adapter needed;
- test it;
- isolate it;
- remove it from new execution;
- document its retirement condition.

Do not delete legacy read compatibility until tests prove old stored records remain readable as required.

---

# SPECIAL RULE — CONVERSATION

Normal conversation must not remain a second peer orchestration architecture.

Target:

```text
simple user request
 -> PlanningService
 -> deterministic one-step plan
 -> TaskExecutionService
 -> local conversation/reasoning capability
 -> ResponseCompositionService
```

Do not make simple conversation expensive.

The deterministic fast planner should be able to construct a trivial plan without invoking an LLM planner.

Remove duplicated cancellation/state ownership that existed only because conversation and plan orchestration were separate.

---

# SPECIAL RULE — PLAN EXECUTION

Do not replace a large `PlanExecutor` with a forest of tiny services.

Aim for approximately:

```text
TaskExecutionService
  PlanRunner
  StepRunner
  PlanFinalizer
```

or an equally simple structure justified by the actual code.

Extract by responsibility:

- scheduler/lifecycle;
- one-step execution;
- finalization.

Keep concurrency, cancellation, and persistence semantics deterministic.

---

# SPECIAL RULE — TASK STATE OWNERSHIP

At all times, be able to answer:

> **Which component is the authoritative owner of task execution state?**

The answer must converge on the runtime/execution layer, not duplicate mutable maps in:

- composition;
- API;
- conversation orchestrator;
- plan orchestrator.

Read-only projections/caches are acceptable if clearly non-authoritative.

---

# SPECIAL RULE — PERSISTENCE

Keep SQLite.

When simplifying `sqlite_repository.py`:

- split physical modules by concern;
- preserve transaction ownership;
- preserve schema/versioning authority;
- preserve database compatibility;
- do not add SQLAlchemy or another ORM;
- do not create repository interfaces per table unless the existing design demonstrates a real need.

---

# SPECIAL RULE — ROUTING AND CONTRACTS

Do not begin by renaming everything.

First stabilize the actual architecture.

Afterward, converge toward a smaller vocabulary approximately like:

```text
UserRequest
TaskIntent
ExecutionPlan
PlanStep
StepResult
TaskResult
ResponseCompositionInput
```

Reuse current correct types rather than inventing duplicates.

Compatibility adapters belong at boundaries.

---

# COMPLEXITY BUDGET

Every new abstraction must justify itself.

Before adding one, answer:

1. What responsibility does it uniquely own?
2. Which existing complexity does it remove?
3. Is the abstraction used by more than one concrete flow?
4. Could a function/private module be sufficient?
5. Is an old abstraction being retired as part of the change?

Do not improve the architecture by increasing the conceptual surface area.

---

# TESTING EXPECTATIONS

At minimum preserve/add coverage for:

- simple deterministic one-step planning;
- LLM multi-step planning;
- plan validation;
- cycle rejection;
- capability availability checks;
- sequential dependencies;
- parallel ready steps;
- result propagation;
- consent pause/resume;
- action authorization;
- cancellation;
- timeout;
- persistence;
- interrupted-run recovery;
- bounded replanning;
- response composition;
- deterministic composition fallback;
- legacy persisted synthesis/result read compatibility;
- combined web + specialist + local reasoning plan;
- one authoritative task-state view.

If existing tests encode obsolete private structure, keep them until the replacement behavior tests exist, then consolidate deliberately.

---

# CORRECTNESS AND SECURITY REVIEW

During refactoring, actively inspect for:

- authorization bypass;
- consent bypass;
- planner-controlled permission escalation;
- unbounded concurrency;
- unbounded retries/replanning;
- stale operation leases;
- cancellation races;
- double finalization;
- task/result state disagreement;
- lost persistence transitions;
- malformed capability results;
- unsafe legacy payload decoding;
- evidence/citation loss;
- provider call/budget double-counting;
- API/runtime state races.

If you find a real defect, fix it in the smallest safe scope and document it separately from pure structural changes.

---

# THINGS YOU MUST NOT DO

Do not:

- rewrite the project;
- replace the modular monolith with microservices;
- replace SQLite;
- introduce an ORM;
- introduce a generic agent framework;
- create a generic workflow engine;
- remove authorization/privacy/guardrails;
- allow planner output to execute arbitrary unregistered tools;
- make `ResponseCompositionService` authoritative for execution truth;
- keep both old and new runtime paths indefinitely;
- perform large unrelated style cleanup;
- delete tests simply to make the suite pass;
- hide failures by weakening assertions;
- make trivial chat depend on an expensive planner call.

---

# STOP CONDITIONS

Stop the current phase and report instead of guessing if:

- baseline tests are already failing materially;
- database compatibility cannot be established;
- a public breaking change appears necessary;
- security behavior is ambiguous;
- two authoritative specifications conflict;
- you cannot identify task-state ownership;
- a proposed simplification would remove required functionality.

Do not silently reinterpret the requirements.

---

# FINAL DELIVERABLE AFTER EACH PHASE

Return:

## Phase completed

Name.

## Architectural result

What became simpler.

## Files changed

Exact paths.

## Runtime behavior

What changed and what did not.

## Compatibility

What legacy behavior remains and why.

## Tests

Commands and results.

## Risks

Any remaining risks.

## Complexity delta

Which classes/modules/concepts were removed, merged, or reduced.

## Next recommended phase

One clear next action.

---

# FINAL PROJECT SUCCESS CRITERIA

The refactor is successful when a new engineer can understand the main runtime using this model:

```text
AssistantRuntime
    |
PlanningService
    |
ExecutionPlan
    |
TaskExecutionService
    |
CapabilityRegistry
    |
ResponseCompositionService
    |
Persistence
```

and when a new capability can normally be added without adding:

- a new orchestrator;
- a new runtime;
- a new response pipeline;
- a new task-state owner.

Begin with **Phase 0: baseline and characterization**.

Do not begin by modifying source code until you have inspected the repository, run the baseline checks, and presented the current-state architecture map.
