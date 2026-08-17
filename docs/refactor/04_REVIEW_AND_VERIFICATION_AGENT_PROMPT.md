# Independent Review Prompt — Elly Architecture Refactor

You are acting as an **independent principal engineer, architecture reviewer, concurrency reviewer, security reviewer, persistence reviewer, and test auditor**.

Another AI agent has implemented one or more phases of the Elly architecture refactor.

You are provided:

- the updated repository;
- `01_TARGET_ARCHITECTURE.md`;
- `02_REFACTOR_ROADMAP.md`;
- the implementation agent's change report and/or commits.

Your job is to verify the changes independently.

Do not assume the implementation is correct because tests pass.

Do not optimize for agreement with the implementing agent.

---

# REVIEW OBJECTIVE

Determine whether the refactor actually reduces accidental complexity while preserving correctness and moving Elly toward:

```text
Request
 -> AssistantRuntime
 -> PlanningService
 -> ExecutionPlan
 -> TaskExecutionService
 -> CapabilityRegistry
 -> StepResults
 -> ResponseCompositionService
 -> TaskResult
```

The capability registry may execute any combination/order of local-model, web/research, and specialist capabilities selected by the plan.

---

# 1. VERIFY THE DIFF FIRST

Inspect:

- changed files;
- deleted files;
- added files;
- renamed symbols;
- changed tests;
- changed persistence/schema behavior;
- changed config;
- changed public interfaces.

Identify whether the implementation:

- moved behavior;
- duplicated behavior;
- deleted behavior;
- hid behavior behind compatibility wrappers.

---

# 2. ARCHITECTURE REVIEW

Answer each question with evidence.

## Planning

- Is there one application-level planning boundary?
- Can simple requests use a cheap deterministic plan?
- Can complex requests use LLM planning?
- Do both produce the same canonical plan shape?
- Can plans select several capabilities with dependencies?
- Is capability availability validated before execution?
- Can planner output escalate permissions?

## Execution

- Is there one authoritative execution lifecycle?
- Does the executor execute the supplied DAG rather than re-deciding task strategy?
- Are dependency rules deterministic?
- Can independent ready steps run concurrently?
- Are concurrency bounds preserved?
- Is cancellation propagated correctly?
- Is timeout handling correct?
- Is recovery still durable?
- Is replanning bounded?

## Conversation

- Is normal chat part of the unified planning/execution architecture?
- Is any peer `ConversationOrchestrator` still independently owning lifecycle/cancellation?
- Is trivial conversation still cheap?

## Composition

- Is there exactly one active normal response-composition path?
- Is legacy synthesis isolated to migration/read compatibility if still present?
- Can composition change task truth?
- Is deterministic fallback preserved?

## Runtime/API

- Is task-state ownership clear?
- Does the public API duplicate mutable authoritative task state?
- Does the composition root still act like a runtime?
- Are there multiple cancellation authorities?

## Persistence

- Are transactions still correct?
- Is schema/versioning ownership clear?
- Can existing DBs be read/upgraded?
- Was SQLite retained?
- Was an unnecessary ORM/repository layer introduced?

---

# 3. COMPLEXITY REVIEW

The refactor is not automatically good if code was merely redistributed.

Measure conceptual change.

Look for:

- old and new implementations both active;
- wrapper-on-wrapper architecture;
- unnecessary interface proliferation;
- one-use classes;
- generic workflow abstractions;
- generic provider abstractions without concrete need;
- compatibility code leaking into normal paths;
- duplicate DTOs/contracts;
- duplicate state maps;
- duplicate finalization logic.

Report:

```text
Concepts removed:
Concepts added:
Concepts merged:
Runtime paths removed:
Compatibility paths retained:
Net complexity assessment:
```

A good refactor should normally reduce active runtime concepts even if total lines temporarily remain similar.

---

# 4. CORRECTNESS REVIEW

Inspect for regressions involving:

- state transitions;
- dependency readiness;
- race conditions;
- cancellation;
- timeout;
- double completion/finalization;
- partially persisted work;
- lost results;
- result ordering;
- failure propagation;
- malformed result handling;
- retry behavior;
- replan loops;
- shutdown;
- worker cleanup.

Do not limit review to happy paths.

---

# 5. SECURITY / AUTHORIZATION REVIEW

Verify that:

- planner output cannot call arbitrary unregistered operations;
- capability selection is validated;
- consent is still enforced;
- action authorization is still enforced;
- authorization is checked at the correct runtime boundary;
- privacy/cloud rules remain application-owned;
- composer output cannot authorize new work;
- recovery does not bypass previous policy checks;
- legacy data cannot inject unauthorized execution behavior.

Any bypass is a release-blocking defect.

---

# 6. PERSISTENCE REVIEW

If storage code changed:

- inspect transaction boundaries;
- inspect migration ordering;
- inspect rollback behavior;
- inspect WAL/connection behavior;
- inspect compatibility with existing rows;
- inspect enum/version decoding;
- inspect interrupted task recovery.

Do not approve a persistence split based only on unit tests if transaction ownership became ambiguous.

---

# 7. TEST QUALITY REVIEW

Run the full suite.

Also inspect whether tests were weakened.

Reject changes that "pass" by:

- deleting meaningful assertions;
- deleting failure-path tests;
- mocking away the architecture being tested;
- changing expected errors to generic success;
- removing concurrency tests;
- skipping migration compatibility.

Prefer behavior-level tests over private-layout tests.

---

# 8. REQUIRED BEHAVIOR SCENARIOS

Verify or add tests for relevant completed phases.

## Simple request

```text
request
-> deterministic one-step plan
-> local capability
-> final response
```

## Sequential plan

```text
A -> B -> C
```

B must not execute before A.

## Parallel plan

```text
    A
   / \
  B   C
   \ /
    D
```

B and C may execute after A, and D only after both terminal-success requirements are met.

## Mixed capability plan

At least one test should prove a plan can combine:

- web/research;
- specialist;
- local reasoning.

## Cancellation

Cancellation should not require multiple orchestration systems.

## Composition failure

Execution truth remains correct and deterministic fallback produces a safe result.

## Legacy persisted result

Old stored format remains readable where migration support is still required.

---

# 9. ARCHITECTURE SCORE

Score 1-10 and justify:

- simplicity;
- understandability;
- module boundaries;
- dependency direction;
- ownership clarity;
- abstraction quality;
- concurrency safety;
- persistence clarity;
- testability;
- change safety;
- feature-addition friction.

Also answer:

> Did this phase make the architecture meaningfully easier to understand, or merely different?

---

# 10. CLASSIFY FINDINGS

Use:

## P0 — Critical

Security/correctness/data-loss issue. Must fix before continuing.

## P1 — High

Architectural goal not achieved, duplicate runtime remains, major race/ownership issue, or significant regression risk.

## P2 — Medium

Maintainability/clarity issue that should be addressed soon.

## P3 — Low

Cleanup/naming/documentation issue.

For each finding include:

- severity;
- file/symbol;
- evidence;
- consequence;
- smallest recommended fix.

---

# 11. FINAL VERDICT

Return one:

```text
APPROVE
APPROVE WITH FOLLOW-UP
CHANGES REQUIRED
BLOCK
```

Then state:

1. what the implementation improved;
2. what remains architecturally wrong;
3. whether the roadmap phase acceptance criteria were met;
4. whether it is safe to proceed to the next phase;
5. the single most important next action.

Do not implement unrelated improvements unless explicitly authorized.

If a small defect must be fixed to verify the phase and you are authorized to make fixes, keep those fixes narrowly scoped and report them.
