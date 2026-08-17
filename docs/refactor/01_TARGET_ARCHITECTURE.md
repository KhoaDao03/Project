# Elly Target Architecture Specification

## 1. Objective

Refactor Elly into a simpler modular monolith with one canonical request lifecycle and one canonical execution architecture.

The architecture should remain suitable for a local-first personal AI assistant that can:

- answer normal conversational questions;
- perform local reasoning;
- perform fresh web/research work;
- delegate to specialized agents/capabilities;
- combine multiple capability results;
- execute sequential and parallel work;
- enforce privacy, authorization, guardrails, budgets, and evidence requirements;
- persist recoverable task/plan state;
- compose a final user-facing answer from validated results.

The architecture must support future capabilities without requiring a new orchestration subsystem for each category.

---

# 2. Architectural thesis

The system should converge on this principle:

> **Everything is represented as a plan, but most plans should be simple.**

A plan may contain:

- one step;
- multiple sequential steps;
- multiple parallel steps;
- a dependency graph combining both.

The planner chooses the capabilities and dependencies.

The executor does **not** decide which capability category the task belongs to.

---

# 3. Target high-level architecture

```text
                    CLI / Web / Mobile
                           |
                           v
                      Public API
                           |
                           v
                  +------------------+
                  | AssistantRuntime |
                  +--------+---------+
                           |
                           v
                  +------------------+
                  | PlanningService  |
                  |------------------|
                  | intent           |
                  | capability match |
                  | plan generation  |
                  | plan validation  |
                  +--------+---------+
                           |
                           v
                     ExecutionPlan
                           |
                           v
              +--------------------------+
              | TaskExecutionService     |
              |--------------------------|
              | DAG scheduling           |
              | dependency handling      |
              | bounded parallelism      |
              | authorization pauses     |
              | cancellation             |
              | retries/recovery         |
              | persistence transitions  |
              | bounded replanning       |
              +------------+-------------+
                           |
                           v
                  +------------------+
                  |CapabilityRegistry|
                  +--------+---------+
                           |
          +----------------+------------------+
          |                |                  |
          v                v                  v
   local-model        web/research        specialists
   capabilities       capabilities        / tools
          |                |                  |
          +----------------+------------------+
                           |
                           v
                       StepResult
                           |
                           v
                  result aggregation
                           |
                           v
             +----------------------------+
             | ResponseCompositionService |
             +-------------+--------------+
                           |
                           v
                       TaskResult
                           |
                           v
                      Final Answer
```

## Important interpretation

The three capability families are a **toolbox**, not a router branch.

This is valid:

```text
web research
     |
     v
stock specialist
     |
     v
local reasoning
```

This is also valid:

```text
              web research
                  |
          +-------+-------+
          |               |
          v               v
  stock specialist   research specialist
          |               |
          +-------+-------+
                  |
                  v
          local reasoning
```

This is also valid:

```text
local conversation
```

The plan determines the graph.

---

# 4. Major architectural components

## 4.1 Public API

### Responsibility

Expose interface-neutral application operations to CLI, web, mobile, or future clients.

### Should own

- request/command DTO boundary;
- task/session identifiers returned to callers;
- translation between external API types and application use cases;
- querying task status/result;
- forwarding cancellation and authorization continuation commands.

### Should not own

- worker futures;
- scheduling;
- plan execution state;
- capability selection;
- planner logic;
- provider authority;
- authorization policy;
- response synthesis/composition policy.

The public API should be thin.

---

# 4.2 AssistantRuntime

### Responsibility

Act as the application-level runtime façade.

It should provide a small, coherent use-case surface such as:

- submit request;
- wait/query task;
- cancel task;
- continue after authorization/consent;
- manage session lifecycle;
- perform application startup/shutdown;
- expose maintenance operations when appropriate.

### Should own

- request handling and bounded submission;
- request-scoped context construction and planning invocation;
- persistence of validated plans before execution;
- invocation of `TaskExecutionService`;
- normal final task completion and `TaskResult`/assistant-message persistence;
- process-local authorization continuation identity and request context;
- cancellation delegation between planning and execution;
- session creation and references to the major services.

### Should not own

- detailed planner implementation;
- DAG scheduling;
- individual capability logic;
- result-composition logic;
- SQLite schema logic;
- duplicated task state already owned by the execution subsystem.

There should be one runtime authority, not one runtime in `composition.Application` and a second runtime in the API façade.

