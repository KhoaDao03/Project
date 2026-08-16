# Elly V3 Phase 2 — Versioned Contracts and Local Planner

**Date:** 2026-08-16  
**Baseline:** Phase 1 independent local-model roles  
**Status:** Implemented and verified; Phase 3 validation and persistence are complete

## 1. Scope delivered

Phase 2 adds the advisory planning boundary required for V3. The local model
may return a typed proposal, but the proposal does not contain a provider,
handler, credential, consent, cost, authorization, or executable callback.
No capability is executed by this phase.

The implementation includes:

- immutable versioned proposal, proposed-step, plan-step, input-binding,
  limit-snapshot, finalization, plan-status, and step-state contracts;
- strict proposal JSON decoding and encoding with schema-version, unknown-field,
  identifier, newline, item-count, and byte-size validation;
- `LocalPlannerPort`, deterministic fake and recorded adapters, and a structured
  Ollama adapter bound only to the resolved `planner` local-model role;
- an immutable, deterministic, provider-free routing catalog projection for
  planner prompts; and
- `PlanInterpreter`, which revalidates proposals against a fresh live registry
  snapshot and returns local, clarification, single-capability, or bounded
  advisory multi-capability decisions.

## 2. Authority and data flow

The planner receives the request, approved bounded context, and minimized
routing metadata. It returns `ExecutionProposal`. `PlanInterpreter` then:

1. rejects provider-shaped identifiers, unknown capabilities, unavailable
   capabilities, unsupported operations, unsupported inputs, unauthorized
   verification markers, invalid references, and dependency cycles;
2. checks the proposal against a fresh V2.5 capability catalog; and
3. either returns a validated advisory decision or invokes the existing
   deterministic V2.5 router for a single-route fallback.

The fallback never synthesizes a multi-step plan. Capability execution,
authorization, and provider resolution remain owned by later phases and the
existing V2.5 workflow boundaries. Phase 3 now owns pure DAG construction,
redundancy policy, and atomic validated-plan persistence.

Planner justification is retained only as a bounded, single-line diagnostic.
The Ollama prompt explicitly forbids hidden reasoning and provider or
authorization decisions. Provider-specific model output is decoded at the
adapter boundary and does not escape as a provider-native object.

## 3. Implemented modules

| Area | Implementation |
| --- | --- |
| Contracts | `src/elly/planning/contracts.py` |
| Strict codec | `src/elly/planning/codec.py` |
| Safe catalog | `src/elly/planning/catalog.py` |
| Planner port | `src/elly/ports/local_planner.py` |
| Planner adapters | `src/elly/adapters/fake_planner.py`, `recorded_planner.py`, `ollama_planner.py` |
| Proposal validation | `src/elly/application/plan_interpreter.py` |
| Composition | `src/elly/composition.py` |

The composition root creates the fake or Ollama planner from
`config.planner_role`. Direct `Application` construction retains a deterministic
fake planner when no planner is supplied for compatibility with existing
embedded/test callers.

## 4. Verification

`tests/test_v3_phase2_local_planner.py` covers:

- strict round trips, unknown fields, malformed JSON, oversized output, unsafe
  IDs, dependency references, and immutable values;
- deterministic fake/recorded adapters, protocol conformance, and cancellation;
- sorted deterministic catalog views with no handler/provider/model metadata;
- local-only, clarification, single-capability, multi-capability, unavailable,
  unknown, provider-shaped, unsupported-operation, cycle, and verification cases;
- malformed and timed-out planner fallback without unvalidated multi-step output;
- fresh-catalog validation and zero capability execution; and
- structured Ollama request construction through a planner role using a patched
  transport boundary.

The focused Phase 2, Phase 1, and Phase 0 tests remain green after the Phase 3
contract extensions. The Phase 3 verification document records the current
pure validation and migration coverage. Ruff and strict Mypy availability is
reported by the repository-wide gate.

## 5. Deferred to later phases

Phase 2 intentionally does not execute a DAG, invoke capability authorization,
normalize step results, aggregate status, or synthesize final responses. Phase
3 constructs and persists only validated plans; Phase 4 owns scheduling and
capability execution.
