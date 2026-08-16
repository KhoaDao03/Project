# Elly V2.5 Phase 5 — Route and Persistence Migration

**Status:** Implemented; finalized by the pre-closure routing refactor  
**Baseline:** Phase 4 web-research and freshness contracts

## Delivered

- Added `registered_capability` and `local_conversation` as the only route
  categories used for new work.
- Separated capability identity and operation from route category.
- Removed the fixed route-to-capability map and active capability-specific
  presentation.
- Added routing metadata to task results and public task/trace views:
  capability ID, operation, selection reason, route category, contract version,
  candidate count, rejection codes, clarification state, and freshness effect.
- Added additive schema migrations 5 and 6 without rewriting stored V2 rows.

## Historical data behavior

Rows created by V2 remain readable with their stored values such as
`web_research` or `coding_specialist`. Those values are historical data only.
New results, audits, CLI output, and API views use a generic route category and
separate capability identity. No compatibility view is generated for new work.

See [LEGACY_ROUTING_REMOVAL.md](LEGACY_ROUTING_REMOVAL.md) for the final cleanup
and verification record.
