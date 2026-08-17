# Elly Architecture Refactor Packet

## Purpose

This packet is intended to be attached to or pasted into an AI coding agent before beginning the Elly architecture cleanup/refactor.

The goal is **not** to rewrite Elly. The goal is to simplify the current modular-monolith architecture, remove accumulated compatibility/runtime duplication, and converge the application on one clear execution model:

> **Every user request is planned. Most plans are trivial. Complex plans may combine multiple capabilities in a dependency graph.**

The target architecture is:

```text
CLI / Web / Mobile
        |
        v
    Public API
        |
        v
 AssistantRuntime
        |
        v
 PlanningService
        |
        v
   ExecutionPlan
        |
        v
 TaskExecutionService
        |
        v
 CapabilityRegistry
        |
        +--> local-model capabilities
        +--> web/research capabilities
        +--> specialist capabilities
        +--> future capabilities/tools
        |
        v
    Step Results
        |
        v
 ResponseCompositionService
        |
        v
    Final Answer
```

The capability branches above are **not mutually exclusive choices**. `PlanningService` may select one capability, several capabilities sequentially, several capabilities in parallel, or a combination of sequential and parallel work.

For example:

```text
web_research
     |
     +------------------+
     |                  |
     v                  v
stock_specialist   research_specialist
     |                  |
     +--------+---------+
              |
              v
      local_model_analysis
              |
              v
 ResponseCompositionService
```

## Files in this packet

1. `01_TARGET_ARCHITECTURE.md`
   - Defines the desired architecture, boundaries, data flow, invariants, and design rules.
   - Treat this as the architectural source of truth for the refactor.

2. `02_REFACTOR_ROADMAP.md`
   - Gives a staged refactoring sequence.
   - Includes objectives, expected changes, acceptance criteria, safety gates, and what not to combine.

3. `03_IMPLEMENTATION_AGENT_PROMPT.md`
   - A ready-to-use master prompt for the coding/refactoring agent.
   - Attach the target architecture and roadmap alongside it.

4. `04_REVIEW_AND_VERIFICATION_AGENT_PROMPT.md`
   - A separate prompt for a reviewer/verifier agent after each significant phase.
   - Intended to reduce the chance that the implementing agent validates its own architectural assumptions too generously.

## Recommended usage

For the implementation agent, provide:

- the current Elly repository;
- `01_TARGET_ARCHITECTURE.md`;
- `02_REFACTOR_ROADMAP.md`;
- `03_IMPLEMENTATION_AGENT_PROMPT.md`.

After each major structural phase, use a separate agent with:

- the updated repository;
- `01_TARGET_ARCHITECTURE.md`;
- the relevant completed phase from `02_REFACTOR_ROADMAP.md`;
- `04_REVIEW_AND_VERIFICATION_AGENT_PROMPT.md`.

## Refactor philosophy

The refactor must optimize for:

- one request lifecycle;
- one planning architecture;
- one execution authority;
- one final response-composition path;
- capability composition through a validated DAG;
- deterministic safety and authorization boundaries;
- clear ownership of runtime state;
- preservation of existing behavior unless the target architecture explicitly changes it;
- smaller conceptual surface area for future engineers and AI agents.

The refactor must **not** optimize for:

- minimizing class count for its own sake;
- adopting microservices;
- introducing an ORM;
- replacing SQLite;
- rewriting the application from scratch;
- deleting ports/adapters merely because they are abstractions;
- removing typed planning, persistence, authorization, privacy, evidence, audit, cancellation, or recovery behavior;
- forcing every trivial chat request through expensive agentic/LLM planning.

## Core architectural principle

> **One planning architecture, multiple planning depths.**

A trivial request should be able to produce a cheap deterministic one-step plan.

A genuinely complex request may invoke the local planner and produce a multi-step dependency graph.

Both requests still follow the same conceptual lifecycle:

```text
Request
  -> PlanningService
  -> ExecutionPlan
  -> TaskExecutionService
  -> capabilities
  -> ResponseCompositionService
  -> TaskResult / final response
```