### Implemented Phase 5 boundary

`application.runtime.AssistantRuntime` is the canonical outer lifecycle owner.
`composition.Application` constructs it and retains narrow compatibility delegates;
the detailed request path no longer lives in the composition root. Composition
continues to own startup migration/recovery wiring, health, maintenance scheduling,
backup/profile operational wiring, and shutdown because these are process-level
composition concerns rather than request execution.

Normal final task completion and final `TaskResult` persistence occur once in
`AssistantRuntime` through `CompletionService`. The API callback only publishes
temporary API compatibility state. API-owned future/pending maps and explicit
consent/action denial completion remain bounded Phase 6 cleanup.

Authorization continuation currently survives only within the running process:
the runtime retains authorization ID to plan/step identity plus the request context
needed for exact resume. Persisted task and plan records survive restart, but this
continuation context does not, so a pending consent/action request cannot currently
be resumed after restart. No restart-safe continuation contract or schema is added
by Phase 5.

---

# 4.3 PlanningService

## Responsibility

Answer:

> **What bounded work should Elly perform for this request?**

It receives the user request plus the allowed application context and returns a validated immutable `ExecutionPlan`.

## Planning responsibilities

The service may:

1. interpret request intent;
2. inspect available capabilities;
3. select one or more capabilities;
4. determine step inputs;
5. define dependencies;
6. identify safe parallelism;
7. decide whether fresh information is required;
8. decide whether specialist expertise is justified;
9. determine authorization/privacy requirements through policy metadata;
10. construct the execution graph;
11. validate the graph before execution.

## Planning depth

Planning must support at least two internal depths.

### Deterministic fast path

Use for obvious/simple requests where an LLM planner adds little value.

Examples:

```text
"Hello"
    -> local_conversation

"Explain dependency injection"
    -> local_reasoning

"What is the latest NVIDIA price?"
    -> market/web freshness capability
```

This path should avoid unnecessary planner-model calls.

### Local LLM planner

Use when the task genuinely requires decomposition, dependency reasoning, or multiple capabilities.

Example:

```text
"Research NVIDIA's latest earnings, ask the stock specialist and
research specialist to evaluate them, then compare the conclusions."
```

Possible graph:

```text
web_research
     |
 +---+---+
 |       |
 v       v
stock   research
agent   agent
 |       |
 +---+---+
     |
     v
local_comparison
```

## Critical rule

The fast path and LLM planner are **implementation strategies inside PlanningService**.

They are not separate application architectures.

---

# 4.4 ExecutionPlan

The plan is the contract between planning and execution.

It should be typed, validated, and stable.

Conceptually it contains:

```text
ExecutionPlan
- plan_id
- task_id
- steps[]
- dependencies[]
- metadata / policy data
- version
```

Each step conceptually contains:

```text
PlanStep
- step_id
- capability_id
- operation_id
- bounded input
- dependency step ids
- execution/policy metadata
```

Exact field names may preserve existing repository contracts where reasonable.

Do not invent a new plan model merely to rename existing correct abstractions.

## Plan invariants

Before execution:

- every referenced capability exists;
- every operation is allowed for that capability;
- the dependency graph is acyclic;
- dependencies reference valid steps;
- step input is bounded and schema-valid;
- authorization/privacy requirements are represented;
- resource limits are bounded;
- the plan cannot grant itself permissions;
- the plan cannot bypass application-owned policy.

---

# 4.5 TaskExecutionService

## Responsibility

Answer:

> **How do I safely execute this already validated plan?**

It should be the single owner of task/plan execution lifecycle.

## It should own

- plan state transitions;
- dependency scheduling;
- bounded worker/concurrency management;
- deciding when a step is runnable based on dependencies;
- step execution lifecycle;
- cancellation;
- deadlines/timeouts;
- retries where policy allows;
- interrupted-run recovery;
- authorization/consent pause boundaries;
- operation leases if still needed;
- persistence of execution transitions;
- bounded replanning/recovery;
- finalization handoff.

## It should not own

- capability-selection policy;
- free-form planner reasoning;
- presentation wording;
- public API state duplication;
- provider registration;
- database schema migration definitions.

## Suggested internal decomposition

Do **not** replace one giant executor with fifteen tiny classes.

A reasonable internal shape is:

```text
TaskExecutionService
    |
    +-- PlanRunner
    |
    +-- StepRunner
    |
    +-- PlanFinalizer
```

