# Elly V2.5 Phase 0 — Approval and Characterization Record

**Date:** 2026-08-15  
**Baseline:** Closed V2 implementation  
**Status:** Completed; compatibility decisions applied by Phases 1–6  

> Final architecture note: the pre-closure refactor superseded the temporary
> active-compatibility decisions recorded here. See
> [LEGACY_ROUTING_REMOVAL.md](LEGACY_ROUTING_REMOVAL.md). Historical stored rows
> remain readable; legacy selection and presentation do not remain active.

## Scope disposition

Phase 0 originally authorized only characterization and compatibility work.
The owner subsequently authorized and implemented Phases 1–6. The decisions
below are therefore retained as the historical contract freeze and have been
applied by the completed V2.5 implementation.

## Compatibility decision

V2.5 will preserve the historical V2 `Route` enum values as a public
compatibility view. V2.5 will not require a new public `api/v3` solely for
registry-driven routing.

The intended migration shape is additive:

- new routing decisions may use a generic registered-capability category and
  carry capability ID and operation separately;
- existing V2 route values remain readable and renderable for historical tasks
  and existing interface clients;
- new public selection metadata must be optional/defaulted so existing V2
  clients continue to deserialize responses;
- historical rows are translated at the application boundary rather than
  rewritten in place.

This is the Phase 0 default because it preserves the closed V2 API and stored
task behavior while satisfying the V2.5 requirement that capability identity
not be encoded as the only generic routing mechanism. The decision should be
confirmed before Phase 1 contracts are finalized.

## Deferred design choices

The following choices are intentionally deferred to the phase that owns them:

| Decision | Phase | Default for planning |
| --- | --- | --- |
| Initial interpretation strategy | 1–2 | Deterministic catalog-aware interpretation first; model assistance remains optional and untrusted. |
| Domain, entity, operation, and freshness vocabulary | 1 | Use closed typed vocabularies validated at startup. |
| Ambiguity threshold and alternative count | 2 | Configure centrally and clarify semantic ties rather than using registry order. |
| Manifest versus Python routing contracts | 1–3 | Use typed contracts for core/web capabilities and derive specialist contracts from validated manifests. |
| Catalog/contract version persistence | 5 | Additive metadata, with exact replay requirements decided before migration. |

## Frozen V2 behavior

The following behavior is the compatibility baseline for later phases:

| Request shape | Current route | Current reason/behavior |
| --- | --- | --- |
| Timeless general question | `local_generalist` | `LOCAL_DEFAULT` |
| Current/news/live information | `web_research` | `CURRENT_INFORMATION_REQUIRED` |
| Explicit code review/debugging request | `coding_specialist` | `CODING_REQUEST` |
| Explicit research-specialist evidence request | `research_specialist` | `RESEARCH_SPECIALIST_REQUEST` |
| Underspecified specialist request | `local_generalist` | Typed clarification; no capability executes |
| Registered capability unavailable | Declared legacy route | `CAPABILITY_UNAVAILABLE`; execution is not allowed |
| Cloud disclosure awaiting approval | Existing route | `AWAITING_CONSENT`; cloud consent remains distinct |
| Consequential action awaiting approval | Existing route | `AWAITING_CONFIRMATION`; action confirmation remains distinct |

The approval states are intentionally separate: cloud consent cannot satisfy
action confirmation, and action confirmation cannot satisfy cloud consent.

## Characterized V2 seams

The Phase 0 tests deliberately record the current implementation seams that
later phases must remove or replace:

- `src/elly/application/intent.py` contains the legacy capability-operation
  mapping and capability-specific coding/research/web branches.
- `src/elly/application/routing.py` contains the fixed route-to-capability map
  and legacy route fallback behavior.
- `src/elly/composition.py` previously derived specialist routes from
  `manifest.role` and supplied legacy `coding` and `research` fallback handlers.

Phase 3 replaces that seam with manifest-declared routing operations and an
explicit compatibility route view. The historical route values remain only so
the V2 execution and presentation boundary can continue to operate until the
Phase 5 generic-route migration.

These are characterization assertions, not permissions for new code to depend
on the mappings. They should be updated only when the corresponding V2.5 phase
removes a seam and replaces its behavior with a generic contract.

## Phase 0 exit evidence

- Static source characterization was added for the capability literals and
  role-based composition branch.
- Route, clarification, unavailable-capability, and approval-state behavior is
  covered by deterministic tests and the existing V2 phase suites.
- No provider or network behavior is required for the Phase 0 tests.
- The full V2 regression suite remains the gate before Phase 1.
