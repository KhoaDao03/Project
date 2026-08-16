# Elly V2.5 — Registry-Driven Routing

**Status:** Completed and closed by owner decision on 2026-08-15  
**Baseline:** Closed V2 implementation  
**Theme:** Make conversational capability selection depend on the validated
runtime registry instead of centrally hard-coded capability identifiers.

## Documents

1. [REQUIREMENTS.md](REQUIREMENTS.md) — normative behavior and acceptance criteria.
2. [TECHNICAL_DESIGN.md](TECHNICAL_DESIGN.md) — proposed contracts, routing pipeline,
   safety boundaries, persistence impact, and historical-data strategy.
3. [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) — phased delivery, tests,
   migration sequence, and completion gates.
4. [PHASE_0_DECISIONS.md](PHASE_0_DECISIONS.md) — Phase 0 scope disposition,
   initial migration decision and frozen V2 baseline.
5. [PHASE_1_IMPLEMENTATION.md](PHASE_1_IMPLEMENTATION.md) — Phase 1 contract,
   catalog and validation record.
6. [PHASE_2_IMPLEMENTATION.md](PHASE_2_IMPLEMENTATION.md) — Phase 2 generic
   interpretation, matching, ranking, and selection validation.
7. [PHASE_3_IMPLEMENTATION.md](PHASE_3_IMPLEMENTATION.md) — manifest-driven
   specialist routing behavior.
8. [PHASE_4_IMPLEMENTATION.md](PHASE_4_IMPLEMENTATION.md) — web research
   operation contracts, freshness, and live-quote selection.
9. [PHASE_5_IMPLEMENTATION.md](PHASE_5_IMPLEMENTATION.md) — generic route
   categories, historical-row handling, and schema-v5 persistence metadata.
10. [PHASE_6_IMPLEMENTATION.md](PHASE_6_IMPLEMENTATION.md) — safe routing
    observability, interface parity, redaction, static boundaries, and cleanup.
11. [LEGACY_ROUTING_REMOVAL.md](LEGACY_ROUTING_REMOVAL.md) — final pre-closure
    removal of active V1/V2 route selection and compatibility presentation.
12. [V2_5_CLOSURE.md](V2_5_CLOSURE.md) — owner acceptance, verification basis,
    accepted boundary, and final milestone status.

## Intended outcome

Installing and enabling a valid capability or specialist makes it eligible for
conversational routing without editing the central intent interpreter, routing
policy, route enum, or composition root.

V2.5 changes discovery and selection, not authorization. Registry metadata may
describe what a capability supports, but it cannot grant cloud, provider, tool,
financial, file, shell, communication, or other side-effect authority.