### PlanRunner

Owns:

- DAG readiness;
- worker scheduling;
- concurrency;
- transitions;
- cancellation propagation;
- task completion detection.

### StepRunner

Owns:

- one bounded step execution;
- capability lookup;
- input preparation;
- authorization boundary;
- timeout/retry wrapper;
- step result normalization/persistence.

### PlanFinalizer

Owns:

- collecting terminal results;
- aggregation;
- task-level status;
- handoff to response composition;
- deterministic fallback behavior if composition fails.

If the existing code can achieve these boundaries with fewer public classes, prefer fewer.

---

# 4.6 CapabilityRegistry

## Responsibility

Define what bounded executable capabilities are available.

Capabilities may include:

```text
conversation.respond
reasoning.analyze
research.search
market.lookup
specialist.coding
specialist.research
specialist.stock
```

Future examples:

```text
github.*
calendar.*
email.*
filesystem.*
browser.*
image.*
voice.*
```

## Important rule

The execution layer should not need special orchestration code for each family.

The registry should expose enough metadata for planning and execution to determine:

- supported operations;
- input/output contract;
- privacy class;
- authorization needs;
- freshness characteristics;
- execution resource class;
- whether network/cloud access is used;
- capability availability.

The registry should not become a service locator for unrelated application objects.

---

# 4.7 Capability implementations

A capability performs bounded work.

Examples:

### Local model capability

May perform:

- conversation;
- analysis;
- comparison;
- transformation;
- reasoning over previous step results.

This is different from final response composition.

### Web/research capability

May perform:

- web search;
- fresh-data retrieval;
- source collection;
- evidence normalization.

### Specialist capability

May perform:

- coding analysis;
- financial/stock analysis;
- research review;
- other domain-specialized bounded tasks.

A single plan may use any combination.

---

# 4.8 ResponseCompositionService

## Responsibility

Answer:

> **How should trusted/validated execution results become the final user-facing response?**

It is presentation-oriented, not an execution authority.

## It may

- combine relevant step outputs;
- remove duplication;
- present disagreements;
- preserve evidence/citations;
- apply tone/personality presentation rules;
- generate a coherent answer using a local composer model;
- fall back to deterministic assembly if the composer fails.

## It must not

- call arbitrary capabilities on its own;
- alter execution truth;
- fabricate successful steps;
- override authorization;
- silently discard critical warnings;
- transform a failed task into a successful task;
- become another planner.

## Local reasoning vs response composition

These are separate roles even if both physically use the same local model.

```text
local reasoning capability
    = performs task reasoning/work

ResponseCompositionService
    = presents already produced results
```

---

# 4.9 Persistence

Keep SQLite.

The goal is to simplify module organization, not redesign storage.

Persistence should remain responsible for durable data such as:

- sessions/messages;
- tasks;
- plans;
- steps/dependencies;
- step results;
- claims/evidence;
- authorizations/operations where currently required;
- profile/config-related durable state;
- audit/provenance.

The existing monolithic SQLite adapter may be split internally by concern without introducing:

- an ORM;
- multiple databases;
- distributed persistence;
- repository interfaces for every table.

Suggested implementation organization:

```text
adapters/sqlite/
    store.py
    schema.py
    sessions.py
    tasks.py
    plans.py
    profile.py
    audit.py
```

Exact module names are flexible.

Preserve one DB ownership model.

---

# 5. Cross-cutting policy

These concerns are required across the architecture:

- privacy classification;
- user consent;
- action authorization;
- guardrails;
- provider/tool budgets;
- concurrency limits;
- deadlines/cancellation;
- evidence/citation integrity;
- audit/provenance;
- deterministic validation.

These policies should remain application-owned.

The planner may propose work.

It may not grant itself authority to perform that work.

---

# 6. Canonical request lifecycle

## 6.1 Trivial request

```text
User
 |
 v
AssistantRuntime
 |
 v
PlanningService
 |
 +-- deterministic fast path
 |
 v
ExecutionPlan:
  [local_conversation]
 |
 v
TaskExecutionService
 |
 v
CapabilityRegistry -> local capability
 |
 v
StepResult
 |
 v
ResponseCompositionService
 |
 v
Final Answer
```

No expensive LLM planner is required.

---

# 6.2 Sequential multi-capability request

