# Elly V2.5 Phase 2 — Generic Matcher and Selector

> Final architecture note: the fixed V2 fallback described below was
> transitional and was removed before closure. See
> [LEGACY_ROUTING_REMOVAL.md](LEGACY_ROUTING_REMOVAL.md).

**Status:** Implemented
**Baseline:** Phase 1 typed contracts and immutable catalog
**Scope:** Capability-neutral interpretation, deterministic matching, ranking,
and live-catalog selection validation

## Delivered

- Added `CatalogIntentInterpreter`, which extracts bounded entities, freshness,
  expected action effect, domain evidence, and operation evidence without
  naming a built-in optional capability.
- Added `CatalogCandidateSelector`, including structured candidate evidence,
  lexicographic ranking, configurable ambiguity threshold, confidence checks,
  typed clarification fields, and safe alternatives.
- Added live-catalog validation for proposed capability and operation IDs,
  availability, required entities, accepted inputs, freshness, and declared
  effect compatibility.
- Extended `RouteDecision` with a validated selection view while accepting both
  the legacy `CapabilityIntent` and the new capability-neutral `TaskIntent`.
- Kept historical V2 route values and fixed intent behavior as a compatibility
  fallback when no generic catalog evidence exists.
- Added a narrow execution-boundary projection from validated `TaskIntent` to
  the existing handler `CapabilityIntent`, so preparation, privacy, consent,
  action authorization, and provider execution remain unchanged.

## Selection behavior

Candidates are ranked by compatibility and availability, required inputs,
operation strength, freshness strength, domain specificity, and declared
priority. Registration order and capability ID are never used to select a
winner; semantic ties request clarification. Static-only operations are not
eligible for current/live requests, and unavailable candidates produce an
unavailable decision without execution.

## Compatibility boundary

This phase did not replace the historical `Route` enum or migrate persisted
route values. Phase 3 now supplies specialist routing contracts from manifests
and removes the composition-time role branch; the generic route and persistence
migration remain assigned to later phases.

## Verification

- Provider-free Phase 2 synthetic-capability, ambiguity, freshness,
  order-independence, unavailable-state, and invented-selection tests pass.
- Existing V2 routing, capability workflow, authorization, migration, and
  characterization suites pass.
- Python compilation and `git diff --check` pass.
