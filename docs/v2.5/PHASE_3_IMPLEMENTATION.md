# Elly V2.5 Phase 3 — Manifest-Driven Specialists

> Final architecture note: manifest legacy-route views and direct-construction
> fallbacks described below were removed before closure. See
> [LEGACY_ROUTING_REMOVAL.md](LEGACY_ROUTING_REMOVAL.md).

**Status:** Implemented
**Baseline:** Phase 2 generic catalog interpretation and selection
**Scope:** Specialist manifest routing contracts, generic handler construction,
and V2 compatibility views

## Delivered

- Added immutable manifest routing metadata: bounded priority, typed operation
  contracts, required/optional entities, accepted inputs, freshness, examples,
  and counterexamples.
- Added a manifest-declared legacy route view solely for compatibility with the
  historical V2 `Route` enum. It is not an authorization or provider policy.
- Migrated coding and research manifests to declare `specialist.analyze`
  contracts and migrated `stock_analysis` to declare security, financial
  statement, valuation, and risk operations requiring a ticker or company.
- Made specialist descriptors expose the operations declared by their manifest.
  Preparation now validates the selected operation and its required entities
  generically, including `ticker_or_company` aliases.
- Changed composition to construct handlers from every valid manifest, including
  valid disabled manifests, without role- or specialist-ID route branches.
- Kept a narrow fallback contract for directly constructed legacy
  `SpecialistManifest` objects that do not yet carry routing metadata; loaded
  TOML manifests use the migrated declarations.

## Behavior and safety

An added valid manifest becomes a catalog candidate without Python changes. A
disabled valid manifest remains visible in the catalog with `DISABLED` status,
but selection returns an unavailable decision and cannot execute. Invalid
manifest routing declarations remain isolated as typed disabled diagnostics.
Manifest routing metadata describes selection scope only; cloud authorization,
consent, tools, actions, provider access, and specialist policy remain owned by
their existing application boundaries.

Stock valuation and financial-analysis requests now select `stock_analysis`
when a company or ticker is present. Web current/news/release/live-quote
contracts are added in [PHASE_4_IMPLEMENTATION.md](PHASE_4_IMPLEMENTATION.md).

## Verification

- Manifest parser and typed contract tests pass, including invalid declarations.
- Dynamic add/disable/remove tests pass using a temporary manifest and no
  central routing edits.
- Stock valuation selection, legacy coding/research behavior, authorization,
  and composition smoke tests pass.
- Full regression, compilation, diff checks, and available static checks are the
  completion gate for this phase.
