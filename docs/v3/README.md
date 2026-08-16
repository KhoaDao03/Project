# Elly V3 — Bounded Multi-Specialist Orchestration

**Status:** Completed and closed 2026-08-16  
**Baseline:** Closed V2.5 registry-driven routing

## Documents

1. [REQUIREMENTS.md](REQUIREMENTS.md) defines thirteen normative requirements
   for model-assisted proposals, capability-first plans, independently bound
   local-model roles, validated DAG execution, typed results, synthesis, aggregation,
   replanning, and provenance.
2. [TECHNICAL_DESIGN.md](TECHNICAL_DESIGN.md) analyzes the requirements and
   defines contracts, authority boundaries, scheduling, persistence, recovery,
   synthesis containment, and configuration migration.
3. [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) provides phased delivery,
   requirement traceability, test matrices, quality gates, and closure rules.
4. [PHASE_0_CONTRACT_FREEZE.md](PHASE_0_CONTRACT_FREEZE.md) records the Phase 0
   authority interpretation, V2.5 compatibility baseline, schema-v6 fixture,
   v3 contract vocabularies, and approved migration decisions.
5. [PHASE_1_LOCAL_MODEL_ROLES.md](PHASE_1_LOCAL_MODEL_ROLES.md) records the
   Phase 1 implementation, compatibility behavior, and verification evidence.
6. [PHASE_2_LOCAL_PLANNER.md](PHASE_2_LOCAL_PLANNER.md) records the Phase 2
   proposal contracts, planner adapters, catalog boundary, validation, and
   verification evidence.
7. [PHASE_3_PLAN_VALIDATION.md](PHASE_3_PLAN_VALIDATION.md) records pure DAG
   validation, redundancy control, schema-v7 persistence, and verification
   evidence.
8. [PHASE_4_EXECUTION.md](PHASE_4_EXECUTION.md) records the bounded dependency
   scheduler, persisted transitions, cancellation, limits, leases, and
   verification evidence.
9. [PHASE_5_AUTHORIZATION_RESULTS.md](PHASE_5_AUTHORIZATION_RESULTS.md) records
   execution-time plan-step authorization, derived-input classification,
   versioned result envelopes, receipt validation, and compatibility migration.
10. [PHASE_6_AGGREGATION_FINALIZATION.md](PHASE_6_AGGREGATION_FINALIZATION.md)
    records deterministic status aggregation, disagreement preservation,
    direct/template finalization, and additive plan/result views.
11. [PHASE_7_SYNTHESIS.md](PHASE_7_SYNTHESIS.md) records the bounded synthesis
    input/draft contracts, deterministic validation/rendering, local adapters,
    fallback behavior, and verification evidence.
12. [PHASE_8_REPLANNING_RECOVERY.md](PHASE_8_REPLANNING_RECOVERY.md) records the
    single-attempt replan policy, completed-step reuse, conservative restart
    recovery, safe provenance, and shared CLI views.
13. [PHASE_9_VERIFICATION.md](PHASE_9_VERIFICATION.md) records end-to-end
    scenarios, full quality gates, live local-model observations, and the
    explicitly deferred hosted-provider check.
14. [V3_CLOSURE.md](V3_CLOSURE.md) records owner-requested V3 closure and its
    accepted exception.

## Delivered outcome

Conversation, planning, and synthesis are independent configurable model roles.
They reuse the existing local Ollama profile by default, but any role can be
upgraded or replaced without changing the other two. Deterministic application
policy validates each proposed plan, authorizes each resolved step, dispatches
only registered capabilities, derives status, and validates final presentation.

V3 remains bounded: no recursive specialist delegation, model-owned authority,
open-ended debate, unlimited replanning, or cyclic execution is included.