```text
PlanningService
 |
 v
ExecutionPlan:
  A web_research
  B stock_analysis depends_on A
  C local_reasoning depends_on B
```

Execution:

```text
A -> B -> C -> composition
```

---

# 6.3 Parallel request

Plan:

```text
A web_research
B stock_specialist depends_on A
C research_specialist depends_on A
D local_compare depends_on B,C
```

Execution:

```text
        A
      /   \
     B     C
      \   /
        D
        |
  composition
```

The executor is responsible for recognizing that B and C may run concurrently after A succeeds.

---

# 7. Data/contract simplification direction

Do not perform a destructive contract rewrite early.

The desired long-term vocabulary is approximately:

```text
UserRequest
    |
    v
TaskIntent
    |
    v
ExecutionPlan
    |
    v
PlanStep
    |
    v
StepResult
    |
    v
TaskResult
    |
    v
ResponseCompositionInput
```

Where the current system already has a sound equivalent, reuse it.

Avoid simultaneously maintaining several semantically equivalent objects such as multiple route proposal / capability selection / intent models unless compatibility requires it.

Compatibility aliases should have explicit retirement conditions.

---

# 8. Ownership rules

The finished architecture should have clear answers to these questions.

| Question | Owner |
|---|---|
| Who accepts a user command? | Public API / AssistantRuntime |
| Who decides what work is needed? | PlanningService |
| Who validates the plan? | PlanningService + deterministic validator |
| Who runs the plan? | TaskExecutionService |
| Who determines step readiness? | TaskExecutionService / PlanRunner |
| Who executes one step? | StepRunner / capability |
| Who provides available operations? | CapabilityRegistry |
| Who grants authorization? | Application-owned authorization/policy |
| Who requests validated-plan persistence? | AssistantRuntime |
| Who owns normal final task completion/result persistence? | AssistantRuntime via CompletionService |
| Who persists task/plan state physically? | Persistence adapter behind repository ports |
| Who persists assistant messages? | AssistantRuntime through SessionRepositoryPort |
| Who retains authorization continuation? | AssistantRuntime (process-local) |
| Who coordinates planning/execution cancellation? | AssistantRuntime delegates to each canonical service |
| Who recovers interrupted work? | TaskExecutionService |
| Who performs bounded replan/recovery? | Planning/execution recovery boundary |
| Who writes the final answer? | ResponseCompositionService |
| Who owns user-facing task truth? | Application/task lifecycle, not composer |

No two components should independently own the same task lifecycle state.

---

# 9. Architectural invariants

The refactor is complete only if these are true.

1. Normal conversation and complex agentic tasks use the same conceptual request lifecycle.
2. `ConversationOrchestrator` is no longer a peer orchestration architecture.
3. Local conversation/reasoning is represented as a capability or equivalent execution step.
4. `PlanningService` may choose any combination and order of capabilities.
5. `TaskExecutionService` executes the supplied graph; it does not perform high-level capability selection.
6. One component owns execution state.
7. There is one active final response-composition path.
8. Legacy persisted data may remain readable without keeping obsolete runtime behavior active.
9. Privacy/authorization cannot be bypassed by a planner-produced plan.
10. Simple requests do not require expensive agentic planning.
11. Existing deterministic tests remain passing or are deliberately replaced with equivalent behavior-level tests.
12. The code remains a modular monolith.
13. SQLite remains the durable store unless a future requirement explicitly changes that decision.
14. New capabilities can normally be added through the registry/contracts rather than a new orchestrator.

---

# 10. Deliberate non-goals

Do not do the following as part of this cleanup unless a discovered correctness issue forces it:

- microservices;
- event bus architecture;
- distributed queues;
- Kubernetes;
- ORM migration;
- database replacement;
- plugin framework rewrite;
- dependency-injection framework adoption;
- generic workflow-engine extraction;
- generic agent framework adoption;
- elimination of all classes;
- wholesale domain-model renaming;
- new hosted providers;
- feature expansion unrelated to architecture cleanup.

---

# 11. Design heuristic for future work

For every new abstraction, ask:

1. Does it represent a genuinely distinct responsibility?
2. Does it remove more complexity than it adds?
3. Will at least two concrete use cases benefit from it soon?
4. Does it duplicate an existing generation of the same concept?
5. Can an existing module be simplified instead?
6. What older abstraction can be retired when this one is introduced?

Prefer architecture that allows Elly to grow by adding capabilities, not by adding orchestration systems.
