# Elly V2.5 Phase 1 — Intent and Catalog Contracts

> Final architecture note: conservative active-route compatibility described
> below was transitional and was removed before closure. See
> [LEGACY_ROUTING_REMOVAL.md](LEGACY_ROUTING_REMOVAL.md).

**Status:** Implemented  
**Baseline:** Closed V2 with Phase 0 characterization  
**Scope:** Typed routing metadata and immutable catalog only

## Delivered

- Added provider-free routing contract DTOs in
  `src/elly/application/routing_contracts.py`:
  freshness support/requirements, operation contracts, routing descriptors,
  capability-neutral task intents, candidate matches, and untrusted selection
  proposals.
- Extended `CapabilityDescriptor` with an additive optional routing descriptor.
- Added `CapabilityRegistry.routing_catalog()`, returning a fresh tuple sorted by
  capability ID and containing no executable collaborators.
- Added startup validation for duplicate operation declarations, unsupported
  input/entity vocabularies, invalid freshness values, bounded priorities and
  specificity, unsafe reason codes, descriptor/operation mismatches, and
  declared-action/effect inconsistencies.
- Added explicit routing metadata to the existing web-research and specialist
  adapters while retaining a conservative compatibility contract for older
  descriptors.

## Compatibility boundary

The existing V2 interpreter, route enum, routing policy, execution workflow,
provider calls, persistence, and public response behavior remain unchanged.
Generic matching, selection, route migration, manifest routing fields, and
specialist role-branch removal remain later-phase work.

## Verification

- Provider-free Phase 1 contract suite passes.
- Existing capability, routing, Phase 2/4 tests, and action-authorization tests
  pass.
- Full regression suite passes with 329 tests.
- Python compilation and `git diff --check` pass.
